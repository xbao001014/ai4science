"""Live PubMed fetch progress from SQLite (works while fetch runs in another terminal)."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from typing import Any

import config
from db.schema import get_conn, init_db


def _count_by_group(rows: list[Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for name in json.loads(row["source_queries"] or "[]"):
            counts[name] += 1
    return counts


def snapshot(since_seconds: int | None = None) -> dict[str, Any]:
    """Return current fetch progress from the database."""
    init_db()
    groups = config.get_enabled_groups()
    group_names = [g["name"] for g in groups]

    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        all_rows = conn.execute("SELECT source_queries FROM papers").fetchall()
        by_group = _count_by_group(all_rows)

        recent_total = 0
        recent_by_group: Counter[str] = Counter()
        if since_seconds is not None:
            recent_rows = conn.execute(
                "SELECT source_queries FROM papers "
                "WHERE created_at >= datetime('now', ?)",
                (f"-{since_seconds} seconds",),
            ).fetchall()
            recent_by_group = _count_by_group(recent_rows)
            recent_total = len(recent_rows)

    active_group = ""
    if recent_by_group:
        active_group = recent_by_group.most_common(1)[0][0]

    return {
        "total": total,
        "by_group": {name: by_group.get(name, 0) for name in group_names},
        "recent_total": recent_total,
        "recent_by_group": dict(recent_by_group),
        "active_group": active_group,
        "group_names": group_names,
        "year_range": f"{config.SEARCH_YEAR_START}-{config.SEARCH_YEAR_END}",
    }


def format_progress(
    data: dict[str, Any],
    *,
    prev_total: int | None = None,
    interval: int = 10,
) -> str:
    lines: list[str] = []
    ts = time.strftime("%H:%M:%S")
    total = data["total"]
    delta = total - prev_total if prev_total is not None else 0
    rate = f"{delta * 60 / interval:.0f}/min" if prev_total is not None and interval > 0 else "-"

    lines.append(f"=== PubMed Fetch Progress  {ts}  ({data['year_range']}) ===")
    if prev_total is not None:
        sign = "+" if delta >= 0 else ""
        lines.append(f"Total papers: {total}  ({sign}{delta} in {interval}s, ~{rate})")
    else:
        lines.append(f"Total papers: {total}")

    if data["recent_total"]:
        lines.append(
            f"Active group: {data['active_group'] or '-'}  "
            f"(+{data['recent_total']} in last {interval}s)"
        )
    else:
        lines.append("Active group: -  (no new papers in this interval)")

    lines.append("")
    lines.append(f"{'Query group':<36} {'in DB':>7}")
    lines.append("-" * 46)

    for name in data["group_names"]:
        count = data["by_group"].get(name, 0)
        marker = " <" if name == data["active_group"] else ""
        recent = data["recent_by_group"].get(name, 0)
        recent_s = f" +{recent}" if recent else ""
        lines.append(f"{name:<36} {count:>7}{recent_s}{marker}")

    other = total - sum(data["by_group"].values())
    if other > 0:
        lines.append(f"{'(multi-group / legacy)':<36} {other:>7}")

    done = sum(1 for n in data["group_names"] if data["by_group"].get(n, 0) > 0)
    lines.append("")
    lines.append(
        f"Groups with data: {done}/{len(data['group_names'])}  "
        f"(Ctrl+C to stop watch)"
    )
    return "\n".join(lines)


def watch_fetch_progress(*, interval: int = 10, once: bool = False, clear: bool = True) -> None:
    """Poll the database and print fetch progress."""
    prev_total: int | None = None
    try:
        while True:
            data = snapshot(since_seconds=interval)
            if clear and not once:
                os.system("cls" if os.name == "nt" else "clear")
            print(format_progress(data, prev_total=prev_total, interval=interval))
            sys.stdout.flush()
            prev_total = data["total"]
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[watch-fetch] Stopped.")
