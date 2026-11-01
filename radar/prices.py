import json
import logging
import math
import re
import statistics
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote
import httpx
from bs4 import BeautifulSoup
from .db import dump, now
from .domain import normalize_model, recognize, reevaluate_all
from .catalog_prices import CATEGORY_PAGES, parse_catalog_prices

log = logging.getLogger("radar.prices")
BOOTSTRAP = [("gpu","RTX 3070"),("cpu","Ryzen 5600X"),("gpu","RTX 3060"),("gpu","RTX 3080"),("cpu","Ryzen 3600"),("cpu","i7-12700K"),
             ("motherboard","B550"),("motherboard","B650"),("ram","DDR4 16GB"),("ram","DDR5 32GB"),("storage","NVMe SSD 1TB"),("storage","HDD 2TB"),
             ("psu","Corsair RM650"),("cooler","CPU air cooler"),("case","PC case"),("pc","gaming PC"),("bundle","computer parts bundle")]

def pcwatch_key(model, category):
    compact=normalize_model(model)
    if category=="cpu":
        m=re.search(r"I([3579])(\d{4,5}[A-Z]*)",compact)
        if m:return f"CORE_I{m[1]}_{m[2]}"
        if compact.startswith("RYZEN"):
            m=re.search(r"\d{4}[A-Z0-9]*",compact)
            if m:
                n=m[0];tier="9" if n[1:4] in {"950","900"} else "7" if n[1:4] in {"800","700"} else "5"
                return f"RYZEN_{tier}_{n}"
    if category=="ram":
        m=re.search(r"(DDR[345])(\d+)GB",compact)
        if m:return f"{m[1]}_{m[2]}GB_1X{m[2]}"
    if category=="psu":
        return "PSU_"+re.sub(r"[^A-Z0-9]+","_",model.upper()).strip("_")
    if category=="gpu" and compact.startswith("ARC"):
        return "ARC_"+compact[3:]
    return compact

def objects_from_jsonld(html):
    soup=BeautifulSoup(html,"html.parser")
    result=[]
    def walk(obj):
        if isinstance(obj,list):
            for x in obj:walk(x)
        elif isinstance(obj,dict):
            result.append(obj)
            if "@graph" in obj:walk(obj["@graph"])
    for s in soup.select('script[type="application/ld+json"]'):
        try:walk(json.loads(s.string or s.get_text()))
        except (ValueError,TypeError):pass
    return result

def shs_slug(model, category):
    if category=="gpu":
        brand="amd" if model.upper().startswith("RX") else "intel" if model.lower().startswith("arc") else "nvidia"
        return brand+"-"+re.sub(r"[^a-z0-9]+","-",model.lower()).strip("-")
    if model.lower().startswith("ryzen"):
        # The site's product paths include product tier, which is not intrinsic to all titles.
        n=re.search(r"\d{4}",model)
        tier="9" if n and n[0][1:] in {"950","900"} else "7" if n and n[0][1:] in {"800","700"} else "5" if n and n[0][1:] in {"600","500"} else "3"
        return "amd-ryzen-"+tier+"-"+re.sub(r"^ryzen\s*[3579]?\s*(?=\d{4})","",model.lower())
    return "intel-core-"+re.sub(r"^core\s*","",model.lower()).replace(" ","-")

def parse_shs(html, model, category, url):
    product = next((x for x in objects_from_jsonld(html) if x.get("@type")=="Product"),None)
    if not product:
        raise ValueError("未找到商品结构化数据（不使用网站免费订阅价 $0）")
    parsed=recognize(product.get("name",""))
    if parsed["model"] and normalize_model(parsed["model"]) != normalize_model(model):
        raise ValueError("来源型号与查询不一致")
    offer=product.get("offers",{})
    m=re.search(r"averages\s+\$([\d,.]+)",product.get("description",""),re.I)
    if not m or offer.get("priceCurrency")!="USD":
        raise ValueError("无法确认美元二手均价")
    mid=float(m[1].replace(",",""))
    # Source low/high includes outliers and historical span; retain, do not claim percentiles.
    return {"category":category,"model":model,"low":float(offer.get("lowPrice",mid*.75)),"mid":mid,"high":float(offer.get("highPrice",mid*1.25)),
            "currency":"USD","source":"Second Hand Silicon","source_url":url,"price_kind":"sold","market":"unknown",
            "data_date":product.get("dateModified"),"sample_count":int(offer["offerCount"]) if offer.get("offerCount") else None,
            "condition":"used","shipping_included":None,"confidence":"low",
            "notes":"公开页称 eBay 成交均价；未提供交易日期窗口、地区和运费口径；低高值非分位数。"}

