from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from radar.db import Database
from radar.app import create_app
from radar.availability import AvailabilityScan, listing_availability
from radar.collector import Collector


def local(day=18,hour=9,minute=0):
    return datetime(2026,10,day,hour,minute,tzinfo=ZoneInfo('America/Los_Angeles'))


@pytest.fixture
def db(tmp_path):return Database(tmp_path)


def item(db,ident='123456789',decision='pending',test=False):
    row={'url':f'https://www.facebook.com/marketplace/item/{ident}/','title':'RTX 3070 graphics card','price':100,'raw_price':'$100'}
    db.upsert(row,'graphics card',is_test=test)
    if decision!='pending':db.decide(ident,decision)
    return row


@pytest.mark.parametrize('badge',['Sold','Sold out','已售出','已賣出','售罄','This listing has been sold.','This item is sold'])
def test_explicit_item_status(badge):
    assert listing_availability('RTX 3070 graphics card\n$100\n'+badge+'\nDetails\nUsed','RTX 3070 graphics card')=='sold'


def test_prefixed_title_and_unicode_whitespace():
    assert listing_availability('Sold · RTX 3070 graphics card\n$100','RTX 3070 graphics card')=='sold'
    assert listing_availability('RTX 3070\u00a0graphics card\n$100\nSold','RTX 3070 graphics card')=='sold'
    assert listing_availability('Sold\n\u00a0\n · gaming pc rtx 3060\n$650\nListed 2 weeks ago in El Cajon, CA\nSave\nShare\nDetails\nUsed','gaming pc rtx 3060')=='sold'
    assert listing_availability('Pending\n\u00a0\n · gaming pc rtx 3060\n$650\nDetails','gaming pc rtx 3060')=='pending'


@pytest.mark.parametrize('text',[
    'RTX 3070 graphics card\n$100\nDetails\nSold',
    'RTX 3070 graphics card\n$100\nRelated searches\nSold',
    'RTX 3070 graphics card\n$100\nSeller information\nSold',
    'Other product\n$100\nSold',
    'RTX 3070 graphics card\n$100\nPending',
    'RTX 3070 graphics card\n$100\nNot sold yet',
    'RTX 3070 graphics card\n$100\nSold separately',
    'This listing is no longer available\nRTX 3070 graphics card\nSold',
    'RTX 3070 graphics card\n$100\nDetails\nSold out elsewhere',
])
def test_ambiguous_or_unrelated_sold_never_deletes(text):
    assert listing_availability(text,'RTX 3070 graphics card')!='sold'


def test_schedule_full_inventory_restart_and_once_daily(db):
    for i in range(25):item(db,str(123456789+i),decision=['pending','keep','reject'][i%3])
    item(db,'999999999',test=True)
    scan=AvailabilityScan(db)
    assert not scan.start_due(local(hour=8,minute=59))
    state=scan.start_due(local())
    assert state['total']==25
    scan.record(scan.next_item()['id'],'available')
    restarted=AvailabilityScan(Database(db.directory))
    assert restarted.state()['checked']==1
    assert restarted.start_due(local())['checked']==1
    while restarted.next_item():restarted.record(restarted.next_item()['id'],'available')
    assert restarted.state()['status']=='completed'
    assert restarted.start_due(local())['checked']==25
    assert restarted.start_due(local(day=19))['checked']==0


def test_delete_removes_all_listing_history_and_prevents_reingest(db):
    row=item(db,decision='reject')
    db.upsert({**row,'price':80})
    scan=AvailabilityScan(db);scan.start_due(local())
    result=scan.record('123456789','sold')
    assert result['deleted']==1 and result['checked']==1 and result['status']=='completed'
    for table in ['listings','hits','audit','snapshots','availability_queue']:
        assert not db.query('SELECT * FROM '+table)
    assert db.upsert(row) is None
    assert not db.query('SELECT * FROM listings')
    # Retry after a crash/duplicate callback cannot double count.
    assert scan.record('123456789','sold')['deleted']==1


def test_keep_decision_rechecked_at_deletion_and_sold_badge_persists(db):
    item(db)
    scan=AvailabilityScan(db);scan.start_due(local())
    pending=scan.next_item()
    db.decide(pending['id'],'keep')
    result=scan.record(pending['id'],'sold')
    assert result['deleted']==0 and result['kept_sold']==1
    assert db.get_listing(pending['id'])['availability_status']=='sold'
    scan.start_due(local(day=19))
    scan.record(pending['id'],'unknown')
    assert db.get_listing(pending['id'])['availability_status']=='sold'
    db.decide(pending['id'],'reject')
    scan.start_due(local(day=20));scan.record(pending['id'],'sold')
    assert not db.query('SELECT * FROM listings')


def test_unknown_and_pending_are_retained(db):
    for i in range(2):item(db,str(123456789+i))
    scan=AvailabilityScan(db);scan.start_due(local())
    scan.record('123456789','unknown');scan.record('123456790','pending')
    assert scan.state()['unknown']==1 and scan.state()['deleted']==0
    assert len(db.query('SELECT * FROM listings'))==2


def test_schedule_api_validation_persistence_and_disabling(db):
    app=create_app(db,background=False);client=TestClient(app)
    path='/api/collector/availability-schedule'
    assert client.put(path,json={'time':'25:99'}).status_code==422
    assert client.put(path,json={'time':'10:30','enabled':False}).status_code==200
    app=create_app(Database(db.directory),background=False)
    assert TestClient(app).get('/api/status').json()['availability']['schedule']['time']=='10:30'
    item(db)
    assert not app.state.collector.availability.start_due(local(hour=11))
    assert TestClient(app).post('/api/collector/check-sold').status_code==400


