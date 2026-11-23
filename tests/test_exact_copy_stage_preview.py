"""Ensure the exact-copy preview cannot switch the production checkout."""

from pathlib import Path


def test_exact_copy_preview_is_branch_pinned_and_isolated():
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy/time4vps/stage_exact_copy_review.sh").read_text(
        encoding="utf-8"
    )

    assert "BRANCH=fix/ai-exact-copy-stability-2026-11-23" in script
    assert '[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]]' in script
    assert '[[ "$current" == "$TARGET" ]]' in script
    assert '[[ "$reviewed" == "$TARGET" ]]' in script
    assert "STAGE=/var/lib/promoeditor/exact-copy-preview" in script
    assert "SOURCE=\"$STAGE/source\"" in script
    assert "JOBS=\"$STAGE/jobs\"" in script
    assert "UNIT=promoeditor-exact-preview" in script
    assert "PORT=18082" in script
    assert "--host 127.0.0.1" in script
    assert 'systemctl is-active --quiet "$service"' in script
    assert "for service in promoeditor regionalresearch caddy" in script
    assert "MemoryMax=$worker_max" in script
    assert "worker_max=760M" in script
    assert "worker_max=480M" in script
    assert 'MemAvailable:' in script
    assert 'ReadWritePaths=$JOBS $CACHE' in script
    assert "OPENAI_API_KEY=\\n" in script
    assert "systemctl stop promoeditor " not in script
    assert "git -C /opt/promoeditor reset" not in script
    assert "git -C /opt/promoeditor merge" not in script
