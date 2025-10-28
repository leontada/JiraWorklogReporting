from datetime import datetime, timezone
import io
import os
import pytest

import jira_worklog_extractor.core as core


def test_parse_config_date_invalid_returns_none():
    assert core.parse_config_date("") is None
    assert core.parse_config_date("invalid-date") is None


def test_month_bounds_first_and_next_month():
    dt = datetime(2025, 10, 15, 12, 0, tzinfo=core.DEFAULT_TZ)
    start, end = core.month_bounds(dt)
    assert start == datetime(2025, 10, 1, 0, 0, 0, tzinfo=core.DEFAULT_TZ)
    assert end == datetime(2025, 11, 1, 0, 0, 0, tzinfo=core.DEFAULT_TZ)


def test_numeric_only_no_digits_returns_empty():
    assert core.numeric_only("abc") == ""
    assert core.numeric_only("") == ""


def test_read_config_missing_section_exits(tmp_path):
    cfg = tmp_path / "no_jira.ini"
    cfg.write_text("[not_jira]\nfoo=bar\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        core.read_config(str(cfg))
    assert ei.value.code == 2
