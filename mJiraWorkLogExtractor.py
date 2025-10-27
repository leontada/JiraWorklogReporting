"""
mJiraWorkLogExtractor v11
- Adds a secondary short report with fewer columns.
  The short file name = same as full, but suffixed with "_short".

Carries forward v10 features:
- Date overrides via config.ini (start_date/end_date)
- TLS/proxy options, --insecure, Windows trust (certifi-win32)
- Progress bar (tqdm), parallel fetching, retries, numeric SoW-only
- Default filename mJiraWorkLogExtractor-YYYY-MM-DD-HHMM.xlsx

- Command to generate .exe file:
    pyinstaller --onefile --name mJiraWorkLogExtractor --icon mJiraWorkLogExtractor.ico --hidden-import dateutil.relativedelta  mJiraWorkLogExtractor.py
"""

import argparse
import configparser
import sys
import os
import re
import time
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil.relativedelta import relativedelta
import requests
import pandas as pd
from tqdm import tqdm
import urllib3

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

DEFAULT_TZ = timezone.utc
SOW_FIELD_ID = "customfield_11921"

COLS = [
    "Projeto",
    "Tipo de Problema",
    "Clave",
    "Resumo",
    "Prioridade",
    "SoW",
    "Data de Início",
    "Nome de Exibição",
    "Tempo Gasto (h)",
    "Descrição do Trabalho",
]

SHORT_COLS = [
    "Projeto",
    "Clave",
    "Resumo",
    "SoW",
    "Data de Início",
    "Nome de Exibição",
    "Tempo Gasto (h)",
]

def month_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    """Return the month bounds in DEFAULT_TZ for the given datetime.

    Returns:
        tuple[datetime, datetime]: (start, end) where start is the first instant
        of the month in DEFAULT_TZ, and end is the first instant of the next
        month (exclusive).
    """
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=DEFAULT_TZ)
    end = start + relativedelta(months=1)
    return start, end

def parse_config_date(s: str) -> Optional[datetime]:
    """Parse a config date string (YYYY-MM-DD) into a timezone-aware datetime.

    The returned datetime is set to midnight (00:00:00) in DEFAULT_TZ.
    Returns None for empty strings or when parsing fails.
    """
    if not s:
        return None
    try:
        d = datetime.strptime(s.strip(), "%Y-%m-%d")
        return d.replace(tzinfo=DEFAULT_TZ)
    except Exception:
        return None

def compute_bounds(now_utc: datetime, start_str: str, end_str: str) -> Tuple[datetime, datetime]:
    """
    Compute the UTC date bounds (start inclusive, end exclusive) used for JQL and filtering.

    Logic:
    - Start:
      If start_str (YYYY-MM-DD) is provided and valid, use that date at 00:00:00 in DEFAULT_TZ.
      Otherwise, use the first instant of the month of now_utc in DEFAULT_TZ.
    - End:
      If end_str is provided and valid, use the day after that date at 00:00:00 (exclusive upper bound).
      Otherwise, use the day after today at 00:00:00 (exclusive upper bound).
    - Safety:
      Ensures end is strictly after start; if not, sets end = start + 1 day.

    Returns:
        tuple[datetime, datetime]: (start, end) timezone-aware datetimes in DEFAULT_TZ.
    """
    month_start, month_end = month_bounds(now_utc)
    start = parse_config_date(start_str) or month_start
    if end_str:
        end_date = parse_config_date(end_str)
        if end_date:
            end = end_date + timedelta(days=1)
        else:
            end = month_end
    else:
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=DEFAULT_TZ)
        end = today_start + timedelta(days=1)
    if start >= end:
        end = start + timedelta(days=1)
    return start, end

