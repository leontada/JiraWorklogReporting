"""
mJiraWorkLogExtractor v11

Thin wrapper delegating all functionality to the package module to avoid duplication.
This preserves backward compatibility for imports/tests while making the package
the single source of truth.

- Windows trust (certifi-win32) optional import is kept here to satisfy tests that
  reload this module and inspect _WIN_TRUST.
- All runtime logic and functions are provided by jira_worklog_extractor.core.
"""

import os

# Optional Windows trust store integration via certifi-win32.
# Kept here so reloading this module re-runs the detection for tests.
_WIN_TRUST = False
if os.name == "nt":
    try:
        import importlib.util
        spec = importlib.util.find_spec("certifi_win32")
        if spec is not None:
            import importlib
            importlib.import_module("certifi_win32")  # applies Windows cert store patch
            _WIN_TRUST = True
    except Exception:
        _WIN_TRUST = False

# Re-export public API from the package core (single source of truth)
from jira_worklog_extractor.core import *  # type: ignore  # noqa: F401,F403

# Ensure main is available from core
from jira_worklog_extractor.core import main  # type: ignore  # noqa: F401


if __name__ == "__main__":
    main()
