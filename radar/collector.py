import logging
import queue
import re
import threading
import time
from pathlib import Path
import json
import socket
import subprocess
import urllib.request
from urllib.parse import urlencode
from .aimm_cards import read_card
from .db import dump, now
from .domain import price_parse, evaluate
from .scope import hardware_admission
from .availability import AvailabilityScan, listing_availability

log=logging.getLogger("radar.collector")

class Attention(Exception):
    pass

def description_from_text(text,title=None):
    if title:
        marker=re.search(r"^"+re.escape(title)+r"\s*$",text,re.M)
        if not marker:return ""
        text=text[marker.end():]
    # Never search recommendation cards for a late 'Description' substring.
    sections=r"Seller information|卖家信息|賣家資訊|Send seller|Message seller|发消息给卖家|发送消息给卖家|Related searches|相关搜索|相關搜尋|Today's picks|今日精选|今日精選|Recommended|推荐商品|相关推荐|相似商品|你可能也喜欢|猜你还喜欢|Similar listings|More like this|Sponsored|赞助内容"
    cutoff=re.search(r"^(?:"+sections+r")\s*$",text,re.M|re.I)
    text=text[:cutoff.start()] if cutoff else text
    heading=re.search(r"^(?:Description|描述|說明|详细信息|詳細資料|Details)\s*$",text,re.M|re.I)
    if not heading:return ""
    content=text[heading.end():].strip()
    # Condition and other structured attributes precede the seller's description.
    content=re.sub(r"^(?:商品状况|商品狀況|Condition)\s*\n[^\n]+\n?","",content,flags=re.I).strip()
    explicit=re.search(r"^(?:Description|描述|說明)\s*$",content,re.M|re.I)
    if explicit:content=content[explicit.end():].strip()
    location=re.search(r"^[^\n]*·\s*(?:我们只提供大概位置|位置为大致位置|Approximate location).*$",content,re.M|re.I)
    if location:content=content[:location.start()].strip()
    if re.search(r"^(?:CA|NV|AZ)[A-Z][^\n]+\n(?:US\s*)?\$|^(?:US\s*)?\$[\d,]+\s*$",content,re.M|re.I):return ""
    return content[:16000]

def contaminated_description(text):
    prices=len(re.findall(r"^(?:US\s*)?\$\s*[\d,]+",text or "",re.M|re.I))
    cities=len(re.findall(r"^(?:CA|NV|AZ)[A-Z][^\n]+$",text or "",re.M))
    sections=bool(re.search(r"^(?:今日精选|今日精選|Today's picks|相关搜索|Related searches|卖家信息|Seller information)\s*$",text or "",re.M|re.I))
    return sections or (prices>=2 and cities>=2)

def location_evidence_matches(visible,selected,postal,radius):
    selected=selected or {}
    radius_ok=bool(re.search(rf"(?<!\d){radius}(?:\.0)?\s*(?:miles?\b|mi\b|英里)",visible,re.I))
    def normalized(value):
        return re.sub(r"圣迭戈|聖迭戈|聖地牙哥","San Diego",value).casefold()
    saved_label=selected.get("selected","").split(",")[0]
    postal_ok=postal in visible or (selected.get("postal_code")==postal and bool(saved_label) and normalized(saved_label) in normalized(visible))
    return bool(postal_ok),radius_ok

def detail_candidates(items,existing,cutoff,changed=()):
    eligible=[ident for ident in items if ident in changed or not existing.get(ident) or existing[ident]<cutoff]
    return sorted(eligible,key=lambda ident:(ident in existing,bool(existing.get(ident)),existing.get(ident) or ""))