def default_out_name(prefix: str="mJiraWorkLogExtractor") -> str:
    """Generate a default Excel output filename.

    The pattern is '<prefix>-YYYY-MM-DD-HHMM.xlsx' using the current local time.
    Args:
        prefix: Base name to prefix the timestamp with. Defaults to 'mJiraWorkLogExtractor'.
    Returns:
        str: The generated filename with .xlsx extension.
    """
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    return f"{prefix}-{ts}.xlsx"

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the extractor.

    Returns:
        argparse.Namespace: Parsed command-line options provided via CLI.
    """
    def app_dir() -> str:
        """Return the application directory.

        When running as a PyInstaller-frozen executable, this points to the
        directory of the bundled executable. Otherwise, it returns the directory
        of this source file.
        """
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    default_cfg = os.path.join(app_dir(), "config.ini")

    p = argparse.ArgumentParser(description="Exporta horas em intervalo definido (ou mês corrente) para .xlsx.")
    p.add_argument("--config", default=default_cfg, help=f"Caminho para o config.ini (padrão: {default_cfg})")
    p.add_argument("--out", default="", help="Arquivo .xlsx de saída; se vazio usa padrão mJiraWorkLogExtractor-YYYY-MM-DD-HHMM.xlsx")
    p.add_argument("--verbose", action="store_true", help="Logs detalhados")
    p.add_argument("--max-workers", type=int, default=8, help="Máximo de threads para worklogs (default=8)")
    p.add_argument("--timeout", type=int, default=120, help="Timeout por requisição (s) (default=120)")
    p.add_argument("--insecure", action="store_true", help="DESATIVA verificação SSL (NÃO RECOMENDADO)")
    p.add_argument("--sow-field-id", default="", help="Override Jira SoW custom field id (e.g., customfield_12345)")
    return p.parse_args()

def vprint(verbose: bool, *args, **kwargs):
    """Print arguments only when verbose is True."""
    if verbose:
        print(*args, **kwargs)

def read_config(path: str) -> Dict[str, Any]:
    """Read and validate configuration from an INI file.

    Args:
        path: Path to config.ini.

    Returns:
        Dict[str, Any]: Normalized configuration values required to run.
    """
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    if "jira" not in cp:
        print("ERRO: config.ini deve conter seção [jira].", file=sys.stderr)
        sys.exit(2)
    sec = cp["jira"]
    base_url = sec.get("base_url", "").strip().rstrip("/")
    email    = sec.get("email", "").strip()
    token    = sec.get("api_token", "").strip()
    # Fallback para variáveis de ambiente (não requer python-dotenv)
    base_url = (base_url or os.environ.get("JIRA_BASE_URL", "")).strip().rstrip("/")
    email    = (email or os.environ.get("JIRA_EMAIL", "")).strip()
    token    = (token or os.environ.get("JIRA_API_TOKEN", "")).strip()
    if not (base_url and email and token):
        print("ERRO: base_url, email e api_token são obrigatórios (config.ini ou variáveis de ambiente).", file=sys.stderr)
        sys.exit(2)

    verify_ssl = sec.get("verify_ssl", "true").strip().lower() in ("1", "true", "yes", "on")
    ca_bundle  = sec.get("ca_bundle", "").strip()
    http_proxy  = sec.get("http_proxy", "").strip()
    https_proxy = sec.get("https_proxy", "").strip()

    start_date = sec.get("start_date", "").strip() or os.environ.get("JIRA_START_DATE", "").strip()
    end_date   = sec.get("end_date", "").strip() or os.environ.get("JIRA_END_DATE", "").strip()
    sow_field_id = sec.get("sow_field_id", "").strip()

    return {
        "base_url": base_url,
        "email": email,
        "token": token,
        "verify_ssl": verify_ssl,
        "ca_bundle": ca_bundle,
        "http_proxy": http_proxy,
        "https_proxy": https_proxy,
        "start_date": start_date,
        "end_date": end_date,
        "sow_field_id": sow_field_id,
    }

def make_session(email: str, token: str, verify: Optional[bool]=True, ca_bundle: Optional[str]="",
                 http_proxy: str="", https_proxy: str="") -> requests.Session:
    """Create a configured requests.Session for Jira API access.

    Applies basic auth with email/token, JSON headers, optional proxies,
    and SSL verification or custom CA bundle.

    Args:
        email: Jira account email (username).
        token: Jira API token (password).
        verify: Whether to verify SSL certs (ignored if ca_bundle provided).
        ca_bundle: Path to CA bundle to use for SSL verification.
        http_proxy: HTTP proxy URL.
        https_proxy: HTTPS proxy URL.

    Returns:
        requests.Session: Configured session instance.
    """
    s = requests.Session()
    s.auth = (email, token)
    s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    if http_proxy or https_proxy:
        proxies = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        s.proxies.update(proxies)
    if ca_bundle:
        s.verify = ca_bundle
    else:
        s.verify = verify
    return s

def ensure_field_exists(session: requests.Session, base_url: str, field_id: str, timeout: int, verbose=False) -> bool:
    """Check whether a custom field exists in Jira.

    Performs a GET to /rest/api/3/field and searches for field_id.
    On HTTP errors, logs a warning and returns True to avoid hard-failing.

    Args:
        session: Configured requests session.
        base_url: Jira base URL.
        field_id: Target field id (e.g., customfield_xxxxx).
        timeout: Request timeout in seconds.
        verbose: Whether to print verbose logs.

    Returns:
        bool: True if the field exists or if validation is skipped; False if missing.
    """
    url = f"{base_url}/rest/api/3/field"
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        print("ERRO SSL ao acessar /field:", e, file=sys.stderr)
        raise
    except requests.HTTPError as e:
        print(f"AVISO: Falha ao listar campos ({getattr(e.response,'status_code', 'N/A')}). Continuando sem validar o SoW...", file=sys.stderr)
        return True
    except Exception as e:
        print(f"AVISO: Falha não prevista ao listar campos: {e}. Continuando...", file=sys.stderr)
        return True

    exists = any(f.get("id") == field_id for f in r.json())
    if not exists:
        print(f"AVISO: Campo SoW '{field_id}' não encontrado. A coluna SoW ficará vazia.", file=sys.stderr)
    else:
        vprint(verbose, f"Campo SoW '{field_id}' detectado.")
    return exists

def jql_for_range(start_utc: datetime, end_utc: datetime) -> str:
    """Build JQL filtering worklogs between start and end-1 day (inclusive)."""
    date_from = start_utc.date().isoformat()
    date_to   = (end_utc - timedelta(days=1)).date().isoformat()
    return f'worklogDate >= "{date_from}" AND worklogDate <= "{date_to}"'

def post_search_jql(session: requests.Session, base_url: str, jql: str, fields: List[str], timeout: int, verbose=False) -> List[Dict[str, Any]]:
    """Query Jira using POST /search/jql and paginate using nextPageToken.

    Args:
        session: Configured requests session.
        base_url: Jira base URL.
        jql: JQL string to execute.
        fields: List of fields to request in the response.
        timeout: Per-request timeout.
        verbose: Whether to log details.

    Returns:
        List[Dict[str, Any]]: Aggregated list of issue objects.
    """
    url = f"{base_url}/rest/api/3/search/jql"
    next_token: Optional[str] = None
    issues_all: List[Dict[str, Any]] = []
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if next_token:
            body["nextPageToken"] = next_token
        r = http_post_with_retry(session, url, json=body, timeout=timeout, backoff_base=0.0)
        try:
            r.raise_for_status()
        except requests.HTTPError:
            print(f"ERRO: search/jql falhou ({getattr(r,'status_code','N/A')}). Resposta do servidor:\n{getattr(r,'text','')}", file=sys.stderr)
            sys.exit(3)
        data = r.json()
        issues = data.get("issues", [])
        issues_all.extend(issues)
        next_token = data.get("nextPageToken")
        if not next_token or not issues:
            break
    return issues_all

def adf_to_text(adf: Any) -> str:
    """Convert Atlassian Document Format (ADF) content to plain text."""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return ""
    result_lines: List[str] = []

    def walk(node: Any):
        """Depth-first traversal of ADF nodes; collects plain text into result_lines."""
        t = node.get("type") if isinstance(node, dict) else None
        if t == "doc":
            for c in node.get("content", []):
                walk(c)
        elif t in ("paragraph", "heading", "blockquote"):
            segs: List[str] = []
            for c in node.get("content", []):
                if c.get("type") == "text":
                    segs.append(c.get("text", ""))
                elif c.get("type") == "hardBreak":
                    segs.append("\n")
                else:
                    txt = c.get("text")
                    if isinstance(txt, str):
                        segs.append(txt)
            result_lines.append("".join(segs))
        elif t in ("bulletList", "orderedList"):
            for li in node.get("content", []):
                walk(li)
        elif t == "listItem":
            before = len(result_lines)
            for c in node.get("content", []):
                walk(c)
            for i in range(before, len(result_lines)):
                if result_lines[i].strip():
                    result_lines[i] = "- " + result_lines[i]
        else:
            if isinstance(node, dict):
                for c in node.get("content", []):
                    walk(c)

    walk(adf)
    text = "\n".join([line.rstrip() for line in result_lines]).strip()
    return text

def _best_label(d: Dict[str, Any]) -> str:
    """Return the best human-friendly label from a field-like dict."""
    for k in ("value", "name", "label", "title", "key"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    v = d.get("id")
    return str(v) if v is not None else ""

def _flatten_hierarchy(d: Dict[str, Any]) -> List[str]:
    """Flatten a hierarchical structure (using 'child' or 'children') into labels."""
    labels: List[str] = []
    cur = d
    while isinstance(cur, dict):
        lab = _best_label(cur)
        if lab:
            labels.append(lab)
        nxt = cur.get("child")
        if not nxt and isinstance(cur.get("children"), list):
            nxt = (cur["children"][0] if cur["children"] else None)
        if nxt is None:
            break
        cur = nxt
    return labels

def stringify_sow(val: Any) -> str:
    """Convert various SoW field shapes (str, dict tree, list) into a string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        parts = [stringify_sow(x) for x in val]
        parts = [p for p in parts if p]
        return " | ".join(parts)
    if isinstance(val, dict):
        labels = _flatten_hierarchy(val)
        return ":".join(labels)
    return str(val)

