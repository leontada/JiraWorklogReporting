from types import SimpleNamespace
from datetime import datetime, timezone
import builtins

import pytest
import pandas as pd

import mJiraWorkLogExtractor as mod


def test_fetch_worklogs_for_issue_filters_and_maps(monkeypatch):
    base_url = "https://example.atlassian.net"
    issue = {
        "key": "TEST-1",
        "fields": {
            "summary": "Sum",
            "project": {"name": "Proj"},
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            mod.SOW_FIELD_ID: "SOW ABC123",
        },
    }

    # Worklogs: one inside range (with +0000), one outside (before), one inside (string comment)
    worklogs = [
        {
            "started": "2025-10-10T10:00:00.000+0000",
            "author": {"displayName": "Dev A"},
            "timeSpentSeconds": 7200,
            "comment": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Worked"}]}],
            },
        },
        {
            "started": "2025-09-30T23:59:59.000+0000",  # before start
            "author": {"displayName": "Dev B"},
            "timeSpentSeconds": 3600,
            "comment": "Should be filtered out",
        },
        {
            "started": "2025-10-24T08:30:00.000+0000",
            "author": {"displayName": "Dev C"},
            "timeSpentSeconds": 1800,
            "comment": "Note",
        },
    ]

    class Sess:
        def get(self, url, params=None, timeout=None):
            # Single page containing all worklogs
            return SimpleResponse(
                status_code=200,
                json_data={"worklogs": worklogs, "total": len(worklogs)},
            )

    def session_factory():
        return Sess()

    # Date bounds: inclusive start 10-01, exclusive end 10-25
    start_utc = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end_utc = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)

    rows = mod.fetch_worklogs_for_issue(base_url, session_factory, issue, start_utc, end_utc, timeout=5)
    # Expect 2 rows (the first and third entries)
    assert len(rows) == 2

    r1 = rows[0]
    assert r1["Projeto"] == "Proj"
    assert r1["Tipo de Problema"] == "Bug"
    assert r1["Clave"] == "TEST-1"
    assert r1["Resumo"] == "Sum"
    assert r1["Prioridade"] == "High"
    # SoW numeric extraction
    assert r1["SoW"] == "123"
    assert r1["Data de Início"] == "2025-10-10"
    assert r1["Nome de Exibição"] == "Dev A"
    assert r1["Tempo Gasto (h)"] == 2.0
    assert "Worked" in r1["Descrição do Trabalho"]

    r2 = rows[1]
    assert r2["Nome de Exibição"] == "Dev C"
    assert r2["Tempo Gasto (h)"] == 0.5
    assert r2["Descrição do Trabalho"] == "Note"


class SimpleResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise Exception(f"HTTP {self.status_code}")


def test_main_smoke_writes_full_and_short_with_suffix(monkeypatch, tmp_path, capsys, tmp_config_file):
    out_file = tmp_path / "report.xlsx"

    # Patch parse_args to point to our temp config and out path
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            config=str(tmp_config_file),
            out=str(out_file),
            verbose=False,
            max_workers=2,
            timeout=5,
            insecure=False,
        ),
    )

    # Avoid real HTTP: patch ensure_field_exists, post_search_jql, fetch_worklogs_for_issue
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: True)
    fake_issues = [{"key": "TEST-1", "fields": {"summary": "S", "project": {"name": "P"}, "issuetype": {"name": "T"}, "priority": {"name": "M"}}}]
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: fake_issues)

    row = {
        "Projeto": "P",
        "Tipo de Problema": "T",
        "Clave": "TEST-1",
        "Resumo": "S",
        "Prioridade": "M",
        "SoW": "1",
        "Data de Início": "2025-10-24",
        "Nome de Exibição": "User",
        "Tempo Gasto (h)": 1.0,
        "Descrição do Trabalho": "Done",
    }
    monkeypatch.setattr(mod, "fetch_worklogs_for_issue", lambda *a, **k: [row])

    # Stub out Excel writing so we don't require openpyxl and no real files needed
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

    # Run main
    mod.main()
    stdout = capsys.readouterr().out

    # Validate that both full and short paths were used
    full = str(out_file)
    if not full.lower().endswith(".xlsx"):
        full += ".xlsx"
    short = full[:-5] + "_short.xlsx"

    # created_paths should contain both
    assert full in created_paths
    assert short in created_paths

    # Check printed suffix info
    assert "_short.xlsx" in stdout
