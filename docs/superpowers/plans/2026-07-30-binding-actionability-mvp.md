# Binding Actionability MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register `study_type_relation_stats` for agents, and annotate combo / impact / transferable opportunity rows with Pass-2 binding + public-dataset fields and small score bumps—without changing candidate membership.

**Architecture:** Add `analysis/binding_enrichment.py` for batch lookup of `(method, disease)` → binding stats. Call it from `tool_method_disease_combo_gap`, `tool_literature_impact_priority_matrix`, and `compute_emerging_gap_opportunities`. Register the existing `tool_study_type_relation_stats` in `SQL_TOOLS` / `TOOL_SCHEMAS` and expose a Chinese label in `gap_ui` tool meta. Keep Task-bridge admission and Cartesian generators unchanged.

**Tech Stack:** Python 3, pytest, SQLite, Streamlit (column lists only)

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-binding-actionability-mvp-design.md`
- Do not rewrite combo with `COVERS_DISEASE` or rank by `SURVEYS_METHOD` (Round 2)
- Do not change Task-bridge admission rules for transferable candidates
- Do not add new UI tabs
- Score bumps only: `+0.5` if `public_dataset_cnt > 0`, else `+0.25` if `binding_paper_cnt > 0`, else `+0`
- Follow TDD: failing test → implement → pass
- Do **not** `git commit` unless the user explicitly asks

## File map

| Path | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/binding_enrichment.py` | Create: batch enrich + hint + score bump helpers |
| `fulltext_workflow/analysis/gap_tools.py` | Register study-type tool; enrich combo + priority matrix |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Enrich transferable rows + bump `opportunity_score` |
| `fulltext_workflow/gap_ui.py` | `TOOL_META` label; extend `opp_cols` |
| `fulltext_workflow/gap_agent.py` | One-line tool guidance for study-type stats |
| `fulltext_workflow/tests/test_gap_tool_registry_sql.py` | Assert registry includes study-type tool |
| `fulltext_workflow/tests/test_binding_enrichment.py` | Create: enrichment + wiring tests |

---

### Task 1: Register `study_type_relation_stats`

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py` (`SQL_TOOLS`, `TOOL_SCHEMAS`)
- Modify: `fulltext_workflow/gap_ui.py` (`TOOL_META`)
- Modify: `fulltext_workflow/gap_agent.py` (prompt bullet)
- Modify: `fulltext_workflow/tests/test_gap_tool_registry_sql.py`

**Interfaces:**
- Consumes: existing `tool_study_type_relation_stats() -> dict`
- Produces: tool name visible in `SQL_TOOLS`, `TOOL_SCHEMAS`, merged `GAP_TOOL_SCHEMAS`, and UI meta

- [ ] **Step 1: Write the failing registry tests**

Append to `fulltext_workflow/tests/test_gap_tool_registry_sql.py`:

```python
def test_study_type_relation_stats_present_in_merged_gap_tool_schemas():
    init_gap_registry()
    names = [tool["function"]["name"] for tool in GAP_TOOL_SCHEMAS]
    assert "study_type_relation_stats" in names


