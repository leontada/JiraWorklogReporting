from types import SimpleNamespace
from datetime import datetime
import pytest
import pandas as pd
import requests

import mJiraWorkLogExtractor as mod


def test_compute_bounds_with_invalid_end_uses_month_end():
    # now in middle of month
    now = datetime(2025, 10, 15, 12, 0, 0, tzinfo=mod.DEFAULT_TZ)
    start, end = mod.compute_bounds(now, start_str="", end_str="not-a-date")
    # start is first of month
    assert start == datetime(2025, 10, 1, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)
    # end is first instant of next month (month_end)
    assert end == datetime(2025, 11, 1, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)


def test_main_insecure_disables_warnings_and_adds_extension_and_no_sow(monkeypatch, tmp_path, tmp_config_file, capsys):
    # Prepare args: missing .xlsx extension and insecure True to trigger disable_warnings
    out_base = tmp_path / "report"  # no .xlsx
    parsed = SimpleNamespace(
        config=str(tmp_config_file),
        out=str(out_base),
        verbose=False,
        max_workers=1,
        timeout=5,
        insecure=True,
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)

    # Ensure sow_ok False so that SOW_FIELD_ID is not requested
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: False)

    # Capture fields passed to post_search_jql
    captured = {"fields": None}

    def fake_post_search_jql(session, base_url, jql, fields, timeout, verbose=False):
        captured["fields"] = list(fields)
        # single fake issue
        return [{"key": "X-1", "fields": {"summary": "S", "project": {"name": "P"}, "issuetype": {"name": "T"}, "priority": {"name": "M"}}}]

    monkeypatch.setattr(mod, "post_search_jql", fake_post_search_jql)

    # Return 1 row from fetch
    row = {
        "Projeto": "P",
        "Tipo de Problema": "T",
        "Clave": "X-1",
        "Resumo": "S",
        "Prioridade": "M",
        "SoW": "7",
        "Data de Início": "2025-10-24",
        "Nome de Exibição": "User",
        "Tempo Gasto (h)": 1.0,
        "Descrição do Trabalho": "Done",
    }
    monkeypatch.setattr(mod, "fetch_worklogs_for_issue", lambda *a, **k: [row])

    # Stub ExcelWriter and DataFrame.to_excel
    created_paths = []

    class DummyWriter:
        def __init__(self, path, engine=None):
            created_paths.append(str(path))
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda self, writer, index=False, sheet_name="Relatório": None)

    # Spy on urllib3.disable_warnings by replacing function
    called = {"disabled": False}
    def fake_disable(_arg):
        called["disabled"] = True
    monkeypatch.setattr("urllib3.disable_warnings", fake_disable)

    # Run main
    mod.main()
    out = capsys.readouterr().out

    # Out path should have gained .xlsx and short suffix file created
    full = str(out_base) + ".xlsx"
    short = str(out_base) + "_short.xlsx"
    assert full in created_paths
    assert short in created_paths
    assert "_short.xlsx" in out

    # No SOW field requested when ensure_field_exists returned False
    assert captured["fields"] is not None
    assert mod.SOW_FIELD_ID not in captured["fields"]

    # insecure + no ca_bundle => warnings disabled
    assert called["disabled"] is True


def test_http_get_with_retry_404_retries_then_returns_last_response(no_sleep):
    attempts = {"n": 0}

    class Sess:
        def get(self, url, params=None, timeout=None):
            attempts["n"] += 1
            # Always 404; raise_for_status should be triggered in code
            return FakeResp(404)

    class FakeResp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {}
        def raise_for_status(self):
            raise requests.HTTPError("404")

    s = Sess()
    r = mod.http_get_with_retry(s, "https://x", timeout=1, max_tries=2, backoff_base=0.0)
    assert r is not None
    assert attempts["n"] == 2
    assert r.status_code == 404


def test_fetch_worklogs_invalid_started_is_skipped(monkeypatch):
    issue = {"key": "K-1", "fields": {"summary": "", "project": {}, "issuetype": {}, "priority": {}}}
    # One invalid started string
    wls = [{"started": "not-an-iso", "author": {"displayName": "U"}, "timeSpentSeconds": 60, "comment": ""}]

    class Resp:
        def __init__(self):
            self.status_code = 200
        def json(self):
            return {"worklogs": wls, "total": 1}
        def raise_for_status(self):
            return None

    def fake_get(_sess, url, params=None, timeout=None):
        return Resp()

    monkeypatch.setattr(mod, "http_get_with_retry", fake_get)

    def session_factory():
        class Dummy: ...
        return Dummy()

    start_utc = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end_utc = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)
    rows = mod.fetch_worklogs_for_issue("https://x", session_factory, issue, start_utc, end_utc, timeout=5)
    assert rows == []


def test_adf_to_text_ignores_unknown_nodes():
    # Unknown node with a paragraph child so walker can collect the text
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "unknownNodeType",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}
                ],
            }
        ],
    }
    txt = mod.adf_to_text(adf)
    assert "Hello" in txt
