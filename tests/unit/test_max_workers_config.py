from types import SimpleNamespace

import pandas as pd
import mJiraWorkLogExtractor as mod


def test_max_workers_from_config(monkeypatch, tmp_path):
    # Create a config with max_workers set
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[jira]\n"
        "base_url = https://example.atlassian.net\n"
        "email = user@example.com\n"
        "api_token = tok\n"
        "verify_ssl = true\n"
        "max_workers = 3\n",
        encoding="utf-8",
    )

    # CLI does not provide max_workers -> should fallback to config value
    parsed = SimpleNamespace(
        config=str(cfg),
        out="",
        verbose=False,
        max_workers=None,
        timeout=5,
        insecure=False,
        sow_field_id="",
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)

    # Avoid real HTTP and Excel writing
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: True)
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: [])

    class DummyWriter:
        def __init__(self, path, engine=None): ...
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda *a, **k: None)

    # Capture the max_workers used to instantiate the executor
    captured = {"mw": None}

    class DummyExecutor:
        def __init__(self, max_workers):
            captured["mw"] = max_workers
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    monkeypatch.setattr(mod, "ThreadPoolExecutor", DummyExecutor)

    # Run
    mod.main()

    assert captured["mw"] == 3


def test_max_workers_cli_overrides_config(monkeypatch, tmp_path):
    # Config with max_workers = 2, CLI provides 5 -> CLI should win
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[jira]\n"
        "base_url = https://example.atlassian.net\n"
        "email = user@example.com\n"
        "api_token = tok\n"
        "verify_ssl = true\n"
        "max_workers = 2\n",
        encoding="utf-8",
    )

    parsed = SimpleNamespace(
        config=str(cfg),
        out="",
        verbose=False,
        max_workers=5,
        timeout=5,
        insecure=False,
        sow_field_id="",
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: True)
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: [])

    class DummyWriter:
        def __init__(self, path, engine=None): ...
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda *a, **k: None)

    captured = {"mw": None}

    class DummyExecutor:
        def __init__(self, max_workers):
            captured["mw"] = max_workers
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    monkeypatch.setattr(mod, "ThreadPoolExecutor", DummyExecutor)

    mod.main()

    assert captured["mw"] == 5
