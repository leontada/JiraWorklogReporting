from types import SimpleNamespace
from datetime import datetime
import pytest
import pandas as pd
import requests

import mJiraWorkLogExtractor as mod


def test_adf_to_text_heading_hardbreak_and_ordered_list():
    adf = {
        "type": "doc",
        "content": [
            {"type": "heading", "content": [{"type": "text", "text": "Title"}]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Line1"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Line2"},
                ],
            },
            {
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "First"}]}
                        ],
                    }
                ],
            },
        ],
    }
    txt = mod.adf_to_text(adf)
    assert "Title" in txt
    assert "Line1" in txt and "Line2" in txt
    # list items are prefixed with "- "
    assert "- First" in txt


def test_ensure_field_exists_ssl_error_reraises():
    class Sess:
        def get(self, url, timeout=None):
            raise requests.exceptions.SSLError("bad ssl")

    with pytest.raises(requests.exceptions.SSLError):
        mod.ensure_field_exists(Sess(), "https://example", mod.SOW_FIELD_ID, timeout=1)


def test_http_get_with_retry_ssl_error_reraises():
    class Sess:
        def get(self, url, params=None, timeout=None):
            raise requests.exceptions.SSLError("oops")

    with pytest.raises(requests.exceptions.SSLError):
        mod.http_get_with_retry(Sess(), "https://x")


def test_fetch_worklogs_pagination(monkeypatch):
    # Two pages: first returns 1 WL with total=2, second returns 1 WL, then loop stops
    calls = {"n": 0}

    wl1 = {
        "started": "2025-10-10T10:00:00.000+0000",
        "author": {"displayName": "Dev1"},
        "timeSpentSeconds": 1800,
        "comment": "C1",
    }
    wl2 = {
        "started": "2025-10-11T12:00:00.000+0000",
        "author": {"displayName": "Dev2"},
        "timeSpentSeconds": 3600,
        "comment": "C2",
    }

    class Resp:
        def __init__(self, wls, total, status=200):
            self._json = {"worklogs": wls, "total": total}
            self.status_code = status
        def json(self):
            return self._json
        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}")

    def fake_get(_sess, url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Resp([wl1], total=2)
        elif calls["n"] == 2:
            return Resp([wl2], total=2)
        return Resp([], total=2)

    monkeypatch.setattr(mod, "http_get_with_retry", fake_get)

    def session_factory():
        class Dummy: ...
        return Dummy()

    issue = {"key": "KEY-1", "fields": {"summary": "S", "project": {"name": "P"}, "issuetype": {"name": "T"}, "priority": {"name": "M"}}}
    start_utc = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end_utc = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)
    rows = mod.fetch_worklogs_for_issue("https://example", session_factory, issue, start_utc, end_utc, timeout=5)
    assert len(rows) == 2
    assert {r["Nome de Exibição"] for r in rows} == {"Dev1", "Dev2"}


def test_fetch_worklogs_error_status_breaks(monkeypatch):
    class Resp:
        def __init__(self, status=500):
            self.status_code = status
            self.text = "err"
        def json(self):
            return {}
        def raise_for_status(self):
            raise requests.HTTPError("boom")

    def fake_get(_sess, url, params=None, timeout=None):
        return Resp(500)

    monkeypatch.setattr(mod, "http_get_with_retry", fake_get)

    def session_factory():
        class Dummy: ...
        return Dummy()

    issue = {"key": "KEY-1", "fields": {}}
    start_utc = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end_utc = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)
    rows = mod.fetch_worklogs_for_issue("https://example", session_factory, issue, start_utc, end_utc, timeout=5)
    assert rows == []


def test_read_config_errors(tmp_path):
    # Missing [jira] section -> exit 2
    p = tmp_path / "cfg.ini"
    p.write_text("[not_jira]\nbase_url=https://x\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        mod.read_config(str(p))
    assert ei.value.code == 2

    # Missing required fields -> exit 2
    p2 = tmp_path / "cfg2.ini"
    p2.write_text("[jira]\nbase_url=https://x\nemail=\napi_token=\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei2:
        mod.read_config(str(p2))
    assert ei2.value.code == 2
