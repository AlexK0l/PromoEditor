"""Render subprocess memory isolation, quotas and fault propagation.

These tests exercise the actual child without any real OpenAI API calls.
"""
import gc
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.ai_quota import QuotaExceeded
from app.render import default_brief
from app.render_worker import RenderWorkerError, run_render_task
from app import render_worker


def _args():
    return (
        default_brief(), None, None, None, None, [],
        True, False, "gpt-image-2.5-flare", "low", "demo template",
    )


def _rss_mib():
    # Linux-only RSS of the HTTP/test process; the worker has already exited.
    return int(Path("/proc/self/status").read_text().split("VmRSS:")[1].split()[0]) / 1024


@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="Linux RSS required")
def test_two_render_jobs_return_memory_to_os_without_paid_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY", "0")
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gc.collect()
    baseline = _rss_mib()
    for _ in range(2):
        output = run_render_task("generate", *_args())
        job = tmp_path / output["job_id"]
        assert (job / "poster_4x3.png").read_bytes().startswith(b"\x89PNG")
        assert (job / "poster_9x16.png").read_bytes().startswith(b"\x89PNG")
        assert (job / "promo_kit.zip").is_file()
        assert output["ai_used"] is False
    gc.collect()
    assert _rss_mib() - baseline < 80, (
        "Large image buffers leaked into the long-running FastAPI process"
    )
    # The temporary argument folders were deleted, leaving only generated jobs.
    assert len(list(tmp_path.iterdir())) == 2


def test_paid_quota_error_survives_process_boundary(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-for-no-network-test")
    args = list(_args())
    args[7] = True
    with pytest.raises(QuotaExceeded, match="PROMO_AI_IMAGE_CALLS_PER_DAY=0"):
        run_render_task("generate", *args)
    assert not list(tmp_path.iterdir())


def test_worker_preserves_raw_bytes_without_pickle(tmp_path):
    payload = {"escaped": {"type": "bytes", "file": "../evil"},
               "raw": b"\x00\xfe\xff" * 8192, "items": [["a", 7], None]}
    packed = render_worker._encode(payload, tmp_path, [0])
    assert render_worker._decode(packed, tmp_path) == payload
    assert (tmp_path / "blob-0.bin").stat().st_size == len(payload["raw"])
    with pytest.raises(ValueError):
        render_worker._decode({"type": "bytes", "file": "../../etc/passwd"}, tmp_path)


def test_render_timeout_does_not_leave_untrusted_staging_files(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=3)
    monkeypatch.setattr(render_worker.subprocess, "run", timeout)
    with pytest.raises(RenderWorkerError, match="Превышено время"):
        run_render_task("generate", *_args())
    assert list(tmp_path.iterdir()) == []


def test_abnormal_child_exit_is_reported_and_staging_cleaned(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    def died(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], returncode=-9)
    monkeypatch.setattr(render_worker.subprocess, "run", died)
    with pytest.raises(RenderWorkerError, match="аварийно"):
        run_render_task("generate", *_args())
    assert list(tmp_path.iterdir()) == []


def test_invalid_render_timeout_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROMO_RENDER_TIMEOUT_SECONDS", "wrong")
    with pytest.raises(RenderWorkerError, match="PROMO_RENDER_TIMEOUT_SECONDS"):
        run_render_task("generate", *_args())
    assert list(tmp_path.iterdir()) == []
