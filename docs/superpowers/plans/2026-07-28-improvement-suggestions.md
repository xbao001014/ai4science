# Improvement Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn author limitations / future work into structured, actionable improvement suggestions (Pass 2 sidecar), then expose paper-level and topic×action corpus views plus an idea-agent tool.

**Architecture:** Extend Pass 2 reconcile JSON with `recommendations[]`. Persist to `paper_improvement_suggestions` (not KG entities). Re-run supersedes prior active rows per PMID. Downstream: gap tools + gap_ui + idea_agent read `status='active'` only.

**Tech Stack:** Python 3, SQLite, existing Pass 2 LLM (`llm_call_structured`), Streamlit `gap_ui`, pytest under `fulltext_workflow/`.

**Spec:** `docs/superpowers/specs/2026-07-28-improvement-suggestions-design.md`

## Global Constraints

- Grounding policy B: author-anchored + light synthesis; never invent dataset names, diseases, or numeric targets absent from evidence/context text.
- Suggestions are a **sidecar table**; do not add Direction/Suggestion entities or `SUGGESTS_*` relations.
- Do not change limitation temporal / impact ranking formulas (still Limitation-based).
- Do not change Fangxin feasibility or difficulty scoring.
- Abstract-only / `skipped_no_ft`: write **zero** suggestions.
- Soft max **8** recommendations per paper after parse/filter.
- Vague suggestions matching “more research is needed” / “further studies are warranted” without a concrete action → **drop**.
- Run pytest from `fulltext_workflow/` (tests add that root to `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.
- Do not commit secrets; do not change PubMed query groups.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/db/schema.py` | `paper_improvement_suggestions` DDL + migrate + CRUD helpers |
| `fulltext_workflow/extractor/improvement_actions.py` | **New** — `ACTION_TYPES`, vague-drop helper, parse/normalize recommendation rows |
| `fulltext_workflow/extractor/fulltext_reconcile.py` | Parse `recommendations`; apply after limitation merges |
| `fulltext_workflow/extractor/study_prompts/shared.py` | Extend `RECONCILE_SHARED_CORE` JSON shape + rules |
| `fulltext_workflow/analysis/gap_tools.py` | `tool_improvement_suggestions_by_topic` (topic × action) |
| `fulltext_workflow/idea_agent.py` | `improvement_suggestions_for_topic` tool + prompt line |
| `fulltext_workflow/gap_ui.py` | Tool labels; render topic×action; enrich 局限 tab |
| `fulltext_workflow/tests/test_improvement_suggestions.py` | **New** — schema, parse, apply, aggregate |
| `fulltext_workflow/tests/test_fulltext_reconcile.py` | Assert apply path writes suggestions |
| `fulltext_workflow/tests/test_study_prompts.py` | Assert reconcile core mentions recommendations |

---

### Task 1: Schema + CRUD helpers

**Files:**
- Modify: `fulltext_workflow/db/schema.py`
- Test: `fulltext_workflow/tests/test_improvement_suggestions.py` (create)

**Interfaces:**
- Produces: table `paper_improvement_suggestions`
- Produces: `replace_paper_improvement_suggestions(pmid: str, rows: list[dict]) -> int`
- Produces: `list_active_improvement_suggestions(pmid: str | None = None, limit: int = 200) -> list[dict]`
- Row dict keys on write: `limitation_entity_id`, `action_type`, `suggestion`, `evidence_quote`, `evidence_section`, `grounding`, `confidence`

- [ ] **Step 1: Write the failing test**

Create `fulltext_workflow/tests/test_improvement_suggestions.py`:

```python
"""Tests for paper_improvement_suggestions store and Pass 2 wiring."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    get_conn,
    init_db,
    list_active_improvement_suggestions,
    replace_paper_improvement_suggestions,
    upsert_entity,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_replace_suggestions_supersedes_prior(monkeypatch):
    _tmp_db(monkeypatch)
    pmid = "90000001"
    upsert_paper({"pmid": pmid, "title": "Suggestion store test"})
    lim_id = upsert_entity("lack of external validation", "Limitation")

    n1 = replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on an independent cohort.",
                "evidence_quote": "lack of external validation",
                "evidence_section": "limitations",
                "grounding": "author_stated",
                "confidence": 0.9,
            }
        ],
    )
    assert n1 == 1
    assert len(list_active_improvement_suggestions(pmid)) == 1

    n2 = replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on a multi-center WSI cohort.",
                "evidence_quote": "future external validation",
                "evidence_section": "future_work",
                "grounding": "synthesized",
                "confidence": 0.85,
            }
        ],
    )
    assert n2 == 1
    active = list_active_improvement_suggestions(pmid)
    assert len(active) == 1
    assert "multi-center" in active[0]["suggestion"]

    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM paper_improvement_suggestions WHERE source_pmid=?",
            (pmid,),
        ).fetchone()["c"]
    assert total == 2  # one superseded + one active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_replace_suggestions_supersedes_prior -v`

Expected: FAIL (import / function missing)

- [ ] **Step 3: Add DDL to `SCHEMA_SQL` and `_migrate_db`**

Append to `SCHEMA_SQL` (before closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS paper_improvement_suggestions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pmid           TEXT NOT NULL,
    limitation_entity_id  INTEGER,
    action_type           TEXT NOT NULL,
    suggestion            TEXT NOT NULL,
    evidence_quote        TEXT,
    evidence_section      TEXT,
    grounding             TEXT NOT NULL,
    confidence            REAL DEFAULT 0.5,
    status                TEXT DEFAULT 'active',
    extraction_pass       TEXT DEFAULT 'fulltext_reconcile',
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pis_pmid ON paper_improvement_suggestions(source_pmid);
CREATE INDEX IF NOT EXISTS idx_pis_action ON paper_improvement_suggestions(action_type);
CREATE INDEX IF NOT EXISTS idx_pis_lim ON paper_improvement_suggestions(limitation_entity_id);
CREATE INDEX IF NOT EXISTS idx_pis_status ON paper_improvement_suggestions(status);
```

In `_migrate_db`, inside the existing `conn.executescript("""...""")` block that creates ops/bindings tables (or a new executescript call at end of migrate), add the same `CREATE TABLE IF NOT EXISTS paper_improvement_suggestions` + indexes so existing DBs pick it up.

- [ ] **Step 4: Implement CRUD helpers**

Add near other upsert helpers in `schema.py`:

```python
def replace_paper_improvement_suggestions(pmid: str, rows: list[dict[str, Any]]) -> int:
    """Supersede prior active rows for pmid, then insert new active rows. Returns insert count."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE paper_improvement_suggestions
               SET status='superseded'
               WHERE source_pmid=? AND COALESCE(status, 'active')='active'""",
            (pmid,),
        )
        n = 0
        for row in rows:
            conn.execute(
                """INSERT INTO paper_improvement_suggestions
                   (source_pmid, limitation_entity_id, action_type, suggestion,
                    evidence_quote, evidence_section, grounding, confidence,
                    status, extraction_pass)
                   VALUES (?,?,?,?,?,?,?,?, 'active', 'fulltext_reconcile')""",
                (
                    pmid,
                    row.get("limitation_entity_id"),
                    row["action_type"],
                    row["suggestion"],
                    row.get("evidence_quote") or "",
                    row.get("evidence_section") or "",
                    row["grounding"],
                    float(row.get("confidence") if row.get("confidence") is not None else 0.5),
                ),
            )
            n += 1
        return n


def list_active_improvement_suggestions(
    pmid: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if pmid:
            rows = conn.execute(
                """SELECT s.*, e.name AS limitation_name
                   FROM paper_improvement_suggestions s
                   LEFT JOIN entities e ON s.limitation_entity_id = e.id
                   WHERE s.source_pmid=? AND COALESCE(s.status, 'active')='active'
                   ORDER BY s.confidence DESC, s.id DESC
                   LIMIT ?""",
                (pmid, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT s.*, e.name AS limitation_name
                   FROM paper_improvement_suggestions s
                   LEFT JOIN entities e ON s.limitation_entity_id = e.id
                   WHERE COALESCE(s.status, 'active')='active'
                   ORDER BY s.confidence DESC, s.id DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
```

Export new symbols from `fulltext_workflow/db/__init__.py` if that module re-exports CRUD (match existing style; if not re-exported, skip).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_replace_suggestions_supersedes_prior -v`

Expected: PASS

- [ ] **Step 6: Commit (if user requested commits)**

```bash
git add fulltext_workflow/db/schema.py fulltext_workflow/db/__init__.py fulltext_workflow/tests/test_improvement_suggestions.py
git commit -m "feat(db): store paper improvement suggestions sidecar"
```

---

### Task 2: Parse / normalize recommendation rows

**Files:**
- Create: `fulltext_workflow/extractor/improvement_actions.py`
- Modify: `fulltext_workflow/extractor/fulltext_reconcile.py` (`parse_reconcile_payload`)
- Test: `fulltext_workflow/tests/test_improvement_suggestions.py`

**Interfaces:**
- Consumes: raw LLM `recommendations` list
- Produces: `ACTION_TYPES: frozenset[str]`
- Produces: `parse_recommendation_rows(rows: Any) -> list[dict]`
- Produces: `is_vague_suggestion(text: str) -> bool`
- Each normalized dict: `limitation` (str), `action_type`, `suggestion`, `evidence_quote`, `evidence_section`, `grounding` (`author_stated`|`synthesized`), `confidence` (float)

- [ ] **Step 1: Write the failing tests**

Append to `test_improvement_suggestions.py`:

```python
def test_parse_recommendation_rows_filters_vague_and_bad_enum():
    from extractor.improvement_actions import parse_recommendation_rows

    rows = parse_recommendation_rows(
        [
            {
                "limitation": "lack of external validation",
                "action_type": "external_validation",
                "suggestion": "Validate on an independent multi-center cohort.",
                "evidence_quote": "lack of external validation",
                "evidence_section": "limitations",
                "grounding": "synthesized",
                "confidence": 0.8,
            },
            {
                "limitation": "small sample size",
                "action_type": "expand_sample",
                "suggestion": "More research is needed.",
                "evidence_quote": "small sample",
                "evidence_section": "discussion",
                "grounding": "author_stated",
                "confidence": 0.7,
            },
            {
                "limitation": "x",
                "action_type": "not_a_real_type",
                "suggestion": "Do something concrete with locked splits.",
                "evidence_quote": "q",
                "evidence_section": "future_work",
                "grounding": "synthesized",
                "confidence": 0.6,
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["action_type"] == "external_validation"


def test_parse_reconcile_payload_includes_recommendations():
    from extractor.fulltext_reconcile import parse_reconcile_payload

    p = parse_reconcile_payload(
        {
            "datasets": [],
            "bindings": [],
            "limitations": [],
            "recommendations": [
                {
                    "limitation": "single-center design",
                    "action_type": "multicenter",
                    "suggestion": "Recruit a second center with the same staining protocol.",
                    "evidence_quote": "single center",
                    "evidence_section": "limitations",
                    "grounding": "author_stated",
                    "confidence": 0.75,
                }
            ],
        }
    )
    assert len(p["recommendations"]) == 1
    assert p["recommendations"][0]["action_type"] == "multicenter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_parse_recommendation_rows_filters_vague_and_bad_enum tests/test_improvement_suggestions.py::test_parse_reconcile_payload_includes_recommendations -v`

Expected: FAIL

- [ ] **Step 3: Implement `improvement_actions.py`**

```python
"""Controlled action types and recommendation row normalization for Pass 2."""
from __future__ import annotations

import re
from typing import Any

ACTION_TYPES: frozenset[str] = frozenset(
    {
        "external_validation",
        "expand_sample",
        "multicenter",
        "prospective_design",
        "multimodal",
        "method_refinement",
        "dataset_enrichment",
        "other",
    }
)

_GROUNDINGS = frozenset({"author_stated", "synthesized"})

_VAGUE_RE = re.compile(
    r"^\s*(more research is needed|further studies? (are|is) (needed|warranted)|"
    r"future work is needed|additional studies are required)\s*\.?$",
    re.I,
)

MAX_RECOMMENDATIONS_PER_PAPER = 8


def is_vague_suggestion(text: str) -> bool:
    return bool(_VAGUE_RE.match((text or "").strip()))


def parse_recommendation_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action_type") or "").strip()
        if action not in ACTION_TYPES:
            continue
        suggestion = str(raw.get("suggestion") or "").strip()
        if not suggestion or is_vague_suggestion(suggestion):
            continue
        quote = str(raw.get("evidence_quote") or "").strip()
        if not quote:
            continue
        grounding = str(raw.get("grounding") or "synthesized").strip()
        if grounding not in _GROUNDINGS:
            grounding = "synthesized"
        limitation = str(raw.get("limitation") or "").strip()
        try:
            conf = float(raw.get("confidence") if raw.get("confidence") is not None else 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        key = (action, limitation.lower(), suggestion.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "limitation": limitation,
                "action_type": action,
                "suggestion": suggestion,
                "evidence_quote": quote,
                "evidence_section": str(raw.get("evidence_section") or "").strip(),
                "grounding": grounding,
                "confidence": conf,
            }
        )
        if len(out) >= MAX_RECOMMENDATIONS_PER_PAPER:
            break
    return out
```

- [ ] **Step 4: Wire into `parse_reconcile_payload`**

In `fulltext_reconcile.py`, import `parse_recommendation_rows` and add to returned dict:

```python
"recommendations": parse_recommendation_rows(raw.get("recommendations")),
```

Keep existing keys; default missing `recommendations` → `[]`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_parse_recommendation_rows_filters_vague_and_bad_enum tests/test_improvement_suggestions.py::test_parse_reconcile_payload_includes_recommendations -v`

Expected: PASS

- [ ] **Step 6: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/improvement_actions.py fulltext_workflow/extractor/fulltext_reconcile.py fulltext_workflow/tests/test_improvement_suggestions.py
git commit -m "feat(extract): parse Pass2 improvement recommendations"
```

---

### Task 3: Apply recommendations after limitation merges

**Files:**
- Modify: `fulltext_workflow/extractor/fulltext_reconcile.py`
- Modify: `fulltext_workflow/tests/test_fulltext_reconcile.py` (extend `test_apply_reconcile_payload` or add sibling)
- Test: `fulltext_workflow/tests/test_improvement_suggestions.py`

**Interfaces:**
- Consumes: `parse_reconcile_payload` → `recommendations`; `normalize_entity_name` / `upsert_entity`
- Produces: `_apply_recommendations(pmid, recommendations) -> None` called from `apply_reconcile_payload` **after** `_apply_limitation_merges`

- [ ] **Step 1: Write the failing test**

```python
def test_apply_reconcile_writes_suggestions(monkeypatch):
    from extractor.fulltext_reconcile import apply_reconcile_payload

    _tmp_db(monkeypatch)
    pmid = "90000002"
    paper_id = upsert_paper({"pmid": pmid, "title": "Apply suggestions"})
    apply_reconcile_payload(
        paper_id,
        pmid,
        {
            "datasets": [],
            "bindings": [],
            "limitations": [
                {
                    "canonical": "lack of external validation",
                    "merges": [],
                    "quote": "no external validation",
                }
            ],
            "recommendations": [
                {
                    "limitation": "lack of external validation",
                    "action_type": "external_validation",
                    "suggestion": "Validate on an independent cohort with locked preprocessing.",
                    "evidence_quote": "future external validation is needed",
                    "evidence_section": "future_work",
                    "grounding": "synthesized",
                    "confidence": 0.8,
                }
            ],
        },
    )
    rows = list_active_improvement_suggestions(pmid)
    assert len(rows) == 1
    assert rows[0]["action_type"] == "external_validation"
    assert rows[0]["limitation_entity_id"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_apply_reconcile_writes_suggestions -v`

Expected: FAIL (suggestions not written)

- [ ] **Step 3: Implement `_apply_recommendations` and call it**

```python
def _apply_recommendations(pmid: str, recommendations: list[dict[str, Any]]) -> None:
    from db.schema import replace_paper_improvement_suggestions, upsert_entity
    from extractor.entity_normalize import normalize_entity_name

    rows: list[dict[str, Any]] = []
    for rec in recommendations:
        lim_name = normalize_entity_name(rec.get("limitation") or "", "Limitation")
        lim_id = upsert_entity(lim_name, "Limitation") if lim_name else None
        rows.append(
            {
                "limitation_entity_id": lim_id,
                "action_type": rec["action_type"],
                "suggestion": rec["suggestion"],
                "evidence_quote": rec.get("evidence_quote") or "",
                "evidence_section": rec.get("evidence_section") or "",
                "grounding": rec["grounding"],
                "confidence": rec.get("confidence", 0.5),
            }
        )
    # Always replace so re-reconcile clears stale actives even when empty.
    replace_paper_improvement_suggestions(pmid, rows)
```

In `apply_reconcile_payload`, after `_apply_limitation_merges(...)`:

```python
_apply_recommendations(pmid, normalized["recommendations"])
```

Update docstring to mention recommendations.

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_apply_reconcile_writes_suggestions tests/test_fulltext_reconcile.py -v --tb=short`

Expected: PASS (existing reconcile tests still pass; new test passes)

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/fulltext_reconcile.py fulltext_workflow/tests/test_improvement_suggestions.py
git commit -m "feat(extract): persist Pass2 improvement suggestions"
```

---

### Task 4: Extend Pass 2 reconcile prompt

**Files:**
- Modify: `fulltext_workflow/extractor/study_prompts/shared.py` (`RECONCILE_SHARED_CORE`)
- Test: `fulltext_workflow/tests/test_study_prompts.py`

**Interfaces:**
- Produces: prompt JSON shape includes `recommendations` array and grounding rules (policy B)

- [ ] **Step 1: Write / extend failing assertion**

In `test_study_prompts.py` add:

```python
def test_reconcile_core_mentions_recommendations():
    from extractor.study_prompts.shared import RECONCILE_SHARED_CORE

    assert '"recommendations"' in RECONCILE_SHARED_CORE
    assert "action_type" in RECONCILE_SHARED_CORE
    assert "author_stated" in RECONCILE_SHARED_CORE
    assert "synthesized" in RECONCILE_SHARED_CORE
```

- [ ] **Step 2: Run to verify fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_study_prompts.py::test_reconcile_core_mentions_recommendations -v`

Expected: FAIL

- [ ] **Step 3: Update `RECONCILE_SHARED_CORE`**

In the return-shape JSON example, add:

```text
  "recommendations": [
    {
      "limitation": "...",
      "action_type": "external_validation|expand_sample|multicenter|prospective_design|multimodal|method_refinement|dataset_enrichment|other",
      "suggestion": "one executable sentence",
      "evidence_quote": "...",
      "evidence_section": "discussion|limitations|future_work|...",
      "grounding": "author_stated|synthesized",
      "confidence": 0.0
    }
  ]
```

Add rules (after limitations bullet):

```text
- recommendations: actionable follow-ups anchored on author limitations / future work.
  Lightly synthesize HOW using methods/cohort/modality context already in the text.
  Do NOT invent dataset names, diseases, diseases, or numeric targets absent from the paper.
  Drop vague lines ("more research is needed") with no concrete action.
  Prefer linking limitation to a canonical name from this pass's limitations list.
  Soft max 8 rows; prefer distinct action_type values.
  grounding=author_stated when mostly restating future work; synthesized when you flesh out how from context.
```

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_study_prompts.py::test_reconcile_core_mentions_recommendations -v`

Expected: PASS

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/study_prompts/shared.py fulltext_workflow/tests/test_study_prompts.py
git commit -m "feat(extract): Pass2 prompt for improvement recommendations"
```

---

### Task 5: Topic × action aggregation tool

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py`
- Test: `fulltext_workflow/tests/test_improvement_suggestions.py`

**Interfaces:**
- Produces: `tool_improvement_suggestions_by_topic(focus: str | None = None) -> dict`
- Return shape: `{"description": str, "count": int, "data": [{"action_type", "paper_cnt", "suggestion", "limitation", "sample_pmids", "avg_confidence"}, ...]}`
- Register in `GAP_TOOLS` / schemas dict used by gap UI (same pattern as `author_stated_gaps`)

- [ ] **Step 1: Write the failing test**

```python
def test_topic_action_aggregation(monkeypatch):
    from analysis.gap_tools import tool_improvement_suggestions_by_topic

    _tmp_db(monkeypatch)
    pmid = "90000003"
    upsert_paper(
        {
            "pmid": pmid,
            "title": "Breast cancer WSI grading with CNN",
            "abstract": "breast cancer digital pathology",
        }
    )
    lim_id = upsert_entity("lack of external validation", "Limitation")
    replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "external_validation",
                "suggestion": "Validate on an independent breast WSI cohort.",
                "evidence_quote": "no external validation",
                "evidence_section": "limitations",
                "grounding": "synthesized",
                "confidence": 0.9,
            }
        ],
    )
    out = tool_improvement_suggestions_by_topic("breast cancer")
    assert out["count"] >= 1
    row = out["data"][0]
    assert row["action_type"] == "external_validation"
    assert row["paper_cnt"] >= 1
    assert pmid in (row.get("sample_pmids") or "")
```

Note: if `topic_keyword_pmid_in_clause` needs title/abstract match, the paper fields above must satisfy the focus filter (adjust title/abstract to match how `search_papers_for_topic` works in this repo). If focus=None returns all active aggregations, also assert that path.

- [ ] **Step 2: Run to verify fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_topic_action_aggregation -v`

Expected: FAIL

- [ ] **Step 3: Implement tool**

In `gap_tools.py`:

```python
def tool_improvement_suggestions_by_topic(focus: str | None = None) -> dict:
    """Aggregate active improvement suggestions by action_type for a topic focus."""
    from analysis.focus_filter import topic_keyword_pmid_in_clause
    from db.schema import get_conn

    pmid_filter = ""
    if focus and str(focus).strip():
        pmid_filter = topic_keyword_pmid_in_clause("s.source_pmid", str(focus).strip())

    limit = int(config.TOOL_TOP_N)
    sql = f"""
        SELECT s.action_type AS action_type,
               COUNT(DISTINCT s.source_pmid) AS paper_cnt,
               AVG(s.confidence) AS avg_confidence,
               GROUP_CONCAT(DISTINCT s.source_pmid) AS sample_pmids
        FROM paper_improvement_suggestions s
        WHERE COALESCE(s.status, 'active')='active'
          {pmid_filter}
        GROUP BY s.action_type
        ORDER BY paper_cnt DESC, avg_confidence DESC
        LIMIT {limit}
    """

    with get_conn() as conn:
        buckets = [dict(r) for r in conn.execute(sql).fetchall()]

    # Attach a representative suggestion per action_type (highest confidence).
    data = []
    for b in buckets:
        action = b["action_type"]
        with get_conn() as conn:
            rep = conn.execute(
                f"""
                SELECT s.suggestion, e.name AS limitation, s.source_pmid, s.grounding
                FROM paper_improvement_suggestions s
                LEFT JOIN entities e ON s.limitation_entity_id = e.id
                WHERE COALESCE(s.status, 'active')='active'
                  AND s.action_type=?
                  {pmid_filter}
                ORDER BY s.confidence DESC, s.id DESC
                LIMIT 1
                """,
                (action,),
            ).fetchone()
        row = dict(b)
        if rep:
            row["suggestion"] = rep["suggestion"]
            row["limitation"] = rep["limitation"]
            row["grounding"] = rep["grounding"]
            # Keep sample_pmids short
            pmids = (row.get("sample_pmids") or "").split(",")
            row["sample_pmids"] = ",".join(pmids[:5])
        data.append(row)

    desc = "Improvement suggestions by action_type"
    if focus:
        desc += f" for '{focus}'"
    return {"description": desc, "count": len(data), "data": data}
```

Register next to `author_stated_gaps` in the tools map and OpenAI-style schema list (name `improvement_suggestions_by_topic`, optional `focus` string).

Trim `sample_pmids` in SQL if `GROUP_CONCAT` is huge — limit in Python as above.

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_topic_action_aggregation -v`

Expected: PASS (if focus matching fails, set `focus=None` in test for smoke and add a second test with a known-matching title from `test_focus_filter` patterns)

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/analysis/gap_tools.py fulltext_workflow/tests/test_improvement_suggestions.py
git commit -m "feat(analysis): topic x action improvement suggestion buckets"
```

---

### Task 6: gap_ui surfaces

**Files:**
- Modify: `fulltext_workflow/gap_ui.py`

**Interfaces:**
- Consumes: `tool_improvement_suggestions_by_topic`, `list_active_improvement_suggestions`
- Produces: UI label entry; when tool result key matches, render table; hotspot「局限」tab shows action buckets when focus available

- [ ] **Step 1: Add catalog metadata**

In the tool label maps (near `author_stated_gaps` / `author_limitations_for_topic`):

```python
"improvement_suggestions_by_topic": {
    "label": "改进方向 × 动作",
    "category": "全文证据",
},
```

And in idea-tool Chinese labels if present:

```python
"improvement_suggestions_for_topic": "改进建议",
```

- [ ] **Step 2: Render helper for suggestion tables**

Where generic tool results are shown (`safe_table(pd.DataFrame(result["data"]))`), ensure columns `action_type`, `suggestion`, `limitation`, `grounding`, `paper_cnt`, `sample_pmids` display without special casing if already generic. If `author_stated_gaps` has a special branch, add a parallel branch:

```python
if tool_name == "improvement_suggestions_by_topic" or "action_type" in (result.get("data") or [{}])[0]:
    st.caption("synthesized = 结合全文轻度综合；author_stated = 贴近作者原述")
    safe_table(pd.DataFrame(result["data"]))
    return
```

(Only add the special branch if the generic path cannot show nested fields.)

- [ ] **Step 3: Enrich hotspot 局限 tab**

In the hotspot section where `tab_l` shows `new_limitations`, after that table:

```python
focus = st.session_state.get("focus") or st.session_state.get("hotspot_focus") or ""
# Use whatever focus variable the hotspot page already has; do not invent a new global.
try:
    from analysis.gap_tools import tool_improvement_suggestions_by_topic
    buckets = tool_improvement_suggestions_by_topic(focus or None)
    if buckets.get("data"):
        st.markdown("**主题 × 改进动作**")
        safe_table(pd.DataFrame(buckets["data"]))
except Exception:
    pass
```

Wire `focus` to the actual sidebar/hotspot focus string already used on that page (inspect nearby code; prefer existing `focus_raw` / keyword state).

- [ ] **Step 4: Manual smoke**

Run: `cd fulltext_workflow; ..\.venv\Scripts\streamlit.exe run gap_ui.py`  
With DB that has suggestions (or insert via test helper), open gap tool `改进方向 × 动作` and hotspot 局限 tab.

Expected: tables render; empty focus still lists global buckets if any rows exist.

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/gap_ui.py
git commit -m "feat(ui): show improvement suggestion buckets"
```

---

### Task 7: Idea agent tool + prompt

**Files:**
- Modify: `fulltext_workflow/idea_agent.py`
- Test: `fulltext_workflow/tests/test_improvement_suggestions.py` (or thin `test_idea_agent_suggestions.py`)

**Interfaces:**
- Produces: `tool_improvement_suggestions_for_topic(keyword: str) -> dict` (row-level, not only buckets)
- Registers in `_SQL_IDEA_TOOLS` + `_IDEA_TOOL_SCHEMAS`
- Prompt: prefer this tool for “what to do next”; keep `author_limitations_for_topic` as problem statement

- [ ] **Step 1: Write the failing test**

```python
def test_idea_tool_improvement_suggestions(monkeypatch):
    from idea_agent import tool_improvement_suggestions_for_topic

    _tmp_db(monkeypatch)
    pmid = "90000004"
    upsert_paper(
        {
            "pmid": pmid,
            "title": "Lung adenocarcinoma WSI classification",
            "abstract": "lung adenocarcinoma pathology AI",
        }
    )
    lim_id = upsert_entity("small sample size", "Limitation")
    replace_paper_improvement_suggestions(
        pmid,
        [
            {
                "limitation_entity_id": lim_id,
                "action_type": "expand_sample",
                "suggestion": "Enlarge the training cohort with additional annotated WSIs.",
                "evidence_quote": "only 87 patients",
                "evidence_section": "limitations",
                "grounding": "synthesized",
                "confidence": 0.88,
            }
        ],
    )
    out = tool_improvement_suggestions_for_topic("lung adenocarcinoma")
    assert out["count"] >= 1
    assert out["data"][0]["action_type"] == "expand_sample"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py::test_idea_tool_improvement_suggestions -v`

Expected: FAIL

- [ ] **Step 3: Implement tool**

```python
def tool_improvement_suggestions_for_topic(keyword: str) -> dict:
    pmid_fc = topic_keyword_pmid_in_clause("s.source_pmid", keyword)
    rows = _q(f"""
        SELECT e.name AS limitation,
               s.action_type,
               s.suggestion,
               s.evidence_quote,
               s.evidence_section,
               s.grounding,
               s.confidence,
               s.source_pmid
        FROM paper_improvement_suggestions s
        LEFT JOIN entities e ON s.limitation_entity_id = e.id
        WHERE COALESCE(s.status, 'active')='active'
          {pmid_fc}
        ORDER BY s.confidence DESC
        LIMIT {config.TOOL_TOP_N}
    """)
    return {
        "description": f"Actionable improvement suggestions for '{keyword}'",
        "count": len(rows),
        "data": rows,
    }
```

Add to `_SQL_IDEA_TOOLS` and schema list (description: structured follow-ups with action_type, suggestion, evidence_quote; prefer over raw limitations when planning next steps).

Update `GENERATOR_SYSTEM_PROMPT` tool-use rules:

```text
- Prefer metrics_for_topic (with evidence_quote) and improvement_suggestions_for_topic
  for actionable next steps; use author_limitations_for_topic as the problem statement
  when suggestions are sparse.
```

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py -v --tb=short`

Expected: all PASS

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/idea_agent.py fulltext_workflow/tests/test_improvement_suggestions.py fulltext_workflow/gap_ui.py
git commit -m "feat(idea): tool for topic improvement suggestions"
```

---

### Task 8: Regression + pilot note

**Files:**
- Optionally append a short QA bullet to `fulltext_workflow/docs/pilot_study_type_qa.md` **or** leave a 5-line note in the PR/commit body only (prefer not expanding docs unless useful). Prefer a checklist comment in `test_improvement_suggestions.py` module docstring pointing at success criteria from the spec.

- [ ] **Step 1: Full related pytest**

Run:

```text
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_improvement_suggestions.py tests/test_fulltext_reconcile.py tests/test_study_prompts.py -v --tb=short
```

Expected: PASS

- [ ] **Step 2: Spec success criteria checklist (manual / pilot later)**

After a re-reconcile on existing pilot PMIDs (out of band; not required to automate in this plan):

1. ≥80% active suggestions have non-empty `evidence_quote`
2. Spot-check: no invented dataset/disease names
3. Re-run Pass 2 → no duplicate active dedup keys for same PMID
4. Topic aggregation returns ≥1 bucket when ≥3 papers have suggestions

- [ ] **Step 3: Final commit (if requested)**

```bash
git add -u fulltext_workflow/
git commit -m "test: cover improvement suggestions end-to-end paths"
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Sidecar table + supersede on re-run | Task 1 |
| Structured action_type + suggestion + evidence + grounding | Tasks 2–3 |
| Pass 2 JSON + policy B rules | Task 4 |
| Paper-level persist linked to Limitation | Task 3 |
| Topic × action aggregation | Task 5 |
| gap_ui paper/corpus surfaces | Task 6 |
| idea_agent tool + prompt | Task 7 |
| Soft max 8 / vague drop / no abstract-only invent | Task 2 (+ Pass 2 skip already means no apply without FT) |
| Do not alter limitation ranking / feasibility | Global constraints (no tasks touch those modules) |

No TBD placeholders. Names consistent: `replace_paper_improvement_suggestions`, `parse_recommendation_rows`, `tool_improvement_suggestions_by_topic`, `tool_improvement_suggestions_for_topic`.
