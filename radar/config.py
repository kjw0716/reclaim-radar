from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("RADAR_DATA_DIR", str(ROOT / ".data")))
CATEGORIES = {"pc": "整机", "gpu": "显卡", "cpu": "CPU", "motherboard": "主板", "ram": "内存", "storage": "SSD / HDD", "psu": "电源", "cooler": "散热", "case": "机箱", "bundle": "零件包", "unknown": "待识别", "mac": "Mac（排除）"}
DEFAULT = {
    "collection_scope":"hardware",
    "postal_code": "92121", "radius_miles": 20, "timezone": "America/Los_Angeles",
    "center_lat": 32.899, "center_lon": -117.202, "center_method": "92121 邮编区域近似中心（非住宅地址）",
    "interval_minutes": 30, "max_cards": 60, "max_details": 10, "term_timeout_seconds": 180,
    "auto_monitor": True, "mode": "local", "target_profit": 20,
    "costs": {"local_fee_percent": 0, "online_fee_percent": 13.25, "shipping": None,
              "pickup": None, "repair": None, "consumables": None, "time": None,
              "risk_normal": 15, "risk_medium": 30, "risk_high": 55},
    "search_groups": [
        {"category": "pc", "keywords": ["gaming PC", "desktop computer", "computer tower", "barebones PC", "gaming PC no GPU"], "max_price": 1500},
        {"category": "gpu", "keywords": ["graphics card", "RTX GPU", "Radeon GPU", "GPU for parts"], "max_price": 1500},
        {"category": "cpu", "keywords": ["CPU processor", "Ryzen CPU", "Intel CPU"], "max_price": 1500},
        {"category": "motherboard", "keywords": ["motherboard", "motherboard combo"], "max_price": 1500},
        {"category": "ram", "keywords": ["DDR5 RAM", "DDR4 RAM", "computer RAM"], "max_price": 1500},
        {"category": "storage", "keywords": ["NVMe SSD", "SSD drive", "hard drive HDD"], "max_price": 1500},
        {"category": "psu", "keywords": ["PC power supply"], "max_price": 1500},
        {"category": "cooler", "keywords": ["CPU cooler"], "max_price": 1500},
        {"category": "case", "keywords": ["PC case", "computer case"], "max_price": 1500},
        {"category": "bundle", "keywords": ["computer parts lot", "PC components", "computer hardware bundle"], "max_price": 1500},
    ]
}
