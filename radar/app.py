import json
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .config import ROOT, CATEGORIES, DEFAULT
from .db import Database, dump, now
from .domain import evaluate, reevaluate_all, FALLBACK
from .collector import Collector, contaminated_description
from .prices import PriceService

log=logging.getLogger("radar")

class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)

class Decision(Strict):
    decision:Literal["pending","keep","reject"]

class Override(Strict):
    category: str | None = None
    model: str | None = None
    price: float | None = Field(default=None,ge=0,le=1_000_000)
    estimate_mid: float | None = Field(default=None,ge=0,le=1_000_000)
    latitude: float | None = Field(default=None,ge=-90,le=90)
    longitude: float | None = Field(default=None,ge=-180,le=180)
    title: str | None = Field(default=None,max_length=1000)
    description: str | None = Field(default=None,max_length=16000)

class Search(Strict):
    keyword:str=Field(default="gaming PC",min_length=1,max_length=120)
    max_price:float=Field(default=1500,ge=0,le=100000)

class Location(Strict):
    selected_label:str=Field(min_length=3,max_length=150)

class LocationPreferences(Strict):
    selected_label:str=Field(default="",max_length=150)
    radius_miles:int=Field(ge=1,le=100,strict=True)
    auto_restore:bool=True
    @field_validator("selected_label")
    @classmethod
    def trim_label(cls,v):
        v=v.strip()
        if v and len(v)<3:raise ValueError("地区名至少 3 个字符，或留空自动识别")
        return v

class AvailabilitySchedule(Strict):
    enabled:bool=True
    time:str=Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone:Literal['America/Los_Angeles']='America/Los_Angeles'

class Reference(Strict):
    category:str
    model:str=Field(min_length=1,max_length=150)
    low:float=Field(ge=0)
    mid:float=Field(ge=0)
    high:float=Field(ge=0)
    currency:Literal["USD"]="USD"
    source:str=Field(min_length=1,max_length=200)
    source_url:str=Field(min_length=10,max_length=1500)
    price_kind:Literal["sold","asking","manual","heuristic"]
    market:str=Field(max_length=80)
    data_date:str|None=None
    sample_count:int|None=Field(default=None,ge=0)
    condition:str="used"
    shipping_included:bool|None=None
    confidence:Literal["medium","low","very_low","manual"]="low"
    notes:str=Field(default="",max_length=16000)
    @field_validator("data_date")
    @classmethod
    def date_valid(cls,v):
        if v:datetime.fromisoformat(v.replace("Z","+00:00"))
        return v

class Evidence(Strict):
    references:list[Reference]=Field(max_length=200)

class Alias(Strict):
    alias:str=Field(min_length=2,max_length=150)
    model:str=Field(min_length=2,max_length=150)
    category:str
    source_url:str=Field(min_length=10,max_length=1500)

class Sale(Strict):
    listing_id:str|None=None
    category:str
    model:str=Field(min_length=1,max_length=150)
    purchase:float=Field(ge=0)
    repair:float=Field(default=0,ge=0)
    resale:float=Field(gt=0)
    mode:Literal["local","online"]="local"
    sold_at:str
    notes:str=Field(default="",max_length=4000)
    @field_validator("sold_at")
    @classmethod
    def date_valid(cls,v):
        datetime.fromisoformat(v.replace("Z","+00:00"));return v

