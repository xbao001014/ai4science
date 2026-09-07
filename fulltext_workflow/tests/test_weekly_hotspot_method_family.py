from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.weekly_hotspot import (  # noqa: E402
    annotate_method_family_rows,
    group_method_family_rows,
)


def test_method_family_annotation_and_weekly_grouping():
    rows = [
        {"name": "ResNet", "recent_cnt": 3, "prior_cnt": 1, "emerging_score": 8.0},
        {"name": "U-Net", "recent_cnt": 2, "prior_cnt": 1, "emerging_score": 6.0},
        {"name": "opaque", "recent_cnt": 1, "prior_cnt": 0, "emerging_score": 2.0},
    ]
    annotate_method_family_rows(
        rows,
        name_key="name",
        family_by_name={"ResNet": "cnn", "U-Net": "cnn"},
        family_labels={"cnn": "卷积神经网络"},
    )
    grouped = group_method_family_rows(rows, {"cnn": "卷积神经网络"})
    assert grouped[0] == {
        "family_id": "cnn",
        "family_name_zh": "卷积神经网络",
        "method_count": 2,
        "methods": "ResNet；U-Net",
        "recent_cnt": 5,
        "prior_cnt": 2,
        "emerging_score": 8.0,
    }
    assert grouped[1]["family_id"] == "unknown"
    assert grouped[1]["family_name_zh"] == "未归类"
