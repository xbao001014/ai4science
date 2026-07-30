# Study-Type Downstream Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dual-channel combo gaps (`applied` + `covered` via `COVERS_DISEASE`) and secondary ranking by `SURVEYS_METHOD` paper counts on combo / priority / transferable surfaces, with UI columns only.

**Architecture:** Add `analysis/study_type_signals.py` for batched survey/cover counters and covered-pair construction. Wire into `tool_method_disease_combo_gap`, `tool_literature_impact_priority_matrix`, and `compute_emerging_gap_opportunities`. Keep Round 1 binding enrichment and primary scores unchanged; survey is a secondary sort key only. Method heat stays `APPLIES_METHOD`-only.

**Tech Stack:** Python 3, pytest, SQLite, Streamlit column lists

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-study-type-downstream-design.md`
- Do not add survey counts into `opportunity_score` / `gap_priority_score` / binding bumps
- Do not change Task-bridge admission rules
- Do not mix `COVERS_DISEASE` into applied-channel Top-N disease heat
- Method heat remains `APPLIES_METHOD` only
- No new UI tabs
- Truncation: applied first up to 40, then fill with covered to total ≤ 40
- Follow TDD: failing test → implement → pass
- Do **not** `git commit` unless the user explicitly asks

## File map

| Path | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/study_type_signals.py` | Create: counters + annotate + covered builder |
| `fulltext_workflow/analysis/gap_tools.py` | Dual-channel combo; matrix secondary sort |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Transferable annotate + secondary sort |
| `fulltext_workflow/gap_ui.py` | `opp_cols` (+ curated combo cols if hard-coded) |
| `fulltext_workflow/gap_agent.py` | Prompt bullet |
| `fulltext_workflow/tests/test_study_type_downstream.py` | Create: dual channel + sort tests |

---

### Task 1: `study_type_signals` helper

**Files:**
- Create: `fulltext_workflow/analysis/study_type_signals.py`
- Create: `fulltext_workflow/tests/test_study_type_downstream.py`

**Interfaces:**
- Consumes: `db.schema.get_conn`, active `relations` + `entities`
- Produces:
  - `count_surveys_by_method() -> dict[str, int]`
  - `count_covers_by_disease() -> dict[str, int]`
  - `annotate_study_type_rows(rows, method_key="method", disease_key="disease") -> list[dict]`  
    Adds `surveys_method_paper_cnt`, `covers_disease_paper_cnt` (default 0)
  - `build_covered_gap_rows(method_names: list[str], cover_disease_names: list[str], applied_cooccur: dict[tuple[str,str], int], applied_pair_set: set[tuple[str,str]]) -> list[dict]`  
    Returns rows with `gap_kind=covered`, `gap=unexplored`, `paper_cnt=0`, cover/survey counts filled via annotate

- [ ] **Step 1: Write failing unit tests**

Create `fulltext_workflow/tests/test_study_type_downstream.py`:

