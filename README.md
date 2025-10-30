# mJiraWorkLogExtractor

Exports Jira Cloud worklogs to Excel, with a full report and a short report. Designed for monthly or custom date ranges, supports parallel fetching, robust retry logic, TLS/proxy options, and Windows trust store integration.

- Full report: all columns
- Short report: fewer columns, filename suffixed with `_short`
- Default output filename pattern: `mJiraWorkLogExtractor-YYYY-MM-DD-HHMM.xlsx`

This README explains setup, configuration, usage, and troubleshooting in detail.

## Table of Contents
- Overview
- Features
- How It Works
- Requirements
- Installation (from source)
- Configuration (config.ini + environment variables)
  - File location rules
  - All options explained
  - Environment variable fallback
  - Examples
- Usage
  - Running from source
  - Running the Windows EXE
- Output files and columns
- Date range logic
- Authentication and permissions
- TLS/SSL, proxies, and Windows trust store
- Performance and rate limiting
- Troubleshooting
- Building a standalone EXE (PyInstaller)
- FAQ

---

## Overview

mJiraWorkLogExtractor v11 collects worklogs for Jira issues that have worklog dates in a target range, then writes:
1) A full Excel report (`.xlsx`) including key issue attributes and worklog details.
2) A short Excel report with fewer columns for quick summaries.

The tool is oriented to Jira Cloud REST API v3 and uses a simple `config.ini` for credentials and parameters, with environment variable fallbacks.

## Features

- Date range resolution:
  - Start defaults to the first day of the current month.
  - End defaults to today (inclusive; internally uses the next day at 00:00:00 as the exclusive upper bound).
  - Optional `start_date`/`end_date` (YYYY-MM-DD) to override.
- Robust HTTP handling with retries/backoff for 429/5xx responses (GET and POST).
- Parallel fetching for worklogs to improve performance.
- TLS control:
  - `verify_ssl` toggle
  - Custom `ca_bundle`
  - Windows trust store support (`certifi-win32`, optional import)
- Proxy support (`http_proxy`, `https_proxy`)
- Two Excel outputs (full and short).
- Configurable SoW custom field ID via config or CLI flag.
- Environment variable fallback for credentials and dates.

## How It Works

High-level flow:
1) Parse CLI args and read `config.ini` (with environment variable fallback).
2) Compute date bounds (inclusive start, exclusive end+1 day internally). Start defaults to the first day of the current month; end defaults to today if not provided.
3) Build a JQL range and query issues via `/rest/api/3/search/jql` (POST, paginated, with retry/backoff).
4) For each issue, fetch all worklogs, filter by date range, and map to report rows.
5) Create the full Excel report, then derive the short Excel report with selected columns.

## Requirements

- Python 3.9+ recommended
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
  Optional (Windows trust integration):
  ```bash
  pip install certifi-win32
  ```

## Installation (from source)

1) Clone or copy this repository.
2) Optional: create and activate a virtual environment.
3) Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4) Prepare `config.ini` or environment variables (see Configuration).

## Configuration (config.ini + environment variables)

The extractor reads settings from `config.ini` in INI format under the `[jira]` section. If a value is missing in config, it falls back to environment variables.

### File location rules

- When running as a PyInstaller-frozen executable: the default `config.ini` path is the same directory as the executable.
- When running from source: the default `config.ini` path is the repository directory where the script is located.
- You can override the config path via `--config`.

### Options (all in the `[jira]` section)

- base_url (required)
  - Your Jira Cloud base URL. Example: `https://yourcompany.atlassian.net`
- email (required)
  - Jira account email used for API authentication.
- api_token (required)
  - Jira API token for your account.
- sow_field_id (optional)
  - Jira custom field ID used for SoW (default: `customfield_11921`). Many instances use different IDs; set this if needed.
- max_workers (optional, default: 8)
  - Controls concurrency for fetching worklogs. If not provided on CLI, the value from config (if set) is used; otherwise defaults to 8. CLI flag `--max-workers` overrides this config value.
- verify_ssl (optional, default: true)
  - `true` to verify SSL certs; `false` to disable verification (not recommended).
- ca_bundle (optional)
  - Path to a custom CA bundle PEM file to verify SSL.
  - If set, it overrides `verify_ssl`.
