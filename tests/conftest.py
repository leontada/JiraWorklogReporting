import os
import sys
# Ensure project root is importable for tests, regardless of runner CWD
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Route legacy module name to the single source of truth (package core)
# This keeps existing tests importing mJiraWorkLogExtractor working without duplicating code.
import importlib
_core_mod = importlib.import_module("jira_worklog_extractor.core")
sys.modules["mJiraWorkLogExtractor"] = _core_mod

import types
import time as _time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest
import requests


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Optional[Any] = None,
        text: str = "",
        headers: Optional[Dict[str, str]] = None,
        raise_for_status_exc: Optional[Exception] = None,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}
        self._raise_exc = raise_for_status_exc

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        if 400 <= self.status_code:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            # attach minimal response info for code under test
            err.response = types.SimpleNamespace(status_code=self.status_code, text=self.text)
            raise err


def make_http_error(status: int) -> requests.HTTPError:
    err = requests.HTTPError(f"HTTP {status}")
    err.response = types.SimpleNamespace(status_code=status, text=f"{status} error")
    return err


@pytest.fixture
def no_sleep(monkeypatch):
    """Make time.sleep a no-op for faster retry tests."""
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    yield


@pytest.fixture
def tmp_config_file(tmp_path):
    """Create a minimal valid config.ini and return its path."""
    p = tmp_path / "config.ini"
    p.write_text(
        "[jira]\n"
        "base_url = https://example.atlassian.net\n"
        "email = user@example.com\n"
        "api_token = token123\n"
        "verify_ssl = true\n",
        encoding="utf-8",
    )
    return p


# Expose utilities for tests
__all__ = ["FakeResponse", "make_http_error"]