```python
"""Study-type downstream: covered channel + survey secondary sort helpers."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.study_type_signals import (  # noqa: E402
    annotate_study_type_rows,
    build_covered_gap_rows,
    count_covers_by_disease,
    count_surveys_by_method,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _edge(pmid: str, paper_id: int, relation: str, name: str, etype: str) -> None:
    eid = upsert_entity(name, etype)
    insert_relation(
        "Paper", paper_id, relation, etype, eid, source_pmid=pmid, status="active",
    )


def test_count_surveys_and_covers(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "s1", "title": "t", "year": 2024})
    p2 = upsert_paper({"pmid": "s2", "title": "u", "year": 2023})
    _edge("s1", p1, "SURVEYS_METHOD", "method-a", "Method")
    _edge("s2", p2, "SURVEYS_METHOD", "method-a", "Method")
    _edge("s1", p1, "COVERS_DISEASE", "disease-x", "Disease")
    assert count_surveys_by_method()["method-a"] == 2
    assert count_covers_by_disease()["disease-x"] == 1


def test_annotate_study_type_rows(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "a1", "title": "t", "year": 2024})
    _edge("a1", p1, "SURVEYS_METHOD", "m1", "Method")
    _edge("a1", p1, "COVERS_DISEASE", "d1", "Disease")
    rows = [{"method": "m1", "disease": "d1"}, {"method": "m2", "disease": "d2"}]
    out = annotate_study_type_rows(rows)
    assert out[0]["surveys_method_paper_cnt"] == 1
    assert out[0]["covers_disease_paper_cnt"] == 1
    assert out[1]["surveys_method_paper_cnt"] == 0
    assert out[1]["covers_disease_paper_cnt"] == 0


def test_build_covered_skips_applied_cooccur(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "c1", "title": "t", "year": 2024})
    _edge("c1", p1, "COVERS_DISEASE", "d-cover", "Disease")
    _edge("c1", p1, "SURVEYS_METHOD", "hot-m", "Method")
    applied_cooccur = {("hot-m", "d-applied"): 1}
    covered = build_covered_gap_rows(
        method_names=["hot-m"],
        cover_disease_names=["d-cover", "d-applied"],
        applied_cooccur={("hot-m", "d-cover"): 0, ("hot-m", "d-applied"): 3},
        applied_pair_set={("hot-m", "d-applied")},
    )
    pairs = {(r["method"], r["disease"]) for r in covered}
    assert ("hot-m", "d-cover") in pairs
    assert ("hot-m", "d-applied") not in pairs
    row = next(r for r in covered if r["disease"] == "d-cover")
    assert row["gap_kind"] == "covered"
    assert row["gap"] == "unexplored"
    assert row["paper_cnt"] == 0
    assert row["covers_disease_paper_cnt"] >= 1
```

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd d:\agent\prototype\build_kg_paper
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_study_type_downstream.py -v
```

Expected: `ModuleNotFoundError` / import failure.

- [ ] **Step 3: Implement `study_type_signals.py`**

```python
"""Batch study-type relation signals for gap/hotspot rows."""
from __future__ import annotations

from typing import Any

from db.schema import get_conn


def count_surveys_by_method() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE COALESCE(r.status, 'active') = 'active'
              AND r.relation = 'SURVEYS_METHOD' AND e.type = 'Method'
            GROUP BY e.id
            """
        ).fetchall()
    return {str(r["name"]): int(r["cnt"]) for r in rows}


def count_covers_by_disease() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS cnt
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE COALESCE(r.status, 'active') = 'active'
              AND r.relation = 'COVERS_DISEASE' AND e.type = 'Disease'
            GROUP BY e.id
            """
        ).fetchall()
    return {str(r["name"]): int(r["cnt"]) for r in rows}


