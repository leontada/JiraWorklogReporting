import re
from types import SimpleNamespace

import pytest
import requests

import mJiraWorkLogExtractor as mod


def test_http_get_with_retry_retry_after_garbage_then_success(monkeypatch, no_sleep):
    calls = {"n": 0}

    class Sess:
        def get(self, url, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # 429 with non-numeric Retry-After should fall back to exponential backoff path
                class R:
                    status_code = 429
                    headers = {"Retry-After": "not-a-number"}
                    def raise_for_status(self): pass
                return R()
            class OK:
                status_code = 200
                headers = {}
                def raise_for_status(self): pass
            return OK()

    r = mod.http_get_with_retry(Sess(), "https://x", timeout=1, max_tries=2, backoff_base=0.0)
    assert r is not None and r.status_code == 200
    assert calls["n"] == 2


def test_fetch_worklogs_empty_list_breaks(monkeypatch):
    class Resp:
        def __init__(self):
            self.status_code = 200
        def json(self):
            return {"worklogs": [], "total": 0}
        def raise_for_status(self): pass

    def fake_get(_sess, url, params=None, timeout=None):
        return Resp()

    monkeypatch.setattr(mod, "http_get_with_retry", fake_get)

    def session_factory():
        class Dummy: ...
        return Dummy()

    issue = {"key": "K-2", "fields": {"summary": "S"}}
    rows = mod.fetch_worklogs_for_issue("https://x", session_factory, issue, mod.DEFAULT_TZ.localize if hasattr(mod.DEFAULT_TZ, "localize") else mod.DEFAULT_TZ, mod.DEFAULT_TZ, 5)  # type: ignore[arg-type]
    # We don't rely on start/end correctness here; just ensure empty worklogs returns []
    assert rows == []


def test_ensure_field_exists_generic_exception_returns_true():
    class Sess:
        def get(self, url, timeout=None):
            raise RuntimeError("boom")

    # Generic exception path should return True (continue)
    assert mod.ensure_field_exists(Sess(), "https://x", mod.SOW_FIELD_ID, timeout=1) is True


def test_default_out_name_custom_prefix():
    name = mod.default_out_name(prefix="custom")
    assert name.startswith("custom-")
    assert name.endswith(".xlsx")
    assert re.match(r"^custom-\d{4}-\d{2}-\d{2}-\d{4}\.xlsx$", name)
