"""Offline city-level approximations, with GeoNames attribution and no address lookup."""
import json
import re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def cities():
    path=Path(__file__).parent/"data"/"us_cities.json"
    if not path.exists():return {}
    index={}
    for row in json.loads(path.read_text(encoding="utf-8"))["cities"]:
        for name in {row["name"],row["ascii"],*row["aliases"]}:
            key=(row["state"],name.casefold().strip())
            if key in index and index[key] and index[key]["id"]!=row["id"]:index[key]=None
            elif key not in index:index[key]=row
    return index

def city_point(label):
    text=(label or "").strip();state=None
    prefix=re.fullmatch(r"([A-Z]{2})([A-Z].+)",text)
    suffix=re.fullmatch(r"(.+?),\s*([A-Z]{2})(?:,?\s*(?:USA|United States))?",text)
    if prefix:state,text=prefix[1],prefix[2]
    elif suffix:text,state=suffix[1],suffix[2]
    if not state:return None # no unrecorded state assumption
    return cities().get((state,text.casefold().strip()))
