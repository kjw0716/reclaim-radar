import copy
import pytest
from fastapi.testclient import TestClient
from radar.app import create_app, validate_config
from radar.config import DEFAULT
from radar.db import Database
from radar.domain import distance


def test_new_search_center_requires_coordinates_and_invalidates_location(tmp_path):
    db = Database(tmp_path)
    db.set_setting('location_selection', {'postal_code': '92121', 'selected': 'San Diego'})
    db.set_setting('location_confirmation', {'verified': True})
    app = create_app(db, background=False)
    client = TestClient(app)
    config = db.setting('config')
    config['postal_code'] = '10001'
    assert client.put('/api/config', json=config).status_code == 400
    assert db.setting('config')['postal_code'] == '92121'
    config.update(center_lat=40.75, center_lon=-73.99, center_method='Verified ZIP center')
    assert client.put('/api/config', json=config).status_code == 200
    assert db.setting('location_selection') is None
    assert db.setting('location_confirmation') is None
    assert app.state.collector.state['status'] == 'needs_location'
    result = distance({'latitude': 40.75, 'longitude': -73.99}, config)
    assert result['miles'] == 0
    assert Database(tmp_path).setting('config')['postal_code'] == '10001'


@pytest.mark.parametrize('zip_code', ['1234', '123456', 'abcde', 10001, '１２３４５', None])
def test_zip_code_validation(zip_code):
    config = copy.deepcopy(DEFAULT)
    config['postal_code'] = zip_code
    with pytest.raises(ValueError):
        validate_config(config)


def test_production_serves_public_artwork_without_exposing_project(tmp_path, monkeypatch):
    import radar.app as app_module
    root = tmp_path / 'project'
    dist = root / 'frontend/dist'
    (dist / 'demo').mkdir(parents=True)
    (dist / 'assets').mkdir()
    (dist / 'index.html').write_text('<html>Radar</html>')
    (dist / 'favicon.svg').write_text('<svg/>')
    (dist / 'demo/gpu.svg').write_text('<svg/>')
    (root / 'private.txt').write_text('not public')
    monkeypatch.setattr(app_module, 'ROOT', root)
    client = TestClient(create_app(Database(tmp_path / 'db'), background=False))
    assert client.get('/').status_code == 200
    assert client.get('/favicon.svg').headers['content-type'].startswith('image/svg+xml')
    assert client.get('/demo/gpu.svg').status_code == 200
    assert client.get('/private.txt').status_code == 404
    assert client.get('/api/health').json()['app'] == 'reclaim-radar'
