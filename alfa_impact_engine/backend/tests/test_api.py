from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get('/api/health')
    assert r.status_code == 200
    assert r.json()['data'] == 'synthetic-only'


def test_company_validation():
    assert client.get('/api/companies/UNKNOWN').status_code == 404


def test_analyze_changes_by_company():
    event = client.get('/api/demo-events').json()[0]
    a = client.post('/api/analyze', json={'company_id': 'DEMO-MFG', 'event': event})
    b = client.post('/api/analyze', json={'company_id': 'DEMO-SVC', 'event': event})
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()['outcome'] == 'POTENTIAL_EXPOSURE'
    assert b.json()['outcome'] == 'NO_CONFIRMED_PATH'
    assert a.json()['paths'][0]['path_status'] == 'HYPOTHETICAL'


def test_bad_event_is_rejected():
    r = client.post('/api/analyze', json={'company_id': 'DEMO-MFG', 'event': {'id': 'a', 'title': 'x', 'channels': ['NOT_REAL']}})
    assert r.status_code == 422
