from types import SimpleNamespace
from datetime import datetime
import os
import pytest
import pandas as pd

import mJiraWorkLogExtractor as mod


def test_http_post_with_retry_retries_429_then_success(monkeypatch):
    calls = {"n": 0}

    class Sess:
        def post(self, url, json=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                class R:
                    status_code = 429
                    headers = {"Retry-After": "0"}
                    def raise_for_status(self): pass
                return R()
            class OK:
                status_code = 200
                headers = {}
                def raise_for_status(self): pass
            return OK()

    s = Sess()
    r = mod.http_post_with_retry(s, "https://x", json={}, timeout=1, max_tries=3, backoff_base=0.0)
    assert r is not None and r.status_code == 200
    assert calls["n"] == 2


def test_http_post_with_retry_returns_error_after_max_retries(monkeypatch):
    class Sess:
        def post(self, url, json=None, timeout=None):
            class R:
                status_code = 500
                headers = {}
                def raise_for_status(self):
                    import requests
                    raise requests.HTTPError("500")
            return R()

    s = Sess()
    r = mod.http_post_with_retry(s, "https://x", json={}, timeout=1, max_tries=2, backoff_base=0.0)
    assert r is not None and r.status_code == 500


def test_read_config_env_fallback(tmp_path, monkeypatch):
    # Create config with empty credentials so env vars must be used
    cfg = tmp_path / "c.ini"
    cfg.write_text(
        "[jira]\n"
        "base_url = \n"
        "email = \n"
        "api_token = \n"
        "verify_ssl = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_BASE_URL", "https://env.example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "env.user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "envtoken")

    d = mod.read_config(str(cfg))
    assert d["base_url"] == "https://env.example.atlassian.net"
    assert d["email"] == "env.user@example.com"
    assert d["token"] == "envtoken"


def test_adf_to_text_hardbreak():
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Line1"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Line2"},
                ],
            }
        ],
    }
    txt = mod.adf_to_text(adf)
    assert "Line1" in txt and "Line2" in txt
    # Ensure a newline was introduced by hardBreak
    assert "Line1\nLine2" in txt or "Line1\r\nLine2" in txt


def test_main_insecure_warns_stderr(monkeypatch, tmp_path, tmp_config_file, capsys):
    # Arrange args: insecure True -> warning on stderr
    out_base = tmp_path / "report"
    parsed = SimpleNamespace(
        config=str(tmp_config_file),
        out=str(out_base),
        verbose=False,
        max_workers=1,
        timeout=5,
        insecure=True,
        sow_field_id="",
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)
    # ensure_field_exists -> False (no sow)
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: False)
    # Minimal issues and rows
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: [{"key": "X-1", "fields": {"summary": "S"}}])
    monkeypatch.setattr(mod, "fetch_worklogs_for_issue", lambda *a, **k: [{
        "Projeto": "", "Tipo de Problema": "", "Clave": "X-1", "Resumo": "S", "Prioridade": "",
        "SoW": "", "Data de Início": "2025-10-24", "Nome de Exibição": "U", "Tempo Gasto (h)": 1.0,
        "Descrição do Trabalho": "",
    }])

    # Dummy Excel writer
    class DummyWriter:
        def __init__(self, path, engine=None): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda self, writer, index=False, sheet_name="Relatório": None)

    # Spy disable_warnings too to avoid noise
    called = {"disabled": False}
    def fake_disable(_): called["disabled"] = True
    monkeypatch.setattr("urllib3.disable_warnings", fake_disable)

    mod.main()
    captured = capsys.readouterr()
    # Assert warning on stderr
    assert "SSL certificate verification is DISABLED" in captured.err
    assert called["disabled"] is True


def test_main_excel_write_error_exits(monkeypatch, tmp_path, tmp_config_file):
    # Force to_excel to raise to exercise error path and sys.exit(4)
    out_file = tmp_path / "dir" / "out.xlsx"
    parsed = SimpleNamespace(
        config=str(tmp_config_file),
        out=str(out_file),
        verbose=False,
        max_workers=1,
        timeout=5,
        insecure=False,
        sow_field_id="",
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: False)
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: [{"key": "K-1", "fields": {"summary": ""}}])
    monkeypatch.setattr(mod, "fetch_worklogs_for_issue", lambda *a, **k: [{
        "Projeto": "", "Tipo de Problema": "", "Clave": "K-1", "Resumo": "", "Prioridade": "",
        "SoW": "", "Data de Início": "2025-10-24", "Nome de Exibição": "U", "Tempo Gasto (h)": 1.0,
        "Descrição do Trabalho": "",
    }])

    class DummyWriter:
        def __init__(self, path, engine=None): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)

    def boom_to_excel(self, writer, index=False, sheet_name="Relatório"):
        raise RuntimeError("fail writing")
    monkeypatch.setattr(pd.DataFrame, "to_excel", boom_to_excel)

    with pytest.raises(SystemExit) as ei:
        mod.main()
    assert ei.value.code == 4


def test_sow_field_id_override_cli(monkeypatch, tmp_path, tmp_config_file):
    out_file = tmp_path / "report.xlsx"
    override_id = "customfield_99999"

    parsed = SimpleNamespace(
        config=str(tmp_config_file),
        out=str(out_file),
        verbose=False,
        max_workers=1,
        timeout=5,
        insecure=False,
        sow_field_id=override_id,
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: True)

    captured = {"fields": []}
    def fake_post_search_jql(session, base_url, jql, fields, timeout, verbose=False):
        captured["fields"] = list(fields)
        return [{"key": "K-1", "fields": {"summary": ""}}]
    monkeypatch.setattr(mod, "post_search_jql", fake_post_search_jql)

    # Minimal row
    monkeypatch.setattr(mod, "fetch_worklogs_for_issue", lambda *a, **k: [{
        "Projeto": "", "Tipo de Problema": "", "Clave": "K-1", "Resumo": "", "Prioridade": "",
        "SoW": "", "Data de Início": "2025-10-24", "Nome de Exibição": "U", "Tempo Gasto (h)": 1.0,
        "Descrição do Trabalho": "",
    }])

    class DummyWriter:
        def __init__(self, path, engine=None): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda *a, **k: None)

    mod.main()

    assert override_id in captured["fields"]