def test_study_type_relation_stats_in_sql_tools():
    from analysis.gap_tools import SQL_TOOLS

    assert "study_type_relation_stats" in SQL_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd d:\agent\prototype\build_kg_paper
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_tool_registry_sql.py -v
```

Expected: FAIL — `study_type_relation_stats` not in registry.

- [ ] **Step 3: Register tool + schema + UI meta + prompt note**

In `SQL_TOOLS` (after `metric_evidence_quality` or near other SQL tools):

```python
"study_type_relation_stats": tool_study_type_relation_stats,
```

In `TOOL_SCHEMAS`, add:

```python
{
    "type": "function",
    "function": {
        "name": "study_type_relation_stats",
        "description": (
            "Read-only QA counts for study-type-specific relations: "
            "SURVEYS_METHOD, COVERS_DISEASE, RELEASES_DATASET, PRETRAINS_ON. "
            "Survey/cover edges are not the same as APPLIES_METHOD / TARGETS_DISEASE."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
},
```

In `gap_ui.py` `TOOL_META`:

```python
"study_type_relation_stats": {"label": "研究类型关系计数", "category": "全文证据"},
```

In `gap_agent.py` tool-usage guidance (near other tool bullets), add one line:

```text
- Use study_type_relation_stats for QA counts of SURVEYS_METHOD / COVERS_DISEASE / RELEASES_DATASET / PRETRAINS_ON (not applied-method heat).
```

- [ ] **Step 4: Re-run registry tests**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_tool_registry_sql.py -v
```

Expected: PASS.

- [ ] **Step 5: Skip commit** unless the user asks.

---

### Task 2: `binding_enrichment` helper

**Files:**
- Create: `fulltext_workflow/analysis/binding_enrichment.py`
- Create: `fulltext_workflow/tests/test_binding_enrichment.py`

**Interfaces:**
- Consumes: SQLite `paper_entity_bindings` + `entities` via `db.schema.get_conn` / config `DB_PATH`
- Produces:
  - `actionability_hint(binding_paper_cnt: int, public_dataset_cnt: int) -> str`
  - `actionability_bump(binding_paper_cnt: int, public_dataset_cnt: int) -> float`
  - `enrich_method_disease_rows(rows: list[dict], *, method_key: str = "method", disease_key: str = "disease") -> list[dict]`
    - Mutates/returns same list length; each row gains `binding_paper_cnt`, `public_dataset_names` (list[str], max 5), `public_dataset_cnt`, `actionability_hint`

- [ ] **Step 1: Write failing unit tests**

Create `fulltext_workflow/tests/test_binding_enrichment.py`:

```python
"""Pass-2 binding annotations for method×disease rows."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.binding_enrichment import (  # noqa: E402
    actionability_bump,
    actionability_hint,
    enrich_method_disease_rows,
)
from db.schema import (  # noqa: E402
    init_db,
    upsert_entity,
    upsert_paper,
    upsert_paper_entity_binding,
)


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_actionability_hint_and_bump():
    assert actionability_hint(0, 0) == "no_binding"
    assert actionability_hint(2, 0) == "bound_no_public"
    assert actionability_hint(1, 1) == "public_data"
    assert actionability_bump(0, 0) == 0.0
    assert actionability_bump(2, 0) == 0.25
    assert actionability_bump(1, 1) == 0.5


def test_enrich_rows_with_and_without_binding(monkeypatch):
    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "b1", "title": "t", "year": 2024})
    mid = upsert_entity("method-a", "Method")
    did = upsert_entity("disease-a", "Disease")
    ds = upsert_entity("camelyon16", "Dataset", access_class="public")
    upsert_paper_entity_binding("b1", mid, did, ds, evidence_quote="used on")

    rows = [
        {"method": "method-a", "disease": "disease-a"},
        {"method": "method-a", "disease": "disease-b"},
    ]
    out = enrich_method_disease_rows(rows)
    assert len(out) == 2
    hit = out[0]
    assert hit["binding_paper_cnt"] == 1
    assert hit["public_dataset_cnt"] == 1
    assert "camelyon16" in hit["public_dataset_names"]
    assert hit["actionability_hint"] == "public_data"
    miss = out[1]
    assert miss["binding_paper_cnt"] == 0
    assert miss["public_dataset_cnt"] == 0
    assert miss["public_dataset_names"] == []
    assert miss["actionability_hint"] == "no_binding"
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_binding_enrichment.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `binding_enrichment.py`**

```python
"""Batch enrichment of method×disease rows from paper_entity_bindings."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from db.schema import get_conn

_PUBLIC_NAME_CAP = 5


def actionability_hint(binding_paper_cnt: int, public_dataset_cnt: int) -> str:
    if public_dataset_cnt > 0:
        return "public_data"
    if binding_paper_cnt > 0:
        return "bound_no_public"
    return "no_binding"


def actionability_bump(binding_paper_cnt: int, public_dataset_cnt: int) -> float:
    if public_dataset_cnt > 0:
        return 0.5
    if binding_paper_cnt > 0:
        return 0.25
    return 0.0


def enrich_method_disease_rows(
    rows: list[dict[str, Any]],
    *,
    method_key: str = "method",
    disease_key: str = "disease",
) -> list[dict[str, Any]]:
    if not rows:
        return rows

    pairs = {
        (str(r.get(method_key) or ""), str(r.get(disease_key) or ""))
        for r in rows
    }
    pairs.discard(("", ""))

    stats: dict[tuple[str, str], dict[str, Any]] = {
        p: {"pmids": set(), "public": []} for p in pairs
    }

    if pairs:
        with get_conn() as conn:
            cur = conn.execute(
                """
                SELECT b.source_pmid,
                       em.name AS method,
                       ed.name AS disease,
                       eds.name AS dataset,
                       LOWER(COALESCE(eds.access_class, '')) AS access_class
                FROM paper_entity_bindings b
                JOIN entities em ON b.method_entity_id = em.id AND em.type = 'Method'
                JOIN entities ed ON b.disease_entity_id = ed.id AND ed.type = 'Disease'
                LEFT JOIN entities eds ON b.dataset_entity_id = eds.id AND eds.type = 'Dataset'
                """
            )
            for row in cur.fetchall():
                key = (str(row["method"]), str(row["disease"]))
                if key not in stats:
                    continue
                stats[key]["pmids"].add(str(row["source_pmid"]))
                ds = row["dataset"]
                if ds and row["access_class"] == "public":
                    names = stats[key]["public"]
                    if ds not in names and len(names) < _PUBLIC_NAME_CAP:
                        names.append(str(ds))

    for r in rows:
        key = (str(r.get(method_key) or ""), str(r.get(disease_key) or ""))
        info = stats.get(key, {"pmids": set(), "public": []})
        bcnt = len(info["pmids"])
        pubs = list(info["public"])
        pcnt = len(pubs)
        r["binding_paper_cnt"] = bcnt
        r["public_dataset_names"] = pubs
        r["public_dataset_cnt"] = pcnt
        r["actionability_hint"] = actionability_hint(bcnt, pcnt)
    return rows
```

(Adjust SQL/imports only if local `get_conn` row access differs; keep field names exact.)

- [ ] **Step 4: Re-run enrichment unit tests**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_binding_enrichment.py -v
```

Expected: PASS.

- [ ] **Step 5: Skip commit** unless the user asks.

---

### Task 3: Wire combo gap + priority matrix

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py` (`tool_method_disease_combo_gap`, `tool_literature_impact_priority_matrix`)
- Modify: `fulltext_workflow/tests/test_binding_enrichment.py` (add wiring tests)

**Interfaces:**
- Consumes: `enrich_method_disease_rows`, `actionability_bump`
- Produces: combo `gaps` and priority `data` rows with annotation fields; priority score bumped

- [ ] **Step 1: Write failing wiring tests**

Append to `test_binding_enrichment.py`:

```python
from analysis.gap_tools import (  # noqa: E402
    tool_literature_impact_priority_matrix,
    tool_method_disease_combo_gap,
)
from db.schema import insert_relation  # noqa: E402


def _edge(pmid: str, paper_id: int, relation: str, name: str, etype: str) -> int:
    eid = upsert_entity(name, etype)
    insert_relation(
        "Paper", paper_id, relation, etype, eid, source_pmid=pmid, status="active",
    )
    return eid


def test_combo_gap_includes_binding_fields(monkeypatch):
    _tmp_db(monkeypatch)
    # Enough APPLIES/TARGETS volume so both appear in Top-N
    for i in range(3):
        pid = upsert_paper({"pmid": f"c{i}", "title": f"t{i}", "year": 2024})
        _edge(f"c{i}", pid, "APPLIES_METHOD", "hot-method", "Method")
        _edge(f"c{i}", pid, "TARGETS_DISEASE", "hot-disease", "Disease")
    mid = upsert_entity("hot-method", "Method")
    did = upsert_entity("hot-disease", "Disease")
    # Binding on a different paper for same pair is fine; gap may be minimal not unexplored
    upsert_paper({"pmid": "cb", "title": "bind", "year": 2023})
    ds = upsert_entity("tcga", "Dataset", access_class="public")
    upsert_paper_entity_binding("cb", mid, did, ds)

    gaps = tool_method_disease_combo_gap().get("gaps") or []
    assert gaps  # smoke: tool returns rows
    for g in gaps:
        assert "binding_paper_cnt" in g
        assert "actionability_hint" in g
        assert "public_dataset_cnt" in g


def test_priority_matrix_bumps_score_without_changing_set(monkeypatch):
    _tmp_db(monkeypatch)
    for i in range(3):
        pid = upsert_paper({"pmid": f"p{i}", "title": f"t{i}", "year": 2024})
        _edge(f"p{i}", pid, "APPLIES_METHOD", "m1", "Method")
        _edge(f"p{i}", pid, "TARGETS_DISEASE", "d1", "Disease")
    # Force an unexplored pair by adding a second hot disease without co-occurrence
    for i in range(3):
        pid = upsert_paper({"pmid": f"q{i}", "title": f"u{i}", "year": 2024})
        _edge(f"q{i}", pid, "TARGETS_DISEASE", "d2", "Disease")
        _edge(f"q{i}", pid, "APPLIES_METHOD", "m2", "Method")

    before = tool_literature_impact_priority_matrix()
    keys = {(r["method"], r["disease"]) for r in before["data"]}
    mid = upsert_entity("m1", "Method")
    did = upsert_entity("d2", "Disease")
    ds = upsert_entity("pub-ds", "Dataset", access_class="public")
    upsert_paper({"pmid": "bx", "title": "b", "year": 2022})
    upsert_paper_entity_binding("bx", mid, did, ds)

    after = tool_literature_impact_priority_matrix()
    keys_after = {(r["method"], r["disease"]) for r in after["data"]}
    assert keys_after == keys
    row = next(r for r in after["data"] if r["method"] == "m1" and r["disease"] == "d2")
    assert row["public_dataset_cnt"] >= 1
    assert row["gap_priority_score"] >= 0.5
```

If Top-N / gap membership is flaky on tiny DBs, tighten fixture until `m1×d2` appears in matrix `data` before asserting bump; do not weaken the membership equality assert.

- [ ] **Step 2: Run new tests — expect FAIL**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_binding_enrichment.py::test_combo_gap_includes_binding_fields fulltext_workflow/tests/test_binding_enrichment.py::test_priority_matrix_bumps_score_without_changing_set -v
```

Expected: FAIL — fields/bump missing.

- [ ] **Step 3: Wire enrichment in `gap_tools.py`**

At end of `tool_method_disease_combo_gap`, before return:

```python
from analysis.binding_enrichment import enrich_method_disease_rows

gaps = enrich_method_disease_rows(gaps)
return {"description": desc, "gaps": gaps[:40]}
```

(Apply enrich **before** the `[:40]` slice, or enrich the sliced list—either is fine; keep length ≤40.)

In `tool_literature_impact_priority_matrix`, after building each `rows.append({...})` loop (or after the full `rows` list), enrich then bump:

```python
from analysis.binding_enrichment import actionability_bump, enrich_method_disease_rows

rows = enrich_method_disease_rows(rows)
for r in rows:
    r["gap_priority_score"] = round(
        float(r["gap_priority_score"]) + actionability_bump(
            int(r.get("binding_paper_cnt") or 0),
            int(r.get("public_dataset_cnt") or 0),
        ),
        2,
    )
rows.sort(key=lambda r: r["gap_priority_score"], reverse=True)
```

- [ ] **Step 4: Re-run wiring tests**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_binding_enrichment.py -v
```

Expected: PASS (fix fixtures if Top-N edge cases fail).

- [ ] **Step 5: Skip commit** unless the user asks.

---

### Task 4: Wire transferable opportunities + UI columns

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`compute_emerging_gap_opportunities`)
- Modify: `fulltext_workflow/gap_ui.py` (`opp_cols` list ~1683)
- Modify: `fulltext_workflow/tests/test_binding_enrichment.py` and/or `test_transferable_opportunities.py`

**Interfaces:**
- Consumes: `enrich_method_disease_rows`, `actionability_bump`
- Produces: opportunity rows with annotation fields; bumped `opportunity_score`; UI column order includes new fields

- [ ] **Step 1: Write failing test for opportunity enrichment**

Append (reuse transferable fixture style from `test_transferable_opportunities.py`):

```python
from analysis.weekly_hotspot import (  # noqa: E402
    compute_emerging_gap_opportunities,
    compute_weekly_hotspots,
)
from datetime import datetime, timedelta, timezone


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_emerging_opportunities_enrich_and_bump(monkeypatch):
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

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    assert rows
    for r in rows:
        assert "binding_paper_cnt" in r
        assert "actionability_hint" in r

    target = next(r for r in rows if r["method"] == "method-a" and r["disease"] == "disease-b")
    base = float(target["opportunity_score"])
    mid = upsert_entity("method-a", "Method")
    did = upsert_entity("disease-b", "Disease")
    ds = upsert_entity("pub", "Dataset", access_class="public")
    upsert_paper({"pmid": "bind", "title": "b", "year": 2020})
    upsert_paper_entity_binding("bind", mid, did, ds)

    rows2 = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    keys = {(r["method"], r["disease"]) for r in rows}
    keys2 = {(r["method"], r["disease"]) for r in rows2}
    assert keys2 == keys
    target2 = next(r for r in rows2 if r["method"] == "method-a" and r["disease"] == "disease-b")
    assert target2["public_dataset_cnt"] >= 1
    assert float(target2["opportunity_score"]) >= base + 0.5 - 1e-6
```

- [ ] **Step 2: Run test — expect FAIL**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_binding_enrichment.py::test_emerging_opportunities_enrich_and_bump -v
```

- [ ] **Step 3: Implement enrichment in `compute_emerging_gap_opportunities`**

After building `rows` and **before** final sort/slice:

```python
from analysis.binding_enrichment import actionability_bump, enrich_method_disease_rows

rows = enrich_method_disease_rows(rows)
for r in rows:
    r["opportunity_score"] = round(
        float(r["opportunity_score"])
        + actionability_bump(
            int(r.get("binding_paper_cnt") or 0),
            int(r.get("public_dataset_cnt") or 0),
        ),
        2,
    )
rows.sort(key=lambda r: r["opportunity_score"], reverse=True)
```

Update `tool_emerging_gap_opportunities` description string to mention binding bump optionally.

In `gap_ui.py` `opp_cols`, append:

```python
"binding_paper_cnt",
"public_dataset_cnt",
"public_dataset_names",
"actionability_hint",
```

(If `public_dataset_names` is a list, dataframe display is fine; optional `", ".join` only if Streamlit renders poorly.)

- [ ] **Step 4: Run focused + regression suites**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_binding_enrichment.py fulltext_workflow/tests/test_transferable_opportunities.py fulltext_workflow/tests/test_gap_tool_registry_sql.py fulltext_workflow/tests/test_gap_study_type_stats.py -v
```

Expected: all PASS.

- [ ] **Step 5: Skip commit** unless the user asks.

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Register `study_type_relation_stats` | Task 1 |
| Annotation fields + hints | Task 2 |
| Combo + priority matrix enrich + bumps | Task 3 |
| Transferable enrich + bumps + UI columns | Task 4 |
| No membership change / no new tabs / Round 2 deferred | Global Constraints + tests |

## Placeholder / consistency self-review

- Field names match spec: `binding_paper_cnt`, `public_dataset_names`, `public_dataset_cnt`, `actionability_hint`
- Bumps: `0.5` / `0.25` / `0`
- No TBD left in steps
