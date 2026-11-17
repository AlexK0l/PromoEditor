from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_public_reverse_proxy_has_authentication():
    caddy=(ROOT/'deploy'/'Caddyfile').read_text(encoding='utf-8')
    assert 'basic_auth {' in caddy
    assert 'reverse_proxy app:8000' in caddy
    assert 'request_body {' in caddy


def test_application_container_does_not_publish_8000():
    compose=(ROOT/'compose.vps.yaml').read_text(encoding='utf-8')
    app_service=compose.split('\n  app:\n',1)[1].split('\n  caddy:\n',1)[0]
    assert 'expose:' in app_service
    assert 'ports:' not in app_service
    assert 'read_only: true' in app_service
    assert 'no-new-privileges:true' in app_service


def test_real_server_env_files_are_ignored():
    ignore=(ROOT/'.gitignore').read_text(encoding='utf-8')
    assert 'deploy/app.env' in ignore
    assert 'deploy/caddy.env' in ignore


def test_docker_healthcheck_uses_unprotected_login_route():
    docker=(ROOT/'Dockerfile').read_text(encoding='utf-8')
    healthcheck=docker.split('HEALTHCHECK ',1)[1].split('\n\nCMD ',1)[0]
    assert "http://127.0.0.1:8000/login" in healthcheck
    assert "/api/config" not in healthcheck


def test_healthcheck_login_works_with_both_auth_modes(monkeypatch):
    """Do not mark a healthy server unhealthy when its private API is protected."""
    from fastapi.testclient import TestClient
    from app import auth,main

    monkeypatch.setenv('PROMO_AUTH_ENABLED','1')
    monkeypatch.setenv('PROMO_PASSWORD_HASH',
                       auth.hash_password('only-a-fake-test-password',
                                          salt=b'test-salt-123456',iterations=300_000))
    monkeypatch.setenv('PROMO_SESSION_SECRET','test-only-'+'x'*52)
    with TestClient(main.app) as client:
        login=client.get('/login',follow_redirects=False)
        assert login.status_code==200
        assert 'Вход в PromoEditor' in login.text
        assert client.get('/api/config',follow_redirects=False).status_code==401
        monkeypatch.setenv('PROMO_AUTH_ENABLED','0')
        assert client.get('/login').status_code==200
