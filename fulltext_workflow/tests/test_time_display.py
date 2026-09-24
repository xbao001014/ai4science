import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.time_display import format_beijing_time


def test_sqlite_utc_timestamp_displays_as_beijing_time() -> None:
    assert format_beijing_time("2026-09-23 18:30:00") == "2026-09-24 02:30:00"
    assert format_beijing_time("2026-09-23T18:30:00+00:00") == "2026-09-24 02:30:00"


def test_missing_timestamp_has_placeholder() -> None:
    assert format_beijing_time(None) == "—"
