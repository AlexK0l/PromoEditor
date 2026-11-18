"""Safety gates for the shared Time4VPS transactional release.

The CI runner never performs a deployment. All tests inspect shell scripts or
exercise fail-closed invalid-input paths, without touching live applications.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "time4vps"


def test_release_scripts_parse_with_bash_and_reject_no_commit():
    for name in ("safe_release.sh", "memory_report.sh"):
        script = DEPLOY / name
        subprocess.run(["bash", "-n", str(script)], check=True)
    invalid = subprocess.run(
        ["bash", str(DEPLOY / "safe_release.sh")],
        text=True, capture_output=True, check=False,
    )
    assert invalid.returncode != 0
    assert "40-character" in invalid.stderr


def test_pinned_release_has_backup_rollback_and_safe_service_boundary():
    script = (DEPLOY / "safe_release.sh").read_text(encoding="utf-8")
    required = (
        "origin/main", "git -C \"$ROOT\" merge-base --is-ancestor",
        "git -C \"$ROOT\" merge --ff-only",
        "git -C \"$ROOT\" reset --hard \"$previous\"",
        "BACKUP_ROOT=/root/promoeditor-releases",
        "cp -a \"$ROOT/.venv\" \"$backup/venv\"",
        "cp -a \"$backup/venv\" \"$ROOT/.venv\"",
        "PROMO_AUTH_ENABLED=1", "PROMO_AI_IMAGE_CALLS_PER_DAY=0",
        "systemctl stop promoeditor", "systemctl start promoeditor",
        "http://127.0.0.1:18080/login",
        "http://127.0.0.1:18080/api/config",
        "regionalresearch caddy", "switched=1", "switched=0",
    )
    for token in required:
        assert token in script, f"release guard missing: {token}"
    # Never deploy an arbitrary moving origin/main: require EXACT SHA equality.
    assert '[[ "$remote" == "$TARGET" ]]' in script
    assert "Under 1 GiB RAM available" in script
    assert "venv_kib*2 + 524288" in script
    assert script.index("cp -a \"$ROOT/.venv\" \"$backup/venv\"") < \
           script.index("switched=1")
    assert script.index("systemctl stop promoeditor", script.index("switched=1")) < \
           script.index("as_app git -C \"$ROOT\" merge --ff-only")


def test_release_and_report_never_mutate_other_server_services():
    release = (DEPLOY / "safe_release.sh").read_text(encoding="utf-8")
    report = (DEPLOY / "memory_report.sh").read_text(encoding="utf-8")
    for script in (release, report):
        for forbidden in (
            "systemctl restart regionalresearch",
            "systemctl stop regionalresearch",
            "systemctl reload caddy",
            "systemctl restart caddy",
            "systemctl stop caddy",
            "docker compose",
            "/opt/regionalresearch/",
            "/etc/caddy/Caddyfile",
        ):
            assert forbidden not in script
        assert "OPENAI_API_KEY=" not in script
    assert "swapon --show" in report
    assert "memory.events" in report
    assert "MemoryPeak" in report
    assert "memory.stat" in report
    for forbidden in ("git reset", "systemctl restart", "systemctl stop", "apt-get",
                      "pip install", "rm -rf"):
        assert forbidden not in report


def test_release_script_is_explicitly_root_only_and_env_safe():
    script = (DEPLOY / "safe_release.sh").read_text(encoding="utf-8")
    assert '[[ "$EUID" -eq 0 ]]' in script
    assert "umask 077" in script
    assert "Env must have mode 0600" in script
    assert "Env must belong to root" in script
    assert 'install -o root -g root -m 0600 "$ENV_FILE"' in script
    assert "Secret" not in script and ".env.example" not in script
    # The user's images and paid-usage SQLite database are not migrated/deleted.
    assert "/var/lib/promoeditor/jobs" in script
    assert "rm -rf /var/lib/promoeditor" not in script
