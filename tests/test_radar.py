import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from radar.app import create_app, validate_config
from radar.config import DEFAULT
from radar.db import Database
from radar.domain import evaluate, recognize, price_parse, distance
from radar.prices import PriceService, parse_shs, parse_pcwatch

@pytest.fixture
def db(tmp_path):
    db=Database(tmp_path)
    config=db.setting('config');config['collection_scope']='hardware';db.set_setting('config',config)
    return db
@pytest.fixture
def client(db):return TestClient(create_app(db,background=False))
def item(title="RTX 3070 graphics card",raw_price="$100",**extra):
    return {"url":"https://www.facebook.com/marketplace/item/123456789/?ref=search","title":title,"raw_price":raw_price,"price":100,"description":"Used, tested and working","location":"San Diego, CA",**extra}

def test_decisions_survive_reimport_reprice_and_restart(db):
    ident=db.upsert(item(),"graphics card",is_test=True)
    evaluate(db,ident);db.decide(ident,"keep")
    first=db.get_listing(ident)["first_seen"]
    db.upsert(item(raw_price="$80",price=80,description="New details"),"RTX GPU")
    evaluate(db,ident)
    restart=Database(db.directory)
    record=restart.get_listing(ident)
    assert record["review_decision"]=="keep"
    assert record["first_seen"]==first and record["price"]==80
    assert len(record["keywords"])==2 and record["is_test"]==1
    assert len(restart.query("SELECT * FROM listings"))==1
    assert restart.query("SELECT * FROM snapshots")[0]["price"]==100
    restart.decide(ident,"reject");restart.upsert(item(price=120));evaluate(restart,ident)
    assert restart.get_listing(ident)["review_decision"]=="reject"

@pytest.mark.parametrize("title,category",[
    ("gaming PC Ryzen 5600X RTX 3070","pc"),("barebones PC no GPU","pc"),
    ("RTX 3070 8GB","gpu"),("Intel i7-12700K processor","cpu"),("B550 motherboard","motherboard"),
    ("DDR4 RAM 16GB","ram"),("NVMe SSD 1TB","storage"),("HDD hard drive 2TB","storage"),
    ("650W PC power supply","psu"),("RTX 3070 waterblock cooler","cooler"),
    ("PC case empty","case"),("motherboard CPU combo bundle","bundle"),
    ("MacBook Pro 2020","mac"),("DDR4 memory compatible with Mac mini","ram"),
])
def test_hardware_object_recognition(title,category):
    assert recognize(title,"also works with Mac")['category']==category

@pytest.mark.parametrize("raw,value,kind",[("Free",0,"free"),("$1",1,"placeholder"),("$1,200",1200,"fixed"),("$100-$200",None,"negotiable_or_range"),("",None,"unknown"),("Negotiable",None,"negotiable_or_range")])
def test_price_uncertainty(raw,value,kind):assert price_parse(raw)==(value,kind)

def test_all_target_categories_have_traceable_fallback(db):
    titles=["gaming PC","graphics card","CPU processor","motherboard","DDR4 RAM","SSD drive","PC power supply","CPU cooler","PC case","computer parts lot"]
    for i,title in enumerate(titles):
        ident=db.upsert({**item(title),"url":f"https://www.facebook.com/marketplace/item/{i+1}/"},is_test=True)
        v=evaluate(db,ident)
        assert v["reference"] is not None
        assert v["reference"]["method"]=="heuristic"
        assert v["reference"]["notes"].startswith("初始类别规则")
        assert v["distance"]["confidence"] == "city"

def test_placeholder_never_becomes_profit(db):
    ident=db.upsert(item(raw_price="$1",price=1),is_test=True)
    v=evaluate(db,ident)
    assert v["profits"]["low"] is None
    assert db.get_listing(ident)["screening_result"]=="check"

def test_unknown_category_does_not_invent_price(db):
    ident=db.upsert(item(title="Thing for sale"),is_test=True)
    assert evaluate(db,ident)["reference"] is None

