import json
import hashlib
import sqlite3
import threading
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from .config import DATA, DEFAULT

def now():
    return datetime.now(timezone.utc).isoformat()

def dump(value):
    return json.dumps(value, ensure_ascii=False)

class Database:
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "radar.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS listings (
              id TEXT PRIMARY KEY, platform TEXT NOT NULL DEFAULT 'facebook', url TEXT NOT NULL,
              title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', raw_price TEXT NOT NULL DEFAULT '',
              price REAL, currency TEXT NOT NULL DEFAULT 'USD', location TEXT NOT NULL DEFAULT '',
              image TEXT, seller TEXT, condition TEXT, latitude REAL, longitude REAL,
              first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, fetched_at TEXT NOT NULL,
              details_at TEXT, review_decision TEXT NOT NULL DEFAULT 'pending', screening_result TEXT NOT NULL DEFAULT 'check',
              category TEXT NOT NULL DEFAULT 'unknown', model TEXT, valuation TEXT NOT NULL DEFAULT '{}',
              raw TEXT NOT NULL DEFAULT '{}', overrides TEXT NOT NULL DEFAULT '{}', is_test INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS hits (listing_id TEXT, keyword TEXT, seen_at TEXT, PRIMARY KEY(listing_id,keyword));
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, listing_id TEXT, action TEXT, old_value TEXT, new_value TEXT, source TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, listing_id TEXT, price REAL, description TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS references_prices (
              id INTEGER PRIMARY KEY, category TEXT NOT NULL, model TEXT NOT NULL, low REAL NOT NULL,
              mid REAL NOT NULL, high REAL NOT NULL, currency TEXT NOT NULL, source TEXT NOT NULL,
              source_url TEXT NOT NULL, price_kind TEXT NOT NULL, market TEXT NOT NULL,
              observed_at TEXT NOT NULL, data_date TEXT, sample_count INTEGER, condition TEXT NOT NULL,
              shipping_included INTEGER, confidence TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
              quarantined INTEGER NOT NULL DEFAULT 0, batch TEXT);
            CREATE INDEX IF NOT EXISTS price_model ON references_prices(category,model,observed_at);
            CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, model TEXT NOT NULL, category TEXT NOT NULL, source_url TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, kind TEXT, keyword TEXT, status TEXT, started_at TEXT, finished_at TEXT, count INTEGER DEFAULT 0, reason TEXT, metadata TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, listing_id TEXT, category TEXT, model TEXT, purchase REAL, repair REAL, resale REAL, mode TEXT, sold_at TEXT, notes TEXT);
            CREATE TABLE IF NOT EXISTS price_jobs (category TEXT, model TEXT, status TEXT DEFAULT 'pending', updated_at TEXT, PRIMARY KEY(category,model));
            CREATE TABLE IF NOT EXISTS availability_queue (listing_id TEXT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS removed_listing_keys (digest TEXT PRIMARY KEY);
            """)
            columns={row['name'] for row in c.execute('PRAGMA table_info(listings)')}
            if 'availability_status' not in columns:c.execute("ALTER TABLE listings ADD COLUMN availability_status TEXT NOT NULL DEFAULT 'unknown'")
            if 'availability_checked_at' not in columns:c.execute("ALTER TABLE listings ADD COLUMN availability_checked_at TEXT")
            c.execute("INSERT OR IGNORE INTO settings VALUES ('config',?)", (dump(DEFAULT),))

    @contextmanager
    def connect(self):
        with self.lock:
            c = sqlite3.connect(self.path, timeout=20)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def query(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as c:
            return c.execute(sql, args).lastrowid

    def setting(self, key, fallback=None):
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else fallback

    def set_setting(self, key, value):
        self.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, dump(value)))

    def get_listing(self, ident):
        rows = self.query("SELECT * FROM listings WHERE id=?", (ident,))
        if not rows:
            raise KeyError(ident)
        item = rows[0]
        for field in ("valuation", "raw", "overrides"):
            item[field] = json.loads(item[field])
        item["keywords"] = [r["keyword"] for r in self.query("SELECT keyword FROM hits WHERE listing_id=?", (ident,))]
        return item

    def upsert(self, item, keyword="", is_test=False):
        import re
        url = item.get("url", "").split("?")[0].rstrip("/") + "/"
        match = re.fullmatch(r"https://(?:www\.)?facebook\.com/marketplace/item/(\d+)/", url)
        if not match or not item.get("title", "").strip():
            raise ValueError("需要有效 Facebook 商品链接和标题")
        ident = match[1]
        stamp = now()
        with self.connect() as c:
            if c.execute('SELECT 1 FROM removed_listing_keys WHERE digest=?',(self.listing_digest(ident),)).fetchone():return None
            old = c.execute("SELECT * FROM listings WHERE id=?", (ident,)).fetchone()
            fields = ["title", "description", "raw_price", "price", "currency", "location", "image", "seller", "condition", "latitude", "longitude"]
            values = {k: item.get(k, old[k] if old else None) for k in fields}
            for k in ("description", "raw_price", "location"):
                values[k] = values[k] or ""
            values["currency"] = values["currency"] or "USD"
            details_at = stamp if item.get("detail_success") else (old["details_at"] if old else None)
            raw_merged = {**(json.loads(old["raw"]) if old else {}), **item}
            if old:
                if old["price"] != values["price"] or old["description"] != values["description"]:
                    c.execute("INSERT INTO snapshots(listing_id,price,description,created_at) VALUES (?,?,?,?)", (ident,old["price"],old["description"],stamp))
                assignments = ",".join(f"{k}=?" for k in fields)
                c.execute(f"UPDATE listings SET {assignments},url=?,last_seen=?,fetched_at=?,details_at=?,raw=? WHERE id=?", (*values.values(),url,stamp,stamp,details_at,dump(raw_merged),ident))
            else:
                c.execute(f"INSERT INTO listings(id,url,{','.join(fields)},first_seen,last_seen,fetched_at,details_at,raw,is_test) VALUES ({','.join('?' for _ in range(len(fields)+8))})", (ident,url,*values.values(),stamp,stamp,stamp,details_at,dump(item),int(is_test)))
            if keyword:
                c.execute("INSERT INTO hits VALUES (?,?,?) ON CONFLICT(listing_id,keyword) DO UPDATE SET seen_at=excluded.seen_at", (ident,keyword,stamp))
        return ident

    @staticmethod
    def listing_digest(ident):return hashlib.sha256(('facebook:'+ident).encode()).hexdigest()

    def delete_sold(self,c,ident):
        # Only a non-readable deduplication key remains; no deleted item/archive/audit row.
        c.execute('INSERT OR IGNORE INTO removed_listing_keys VALUES (?)',(self.listing_digest(ident),))
        for table in ('hits','audit','snapshots'):
            c.execute(f'DELETE FROM {table} WHERE listing_id=?',(ident,))
        # Independently entered accounting transactions are not listing history.
        c.execute('UPDATE sales SET listing_id=NULL WHERE listing_id=?',(ident,))
        c.execute('DELETE FROM listings WHERE id=?',(ident,))

    def decide(self, ident, decision):
        if decision not in {"pending", "keep", "reject"}:
            raise ValueError("无效审核决定")
        with self.connect() as c:
            old = c.execute("SELECT review_decision FROM listings WHERE id=?", (ident,)).fetchone()
            if not old:
                raise KeyError(ident)
            c.execute("UPDATE listings SET review_decision=? WHERE id=?", (decision,ident))
            c.execute("INSERT INTO audit(listing_id,action,old_value,new_value,source,created_at) VALUES (?,?,?,?,?,?)", (ident,"decision",old[0],decision,"user",now()))

    def backup(self):
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / (datetime.now(timezone.utc).strftime("radar-%Y%m%d-%H%M%S-%f") + ".sqlite3")
        with self.lock, closing(sqlite3.connect(self.path)) as src, closing(sqlite3.connect(target)) as dest:
            src.backup(dest)
            dest.commit()
        for old in sorted(folder.glob("radar-*.sqlite3"), reverse=True)[14:]:
            old.unlink()
        return target
