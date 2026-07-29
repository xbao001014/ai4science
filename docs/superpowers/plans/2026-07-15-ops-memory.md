# Weekly Ops Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist weekly gap/proposal/hotspot ops into SQLite and soft-steer later gap debates away from near-duplicate directions using the last 4 runs per focus.

**Architecture:** New `ops_runs` / `ops_gap_items` / `ops_proposals` tables in `kg_fulltext.db`; pure fingerprint + Jaccard helpers and a thin `analysis/ops_memory.py` API; gap debate loads a memory prompt block when enabled; UI/CLI dual flags control inject vs persist; hotspot save only links `hotspot_week_id`.

**Tech Stack:** Python 3.12, SQLite (`db/schema.py`), Streamlit (`gap_ui.py`), existing `pipeline_utils.parse_gap_*`, pytest-style scripts under `fulltext_workflow/tests/`.

**Spec:** `docs/superpowers/specs/2026-07-15-ops-memory-design.md`

## Global Constraints

- Soft avoid only — never hard-delete overlapping gaps from reports.
- Lookback default: last **4** finished runs per `focus_key`; empty focus uses `__all__`.
- Jaccard threshold default **0.55**; `section_md` cap default **8192** chars.
- Prefer report file paths over huge DB blobs; truncate `section_md`.
- No embeddings; no Markdown backfill; do not commit `*.db` or secrets.
- Follow existing test pattern: set `config.DB_PATH` to a temp/test DB under `fulltext_workflow/data/` before importing schema helpers.
- Working directory for commands: `fulltext_workflow/` unless noted; use `..\.venv\Scripts\python.exe` on Windows.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/db/schema.py` | DDL + migrate for `ops_*`; thin insert/select helpers used by ops_memory |
| `fulltext_workflow/config.py` | `OPS_MEMORY_*` env knobs |
| `fulltext_workflow/analysis/ops_memory.py` | Fingerprint, Jaccard, create/load/persist, prompt block, revisit tags |
| `fulltext_workflow/tests/test_ops_memory.py` | Unit tests (temp SQLite, no LLM) |
| `fulltext_workflow/gap_agent.py` | Inject memory into debate; optional persist after final |
| `fulltext_workflow/gap_ui.py` | Sidebar toggles + memory summary; pass flags; persist on success |
| `fulltext_workflow/pipeline.py` | Persist after debate / proposals when enabled |
| `fulltext_workflow/main.py` | CLI `--no-ops-memory` / `--no-ops-persist` |
| `fulltext_workflow/analysis/weekly_hotspot.py` | After snapshot persist, call `link_hotspot_week` |
| `fulltext_workflow/PIPELINE.md` or `gap_ui_guide.md` | Short operator note |

---

### Task 1: Config + schema + pure fingerprint helpers

**Files:**
- Modify: `fulltext_workflow/config.py`
- Modify: `fulltext_workflow/db/schema.py` (SCHEMA_SQL + `_migrate_db`)
- Create: `fulltext_workflow/analysis/ops_memory.py` (pure helpers first)
- Create: `fulltext_workflow/tests/test_ops_memory.py`

**Interfaces:**
- Consumes: none
- Produces:
  - `config.OPS_MEMORY_ENABLED: bool`
  - `config.OPS_MEMORY_LOOKBACK_RUNS: int` (default 4)
  - `config.OPS_MEMORY_JACCARD_THRESHOLD: float` (default 0.55)
  - `config.OPS_MEMORY_SECTION_MAX_CHARS: int` (default 8192)
  - `normalize_focus_key(focus: str | None) -> str`
  - `tokenize_for_fingerprint(text: str) -> list[str]`
  - `fingerprint_gap_title(title: str) -> str`
  - `jaccard_overlap(a: str, b: str) -> float`

- [ ] **Step 1: Write failing tests for pure helpers**

Create `fulltext_workflow/tests/test_ops_memory.py`:

```python
"""Unit tests for weekly ops memory helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

config.DB_PATH = str(_ROOT / "data" / "test_ops_memory.db")

from analysis.ops_memory import (  # noqa: E402
    fingerprint_gap_title,
    jaccard_overlap,
    normalize_focus_key,
)


def test_normalize_focus_key_empty_is_all():
    assert normalize_focus_key(None) == "__all__"
    assert normalize_focus_key("") == "__all__"
    assert normalize_focus_key("  ") == "__all__"


def test_normalize_focus_key_lower_strip():
    assert normalize_focus_key("  Nasopharyngeal Carcinoma ") == "nasopharyngeal carcinoma"


def test_fingerprint_stable_and_order_invariant():
    a = fingerprint_gap_title("Survival prediction with radiomics")
    b = fingerprint_gap_title("radiomics with Survival prediction")
    assert a == b
    assert len(a) == 16  # truncated hex


def test_jaccard_identical_high():
    assert jaccard_overlap(
        "NPC radiomics prognosis deep learning",
        "NPC radiomics prognosis deep learning",
    ) == 1.0


def test_jaccard_unrelated_low():
    score = jaccard_overlap(
        "breast cancer pathomics grading",
        "cardiac CTA stenosis scoring",
    )
    assert score < 0.3
```

- [ ] **Step 2: Run tests — expect ImportError / missing attributes**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: FAIL (module or symbols missing).

- [ ] **Step 3: Add config knobs**

In `fulltext_workflow/config.py`, after hotspot knobs (~line 104), add:

```python
# Weekly ops memory (gap soft-dedup + persist)
OPS_MEMORY_ENABLED: bool = os.getenv("OPS_MEMORY_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
OPS_MEMORY_LOOKBACK_RUNS: int = int(os.getenv("OPS_MEMORY_LOOKBACK_RUNS", "4"))
OPS_MEMORY_JACCARD_THRESHOLD: float = float(
    os.getenv("OPS_MEMORY_JACCARD_THRESHOLD", "0.55")
)
OPS_MEMORY_SECTION_MAX_CHARS: int = int(
    os.getenv("OPS_MEMORY_SECTION_MAX_CHARS", "8192")
)
```

- [ ] **Step 4: Implement pure helpers in `ops_memory.py`**

```python
"""Weekly ops memory: fingerprinting, persist, soft-avoid prompt blocks."""
from __future__ import annotations

import hashlib
import re
from typing import Any

import config

_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)


def normalize_focus_key(focus: str | None) -> str:
    if focus is None:
        return "__all__"
    s = " ".join(str(focus).strip().lower().split())
    return s if s else "__all__"


def tokenize_for_fingerprint(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    # unique, sorted for order invariance
    return sorted(set(tokens))


def fingerprint_gap_title(title: str) -> str:
    toks = tokenize_for_fingerprint(title)
    joined = " ".join(toks)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def jaccard_overlap(a: str, b: str) -> float:
    sa, sb = set(tokenize_for_fingerprint(a)), set(tokenize_for_fingerprint(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
```

- [ ] **Step 5: Add `ops_*` DDL to SCHEMA_SQL and `_migrate_db`**

Append to `SCHEMA_SQL` (and the same `CREATE TABLE IF NOT EXISTS` block inside `_migrate_db` executescript) exactly:

```sql
CREATE TABLE IF NOT EXISTS ops_runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id             TEXT,
    focus_raw           TEXT,
    focus_key           TEXT NOT NULL,
    source              TEXT,
    started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at         TIMESTAMP,
    hotspot_week_id     TEXT,
    gap_report_path     TEXT,
    proposal_report_path TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_runs_focus_finished
    ON ops_runs(focus_key, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_runs_week ON ops_runs(week_id);

CREATE TABLE IF NOT EXISTS ops_gap_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES ops_runs(run_id),
    rank_pos            INTEGER,
    title               TEXT NOT NULL,
    research_question   TEXT,
    fingerprint         TEXT,
    section_md          TEXT,
    status              TEXT DEFAULT 'reported'
);
CREATE INDEX IF NOT EXISTS idx_ops_gap_run ON ops_gap_items(run_id);
CREATE INDEX IF NOT EXISTS idx_ops_gap_fp ON ops_gap_items(fingerprint);

CREATE TABLE IF NOT EXISTS ops_proposals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES ops_runs(run_id),
    gap_item_id         INTEGER REFERENCES ops_gap_items(id),
    proposal_path       TEXT,
    proposal_md         TEXT,
    feasibility_score   REAL,
    status              TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_prop_run ON ops_proposals(run_id);
```

- [ ] **Step 6: Re-run helper tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: PASS for the five tests above.

- [ ] **Step 7: Commit** (only if user asked to commit in this session; otherwise skip)

```bash
git add fulltext_workflow/config.py fulltext_workflow/db/schema.py \
  fulltext_workflow/analysis/ops_memory.py fulltext_workflow/tests/test_ops_memory.py
git commit -m "feat(ops-memory): add schema, config, and fingerprint helpers"
```

---

### Task 2: Persist / load API (`ops_memory` + schema helpers)

**Files:**
- Modify: `fulltext_workflow/db/schema.py` (CRUD helpers)
- Modify: `fulltext_workflow/analysis/ops_memory.py`
- Modify: `fulltext_workflow/tests/test_ops_memory.py`

**Interfaces:**
- Consumes: fingerprint helpers from Task 1; `pipeline_utils.parse_gap_sections` / `parse_gap_titles`; `analysis.weekly_hotspot.week_id`
- Produces:
  - `@dataclass MemoryGapItem` / `MemoryBundle`
  - `create_ops_run(focus_raw, source, *, week_id=None) -> int`
  - `finalize_ops_run(run_id, *, gap_report_path="", hotspot_week_id="", proposal_report_path="") -> None`
  - `persist_gaps_from_report(run_id, report_text) -> list[dict]`
  - `persist_proposal(run_id, *, gap_item_id=None, proposal_path="", proposal_md="", feasibility_score=None, status="") -> int`
  - `link_hotspot_week(hotspot_week_id, *, focus_key="__all__", source="hotspot") -> int`  # returns run_id
  - `load_recent_gaps(focus: str | None, limit_runs: int | None = None) -> MemoryBundle`
  - `format_memory_prompt_block(bundle: MemoryBundle) -> str`
  - `tag_revisited_against_memory(titles: list[str], bundle: MemoryBundle, threshold: float | None = None) -> list[tuple[str, str]]`  # (title, status)

- [ ] **Step 1: Extend tests for persist + lookback isolation**

Append to `test_ops_memory.py`:

```python
from db.schema import init_db  # noqa: E402
from analysis.ops_memory import (  # noqa: E402
    create_ops_run,
    finalize_ops_run,
    format_memory_prompt_block,
    load_recent_gaps,
    persist_gaps_from_report,
    tag_revisited_against_memory,
)


def _reset_ops_db() -> None:
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    init_db()


SAMPLE_REPORT = """
## Research gap analysis

