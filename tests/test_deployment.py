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