def test_coordinate_range_and_mac_exclusion_preserve_keep(db):
    ident=db.upsert(item(latitude=34.0522,longitude=-118.2437),is_test=True)
    db.decide(ident,"keep");evaluate(db,ident)
    assert db.get_listing(ident)["screening_result"]=="excluded"
    assert db.get_listing(ident)["review_decision"]=="keep"
    assert distance(item(latitude=DEFAULT["center_lat"],longitude=DEFAULT["center_lon"]),DEFAULT)["miles"]==0
    db.upsert(item(title="MacBook Pro"));evaluate(db,ident)
    assert db.get_listing(ident)["valuation"]["reference"] is None

def test_whole_pc_and_parts_never_sum_twice(db):
    prices=PriceService(db)
    for cat,model,amount in [("cpu","Ryzen 5600X",80),("gpu","RTX 3070",200)]:
        prices.import_reference({"category":cat,"model":model,"low":amount,"mid":amount,"high":amount,"currency":"USD","source":"test fixture","source_url":"https://example.com/test-fixture","price_kind":"sold","market":"US"})
    ident=db.upsert(item(title="gaming PC Ryzen 5600X RTX 3070",description="no GPU included"),is_test=True)
    v=evaluate(db,ident)
    assert all(x['category']!='gpu' for x in v['parts'])
    assert v['reference']['mid']<=80

def test_outlier_quarantine_does_not_replace_previous(db):
    prices=PriceService(db)
    r={"category":"gpu","model":"RTX 3070","low":180,"mid":220,"high":260,"currency":"USD","source":"test fixture","source_url":"https://example.com/fixture","price_kind":"sold","market":"US"}
    prices.import_reference(r);ident=db.upsert(item(),is_test=True)
    prices.import_reference({**r,"low":5000,"mid":10000,"high":20000})
    v=evaluate(db,ident)
    assert v["reference"]["mid"]==220
    assert db.query("SELECT count(*) AS n FROM references_prices WHERE quarantined=1")[0]["n"]==1
    with pytest.raises(ValueError):prices.import_reference({**r,"currency":"EUR"})
    with pytest.raises(ValueError):prices.import_reference({**r,"mid":float('nan')})

def test_source_free_subscription_not_hardware_price():
    html='<script type="application/ld+json">{"@type":"SoftwareApplication","offers":{"price":"0","priceCurrency":"USD"}}</script>'
    with pytest.raises(ValueError):parse_shs(html,"RTX 3070","gpu","https://example.com")

def test_shs_date_and_market_unknown_remain_unknown():
    html='<script id="product-jsonld" type="application/ld+json">'+json.dumps({"@type":"Product","name":"NVIDIA RTX 3070","description":"Used NVIDIA RTX 3070 averages $220 on eBay.","offers":{"priceCurrency":"USD","lowPrice":100,"highPrice":300,"offerCount":100}})+'</script>'
    r=parse_shs(html,"RTX 3070","gpu","https://example.com")
    assert r["mid"]==220 and r["data_date"] is None and r["market"]=="unknown"

def test_eur_conversion_and_asking_sold_separation():
    objs=[{"@type":"Product","dateModified":"2026-10-02","offers":{"priceCurrency":"EUR","lowPrice":100,"highPrice":200,"offerCount":10}},
          {"@type":"FAQPage","mainEntity":[{"acceptedAnswer":{"text":"The global median sold price is €150 from 20 recent sales."}}]}]
    html='<script type="application/ld+json">'+json.dumps(objs)+'</script>'
    rows=parse_pcwatch(html,"RTX 3070","gpu","https://example.com",{"rate":1.1,"date":"2026-10-02"})
    assert {r['price_kind'] for r in rows}=={'sold','asking'}
    assert rows[0]['mid']==pytest.approx(165)
    assert rows[0]['market']=='global'
    assert rows[0]['data_date']=='2026-10-02'

