from types import SimpleNamespace
from datetime import datetime, timezone
import requests
import pytest

import mJiraWorkLogExtractor as mod
from tests.conftest import FakeResponse, make_http_error


def test_make_session_configures_auth_proxies_and_verify():
    s = mod.make_session(
        email="user@example.com",
        token="tok",
        verify=False,
        ca_bundle="",
        http_proxy="http://proxy.local:8080",
        https_proxy="http://proxy.local:8080",
    )
    assert s.auth == ("user@example.com", "tok")
    assert s.headers["Accept"] == "application/json"
    assert s.proxies["http"] == "http://proxy.local:8080"
    assert s.proxies["https"] == "http://proxy.local:8080"
    assert s.verify is False

    s2 = mod.make_session("u", "t", verify=True, ca_bundle="C:/root.pem")
    # when ca_bundle is provided, it's used instead of boolean verify
    assert s2.verify == "C:/root.pem"


def test_http_get_with_retry_retries_429_then_success(no_sleep):
    # Prepare a fake session producing 429 then 200
    calls = {"count": 0}

    class Sess:
        def get(self, url, params=None, timeout=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return FakeResponse(
                    status_code=429,
                    headers={"Retry-After": "0"},
                    json_data={"msg": "rate limit"},
                )
            return FakeResponse(status_code=200, json_data={"ok": True})

    s = Sess()
    r = mod.http_get_with_retry(s, "http://x", timeout=1, max_tries=3, backoff_base=0.01)
    assert r.status_code == 200
    assert calls["count"] == 2


def test_http_get_with_retry_returns_error_after_max_retries(no_sleep):
    class Sess:
        def get(self, url, params=None, timeout=None):
            return FakeResponse(status_code=500, json_data={"err": "server"})

    s = Sess()
    r = mod.http_get_with_retry(s, "http://x", timeout=1, max_tries=2, backoff_base=0.0)
    # returns the last response even if it's an error
    assert r is not None
    assert r.status_code == 500


def test_ensure_field_exists_true_and_false(monkeypatch):
    # True case: field present
    class Sess1:
        def get(self, url, timeout=None):
            return FakeResponse(status_code=200, json_data=[{"id": mod.SOW_FIELD_ID}, {"id": "other"}])

    ok = mod.ensure_field_exists(Sess1(), "https://example", mod.SOW_FIELD_ID, timeout=1, verbose=True)
    assert ok is True

    # False case: field missing
    class Sess2:
        def get(self, url, timeout=None):
            return FakeResponse(status_code=200, json_data=[{"id": "not_it"}])

    ok2 = mod.ensure_field_exists(Sess2(), "https://example", mod.SOW_FIELD_ID, timeout=1, verbose=False)
    assert ok2 is False

    # HTTP error case should warn and return True (continue without hard-fail)
    class Sess3:
        def get(self, url, timeout=None):
            return FakeResponse(status_code=400, raise_for_status_exc=make_http_error(400))

    assert mod.ensure_field_exists(Sess3(), "https://example", mod.SOW_FIELD_ID, timeout=1, verbose=False) is True


def test_post_search_jql_paginates(monkeypatch):
    pages = [
        FakeResponse(
            status_code=200,
            json_data={"issues": [{"id": "1"}], "nextPageToken": "nxt"},
        ),
        FakeResponse(
            status_code=200,
            json_data={"issues": [{"id": "2"}], "nextPageToken": None},
        ),
    ]
    calls = {"i": 0}

    class Sess:
        def post(self, url, json=None, timeout=None):
            r = pages[calls["i"]]
            calls["i"] += 1
            return r

    res = mod.post_search_jql(Sess(), "https://x", "project = TEST", ["summary"], timeout=5, verbose=True)
    assert [x["id"] for x in res] == ["1", "2"]
    assert calls["i"] == 2


def test_post_search_jql_http_error_exits(monkeypatch):
    class Sess:
        def post(self, url, json=None, timeout=None):
            # raise_for_status will raise
            return FakeResponse(status_code=400, raise_for_status_exc=make_http_error(400))

    with pytest.raises(SystemExit) as ei:
        mod.post_search_jql(Sess(), "https://x", "bad", ["f"], timeout=1, verbose=False)
    assert ei.value.code == 3