def validate_config(value):
    if value.get("collection_scope") not in {"pc_only","hardware"}:raise ValueError("无效采集范围")
    if set(value)!=set(DEFAULT):raise ValueError("配置字段不完整或包含未知字段")
    if not isinstance(value["postal_code"],str) or not re.fullmatch(r"[0-9]{5}",value["postal_code"]):raise ValueError("Enter a five-digit US ZIP code")
    if not isinstance(value["center_method"],str) or not 1<=len(value["center_method"].strip())<=300:raise ValueError("Describe the source of the center coordinates")
    if value["timezone"]!="America/Los_Angeles":raise ValueError("首版使用洛杉矶时区")
    bounds={"radius_miles":(1,100),"interval_minutes":(10,1440),"max_cards":(1,200),"max_details":(0,30),"term_timeout_seconds":(30,600),"target_profit":(0,100000),"center_lat":(-90,90),"center_lon":(-180,180)}
    import math
    for k,(lo,hi) in bounds.items():
        if isinstance(value[k],bool) or not isinstance(value[k],(int,float)) or not math.isfinite(value[k]) or not lo<=value[k]<=hi:raise ValueError(f"{k} 范围 {lo}–{hi}")
    for k in ("radius_miles","interval_minutes","max_cards","max_details","term_timeout_seconds"):
        if not isinstance(value[k],int):raise ValueError(f"{k} 必须为整数")
    if not isinstance(value["auto_monitor"],bool):raise ValueError("auto_monitor 必须为布尔值")
    if value["mode"] not in {"local","online"}:raise ValueError("无效转售方式")
    if set(value["costs"])!=set(DEFAULT["costs"]):raise ValueError("成本字段不完整")
    for k,v in value["costs"].items():
        nullable=k in {"shipping","pickup","repair","consumables","time"}
        if v is None and nullable:continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>100000:raise ValueError("成本必须为有限非负数；未配置项使用 null")
        if "percent" in k and v>100:raise ValueError("费用百分比不能超过100")
    if not isinstance(value["search_groups"],list) or not 1<=len(value["search_groups"])<=30:raise ValueError("搜索组数量 1–30")
    for group in value["search_groups"]:
        if set(group)!={"category","keywords","max_price"} or group["category"] not in FALLBACK:raise ValueError("无效搜索组")
        if value["collection_scope"]=="pc_only" and group["category"]!="pc":raise ValueError("只收 PC 主机时不能启用独立零件搜索组")
        if not isinstance(group["keywords"],list) or not 1<=len(group["keywords"])<=30 or any(not isinstance(x,str) or not 1<=len(x.strip())<=120 for x in group["keywords"]):raise ValueError("无效关键词")
        if not isinstance(group["max_price"],(int,float)) or not math.isfinite(group["max_price"]) or not 0<=group["max_price"]<=100000:raise ValueError("无效价格上限")
    return value

