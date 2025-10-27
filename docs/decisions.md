# Architecture Decisions (ADR)

- Date: 2025-10-27

- Context:
  The project is a robust single-file CLI tool that exports Jira Cloud worklogs to Excel, with high test coverage and PyInstaller packaging. To improve production readiness per rules (.clinerules) and reduce operational risk, we needed to:
  - Align documentation with real behavior (Windows trust store support).
  - Avoid hardcoding operationally variable values (SoW custom field ID).
  - Improve security posture (env var support for secrets, explicit SSL warning).
  - Increase HTTP robustness (retry for POST as well as GET).
  - Improve reproducibility and developer ergonomics (requirements.txt, .editorconfig, .env.example).
  These are non-breaking “Phase 1” changes designed to keep current tests green.

- Decision:
  1) Windows trust store support (optional import)
     - Re-enable optional import of `certifi-win32` to leverage Windows trust. If not available, continue without error.
     - Code: optional import at module load; sets `_WIN_TRUST` flag.
     - Docs updated to reflect optional behavior.

  2) Environment variable fallback for secrets and dates
     - `read_config` now falls back to env vars when INI keys are missing:
       - JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_START_DATE, JIRA_END_DATE
     - Added `.env.example` and `.gitignore` rules for `.env`.

  3) Configurable SoW field ID
     - New optional `[jira] sow_field_id` in config.
     - New CLI flag `--sow-field-id` to override per-run.
     - Default remains `customfield_11921` if neither config nor flag provided.

  4) HTTP POST retry/backoff
     - Introduced `http_post_with_retry` mirroring GET retry logic (429/5xx, honors Retry-After).
     - `post_search_jql` uses this helper. Tests remain fast by using `backoff_base=0.0` at call-site.

  5) Explicit SSL insecure warning
     - When verification is disabled (`--insecure` or `verify_ssl=false` without `ca_bundle`), print a WARNING to stderr and disable urllib3 insecure warnings.

  6) Safer Excel writing
     - Ensure output directory exists (`os.makedirs(..., exist_ok=True)`).
     - Wrap Excel writing in try/except; on failure, print error and exit with code 4.

  7) Reproducibility and editor settings
     - Added `requirements.txt` with pinned versions.
     - Added `.editorconfig` for consistent formatting.
     - Updated README with new flags, env vars, and security notes.
     - Updated `TEMPLATE_config.ini` to include optional `sow_field_id`.

- Alternatives Considered:
  - Introduce logging subsystem now (structured logging, levels) and replace prints: postponed to Phase 2 to avoid touching many tests at once.
  - Replace `sys.exit` in helpers with exceptions and handle only in `main`: also Phase 2 to change error-handling strategy without breaking tests.
  - Full package refactor (multi-module + pyproject): Phase 3 to keep Phase 1 minimal and non-breaking.

- Consequences:
  - Minimal behavior change with better ops posture (security and resiliency).
  - Docs and code are now consistent about Windows trust store behavior.
  - Users with different Jira SoW field IDs can configure without editing code.
  - CI/CD and local onboarding are simplified with pinned requirements and `.editorconfig`.
  - A small new stderr WARNING appears when SSL is disabled, which is intentional.

- Related Issues/PRs:
  - Phase 1 implementation in:
    - mJiraWorkLogExtractor.py (optional certifi_win32, env fallback, sow_field_id, POST retry, SSL warning, safer Excel writing)
    - README.md (docs updates)
    - TEMPLATE_config.ini (sow_field_id)
    - requirements.txt (pinned deps)
    - .editorconfig (editor config)
    - .env.example and .gitignore update (env handling)

- Next Steps (Phase 2–3 roadmap, separate PRs):
  - Phase 2: Introduce logging; convert helper `sys.exit` to exceptions; main handles exit codes. Add jitter to backoff; optional CLI/config for retry params.
  - Phase 3: Restructure into a package; pyproject.toml; console entry point; CI with lint, type-check, test matrix, and PyInstaller build artifacts.
