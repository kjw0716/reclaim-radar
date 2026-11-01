# Adapted from BoPeng/ai-marketplace-monitor FacebookSearchResultPage.get_listings.
# AGPL-3.0. Pinned original and complete license: third_party/aimm/.
# Structural extraction below retains AIMM's details_divs/divs parsing as fallback;
# semantic item links are the primary selector to tolerate grid layout changes.
import re

def read_card(anchor):
    post_url = anchor.get_attribute("href") or ""
    if not re.search(r"/marketplace/item/\d+",post_url):
        return None
    if post_url.startswith("/"):
        post_url = "https://www.facebook.com" + post_url
    lines = [s.strip() for s in anchor.inner_text().splitlines() if s.strip()]
    price_index = next((i for i,x in enumerate(lines) if re.match(r"^(?:US\s*)?\$\s*[\d,]|^Free$|^免费$|^免費$",x,re.I)),None)
    title = ""
    raw_price = ""
    location = ""
    if price_index is not None:
        raw_price = lines[price_index]
        remaining = [x for x in lines[price_index+1:] if not re.match(r"^(?:US\s*)?\$",x)]
        title = remaining[0] if remaining else ""
        location = remaining[1] if len(remaining)>1 else ""
    if not title:
        # AIMM fallback, adapted from ElementHandle to Locator and preserving raw price.
        details_divs = anchor.locator(":scope > :first-child > div")
        if details_divs.count()>1:
            details = details_divs.nth(1)
            divs = details.locator(":scope > div")
            raw_price = "" if divs.count()<1 else divs.nth(0).inner_text()
            title = "" if divs.count()<2 else divs.nth(1).inner_text()
            location = "" if divs.count()<3 else divs.nth(2).inner_text()
    if not title:
        # Unknown price still belongs in raw records, but never guess a price from title.
        non_badges=[x for x in lines if not re.match(r"^(?:Just listed|Sponsored|Listed|刚刚|赞助)",x,re.I)]
        title = non_badges[0] if non_badges else ""
        location = non_badges[-1] if len(non_badges)>1 else ""
    if not title:
        return None
    img = anchor.locator("img").first
    image = img.get_attribute("src") if img.count() else None
    return {"url":post_url,"title":title,"raw_price":raw_price,"location":location,"image":image,"card_lines":lines}
