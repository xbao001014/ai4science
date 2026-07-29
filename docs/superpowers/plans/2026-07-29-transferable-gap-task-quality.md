# Transferable Gap Candidates + Task Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Cartesian「空白机会」with Task-bridged **可迁移候选**, and harden Task extraction via quality tiers, synonym normalize, and prompt policy.

**Architecture:** Shared Task rules live in `entity_normalize` (synonym + reject predicates used at extract time) and `task_quality` (tier classification + audit aggregation). `compute_emerging_gap_opportunities` only emits method×disease pairs that are sparse, have transfer prior, and share an `ok` Task bridge. UI/report/brief/agent copy follow the new semantics. Audit CLI is read-only.

**Tech Stack:** Python 3, SQLite (`db.schema`), pytest, Streamlit (`gap_ui.py`), argparse (`main.py`).

**Spec:** `docs/superpowers/specs/2026-07-29-transferable-gap-task-quality-design.md`

## Global Constraints

- Do **not** use `method_disease_combo_gap` Cartesian holes as the weekly transferable main board source.
- Bridge tasks must have `classify_task_quality(name) == "ok"`; `weak` / `reject` never bridge.
- Generic bare tasks are **rejected at extract** (`postprocess_triples` drops them); synonym merge does **not** canonicalise into generic names.
- No offline DB entity rename migration this round (user will full-corpus re-extract).
- Do not change hot-combo co-occurrence SQL semantics.
- Run pytest from `fulltext_workflow/` (tests add that root to `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.
- Do not commit secrets; do not run full-corpus re-extract as part of this plan.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/extractor/entity_normalize.py` | `_GENERIC_TASKS`, `_TASK_NARRATIVE_MARKERS`, `_TASK_SYNONYMS`, `is_generic_task`, `is_narrative_task`, `normalize_entity_name` Task branch, drop reject tasks in `postprocess_triples` |
| `fulltext_workflow/analysis/task_quality.py` | **New** — `classify_task_quality`, audit helpers, near-duplicate candidates |
| `fulltext_workflow/extractor/study_prompts/shared.py` | Task naming policy (GOOD/BAD) |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Rewrite `compute_emerging_gap_opportunities`; report section title/columns |
| `fulltext_workflow/analysis/hotspot_brief.py` | Brief system prompt: 可迁移候选 |
| `fulltext_workflow/gap_agent.py` | One-line tool guidance sync |
| `fulltext_workflow/gap_ui.py` | Tab rename + caption + columns |
| `fulltext_workflow/main.py` | `task-quality-audit` command |
| `fulltext_workflow/tests/test_entity_normalize.py` | Task synonym / drop tests |
| `fulltext_workflow/tests/test_task_quality.py` | **New** — tier + audit unit tests |
| `fulltext_workflow/tests/test_transferable_opportunities.py` | **New** — bridge vs Cartesian regression |
| `fulltext_workflow/gap_ui_guide.md` | Short doc sync (optional fold into UI task) |
| `fulltext_workflow/PIPELINE.md` / `SCRIPTS.md` | Mention audit command (fold into CLI task) |

---

### Task 1: Task synonym + reject predicates in entity_normalize

**Files:**
- Modify: `fulltext_workflow/extractor/entity_normalize.py`
- Modify: `fulltext_workflow/tests/test_entity_normalize.py`

**Interfaces:**
- Produces: `is_generic_task(name: str) -> bool`
- Produces: `is_narrative_task(name: str) -> bool`
- Produces: `is_reject_task(name: str) -> bool`  # generic OR narrative OR overlong heuristic
- Extends: `normalize_entity_name(name, "Task")` → synonym map then `_norm_key`
- Extends: `postprocess_triples` — normalize Task names; **drop** triples whose object is Task and `is_reject_task`

- [ ] **Step 1: Write the failing tests**

Append to `fulltext_workflow/tests/test_entity_normalize.py`:

```python
from extractor.entity_normalize import (
    is_generic_task,
    is_narrative_task,
    is_reject_task,
)


def _task_triple(name: str) -> Triple:
    return Triple(
        subject=Entity(name="paper", type="Disease"),
        relation="PERFORMS_TASK",
        object=Entity(name=name, type="Task"),
        evidence_quote="test",
    )


def test_task_synonym_prognosis():
    assert normalize_entity_name("prognostic prediction", "Task") == "prognosis prediction"
    assert normalize_entity_name("prognosis prediction", "Task") == "prognosis prediction"


def test_task_synonym_pathology_classification():
    assert (
        normalize_entity_name("pathological classification", "Task")
        == "pathology classification"
    )


def test_generic_task_detected():
    assert is_generic_task("classification")
    assert is_generic_task("Segmentation")
    assert not is_generic_task("tumor subtype classification")


def test_narrative_task_detected():
    assert is_narrative_task("workshop report on digital pathology imaging")
    assert is_narrative_task("improving diversity in study cohorts")
    assert not is_narrative_task("survival prediction")


def test_postprocess_drops_reject_tasks():
    kept = postprocess_triples(
        [
            _task_triple("classification"),
            _task_triple("tumor subtype classification"),
            _task_triple("workshop report on digital pathology"),
        ],
        "methods",
    )
    names = {t.object.name for t in kept if t.object.type == "Task"}
    assert "classification" not in names
    assert "workshop report on digital pathology" not in names
    assert "tumor subtype classification" in names


def test_postprocess_applies_task_synonym():
    kept = postprocess_triples([_task_triple("prognostic prediction")], "methods")
    assert kept[0].object.name == "prognosis prediction"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_entity_normalize.py::test_task_synonym_prognosis tests/test_entity_normalize.py::test_generic_task_detected tests/test_entity_normalize.py::test_postprocess_drops_reject_tasks -v
```

Expected: FAIL (imports / functions missing).

- [ ] **Step 3: Implement predicates + normalize + drop**

In `entity_normalize.py`, add near other `_GENERIC_*` sets:

```python
_GENERIC_TASKS = frozenset(
    {
        "classification",
        "segmentation",
        "detection",
        "prediction",
        "diagnosis",
        "prognosis",
        "analysis",
        "identification",
        "grading",
        "staging",
    }
)

_TASK_NARRATIVE_MARKERS = (
    "workshop",
    "report",
    "improving ",
    "developing ",
    "integrating ",
)

_TASK_SYNONYMS: dict[str, str] = {
    "prognostic prediction": "prognosis prediction",
    "prognosis prediction": "prognosis prediction",
    "pathological classification": "pathology classification",
}

_TASK_MAX_LEN = 80


def is_generic_task(name: str) -> bool:
    return _norm_key(name) in _GENERIC_TASKS


def is_narrative_task(name: str) -> bool:
    key = _norm_key(name)
    if any(m in key for m in _TASK_NARRATIVE_MARKERS):
        return True
    if len(key) > _TASK_MAX_LEN:
        return True
    return False


def is_reject_task(name: str) -> bool:
    return is_generic_task(name) or is_narrative_task(name)
```

Update `normalize_entity_name`:

```python
def normalize_entity_name(name: str, entity_type: str) -> str:
    key = _norm_key(name)
    if entity_type == "Limitation":
        return _LIMITATION_ALIASES.get(key, key)
    if entity_type == "Modality":
        return _MODALITY_ALIASES.get(key, key)
    if entity_type == "Task":
        return _TASK_SYNONYMS.get(key, key)
    return key
```

In `postprocess_triples` first loop, also normalize when `obj_type == "Task"`. After repair, in the final filter loop, drop when:

```python
if obj_type == "Task" and is_reject_task(obj_name):
    continue
```

(Apply after Task name has been synonym-normalized.)

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_entity_normalize.py -v -k "task"
```

Expected: PASS.

- [ ] **Step 5: Commit** (if executing with commits enabled)

```bash
git add fulltext_workflow/extractor/entity_normalize.py fulltext_workflow/tests/test_entity_normalize.py
git commit -m "feat(extract): reject generic/narrative tasks and merge task synonyms"
```

---

### Task 2: task_quality module (tiers + near-duplicate hints)

**Files:**
- Create: `fulltext_workflow/analysis/task_quality.py`
- Create: `fulltext_workflow/tests/test_task_quality.py`

**Interfaces:**
- Consumes: `is_generic_task`, `is_narrative_task`, `is_reject_task`, `normalize_entity_name` from `extractor.entity_normalize`
- Produces: `classify_task_quality(name: str) -> Literal["reject", "weak", "ok"]`
- Produces: `audit_task_names(names: list[str]) -> dict` with keys `counts`, `by_tier`, `near_duplicate_candidates`
- Near-duplicate heuristic: same token set after removing stopwords `{of,the,and,a,an}` OR edit-distance-lite via sorted-token equality of synonyms-not-mapped pairs sharing ≥2 tokens

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_task_quality.py`:

```python
"""Tests for Task quality tiers."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.task_quality import audit_task_names, classify_task_quality  # noqa: E402


def test_reject_generic_and_narrative():
    assert classify_task_quality("classification") == "reject"
    assert classify_task_quality("workshop report on digital pathology") == "reject"


def test_weak_single_token_non_generic():
    # single token not in generic blacklist → weak (too coarse to bridge)
    assert classify_task_quality("quantification") == "weak"


def test_ok_specific_phrase():
    assert classify_task_quality("tumor subtype classification") == "ok"
    assert classify_task_quality("survival prediction") == "ok"
    assert classify_task_quality("prognosis prediction") == "ok"


def test_audit_counts():
    out = audit_task_names(
        [
            "classification",
            "tumor subtype classification",
            "quantification",
            "prognostic prediction",  # normalizes then ok
        ]
    )
    assert out["counts"]["reject"] >= 1
    assert out["counts"]["ok"] >= 2
    assert out["counts"]["weak"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_task_quality.py -v
```

Expected: FAIL (`ModuleNotFoundError` or import error).

- [ ] **Step 3: Implement `task_quality.py`**

```python
"""Task entity quality tiers for bridging and audit."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from extractor.entity_normalize import (
    is_reject_task,
    normalize_entity_name,
)

TaskTier = Literal["reject", "weak", "ok"]

_STOP = frozenset({"of", "the", "and", "a", "an", "for", "in", "on", "to"})


def classify_task_quality(name: str) -> TaskTier:
    canon = normalize_entity_name(name, "Task")
    if is_reject_task(canon):
        return "reject"
    tokens = [t for t in canon.split() if t and t not in _STOP]
    if len(tokens) <= 1:
        return "weak"
    return "ok"


def _token_set(name: str) -> frozenset[str]:
    canon = normalize_entity_name(name, "Task")
    return frozenset(t for t in canon.split() if t and t not in _STOP)


def near_duplicate_candidates(names: list[str], *, min_shared_tokens: int = 2) -> list[dict[str, Any]]:
    """Suggest unmapped near-duplicates for synonym table curation (no auto-merge)."""
    uniq = sorted({normalize_entity_name(n, "Task") for n in names if n and n.strip()})
    out: list[dict[str, Any]] = []
    for i, a in enumerate(uniq):
        ta = _token_set(a)
        if len(ta) < min_shared_tokens:
            continue
        for b in uniq[i + 1 :]:
            if a == b:
                continue
            tb = _token_set(b)
            shared = ta & tb
            if len(shared) >= min_shared_tokens and ta != tb:
                out.append({"a": a, "b": b, "shared_tokens": sorted(shared)})
    return out[:50]


def audit_task_names(names: list[str]) -> dict[str, Any]:
    by_tier: dict[str, list[str]] = defaultdict(list)
    for raw in names:
        tier = classify_task_quality(raw)
        by_tier[tier].append(normalize_entity_name(raw, "Task"))
    counts = {t: len(by_tier.get(t, [])) for t in ("reject", "weak", "ok")}
    return {
        "counts": counts,
        "by_tier": {k: sorted(set(v)) for k, v in by_tier.items()},
        "near_duplicate_candidates": near_duplicate_candidates(names),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_task_quality.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/analysis/task_quality.py fulltext_workflow/tests/test_task_quality.py
git commit -m "feat(analysis): add task quality tiers and audit helpers"
```

---

### Task 3: Prompt Task naming policy

**Files:**
- Modify: `fulltext_workflow/extractor/study_prompts/shared.py` (Entity disambiguation / Task bullets ~lines 74–76 and add a Task naming policy block analogous to Method/Disease)

**Interfaces:**
- Produces: prompt text only (no new Python API)
- No automated LLM test required; add a tiny string-presence unit test optional in `tests/test_entity_normalize.py` or skip if no existing prompt tests — prefer a lightweight check:

```python
def test_shared_prompt_has_task_naming_policy():
    from extractor.study_prompts import shared
    text = shared.CORE_RULES if hasattr(shared, "CORE_RULES") else open(
        # fallback: read module source
    )
```

Prefer reading the module attribute that holds the shared rules string (inspect `shared.py` for the constant name — typically the big rules blob assigned to a variable used by packs). Assert substrings `"Task naming policy"` and `"tumor segmentation"` and `"BAD:"` appear.

- [ ] **Step 1: Locate the shared rules string in `shared.py` and write a failing substring test**

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Insert Task naming policy**

Add after the existing Task disambiguation bullet:

```text
Task naming policy (CRITICAL) — clinical/ML objective noun phrases only:
  - Task = this paper's study objective as a concise noun phrase
  - GOOD: "tumor segmentation", "survival prediction", "biomarker prediction",
    "msi status prediction", "tumor subtype classification"
  - BAD bare umbrellas: classification, segmentation, detection, prediction, diagnosis
  - BAD non-tasks: workshop/report titles; "improving cohort diversity";
    engineering roadmap sentences; Method backbone names reused as Task
  - Use PERFORMS_TASK → Task; never APPLIES_METHOD with object type Task
```

- [ ] **Step 4: Run substring test — PASS**

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/extractor/study_prompts/shared.py fulltext_workflow/tests/...
git commit -m "feat(extract): tighten Task naming policy in study prompts"
```

---

### Task 4: Rewrite transferable opportunities (core)

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`compute_emerging_gap_opportunities`, `tool_emerging_gap_opportunities`, report section in `generate_hotspot_report`)
- Create: `fulltext_workflow/tests/test_transferable_opportunities.py`

**Interfaces:**
- Consumes: `classify_task_quality`, `normalize_entity_name`, `literature_gap_points`
- Produces: rows with fields  
  `method`, `disease`, `literature_gap`, `literature_paper_cnt`, `bridge_task`, `bridge_quality`, `bridge_mode`, `support_diseases`, `recent_hot_cnt`, `velocity`, `emerging_score`, `opportunity_score`
- Removes: Cartesian loop over `tool_method_disease_combo_gap` without bridge

**Bridge bonus constants (document in code):**

```python
_BRIDGE_BONUS_SAME = 2.0
_BRIDGE_BONUS_CROSS = 1.0
```

- [ ] **Step 1: Write failing integration tests**

Create `fulltext_workflow/tests/test_transferable_opportunities.py` using temp DB pattern from `test_weekly_hotspot_pubdate.py`:

```python
"""Transferable opportunities require ok Task bridges (no Cartesian holes)."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from analysis.weekly_hotspot import compute_emerging_gap_opportunities, compute_weekly_hotspots
from db.schema import get_conn, init_db, insert_relation, upsert_entity, upsert_paper


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _paper(pmid: str, days_ago: int) -> None:
    upsert_paper(
        {
            "pmid": pmid,
            "title": pmid,
            "pub_date": _iso(days_ago),
            "year": int(_iso(days_ago)[:4]),
            "date_precision": "day",
            "extraction_done": 1,
        }
    )


def _edge(pmid: str, rel: str, name: str, etype: str) -> None:
    eid = upsert_entity(name, etype)
    insert_relation("Paper", pmid, rel, etype, eid, status="active")


def test_cartesian_hot_without_bridge_excluded(monkeypatch):
    _tmp_db(monkeypatch)
    # M1 used on D1 recently; M2 on D2; both methods/diseases "hot" but no shared task
    _paper("1", 3)
    _edge("1", "APPLIES_METHOD", "method-a", "Method")
    _edge("1", "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", "PERFORMS_TASK", "survival prediction", "Task")
    _paper("2", 4)
    _edge("2", "APPLIES_METHOD", "method-b", "Method")
    _edge("2", "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", "PERFORMS_TASK", "tumor segmentation", "Task")
    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    pairs = {(r["method"], r["disease"]) for r in rows}
    assert ("method-a", "disease-b") not in pairs
    assert ("method-b", "disease-a") not in pairs


def test_bridged_sparse_pair_included(monkeypatch):
    _tmp_db(monkeypatch)
    # method-a on disease-a + task T; disease-b + same task T; method-a NOT yet on disease-b
    _paper("1", 3)
    _edge("1", "APPLIES_METHOD", "method-a", "Method")
    _edge("1", "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", "PERFORMS_TASK", "survival prediction", "Task")
    _paper("2", 5)
    _edge("2", "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", "PERFORMS_TASK", "survival prediction", "Task")
    # make disease-b and method-a appear in emerging boards: need enough recent signal
    _paper("3", 4)
    _edge("3", "APPLIES_METHOD", "method-a", "Method")
    _edge("3", "TARGETS_DISEASE", "disease-a", "Disease")
    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    hit = [r for r in rows if r["method"] == "method-a" and r["disease"] == "disease-b"]
    assert hit, rows
    assert hit[0]["bridge_task"] == "survival prediction"
    assert hit[0]["bridge_quality"] == "ok"
    assert hit[0]["bridge_mode"] in ("same_paper", "cross_paper")
    assert "disease-a" in (hit[0].get("support_diseases") or "")
```

Adjust fixture paper counts if `HOTSPOT_MIN_RECENT_PAPERS` filters methods out — lower via `monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)` and `HOTSPOT_TOP_N` as needed.

- [ ] **Step 2: Run tests — expect FAIL** (Cartesian path may still emit pairs, or new fields missing)

- [ ] **Step 3: Implement algorithm**

Replace `compute_emerging_gap_opportunities` roughly as:

1. Build `hot_methods` / `hot_diseases` from payload top-20 with scores map.
2. SQL load active co-occurrence sets:
   - method→diseases, method→tasks, disease→tasks, method×disease counts
   - Prefer one or few queries; keep readable CTEs.
3. For each hot method M and each candidate disease D in (hot_diseases ∪ focus diseases):
   - skip if `cnt(M,D) > 2`
   - require `support = diseases(M) - {D}` non-empty
   - find ok tasks in `tasks(M) ∩ tasks(D)` via `classify_task_quality == "ok"`
   - pick best T; `bridge_mode = same_paper` if ∃ pmid with M+D+T or (M+T and D+T same pmid) else `cross_paper`
4. Score and sort; return top_n.
5. **Do not** call `tool_method_disease_combo_gap` for inclusion.

Update `tool_emerging_gap_opportunities` description string to mention task bridge.

Update `generate_hotspot_report` section title to `## Transferable Candidates (task-bridged)` and columns list including bridge fields.

- [ ] **Step 4: Run tests — PASS**

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_transferable_opportunities.py tests/test_weekly_hotspot.py -v
```

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/analysis/weekly_hotspot.py fulltext_workflow/tests/test_transferable_opportunities.py
git commit -m "feat(hotspot): replace Cartesian gaps with task-bridged transferable candidates"
```

---

### Task 5: Audit CLI `task-quality-audit`

**Files:**
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/analysis/task_quality.py` (add `run_task_quality_audit() -> str` markdown)
- Modify: `fulltext_workflow/SCRIPTS.md` and/or `PIPELINE.md` (one-line command note)

**Interfaces:**
- Produces: `run_task_quality_audit(limit_examples: int = 20) -> str`
- CLI: `main.py task-quality-audit [--out PATH]`
- Read-only on `entities` / `relations`

- [ ] **Step 1: Write a unit test that mocks/uses temp DB with a few Task entities and asserts markdown contains `reject` / `ok` headings**

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

```python
def run_task_quality_audit(...) -> str:
    # SELECT Task names + paper counts + relation mix
    # audit_task_names(...)
    # format markdown
```

Wire `cmd_task_quality_audit` + `sub.add_parser("task-quality-audit", ...)`.

Default out: `output/task_quality_audit_{YYYYMMDD}.md` under `config.OUTPUT_DIR` when `--out` omitted; always print summary counts to stdout.

- [ ] **Step 4: Run unit test PASS; optionally run CLI against real DB (manual)**

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/main.py fulltext_workflow/analysis/task_quality.py fulltext_workflow/SCRIPTS.md fulltext_workflow/tests/test_task_quality.py
git commit -m "feat(cli): add read-only task-quality-audit command"
```

---

### Task 6: UI, brief, agent copy

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_weekly_hotspot_tab`)
- Modify: `fulltext_workflow/analysis/hotspot_brief.py` (`_BRIEF_SYSTEM`)
- Modify: `fulltext_workflow/gap_agent.py` (emerging_gap_opportunities bullet)
- Modify: `fulltext_workflow/gap_ui_guide.md` (Weekly Hotspot subsection)

**Interfaces:**
- UI tab label: `可迁移候选`
- Caption under table: 需合格 Task 桥（`ok`）；无桥则列表为空属预期
- Preferred columns order when presenting dataframe:  
  `method`, `disease`, `bridge_task`, `bridge_mode`, `literature_gap`, `literature_paper_cnt`, `support_diseases`, `opportunity_score`, …

- [ ] **Step 1: Apply UI string/column changes in `gap_ui.py`**

Replace tab `"空白机会"` → `"可迁移候选"`; update empty `st.info` message; metric label `"空白机会"` → `"可迁移候选"` if present.

- [ ] **Step 2: Update `_BRIEF_SYSTEM` structure item (4) to 可迁移候选 (task-bridged); forbid inventing Cartesian holes**

- [ ] **Step 3: Update `gap_agent.py` line about `emerging_gap_opportunities`**

- [ ] **Step 4: Sync `gap_ui_guide.md` Weekly Hotspot bullet**

- [ ] **Step 5: Smoke — no pytest required beyond ensuring imports; optional:**

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -c "from analysis.weekly_hotspot import compute_emerging_gap_opportunities; print('ok')"
```

- [ ] **Step 6: Commit** (if enabled)

```bash
git add fulltext_workflow/gap_ui.py fulltext_workflow/analysis/hotspot_brief.py fulltext_workflow/gap_agent.py fulltext_workflow/gap_ui_guide.md
git commit -m "feat(ui): rename blank opportunities to transferable candidates"
```

---

### Task 7: Final verification

**Files:** none new

- [ ] **Step 1: Run full related pytest suite**

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_entity_normalize.py tests/test_task_quality.py tests/test_transferable_opportunities.py tests/test_weekly_hotspot.py tests/test_weekly_hotspot_pubdate.py -v
```

Expected: all PASS.

- [ ] **Step 2: Spec coverage check (manual)**

| Spec requirement | Task |
|------------------|------|
| Reject Cartesian main board | Task 4 |
| ok-only Task bridge | Task 2 + 4 |
| Synonym + extract drop | Task 1 |
| Prompt policy | Task 3 |
| Audit CLI | Task 5 |
| UI/report/brief/agent | Task 4 report + Task 6 |
| No DB rename migration | honored |

- [ ] **Step 3: Note for user** — run `main.py task-quality-audit` on current DB; full re-extract later to materialize extract-time rules.

---

## Self-review (plan vs spec)

1. **Spec coverage:** Goals 1–5 mapped to Tasks 1–6; non-goals respected (no UMLS, no combo SQL change, no DB rename, `method_disease_combo_gap` retained elsewhere).
2. **Placeholders:** None intentional; Task 3 requires locating the exact shared-rules constant name at implement time (inspect `shared.py` — do not invent a wrong attribute).
3. **Type consistency:** `classify_task_quality` → `"reject"|"weak"|"ok"`; opportunity rows use `bridge_quality="ok"` and `bridge_mode` in `same_paper`|`cross_paper`.
