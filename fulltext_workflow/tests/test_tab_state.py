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
    script = build_tab_sync_script(
        [
            "Debate Process",
            "Data Feasibility (Fangxin LIS)",
            "Research Proposal",
        ],
        "data-feasibility-fangxin-lis",
    )
    assert "data-feasibility-fangxin-lis" in script
    assert "Data Feasibility (Fangxin LIS)" in script
    assert "Research Proposal" in script


def test_build_tab_sync_script_syncs_before_widget_interaction():
    script = build_tab_sync_script(
        ["Debate Process", "Research Proposal"],
        "research-proposal",
    )
    assert "pointerdown" in script