def parse_pcwatch(html, model, category, url, fx):
    objs=objects_from_jsonld(html)
    product=next((x for x in objs if x.get("@type")=="Product"),None)
    if not product:
        raise ValueError("未找到 PCPrice 商品数据")
    offer=product.get("offers",{})
    if offer.get("priceCurrency")!="EUR":
        raise ValueError("PCPrice 原币种变化，暂停解析")
    candidates=[]
    for obj in objs:
        if obj.get("@type")=="FAQPage":
            for q in obj.get("mainEntity",[]):
                t=q.get("acceptedAnswer",{}).get("text","")
                m=re.search(r"(?:global median sold price is|median used .*? sold for)\s*€([\d,.]+)",t,re.I)
                if m:
                    candidates.append((float(m[1].replace(",","")),t))
    result=[]
    if candidates:
        mid,text=candidates[0]
        count=re.search(r"from ([\d,]+) recent sales",text)
        result.append({"low":mid*.8*fx["rate"],"mid":mid*fx["rate"],"high":mid*1.2*fx["rate"],"price_kind":"sold","market":"global", "sample_count":int(count[1].replace(",","")) if count else None,
                       "notes":f"全球成交中位数 EUR {mid}；区间按±20%规则展开，并非成交分位数；EUR/USD={fx['rate']} ({fx['date']})。"})
    if offer.get("lowPrice") and offer.get("highPrice"):
        lo,hi=float(offer["lowPrice"]),float(offer["highPrice"])
        result.append({"low":lo*fx["rate"],"mid":(lo+hi)/2*fx["rate"],"high":hi*fx["rate"],"price_kind":"asking","market":"ships_to_US", "sample_count":int(offer.get("offerCount",0)) or None,
                       "notes":f"原始在售价 EUR {lo}–{hi}；中值为区间中点，非成交均价；EUR/USD={fx['rate']} ({fx['date']})。"})
    if not result:
        raise ValueError("无可解析参考")
    for r in result:
        r.update({"category":category,"model":model,"currency":"USD","source":"PCPrice.watch","source_url":url,"data_date":product.get("dateModified"),"condition":"used","shipping_included":None,"confidence":"low"})
    return result

def parse_ebay(html, model, category, url):
    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text(" ",strip=True)
    if re.search(r"verify.*human|pardon our interruption|security measure|captcha",text,re.I):
        raise PermissionError("eBay 要求验证，暂停来源")
    values=[];evidence=[]
    for card in soup.select("li.s-item, li.s-card"):
        title_el=card.select_one(".s-item__title, .s-card__title")
        price_el=card.select_one(".s-item__price, .s-card__price")
        link=card.select_one("a.s-item__link, a.s-card__link")
        if not title_el or not price_el or not link:continue
        title=title_el.get_text(" ",strip=True)
        if re.search(r"for parts|broken|not working|lot of|water ?block|box only|cooler only",title,re.I):continue
        if category in {"cpu","gpu","motherboard"} and normalize_model(model) not in normalize_model(title):continue
        recognized=recognize(title)
        if recognized["category"] != category and category not in {"bundle","pc"}:continue
        raw=price_el.get_text(" ",strip=True)
        if " to " in raw:continue
        match=re.search(r"\$([\d,]+(?:\.\d{2})?)",raw)
        if match:
            value=float(match[1].replace(",",""))
            if value>1:values.append(value);evidence.append({"title":title,"price":value,"url":link.get("href","").split("?")[0]})
    if len(values)<3:
        raise ValueError("有效同类美元样本少于3个；可能页面布局变化或无结果")
    med=statistics.median(values)
    clean=[v for v in values if med*.2<=v<=med*3]
    clean.sort()
    return {"category":category,"model":model,"low":clean[int((len(clean)-1)*.25)],"mid":statistics.median(clean),"high":clean[int((len(clean)-1)*.75)],
            "currency":"USD","source":"eBay public sold search","source_url":url,"price_kind":"sold","market":"US","data_date":None,
            "sample_count":len(clean),"condition":"used","shipping_included":False,"confidence":"medium",
            "notes":dump({"warning":"公开已售搜索展示价格，接受议价的真实成交金额可能隐藏；交易日期未逐条确认；不含运费。","samples":evidence[:20]})}