def numeric_only(s: str) -> str:
    """Extract the first numeric substring from s; return '' if none found."""
    if not s:
        return ""
    m = re.search(r"\d+", s)
    return m.group(0) if m else ""

def http_get_with_retry(session: requests.Session, url: str, params: Optional[Dict[str, Any]]=None,
                        timeout: int=120, max_tries: int=5, backoff_base: float=0.5) -> Optional[requests.Response]:
    """HTTP GET with retry/backoff on 429 and 5xx responses.

    Honors Retry-After header when present; returns the final response even if
    it is an error after exhausting retries.

    Args:
        session: requests.Session to use.
        url: Target URL.
        params: Optional query parameters.
        timeout: Per-request timeout seconds.
        max_tries: Maximum number of attempts.
        backoff_base: Base seconds for exponential backoff.

    Returns:
        Optional[requests.Response]: Response object or None if a request failed before yielding a response.
    """
    tries = 0
    while True:
        tries += 1
        try:
            r = session.get(url, params=params, timeout=timeout)
        except requests.exceptions.SSLError as e:
            raise
        if r.status_code == 429 or 500 <= r.status_code < 600:
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = float(retry_after)
                except Exception:
                    wait = backoff_base * (2 ** (tries - 1))
            else:
                wait = backoff_base * (2 ** (tries - 1))
            if tries < max_tries:
                time.sleep(wait)
                continue
        try:
            r.raise_for_status()
            return r
        except requests.HTTPError:
            if tries < max_tries:
                time.sleep(backoff_base * (2 ** (tries - 1)))
                continue
            return r

