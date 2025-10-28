import re
from datetime import datetime, timedelta, timezone

import pytest

import mJiraWorkLogExtractor as mod


def test_month_bounds_first_and_next_month():
    # Use a fixed date
    dt = datetime(2025, 10, 24, 15, 30, tzinfo=mod.DEFAULT_TZ)
    start, end = mod.month_bounds(dt)
    assert start == datetime(2025, 10, 1, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)
    assert end == datetime(2025, 11, 1, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)


@pytest.mark.parametrize(
    "s,expected",
    [
        ("2025-10-24", datetime(2025, 10, 24, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)),
        (" 2025-01-01 ", datetime(2025, 1, 1, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)),
        ("", None),
        ("invalid", None),
    ],
)
def test_parse_config_date(s, expected):
    assert mod.parse_config_date(s) == expected


def test_compute_bounds_defaults_end_today_when_missing():
    now = datetime(2025, 10, 24, 10, 0, 0, tzinfo=mod.DEFAULT_TZ)
    # no end_str -> should default to "today inclusive" (exclusive bound = tomorrow 00:00)
    start, end = mod.compute_bounds(now, start_str="", end_str="")
    # start defaults to first day of month
    assert start == datetime(2025, 10, 1, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)
    # end is tomorrow at 00:00 UTC
    assert end == datetime(2025, 10, 25, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)


def test_compute_bounds_with_explicit_dates_and_safety_rule():
    now = datetime(2025, 10, 24, 10, 0, 0, tzinfo=mod.DEFAULT_TZ)
    # Explicit end before start -> safety kicks in (end = start + 1 day)
    start, end = mod.compute_bounds(now, start_str="2025-10-10", end_str="2025-10-09")
    assert start == datetime(2025, 10, 10, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)
    assert end == datetime(2025, 10, 11, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)

    # Normal explicit range
    start, end = mod.compute_bounds(now, start_str="2025-10-10", end_str="2025-10-24")
    assert start == datetime(2025, 10, 10, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)
    # end exclusive = 2025-10-25 00:00
    assert end == datetime(2025, 10, 25, 0, 0, 0, tzinfo=mod.DEFAULT_TZ)


def test_default_out_name_pattern():
    name = mod.default_out_name()
    assert name.endswith(".xlsx")
    # mJiraWorkLogExtractor-YYYY-MM-DD-HHMM.xlsx
    m = re.match(r"^mJiraWorkLogExtractor-\d{4}-\d{2}-\d{2}-\d{4}\.xlsx$", name)
    assert m is not None


def test_jql_for_range_inclusive_bounds():
    start = datetime(2025, 10, 1, 0, 0, tzinfo=mod.DEFAULT_TZ)
    end = datetime(2025, 10, 25, 0, 0, tzinfo=mod.DEFAULT_TZ)  # exclusive
    jql = mod.jql_for_range(start, end)
    assert jql == 'worklogDate >= "2025-10-01" AND worklogDate <= "2025-10-24"'


def test_numeric_only_various_inputs():
    assert mod.numeric_only("SOW: 12345 ABC") == "12345"
    assert mod.numeric_only("no-digits") == ""
    assert mod.numeric_only("") == ""


def test__best_label_and__flatten_hierarchy_and_stringify_sow():
    # _best_label
    assert mod._best_label({"value": "Alpha"}) == "Alpha"
    assert mod._best_label({"name": "Beta"}) == "Beta"
    assert mod._best_label({"label": "Gamma"}) == "Gamma"
    assert mod._best_label({"title": "Delta"}) == "Delta"
    assert mod._best_label({"key": "Epsilon"}) == "Epsilon"
    assert mod._best_label({"id": 42}) == "42"
    assert mod._best_label({}) == ""

    # _flatten_hierarchy with child
    h = {"value": "Top", "child": {"value": "Mid", "child": {"value": "Leaf"}}}
    assert mod._flatten_hierarchy(h) == ["Top", "Mid", "Leaf"]

    # _flatten_hierarchy with children list
    h2 = {"value": "Top", "children": [{"value": "Mid"}]}
    assert mod._flatten_hierarchy(h2) == ["Top", "Mid"]

    # stringify_sow
    assert mod.stringify_sow(None) == ""
    assert mod.stringify_sow("ABC") == "ABC"
    assert mod.stringify_sow(["A1", "B2"]) == "A1 | B2"
    assert mod.stringify_sow({"value": "Top", "child": {"value": "Leaf"}}) == "Top:Leaf"


def test_adf_to_text_paragraphs_and_list():
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Item1"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Item2"}]}
                        ],
                    },
                ],
            },
        ],
    }
    txt = mod.adf_to_text(adf)
    # Expect "Hello" and list items prefixed with "- "
    assert "Hello" in txt
    assert "- Item1" in txt
    assert "- Item2" in txt


def test_vprint_only_when_verbose(capsys):
    mod.vprint(True, "A", 123)
    captured = capsys.readouterr()
    assert "A 123" in captured.out

    mod.vprint(False, "B", 456)
    captured = capsys.readouterr()
    # nothing new printed
    assert captured.out == ""
