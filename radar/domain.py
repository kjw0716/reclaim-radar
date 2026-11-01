"""Explainable hardware recognition and conservative valuation; no model API calls."""
import math
import re
import statistics
from urllib.parse import urlparse
from datetime import datetime, timezone
from .db import dump, now

RULE_VERSION = "2026-10-03.4-component-specs"
# Explicit bootstrap heuristics, not asserted current market observations.
# Each is replaceable by observed category/specification data as the catalog grows.
FALLBACK = {
    "pc": (30, 180, 500), "gpu": (15, 80, 250), "cpu": (5, 40, 130),
    "motherboard": (10, 40, 120), "ram": (5, 20, 65), "storage": (5, 20, 65),
    "psu": (5, 25, 65), "cooler": (3, 15, 50), "case": (0, 15, 50), "bundle": (5, 40, 150)
}
PATTERNS = {
    "gpu": r"\b(?:RTX|GTX|RX|Arc)\s*[- ]?\s*(?:[AB]\s*)?\d{3,4}(?:\s*(?:TI\s*SUPER|SUPER|TI|XTX|XT))?\b",
    "cpu": r"\b(?:Ryzen\s*[3579]?\s*\d{4}[A-Z0-9]*|(?:Core\s*)?i[3579]\s*[- ]\s*\d{4,5}[A-Z]*|Core\s+Ultra\s+[579]\s+\d{3}[A-Z]*)\b",
    "motherboard": r"\b[ABHXZ]\d{3}(?:[A-Z])?\b",
    "ram": r"\bDDR[345]\b",
    "storage": r"\b(?:NVMe|SSD|HDD)\b",
    "psu": r"\b\d{3,4}\s*W(?:ATT)?\b",
}

def normalize_model(s):
    return re.sub(r"[\s_-]+", "", s).upper()

def price_parse(raw):
    t = raw.strip().lower()
    if t in {"free", "免费", "免費", "$0", "$0.00"}:
        return 0.0, "free"
    if not t:
        return None, "unknown"
    if re.search(r"negotiable|obo|contact|议价|面议|trade|wanted|\d\s*[-–]\s*\$?\d", t):
        return None, "negotiable_or_range"
    m = re.search(r"(?:US\s*)?\$\s*([\d,]+(?:\.\d{1,2})?)", t)
    if not m:
        return None, "unknown"
    value = float(m[1].replace(",", ""))
    if value <= 1:
        return value, "placeholder"
    return value, "fixed"