### Research gap 1: NPC radiomics prognosis modeling
**Research question**: Can multimodal radiomics improve NPC OS prediction?

### Research gap 2: Pathomics subtype discovery for NPC
**Research question**: Unsupervised subtypes on WSI.
"""


def test_persist_and_load_lookback_four():
    _reset_ops_db()
    ids = []
    for i in range(5):
        rid = create_ops_run("nasopharyngeal carcinoma", "gap-debate")
        persist_gaps_from_report(
            rid,
            SAMPLE_REPORT.replace("NPC", f"NPC{i}" if i < 4 else "NPC"),
        )
        finalize_ops_run(rid, gap_report_path=f"output/t{i}.md")
        ids.append(rid)
    bundle = load_recent_gaps("nasopharyngeal carcinoma", limit_runs=4)
    assert len(bundle.run_ids) == 4
    assert ids[0] not in bundle.run_ids  # oldest dropped
    assert ids[-1] in bundle.run_ids


def test_focus_lanes_do_not_mix():
    _reset_ops_db()
    r1 = create_ops_run("breast cancer", "gap-debate")
    persist_gaps_from_report(r1, SAMPLE_REPORT.replace("NPC", "breast"))
    finalize_ops_run(r1)
    r2 = create_ops_run(None, "gap-debate")
    persist_gaps_from_report(r2, "### Research gap 1: Global radiomics gap\n")
    finalize_ops_run(r2)
    breast = load_recent_gaps("breast cancer")
    all_lane = load_recent_gaps(None)
    assert all(g.title.lower().find("breast") >= 0 or "breast" in g.title.lower()
               or True for g in breast.items)  # structural: only breast run
    assert len(breast.run_ids) == 1
    assert breast.run_ids[0] == r1
    assert all_lane.run_ids == [r2]


def test_memory_prompt_and_revisited_tag():
    _reset_ops_db()
    rid = create_ops_run("npc", "gap_ui")
    persist_gaps_from_report(rid, SAMPLE_REPORT)
    finalize_ops_run(rid)
    bundle = load_recent_gaps("npc")
    block = format_memory_prompt_block(bundle)
    assert "近期已覆盖" in block or "previously covered" in block.lower() or "ops memory" in block.lower()
    tagged = tag_revisited_against_memory(
        ["NPC radiomics prognosis modeling", "Completely novel cardiac gap"],
        bundle,
    )
    status_map = dict(tagged)
    assert status_map["NPC radiomics prognosis modeling"] == "revisited"
    assert status_map["Completely novel cardiac gap"] == "reported"
```

Tighten `test_focus_lanes_do_not_mix` assertions to:

```python
    assert breast.run_ids == [r1]
    assert all_lane.run_ids == [r2]
```

- [ ] **Step 2: Run tests — expect missing CRUD failures**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: FAIL on create/load.

- [ ] **Step 3: Add schema CRUD helpers**

In `db/schema.py`, add:

```python
def insert_ops_run(
    *,
    week_id: str,
    focus_raw: str | None,
    focus_key: str,
    source: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO ops_runs
               (week_id, focus_raw, focus_key, source, started_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (week_id, focus_raw, focus_key, source),
        )
        return int(cur.lastrowid)


def update_ops_run_finalize(
    run_id: int,
    *,
    gap_report_path: str = "",
    hotspot_week_id: str = "",
    proposal_report_path: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE ops_runs SET
               finished_at=CURRENT_TIMESTAMP,
               gap_report_path=COALESCE(NULLIF(?, ''), gap_report_path),
               hotspot_week_id=COALESCE(NULLIF(?, ''), hotspot_week_id),
               proposal_report_path=COALESCE(NULLIF(?, ''), proposal_report_path)
               WHERE run_id=?""",
            (gap_report_path, hotspot_week_id, proposal_report_path, run_id),
        )