def create_app(database=None,background=True):
    db=database or Database()
    config=db.setting("config")
    if "collection_scope" not in config:
        config["collection_scope"]="hardware"
        db.set_setting("config",config)
    collector=Collector(db)
    prices=PriceService(db)
    shutdown=threading.Event()
    scheduler_state={"status":"idle"}

    def daily_scheduler():
        while not shutdown.wait(10):
            try:
                local=datetime.now(ZoneInfo("America/Los_Angeles"))
                date=local.date().isoformat()
                if local.hour>=7 and db.setting("price_attempt_date")!=date and not prices.lock.locked():
                    db.set_setting("price_attempt_date",date)
                    threading.Thread(target=prices.refresh,name="daily-prices",daemon=True).start()
                elif not prices.lock.locked() and db.setting('price_recheck_requested'):
                    db.set_setting('price_recheck_requested',None)
                    threading.Thread(target=lambda:prices.refresh(discovered_only=True),name='recheck-listing-prices',daemon=True).start()
                elif not prices.lock.locked() and db.query("SELECT 1 FROM price_jobs WHERE status='pending' LIMIT 1"):
                    threading.Thread(target=lambda:prices.refresh(jobs_only=True),name="new-model-prices",daemon=True).start()
                if db.setting("backup_date")!=date:
                    db.backup();db.set_setting("backup_date",date)
                scheduler_state.update(status="running",checked_at=now())
            except Exception as e:
                scheduler_state.update(status="error",message=str(e));log.exception("Scheduler failed")

    @asynccontextmanager
    async def lifespan(app):
        if background:
            db.execute("UPDATE runs SET status='interrupted',finished_at=?,reason='服务重启，中断的任务不作为零结果或成功更新' WHERE status='running'",(now(),))
            collector.start()
            threading.Thread(target=daily_scheduler,name="radar-scheduler",daemon=True).start()
            if (db.setting("location_confirmation") or db.setting("location_selection") or db.setting("browser_profile")) and db.setting("config")["auto_monitor"] and db.setting("location_auto_restore") and not db.setting("collector_paused",False):
                collector.submit("verify")
        yield
        shutdown.set();collector.stop_event.set()
        if background:collector.thread.join(timeout=6)

    app=FastAPI(title="Reclaim Radar / 回收雷达",version="0.2.0",lifespan=lifespan)
    app.state.db=db;app.state.collector=collector;app.state.prices=prices;app.state.shutdown=shutdown

    @app.middleware("http")
    async def local_only(request:Request,call_next):
        host=request.headers.get("host","").split(":")[0]
        if host not in {"127.0.0.1","localhost","testserver"}:return JSONResponse({"detail":"仅供本机访问"},status_code=403)
        origin=request.headers.get("origin")
        if request.method not in {"GET","HEAD","OPTIONS"}:
            if origin and origin not in {"http://127.0.0.1:8765","http://localhost:8765","http://127.0.0.1:5173","http://localhost:5173"}:return JSONResponse({"detail":"拒绝跨站写入"},status_code=403)
        result=await call_next(request)
        result.headers["X-Content-Type-Options"]="nosniff"
        return result

    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse({"detail":"记录不存在"},status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({"detail":str(exc)},status_code=400)

    @app.get("/api/health")
    def health():return {"app":"reclaim-radar","version":"0.2.0","pid":os.getpid(),"status":"ok","data_directory":str(db.directory)}

    @app.get("/api/status")
    def status():
        stats=db.query("SELECT category,json_extract(valuation,'$.reference.method') AS method,count(*) AS count FROM listings WHERE is_test=0 GROUP BY category,method")
        return {"collector":collector.state,"prices":prices.state,"scheduler":scheduler_state,"location":db.setting("location_confirmation"),"location_preferences":location_preferences(),
                "availability":{"schedule":db.setting('availability_schedule'),"scan":collector.availability.state(),"paused":collector.paused},
                "last_search":db.query("SELECT * FROM runs WHERE kind='search' ORDER BY id DESC LIMIT 1"),
                "last_completed_search":db.query("SELECT * FROM runs WHERE kind='search' AND status IN ('success','partial') ORDER BY id DESC LIMIT 1"),"price_last_success":db.setting("price_last_success"),
                "last_ingest":db.query("SELECT max(fetched_at) AS time FROM listings WHERE is_test=0")[0]["time"],"coverage":stats,
                "totals":db.query("SELECT review_decision,screening_result,count(*) AS count FROM listings WHERE is_test=0 GROUP BY review_decision,screening_result"),
                "reference_count":db.query("SELECT count(*) AS count FROM references_prices WHERE quarantined=0")[0]["count"],
                "priced_model_count":db.query("SELECT count(*) AS count FROM (SELECT DISTINCT category,upper(replace(model,' ','')) FROM references_prices WHERE quarantined=0)")[0]["count"],
                "price_category_coverage":db.query("SELECT category,count(DISTINCT upper(replace(model,' ',''))) AS models FROM references_prices WHERE quarantined=0 GROUP BY category"),
                "missing_models":db.query("SELECT * FROM price_jobs WHERE status IN ('pending','failed') LIMIT 100"),"shs_catalog_count":len(db.setting("shs_catalog",[])),
                "pcwatch_catalog_count":len(db.setting("pcwatch_catalog",[])),"catalog_bootstrap":db.setting("catalog_bootstrap_attempt")}

    @app.get("/api/config")
    def config():return {"config":db.setting("config"),"categories":CATEGORIES}
    @app.put("/api/config")
    def config_save(value:dict):
        validate_config(value)
        old=db.setting("config")
        if old["postal_code"]!=value["postal_code"] and (old["center_lat"],old["center_lon"])==(value["center_lat"],value["center_lon"]):
            raise ValueError("Update the center coordinates when changing the ZIP code")
        with collector.location_lock:
            db.set_setting("config",value)
            if any(old[k]!=value[k] for k in ("postal_code","radius_miles","center_lat","center_lon")):
                db.set_setting("location_confirmation",None)
                if old["postal_code"]!=value["postal_code"]:db.set_setting("location_selection",None)
                collector.state.update(location_confirmed=False,status="needs_location",message="新位置偏好已保存，点击自动恢复应用到 Facebook")
        reevaluate_all(db)
        return {"saved":True}

    @app.put('/api/collector/availability-schedule')
    def availability_schedule(body:AvailabilitySchedule):
        db.set_setting('availability_schedule',body.model_dump())
        return {'saved':True,'schedule':body.model_dump()}

    @app.post('/api/collector/check-sold')
    def check_sold():
        if not db.setting('availability_schedule')['enabled']:
            raise ValueError('请先启用每日售出检查')
        return collector.submit('check_sold')

    @app.get("/api/listings")
    def listings(view:str="pending",category:str="",q:str="",sort:str="newest",order:str="desc",min_price:float|None=None,max_price:float|None=None,min_profit:float|None=None,distance_filter:str="all",limit:int=100,offset:int=0):
        where=["is_test=0"];args=[]
        if view in {"keep","reject"}:where.append("review_decision=?");args.append(view)
        elif view=="excluded":where.append("review_decision='pending' AND screening_result='excluded'")
        elif view=="price_review":where.append("review_decision='pending' AND screening_result='price_review'")
        elif view=="pending":where.append("review_decision='pending' AND screening_result NOT IN ('excluded','price_review')")
        elif view!="all":raise ValueError("无效列表")
        if view in {"pending","price_review","keep","reject"}:
            where.append("json_extract(valuation,'$.scope_allowed')=1")
        if category:
            cats=category.split(",");where.append("category IN ("+",".join("?" for _ in cats)+")");args+=cats
        if q:where.append("(title LIKE ? OR description LIKE ?)");args += [f"%{q}%",f"%{q}%"]
        if min_price is not None:where.append("price>=?");args.append(min_price)
        if max_price is not None:where.append("price<=?");args.append(max_price)
        if min_profit is not None:where.append("json_extract(valuation,'$.expected_profit')>=?");args.append(min_profit)
        dist="json_extract(valuation,'$.distance.miles')"
        certainty="json_extract(valuation,'$.distance.confidence')"
        if distance_filter=="known":where.append(f"{certainty}='coordinate' AND {dist}<=?");args.append(db.setting("config")["radius_miles"])
        elif distance_filter=="unknown":where.append(f"coalesce({certainty},'unknown')!='coordinate'")
        elif distance_filter=="outside":where.append(f"{certainty}='coordinate' AND {dist}>?");args.append(db.setting("config")["radius_miles"])
        elif distance_filter!="all":raise ValueError("无效距离筛选")
        sort_expr={"newest":"first_seen","price":"price","profit":"json_extract(valuation,'$.expected_profit')","distance":dist}.get(sort)
        if not sort_expr or order not in {"asc","desc"}:raise ValueError("无效排序")
        clause=" AND ".join(where)
        ids=db.query(f"SELECT id FROM listings WHERE {clause} ORDER BY ({sort_expr} IS NULL),{sort_expr} {order},id LIMIT ? OFFSET ?",(*args,min(200,max(1,limit)),max(0,offset)))
        total=db.query(f"SELECT count(*) AS count FROM listings WHERE {clause}",args)[0]["count"]
        return {"items":[db.get_listing(x["id"]) for x in ids],"total":total}
    @app.get("/api/listings/{ident}")
    def listing(ident:str):return db.get_listing(ident)
    @app.post("/api/listings/{ident}/decision")
    def decide(ident:str,body:Decision):db.decide(ident,body.decision);return db.get_listing(ident)
    @app.put("/api/listings/{ident}/overrides")
    def override(ident:str,body:Override):
        item=db.get_listing(ident);data=body.model_dump(exclude_unset=True)
        if data.get("category") and data["category"] not in CATEGORIES:raise ValueError("无效类别")
        # Null explicitly removes an override rather than turning the original value null.
        old=item["overrides"];new={**old}
        for k,v in data.items():
            if v is None:new.pop(k,None)
            else:new[k]=v
        with db.connect() as c:
            c.execute("UPDATE listings SET overrides=? WHERE id=?",(dump(new),ident))
            c.execute("INSERT INTO audit(listing_id,action,old_value,new_value,source,created_at) VALUES (?,'overrides',?,?, 'user',?)",(ident,dump(old),dump(new),now()))
        evaluate(db,ident);return db.get_listing(ident)
    @app.get("/api/listings/{ident}/history")
    def history(ident:str):return {"audit":db.query("SELECT * FROM audit WHERE listing_id=? ORDER BY id DESC",(ident,)),"snapshots":db.query("SELECT * FROM snapshots WHERE listing_id=? ORDER BY id DESC",(ident,))}

    @app.post("/api/collector/connect")
    def connect():return collector.submit("connect")
    @app.post("/api/collector/repair-descriptions")
    def repair_descriptions():
        backup=str(db.backup());fixed=[]
        with db.connect() as c:
            for row in c.execute("SELECT id,description,raw FROM listings WHERE description!=''").fetchall():
                if not contaminated_description(row['description']):continue
                raw=json.loads(row['raw']);raw['description']='';raw['detail_success']=False;raw['description_status']='contamination_cleared'
                c.execute("INSERT INTO audit(listing_id,action,old_value,new_value,source,created_at) VALUES (?,'description_repair',?,'','parser',?)",(row['id'],row['description'],now()))
                c.execute("UPDATE listings SET description='',details_at=NULL,raw=? WHERE id=?",(dump(raw),row['id']))
                fixed.append(row['id'])
        reevaluate_all(db)
        return {"fixed":fixed,"backup":backup}
    @app.post("/api/collector/detail/{listing_id}")
    def refresh_detail(listing_id:str):
        db.get_listing(listing_id)
        return collector.submit("detail",listing_id=listing_id)
    @app.post("/api/collector/recover-login")
    def recover_login():return collector.submit("recover_login")
    @app.post("/api/collector/location")
    def location():return collector.submit("location")

    @app.get("/api/collector/location-preferences")
    def location_preferences():
        config=db.setting("config")
        saved=db.setting("location_selection") or {}
        return {"postal_code":config["postal_code"],"radius_miles":config["radius_miles"],
                "selected_label":saved.get("selected",""),"auto_restore":db.setting("location_auto_restore",True),
                "saved_at":saved.get("selected_at"),"last_check":db.setting("location_check")}

    @app.put("/api/collector/location-preferences")
    def save_location_preferences(body:LocationPreferences):
        with collector.location_lock:
            config=db.setting("config")
            config["radius_miles"]=body.radius_miles
            validate_config(config)
            saved=db.setting("location_selection") or {}
            if body.selected_label!=saved.get("selected",""):
                saved={"postal_code":config["postal_code"],"selected":body.selected_label,"selected_at":now(),"method":"user_attested_postal_selection"} if body.selected_label else None
            db.set_setting("config",config)
            db.set_setting("location_selection",saved)
            db.set_setting("location_auto_restore",body.auto_restore)
            db.set_setting("location_confirmation",None)
            collector.state.update(status="needs_location",location_confirmed=False,message="位置偏好已保存，点击自动恢复即可应用；重启后仍会保留。")
        reevaluate_all(db)
        return {"saved":True,**location_preferences()}

    @app.delete("/api/collector/location-preferences")
    def delete_location_preferences():
        with collector.location_lock:
            for key in ("location_selection","location_confirmation","location_check"):db.set_setting(key,None)
            db.set_setting("location_auto_restore",False)
            collector.paused=True
            db.set_setting("collector_paused",True)
            collector.state.update(status="paused",location_confirmed=False,location=None,message="位置记忆已删除，自动恢复已关闭。搜索中心与半径仍可在设置中修改。")
        return {"deleted":True}

    @app.post("/api/collector/selected-location")
    def selected(body:Location):
        with collector.location_lock:
            db.set_setting("location_selection",{"postal_code":db.setting("config")["postal_code"],"selected":body.selected_label.strip(),"selected_at":now(),"method":"user_attested_postal_selection"})
            db.set_setting("location_auto_restore",True)
            collector.state["location_confirmed"]=False
        return collector.submit("verify")
    @app.post("/api/collector/verify")
    def verify():return collector.submit("verify")
    @app.post("/api/collector/pause")
    def pause():
        collector.paused=True
        db.set_setting("collector_paused",True)
        collector.state.update(status="paused",message="采集已暂停，位置偏好仍然保留")
        return {"paused":True}
    @app.post("/api/collector/search")
    def search(body:Search):return collector.submit("search",**body.model_dump())

    @app.get("/api/prices")
    def references(q:str="",category:str="",limit:int=100,offset:int=0,history:bool=False):
        where=[];args=[]
        if q:where.append("model LIKE ?");args.append("%"+q+"%")
        if category:where.append("category=?");args.append(category)
        table="references_prices" if history else "(SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY category,upper(replace(model,' ','')),source,price_kind ORDER BY id DESC) AS rn FROM references_prices) WHERE rn=1)"
        base=f" FROM {table}"+(" WHERE "+" AND ".join(where) if where else "")
        query="SELECT *"+base+" ORDER BY category,model,source,price_kind LIMIT ? OFFSET ?"
        return {"items":db.query(query,(*args,min(300,max(1,limit)),max(0,offset))),"total":db.query("SELECT count(*) AS count"+base,args)[0]["count"],"fx":db.setting("eur_usd"),"bootstrap_rules":FALLBACK}
    @app.post("/api/prices/refresh")
    def refresh(full_catalog:bool=False):
        if prices.lock.locked():return {"status":"busy"}
        threading.Thread(target=lambda:prices.refresh(full_catalog=full_catalog),name="manual-prices",daemon=True).start();return {"queued":True}
    @app.post("/api/prices/recheck-listings")
    def recheck_listings():
        backup=str(db.backup());reevaluate_all(db)
        if prices.lock.locked():
            db.set_setting('price_recheck_requested',now())
            return {"queued":True,"waiting_for_current_update":True,"backup":backup}
        threading.Thread(target=lambda:prices.refresh(discovered_only=True),name="recheck-listing-prices",daemon=True).start()
        return {"queued":True,"backup":backup}
    @app.post("/api/prices/import")
    def import_evidence(body:Evidence):
        ids=[]
        with db.connect() as connection:
            for r in body.references:
                if r.category not in FALLBACK or not r.low<=r.mid<=r.high or not r.source_url.startswith(("https://","http://127.0.0.1:")):raise ValueError("无效证据项")
            for r in body.references:ids.append(prices.import_reference(r.model_dump(),"manual-evidence",connection=connection))
        reevaluate_all(db);return {"imported":len(ids),"ids":ids}
    @app.post("/api/aliases")
    def alias(body:Alias):
        if body.category not in FALLBACK or not body.source_url.startswith("https://"):raise ValueError("别名需要类别和来源")
        db.execute("INSERT INTO aliases VALUES (?,?,?,?) ON CONFLICT(alias) DO UPDATE SET model=excluded.model,category=excluded.category,source_url=excluded.source_url",(body.alias,body.model,body.category,body.source_url))
        reevaluate_all(db);return {"saved":True}
    @app.post("/api/sales")
    def sale(body:Sale):
        if body.category not in FALLBACK:raise ValueError("无效类别")
        ident=db.execute("INSERT INTO sales(listing_id,category,model,purchase,repair,resale,mode,sold_at,notes) VALUES (?,?,?,?,?,?,?,?,?)",tuple(body.model_dump().values()))
        prices.import_reference({"category":body.category,"model":body.model,"low":body.resale,"mid":body.resale,"high":body.resale,"currency":"USD","source":"用户本地成交记录","source_url":f"http://127.0.0.1:8765/api/sales/{ident}","price_kind":"sold","market":"US","data_date":body.sold_at,"sample_count":1,"confidence":"medium","notes":"用户录入；单次成交不能代表整个市场；"+body.notes})
        reevaluate_all(db);return {"id":ident}
    @app.get("/api/sales/{ident}")
    def sale_get(ident:int):
        rows=db.query("SELECT * FROM sales WHERE id=?",(ident,))
        if not rows:raise KeyError(ident)
        return rows[0]
    @app.get("/api/runs")
    def runs():return db.query("SELECT * FROM runs ORDER BY id DESC LIMIT 100")
    @app.get("/api/research")
    def research():return {"pricing_review":db.query("SELECT id,title,price,category,model,valuation FROM listings WHERE is_test=0 AND screening_result='price_review' ORDER BY last_seen DESC LIMIT 100"),"cross_check_policy":"优先核查待核价商品及其组件；尽量查两个独立交易平台或可靠公开价格依据。同上游 eBay 不算独立来源，历史标价和 sold out 不冒充成交。通过证据接口导入，保留人工基准与审核决定。", "missing_models":db.query("SELECT * FROM price_jobs WHERE status IN ('pending','failed')"),"unknown_items":db.query("SELECT id,title,description,category,model FROM listings WHERE is_test=0 AND (model IS NULL OR category='unknown') LIMIT 100"),"source_errors":db.query("SELECT * FROM runs WHERE kind='prices' AND status!='success' ORDER BY id DESC LIMIT 3"),"aliases":db.query("SELECT * FROM aliases"),"prices":prices.state}
    @app.post("/api/backup")
    def backup():return {"path":str(db.backup())}
    @app.post("/api/shutdown")
    def stop():shutdown.set();return {"stopping":True}

    dist=ROOT/"frontend"/"dist"
    if (dist/"assets").exists():app.mount("/assets",StaticFiles(directory=dist/"assets"),name="assets")
    if (dist/"demo").exists():app.mount("/demo",StaticFiles(directory=dist/"demo"),name="demo-artwork")
    @app.get("/favicon.svg",include_in_schema=False)
    def favicon():
        if (dist/"favicon.svg").exists():return FileResponse(dist/"favicon.svg",media_type="image/svg+xml")
        raise HTTPException(status_code=404,detail="Favicon not built")
    @app.get("/")
    def home():
        if (dist/"index.html").exists():return FileResponse(dist/"index.html")
        return JSONResponse({"detail":"请运行安装.cmd 构建前端"},status_code=503)
    return app
