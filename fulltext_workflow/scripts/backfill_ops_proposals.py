"""One-off backfill for ops_proposals rows missing linked fields."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from analysis.ops_memory import resolve_gap_item_id
from db.schema import get_conn


def main() -> None:
    with get_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, run_id, proposal_md, gap_item_id, proposal_path, status "
                "FROM ops_proposals"
            ).fetchall()
        ]
        for r in rows:
            updates: dict = {}
            if not r.get("gap_item_id") and r.get("proposal_md"):
                title = None
                for line in (r["proposal_md"] or "").splitlines()[:5]:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                if title:
                    gid = resolve_gap_item_id(r["run_id"], title)
                    if gid:
                        updates["gap_item_id"] = gid
                        print(f"linked gap_item_id={gid} title={title[:60]!r}")
            if not r.get("status"):
                updates["status"] = "generated"
            path = r.get("proposal_path")
            if not path and r.get("proposal_md"):
                os.makedirs(config.OUTPUT_DIR, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(
                    config.OUTPUT_DIR,
                    f"ops_proposal_{r['run_id']}_backfill_{stamp}.md",
                )
                with open(path, "w", encoding="utf-8") as f:
                    f.write(r["proposal_md"])
                updates["proposal_path"] = path
                md = r["proposal_md"]
                if len(md) > config.OPS_MEMORY_SECTION_MAX_CHARS:
                    updates["proposal_md"] = md[: config.OPS_MEMORY_SECTION_MAX_CHARS]
            if updates:
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE ops_proposals SET {sets} WHERE id=?",
                    (*updates.values(), r["id"]),
                )
                # Same connection — avoid nested get_conn() lock
                if updates.get("proposal_path"):
                    conn.execute(
                        """UPDATE ops_runs SET
                           proposal_report_path=COALESCE(NULLIF(?, ''), proposal_report_path)
                           WHERE run_id=?""",
                        (updates["proposal_path"], r["run_id"]),
                    )
                print("updated proposal", r["id"], list(updates.keys()))

        for r in conn.execute(
            "SELECT id, run_id, gap_item_id, length(proposal_md) AS md_len, "
            "status, proposal_path FROM ops_proposals"
        ):
            print(dict(r))


if __name__ == "__main__":
    main()
