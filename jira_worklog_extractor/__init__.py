"""
jira_worklog_extractor package

Phase 3 packaging shim:
- Re-exports from the legacy mJiraWorkLogExtractor module to preserve backward compatibility.
- Provides a package-level main() suitable for console_scripts entrypoints.
"""

# Re-export everything from the legacy module to keep existing imports/tests working
from mJiraWorkLogExtractor import *  # type: ignore  # noqa: F401,F403


def main() -> None:
    """Package entrypoint. Delegates to the legacy script's main()."""
    from mJiraWorkLogExtractor import main as _main
    _main()
