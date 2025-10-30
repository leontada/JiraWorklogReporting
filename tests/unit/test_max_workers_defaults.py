from types import SimpleNamespace

import pandas as pd
import mJiraWorkLogExtractor as mod


def _patch_io_and_http(monkeypatch):
    # Avoid real HTTP and Excel writing
    monkeypatch.setattr(mod, "ensure_field_exists", lambda *a, **k: True)
    monkeypatch.setattr(mod, "post_search_jql", lambda *a, **k: [])
    class DummyWriter:
        def __init__(self, path, engine=None): ...
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    monkeypatch.setattr(pd, "ExcelWriter", DummyWriter)
    monkeypatch.setattr(pd.DataFrame, "to_excel", lambda *a, **k: None)


def test_max_workers_invalid_in_config_uses_default(monkeypatch, tmp_path):
    # Invalid string for max_workers in config should fall back to default 8
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[jira]\n"
        "base_url = https://example.atlassian.net\n"
        "email = user@example.com\n"
        "api_token = tok\n"
        "verify_ssl = true\n"
        "max_workers = not-a-number\n",
        encoding="utf-8",
    )
    parsed = SimpleNamespace(
        config=str(cfg),
        out="",
        verbose=False,
        max_workers=None,  # no CLI override
        timeout=5,
        insecure=False,
        sow_field_id="",
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)
    _patch_io_and_http(monkeypatch)

    captured = {"mw": None}

    class DummyExecutor:
        def __init__(self, max_workers):
            captured["mw"] = max_workers
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    monkeypatch.setattr(mod, "ThreadPoolExecutor", DummyExecutor)

    mod.main()
    assert captured["mw"] == 8


def test_max_workers_default_when_no_cfg_no_cli(monkeypatch, tmp_path):
    # No config value and no CLI value -> default to 8
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[jira]\n"
        "base_url = https://example.atlassian.net\n"
        "email = user@example.com\n"
        "api_token = tok\n"
        "verify_ssl = true\n",
        encoding="utf-8",
    )
    parsed = SimpleNamespace(
        config=str(cfg),
        out="",
        verbose=False,
        max_workers=None,  # no CLI override
        timeout=5,
        insecure=False,
        sow_field_id="",
    )
    monkeypatch.setattr(mod, "parse_args", lambda: parsed)
    _patch_io_and_http(monkeypatch)

    captured = {"mw": None}

    class DummyExecutor:
        def __init__(self, max_workers):
            captured["mw"] = max_workers
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    monkeypatch.setattr(mod, "ThreadPoolExecutor", DummyExecutor)

    mod.main()
    assert captured["mw"] == 8