class Collector:
    def __init__(self,db):
        self.db=db
        self.commands=queue.Queue()
        self.stop_event=threading.Event()
        self.paused=bool(self.db.setting("collector_paused",False))
        self.context=None
        self.page=None
        self.playwright=None
        self.cdp_browser=None
        self.chrome_process=None
        self.manual_process=None
        self.next_due={}
        self.last_kept_refresh=0
        self.availability=AvailabilityScan(db)
        self.availability_failures=0
        self.availability_pages=[]
        self.availability_media_sessions=[]
        self.location_lock=threading.RLock()
        if self.db.setting("location_auto_restore") is None:
            self.db.set_setting("location_auto_restore",True)
        self.state={"status":"needs_login","message":"连接 Facebook 后，核验设置中的位置和半径", "location_confirmed":False}
        if self.paused:self.state.update(status="paused",message="采集已暂停，保存的位置偏好仍然保留")
        self.thread=threading.Thread(target=self.loop,name="marketplace-browser",daemon=True)

    def start(self):self.thread.start()
    def saved_profile(self):
        # Keep the successful profile selection even when an older SQLite backup is restored.
        manifest=self.db.directory/"browser-profile.json"
        profile=self.db.setting("browser_profile","browser")
        if manifest.exists():
            profile=json.loads(manifest.read_text(encoding="utf-8"))["profile"]
        if not re.fullmatch(r"browser(?:-login-\d+)?",profile):
            raise ValueError("浏览器配置记录异常；不会创建新会话覆盖已有登录")
        self.save_profile(profile)
        return self.db.directory/profile

    def save_profile(self,profile):
        self.db.set_setting("browser_profile",profile)
        manifest=self.db.directory/"browser-profile.json"
        temporary=manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps({"profile":profile}),encoding="utf-8")
        temporary.replace(manifest)

    def submit(self,command,**kwargs):
        if self.commands.qsize()>=2:raise ValueError("已有采集操作排队，请等待")
        self.commands.put((command,kwargs))
        return {"queued":True,"command":command}

    def browser(self):
        if self.manual_process and self.manual_process.poll() is None:
            # Only the process we launched for the fresh project profile is closed.
            subprocess.run(["powershell.exe","-NoProfile","-Command",f"(Get-Process -Id {self.manual_process.pid} -ErrorAction SilentlyContinue).CloseMainWindow()"],capture_output=True,timeout=10)
            try:self.manual_process.wait(timeout=10)
            except subprocess.TimeoutExpired:raise Attention("请先关闭刚才的项目登录窗口，再点击检查并恢复；登录会话已经保存在本机")
        self.manual_process=None
        if self.context:
            try:
                if not self.page.is_closed():return
            except Exception:pass
            try:self.context.close()
            except Exception:pass
            self.context=None
        if not self.playwright:
            from playwright.sync_api import sync_playwright
            self.playwright=sync_playwright().start()
        executable=next((p for p in [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")] if p.exists()),None)
        if not executable:raise ValueError("请安装本机 Chrome 或 Edge；人工验证使用正常浏览器沙箱")
        control_file=self.db.directory/"chrome-control.json"
        endpoint=None
        if control_file.exists():
            try:
                saved=json.loads(control_file.read_text(encoding="utf-8"))
                candidate=f"http://127.0.0.1:{int(saved['port'])}"
                with urllib.request.urlopen(candidate+"/json/version",timeout=1) as response:
                    if "Chrome" in json.load(response).get("Browser",""):
                        endpoint=candidate
            except Exception:pass
        if not endpoint:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
            # Normal installed browser: retain its sandbox and network/cookie defaults.
            # Do not disable automation detection, solve captchas, or read any normal profile.
            profile=self.saved_profile()
            arguments=[str(executable),f"--user-data-dir={profile}",f"--remote-debugging-port={port}","--remote-debugging-address=127.0.0.1","--no-first-run","https://www.facebook.com/"]
            startup=None
            if hasattr(subprocess,"STARTUPINFO"):
                startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1
            self.chrome_process=subprocess.Popen(arguments,startupinfo=startup)
            endpoint=f"http://127.0.0.1:{port}"
            for _ in range(40):
                try:
                    with urllib.request.urlopen(endpoint+"/json/version",timeout=1) as response:
                        if "Chrome" in json.load(response).get("Browser",""):break
                except Exception:time.sleep(.25)
            else:raise ValueError("普通 Chrome 未打开控制接口；请关闭项目专用窗口后重试，不需要关闭你的日常 Chrome")
            control_file.write_text(json.dumps({"port":port,"pid":self.chrome_process.pid}),encoding="utf-8")
        self.cdp_browser=self.playwright.chromium.connect_over_cdp(endpoint,timeout=15000)
        self.context=self.cdp_browser.contexts[0]
        self.page=next((page for page in self.context.pages if re.match(r"https://(?:www\.)?facebook\.com/",page.url)),self.context.pages[0] if self.context.pages else self.context.new_page())
        self.page.set_default_timeout(6000)
        self.state["location_confirmed"]=False

    def recover_login(self):
        self.paused=True
        executable=next((p for p in [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")] if p.exists()),None)
        if not executable:raise ValueError("请安装 Chrome 或 Edge")
        if self.manual_process and self.manual_process.poll() is None:
            raise Attention("新的人工登录窗口已经打开，请在那里完成登录")
        if not self.context and (self.db.directory/"chrome-control.json").exists():
            self.browser()
        if self.context and self.page and not self.page.is_closed():
            try:self.context.new_cdp_session(self.page).send("Browser.close")
            except Exception:pass
        self.context=None;self.page=None;self.cdp_browser=None
        if self.chrome_process:
            try:self.chrome_process.wait(timeout=10)
            except subprocess.TimeoutExpired:pass
        control=self.db.directory/"chrome-control.json"
        control.unlink(missing_ok=True)
        profile=f"browser-login-{time.time_ns()}"
        self.save_profile(profile)
        self.db.set_setting("location_confirmation",None)
        startup=None
        if hasattr(subprocess,"STARTUPINFO"):
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1
        self.manual_process=subprocess.Popen([str(executable),f"--user-data-dir={self.db.directory/profile}","--no-first-run","https://www.facebook.com/"],startupinfo=startup)
        self.state.update(status="needs_login",location_confirmed=False,message="已打开全新人工登录窗口，未连接采集控制。请完成登录并进入 Marketplace，再点检查并恢复；旧会话已保留。")

    def page_status(self):
        url=self.page.url
        text=self.page.locator("body").inner_text(timeout=10000)[:40000]
        if re.search(r"checkpoint|challenge|two_step_verification",url) or re.search(r"confirm (?:your identity|you.re human)|enter (?:the )?(?:security|confirmation) code|验证你的身份|確認你的身分|输入验证码",text,re.I):
            return "verification",text
        if "/login" in url or self.page.locator('input[name="email"],input[name="pass"]').count():
            return "needs_login",text
        if "/marketplace" not in url or re.search(r"Marketplace isn.t available|Marketplace isn't available|无法使用 Marketplace|Marketplace 目前無法使用",text,re.I):
            return "unavailable",text
        return "marketplace",text

    def require_marketplace(self):
        kind,text=self.page_status()
        if kind!="marketplace":
            self.state.update(status=kind,location_confirmed=False,message="请在专用浏览器完成登录/验证，之后点击自动恢复；位置偏好仍然保留")
            raise Attention(kind)
        return text

    def connect(self):
        self.browser()
        # Let the user finish the normal-browser login/checkpoint without navigation.
        if self.state.get("status") in {"ready","searching"}:
            self.page.goto("https://www.facebook.com/marketplace/",wait_until="domcontentloaded",timeout=45000)
        kind,text=self.page_status()
        if kind not in {"needs_login","verification"}:
            self.verify()
            return
        self.state.update(status=kind,message="请在 Facebook 完成登录或验证；位置偏好已保存在本机，之后点击自动恢复。",location_confirmed=False)

    def setup_location(self):
        with self.location_lock:
            return self._setup_location()

    def _setup_location(self):
        self.browser()
        self.require_marketplace()
        config=self.db.setting("config")
        postal=config["postal_code"]
        radius=config["radius_miles"]
        saved=self.db.setting("location_selection") or {}
        self.state.update(status="restoring_location",location_confirmed=False,message=f"正在自动恢复已保存的位置：{postal} · {radius} miles")
        # Use visible controls only. Never claim a query URL radius proves actual location.
        dialog=self.page.get_by_role("dialog").last
        if not dialog.count() or not dialog.is_visible():
            locator=self.page.get_by_role("button",name=re.compile(r"^(?:地点|位置|Location)[:：]|Within.*(?:miles?|mi)|\d+\s*英里",re.I))
            if locator.count():locator.first.click()
            else:
                locator=self.page.get_by_text(re.compile(r"Within.*(?:miles?|mi)|英里以内|英里內",re.I)).first
                if locator.count():locator.click()
            try:dialog.wait_for(state="visible",timeout=6000)
            except Exception:
                self.location_failed("未找到位置设置窗口")
                return
        inputs=dialog.locator("input:not([type=hidden]):visible")
        try:inputs.first.wait_for(state="visible",timeout=8000)
        except Exception:pass
        if not inputs.count():
            self.location_failed("未找到位置输入框")
            return
        inputs.first.fill(postal)
        self.page.wait_for_timeout(1500)
        suggestion=self.page.get_by_role("option",name=re.compile(r"(?<!\d)"+re.escape(postal)+r"(?!\d)")).first
        try:suggestion.wait_for(state="visible",timeout=8000)
        except Exception:pass
        if not suggestion.count():suggestion=dialog.get_by_text(re.compile(re.escape(postal)+r".*(?:California|CA)|(?:California|CA).*"+re.escape(postal))).first
        # A previously saved exact suggestion can be reused if Facebook omits the ZIP.
        if not suggestion.count() and saved.get("postal_code")==postal:
            label=saved.get("postal_option") or saved.get("selected")
            if label:
                remembered=self.page.get_by_role("option",name=label,exact=True)
                if remembered.count()==1:suggestion=remembered
        if not suggestion.count():
            self.location_failed("邮编已填入，但没有找到匹配的地点选项")
            return
        selected=suggestion.inner_text()
        suggestion.click()
        visible_label=inputs.first.input_value()
        selection={"postal_code":postal,"selected":visible_label,"postal_option":selected,"selected_at":now(),"method":"postal_suggestion"}
        if not self.set_radius(dialog,radius):
            self.location_failed(f"未找到可用的 {radius} miles 半径选项")
            return
        apply=dialog.get_by_role("button",name=re.compile(r"^(Apply|应用|套用)$",re.I))
        if apply.count()!=1:
            self.location_failed("未找到应用按钮")
            return
        apply.click()
        dialog.wait_for(state="hidden",timeout=10000)
        self.page.wait_for_timeout(1200)
        applied=self.page.get_by_role("button",name=re.compile(r"^(?:地点|位置|Location)[:：]",re.I)).first
        if applied.count():
            selection["selected"]=applied.inner_text().splitlines()[0].strip()
            selection["applied_label"]=applied.get_attribute("aria-label")
        # Remember only applied choices. A deleted memory remains deleted until saved again.
        if self.db.setting("location_auto_restore"):
            self.db.set_setting("location_selection",selection)
        self._verify(restore=False,selection=selection)

    def location_failed(self,reason):
        self.state.update(status="needs_location",location_confirmed=False,message=f"{reason}。偏好仍已保存；可重试自动恢复，或在 Facebook 设置后检查。")
        self.screenshot("location-restore")

    def set_radius(self,dialog,radius):
        pattern=re.compile(rf"^(?:Within\s+)?{radius}(?:\.0)?\s*(?:miles?|mi|英里)(?:以内|內|内)?$",re.I)
        control=dialog.get_by_role("combobox",name=re.compile(r"radius|半径|半徑|范围|範圍",re.I))
        if not control.count():control=dialog.get_by_role("button",name=re.compile(r"radius|半径|半徑|^\d+\s*(?:miles?|mi|英里)$",re.I))
        if not control.count():
            # Some versions label only the selected value, with no accessible name.
            control=dialog.get_by_text(re.compile(r"^\d+\s*(?:miles?|mi|英里)$",re.I))
        if control.count()!=1:return False
        control=control.first
        if control.evaluate("el => el.tagName.toLowerCase()") == "select":
            options=control.locator("option").all()
            matches=[option for option in options if pattern.fullmatch(option.inner_text().strip())]
            if len(matches)!=1:return False
            control.select_option(value=matches[0].get_attribute("value"))
            return True
        control.click()
        option=self.page.get_by_role("option",name=pattern)
        if not option.count():option=self.page.get_by_role("menuitem",name=pattern)
        if option.count()==1:
            option.click()
            return True
        # Custom radius is exposed as a numeric input in some Facebook layouts.
        custom=self.page.get_by_text(re.compile(r"^(?:Custom|自定义|自訂)(?: radius|半径|半徑)?$",re.I))
        if custom.count()==1:
            custom.click()
            number=dialog.get_by_role("spinbutton")
            if number.count()==1 and re.search(r"miles?|英里",dialog.inner_text(),re.I):
                number.fill(str(radius))
                number.press("Tab")
                return True
        return False

    def verify(self):
        with self.location_lock:
            return self._verify()

    def _verify(self,restore=True,selection=None):
        self.browser()
        kind,_=self.page_status()
        # Explicit resume may open Marketplace after login; never interrupt a checkpoint.
        if kind=="unavailable" and re.match(r"https://(?:www\.)?facebook\.com/(?:\?.*)?$",self.page.url):
            self.page.goto("https://www.facebook.com/marketplace/",wait_until="domcontentloaded",timeout=45000)
        elif kind=="marketplace" and "/marketplace/item/" in self.page.url:
            # Item pages show the seller's location, not the saved search radius.
            self.page.goto("https://www.facebook.com/marketplace/",wait_until="domcontentloaded",timeout=45000)
            self.page.wait_for_timeout(1500)
        text=self.require_marketplace()
        config=self.db.setting("config")
        radius=config["radius_miles"]
        selected=selection or self.db.setting("location_selection") or {}
        labels=[]
        for loc in [self.page.get_by_role("button",name=re.compile(r"(?:\d+\s*(?:miles?|英里|km|公里))\s*(?:内|內)?$",re.I)),self.page.locator('[aria-label^="Location:"]')]:
            for el in loc.all()[:8]:
                labels.append((el.get_attribute("aria-label") or "")+" "+el.inner_text())
        # Product cards contain unrelated seller cities and distances: never use body text.
        visible=" ".join(labels)
        postal_ok,radius_ok=location_evidence_matches(visible,selected,config["postal_code"],radius)
        self.db.set_setting("location_check",{"checked_at":now(),"radius_ok":radius_ok,"postal_ok":postal_ok,"visible_labels":labels})
        if not postal_ok or not radius_ok:
            self.state.update(status="needs_location",location_confirmed=False,message=f"当前页面尚未确认 {config['postal_code']} / {radius} miles；已保存的偏好可随时修改或删除。")
            if restore and self.db.setting("location_auto_restore"):
                self._setup_location()
            return
        confirmation={"postal_code":config["postal_code"],"radius_miles":radius,"page_labels":labels,"verified_at":now(),"method":selected.get("method","visible_postal")}
        self.db.set_setting("location_confirmation",confirmation)
        self.state.update(status="ready",location_confirmed=True,message="位置与半径已核对，单队列监控已就绪",location=confirmation)
        self.paused=False
        self.db.set_setting("collector_paused",False)
        self.availability.resume()

    def screenshot(self,stage):
        # Never save login/checkpoint DOM, cookies, tokens or credential screenshots.
        folder=self.db.directory/"screenshots";folder.mkdir(exist_ok=True)
        try:
            if self.page_status()[0]=="marketplace":
                file=folder/f"{int(time.time())}-{stage}.png"
                self.page.screenshot(path=str(file),full_page=False)
                for old in sorted(folder.glob("*.png"),reverse=True)[40:]:old.unlink()
                return str(file.relative_to(self.db.directory))
        except Exception:pass
        return None

    def search(self,keyword,max_price):
        self.browser()
        if not self.state.get("location_confirmed"):
            self.verify()
            if not self.state.get("location_confirmed"):raise Attention("needs_location")
        config=self.db.setting("config")
        rid=self.db.execute("INSERT INTO runs(kind,keyword,status,started_at) VALUES ('search',?,'running',?)",(keyword,now()))
        self.state.update(status="searching",message=f"搜索 {keyword}",current_keyword=keyword)
        count=0;reason="";failures=0;started=time.monotonic();items={};seen_ids=set();scope_rejected=0;removed_seen=0
        old_rows=self.db.query("SELECT id,details_at,price FROM listings")
        existing={row['id']:row['details_at'] for row in old_rows}
        old_prices={row['id']:row['price'] for row in old_rows};changed=set()
        try:
            params={"query":keyword,"radius":round(config["radius_miles"]*1.609344),"maxPrice":max_price,"sortBy":"creation_time_descend","deliveryMethod":"local_pick_up"}
            self.page.goto("https://www.facebook.com/marketplace/search/?"+urlencode(params),wait_until="domcontentloaded",timeout=45000)
            self.page.wait_for_timeout(2500)
            text=self.require_marketplace()
            # Reject a page indicating a different radius; missing indicator is recorded, not silently reconfigured.
            if re.search(r"(?:Within|范围|範圍).*?(\d+)\s*(?:miles|英里)",text,re.I):
                m=re.search(r"(?:Within|范围|範圍).*?(\d+)\s*(?:miles|英里)",text,re.I)
                if int(m[1])!=config["radius_miles"]:
                    self.state["location_confirmed"]=False
                    raise Attention("页面范围发生变化，请重新检查")
            idle=0
            while not self.stop_event.is_set() and not self.paused:
                before=len(seen_ids)
                anchors=self.page.locator('a[href*="/marketplace/item/"]')
                for anchor in anchors.all():
                    try:
                        card=read_card(anchor)
                        if card:
                            key=card['url'].split('?')[0].rstrip('/')
                            if key in seen_ids:continue
                            seen_ids.add(key)
                            if not hardware_admission(card['title'],scope=config.get('collection_scope','hardware'))[0]:
                                scope_rejected+=1
                                if len(seen_ids)>=config['max_cards']:break
                                continue
                            parsed,kind=price_parse(card["raw_price"])
                            card.update(price=parsed,currency="USD",price_type=kind)
                            ident=self.db.upsert(card,keyword)
                            if ident is None:
                                removed_seen+=1
                                if len(seen_ids)>=config['max_cards']:break
                                continue
                            if ident in old_prices and old_prices[ident]!=parsed:changed.add(ident)
                            evaluate(self.db,ident)
                            items[ident]=card
                            if len(seen_ids)>=config["max_cards"]:break
                    except Exception:
                        failures+=1
                idle=idle+1 if len(seen_ids)==before else 0
                if len(seen_ids)>=config["max_cards"]:reason="card_limit";break
                if time.monotonic()-started>=config["term_timeout_seconds"]:reason="time_limit";break
                if idle>=3:reason="no_new_ids";break
                self.page.mouse.wheel(0,900)
                self.page.wait_for_timeout(1700)
                self.require_marketplace()
            if not items:
                if removed_seen:reason="only_removed_listings"
                elif scope_rejected:reason="no_desktop_candidates"
                elif re.search(r"No results|No listings|We couldn.t find|没有结果|找不到结果|沒有結果",text,re.I):reason="true_zero_results"
                else:raise ValueError("没有可解析商品，也没有明确零结果标识；视为解析异常")
            detail_count=0;detail_attempts=0
            # Don't spend each keyword's detail budget on the same fresh listings.
            candidates=detail_candidates(items,existing,datetime_cutoff(),changed)
            for ident in candidates:
                if detail_attempts>=config["max_details"] or time.monotonic()-started>=config["term_timeout_seconds"] or self.paused or self.stop_event.is_set():break
                detail_attempts+=1
                try:
                    self.read_detail(ident);detail_count+=1
                except Attention:raise
                except Exception as e:
                    log.warning("Detail %s: %s",ident,str(e)[:160]);failures+=1
                self.page.wait_for_timeout(1500)
            count=len(items)
            if self.paused or self.stop_event.is_set():reason="paused"
            previous=self.db.query("SELECT count,metadata FROM runs WHERE kind='search' AND keyword=? AND status IN ('success','partial') AND id!=? ORDER BY id DESC LIMIT 1",(keyword,rid))
            same_scope=previous and json.loads(previous[0]['metadata']).get('collection_scope','hardware')==config.get('collection_scope','pc_only')
            suspicious=bool(same_scope and previous[0]["count"]>=10 and count<previous[0]["count"]*.2)
            new_count=sum(ident not in existing for ident in items)
            results=[self.db.get_listing(ident)['screening_result'] for ident in items]
            excluded_count=results.count('excluded');price_review_count=results.count('price_review');candidate_count=count-excluded_count-price_review_count
            meta={"new_count":new_count,"existing_count":count-new_count,"excluded_count":excluded_count,"candidate_count":candidate_count,"price_review_count":price_review_count,"detail_skipped_fresh":count-len(candidates),"collection_scope":config.get('collection_scope','pc_only'),"detail_count":detail_count,"detail_attempts":detail_attempts,"cards_seen":len(seen_ids),"scope_rejected":scope_rejected,"parse_failures":failures,"sudden_drop":suspicious,"location":self.db.setting("location_confirmation"),"elapsed_seconds":round(time.monotonic()-started)}
            self.db.execute("UPDATE runs SET status=?,finished_at=?,count=?,reason=?,metadata=? WHERE id=?",("partial" if failures or suspicious or reason in {"time_limit","paused"} else "success",now(),count,reason,dump(meta),rid))
            self.state.update(status="paused" if self.paused else "ready",message=f"{keyword}: 新增 {new_count}，重复命中 {count-new_count}，候选 {candidate_count}，待核价 {price_review_count}，系统排除 {excluded_count}"+("；数量骤降，需检查" if suspicious else ""),last_search_success=now())
        except Attention as e:
            self.db.execute("UPDATE runs SET status='attention',finished_at=?,count=?,reason=? WHERE id=?",(now(),len(items),str(e),rid))
            if self.state["status"]=="searching":self.state.update(status="needs_location",message=str(e))
            raise
        except Exception as e:
            shot=self.screenshot("parse")
            self.db.execute("UPDATE runs SET status='failed',finished_at=?,count=?,reason=?,metadata=? WHERE id=?",(now(),len(items),str(e),dump({"screenshot":shot}),rid))
            self.state.update(status="parse_failed",message=str(e))
            log.exception("Search failed")
        finally:
            self.next_due[keyword]=time.monotonic()+config["interval_minutes"]*60

    def read_detail(self,ident):
        item=self.db.get_listing(ident)
        self.page.goto(item["url"],wait_until="domcontentloaded",timeout=30000)
        self.page.wait_for_timeout(1700)
        text=self.require_marketplace()
        if re.search(r"This listing is no longer available|This content isn.t available|此商品已不存在",text,re.I):
            self.db.execute("INSERT INTO audit(listing_id,action,new_value,source,created_at) VALUES (?,'availability','unavailable_page','collector',?)",(ident,now()))
            return
        # Expand only a description-specific button when available, avoiding arbitrary navigation.
        more=self.page.get_by_role("button",name=re.compile(r"^(See more|查看更多|顯示更多)$",re.I))
        if more.count()==1:
            try:more.click();text=self.require_marketplace()
            except Attention:raise
            except Exception:pass
        desc=description_from_text(text,item['title'])
        if not desc:
            raise ValueError("详情描述未可靠识别，保留已有卡片并记录解析失败")
        update={"url":item["url"],"title":item["title"],"description":desc,"detail_success":True,"description_parser":"bounded-v2","description_status":"verified"}
        # Price immediately adjacent to the matching title; no arbitrary '$' from recommendation cards.
        lines=[x.strip() for x in text.splitlines() if x.strip()]
        for i,line in enumerate(lines):
            if line==item["title"]:
                for adjacent in lines[i+1:i+4]:
                    if re.match(r"^(?:US\s*)?\$|^Free$",adjacent,re.I):
                        value,kind=price_parse(adjacent)
                        update.update(raw_price=adjacent,price=value,price_type=kind);break
                break
        condition=re.search(r"(?:Condition|成色|商品状况|商品狀況)\s*\n([^\n]+)",text,re.I)
        if condition:update["condition"]=condition[1]
        if self.db.upsert(update):evaluate(self.db,ident)

    def availability_interrupted(self):
        return self.paused or self.stop_event.is_set() or not self.db.setting('availability_schedule')['enabled']

    def close_availability_pages(self):
        for page in self.availability_pages:
            try:page.close()
            except Exception:pass
        self.availability_pages=[]
        self.availability_media_sessions=[]

    def availability_page_result(self,page,item):
        # Wait for item content, an unavailable notice, or an authentication barrier.
        # Starting navigation at commit lets three tabs render concurrently.
        page.wait_for_function(r"""({title}) => {
          const body=document.body?.innerText || '';
          if (/checkpoint|challenge|two_step_verification|\/login/.test(location.pathname) ||
              document.querySelector('input[name="email"],input[name="pass"]') ||
              /confirm (your identity|you.re human)|enter (the )?(security|confirmation) code|temporarily blocked|going too fast|try again later|输入验证码|验证你的身份/i.test(body)) return true;
          const main=document.querySelector('[role="main"],main');
          if (!main) return false;
          const normalize=v=>v.replace(/\s+/g,' ').trim().toLowerCase();
          if ([...main.querySelectorAll('h1,[role="heading"][aria-level="1"]')].some(h=>normalize(h.innerText).includes(normalize(title)))) return true;
          return /This listing (isn't available anymore|is no longer available)|This content isn't available|此商品已不存在|此内容无法显示|Marketplace isn't available/i.test(main.innerText);
        }""",arg={'title':item['title']},timeout=12000)
        text=page.locator('body').inner_text(timeout=5000)[:40000]
        if re.search(r'checkpoint|challenge|two_step_verification|/login',page.url) or page.locator('input[name="email"],input[name="pass"]').count() or re.search(r"confirm (?:your identity|you.re human)|enter (?:the )?(?:security|confirmation) code|输入验证码|验证你的身份",text,re.I):
            raise Attention('需要登录或验证，售出检查已暂停')
        if re.search(r"temporarily blocked|going too fast|try again later|暂时被封锁|操作过于频繁|請稍後再試|请稍后再试",text,re.I):
            raise Attention('Facebook 限制访问，稍后点击自动恢复')
        match=re.search(r'/marketplace/item/(\d+)(?:/|$)',page.url)
        if not match or match[1]!=item['id']:return 'unknown'
        main=page.get_by_role('main')
        content=main.first.inner_text(timeout=5000) if main.count() else text
        return listing_availability(content,item['title'])

    def check_availability_next(self):
        items=self.availability.next_items(3)
        if not items:return
        try:
            self.browser()
            kind,_=self.page_status()
            if kind in {'needs_login','verification'}:
                raise Attention('需要登录或验证，售出检查已暂停')
            self.state.update(status='checking_sold')
            if any(page.is_closed() for page in self.availability_pages):self.close_availability_pages()
            while len(self.availability_pages)<len(items):
                page=self.context.new_page()
                page.set_default_timeout(12000)
                # Playwright routing disables HTTP cache. Block media in Chromium instead,
                # retaining cached Facebook scripts/styles across the existing item URLs.
                session=self.context.new_cdp_session(page)
                session.send('Network.enable')
                session.send('Network.setBlockedURLs',{'urls':['*.jpg*','*.jpeg*','*.png*','*.webp*','*.gif*','*.mp4*','*.webm*','*.woff*','*.ttf*']})
                self.availability_media_sessions.append(session)
                self.availability_pages.append(page)
            pending=[]
            for page,item in zip(self.availability_pages,items):
                if self.availability_interrupted():return
                failed=False
                try:
                    response=page.goto(item['url'],wait_until='commit',timeout=15000)
                    if response and response.status in {403,429}:
                        raise Attention('Facebook 限制访问，稍后点击自动恢复')
                except Attention:raise
                except Exception:failed=True
                pending.append((page,item,failed))
            for page,item,failed in pending:
                if self.availability_interrupted():return
                try:
                    if failed:raise TimeoutError('navigation failed')
                    result=self.availability_page_result(page,item)
                    self.availability_failures=0
                except Attention:raise
                except Exception:
                    result='unknown'
                    self.availability_failures+=1
                if self.availability_interrupted():return
                progress=self.availability.record(item['id'],result)
                self.state.update(message=f"检查售出状态 {progress['checked']}/{progress['total']} · 已删除 {progress['deleted']}")
                if self.availability_failures>=3 and progress['status']!='completed':
                    raise Attention('连续访问失败，点击自动恢复后继续')
                if progress['status']=='completed':
                    self.state.update(status='ready',message=f"售出检查完成：检查 {progress['checked']}，删除 {progress['deleted']}，保留已售 {progress['kept_sold']}，未确认 {progress['unknown']}")
                    self.close_availability_pages()
        except Attention as e:
            self.availability.attention(str(e))
            self.state.update(status='error',message=str(e))
            self.close_availability_pages()
        except Exception:
            self.availability.attention('检查页面连接失败，点击自动恢复后继续')
            self.state.update(status='error',message='检查页面连接失败')
            self.close_availability_pages()
            log.exception('Availability check connection failed')
        finally:
            if self.availability_interrupted():self.close_availability_pages()

    def loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    if self.availability_interrupted() and self.availability_pages:self.close_availability_pages()
                    command,args=self.commands.get(timeout=0 if self.state['status']=='checking_sold' and not self.paused else 2)
                    if command=="connect":self.connect()
                    elif command=="recover_login":self.recover_login()
                    elif command=="location":self.setup_location()
                    elif command=="verify":self.verify()
                    elif command=="pause":self.paused=True;self.state.update(status="paused",message="采集已暂停")
                    elif command=="search":self.search(args.get("keyword","gaming PC"),args.get("max_price",1500))
                    elif command=="detail":self.browser();self.read_detail(args['listing_id'])
                    elif command=="resume":self.verify()
                    elif command=="check_sold":
                        self.paused=False
                        self.db.set_setting('collector_paused',False)
                        self.availability.start_due(force=True)
                    self.commands.task_done()
                except queue.Empty:
                    config=self.db.setting("config")
                    schedule_enabled=self.db.setting('availability_schedule')['enabled']
                    if not schedule_enabled and self.state['status']=='checking_sold':
                        self.state.update(status='ready',message='每日售出检查已停用')
                    if not self.paused and schedule_enabled:
                        progress=self.availability.start_due()
                        if progress.get('status')=='running':
                            self.check_availability_next()
                            continue
                    if config["auto_monitor"] and self.state["status"]=="ready" and not self.paused:
                        eligible=[(keyword,group["max_price"]) for group in config["search_groups"] for keyword in group["keywords"] if time.monotonic()>=self.next_due.get(keyword,0)]
                        chosen=min(eligible,key=lambda term:self.next_due.get(term[0],0)) if eligible else None
                        if chosen:self.search(*chosen)
                        elif time.monotonic()-self.last_kept_refresh>86400:
                            rows=self.db.query("SELECT id FROM listings WHERE review_decision='keep' AND (details_at IS NULL OR details_at<?) LIMIT 10",(datetime_cutoff(),))
                            for row in rows:
                                self.read_detail(row["id"])
                            self.last_kept_refresh=time.monotonic() if len(rows)<10 else time.monotonic()-86400+60
                except Attention as e:
                    log.info("Human attention: %s",e)
                except Exception as e:
                    self.state.update(status="error",message=f"浏览器操作失败: {str(e)[:220]}")
                    log.exception("Browser worker error")
        finally:
            self.close_availability_pages()
            # Disconnect without closing the user's in-progress login window.
            if self.playwright:
                try:self.playwright.stop()
                except Exception:pass

def datetime_cutoff():
    from datetime import datetime,timezone,timedelta
    return (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
