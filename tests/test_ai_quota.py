"""Durable and atomic OpenAI API quotas, with no actual paid calls."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import ai_quota, main, openai_service
from app.render import default_brief


@pytest.fixture
def quota_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "2")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY", "1")
    monkeypatch.setattr(ai_quota, "_utc_day", lambda: "2026-11-17")
    return tmp_path


def _count(path, category, day="2026-11-17"):
    with sqlite3.connect(path / "openai_call_quota.sqlite3") as db:
        row = db.execute(
            "SELECT attempts FROM paid_call_usage WHERE category=? AND utc_day=?",
            (category, day),
        ).fetchone()
        return row[0] if row else 0


def test_daily_quotas_are_separate_durable_and_reset_at_utc_midnight(quota_env, monkeypatch):
    ai_quota.reserve_paid_call("image")
    ai_quota.reserve_paid_call("text")
    ai_quota.reserve_paid_call("image")
    assert _count(quota_env, "image") == 2
    assert _count(quota_env, "text") == 1
    with pytest.raises(ai_quota.QuotaExceeded, match="Дневной лимит"):
        ai_quota.reserve_paid_call("image")
    with pytest.raises(ai_quota.QuotaExceeded, match="Дневной лимит"):
        ai_quota.reserve_paid_call("text")
    assert _count(quota_env, "image") == 2
    monkeypatch.setattr(ai_quota, "_utc_day", lambda: "2026-11-18")
    ai_quota.reserve_paid_call("image")
    assert _count(quota_env, "image", day="2026-11-18") == 1


def test_concurrent_requests_cannot_exceed_sqlite_quota(quota_env, monkeypatch):
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "5")

    def invoke(_):
        try:
            ai_quota.reserve_paid_call("image")
            return True
        except ai_quota.QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(invoke, range(32)))
    assert results.count(True) == 5
    assert results.count(False) == 27
    assert _count(quota_env, "image") == 5


def test_zero_is_unlimited_but_disabled_and_invalid_fail_closed(quota_env, monkeypatch):
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY", "0")
    for _ in range(100):
        ai_quota.check_paid_capacity("image", 2)
        ai_quota.reserve_paid_call("image")
        ai_quota.reserve_paid_call("text")
    assert not (quota_env / "openai_call_quota.sqlite3").exists(), (
        "Unlimited calls must not depend on SQLite or create usage rows"
    )
    for kind, key in (("image", "PROMO_AI_IMAGE_CALLS_PER_DAY"),
                      ("text", "PROMO_AI_TEXT_CALLS_PER_DAY")):
        monkeypatch.setenv(key, "disabled")
        with pytest.raises(ai_quota.QuotaExceeded, match="отключены"):
            ai_quota.reserve_paid_call(kind)
        with pytest.raises(ai_quota.QuotaExceeded, match="отключены"):
            ai_quota.check_paid_capacity(kind, 1)
        monkeypatch.setenv(key, "0")
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "-1")
    with pytest.raises(ai_quota.QuotaStoreUnavailable):
        ai_quota.reserve_paid_call("image")
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "not-a-number")
    with pytest.raises(ai_quota.QuotaStoreUnavailable):
        ai_quota.reserve_paid_call("image")


def test_missing_quota_settings_default_to_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PROMO_AI_IMAGE_CALLS_PER_DAY", raising=False)
    monkeypatch.delenv("PROMO_AI_TEXT_CALLS_PER_DAY", raising=False)
    for _ in range(101):
        ai_quota.reserve_paid_call("image")
        ai_quota.reserve_paid_call("text")
    ai_quota.check_paid_capacity("image", 2)
    assert not list(tmp_path.iterdir())


def test_unwritable_counter_path_never_allows_paid_call(quota_env, monkeypatch):
    target = quota_env / "not-a-directory"
    target.write_text("file, not folder", encoding="utf-8")
    monkeypatch.setenv("PROMO_DATA_DIR", str(target))
    with pytest.raises(ai_quota.QuotaStoreUnavailable, match="учёт"):
        ai_quota.reserve_paid_call("image")


def test_single_sdk_boundary_covers_responses_generate_and_edit(quota_env, monkeypatch):
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-token-not-real")
    calls = []

    class Images:
        def generate(self, **kwargs):
            calls.append("generate")
            return {"ok": True}

        def edit(self, **kwargs):
            calls.append("edit")
            return {"ok": True}

    class Responses:
        def create(self, **kwargs):
            calls.append("create")
            return {"ok": True}

    monkeypatch.setattr(
        openai, "OpenAI",
        lambda **kwargs: type("FakeSDK", (), {
            "images": Images(), "responses": Responses(),
        })(),
    )
    client = openai_service.client()
    client.images.generate(model="mock")
    client.images.edit(model="mock")
    client.responses.create(model="mock")
    assert calls == ["generate", "edit", "create"]
    assert _count(quota_env, "image") == 2
    assert _count(quota_env, "text") == 1
    with pytest.raises(ai_quota.QuotaExceeded):
        client.images.generate(model="mock")
    with pytest.raises(ai_quota.QuotaExceeded):
        client.responses.create(model="mock")
    assert len(calls) == 3


def test_timeout_consumes_attempt_as_conservative_budget(quota_env, monkeypatch):
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-token-not-real")
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "1")
    calls = []

    class Images:
        def generate(self, **kwargs):
            calls.append("generate")
            raise TimeoutError("Simulated upstream timeout")

    monkeypatch.setattr(
        openai, "OpenAI",
        lambda **kwargs: type("FakeSDK", (), {"images": Images(), "responses": None})(),
    )
    client = openai_service.client()
    with pytest.raises(TimeoutError, match="Simulated"):
        client.images.generate()
    assert _count(quota_env, "image") == 1
    with pytest.raises(ai_quota.QuotaExceeded):
        client.images.generate()
    assert len(calls) == 1


def test_exhausted_layout_budget_rejected_before_openai_request(quota_env, monkeypatch):
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-token-not-real")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY", "disabled")
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)

    report = {
        "selected_assets": {"primary_photo": None, "reference_example": None},
        "project_assets": [],
    }
    monkeypatch.setattr(
        main, "analyze_project",
        lambda *args, **kwargs: (report, {}),
    )
    upstream_calls = []

    class Responses:
        def create(self, **kwargs):
            upstream_calls.append(kwargs)
            raise AssertionError("Must not call the upstream model after quota exhaustion")

    monkeypatch.setattr(
        openai, "OpenAI",
        lambda **kwargs: type("FakeSDK", (), {
            "images": None, "responses": Responses(),
        })(),
    )
    response = TestClient(main.app).post(
        "/api/concepts",
        data={"payload": json.dumps(default_brief(), ensure_ascii=False)},
    )
    assert response.status_code == 429, response.text
    assert "отключены" in response.json()["detail"]
    assert upstream_calls == []
