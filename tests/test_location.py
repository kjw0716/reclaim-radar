import pytest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from radar.app import create_app
from radar.collector import Collector, location_evidence_matches
from radar.db import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path)


def test_preferences_survive_restart_edit_and_delete(db):
    client=TestClient(create_app(db,background=False))
    saved={"selected_label":" San Diego, California ","radius_miles":25,"auto_restore":True}
    assert client.put('/api/collector/location-preferences',json=saved).status_code==200
    restarted=TestClient(create_app(Database(db.directory),background=False))
    prefs=restarted.get('/api/collector/location-preferences').json()
    assert prefs['selected_label']=='San Diego, California'
    assert prefs['radius_miles']==25 and prefs['auto_restore']
    saved.update(selected_label='La Jolla, California',radius_miles=20)
    assert restarted.put('/api/collector/location-preferences',json=saved).status_code==200
    assert db.setting('location_confirmation') is None
    assert restarted.delete('/api/collector/location-preferences').status_code==200
    again=TestClient(create_app(Database(db.directory),background=False))
    prefs=again.get('/api/collector/location-preferences').json()
    assert not prefs['auto_restore'] and prefs['selected_label']==''
    assert db.setting('location_selection') is None
    assert db.setting('collector_paused')
    assert again.get('/api/status').json()['location_preferences']==prefs


def test_radius_change_keeps_postal_evidence(db):
    app=create_app(db,background=False)
    client=TestClient(app)
    selected={'postal_code':'92121','selected':'San Diego','postal_option':'San Diego 92121','method':'postal_suggestion'}
    db.set_setting('location_selection',selected)
    config=db.setting('config');config['radius_miles']=30
    assert client.put('/api/config',json=config).status_code==200
    assert db.setting('location_selection')==selected
    assert not app.state.collector.state['location_confirmed']


@pytest.mark.parametrize('radius',[0,101,20.5,True])
def test_invalid_radius_does_not_overwrite_preferences(db,radius):
    client=TestClient(create_app(db,background=False))
    assert client.put('/api/collector/location-preferences',json={'radius_miles':radius}).status_code==422
    assert db.setting('config')['radius_miles']==20


def page_for(collector,label,body=''):
    collector.browser=Mock()
    collector.page=Mock()
    collector.page.url='https://www.facebook.com/marketplace/'
    collector.page_status=Mock(return_value=('marketplace',body))
    el=Mock();el.get_attribute.return_value=label;el.inner_text.return_value=label
    collector.page.get_by_role.return_value.all.return_value=[el] if label else []
    collector.page.locator.return_value.all.return_value=[]
    return collector


def test_drift_restores_once_and_rechecks_actual_page(db):
    db.set_setting('location_selection',{'postal_code':'92121','selected':'San Diego'})
    collector=page_for(Collector(db),'Location: San Diego, California, Within 19 mi')
    calls=[]
    def restore():
        calls.append(True)
        page_for(collector,'Location: San Diego, California, Within 20 mi')
        collector._verify(restore=False)
    collector._setup_location=restore
    collector.verify()
    assert len(calls)==1
    assert collector.state['status']=='ready'
    assert db.setting('location_confirmation')['radius_miles']==20


def test_failed_restore_does_not_loop_or_claim_ready(db):
    collector=page_for(Collector(db),'Location: San Diego, Within 19 mi')
    collector._setup_location=Mock(side_effect=lambda:collector._verify(restore=False))
    collector.verify()
    collector._setup_location.assert_called_once()
    assert not collector.state['location_confirmed']
    assert db.setting('location_confirmation') is None


def test_deleted_memory_never_auto_applies_or_uses_product_text(db):
    db.set_setting('location_auto_restore',False)
    db.set_setting('location_selection',None)
    collector=page_for(Collector(db),'',body='Seller 92121 Within 20 mi')
    collector._setup_location=Mock()
    collector.verify()
    collector._setup_location.assert_not_called()
    assert not collector.state['location_confirmed']
    assert location_evidence_matches('San Diego Within 20 mi',None,'92121',20)==(False,True)


def test_checkpoint_does_not_fill_location(db):
    collector=page_for(Collector(db),'')
    collector.page_status=Mock(return_value=('verification','Enter security code'))
    collector._setup_location=Mock()
    from radar.collector import Attention
    with pytest.raises(Attention):collector.verify()
    collector._setup_location.assert_not_called()
    collector.page.goto.assert_not_called()


def test_startup_resumes_with_memory_without_old_confirmation(db,monkeypatch):
    db.set_setting('location_selection',{'postal_code':'92121','selected':'San Diego'})
    import radar.app as module
    monkeypatch.setattr(module.threading.Thread,'start',lambda self:None)
    monkeypatch.setattr(module.threading.Thread,'join',lambda self,**kwargs:None)
    app=create_app(db)
    import asyncio
    async def startup(app,expected):
        async with app.router.lifespan_context(app):
            if expected:assert app.state.collector.commands.get_nowait()[0]=='verify'
            else:assert app.state.collector.commands.empty()
    asyncio.run(startup(app,True))
    db.set_setting('collector_paused',True)
    app=create_app(db)
    asyncio.run(startup(app,False))


def test_radius_choice_is_exact_not_similar(db):
    collector=Collector(db)
    collector.page=Mock()
    dialog=Mock()
    control=dialog.get_by_role.return_value
    control.count.return_value=1
    control.first.evaluate.return_value='div'
    option=collector.page.get_by_role.return_value
    option.count.return_value=1
    assert collector.set_radius(dialog,20)
    pattern=collector.page.get_by_role.call_args.kwargs['name']
    assert pattern.fullmatch('20 miles')
    assert not pattern.fullmatch('120 miles')
    assert not pattern.fullmatch('20 km')
    option.click.assert_called_once()