- http_proxy, https_proxy (optional)
  - Proxy URLs if your network requires HTTP/HTTPS proxies.
- start_date (optional)
  - Date string (`YYYY-MM-DD`) for the inclusive start bound of the report.
- end_date (optional)
  - Date string (`YYYY-MM-DD`) for the inclusive end bound (the tool uses the day after internally as the exclusive upper bound).

Important:
- Do not commit your personal `config.ini` with secrets (email, api_token) to source control.
- Keep your API tokens secure.

### Environment variable fallback

If keys are missing in `config.ini`, the tool will read from these environment variables:
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_START_DATE` (optional)
- `JIRA_END_DATE` (optional)

You may create a local `.env` file (not required and not automatically loaded) and export these variables in your shell, or configure them in your CI/CD environment. See `.env.example` for placeholders.

### Example: Template (from TEMPLATE_config.ini)
```ini
[jira]
base_url   = https://your_company.atlassian.net
email      = usuario@empresa.com
api_token  = seu_api_token

; Optional: override SoW custom field id if your Jira uses a different ID
sow_field_id =

# Optional TLS/proxy
verify_ssl = true
ca_bundle  = C:\path\to\corp-root.pem
http_proxy  =
https_proxy =

# Optional date overrides (YYYY-MM-DD)
start_date = 2025-10-01
end_date   = 2025-10-31
```

### Example: Minimal config
```ini
[jira]
base_url  = https://yourcompany.atlassian.net
email     = your.name@yourcompany.com
api_token = <your_api_token>
```

### Example: Corporate TLS and proxies
```ini
[jira]
base_url   = https://yourcompany.atlassian.net
email      = your.name@yourcompany.com
api_token  = <your_api_token>

verify_ssl = true
ca_bundle  = C:\certs\corp-root.pem
http_proxy  = http://proxy.mycorp.local:8080
https_proxy = http://proxy.mycorp.local:8080