def recognize(title, description="", aliases=()):
    t, d = title.lower(), description.lower()
    text = title + " " + description
    unsupported=bool(re.search(r"\b(?:meta quest|oculus|vr headset|playstation|nintendo|xbox|iphone|galaxy s\d+|rice cooker|gift\s*card|headphones?|headset|gaming monitor|mouse|keyboard|speakers?|printer|computer desk|computer table|desk workstation|steering wheel|trackpad|space heater|discs only|office chair)\b",t) and not re.search(r"\b(?:gaming pc|gaming computer|desktop (?:computer|pc)|computer tower|mini pc|workstation pc|pc bundle)\b",t))
    # Exclude the object for sale, rather than every mention of Apple compatibility.
    if re.search(r"\b(macbook|imac|mac\s*mini|mac\s*pro|apple\s*m[1-9])\b", t) and not re.search(r"compatible|works with|支持|兼容", t):
        category = "mac"
    elif re.search(r"(?:macbook|imac|mac mini|mac pro).*(?:logic board|battery|screen)|(?:logic board|battery|screen).*macbook", t):
        category = "mac"
    elif re.search(r"\b(lot|bundle|combo|components|parts lot)\b|零件包|组合", t):
        category = "bundle"
    elif re.search(r"\b(coolers?|heatsink|waterblock|water block|radiator|cooling|fans?)\b|散热|风扇", t):
        category = "cooler"
    elif re.search(r"\b(power supply|psu)\b|电源", t):
        category = "psu"
    elif re.search(r"\b(motherboard|mainboard|mobo)\b|主板", t):
        category = "motherboard"
    elif re.search(r"\b(ram|ddr[345]|memory kit)\b|内存", t) and not re.search(r"\b(pc|computer|desktop|tower)\b", t):
        category = "ram"
    elif re.search(r"\b(ssd|hdd|nvme|hard drive|solid state)\b|硬盘", t) and not re.search(r"\b(pc|computer|desktop|tower)\b", t):
        category = "storage"
    elif re.search(r"\b(pc case|computer case|chassis|empty case)\b|机箱", t):
        category = "case"
    elif re.search(r"\b(pc|desktop|computer|tower|workstation|barebones|optiplex|elite ?desk|thinkcentre)\b|整机|电脑", t):
        category = "pc"
    elif re.search(PATTERNS["gpu"], title, re.I) or re.search(r"\b(gpu|graphics card|video card)\b|显卡", t):
        category = "gpu"
    elif re.search(PATTERNS["cpu"], title, re.I) or re.search(r"\b(cpu|processor)\b|处理器", t):
        category = "cpu"
    else:
        category = "unknown"
    from .scope import hardware_admission
    _,_,object_category=hardware_admission(title,description)
    if object_category and category!="mac":category=object_category
    components = []
    for kind, pattern in PATTERNS.items():
        for m in re.finditer(pattern, text, re.I):
            model = m[0].strip()
            if kind == "cpu" and model.lower().startswith("ryzen"):
                model = re.sub(r"^Ryzen\s+[3579]\s+(?=\d{4})", "Ryzen ", model, flags=re.I)
            if kind == "gpu":
                model = re.sub(r"^(RTX|GTX|RX|Arc)\s*[- ]?\s*", r"\1 ", model, flags=re.I)
                # Models sold with materially different VRAM variants must not share a price key.
                vram=re.match(r"\s*(?:[-(]\s*)?(\d{1,2})\s*GB\b",text[m.end():],re.I)
                if normalize_model(model) in {"RTX3060","RTX3080"} and vram:
                    model += " " + vram[1] + "GB"
            key = (kind, normalize_model(model))
            if not any((c["category"], normalize_model(c["model"])) == key for c in components):
                components.append({"category": kind, "model": model})
    for a in aliases:
        if re.search(r"(?<!\w)" + re.escape(a["alias"]) + r"(?!\w)", text, re.I):
            components = [x for x in components if x["category"] != a["category"]]
            components.append({"category": a["category"], "model": a["model"]})
    if category in {"pc","bundle"}:
        components=component_specs(text,components)
    model = next((x["model"] for x in components if x["category"] == category), None)
    specs = {}
    for name, pat in {"capacity": r"\b(\d+(?:\.\d+)?)\s*(GB|TB)\b", "ddr": r"\bDDR[345]\b", "power": r"\b\d{3,4}\s*W\b", "socket": r"\b(?:AM[345]|LGA\s*\d{4})\b"}.items():
        matches = list(re.finditer(pat, text, re.I))
        if matches:
            specs[name] = [m[0].upper() for m in matches]
    risks = []
    if re.search(r"\b(broken|not working|for parts|faulty|dead|untested|no test|as is)\b|故障|未测试|不开机", t + " " + d):
        risks.append("故障或未测试，按风险折价")
    if re.search(r"\b(no gpu|without gpu|no ram|no cpu|missing|barebones|no ssd|no hard drive)\b|缺件", t + " " + d):
        risks.append("缺件，不能按完整电脑估价")
    if re.search(r"\b(mining|mined|corrosion|bent pin|liquid damage)\b|矿卡|进水", t + " " + d):
        risks.append("矿用、进水或损伤风险")
    if category in {"ram","storage"}:
        capacity = " ".join(specs.get("capacity",[])[:1])
        title_capacity=re.search(r"\b(\d+(?:\.\d+)?)\s*(GB|TB)\b",title,re.I)
        if title_capacity:capacity=title_capacity[0].upper()
        # Use title capacity before description capacity; a kit is count × module size.
        kit=re.search(r"\b(\d+)\s*[x×]\s*(\d+)\s*GB",title,re.I)
        if not kit and not title_capacity:kit=re.search(r"\b(\d+)\s*[x×]\s*(\d+)\s*GB",description,re.I)
        if category=="ram" and kit:capacity=f"{int(kit[1])*int(kit[2])}GB"
        if category == "ram" and model and capacity:
            model=model.upper()+" "+capacity.replace(" ","")
            specs["capacity"]=[capacity]
        elif category == "storage" and capacity:
            kind="NVMe SSD" if "nvme" in text.lower() else "HDD" if re.search(r"hdd|hard drive",text,re.I) else "SSD"
            model=kind+" "+capacity.replace(" ","")
    if category=="psu":
        branded=re.search(r"\b(?:Corsair\s+(?:RM|CX|HX|AX|SF|TX)\d{3,4}[A-Z]*|Seasonic\s+Focus\s+GX\s*[- ]?\d{3,4}|EVGA\s+Supernova\s+\d{3,4}\s+[A-Z0-9]+)\b",text,re.I)
        if branded:model=branded[0]
    return {"category": category, "model": model, "components": components, "specs": specs, "risks": risks,"unsupported":unsupported}

