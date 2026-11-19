"""Regression checks: host Time4VPS deploy must coexist with RegionalResearch."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "deploy" / "time4vps"


def test_service_uses_dedicated_loopback_port_and_single_worker():
    unit = (BASE / "promoeditor.service").read_text()
    assert "--host 127.0.0.1 --port 18080 --workers 1" in unit
    assert "User=promoeditor" in unit
    assert "EnvironmentFile=/etc/promoeditor/promoeditor.env" in unit
    assert "WorkingDirectory=/opt/promoeditor" in unit
    assert "ReadWritePaths=/var/lib/promoeditor/jobs" in unit
    assert "ProtectSystem=strict" in unit
    assert "NoNewPrivileges=true" in unit
    assert "MemoryMax=800M" in unit
    assert ":10000" not in unit


def test_scripts_are_shell_parseable():
    for f in ["preflight.sh", "install.sh", "configure_caddy.sh", "update.sh", "switch_to_password_login.sh", "stage_review.sh"]:
        subprocess.run(["bash", "-n", str(BASE / f)], check=True)


def test_host_configuration_is_additive_and_authenticates_every_route():
    caddy = (BASE / "configure_caddy.sh").read_text()
    assert "read -r -p 'PromoEditor HTTPS hostname" in caddy
    assert "getent ahostsv4" in caddy
    assert "basic_auth {" not in caddy
    assert "Password-only app login is not ready" in caddy
    assert "401" in caddy
    assert "reverse_proxy 127.0.0.1:18080" in caddy
    assert "max_size 72MB" in caddy
    assert "import /etc/caddy/promoeditor.caddy" in caddy
    assert "cp -p /etc/caddy/Caddyfile" in caddy
    assert "caddy validate --config /etc/caddy/Caddyfile" in caddy
    assert "systemctl reload caddy" in caddy
    assert "0.0.0.0:18080" not in caddy


def test_scripts_dont_reconfigure_or_restart_other_app():
    for file in BASE.glob("*.sh"):
        content = file.read_text()
        assert "systemctl restart regionalresearch" not in content
        assert "systemctl stop regionalresearch" not in content
        assert "rm -rf /opt/regionalresearch" not in content
        assert "tailscale serve" not in content
        assert "docker compose" not in content


def test_config_contains_no_real_secrets():
    sample = (BASE / "promoeditor.env.example").read_text()
    assert "OPENAI_API_KEY=\n" in sample
    assert "PROMO_REQUESTS_PER_HOUR=" in sample
    assert "PROMO_DATA_DIR" not in sample  # fixed in systemd unit


def test_pr_preview_is_isolated_rate_limited_and_rollback_free():
    script = (BASE / "stage_review.sh").read_text()
    assert "STAGE=/var/lib/promoeditor/pr58-preview" in script
    assert "SOURCE=\"$STAGE/source\"" in script
    assert "JOBS=\"$STAGE/jobs\"" in script
    assert '[[ "$current" == "$TARGET" ]]' in script
    assert "available_kib < needed*1024" in script
    assert "required" not in script or "needed=1152" in script
    assert "needed=1400" in script
    assert "rr_bytes < 640*1024*1024" in script
    assert "MemoryMax=480M" in script
    assert "MemoryHigh=340M" in script
    assert "RuntimeMaxSec=3600" in script
    assert "Restart=no" in script
    assert "PROMO_AUTH_ENABLED=0" in script
    assert "OPENAI_API_KEY=" in script
    assert '"ReadWritePaths=$JOBS"' in script
    assert '--host 127.0.0.1 --port "$PORT"' in script
    assert "ssh -N -L 18081:127.0.0.1:18081" in script
    assert "EnvironmentFile=$ENV_FILE" in script
    assert "systemctl restart" not in script
    assert "systemctl stop promoeditor" not in script.replace(
        "systemctl stop promoeditor-preview", "")
    assert "docker compose" not in script
    assert "/opt/promoeditor/.venv/bin/python" in script
    assert "git -C /opt/promoeditor reset" not in script
