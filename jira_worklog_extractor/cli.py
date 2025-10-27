"""
Console script entrypoint for jira-worklog-extractor.

Delegates to the existing legacy script's main() to preserve behavior while
we gradually refactor into a modular package.
"""
from __future__ import annotations


def main() -> None:
    # Import inside function to avoid import-time side effects if this module
    # is imported for introspection.
    from mJiraWorkLogExtractor import main as _main  # type: ignore

    _main()


if __name__ == "__main__":
    main()