def component_specs(text,components):
    """Attach a component's own capacity, never the whole PC's first GB value."""
    result=[]
    memory=re.search(r"\b(\d+)\s*GB\s+(?:[\w-]+\s+){0,4}(?:DDR[345]|RAM)\b",text,re.I)
    if not memory:memory=re.search(r"\b(?:RAM|RAM Capacity|内存容量)\s*[:：]?\s*(\d+)\s*GB",text,re.I)
    storage=[]
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(GB|TB)\s*(NVMe(?:\s+SSD)?|SSD|HDD)\b|\b(NVMe(?:\s+SSD)?|SSD|HDD)\s*(\d+(?:\.\d+)?)\s*(GB|TB)\b",text,re.I):
        size,unit,kind=(match[1],match[2],match[3]) if match[1] else (match[5],match[6],match[4])
        kind='NVMe SSD' if kind.lower().startswith('nvme') else kind.upper()
        model=f'{kind} {size}{unit.upper()}'
        if model not in storage:storage.append(model)
    storage=[model for model in storage if not (model.startswith('SSD ') and 'NVMe '+model in storage)]
    for comp in components:
        comp=dict(comp)
        if comp['category']=='ram' and memory:
            capacity=memory[1]+'GB';comp.update(model=comp['model']+' '+capacity,specs={'capacity':[capacity]})
        if comp['category']=='storage' and storage:continue
        result.append(comp)
    for model in storage:
        capacity=re.search(r'\d+(?:\.\d+)?(?:GB|TB)',model)[0]
        result.append({'category':'storage','model':model,'specs':{'capacity':[capacity]}})
    # Only include explicitly listed chassis/cooling, not assumed components.
    for kind,pattern,model in [('case',r'(?im)^.*\b(?:case|chassis)\b.*$','PC case'),('cooler',r'(?im)^.*\b(?:cpu cooler|cpu cooling)\b.*$','CPU cooler')]:
        if re.search(pattern,text) and not any(c['category']==kind for c in result):result.append({'category':kind,'model':model})
    return result

def distance(item, config):
    from .geography import city_point
    coordinate=item.get("latitude") is not None and item.get("longitude") is not None
    city=None if coordinate else city_point(item.get("location"))
    if coordinate or city:
        target=item if coordinate else city
        lat1,lon1,lat2,lon2 = map(math.radians, [config["center_lat"],config["center_lon"],target["latitude"],target["longitude"]])
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        miles = 3958.8 * 2 * math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))
        if city:return {"miles":round(miles,1),"method":"城市代表点粗估，范围仍待确认（GeoNames，CC BY 4.0）","confidence":"city","source_url":f"https://www.geonames.org/{city['id']}/","city":city["name"]}
        return {"miles": round(miles,1), "method": "坐标直线距离（中心为邮编区域近似点）", "confidence": "coordinate"}
    return {"miles": None, "method": "只有地点文字，范围待确认", "confidence": "unknown"}

