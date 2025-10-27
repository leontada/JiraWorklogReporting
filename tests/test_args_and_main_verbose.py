import os
import re
from types import SimpleNamespace

import pandas as pd

import mJiraWorkLogExtractor as mod


def test_parse_args_app_dir_source(monkeypatch):
    # Simulate running from source (no frozen attrs)
    monkeypatch.setenv("PYTHONPATH", "")  # noop but ensures env control
    # Ensure no frozen flags
    if hasattr(mod.sys, "frozen"):
        monkeypatch.delattr(mod.sys, "frozen", raising=False)
    if hasattr(mod.sys, "_MEIPASS"):
        monkeypatch.delattr(mod.sys, "_MEIPASS", raising=False)

    # Limit argv so argparse doesn't see pytest args
    monkeypatch.setattr(mod.sys, "argv", ["prog"])

    args = mod.parse_args()
    expected_dir = os.path.dirname(os.path.abspath(mod.__file__))
    assert args.config == os.path.join(expected_dir, "config.ini")


def test_parse_args_app_dir_frozen(monkeypatch, tmp_path):
    # Simulate PyInstaller frozen app: config should be next to exe
    fake_exe_dir = tmp_path / "dist_dir"
    fake_exe_dir.mkdir()
    fake_exe = fake_exe_dir / "app.exe"

    monkeypatch.setattr(mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(mod.sys, "_MEIPASS", str(fake_exe_dir), raising=False)
    monkeypatch.setattr(mod.sys, "executable", str(fake_exe))

    # Limit argv so argparse doesn't see pytest args
    monkeypatch.setattr(mod.sys, "argv", ["prog"])

    args = mod.parse_args()
    assert args.config == os.path.join(str(fake_exe_dir), "config.ini")


def test_main_verbose_prints_interval_and_jql_and_uses_default_out(monkeypatch, tmp_path, tmp_config_file, capsys):
    # verbose on, empty out to trigger default_out_name
    parsed = SimpleNamespace(
        config=str(tmp_config_file),
        out="",
        verbose=True,
        max_workers=1,
        timeout=5,
        insecure=False,
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)

    # Avoid SSL warnings branch; ensure_field_exists True so SOW added
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: True)

    # Provide a small set of issues
    fake_issues = [{"key": "T-1", "fields": {"summary": "S", "project": {"name": "P"}, "issuetype": {"name": "T"}, "priority": {"name": "M"}}}]
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: fake_issues)

    # Return one row
    row = {
        "Projeto": "P",
        "Tipo de Problema": "T",
        "Clave": "T-1",
        "Resumo": "S",
        "Prioridade": "M",
        "SoW": "9",
        "Data de Início": "2025-10-24",
        "Nome de Exibição": "User",
        "Tempo Gasto (h)": 1.25,
        "Descrição do Trabalho": "Did stuff",
    }
    monkeypatch.setattr(mod, "fetch_worklogs_for_issue", lambda *a, **k: [row])

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

    mod.main()
    out = capsys.readouterr().out

    # Ensure verbose printed JQL and Intervalo efetivo
    assert "Intervalo efetivo (UTC):" in out
    assert "JQL:" in out

    # Ensure default_out_name pattern was used and short file created
    # created_paths[0] is the full report path (first ExcelWriter call in main)
    assert created_paths, "No Excel files were recorded"
    full_path = created_paths[0]
    assert full_path.endswith(".xlsx")
    base = os.path.basename(full_path)
    assert re.match(r"^mJiraWorkLogExtractor-\d{4}-\d{2}-\d{2}-\d{4}\.xlsx$", base)
    # short file path uses _short suffix
    assert any(p.endswith("_short.xlsx") for p in created_paths)