def annotate_study_type_rows(
    rows: list[dict[str, Any]],
    *,
    method_key: str = "method",
    disease_key: str = "disease",
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    surveys = count_surveys_by_method()
    covers = count_covers_by_disease()
    for r in rows:
        m = str(r.get(method_key) or "")
        d = str(r.get(disease_key) or "")
        r["surveys_method_paper_cnt"] = int(surveys.get(m, 0))
        r["covers_disease_paper_cnt"] = int(covers.get(d, 0))
    return rows


def build_covered_gap_rows(
    method_names: list[str],
    cover_disease_names: list[str],
    applied_cooccur: dict[tuple[str, str], int],
    applied_pair_set: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in method_names:
        for d in cover_disease_names:
            key = (m, d)
            if key in applied_pair_set:
                continue
            if int(applied_cooccur.get(key, 0)) != 0:
                continue
            rows.append({
                "method": m,
                "disease": d,
                "paper_cnt": 0,
                "gap": "unexplored",
                "gap_kind": "covered",
            })
    rows = annotate_study_type_rows(rows)
    rows = [r for r in rows if int(r.get("covers_disease_paper_cnt") or 0) >= 1]
    rows.sort(
        key=lambda r: (
            -int(r.get("covers_disease_paper_cnt") or 0),
            -int(r.get("surveys_method_paper_cnt") or 0),
            str(r.get("method") or ""),
            str(r.get("disease") or ""),
        )
    )
    return rows
```

- [ ] **Step 4: Re-run unit tests — expect PASS**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_study_type_downstream.py -v
```

- [ ] **Step 5: Skip commit** unless the user asks.

---

### Task 2: Dual-channel `method_disease_combo_gap`

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py` (`tool_method_disease_combo_gap`)
- Modify: `fulltext_workflow/tests/test_study_type_downstream.py`

**Interfaces:**
- Consumes: `build_covered_gap_rows`, `annotate_study_type_rows`, `enrich_method_disease_rows`
- Produces: merged `gaps` with `gap_kind`, study-type counts, binding fields; length ≤ 40

- [ ] **Step 1: Write failing integration tests**

```python
from analysis.gap_tools import tool_method_disease_combo_gap  # noqa: E402


def test_combo_dual_channel_applied_and_covered(monkeypatch):
    _tmp_db(monkeypatch)
    # Hot applied method×disease with co-occurrence (minimal or none for other disease)
    for i in range(3):
        pid = upsert_paper({"pmid": f"ap{i}", "title": f"t{i}", "year": 2024})
        _edge(f"ap{i}", pid, "APPLIES_METHOD", "hot-method", "Method")
        _edge(f"ap{i}", pid, "TARGETS_DISEASE", "hot-disease", "Disease")
    # Cover-only disease (no APPLIES×TARGETS with hot-method)
    for i in range(3):
        pid = upsert_paper({"pmid": f"cv{i}", "title": f"c{i}", "year": 2024})
        _edge(f"cv{i}", pid, "COVERS_DISEASE", "cover-disease", "Disease")
        _edge(f"cv{i}", pid, "SURVEYS_METHOD", "hot-method", "Method")

    gaps = tool_method_disease_combo_gap().get("gaps") or []
    by_kind = {}
    for g in gaps:
        by_kind.setdefault(g.get("gap_kind"), []).append(g)
        assert "surveys_method_paper_cnt" in g
        assert "covers_disease_paper_cnt" in g
    assert by_kind.get("applied")
    covered_pairs = {(g["method"], g["disease"]) for g in by_kind.get("covered", [])}
    assert ("hot-method", "cover-disease") in covered_pairs
    # Applied co-occurrence pair must not also appear as covered
    for g in by_kind.get("covered", []):
        assert not (g["method"] == "hot-method" and g["disease"] == "hot-disease")


def test_combo_covered_excluded_when_applied_cooccur(monkeypatch):
    _tmp_db(monkeypatch)
    for i in range(3):
        pid = upsert_paper({"pmid": f"both{i}", "title": f"t{i}", "year": 2024})
        _edge(f"both{i}", pid, "APPLIES_METHOD", "m", "Method")
        _edge(f"both{i}", pid, "TARGETS_DISEASE", "d", "Disease")
        _edge(f"both{i}", pid, "COVERS_DISEASE", "d", "Disease")
    gaps = tool_method_disease_combo_gap().get("gaps") or []
    covered = [g for g in gaps if g.get("gap_kind") == "covered" and g["method"] == "m" and g["disease"] == "d"]
    assert covered == []
```

Tighten fixtures if Top-N does not surface names; do not weaken assertions.

- [ ] **Step 2: Run new tests — expect FAIL**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_study_type_downstream.py::test_combo_dual_channel_applied_and_covered fulltext_workflow/tests/test_study_type_downstream.py::test_combo_covered_excluded_when_applied_cooccur -v
```

- [ ] **Step 3: Wire dual channel in `tool_method_disease_combo_gap`**

Replace the end of the function (after building applied `gaps`) with logic equivalent to:

```python
from analysis.binding_enrichment import enrich_method_disease_rows
from analysis.study_type_signals import annotate_study_type_rows, build_covered_gap_rows

for g in gaps:
    g["gap_kind"] = "applied"
gaps = annotate_study_type_rows(gaps)
gaps = enrich_method_disease_rows(gaps)
gaps.sort(
    key=lambda r: (
        -int(r.get("surveys_method_paper_cnt") or 0),
        str(r.get("method") or ""),
        str(r.get("disease") or ""),
    )
)

# Cover disease Top-N
cover_diseases = _q(f"""
    SELECT e.name
    FROM relations r JOIN entities e ON r.object_id=e.id
    WHERE e.type='Disease' AND r.relation='COVERS_DISEASE'
      AND COALESCE(r.status, 'active') = 'active' {df}
    GROUP BY e.id ORDER BY COUNT(DISTINCT r.source_pmid) DESC
    LIMIT {config.TOOL_TOP_N}
""")
cover_names = [r["name"] for r in cover_diseases]
applied_pairs = {(g["method"], g["disease"]) for g in gaps}
covered = build_covered_gap_rows(
    method_names=method_names,
    cover_disease_names=cover_names,
    applied_cooccur=existing,
    applied_pair_set=applied_pairs,
)
covered = enrich_method_disease_rows(covered)

applied_out = gaps[:40]
remain = 40 - len(applied_out)
merged = applied_out + covered[: max(0, remain)]
desc = "Hot method x hot disease combination gaps (applied + covered channels)"
if focus:
    desc += f" (focus: {focus})"
return {"description": desc, "gaps": merged}
```

Keep the existing applied Top-N / `existing` co-occurrence map construction intact above this block. Ensure `df` focus clause is safe when empty (same as today).

- [ ] **Step 4: Re-run Task 2 tests — PASS**

- [ ] **Step 5: Skip commit** unless asked.

---

### Task 3: Secondary sort on priority matrix + transferable

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py` (`tool_literature_impact_priority_matrix`)
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`compute_emerging_gap_opportunities`)
- Modify: `fulltext_workflow/tests/test_study_type_downstream.py`

**Interfaces:**
- Consumes: `annotate_study_type_rows`
- Produces: rows with survey/cover counts; sort `(-primary, -surveys_method_paper_cnt)`; primary scores unchanged by survey

- [ ] **Step 1: Write failing sort tests**

```python
from analysis.weekly_hotspot import (  # noqa: E402
    compute_emerging_gap_opportunities,
    compute_weekly_hotspots,
)
from analysis.gap_tools import tool_literature_impact_priority_matrix  # noqa: E402
from datetime import datetime, timedelta, timezone


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_priority_matrix_secondary_sort_by_survey(monkeypatch):
    """When primary scores tie, higher surveys_method_paper_cnt ranks first."""
    _tmp_db(monkeypatch)
    # Build two unexplored pairs with same literature tier; different survey counts
    for i in range(3):
        pid = upsert_paper({"pmid": f"m{i}", "title": "t", "year": 2024})
        _edge(f"m{i}", pid, "APPLIES_METHOD", "m-hi", "Method")
        _edge(f"m{i}", pid, "APPLIES_METHOD", "m-lo", "Method")
        _edge(f"m{i}", pid, "TARGETS_DISEASE", "d-a", "Disease")
        _edge(f"m{i}", pid, "TARGETS_DISEASE", "d-b", "Disease")
    # Surveys only on m-hi
    for i in range(2):
        pid = upsert_paper({"pmid": f"sv{i}", "title": "s", "year": 2023})
        _edge(f"sv{i}", pid, "SURVEYS_METHOD", "m-hi", "Method")
    # Force unexplored: no co-occurrence edges between crossed pairs — if fixture
    # cannot force a tie, assert surveys field present and sort key behavior on
    # two rows manually constructed via annotate + sort helper instead.
    data = tool_literature_impact_priority_matrix().get("data") or []
    assert data
    for row in data:
        assert "surveys_method_paper_cnt" in row
    # Stable secondary: among equal gap_priority_score, survey desc
    from itertools import groupby
    from operator import itemgetter
    rows = sorted(data, key=lambda r: -float(r["gap_priority_score"]))
    for score, group in groupby(rows, key=lambda r: float(r["gap_priority_score"])):
        grp = list(group)
        surveys = [int(r["surveys_method_paper_cnt"]) for r in grp]
        assert surveys == sorted(surveys, reverse=True)


def test_emerging_secondary_sort_and_gap_kind(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)

    def paper(pmid: str, days_ago: int) -> int:
        return upsert_paper({
            "pmid": pmid,
            "title": pmid,
            "pub_date": _iso(days_ago),
            "year": int(_iso(days_ago)[:4]),
            "date_precision": "day",
            "extraction_done": 1,
        })

    p1 = paper("1", 3)
    _edge("1", p1, "APPLIES_METHOD", "method-a", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", p1, "PERFORMS_TASK", "survival prediction", "Task")
    p2 = paper("2", 4)
    _edge("2", p2, "APPLIES_METHOD", "method-a", "Method")
    _edge("2", p2, "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", p2, "PERFORMS_TASK", "survival prediction", "Task")
    p3 = paper("3", 5)
    _edge("3", p3, "SURVEYS_METHOD", "method-a", "Method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    assert rows
    for r in rows:
        assert r.get("gap_kind") == "applied"
        assert "surveys_method_paper_cnt" in r
        assert int(r["surveys_method_paper_cnt"]) >= 0
    # Primary order still by opportunity_score desc
    scores = [float(r["opportunity_score"]) for r in rows]
    assert scores == sorted(scores, reverse=True)
```

If the priority groupby assertion is brittle on tiny DBs, add a pure unit test that sorts two hand-built dicts with equal `gap_priority_score` and different survey counts using the same key tuple as production.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement wiring**

In `tool_literature_impact_priority_matrix`, after binding bump loop:

```python
from analysis.study_type_signals import annotate_study_type_rows

rows = annotate_study_type_rows(rows)
rows.sort(
    key=lambda r: (
        -float(r["gap_priority_score"]),
        -int(r.get("surveys_method_paper_cnt") or 0),
    )
)
```

(If rows were already sorted by priority only, replace that sort.)

In `compute_emerging_gap_opportunities`, after binding bump, before slice:

```python
from analysis.study_type_signals import annotate_study_type_rows

for r in rows:
    r["gap_kind"] = "applied"
rows = annotate_study_type_rows(rows)
rows.sort(
    key=lambda r: (
        -float(r["opportunity_score"]),
        -int(r.get("surveys_method_paper_cnt") or 0),
    )
)
```

Do **not** add survey into `opportunity_score` / `gap_priority_score`.

- [ ] **Step 4: Re-run Task 3 tests + `test_transferable_opportunities.py` + `test_binding_enrichment.py` — PASS**

- [ ] **Step 5: Skip commit** unless asked.

---

### Task 4: UI columns + agent prompt

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`opp_cols`; curated combo column lists if any)
- Modify: `fulltext_workflow/gap_agent.py` (prompt bullet)
- Optional: assert prompt/schema string in a tiny test if one already patterns that

**Interfaces:**
- Consumes: new row keys from Tasks 2–3
- Produces: visible columns + agent guidance

- [ ] **Step 1: Extend `opp_cols`**

Append after binding columns:

```python
"gap_kind",
"covers_disease_paper_cnt",
"surveys_method_paper_cnt",
```

Search `gap_ui.py` for other hard-coded opportunity/combo column lists (e.g. 机会表) and append the same three keys when the frame is built from combo/transferable rows.

- [ ] **Step 2: Agent prompt**

Add near study_type / emerging bullets:

```text
- Covered combo gaps (gap_kind=covered) use COVERS_DISEASE mentions, not APPLIES×TARGETS co-occurrence; SURVEYS_METHOD is survey mention for secondary ranking only, not APPLIES_METHOD heat.
```

- [ ] **Step 3: Smoke test**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_study_type_downstream.py fulltext_workflow/tests/test_transferable_opportunities.py fulltext_workflow/tests/test_binding_enrichment.py fulltext_workflow/tests/test_gap_study_type_stats.py -q
```

Expected: all PASS.

- [ ] **Step 4: Skip commit** unless asked.

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Counters + covered builder | Task 1 |
| Dual-channel combo + truncation | Task 2 |
| Secondary sort on matrix + transferable | Task 3 |
| UI columns + agent copy | Task 4 |
| No survey in primary scores / no new tabs / APPLIES heat | Global Constraints |

## Placeholder / consistency self-review

- Field names match spec: `gap_kind`, `covers_disease_paper_cnt`, `surveys_method_paper_cnt`
- Covered requires applied co-occurrence == 0 and cover count ≥ 1
- No TBD left in steps