def test_api_approval_commit_and_test_data_hidden(client,db):
    ident=db.upsert(item(),is_test=True);evaluate(db,ident)
    assert client.get('/api/listings').json()['total']==0
    response=client.post(f'/api/listings/{ident}/decision',json={'decision':'reject'})
    assert response.status_code==200 and response.json()['review_decision']=='reject'
    assert client.post(f'/api/listings/{ident}/decision',json={'decision':'garbage'}).status_code==422
    assert client.post('/api/backup',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==403

def test_manual_price_correction_and_clear(client,db):
    ident=db.upsert(item(raw_price='$1',price=1),is_test=True);evaluate(db,ident)
    d=client.put(f'/api/listings/{ident}/overrides',json={'price':50,'estimate_mid':200}).json()
    assert d['valuation']['price_type']=='manual' and d['valuation']['profits']['mid'] is not None
    d=client.put(f'/api/listings/{ident}/overrides',json={'price':None,'estimate_mid':None}).json()
    assert d['valuation']['profits']['mid'] is None

def test_backup_survives_live_database_change(db):
    ident=db.upsert(item(),is_test=True);db.decide(ident,'keep')
    path=db.backup();db.decide(ident,'reject')
    with sqlite3.connect(path) as backup:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert backup.execute('SELECT review_decision FROM listings').fetchone()[0]=='keep'

def test_source_failure_retains_estimates(db,monkeypatch):
    prices=PriceService(db)
    prices.import_reference({'category':'gpu','model':'RTX 3070','low':180,'mid':200,'high':240,'currency':'USD','source':'test fixture','source_url':'https://example.com','price_kind':'sold','market':'US'})
    db.execute("INSERT INTO price_jobs(category,model) VALUES ('gpu','RTX 3070')")
    monkeypatch.setattr(prices,'fetch',lambda url: (_ for _ in ()).throw(PermissionError('blocked')))
    result=prices.refresh(jobs_only=True)
    assert result['status']=='failed'
    ident=db.upsert(item(),is_test=True)
    assert evaluate(db,ident)['reference']['mid']==200

def test_settings_costs_and_frequency_validation():
    import copy
    valid=copy.deepcopy(DEFAULT);validate_config(valid)
    valid['costs']['pickup']=10;validate_config(valid)
    valid['interval_minutes']=1
    with pytest.raises(ValueError):validate_config(valid)


def test_recovery_login_isolated_and_uncontrolled(db,monkeypatch):
    from radar.collector import Collector
    from unittest.mock import Mock
    import radar.collector as module
    old=db.directory/'browser';old.mkdir();(old/'session-marker').write_text('preserve')
    control=db.directory/'chrome-control.json';control.write_text('{}')
    collector=Collector(db)
    collector.context=Mock();collector.page=Mock()
    collector.page.is_closed.return_value=False
    launched=[]
    process=Mock();process.pid=12345;process.poll.return_value=None
    monkeypatch.setattr(module.subprocess,'Popen',lambda args,**kwargs:(launched.append(args) or process))
    collector.recover_login()
    args=launched[0]
    assert not any('--remote-debugging' in arg or '--no-sandbox' in arg or '--enable-automation' in arg for arg in args)
    assert str(old) not in args
    assert (old/'session-marker').read_text()=='preserve'
    assert db.setting('browser_profile').startswith('browser-login-')
    assert not control.exists()
    assert db.setting('location_confirmation') is None
    assert collector.paused and collector.state['status']=='needs_login'


def test_successful_browser_profile_survives_restart_and_db_restore(db):
    from radar.collector import Collector
    profile='browser-login-123456'
    original=db.directory/profile
    original.mkdir();(original/'session-marker').write_text('keep-login')
    Collector(db).save_profile(profile)
    # Simulate restoring a database whose settings predate successful login.
    db.set_setting('browser_profile','browser')
    restarted=Collector(db)
    assert restarted.saved_profile()==original
    assert db.setting('browser_profile')==profile
    assert (original/'session-marker').read_text()=='keep-login'


def test_actual_chinese_marketplace_description_boundaries():
    from radar.collector import description_from_text
    text='Gaming PC\nUS$ 500\n发消息\n详细信息\n商品状况\n二手 - 状况良好\nRyzen 5600X, RTX 3070\nNo SSD included\nSan Diego, CA · 我们只提供大概位置\n卖家信息\nPrivate seller\n发送'
    assert description_from_text(text)=='Ryzen 5600X, RTX 3070\nNo SSD included'
    assert description_from_text('login page')==''


def test_catalog_prices_no_sample_no_fake_dates():
    from radar.catalog_prices import parse_catalog_prices
    html='<p>from verified eBay sold listings</p><div>LAST REFRESHSep 26, 2026</div><ul class="modelIndexList"><li><a href="/market-prices/nvme-ssd/1tb">Used 1TB NVMe M.2 SSD price</a><b>$100</b></li></ul>'
    row=parse_catalog_prices(html,'storage','https://www.getpcparts.com/market-prices/nvme-ssd')[0]
    assert row['model']=='NVMe SSD 1TB' and row['data_date']=='2026-09-26'
    assert row['market']=='unknown' and row['sample_count'] is None
    assert row['low']==75 and row['price_kind']=='sold'
    with pytest.raises(ValueError):parse_catalog_prices(html+'<p>sample data</p>','storage','https://example.com')


def test_city_approximation_does_not_exclude_confirmed_distance(db):
    nearby=distance(item(location='CASan Diego'),DEFAULT)
    assert nearby['confidence']=='city' and nearby['miles'] is not None
    assert 'GeoNames' in nearby['method']
    far=db.upsert(item(location='CALos Angeles',price=5,raw_price='$5'),is_test=True)
    v=evaluate(db,far)
    assert v['distance']['miles']>20 and v['distance']['confidence']=='city'
    assert db.get_listing(far)['screening_result']=='check'
    assert distance(item(location='unknown'),DEFAULT)['miles'] is None


def test_backup_is_unique_and_windows_handles_closed(db):
    first=db.backup();second=db.backup()
    assert first!=second
    temporary=first.with_suffix('.moved')
    first.rename(temporary);temporary.rename(first)


def test_vr_bundle_is_not_pc_parts_bundle(db):
    ident=db.upsert(item(title='Meta Quest 3 512GB VR Headset Bundle',price=390,raw_price='$390'),is_test=True)
    evaluate(db,ident)
    assert db.get_listing(ident)['screening_result']=='excluded'
    assert recognize('NZXT White Computer Case Fans - Set of 4')['category']=='cooler'


def test_manual_model_baseline_wins_and_profit_is_single_value(db):
    service=PriceService(db)
    base={'category':'gpu','model':'RTX 5080','currency':'USD','source_url':'http://127.0.0.1:8765/api/prices','market':'local'}
    service.import_reference({**base,'low':1100,'mid':1100,'high':1100,'price_kind':'manual','confidence':'manual','source':'user baseline'})
    service.import_reference({**base,'low':1800,'mid':2200,'high':2600,'price_kind':'sold','market':'US','confidence':'medium','source':'automatic source'})
    ident=db.upsert(item(title='RTX 5080 graphics card',price=900,raw_price='$900'),is_test=True)
    v=evaluate(db,ident)
    assert v['point_based'] and v['resale_estimate']==1100
    assert v['expected_profit']==185 and v['max_offer']==1065
    assert db.get_listing(ident)['screening_result']=='check'
    db.decide(ident,'keep')
    db.upsert(item(title='RTX 5080 graphics card',price=1090,raw_price='$1090'))
    v=evaluate(db,ident)
    assert v['expected_profit']==-5 and db.get_listing(ident)['screening_result']=='excluded'
    assert db.get_listing(ident)['review_decision']=='keep'


def test_unprofitable_coarse_listing_not_in_default_queue(db,client):
    ident=db.upsert(item(title='desktop computer',price=350,raw_price='$350'),is_test=False)
    v=evaluate(db,ident)
    assert v['expected_profit']<20 and db.get_listing(ident)['screening_result']=='price_review'
    assert client.get('/api/listings?view=pending').json()['total']==0
    assert client.get('/api/listings?view=excluded').json()['total']==0
    assert client.get('/api/listings?view=price_review').json()['total']==1


@pytest.mark.parametrize('title',[
 'VariDesk Tall 40 Standing Desk Converter','VIVO Black Desk Riser','Ergodox EZ Glow',
 'Gator G-MONITOR2-GO22 Flat Screen Monitor Case','Hardcase for Shipping Electronics',
 'Computer Desk Workstation','PC Parts & Peripherals','Gaming PC case','Keyboard for gaming PC',
 'Gigabyte RTX3080 Gaming OC','Corsair RM750e 80+ Gold','NZXT Kraken Elite 360 Aio',
 'Gaming Monitor','Synology RackStation RS816','Mac mini','Lenovo IdeaCentre AIO',
 'Acer swift 16 AI','Unidentified item','Gaming laptop RTX 5080'])
def test_pc_only_rejects_real_noise(title):
    from radar.scope import desktop_admission
    assert not desktop_admission(title,'compatible with gaming PC Ryzen 5600X, DDR4 RAM, SSD')[0]

@pytest.mark.parametrize('title',[
 'Gaming desktop','gaming pc rtx 3060','Desktop Computers','Dell Optiplex 7050',
 'barebones PC no GPU','HP Omen gaming PC','Custom built PC Ryzen 5600X',
 'Gaming PC Setup - Ryzen 9 5900X, RX 7800 XT, 32GB RAM, Monitor',
 'Mini PC','台式电脑主机'])
def test_pc_only_allows_actual_towers(title):
    from radar.scope import desktop_admission
    assert desktop_admission(title)[0]


def test_scope_reclassifies_existing_noise_without_losing_decisions(db,client):
    ident=db.upsert(item(title='Gaming PC case',price=5,raw_price='$5'),is_test=False)
    db.decide(ident,'keep')
    config=db.setting('config');config['collection_scope']='pc_only';db.set_setting('config',config)
    evaluate(db,ident)
    assert db.get_listing(ident)['review_decision']=='keep'
    assert db.get_listing(ident)['screening_result']=='excluded'
    assert client.get('/api/listings?view=keep').json()['total']==0
    assert client.get('/api/listings?view=all').json()['total']==1


@pytest.mark.parametrize('title,category',[
 ('Gigabyte RTX3080 Gaming OC','gpu'),('RX 6500 XT 4 GB FOR SALE','gpu'),
 ('Corsair RM750e 80+ Gold','psu'),('NZXT Kraken Elite 360 Aio','cooler'),
 ('Lian Li LANCOOL 207 Black','case'),('PC case empty','case'),
 ('TeamGroup 16GB (2x8GB) DDR4 2400MHz RAM','ram'),
 ('HDD hard drive 2TB','storage'),('NVMe SSD 1TB','storage'),
 ('CPU processor','cpu'),('B550 motherboard','motherboard'),
 ('computer parts lot','bundle'),('Gaming desktop','pc')])
def test_hardware_gate_preserves_independent_parts(title,category):
    from radar.scope import hardware_admission
    allowed,_,kind=hardware_admission(title)
    assert allowed and kind==category
    assert recognize(title)['category']==category

@pytest.mark.parametrize('title',[
 'VIVO Black Desk Riser','Ergodox EZ Glow','Hardcase for Shipping Electronics',
 'Gator G-MONITOR2-GO22 Flat Screen Monitor Case','Monitor Dell',
 'Standing Desk Converter','Ikea Micke - need gone ASAP','Behringer Mixer',
 '1989 Topps Baseball EMPTY Wax Display Box','Unidentified item'])
def test_hardware_gate_cannot_be_opened_by_description_compatibility(title):
    from radar.scope import hardware_admission
    assert not hardware_admission(title,'Compatible with gaming PC RTX 5080, Ryzen 5600X, DDR4 RAM')[0]


def test_description_never_selects_a_heading_in_recommendations():
    from radar.collector import description_from_text
    text="RAM kit\nUS$ 630\n详细信息\n商品状况\n全新\n64GB total (2 x 32GB), tested\nSan Diego, CA · 我们只提供大概位置\n卖家信息\n今日精选\nDescription\nCASan Marcos\nUS$ 23995\nBMW M550i"
    assert description_from_text(text,'RAM kit')=='64GB total (2 x 32GB), tested'
    assert description_from_text('RAM kit\nUS$ 630\n今日精选\nDescription\nWrong recommendation','RAM kit')==''
    assert description_from_text(text,'Other listing')==''

@pytest.mark.parametrize('label,expected',[
 ('64GB (2x32GB) DDR5 RAM','DDR5 64GB'),
 ('16GB (2x8GB) DDR4 RAM','DDR4 16GB'),
 ('2x32GB DDR5 RAM','DDR5 64GB'),
 ('DDR4 RAM 16GB','DDR4 16GB')])
def test_memory_kit_total_capacity_not_multiplied_twice(label,expected):
    assert recognize(label)['model']==expected


def test_contamination_repair_keeps_manual_decision_and_clean_sources(db,client):
    bad='CASan Marcos\nUS$ 23995\nBMW M550i\nCAEscondido\nUS$ 375\nMotherboard'
    ident=db.upsert(item(title='DDR5 RAM 64GB (2x32GB)',description=bad),is_test=True)
    db.decide(ident,'keep')
    clean=db.upsert({**item(title='DDR4 RAM 16GB',description='Tested 16GB kit (2x8GB), works.'),'url':'https://www.facebook.com/marketplace/item/987654321/'},is_test=True)
    response=client.post('/api/collector/repair-descriptions')
    assert response.status_code==200 and response.json()['fixed']==[ident]
    repaired=db.get_listing(ident)
    assert repaired['description']=='' and repaired['review_decision']=='keep'
    assert repaired['raw']['description_status']=='contamination_cleared'
    assert repaired['model']=='DDR5 64GB'
    assert db.get_listing(clean)['description']=='Tested 16GB kit (2x8GB), works.'
    assert db.query("SELECT old_value FROM audit WHERE action='description_repair'")[0]['old_value']==bad


def test_title_capacity_wins_over_unrelated_description_comparison():
    assert recognize('DDR5 64GB RAM','Upgraded from my old 2x16GB kit')['model']=='DDR5 64GB'


def test_missing_description_does_not_use_later_similar_listing():
    from radar.collector import description_from_text
    text='RTX 3070\nUS$ 200\n相似商品\nDescription\nA different item'
    assert description_from_text(text,'RTX 3070')==''
def test_location_language_switch_retains_postal_evidence():
    from radar.collector import location_evidence_matches
    selected={'postal_code':'92121','selected':'圣迭戈'}
    assert location_evidence_matches('Location: San Diego, California, Within 20 mi',selected,'92121',20)==(True,True)
    assert location_evidence_matches('Location: Los Angeles, Within 20 mi',selected,'92121',20)==(False,True)
    assert location_evidence_matches('Location: San Diego, Within 120 mi',selected,'92121',20)==(True,False)
    assert location_evidence_matches('Location: San Diego, Within 20 mi',{},'92121',20)==(False,True)
def test_branded_desktop_specs_are_not_standalone_ram():
    title='Alienware Area R4 i7-7800X X Serie 6cores 3.5ghz 32GB RAM 512GB NVMe+2TB HDD W11 GTX1070 card'
    assert recognize(title)['category']=='pc'
    assert recognize('Alienware Area R4 motherboard')['category']=='motherboard'
    assert recognize('Alienware Aurora RAM DDR4 32GB')['category']=='ram'

def test_detail_budget_prioritizes_new_missing_stale_and_changed():
    from radar.collector import detail_candidates
    old={'fresh':'2026-10-03','stale':'2026-10-01','missing':None,'changed':'2026-10-03'}
    items={'fresh':{},'stale':{},'missing':{},'new':{},'changed':{}}
    assert detail_candidates(items,old,'2026-10-02',{'changed'})==['new','missing','stale','changed']
def test_whole_pc_uses_each_storage_capacity_not_gpu_vram(db):
    ident=db.upsert(item(title='Gaming PC RTX 2070 Super 8GB',description='Intel Core i7-11700F\n16GB XPG Gaming D10 DDR4 RAM\n512GB SSD\n2TB HDD\n650W PSU'),is_test=True)
    val=evaluate(db,ident)
    parts={p['model']:p for p in val['parts']}
    assert 'DDR4 16GB' in parts and 'SSD 512GB' in parts and 'HDD 2TB' in parts
    assert parts['SSD 512GB']['estimate']['mid']==20
    assert parts['HDD 2TB']['estimate']['mid']>20
    assert val['resale_estimate']==round(sum(p['estimate']['mid'] for p in val['parts']),2)

def test_nvme_ssd_repeated_description_not_counted_twice():
    parts=recognize('Gaming PC 512GB NVMe','Installed 512GB SSD NVMe')['components']
    assert len([p for p in parts if p['category']=='storage'])==1

def test_negative_single_source_goes_to_price_review_and_uses_mid(db):
    PriceService(db).import_reference({'category':'gpu','model':'RTX 2070 Super','low':76,'mid':192,'high':350,'currency':'USD','source':'Second Hand Silicon','source_url':'https://www.secondhandsilicon.com/product/nvidia-rtx-2070-super','price_kind':'sold','market':'unknown'})
    ident=db.upsert(item(title='RTX 2070 Super GPU',price=250,raw_price='$250'),is_test=True)
    val=evaluate(db,ident)
    assert val['resale_estimate']==192 and val['expected_profit']==-73
    assert db.get_listing(ident)['screening_result']=='price_review'

def test_aggregators_same_ebay_market_do_not_count_as_two(db):
    service=PriceService(db)
    for source,url in [('Second Hand Silicon','https://www.secondhandsilicon.com/product/nvidia-rtx-2070-super'),('Get PC Parts weekly','https://www.getpcparts.com/test')]:
        service.import_reference({'category':'gpu','model':'RTX 2070 Super','low':76,'mid':192,'high':350,'currency':'USD','source':source,'source_url':url,'price_kind':'sold','market':'US','data_date':'2026-10-03','sample_count':10})
    ident=db.upsert(item(title='RTX 2070 Super GPU',price=250,raw_price='$250'),is_test=True)
    v=evaluate(db,ident)['price_verification']
    assert v['websites']==2 and v['sold_markets']==1 and not v['verified']

def test_motherboard_chipset_peer_does_not_include_b550(db):
    from radar.domain import reference
    service=PriceService(db)
    for model,price in [('B560 LGA1200 mATX',76),('B550 AM4 ATX',200)]:
        service.import_reference({'category':'motherboard','model':model,'low':price,'mid':price,'high':price,'currency':'USD','source':'test fixture','source_url':'https://example.com/fixture','price_kind':'sold','market':'US'})
    r=reference(db,'motherboard','B560M')
    assert r['mid']==76 and len(r['evidence'])==1
def test_two_comparable_sold_markets_use_single_median_not_asking(db):
    from radar.domain import reference
    service=PriceService(db)
    for source,url,mid,kind in [('market one','https://example.com/sold',180,'sold'),('market two','https://example.org/sold',220,'sold'),('asking listing','https://example.net/asking',600,'asking')]:
        service.import_reference({'category':'gpu','model':'RTX 2070 Super','low':mid*.8,'mid':mid,'high':mid*1.2,'currency':'USD','source':source,'source_url':url,'price_kind':kind,'market':'US','data_date':'2026-10-03','sample_count':10})
    r=reference(db,'gpu','RTX 2070 Super')
    assert r['mid']==200 and r['price_verification']['verified']
    assert len(r['evidence'])==3
@pytest.mark.parametrize('title,category',[
    ('HP Z840 Workstation, Computer, HP z840','pc'),('PC (Dell Precision 5820)','pc'),
    ('Dell Vostro 3681 i7-10700 32GB RAM','pc'),('Lenovo IdeaCentre AIO 520-24ICB','pc'),
    ('Pc','pc'),('PC with monitors and keyboards','pc'),
    ('intel core ultra 7 265','cpu'),('Intel Computer Processors LGA 1511','cpu'),
    ('Mini ITX case and liquid cooling setup','case'),('Cooler Master Elite 110 Mini-ITX Case','case'),
    ('Lian Li 207M Mesh PowerSpec','case'),('2 PC cases $20 each','case')])
def test_historical_target_titles_not_missed(title,category):
    from radar.scope import hardware_admission
    assert hardware_admission(title)[0] and recognize(title)['category']==category
