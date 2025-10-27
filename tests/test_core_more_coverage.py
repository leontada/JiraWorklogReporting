from datetime import datetime

import jira_worklog_extractor.core as core


def test_compute_bounds_start_ge_end_adjusts_end():
    # When end <= start, compute_bounds should set end = start + 1 day
    now = datetime(2025, 10, 10, 12, 0, tzinfo=core.DEFAULT_TZ)
    start_str = "2025-10-05"
    end_str = "2025-10-04"  # end <= start triggers safety adjustment
    start, end = core.compute_bounds(now, start_str, end_str)
    assert start == datetime(2025, 10, 5, 0, 0, 0, tzinfo=core.DEFAULT_TZ)
    assert end == datetime(2025, 10, 6, 0, 0, 0, tzinfo=core.DEFAULT_TZ)


def test_adf_to_text_ordered_list_prefix():
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "One"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Two"}]}
                        ],
                    },
                ],
            }
        ],
    }
    txt = core.adf_to_text(adf)
    # Ensure both items are present; list items should be collected
    assert "One" in txt and "Two" in txt