def http_post_with_retry(session: requests.Session, url: str, json: Dict[str, Any],
                         timeout: int = 120, max_tries: int = 5, backoff_base: float = 0.5) -> requests.Response:
    """HTTP POST with retry/backoff on 429 and 5xx responses. Returns the final response."""
    tries = 0
    while True:
        tries += 1
        r = session.post(url, json=json, timeout=timeout)
        if r.status_code == 429 or 500 <= r.status_code < 600:
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = float(retry_after)
                except Exception:
                    wait = backoff_base * (2 ** (tries - 1))
            else:
                wait = backoff_base * (2 ** (tries - 1))
            if tries < max_tries:
                time.sleep(wait)
                continue
        try:
            r.raise_for_status()
            return r
        except requests.HTTPError:
            if tries < max_tries:
                time.sleep(backoff_base * (2 ** (tries - 1)))
                continue
            return r

def fetch_worklogs_for_issue(base_url: str, session_factory, issue: Dict[str, Any],
                             start_utc: datetime, end_utc: datetime, timeout: int) -> List[Dict[str, Any]]:
    """Fetch worklogs for a single issue and map to report rows within a date range.

    Args:
        base_url: Jira base URL.
        session_factory: Callable that returns a configured requests.Session.
        issue: Issue JSON object from search results.
        start_utc: Inclusive lower bound (DEFAULT_TZ).
        end_utc: Exclusive upper bound (DEFAULT_TZ).
        timeout: Per-request timeout seconds.

    Returns:
        List[Dict[str, Any]]: Row dicts ready for DataFrame construction.
    """
    key = issue.get("key")
    f = issue.get("fields", {})

    projeto    = (f.get("project") or {}).get("name", "")
    tipo       = (f.get("issuetype") or {}).get("name", "")
    prioridade = (f.get("priority") or {}).get("name", "")
    resumo     = f.get("summary", "")

    sow_raw = f.get(SOW_FIELD_ID, None)
    sow_str = stringify_sow(sow_raw)
    if " | " in sow_str:
        parts = [numeric_only(p) for p in sow_str.split(" | ")]
        parts = [p for p in parts if p]
        sow_value = " | ".join(parts)
    else:
        sow_value = numeric_only(sow_str)

    sess = session_factory()

    linhas: List[Dict[str, Any]] = []
    start_at = 0
    max_results = 100

    while True:
        url_wl = f"{base_url}/rest/api/3/issue/{key}/worklog"
        params = {"startAt": start_at, "maxResults": max_results}
        rw = http_get_with_retry(sess, url_wl, params=params, timeout=timeout)
        if rw is None or rw.status_code >= 400:
            sys.stderr.write(f"AVISO: worklog de {key} retornou status {getattr(rw,'status_code', 'N/A')}.\n")
            break
        wdata = rw.json()
        wlogs = wdata.get("worklogs", [])
        if not wlogs:
            break

        for wl in wlogs:
            started_raw = wl.get("started", "")
            try:
                if isinstance(started_raw, str) and started_raw.endswith("+0000"):
                    started_raw = started_raw[:-5] + "+00:00"
                dt = datetime.fromisoformat(started_raw)
            except Exception:
                dt = None
            if not dt or not (start_utc <= dt.astimezone(DEFAULT_TZ) < end_utc):
                continue

            display_name = (wl.get("author") or {}).get("displayName", "")
            seconds = wl.get("timeSpentSeconds", 0) or 0
            horas = round(seconds / 3600.0, 2)

            comment = wl.get("comment", "")
            if isinstance(comment, dict):
                desc = adf_to_text(comment)
            else:
                desc = str(comment) if comment else ""

            data_inicio = dt.date().isoformat()

            linhas.append({
                "Projeto": projeto,
                "Tipo de Problema": tipo,
                "Clave": key,
                "Resumo": resumo,
                "Prioridade": prioridade,
                "SoW": sow_value,
                "Data de Início": data_inicio,
                "Nome de Exibição": display_name,
                "Tempo Gasto (h)": horas,
                "Descrição do Trabalho": desc,
            })

        start_at += len(wlogs)
        if start_at >= wdata.get("total", 0):
            break

    return linhas

