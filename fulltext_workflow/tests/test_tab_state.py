from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.tab_state import build_tab_sync_script, normalize_tab_label


def test_normalize_tab_label_slugifies_labels():
    assert normalize_tab_label("Debate Process") == "debate-process"
    assert normalize_tab_label("Data Feasibility (Fangxin LIS)") == "data-feasibility-fangxin-lis"


def test_build_tab_sync_script_embeds_requested_tab_and_labels():
    labels = ["辩论过程", "数据可行性（方信 LIS）", "研究提案"]
    slug_by_label = {
        "辩论过程": "debate-process",
        "数据可行性（方信 LIS）": "data-feasibility-fangxin-lis",
        "研究提案": "research-proposal",
    }
    script = build_tab_sync_script(
        labels,
        "data-feasibility-fangxin-lis",
        slug_by_label=slug_by_label,
    )
    assert "data-feasibility-fangxin-lis" in script
    assert "数据可行性（方信 LIS）" in script
    assert "研究提案" in script
    assert "slugByLabel" in script


def test_build_tab_sync_script_syncs_before_widget_interaction():
    script = build_tab_sync_script(
        ["辩论过程", "研究提案"],
        "research-proposal",
        slug_by_label={
            "辩论过程": "debate-process",
            "研究提案": "research-proposal",
        },
    )
    assert "pointerdown" in script
