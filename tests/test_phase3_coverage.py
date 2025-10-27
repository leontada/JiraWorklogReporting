from types import SimpleNamespace
import importlib
import pytest
import requests

import mJiraWorkLogExtractor as mod


def test_http_get_with_retry_sslerror_propagates():
    class Sess:
        def get(self, url, params=None, timeout=None):
            raise requests.exceptions.SSLError("ssl boom")

    with pytest.raises(requests.exceptions.SSLError):
        mod.http_get_with_retry(Sess(), "https://x", timeout=1)


def test_adf_to_text_bullet_list_prefix():
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Item 1"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Item 2"}]}
                        ],
                    },
                ],
            }
        ],
    }
    txt = mod.adf_to_text(adf)
    # Each listItem should be prefixed with "- "
    assert "- Item 1" in txt
    assert "- Item 2" in txt


def test_win_trust_optional_import_branch(monkeypatch):
    # Force the optional Windows trust import path to execute successfully
    # by making importlib.util.find_spec report a module and import_module succeed.
    monkeypatch.setattr("os.name", "nt", raising=False)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object() if name == "certifi_win32" else None)

    called = {"imported": False}

    def fake_import(name):
        if name == "certifi_win32":
            called["imported"] = True
            class Dummy:
                pass
            return Dummy()
        return importlib.__import__(name)

    monkeypatch.setattr("importlib.import_module", fake_import)

    # Reload module to run the top-level optional import logic again
    mod_reloaded = importlib.reload(mod)

    assert called["imported"] is True
    # _WIN_TRUST should be True when the optional import path is successful
    assert getattr(mod_reloaded, "_WIN_TRUST", False) is True


def test_win_trust_non_windows_skips(monkeypatch):
    # Simulate non-Windows OS so block should not run (coverage of early branch)
    monkeypatch.setattr("os.name", "posix", raising=False)
    mod_reloaded = importlib.reload(mod)
    assert getattr(mod_reloaded, "_WIN_TRUST", False) is False


def test_win_trust_import_exception(monkeypatch):
    # Simulate Windows but importlib raises, exercising the except branch to False
    monkeypatch.setattr("os.name", "nt", raising=False)

    def boom_find_spec(name):
        raise RuntimeError("boom")

    monkeypatch.setattr("importlib.util.find_spec", boom_find_spec, raising=False)
    mod_reloaded = importlib.reload(mod)
    assert getattr(mod_reloaded, "_WIN_TRUST", False) is False
