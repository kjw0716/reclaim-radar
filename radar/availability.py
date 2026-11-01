"""Daily inventory checks; only explicit, listing-bound sold evidence permits deletion."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from .db import dump, now

DEFAULT_SCHEDULE = {"enabled": True, "time": "09:00", "timezone": "America/Los_Angeles"}
SOLD = re.compile(r"^(?:sold(?: out)?|已售出|已卖出|已賣出|已售完|售罄|This (?:listing|item) (?:has been|is) sold[.!]?|此商品已售出[。！]?)$", re.I)
BOUNDARY = re.compile(r"^(?:Description|Details|Seller information|Related searches|Today's picks|Recommended|Similar listings|More like this|Sponsored|描述|說明|详细信息|詳細資料|卖家信息|賣家資訊|相关搜索|相關搜尋|今日精选|今日精選|推荐商品|相似商品|你可能也喜欢|猜你还喜欢)$", re.I)


def listing_availability(text, title):
    """Read the item's heading/status, never seller prose or recommendation cards."""
    normalize=lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if any(re.fullmatch(r"This (?:listing is no longer|content isn't) available[.!]?|此商品已不存在|此内容无法显示",line,re.I) for line in lines):return 'unknown'
    end=next((i for i,line in enumerate(lines) if BOUNDARY.fullmatch(line)),len(lines))
    lines=lines[:end]
    for line in lines:
        parts=re.split(r"\s+[·•]\s+",line,maxsplit=1)
        if len(parts)==2 and SOLD.fullmatch(parts[0]) and normalize(parts[1])==normalize(title):return 'sold'
    # Facebook renders the badge as `Sold\n \n · item title` in the current UI.
    heading=next((i for i,line in enumerate(lines) if normalize(re.sub(r'^[·•]\s*','',line))==normalize(title)),None)
    if heading is None:return "unknown"
    # Status badges occur next to the item title and price, before the description.
    nearby=lines[max(0,heading-3):heading]+lines[heading+1:heading+8]
    if any(SOLD.fullmatch(line) for line in nearby):return "sold"
    if any(re.fullmatch(r"Pending|待售确认|待售確認|待交易",line,re.I) for line in nearby):return "pending"
    if any(re.match(r"^(?:US\s*)?\$\s*[\d,]|^Free$|^免费$|^免費$",line,re.I) for line in nearby):return "available"
    return "unknown"


class AvailabilityScan:
    def __init__(self,db):
        self.db=db
        if db.setting("availability_schedule") is None:
            db.set_setting("availability_schedule",DEFAULT_SCHEDULE)

    def state(self):return self.db.setting("availability_scan") or {"status":"idle"}

    def start_due(self,local=None,force=False):
        local=local or datetime.now(ZoneInfo("America/Los_Angeles"))
        schedule=self.db.setting("availability_schedule")
        with self.db.connect() as c:
            row=c.execute("SELECT value FROM settings WHERE key='availability_scan'").fetchone()
            previous=json.loads(row[0]) if row else {}
            if previous.get("status") in {"running","attention"}:
                if force:
                    previous.update(status="running",message="")
                    self._save(c,previous)
                return previous
            date=local.date().isoformat()
            scheduled=c.execute("SELECT value FROM settings WHERE key='availability_last_scheduled_date'").fetchone()
            last_scheduled=json.loads(scheduled[0]) if scheduled else None
            if not force and (not schedule['enabled'] or local.strftime('%H:%M')<schedule['time'] or last_scheduled==date):
                return previous
            c.execute("DELETE FROM availability_queue")
            c.execute("INSERT INTO availability_queue(listing_id) SELECT id FROM listings WHERE is_test=0")
            total=c.execute("SELECT count(*) FROM availability_queue").fetchone()[0]
            state={"status":"running" if total else "completed","date":date,"trigger":"manual" if force else "scheduled","started_at":now(),"total":total,"checked":0,"deleted":0,"kept_sold":0,"unknown":0,"message":""}
            if not force:
                c.execute("INSERT INTO settings VALUES ('availability_last_scheduled_date',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dump(date),))
            if not total:state['finished_at']=now()
            self._save(c,state)
            return state

    def _save(self,c,state):
        c.execute("INSERT INTO settings VALUES ('availability_scan',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dump(state),))

    def next_item(self):
        rows=self.next_items(1)
        return rows[0] if rows else None

    def next_items(self,limit=3):
        return self.db.query("SELECT l.* FROM availability_queue q JOIN listings l ON l.id=q.listing_id ORDER BY l.first_seen,l.id LIMIT ?",(limit,))

    def record(self,ident,result):
        if result not in {'sold','available','pending','unknown'}:raise ValueError('Invalid availability')
        # The keep decision and deletion share one transaction: a newly kept item is protected.
        with self.db.connect() as c:
            state=json.loads(c.execute("SELECT value FROM settings WHERE key='availability_scan'").fetchone()[0])
            if not c.execute("SELECT 1 FROM availability_queue WHERE listing_id=?",(ident,)).fetchone():return state
            row=c.execute("SELECT review_decision,availability_status FROM listings WHERE id=?",(ident,)).fetchone()
            if row:
                if result=='sold' and row['review_decision']!='keep':
                    self.db.delete_sold(c,ident)
                    state['deleted']+=1
                else:
                    # An inaccessible page must not erase an earlier sold status on a kept item.
                    status=row['availability_status'] if result=='unknown' and row['availability_status']=='sold' else result
                    c.execute("UPDATE listings SET availability_status=?,availability_checked_at=? WHERE id=?",(status,now(),ident))
                    if result=='sold':state['kept_sold']+=1
                if result=='unknown':state['unknown']+=1
            c.execute("DELETE FROM availability_queue WHERE listing_id=?",(ident,))
            state['checked']+=1
            state['updated_at']=now()
            if not c.execute("SELECT 1 FROM availability_queue LIMIT 1").fetchone():
                state.update(status='completed',finished_at=now())
            self._save(c,state)
            return state

    def attention(self,message):
        state=self.state()
        state.update(status='attention',message=message)
        self.db.set_setting('availability_scan',state)

    def resume(self):
        state=self.state()
        if state.get('status')=='attention':
            state.update(status='running',message='')
            self.db.set_setting('availability_scan',state)