def main():
    """Program entry point to orchestrate extraction and export."""
    args = parse_args()
    cfg = read_config(args.config)
    base_url = cfg["base_url"]
    email    = cfg["email"]
    token    = cfg["token"]
    verify_ssl_cfg = bool(cfg.get("verify_ssl", True))
    ca_bundle = cfg.get("ca_bundle", "")
    http_proxy = cfg.get("http_proxy", "")
    https_proxy = cfg.get("https_proxy", "")
    global SOW_FIELD_ID
    sow_field_id_eff = (getattr(args, "sow_field_id", "").strip() or cfg.get("sow_field_id") or SOW_FIELD_ID)
    SOW_FIELD_ID = sow_field_id_eff

    if args.insecure:
        verify_val = False
    else:
        verify_val = verify_ssl_cfg

    if not verify_val and not ca_bundle:
        sys.stderr.write("WARNING: SSL certificate verification is DISABLED. Use only for testing.\n")
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    """     if verify_val:
            if _CERTIFI_WIN32_OK and os.name == "nt" and not ca_bundle:
                pass """

    verbose  = args.verbose
    timeout  = args.timeout
    max_workers = max(1, args.max_workers)

    start_str = cfg.get("start_date", "")
    end_str   = cfg.get("end_date", "")

    now = datetime.now(tz=DEFAULT_TZ)
    start_utc, end_utc = compute_bounds(now, start_str, end_str)
    if verbose:
        print(f"Intervalo efetivo (UTC): {start_utc.date().isoformat()} a {(end_utc - timedelta(days=1)).date().isoformat()} (inclusive)")

    jql = jql_for_range(start_utc, end_utc)
    if verbose:
        print("JQL:", jql)

    ses = make_session(email, token, verify=verify_val, ca_bundle=ca_bundle,
                       http_proxy=http_proxy, https_proxy=https_proxy)

    try:
        sow_ok = ensure_field_exists(ses, base_url, sow_field_id_eff, timeout=timeout, verbose=verbose)
    except requests.exceptions.SSLError as e:
        print("ERRO SSL persistente ao validar campos. Tente configurar verify_ssl=false, --insecure ou ca_bundle.", file=sys.stderr)
        raise

    fields_list = ["summary", "project", "issuetype", "priority"]
    if sow_ok:
        fields_list.append(sow_field_id_eff)

    issues = post_search_jql(ses, base_url, jql, fields_list, timeout=timeout, verbose=verbose)
    vprint(verbose, f"Total de issues para processar: {len(issues)}")

    def session_factory():
        """Factory to create a configured requests.Session for concurrent calls."""
        return make_session(email, token, verify=verify_val, ca_bundle=ca_bundle,
                            http_proxy=http_proxy, https_proxy=https_proxy)

    linhas_all: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                fetch_worklogs_for_issue, base_url, session_factory, issue, start_utc, end_utc, timeout
            )
            for issue in issues
        ]
        with tqdm(total=len(futures), desc="Processando issues", unit="issue") as pbar:
            for fut in as_completed(futures):
                try:
                    linhas_all.extend(fut.result())
                except requests.exceptions.SSLError as e:
                    sys.stderr.write(f"ERRO SSL em uma issue: {e}\n")
                except Exception as e:
                    sys.stderr.write(f"AVISO: falha em uma issue: {e}\n")
                finally:
                    pbar.update(1)

    out_path = args.out.strip() or default_out_name()
    if not out_path.lower().endswith(".xlsx"):
        out_path += ".xlsx"

    df = pd.DataFrame(linhas_all, columns=COLS)
    # Ensure output directory exists and write Excel files safely
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Relatório")

        # --- New: short file ---
        short_df = df[SHORT_COLS].copy()
        base_dir = os.path.dirname(out_path) or "."
        base_name = os.path.basename(out_path)
        root, ext = os.path.splitext(base_name)
        short_name = os.path.join(base_dir, f"{root}_short{ext}")
        with pd.ExcelWriter(short_name, engine="openpyxl") as writer:
            short_df.to_excel(writer, index=False, sheet_name="Relatório")
    except Exception as e:
        sys.stderr.write(f"ERRO: falha ao escrever arquivos Excel: {e}\n")
        sys.exit(4)

    print(f"Concluído. Issues analisadas: {len(issues)}, Worklogs exportados: {len(linhas_all)}")
    print(f"Arquivo gerado: {out_path}")
    print(f"Arquivo curto gerado: {short_name}")

if __name__ == "__main__":
    main()
