import os
import re
from types import SimpleNamespace
from datetime import datetime

import pytest

import mJiraWorkLogExtractor as mod


def test_fetch_worklogs_sow_list_and_hierarchy(monkeypatch):
    # SoW as mixed list -> stringify produces "SOW 12 | Top:Leaf"
    # fetch_worklogs_for_issue should then keep only numeric parts -> "12"
    issue = {
        "key": "K-3",
        "fields": {
            "summary": "S",
            "project": {"name": "P"},
            "issuetype": {"name": "T"},
            "priority": {"name": "M"},
            mod.SOW_FIELD_ID: ["SOW 12", {"value": "Top", "child": {"value": "Leaf"}}],
        },
    }

    wl = {
        "started": "2025-10-10T10:00:00.000+0000",
        "author": {"displayName": "Dev"},
        "timeSpentSeconds": 3600,
        "comment": "C",
    }

    class Resp:
        def __init__(self):
            self.status_code = 200
        def json(self):
            return {"worklogs": [wl], "total": 1}
        def raise_for_status(self): pass

    def fake_get(_sess, url, params=None, timeout=None):
        return Resp()

    monkeypatch.setattr(mod, "http_get_with_retry", fake_get)

    def session_factory():
        class Dummy: ...
        return Dummy()

    start_utc = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end_utc = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)
    rows = mod.fetch_worklogs_for_issue("https://x", session_factory, issue, start_utc, end_utc, timeout=5)
    assert len(rows) == 1
    assert rows[0]["SoW"] == "12"  # only numeric part retained


def test_post_search_jql_no_issues(monkeypatch):
    class Sess:
        def post(self, url, json=None, timeout=None):
            class R:
                def __init__(self):
                    self.status_code = 200
                def raise_for_status(self): pass
                def json(self):
                    return {"issues": [], "nextPageToken": None}
            return R()
    res = mod.post_search_jql(Sess(), "https://x", "project = TEST", ["summary"], timeout=5, verbose=False)
    assert res == []


def test_http_get_with_retry_immediate_success():
    class Sess:
        def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                headers = {}
                def raise_for_status(self): pass
            return R()
    r = mod.http_get_with_retry(Sess(), "https://x", timeout=1, max_tries=3)
    assert r is not None and r.status_code == 200


def test_read_config_bool_and_proxies(tmp_path):
    cfg = tmp_path / "c.ini"
    cfg.write_text(
        "[jira]\n"
        "base_url = https://example.atlassian.net\n"
        "email = user@example.com\n"
        "api_token = tok\n"
        "verify_ssl = Yes\n"
        "ca_bundle = C:\\\\root.pem\n"
        "http_proxy = http://proxy:8080\n"
        "https_proxy = http://proxy:8080\n"
        "start_date = 2025-10-01\n"
        "end_date = 2025-10-24\n",
        encoding="utf-8",
    )
    d = mod.read_config(str(cfg))
    assert d["verify_ssl"] is True
    assert d["ca_bundle"].endswith("root.pem")
    assert d["http_proxy"].startswith("http://proxy")
    assert d["start_date"] == "2025-10-01"
    assert d["end_date"] == "2025-10-24"


def test_parse_args_flags(monkeypatch, tmp_path):
    cfg_path = tmp_path / "conf.ini"
    cfg_path.write_text("[jira]\nbase_url=https://x\nemail=a@b\napi_token=t\n", encoding="utf-8")
    monkeypatch.setattr(mod.sys, "argv", [
        "prog",
        "--config", str(cfg_path),
        "--out", "custom.xlsx",
        "--verbose",
        "--max-workers", "3",
        "--timeout", "7",
        "--insecure",
    ])
    args = mod.parse_args()
    assert args.config == str(cfg_path)
    assert args.out == "custom.xlsx"
    assert args.verbose is True
    assert args.max_workers == 3
    assert args.timeout == 7
    assert args.insecure is True


def test_vprint_with_sep_and_end(capsys):
    mod.vprint(True, "A", "B", sep="|", end="")
    out = capsys.readouterr().out
    assert out.endswith("A|B")


def test_stringify_sow_on_non_string():
    assert mod.stringify_sow(123) == "123"