def age_days(date):
    if not date:
        return None
    try:
        dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc)-dt).days)
    except (ValueError, TypeError):
        return None

def reference(db, category, model, specs=None):
    rows = db.query("SELECT * FROM references_prices WHERE category=? AND quarantined=0 AND currency='USD' ORDER BY observed_at DESC,id DESC", (category,))
    if model:
        exact = [r for r in rows if normalize_model(r["model"]) == normalize_model(model)]
        # Prefer dated US sold evidence, then undated aggregator evidence, then asking references.
        exact.sort(key=lambda r: (r["price_kind"] == "manual" and r["confidence"] == "manual", r["market"] == "US" and r["price_kind"] == "sold", r["price_kind"] == "sold", -(age_days(r["data_date"] or r["observed_at"]) or 0)), reverse=True)
        if exact:
            r = exact[0]
            latest={}
            for e in exact:latest.setdefault((e['source'],e['price_kind']),e)
            evidence=list(latest.values())
            manual=r['price_kind']=='manual' and r['confidence']=='manual'
            comparable=[e for e in evidence if e['price_kind']==r['price_kind'] and e['market']==r['market']]
            by_market={}
            for e in comparable:by_market.setdefault(evidence_market(e),e)
            mid=r['mid'] if manual else statistics.median(e['mid'] for e in by_market.values())
            markets={evidence_market(e) for e in evidence if e['price_kind']=='sold'}
            verified=manual or (len(markets)>=2 and len(by_market)>=2 and r['price_kind']=='sold' and r['market']=='US' and all(e['data_date'] and (age_days(e['data_date']) or 0)<=90 and e.get('sample_count',0) and e['sample_count']>=3 for e in by_market.values()))
            return {"low":r["low"],"mid":mid,"high":r["high"],"method":"exact", "confidence":r["confidence"], "evidence":evidence,
                    "price_verification":{"verified":verified,"websites":len({urlparse(e['source_url']).hostname for e in evidence}),"sold_markets":len(markets),"status":"manual" if manual else "cross_checked" if verified else "needs_check","notes":"人工基准优先" if manual else "成交与在售价分开；同上游市场不重复计票，日期或美国样本不足时待核价"}}
        # Only compare identifiable same-generation GPU/CPU families, not all category prices.
        digits = re.search(r"\d{3,5}", model)
        prefix = re.sub(r"\d.*", "", normalize_model(model))
        if digits and category in {"cpu","gpu","motherboard"}:
            family=prefix+digits[0] if category=='motherboard' else prefix+digits[0][:1]
            peers = [r for r in rows if r["model"] != "*" and normalize_model(r["model"]).startswith(family)]
            unique = {}
            for r in peers:
                unique.setdefault(normalize_model(r["model"]), r)
            peers = list(unique.values())[:12]
            if peers:
                mids = sorted(r["mid"] for r in peers)
                return {"low":min(r["low"] for r in peers)*.65, "mid":mids[len(mids)//2], "high":max(r["high"] for r in peers), "method":"peer", "confidence":"low", "evidence":peers}
    # Category anchors are explicit '*', not an unfiltered median of unrelated hardware.
    anchors = [r for r in rows if r["model"] == "*"]
    if anchors:
        r=anchors[0]
        return {"low":r["low"],"mid":r["mid"],"high":r["high"],"method":"category", "confidence":"low", "evidence":[r]}
    if category in FALLBACK:
        low,mid,high = FALLBACK[category]
        if category == "ram" and specs:
            cap = re.search(r"(\d+)\s*GB", " ".join(specs.get("capacity",[])))
            if cap:
                factor = max(.25,min(8,int(cap[1])/16))
                low,mid,high = [x*factor for x in (low,mid,high)]
        if category == "storage" and specs:
            cap = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", " ".join(specs.get("capacity",[])))
            if cap:
                size = float(cap[1])*(1000 if cap[2] == "TB" else 1)
                factor = max(.2,min(8,size/512))
                low,mid,high = [x*factor for x in (low,mid,high)]
        return {"low":low,"mid":mid,"high":high,"method":"heuristic", "confidence":"very_low", "evidence":[], "notes":"初始类别规则粗估，非实时成交价；优先人工核对"}
    return None

def evidence_market(e):
    text=(e['source']+' '+e.get('notes','')+' '+e['source_url']).lower()
    if 'ebay' in text or 'secondhandsilicon' in text or 'getpcparts' in text:return 'ebay'
    return urlparse(e['source_url']).hostname or e['source']

def evaluate(db, ident):
    item = db.get_listing(ident)
    config = db.setting("config")
    overrides = item["overrides"]
    info = recognize(overrides.get("title",item["title"]), overrides.get("description",item["description"]), db.query("SELECT * FROM aliases"))
    for key in ("category","model"):
        if key in overrides:
            info[key] = overrides[key]
    working = {**item, **{k:v for k,v in overrides.items() if k in {"latitude","longitude","price"}}}
    from .scope import hardware_admission
    admitted,scope_reason,admitted_category=hardware_admission(overrides.get("title",item["title"]),overrides.get("description",item["description"]),config.get("collection_scope","hardware"))
    if admitted_category and "category" not in overrides:
        info["category"]=admitted_category
        if admitted_category=="pc":info["model"]=None
    dist = distance(working,config)
    parsed,price_type = price_parse(item["raw_price"])
    if "price" in overrides:
        price_type = "manual"
    risk = info["risks"]
    ref = reference(db,info["category"],info["model"],info["specs"])
    parts = []
    if info["category"] in {"pc","bundle"}:
        for comp in info["components"]:
            # Explicit missing parts are not added just because mentioned in the text.
            name = "gpu" if comp["category"] == "gpu" else comp["category"]
            if re.search(r"\b(?:no|without|missing)\s+"+name+r"\b", item["title"]+" "+item["description"],re.I):
                continue
            r=reference(db,comp["category"],comp["model"],comp.get('specs',{}))
            if r:
                parts.append({**comp, "estimate":r})
    if "estimate_mid" in overrides:
        value = overrides["estimate_mid"]
        ref = {"low": value*.8,"mid":value,"high":value*1.2,"method":"manual","confidence":"manual","evidence":[],"notes":"用户手动估值"}
    if info["category"] == "mac":
        ref=None
    if ref:
        ref = dict(ref)
        # Component sums are displayed separately; never add them to whole-PC value.
        if parts and info["category"] == "pc" and ref["method"] == "heuristic":
            sums = {k:sum(p["estimate"][k] for p in parts) for k in ("low","mid","high")}
            ref.update({"low":sums["low"]*.8, "mid":sums["mid"], "high":sums["high"]*1.1, "method":"components", "confidence":"low", "evidence":[e for p in parts for e in p["estimate"]["evidence"]], "notes":"按各零件单个基准价合计计算利润；规则粗估另行标注，仅计入明确存在的组件"})
        factor = .35 if risk else 1
        for k in ("low","mid","high"):
            ref[k] = round(ref[k]*factor,2)
        costs = config["costs"]
        mode = config["mode"]
        percent = costs["local_fee_percent"] if mode == "local" else costs["online_fee_percent"]
        keys = ["pickup","repair","consumables","time"] + (["shipping"] if mode == "online" else [])
        missing = [k for k in keys if costs[k] is None]
        risk_cost = costs["risk_high"] if risk else costs["risk_normal"]
        fixed = sum(costs[k] or 0 for k in keys) + risk_cost
        channel_ref = ref
        if mode == "online" and parts:
            channel_ref = {k:sum(p["estimate"][k] for p in parts)*factor for k in ("low","mid","high")}
        net = {k:round(channel_ref[k]*(1-percent/100)-fixed,2) for k in ("low","mid","high")}
        price = working["price"]
        valid_price = price is not None and price_type not in {"placeholder","negotiable_or_range","unknown"} and item["currency"] == "USD"
        profits = {k:round(net[k]-price,2) if valid_price else None for k in net}
        point_based=bool(info["model"]) or ref["method"] in {"manual","components"}
        offer = round(max(0,net["mid" if point_based else "low"]-config["target_profit"]),2)
    else:
        missing=[];profits={k:None for k in ("low","mid","high")};offer=None;valid_price=False;point_based=False
    expected_profit=profits["mid"] if point_based else profits["low"]
    calculation=None
    if ref and valid_price:
        basis='mid' if point_based else 'low'
        calculation={'resale':round(channel_ref[basis],2),'purchase':price,'deductions':round(channel_ref[basis]-net[basis],2),'profit':expected_profit}
    verification=(ref or {}).get('price_verification',{'verified':False,'status':'needs_check','websites':0,'sold_markets':0,'notes':'粗估或同规格参考待核对'})
    if ref and ref['method']=='manual':verification={**verification,'verified':True,'status':'manual'}
    if ref and ref['method']=='components':
        verified=all(p['estimate'].get('price_verification',{}).get('verified',False) for p in parts)
        verification={**verification,'verified':verified,'status':'cross_checked' if verified else 'needs_check','notes':'各组件均需有效基准；容量规格粗估或单来源不能直接据此排除整机'}
    reasons = list(risk)
    if not admitted:
        screening="excluded";reasons.append(scope_reason)
    elif info["category"] == "mac":
        screening="excluded";reasons.append("Mac 商品不在搜索范围")
    elif info["unsupported"]:
        screening="excluded";reasons.append("明确为游戏机、VR、手机或其他非目标商品")
    elif dist["confidence"]=="coordinate" and dist["miles"] > config["radius_miles"]:
        screening="excluded";reasons.append("已知直线距离超过范围")
    elif expected_profit is not None and expected_profit < config["target_profit"]:
        basis="型号基准预计" if point_based else "粗估保守"
        screening="excluded" if verification['verified'] else "price_review"
        reasons.append(f"按{basis}利润 ${expected_profit:.2f}，低于目标 ${config['target_profit']:.2f}"+('，不划算' if verification['verified'] else '；价格依据未充分交叉核对，先待核价，不判定不划算'))
    elif profits["high"] is not None and profits["high"] < config["target_profit"]:
        screening="excluded";reasons.append("即使按粗估上限，利润仍低于目标，不划算")
    elif dist["confidence"]!="coordinate" or not valid_price or not ref or ref["confidence"] in {"low","very_low"} or missing:
        screening="check";reasons.append("地点、价格、估值依据或成本需确认")
    else:
        screening="recommended"
    val = {**info, "reference":ref, "parts":parts, "distance":dist, "profits":profits, "max_offer":offer,
           "scope_allowed":admitted,"scope_reason":scope_reason,
           "point_based":point_based,"resale_estimate":ref["mid"] if ref else None,"expected_profit":expected_profit,
           "price_verification":verification,
           "calculation":calculation,
           "price_type":price_type,"missing_costs":missing,"mode":config["mode"],"reasons":reasons,
           "rule_version":RULE_VERSION,"calculated_at":now(),"costs":config["costs"],"target_profit":config["target_profit"]}
    db.execute("UPDATE listings SET category=?,model=?,screening_result=?,valuation=? WHERE id=?",(info["category"],info["model"],screening,dump(val),ident))
    for comp in ([{"category":info["category"],"model":info["model"]}] if info["model"] else []) + info["components"]:
        if comp["category"] in FALLBACK and comp["model"]:
            db.execute("INSERT OR IGNORE INTO price_jobs(category,model,updated_at) VALUES (?,?,?)",(comp["category"],comp["model"],now()))
    return val

def reevaluate_all(db):
    for item in db.query("SELECT id FROM listings"):
        evaluate(db,item["id"])