def collector_for(db,text,url=None):
    row=item(db)
    collector=Collector(db);collector.browser=Mock();collector.page=Mock()
    collector.page.url=url or row['url']
    collector.page_status=Mock(return_value=('marketplace',text))
    collector.context=Mock()
    collector.context.new_page.return_value=collector.page
    collector.page.is_closed.return_value=False
    collector.page.goto.return_value.status=200
    collector.page.locator.return_value.count.return_value=0
    collector.page.locator.return_value.inner_text.return_value=text
    collector.page.get_by_role.return_value.count.return_value=1
    collector.page.get_by_role.return_value.first.inner_text.return_value=text
    collector.availability.start_due(local())
    return collector


def test_worker_requires_matching_item_and_resumes_after_login(db):
    collector=collector_for(db,'RTX 3070 graphics card\n$100\nSold')
    collector.page_status=Mock(return_value=('verification','Enter code'))
    collector.check_availability_next()
    collector.page.goto.assert_not_called()
    assert collector.availability.state()['status']=='attention'
    assert collector.availability.state()['checked']==0
    collector.availability.resume()
    collector.page_status=Mock(return_value=('marketplace','RTX 3070 graphics card\n$100\nSold'))
    collector.check_availability_next()
    assert collector.availability.state()['deleted']==1
    assert collector.state['status']=='ready'


def test_redirect_and_timeout_never_delete(db):
    collector=collector_for(db,'RTX 3070 graphics card\n$100\nSold','https://www.facebook.com/marketplace/item/987654321/')
    collector.check_availability_next()
    assert db.get_listing('123456789')['availability_status']=='unknown'
    collector.availability.start_due(local(day=19))
    collector.page.goto.side_effect=TimeoutError()
    collector.check_availability_next()
    assert db.get_listing('123456789')
    assert collector.availability.state()['deleted']==0


def test_pause_during_navigation_keeps_pending_queue(db):
    collector=collector_for(db,'RTX 3070 graphics card\n$100\nSold')
    collector.page.goto.side_effect=lambda *a,**k:setattr(collector,'paused',True)
    collector.check_availability_next()
    assert collector.availability.state()['checked']==0
    assert collector.availability.next_item()['id']=='123456789'


def test_disabled_schedule_and_dst_wall_clock(db):
    item(db);scan=AvailabilityScan(db)
    db.set_setting('availability_schedule',{'time':'09:00','enabled':False,'timezone':'America/Los_Angeles'})
    assert not scan.start_due(local(hour=12))
    db.set_setting('availability_schedule',{'time':'09:00','enabled':True,'timezone':'America/Los_Angeles'})
    november=datetime(2026,11,1,9,tzinfo=ZoneInfo('America/Los_Angeles'))
    assert scan.start_due(november)['total']==1


def test_manual_trial_does_not_consume_scheduled_run(db):
    item(db);scan=AvailabilityScan(db)
    assert scan.start_due(local(hour=8),force=True)['trigger']=='manual'
    scan.record('123456789','available')
    assert scan.start_due(local(hour=9))['checked']==0
    scan.record('123456789','available')
    assert scan.start_due(local(hour=10))['checked']==1


def test_fast_scan_overlaps_navigations_and_protects_kept(db):
    rows=[item(db,str(123456789+i),decision='keep' if i==1 else 'pending') for i in range(3)]
    collector=Collector(db);collector.browser=Mock();collector.page_status=Mock(return_value=('marketplace',''))
    collector.context=Mock()
    pages=[Mock() for _ in rows]
    collector.context.new_page.side_effect=pages
    events=[]
    for i,page in enumerate(pages):
        page.goto.side_effect=lambda url,idx=i,**kwargs:(events.append(('navigate',idx)) or Mock(status=200))
    def read(page,row):
        assert sum(event[0]=='navigate' for event in events)==3
        events.append(('read',row['id']))
        return 'available' if row['id']=='123456791' else 'sold'
    collector.availability_page_result=Mock(side_effect=read)
    collector.availability.start_due(local())
    collector.check_availability_next()
    state=collector.availability.state()
    assert state['status']=='completed' and state['checked']==3
    assert state['deleted']==1 and state['kept_sold']==1
    for page in pages:
        assert page.goto.call_args.kwargs['wait_until']=='commit'
        page.wait_for_timeout.assert_not_called()
        page.close.assert_called_once()


def test_fast_scan_rate_limit_stops_without_deletion(db):
    collector=collector_for(db,'RTX 3070 graphics card\n$100\nSold')
    collector.page.goto.return_value.status=429
    collector.check_availability_next()
    assert collector.availability.state()['status']=='attention'
    assert collector.availability.state()['checked']==0
    assert collector.availability.next_item()


def test_fast_scan_media_blocking_keeps_script_cache(db):
    collector=collector_for(db,'RTX 3070 graphics card\n$100')
    collector.check_availability_next()
    collector.page.route.assert_not_called()
    session=collector.context.new_cdp_session.return_value
    assert session.send.call_args.args[0]=='Network.setBlockedURLs'
    patterns=session.send.call_args.args[1]['urls']
    assert '*.jpg*' in patterns and '*.woff*' in patterns
    assert not any('.js' in pattern or '.css' in pattern or pattern=='*' for pattern in patterns)