class PriceService:
    def __init__(self,db):
        self.db=db
        self.lock=threading.Lock()
        self.state={"status":"idle","message":"等待更新价格","last_success":db.setting("price_last_success")}
        self.blocked=set()
        self.client=httpx.Client(timeout=25,follow_redirects=True,headers={"User-Agent":"ReclaimRadar/0.1 (local price research)"})

    def fetch(self,url):
        response=self.client.get(url)
        if response.status_code in (403,429):raise PermissionError(f"来源 HTTP {response.status_code}，本轮暂停")
        response.raise_for_status()
        return response.text

    def import_reference(self,r,batch=None,connection=None):
        fields=["category","model","low","mid","high","currency","source","source_url","price_kind","market","observed_at","data_date","sample_count","condition","shipping_included","confidence","notes","quarantined","batch"]
        r={"observed_at":now(),"data_date":None,"sample_count":None,"condition":"used","shipping_included":None,"confidence":"low","notes":"","quarantined":0,"batch":batch,**r}
        from .config import CATEGORIES
        if r["category"] not in CATEGORIES or r["category"] in {"unknown","mac"}:raise ValueError("无效参考类别")
        if r["currency"] != "USD":raise ValueError("导入前必须明确换算 USD，并在备注保留原币种和汇率日期")
        if r["price_kind"] not in {"sold","asking","manual","heuristic"}:raise ValueError("无效价格口径")
        nums=[float(r[k]) for k in ("low","mid","high")]
        if not all(math.isfinite(x) and 0<=x<=1_000_000 for x in nums) or not nums[0]<=nums[1]<=nums[2]:raise ValueError("估值需为有限非负数，low ≤ mid ≤ high")
        if not r["source_url"].startswith(("https://","http://127.0.0.1:")):raise ValueError("需要可追溯来源链接")
        sql="SELECT mid FROM references_prices WHERE category=? AND model=? AND source=? AND quarantined=0 ORDER BY id DESC LIMIT 1"
        args=(r["category"],r["model"],r["source"])
        previous=list(connection.execute(sql,args)) if connection else self.db.query(sql,args)
        if nums[1]<=0 or (previous and previous[0]["mid"]>0 and not .3<=nums[1]/previous[0]["mid"]<=3):
            r["quarantined"]=1;r["notes"]+=" 价格异常，已隔离等待人工核对。"
        sql=f"INSERT INTO references_prices({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})"
        args=tuple(r[k] for k in fields)
        return connection.execute(sql,args).lastrowid if connection else self.db.execute(sql,args)

    def fx(self):
        obj=json.loads(self.fetch("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD"))
        if not .5 < obj["rates"]["USD"] < 2:raise ValueError("异常 EUR/USD 汇率")
        self.db.set_setting("eur_usd",{"rate":obj["rates"]["USD"],"date":obj["date"]})
        return self.db.setting("eur_usd")

    def refresh(self, jobs_only=False, full_catalog=False, discovered_only=False):
        if not self.lock.acquire(blocking=False):return {"status":"busy"}
        rid=self.db.execute("INSERT INTO runs(kind,status,started_at) VALUES ('prices','running',?)",(now(),))
        self.state={"status":"running","message":"正在更新多来源价格库","last_success":self.db.setting("price_last_success")}
        successes=0;errors=[];self.blocked=set()
        try:
            if not jobs_only:
                for category,slug in CATEGORY_PAGES.items():
                    url="https://www.getpcparts.com/market-prices/"+slug
                    try:
                        for ref in parse_catalog_prices(self.fetch(url),category,url):
                            self.import_reference(ref,str(rid));successes+=1
                    except PermissionError as e:
                        errors.append(f"Get PC Parts: {e}");break
                    except Exception as e:errors.append(f"Get PC Parts/{category}: {str(e)[:180]}")
                    time.sleep(.4)
            jobs=[(r["category"],r["model"]) for r in self.db.query("SELECT * FROM price_jobs WHERE status='pending' ORDER BY updated_at LIMIT 20")]
            if discovered_only:
                jobs=[]
                for row in self.db.query("SELECT valuation FROM listings WHERE is_test=0"):
                    val=json.loads(row['valuation'])
                    if not val.get('scope_allowed'):continue
                    entries=val.get('parts',[])+([val] if val.get('model') else [])
                    for entry in entries:
                        if entry.get('model') and entry.get('category') in {'gpu','cpu','ram','motherboard','storage','psu'}:
                            jobs.append((entry['category'],entry['model']))
                jobs=list(dict.fromkeys(jobs))
            if not jobs_only and not discovered_only:
                tracked=[(r["category"],r["model"]) for r in self.db.query("SELECT DISTINCT category,model FROM references_prices WHERE model!='*' AND source!='Get PC Parts weekly'")]
                jobs=list(dict.fromkeys(jobs+tracked+BOOTSTRAP))
                # Discover the actual catalog, not only the handful of popular homepage models.
                try:
                    catalog=self.db.setting("shs_catalog",[])
                    if not catalog:
                        xml=self.fetch("https://www.secondhandsilicon.com/sitemap.xml")
                        slugs=re.findall(r"https?://(?:www\.)?secondhandsilicon\.com/product/([^<\s]+)",xml)
                        for slug in dict.fromkeys(slugs):
                            category="gpu" if any(p in slug for p in ("rtx","gtx","radeon","rx-","arc-")) else "cpu" if any(p in slug for p in ("ryzen","core","xeon")) else None
                            model=re.sub(r"^(nvidia-|amd-|intel-)","",slug).replace("-"," ")
                            parsed=recognize(model)
                            if category and parsed["model"]:catalog.append({"category":category,"model":parsed["model"],"slug":slug})
                        # Interleave processors and GPUs so a newly installed catalog does
                        # not spend its first week refreshing only GPU generations.
                        gpus=[x for x in catalog if x["category"]=="gpu"]
                        cpus=[x for x in catalog if x["category"]=="cpu"]
                        catalog=[]
                        for i in range(max(len(gpus),len(cpus))):
                            if i<len(gpus):catalog.append(gpus[i])
                            if i<len(cpus):catalog.append(cpus[i])
                        self.db.set_setting("shs_catalog",catalog)
                    cursor=self.db.setting("catalog_cursor",0)
                    chunk=catalog if full_catalog else catalog[cursor:cursor+30]
                    jobs=list(dict.fromkeys(jobs+[(x["category"],x["model"]) for x in chunk]))
                    self.db.set_setting("catalog_cursor",0 if cursor+30>=len(catalog) else cursor+30)
                except Exception as e:errors.append(f"目录发现: {e}")
                try:
                    pc_catalog=self.db.setting("pcwatch_catalog",[])
                    if not pc_catalog:
                        html=self.fetch("https://www.pcprice.watch/search")
                        keys=list(dict.fromkeys(re.findall(r'href="/search/([A-Z0-9_]+)"',html)))
                        for key in keys:
                            display=key.replace("_"," ")
                            if key.startswith("PSU_"):category="psu";model=display[4:].title()
                            elif key.startswith("DDR"):category="ram";model=display
                            elif re.fullmatch(r"[ABHXZ]\d{3}E?",key):category="motherboard";model=key
                            elif key.startswith(("CORE_","RYZEN_")):
                                category="cpu";model=recognize(display)["model"]
                            elif key.startswith(("RTX","GTX","RX","ARC_")):
                                category="gpu";model=recognize(display)["model"]
                            else:continue
                            if model:pc_catalog.append({"key":key,"model":model,"category":category})
                        self.db.set_setting("pcwatch_catalog",pc_catalog)
                    if full_catalog:
                        jobs=list(dict.fromkeys(jobs+[(x["category"],x["model"]) for x in pc_catalog]))
                except Exception as e:errors.append(f"PCPrice目录发现: {e}")
            else:
                pc_catalog=self.db.setting("pcwatch_catalog",[])
            fx=None
            for job_index,(category,model) in enumerate(jobs):
                self.state.update(message=f"查询 {model}（{job_index+1}/{len(jobs)}，已导入 {successes} 条）",processed=job_index,total=len(jobs),current_model=model)
                found=0
                sources=[]
                if category in {"cpu","gpu"}:
                    slug=next((x["slug"] for x in self.db.setting("shs_catalog",[]) if normalize_model(x["model"])==normalize_model(model)),shs_slug(model,category))
                    sources.append(("shs","https://www.secondhandsilicon.com/product/"+slug))
                compact=next((x["key"] for x in pc_catalog if x["category"]==category and normalize_model(x["model"])==normalize_model(model)),pcwatch_key(model,category))
                type_map={"gpu":"GPU","cpu":"CPU","ram":"RAM","motherboard":"MOTHERBOARD","psu":"PSU"}
                if category in type_map:
                    sources.append(("pcwatch",f"https://www.pcprice.watch/search/{compact}/US/{type_map[category]}"))
                # Cross-check every model; don't stop after the first usable website.
                sources.append(("ebay","https://www.ebay.com/sch/i.html?_nkw="+quote(model)+"&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000&LH_PrefLoc=1&_ipg=60"))
                for source,url in sources:
                    if source in self.blocked:continue
                    try:
                        html=self.fetch(url)
                        if source=="shs":refs=[parse_shs(html,model,category,url)]
                        elif source=="pcwatch":
                            fx=fx or self.fx();refs=parse_pcwatch(html,model,category,url,fx)
                        else:refs=[parse_ebay(html,model,category,url)]
                        for r in refs:
                            self.import_reference(r,str(rid));successes+=1;found+=1
                    except PermissionError as e:
                        self.blocked.add(source);errors.append(f"{source}: {e}")
                    except Exception as e:errors.append(f"{source}/{model}: {str(e)[:180]}")
                    time.sleep(.4)
                self.db.execute("INSERT INTO price_jobs VALUES (?,?,?,?) ON CONFLICT(category,model) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at",(category,model,"done" if found else "failed",now()))
                if discovered_only and (job_index+1)%10==0:reevaluate_all(self.db)
            reevaluate_all(self.db)
            status="success" if successes and not errors else "partial" if successes else "failed"
            self.db.execute("UPDATE runs SET status=?,finished_at=?,count=?,reason=?,metadata=? WHERE id=?",(status,now(),successes,"; ".join(errors)[:12000],dump({"jobs":len(jobs),"errors":errors}),rid))
            self.db.set_setting("price_last_attempt",now())
            if successes:self.db.set_setting("price_last_success",now())
            if full_catalog:
                self.db.set_setting("catalog_bootstrap_attempt",{"finished_at":now(),"jobs":len(jobs),"imported":successes,"errors":len(errors)})
            self.state={"status":status,"message":f"导入 {successes} 条参考；{len(errors)} 个来源/型号问题", "last_success":self.db.setting("price_last_success")}
            return {**self.state,"errors":errors}
        except Exception as e:
            log.exception("Price refresh failed")
            self.db.execute("UPDATE runs SET status='failed',finished_at=?,reason=? WHERE id=?",(now(),str(e),rid))
            self.state["status"]="failed";self.state["message"]=str(e)
            self.db.set_setting("price_last_attempt",now())
            return self.state
        finally:self.lock.release()
