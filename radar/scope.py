"""Positive PC and internal-component admission; unrelated/unknown objects stay out."""
import re

WHOLE=re.compile(r"\b(?:gaming\s+(?:pc|desktop|computer)|desktop(?:\s+(?:computer|pc))?s?|(?:computer|pc)\s+tower|mini\s*pc|custom(?:\s+built)?(?:\s+gaming)?\s+pc|barebones(?:\s+(?:pc|computer))?|pc\s+(?:build|system)|optiplex|elite\s*desk|thinkcentre|hp\s+omen|alienware\s+aurora|powerspec\s+[gb]\d{3})\b|台式(?:电脑|机)|电脑主机|電腦主機|台式主机|台式主機",re.I)
ACCESSORY=re.compile(r"\b(?:desk|tabletop|furniture|riser|converter|laptop|notebook|macbook|imac|mac\s*(?:mini|pro)|rackstation|nas|egpu|headset|touchpad|trackpad|varidesk|ergodox|power\s+(?:bank|station)|docking|baseball|basketball|diecast|hot\s+wheels)\b|笔记本|筆記本|电脑桌|電腦桌",re.I)
PART_NOUN=re.compile(r"\b(?:ram|ddr[345]|parts?|peripherals?|case|chassis|fans?|coolers?|heatsink|motherboard|mainboard|power\s+supply|monitor|keyboard|mouse|cable|stand|games?)\b|机箱|機箱|主板|显示器|顯示器|键盘|鍵盤",re.I)

def desktop_admission(title,description=""):
    title=(title or "").strip()
    whole=WHOLE.search(title) or re.search(r"\b(?:hp\s+z\d{3}\s+workstation|dell\s+(?:precision|vostro)\s+\d{3,4}|lenovo\s+ideacentre\s+aio\s+(?:\d{3}|i\b))\b|^pc\s*(?:$|\(|with\b)",title,re.I)
    bad=ACCESSORY.search(title)
    if bad:
        return False,"不是 PC 主机：外设、桌架、笔记本、其他设备或无关商品"
    branded=re.search(r"\b(?:alienware\s+(?:area(?:[- ]?51)?\s*r?\d*|aurora)|ibuypower|cyberpowerpc)\b",title,re.I)
    if branded and re.search(r"\bi[3579][- ]\d{4,5}[A-Z]*\b|\bRyzen\b",title,re.I) and re.search(r"\b(?:RAM|DDR[345]|NVMe|SSD|HDD)\b",title,re.I) and not re.search(r"\b(?:case|chassis|motherboard|keyboard|monitor|for)\b",title,re.I):
        return True,"品牌主机与 CPU / 内存或存储配置相互印证"
    part=PART_NOUN.search(title)
    # An entire PC with bundled peripherals is allowed, but 'keyboard for gaming PC'
    # and 'gaming PC case' are not. Mere PC mentions in descriptions never suffice.
    if part:
        tail=title[whole.end():].strip() if whole else ""
        immediate=PART_NOUN.match(tail)
        if not whole or part.start()<whole.start() or immediate:
            return False,"独立零件或配件，不是 PC 主机"
    if whole:return True,"标题明确为 PC 主机"
    generic=re.search(r"\b(?:pc|computer|workstation)\b|主机|主機",title,re.I)
    if generic and not part:
        specs=title+" "+description
        cpu=bool(re.search(r"\b(?:Ryzen|Intel\s+Core|i[3579][- ]\d{4,5})\b",specs,re.I))
        memory=bool(re.search(r"\b\d+\s*GB\s*(?:RAM|DDR[345])|\bDDR[345]\b",specs,re.I))
        storage=bool(re.search(r"\b(?:SSD|HDD|NVMe)\b",specs,re.I))
        if cpu and (memory or storage):return True,"主机标题及 CPU / 内存或存储配置相互印证"
    return False,"缺少明确 PC 主机证据，不进入候选列表"

def hardware_admission(title,description="",scope="hardware"):
    allowed,reason=desktop_admission(title,description)
    if allowed:return True,reason,"pc"
    if scope=="pc_only":return False,reason,None
    title=(title or "").strip()
    # Product evidence comes from the title. Compatibility/specs buried in an
    # unrelated desk, peripheral or carrying-case description do not admit it.
    if re.search(r"\b(?:desk|tabletop|table|furniture|riser|converter|monitor|keyboard|mouse|headset|headphones?|printer|touchpad|trackpad|ergodox|docking|baseball|basketball|diecast|hot wheels|gator|hardcase|carrying case|shipping electronics|rackstation|nas|playstation|xbox|nintendo|meta quest|vr headset)\b|电脑桌|显示器|键盘|箱包",title,re.I):
        return False,"无关商品：外设、家具、箱包或其他设备",None
    if re.search(r"\b(?:macbook|imac|mac\s*(?:mini|pro))\b",title,re.I) and not re.search(r"compatible|works with|支持|兼容",title,re.I):
        return False,"Mac 专属商品不在范围",None
    patterns={
        "bundle":r"\b(?:computer|pc|hardware)\s+(?:parts|components)(?:\s+(?:lot|bundle))?\b|\b(?:motherboard|cpu|gpu)\s+(?:combo|bundle)\b|电脑零件包|电脑配件包",
        "cooler":r"\b(?:cpu\s+(?:cooler|fan)|pc\s+fans?|computer\s+(?:case\s+)?fans?|case\s+fans?|heatsink|water\s*block|nzxt\s+kraken|corsair\s+h\d{2,3}|noctua\s+nh[- ]|thermalright\s+(?:peerless|phantom))\b|散热|散熱",
        "psu":r"\b(?:pc\s+power\s+supply|power\s+supply|psu|corsair\s+(?:rm|cx|hx|ax|sf|tx)\d{3,4}[a-z]*|evga\s+supernova|seasonic\s+(?:focus|prime))\b|电源|電源",
        "case":r"\b(?:pc\s+cases?|computer\s+cases?|gaming\s+pc\s+case|empty\s+case|(?:mini[- ]?itx|micro[- ]?atx|atx)\s+case|lian\s*li\s+(?:lancool|o11|\d{3}[a-z]*)|nzxt\s+h\d{3}|corsair\s+\d{4}d|fractal\s+(?:design|north|meshify))\b|机箱|機箱",
        "motherboard":r"\b(?:motherboard|mainboard|mobo)\b|主板",
        "ram":r"\b(?:ddr[345]|ram|memory\s+kit)\b|内存|記憶體",
        "storage":r"\b(?:ssd|hdd|nvme|hard\s+drive|solid\s+state)\b|硬盘|硬碟",
        "gpu":r"\b(?:rtx|gtx|rx|arc)\s*[- ]?\s*(?:[ab]\s*)?\d{3,4}|\b(?:gpu|graphics\s+card|video\s+card|\d{3,4}\s*ti)\b|显卡|顯示卡",
        "cpu":r"\b(?:cpu|processors?|core\s+ultra\s+[579]\s+\d{3}[a-z]*|ryzen|(?:core\s+)?i[3579][- ]\d{4,5}[a-z]*)\b|处理器|處理器",
    }
    for category,pattern in patterns.items():
        if re.search(pattern,title,re.I):return True,"标题明确为电脑内部零件",category
    return False,"缺少明确主机或电脑零件证据，不进入候选",None
