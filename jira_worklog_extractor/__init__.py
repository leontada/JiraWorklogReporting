"""
jira_worklog_extractor package

Phase 3 packaging shim:
- Re-exports from the package core as the single source of truth.
"""

# Re-export everything from the package core (single source of truth)
from .core import *  # noqa: F401,F403