start_date = 2025-10-01
end_date   = 2025-10-31
```

## Usage

Common CLI options:
- `--config` Path to config file (default as per location rules).
- `--out` Output `.xlsx` filename. If omitted, a default timestamped name is used.
- `--verbose` Print extra logs (JQL, ranges, totals).
- `--max-workers` Max threads for parallel worklog fetch (default: from config or 8).
- `--timeout` Per-request timeout seconds (default: 120).
- `--insecure` Disables SSL verification (not recommended; similar to `verify_ssl = false`).
- `--sow-field-id` Override Jira SoW custom field id (e.g., `customfield_12345`).

When SSL verification is disabled (via `--insecure` or `verify_ssl=false` without a `ca_bundle`), the tool prints an explicit WARNING to stderr and disables urllib3 insecure warnings.

### Running from source
```bash
python mJiraWorkLogExtractor.py --verbose
```

With a specific config and output filename:
```bash
python mJiraWorkLogExtractor.py --config ./config.ini --out ./worklogs-oct.xlsx --verbose
```

Override SoW field ID:
```bash
python mJiraWorkLogExtractor.py --config ./config.ini --sow-field-id customfield_12345
```

### Running the Windows EXE
Place `config.ini` next to `mJiraWorkLogExtractor.exe`, then:
```powershell
.\mJiraWorkLogExtractor.exe --verbose
```
Or specify an alternate config:
```powershell
.\mJiraWorkLogExtractor.exe --config C:\path\to\config.ini --verbose
```

## Output files and columns

- Full report: `<name>.xlsx` with sheet name `Relatório`
- Short report: `<name>_short.xlsx` with sheet name `Relatório`

Full report columns:
- Projeto
- Tipo de Problema
- Clave
- Resumo
- Prioridade
- SoW
- Data de Início
- Nome de Exibição
- Tempo Gasto (h)
- Descrição do Trabalho

Short report columns:
- Projeto
- Clave
- Resumo
- SoW
- Data de Início
- Nome de Exibição
- Tempo Gasto (h)

## Date range logic

- If `start_date` and/or `end_date` are provided in config, they are used.
  - `start_date`: inclusive at 00:00:00 in UTC.
  - `end_date`: inclusive; internally, the tool sets the exclusive upper bound to the next day at 00:00:00 UTC.
- If not provided:
  - start defaults to the first day of the current month at 00:00:00 UTC.
  - end defaults to today (inclusive), implemented as an exclusive upper bound of tomorrow at 00:00:00 UTC.
- JQL used:
  ```
  worklogDate >= "YYYY-MM-DD" AND worklogDate <= "YYYY-MM-DD"
  ```
  The `<=` bound corresponds to the inclusive `end_date`.

Time zone:
- The filtering and defaults use UTC internally.

## Authentication and permissions

- You need a Jira API token associated with your account.
- Generate a token here: https://id.atlassian.com/manage-profile/security/api-tokens
- Permissions:
  - Your account must be able to browse projects/issues and view worklogs in the target projects.

## TLS/SSL, proxies, and Windows trust store

- `verify_ssl = true` (default) validates server certificates.
- To trust your corporate CA, set `ca_bundle` to your PEM file path.
- To disable verification (testing only), set `verify_ssl = false` or use `--insecure`.
  - The tool will emit a WARNING to stderr and disable urllib3 insecure warnings.
- Proxies: set `http_proxy`/`https_proxy` in `config.ini`.
- Windows trust store:
  - The tool optionally imports `certifi-win32` on Windows to leverage the Windows trust store. If unavailable, it continues without error.

## Performance and rate limiting

- Concurrency: set via `--max-workers` (default: 8).
- Timeout: per-request seconds via `--timeout` (default: 120).
- Rate limiting:
  - 429 or 5xx responses trigger exponential backoff (honors `Retry-After` when present) for both GET and POST requests.
  - If Jira is rate limiting, consider lowering `--max-workers`.

## Troubleshooting

- SSL errors:
  - Ensure `verify_ssl = true` and provide `ca_bundle` with your corporate root CA if needed.
  - As a last resort, use `verify_ssl = false` or `--insecure` (not recommended for production).
- 401 Unauthorized:
  - Check `email` and `api_token`. Ensure the token is valid and the email matches the token’s account.
- 403 Forbidden:
  - Verify your account has permissions to view the issues and worklogs.
- 429 Too Many Requests:
  - Reduce `--max-workers`. The tool already retries with backoff.
- Proxy issues:
  - Confirm `http_proxy`/`https_proxy` values and your network requirements.
- Invalid date format:
  - Use `YYYY-MM-DD` for `start_date`/`end_date`.
- SoW field missing:
  - The tool tries to detect the SoW field. If absent, it logs a warning and leaves the SoW column blank.
  - If your Jira uses a different ID for SoW, set `sow_field_id` in config or pass `--sow-field-id`.

## Building a standalone EXE (PyInstaller)

A spec file `mJiraWorkLogExtractor.spec` is included.

Quick build example:
```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --name mJiraWorkLogExtractor --icon mJiraWorkLogExtractor.ico --hidden-import dateutil.relativedelta  mJiraWorkLogExtractor.py
```

Notes:
- Place `config.ini` next to the generated `mJiraWorkLogExtractor.exe`.
- If you need corporate CA trust, distribute the CA PEM and point `ca_bundle` to it in `config.ini`.
- On Windows, installing `certifi-win32` allows using the Windows trust store automatically.

## FAQ

- Q: Where does the tool look for `config.ini` by default?
  - A: Next to the executable if frozen; otherwise next to the Python source file. You can override with `--config`.

- Q: What time zone is used for date filtering?
  - A: UTC boundaries are used internally. JQL uses inclusive days for `worklogDate`.

- Q: What if my company requires a proxy?
  - A: Set `http_proxy` and `https_proxy` in `config.ini`. The tool will route requests accordingly.

- Q: How do I set credentials without a local file?
  - A: Export `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` environment variables. Optionally `JIRA_START_DATE` and `JIRA_END_DATE`.

- Q: Can I customize the SoW field ID?
  - A: Yes, set `sow_field_id` in the config or pass `--sow-field-id customfield_XXXXX`.

- Q: What pandas/openpyxl versions are required?
  - A: See `requirements.txt` for pinned versions used by this project.

---

Keep your `config.ini` and any `.env` secrets safe and do not commit real credentials/tokens to version control.
