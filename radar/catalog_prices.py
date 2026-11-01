"""Supplemental public weekly aggregates; never parse landing-page sample charts."""
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .domain import recognize

CATEGORY_PAGES={"gpu":"gpu-graphics-cards","cpu":"cpu-processors","motherboard":"motherboards","ram":"ram-memory","storage":"nvme-ssd"}

def parse_catalog_prices(html,category,url):
    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text(" ",strip=True)
    if re.search(r"sample data|demo data|illustrative prices",text,re.I):
        raise ValueError("页面说明为示例数据，不导入")
    if not re.search(r"from verified eBay sold listings",text,re.I):
        raise ValueError("未找到成交来源声明")
    date=re.search(r"LAST REFRESH\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})",text,re.I)
    data_date=datetime.strptime(date[1],"%b %d, %Y").date().isoformat() if date else None
    rows=[]
    for item in soup.select(".modelIndexList li"):
        link=item.find("a");amount=item.find("b")
        if not link or not amount:continue
        m=re.fullmatch(r"\$([\d,]+(?:\.\d+)?)",amount.get_text(strip=True))
        if not m:continue
        label=re.sub(r"^Used\s+|\s+price$","",link.get_text(" ",strip=True),flags=re.I)
        parsed=recognize(label)
        model=parsed["model"] if parsed["category"]==category and parsed["model"] else label
        if category=="motherboard":model=label # retain socket and form factor
        if not model:continue
        mid=float(m[1].replace(",",""))
        rows.append({"category":category,"model":model,"low":round(mid*.75,2),"mid":mid,"high":round(mid*1.25,2),"currency":"USD",
                     "source":"Get PC Parts weekly","source_url":urljoin(url,link.get("href","")),"price_kind":"sold","market":"unknown","data_date":data_date,
                     "sample_count":None,"condition":"used","shipping_included":None,"confidence":"low",
                     "notes":f"美国商家公开目录美元报价，页面称来自 eBay 已售均价，每周更新；未独立核实成交样本、地区和运费。原标签：{label}。低高值按均价±25%规则展开，并非成交分位数；数据日期为来源公布的刷新日期，非单笔成交日期。"})
    if not rows:raise ValueError("未找到结构化型号价格目录")
    return rows