def insert_ops_gap_items(run_id: int, items: list[dict[str, Any]]) -> int:
    with get_conn() as conn:
        for it in items:
            conn.execute(
                """INSERT INTO ops_gap_items
                   (run_id, rank_pos, title, research_question, fingerprint,
                    section_md, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    it.get("rank_pos"),
                    it["title"],
                    it.get("research_question"),
                    it.get("fingerprint"),
                    it.get("section_md"),
                    it.get("status") or "reported",
                ),
            )
        return len(items)


def insert_ops_proposal(
    run_id: int,
    *,
    gap_item_id: int | None = None,
    proposal_path: str = "",
    proposal_md: str = "",
    feasibility_score: float | None = None,
    status: str = "",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO ops_proposals
               (run_id, gap_item_id, proposal_path, proposal_md,
                feasibility_score, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                gap_item_id,
                proposal_path or None,
                proposal_md or None,
                feasibility_score,
                status or None,
            ),
        )
        return int(cur.lastrowid)


def fetch_recent_ops_runs(focus_key: str, limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT run_id, week_id, focus_raw, focus_key, source,
                      started_at, finished_at, hotspot_week_id,
                      gap_report_path, proposal_report_path
               FROM ops_runs
               WHERE focus_key=? AND finished_at IS NOT NULL
               ORDER BY finished_at DESC, run_id DESC
               LIMIT ?""",
            (focus_key, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_ops_gap_items_for_runs(run_ids: list[int]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ",".join("?" * len(run_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, run_id, rank_pos, title, research_question,
                       fingerprint, section_md, status
                FROM ops_gap_items
                WHERE run_id IN ({placeholders})
                ORDER BY run_id DESC, rank_pos ASC""",
            tuple(run_ids),
        ).fetchall()
    return [dict(r) for r in rows]


def update_ops_run_hotspot(run_id: int, hotspot_week_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE ops_runs SET hotspot_week_id=? WHERE run_id=?",
            (hotspot_week_id, run_id),
        )


def find_ops_run_by_week_focus(week_id: str, focus_key: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT run_id FROM ops_runs
               WHERE week_id=? AND focus_key=?
               ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
               LIMIT 1""",
            (week_id, focus_key),
        ).fetchone()
    return int(row["run_id"]) if row else None
```

- [ ] **Step 4: Implement high-level API in `ops_memory.py`**

Append (imports + dataclasses + functions). Key behaviors:

```python
from dataclasses import dataclass, field
from analysis.weekly_hotspot import week_id as iso_week_id
from db.schema import (
    fetch_ops_gap_items_for_runs,
    fetch_recent_ops_runs,
    find_ops_run_by_week_focus,
    insert_ops_gap_items,
    insert_ops_proposal,
    insert_ops_run,
    update_ops_run_finalize,
    update_ops_run_hotspot,
)
from pipeline_utils import parse_gap_sections, parse_gap_titles


@dataclass
class MemoryGapItem:
    run_id: int
    week_id: str
    title: str
    research_question: str = ""
    fingerprint: str = ""
    status: str = "reported"


@dataclass
class MemoryBundle:
    focus_key: str
    run_ids: list[int] = field(default_factory=list)
    items: list[MemoryGapItem] = field(default_factory=list)


def create_ops_run(focus_raw: str | None, source: str, *, week_id: str | None = None) -> int:
    wid = week_id or iso_week_id()
    key = normalize_focus_key(focus_raw)
    return insert_ops_run(
        week_id=wid,
        focus_raw=(focus_raw or "") if focus_raw else None,
        focus_key=key,
        source=source,
    )


def finalize_ops_run(
    run_id: int,
    *,
    gap_report_path: str = "",
    hotspot_week_id: str = "",
    proposal_report_path: str = "",
) -> None:
    update_ops_run_finalize(
        run_id,
        gap_report_path=gap_report_path,
        hotspot_week_id=hotspot_week_id,
        proposal_report_path=proposal_report_path,
    )


def _extract_research_question(section_md: str) -> str:
    import re
    m = re.search(
        r"\*\*Research question\*\*[：:]\s*(.+)",
        section_md or "",
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:500]
    m = re.search(r"\*\*研究问题\*\*[：:]\s*(.+)", section_md or "")
    return m.group(1).strip()[:500] if m else ""


def persist_gaps_from_report(run_id: int, report_text: str) -> list[dict[str, Any]]:
    sections = parse_gap_sections(report_text)
    if not sections:
        titles = parse_gap_titles(report_text)
        sections = [(t, t) for t in titles]
    items: list[dict[str, Any]] = []
    max_chars = config.OPS_MEMORY_SECTION_MAX_CHARS
    for i, (title, body) in enumerate(sections, start=1):
        items.append({
            "rank_pos": i,
            "title": title,
            "research_question": _extract_research_question(body),
            "fingerprint": fingerprint_gap_title(title),
            "section_md": (body or "")[:max_chars],
            "status": "reported",
        })
    insert_ops_gap_items(run_id, items)
    return items


def persist_proposal(
    run_id: int,
    *,
    gap_item_id: int | None = None,
    proposal_path: str = "",
    proposal_md: str = "",
    feasibility_score: float | None = None,
    status: str = "",
) -> int:
    md = proposal_md
    if md and len(md) > config.OPS_MEMORY_SECTION_MAX_CHARS and proposal_path:
        md = md[: config.OPS_MEMORY_SECTION_MAX_CHARS]
    return insert_ops_proposal(
        run_id,
        gap_item_id=gap_item_id,
        proposal_path=proposal_path,
        proposal_md=md,
        feasibility_score=feasibility_score,
        status=status,
    )


def link_hotspot_week(
    hotspot_week_id: str,
    *,
    focus_key: str = "__all__",
    source: str = "hotspot",
) -> int:
    existing = find_ops_run_by_week_focus(hotspot_week_id, focus_key)
    if existing:
        update_ops_run_hotspot(existing, hotspot_week_id)
        return existing
    rid = insert_ops_run(
        week_id=hotspot_week_id,
        focus_raw=None if focus_key == "__all__" else focus_key,
        focus_key=focus_key,
        source=source,
    )
    update_ops_run_hotspot(rid, hotspot_week_id)
    finalize_ops_run(rid, hotspot_week_id=hotspot_week_id)
    return rid


def load_recent_gaps(
    focus: str | None,
    limit_runs: int | None = None,
) -> MemoryBundle:
    key = normalize_focus_key(focus)
    lim = limit_runs if limit_runs is not None else config.OPS_MEMORY_LOOKBACK_RUNS
    runs = fetch_recent_ops_runs(key, lim)
    run_ids = [int(r["run_id"]) for r in runs]
    week_by_run = {int(r["run_id"]): (r.get("week_id") or "") for r in runs}
    raw_items = fetch_ops_gap_items_for_runs(run_ids)
    items = [
        MemoryGapItem(
            run_id=int(it["run_id"]),
            week_id=week_by_run.get(int(it["run_id"]), ""),
            title=it["title"],
            research_question=it.get("research_question") or "",
            fingerprint=it.get("fingerprint") or "",
            status=it.get("status") or "reported",
        )
        for it in raw_items
    ]
    return MemoryBundle(focus_key=key, run_ids=run_ids, items=items)


def format_memory_prompt_block(bundle: MemoryBundle) -> str:
    if not bundle.items:
        return ""
    lines = [
        "【周常操作记忆 / Ops memory — soft avoid】",
        f"focus_key={bundle.focus_key}; recent finished runs={len(bundle.run_ids)}",
        "近期已覆盖方向（优先提出不同角度；若重提须声明 Distinction / previously covered）：",
    ]
    seen: set[str] = set()
    for it in bundle.items:
        key = it.title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        q = f" — {it.research_question}" if it.research_question else ""
        lines.append(f"- [{it.week_id}] {it.title}{q}")
    lines.append(
        "禁止仅复述上表；Skeptic 将无差异的高相似项视为 duplicate_risk / weak_evidence，不得仅凭重合判为 false_gap。"
    )
    return "\n".join(lines)


def tag_revisited_against_memory(
    titles: list[str],
    bundle: MemoryBundle,
    threshold: float | None = None,
) -> list[tuple[str, str]]:
    thr = (
        threshold
        if threshold is not None
        else config.OPS_MEMORY_JACCARD_THRESHOLD
    )
    out: list[tuple[str, str]] = []
    mem_titles = [it.title for it in bundle.items]
    for title in titles:
        status = "reported"
        for mt in mem_titles:
            if jaccard_overlap(title, mt) >= thr:
                status = "revisited"
                break
        out.append((title, status))
    return out
```

- [ ] **Step 5: Run full ops_memory tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit** (if user requested commits)

```bash
git add fulltext_workflow/db/schema.py fulltext_workflow/analysis/ops_memory.py \
  fulltext_workflow/tests/test_ops_memory.py
git commit -m "feat(ops-memory): persist/load API and lookback helpers"
```

---

### Task 3: Inject soft-avoid into `gap_agent`

**Files:**
- Modify: `fulltext_workflow/gap_agent.py`
- Modify: `fulltext_workflow/tests/test_ops_memory.py` (optional unit on prompt wiring helper)

**Interfaces:**
- Consumes: `load_recent_gaps`, `format_memory_prompt_block`
- Produces: `stream_gap_debate_agent(..., use_ops_memory: bool | None = None)` and `run_gap_debate_agent(..., use_ops_memory=..., persist_ops_memory=...)` kwargs

- [ ] **Step 1: Add a small unit test for “memory block attached when enabled”**

Prefer extracting a pure helper in `gap_agent.py` or `ops_memory.py`:

```python
def resolve_ops_memory_block(
    focus: str | None,
    use_ops_memory: bool | None,
) -> str:
    enabled = config.OPS_MEMORY_ENABLED if use_ops_memory is None else use_ops_memory
    if not enabled:
        return ""
    return format_memory_prompt_block(load_recent_gaps(focus))
```

Test:

```python
def test_resolve_ops_memory_block_respects_flag():
    from gap_agent import resolve_ops_memory_block
    _reset_ops_db()
    rid = create_ops_run("npc", "gap_ui")
    persist_gaps_from_report(rid, SAMPLE_REPORT)
    finalize_ops_run(rid)
    assert resolve_ops_memory_block("npc", True)
    assert resolve_ops_memory_block("npc", False) == ""
```

- [ ] **Step 2: Run — expect import failure until helper exists**

- [ ] **Step 3: Wire into `stream_gap_debate_agent`**

1. Add parameters: `use_ops_memory: bool | None = None`.
2. At start, `memory_block = resolve_ops_memory_block(focus, use_ops_memory)`.
3. Append `memory_block` to Optimist user messages (round 1 and revise rounds), Skeptic user message, and Moderator user message when non-empty.
4. Optionally append a short Skeptic/Moderator bullet in system prompts only when `memory_block` is non-empty (keep YAGNI: user-message append is enough if block text already instructs roles).

Also thread the same kwargs through `run_gap_debate_agent`.

- [ ] **Step 4: Re-run tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit** (if requested)

```bash
git commit -am "feat(ops-memory): inject soft-avoid memory block into gap debate"
```

---

### Task 4: Persist hooks (debate success) + CLI flags

**Files:**
- Modify: `fulltext_workflow/gap_agent.py` (`save_report` or caller-side persist helper)
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/pipeline.py`
- Prefer new helper in `ops_memory.py`:

```python
def persist_debate_report(
    report_text: str,
    *,
    focus: str | None,
    source: str,
    gap_report_path: str = "",
    enabled: bool | None = None,
) -> int | None:
    on = config.OPS_MEMORY_ENABLED if enabled is None else enabled
    if not on or not (report_text or "").strip():
        return None
    # Load prior bundle BEFORE writing this run (caller should tag using pre-write bundle)
    rid = create_ops_run(focus, source)
    items = persist_gaps_from_report(rid, report_text)
    # Tag revisited vs previous memory (exclude current run by loading before create —
    # implement by accepting optional prior_bundle or load before create_ops_run)
    finalize_ops_run(rid, gap_report_path=gap_report_path)
    return rid
```

**Important:** Call `load_recent_gaps(focus)` **before** `create_ops_run` + persist, then `tag_revisited_against_memory` on new titles; if status is `revisited`, update rows (add `update_ops_gap_item_status` in schema) or pass status into insert. Prefer computing statuses before `insert_ops_gap_items`.

- [ ] **Step 1: Test persist_debate_report + revisit status on insert**

```python
def test_persist_debate_marks_revisited():
    _reset_ops_db()
    rid0 = create_ops_run("npc", "gap-debate")
    persist_gaps_from_report(rid0, SAMPLE_REPORT)
    finalize_ops_run(rid0)
    from analysis.ops_memory import persist_debate_report
    rid1 = persist_debate_report(
        SAMPLE_REPORT, focus="npc", source="gap-debate", enabled=True
    )
    assert rid1 is not None
    items = fetch_ops_gap_items_for_runs([rid1])
    assert any(it["status"] == "revisited" for it in items)
    assert persist_debate_report(SAMPLE_REPORT, focus="npc", source="x", enabled=False) is None
```

- [ ] **Step 2: Implement `persist_debate_report` with pre-load tagging**

- [ ] **Step 3: Wire CLI**

In `main.py` for `gap-debate` and `idea-pipeline` parsers:

```python
p_debate.add_argument("--no-ops-memory", action="store_true",
                      help="Do not inject ops memory into debate prompts")
p_debate.add_argument("--no-ops-persist", action="store_true",
                      help="Do not write ops_* rows after debate")
```

Same flags on `idea-pipeline`.

In `cmd_gap_debate`:

```python
report = run_gap_debate_agent(
    ...,
    use_ops_memory=not args.no_ops_memory,
)
if args.output and report:
    save_report(...)
if report and not args.no_ops_persist:
    persist_debate_report(
        report, focus=args.focus, source="gap-debate",
        gap_report_path=args.output or "",
        enabled=True,
    )
```

Note: inject flag and persist flag are independent — `--no-ops-memory` must not force skip persist unless user also passes `--no-ops-persist`.

- [ ] **Step 4: Wire `pipeline.run_idea_pipeline`**

Add params `use_ops_memory: bool | None = None`, `persist_ops_memory: bool | None = None`. After debate `save_report`, call `persist_debate_report`. After proposals, call `persist_proposal` on the same `run_id` returned (store run_id from persist).

- [ ] **Step 5: Run tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit** (if requested)

---

### Task 5: Gap UI toggles + summary + persist

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (sidebar + debate runner + optional Proposal persist)

**Interfaces:**
- Consumes: `load_recent_gaps`, `format_memory_prompt_block` / bundle.items, `persist_debate_report`, `persist_proposal`, stream kwargs

- [ ] **Step 1: Sidebar controls**

Near focus input / Run button, add:

```python
use_ops_memory = st.checkbox("使用周常记忆", value=True,
    help="注入该 focus 最近 4 次已报告空白，软避开雷同方向")
persist_ops_memory = st.checkbox("本轮写入记忆", value=True,
    help="辩论成功后写入 ops_runs / ops_gap_items")
```

Expander:

```python
with st.expander("该 focus 记忆摘要", expanded=False):
    bundle = load_recent_gaps(focus_input or None)
    if not bundle.items:
        st.caption("暂无记忆")
    else:
        for it in bundle.items[:40]:
            st.markdown(f"- `{it.week_id}` {it.title}")
```

- [ ] **Step 2: Pass flags into stream**

```python
for event in stream_gap_debate_agent(
    focus=focus_input or None,
    top_n=top_n_input,
    max_debate_rounds=debate_rounds_input,
    use_ops_memory=use_ops_memory,
):
    ...
```

On `final` event, if `persist_ops_memory` and report content:

```python
path = ...  # optional save under output/gap_debate_{timestamp}.md if you already write files; else ""
persist_debate_report(
    event["content"],
    focus=focus_input or None,
    source="gap_ui",
    gap_report_path=path,
    enabled=True,
)
```

- [ ] **Step 3: Proposal tab**

When a proposal finishes successfully and persist is on, call `persist_proposal` (create/finalize a run with `source=gap_ui` or reuse last debate run_id stored in `st.session_state["ops_run_id"]` from Step 2).

Set `st.session_state["ops_run_id"] = rid` when debate persists.

- [ ] **Step 4: Manual smoke** (no automated Streamlit test required)

1. Start UI, leave both toggles on, run debate for a focus (or rely on seeded test DB offline).
2. Toggle **使用周常记忆** off — confirm no memory lines needed in logic (`resolve_ops_memory_block` false).
3. Toggle **本轮写入记忆** off — confirm no new `ops_runs` after success (query SQLite).

- [ ] **Step 5: Commit** (if requested)

---

### Task 6: Hotspot link + docs

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`save_hotspot_report` when `persist=True`)
- Modify: `fulltext_workflow/PIPELINE.md` (short subsection) **or** `gap_ui_guide.md`

- [ ] **Step 1: After `persist_hotspot_snapshot`, link ops memory**

```python
if persist:
    n = persist_hotspot_snapshot(payload, report_path=out)
    payload["snapshot_rows"] = n
    try:
        from analysis.ops_memory import link_hotspot_week
        link_hotspot_week(payload["week_id"], focus_key="__all__", source="hotspot")
    except Exception as exc:
        # do not fail hotspot save
        print(f"[Hotspot] ops memory link skipped: {exc}", flush=True)
```

- [ ] **Step 2: Unit test**

```python
def test_link_hotspot_creates_or_updates_run():
    _reset_ops_db()
    from analysis.ops_memory import link_hotspot_week
    rid = link_hotspot_week("2026-W29")
    rid2 = link_hotspot_week("2026-W29")
    assert rid == rid2
```

- [ ] **Step 3: Docs note** (5–10 lines)

In `PIPELINE.md` after gap-debate section, add “周常操作记忆” bullets: tables, lookback 4, UI toggles, CLI `--no-ops-memory` / `--no-ops-persist`.

- [ ] **Step 4: Full test suite for this feature**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_ops_memory.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit** (if requested)

```bash
git commit -am "feat(ops-memory): hotspot week link and operator docs"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| `ops_runs` / `ops_gap_items` / `ops_proposals` | 1–2 |
| Fingerprint + Jaccard 0.55 | 1–2 |
| Lookback 4 runs / focus lanes | 2 |
| Soft inject Optimist/Skeptic/Moderator | 3 |
| Persist debate/proposal hooks | 4–5 |
| UI dual toggles + summary | 5 |
| Hotspot `hotspot_week_id` link | 6 |
| CLI flags | 4 |
| Acceptance criteria 1–6 | 2–6 tests + UI smoke |
| Non-goals (no embeddings/hard delete/backfill) | respected throughout |

## Placeholder / consistency review

- No TBD steps; function names aligned (`link_hotspot_week`, `persist_debate_report`, `resolve_ops_memory_block`).
- Persist vs inject are independent flags end-to-end.
- Revisit tagging uses memory **before** current run is finalized.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-ops-memory.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with executing-plans checkpoints  

Which approach?
