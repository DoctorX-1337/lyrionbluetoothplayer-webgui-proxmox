import httpx
from fastapi.testclient import TestClient
from app.auth import hash_password, verify_password
from app.config import Config
from app.internal_api import manager_app
from app.web import create_app
from conftest import MAC1


def test_password_hash():
    encoded = hash_password('A secure test password')
    assert verify_password('A secure test password', encoded)
    assert not verify_password('wrong', encoded)
    assert not verify_password('wrong', None)


async def test_internal_api_validation_and_confirmation(manager):
    app = manager_app(manager, lifecycle=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://manager') as client:
        response = await client.post('/api/bluetooth/invalid/connect')
        assert response.status_code == 409
        manager.repo.remember(MAC1)
        response = await client.delete('/api/bluetooth/'+MAC1)
        assert response.status_code == 409
        manager.bluetooth.remove.assert_not_awaited()
        response = await client.delete('/api/bluetooth/'+MAC1+'?confirm=true')
        assert response.status_code == 200
        assert not manager.repo.get(MAC1)
        response = await client.put('/api/settings', json={'lms_host':'bad;command'})
        assert response.status_code == 422
        response = await client.post('/api/services/proxmox/restart')
        assert response.status_code == 409


def test_login_force_change_csrf_and_security_headers(manager):
    app = create_app(manager.config, httpx.ASGITransport(manager_app(manager, lifecycle=False)))
    app.state.auth.initialize('initial-test-pass')
    with TestClient(app) as client:
        assert client.get('/api/status').status_code == 401
        response = client.post('/api/auth/login', json={'username':'admin','password':'initial-test-pass'})
        assert response.status_code == 200
        csrf = response.json()['csrf']
        assert 'HttpOnly' in response.headers['set-cookie']
        assert client.get('/api/status').status_code == 403
        assert client.post('/api/auth/password',json={'old_password':'initial-test-pass','new_password':'changed-test-pass'}).status_code == 403
        response = client.post('/api/auth/password',headers={'x-csrf-token':csrf},json={'old_password':'initial-test-pass','new_password':'changed-test-pass'})
        assert response.status_code == 200
        response = client.get('/api/status')
        assert response.status_code == 200
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['cache-control'] == 'no-store'
        assert 'frame-ancestors' in response.headers['content-security-policy']
        response = client.post('/api/audio/volume', headers={'x-csrf-token':csrf,'origin':'http://evil.local'},json={'value':20})
        assert response.status_code == 403
        assert client.post('/api/audio/volume',headers={'x-csrf-token':csrf},json={'value':40}).status_code == 200
        assert client.get('/api/unknown').status_code == 404
        assert client.get('/secrets.env').status_code == 404
        client.post('/api/auth/logout',headers={'x-csrf-token':csrf})
        assert client.get('/api/status').status_code == 401


def test_login_throttling(manager):
    app = create_app(manager.config, httpx.ASGITransport(manager_app(manager, lifecycle=False)))
    app.state.auth.initialize('test-password')
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post('/api/auth/login',json={'username':'admin','password':'wrong'}).status_code == 401
        assert client.post('/api/auth/login',json={'username':'admin','password':'wrong'}).status_code == 429


def test_auth_disabled_still_requires_csrf(manager):
    assert Config().auth_enabled is False
    manager.config.auth_enabled = False
    app = create_app(manager.config, httpx.ASGITransport(manager_app(manager, lifecycle=False)))
    with TestClient(app) as client:
        session = client.get('/api/auth/session').json()
        assert session['authenticated']
        assert session['auth_enabled'] is False
        assert client.get('/api/status').status_code == 200
        assert client.post('/api/audio/volume',json={'value':40}).status_code == 403
        assert client.post('/api/audio/volume',headers={'x-csrf-token':session['csrf']},json={'value':40}).status_code == 200
