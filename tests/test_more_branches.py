from datetime import datetime

import mJiraWorkLogExtractor as mod


def test_fetch_worklogs_http_get_none_breaks(monkeypatch):
    # If http_get_with_retry returns None, loop should break and return []
    monkeypatch.setattr(mod, "http_get_with_retry", lambda *_a, **_k: None)

    def session_factory():
        class Dummy: ...
        return Dummy()

    issue = {"key": "K-4", "fields": {}}
    start_utc = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end_utc = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)
    rows = mod.fetch_worklogs_for_issue("https://x", session_factory, issue, start_utc, end_utc, timeout=5)
    assert rows == []


def test_post_search_jql_next_token_no_issues(monkeypatch):
    # Ensure that a page with a nextPageToken but empty issues still terminates
    pages = [
        type("R", (), {
            "status_code": 200,
            "raise_for_status": staticmethod(lambda: None),
            "json": staticmethod(lambda: {"issues": [], "nextPageToken": "nxt"}),
        })(),
        type("R", (), {
            "status_code": 200,
            "raise_for_status": staticmethod(lambda: None),
            "json": staticmethod(lambda: {"issues": [], "nextPageToken": None}),
        })(),
    ]
    calls = {"i": 0}

    class Sess:
        def post(self, url, json=None, timeout=None):
            r = pages[calls["i"]]
            calls["i"] += 1
            return r

    res = mod.post_search_jql(Sess(), "https://x", "project = TEST", ["summary"], timeout=5, verbose=False)
    assert res == []
    assert calls["i"] == 1


def test_make_session_no_proxies_verify_true():
    s = mod.make_session("u", "t", verify=True, ca_bundle="", http_proxy="", https_proxy="")
    assert s.verify is True
    assert "http" not in s.proxies and "https" not in s.proxies


def test_jql_for_range_single_day():
    start = datetime(2025, 10, 5, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end = datetime(2025, 10, 6, 0, 0, tzinfo=mod.DEFAULT_TZ)  # exclusive
    jql = mod.jql_for_range(start, end)
    assert jql == 'worklogDate >= "2025-10-05" AND worklogDate <= "2025-10-05"'
