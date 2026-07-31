# Weekly Hotspot Novelty + Maturity Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep weekly method boards focused on **新苗头** (non-established methods), while allowing **情境新意** transferable candidates that demote and label mature baselines like LLM/SVM.

**Architecture:** Add `analysis/method_maturity.py` for blacklist + corpus-frequency tiers. `compute_weekly_hotspots` emits filtered `emerging_methods` plus unfiltered `active_methods`. Transferable scoring adds context-novelty bonus and maturity penalty; established methods may still enter via the active pool. UI/report/brief copy follow the new semantics.

**Tech Stack:** Python 3, SQLite (`db.schema`), pytest, Streamlit (`gap_ui.py`).

**Spec:** `docs/superpowers/specs/2026-07-31-weekly-hotspot-novelty-design.md`

## Global Constraints

- Method maturity = **blacklist first**, then corpus `APPLIES_METHOD` distinct PMID count ≥ `HOTSPOT_ESTABLISHED_MIN_PAPERS` (default **10**).
- Blacklist matching is **whole-string / explicit alias** after `_norm_key` — no naive substring.
- `emerging_methods` must **exclude** `method_maturity == established`; `active_methods` keeps them.
- Do **not** drop established from transferable; demote + label.
- Do **not** restore Cartesian `method_disease_combo_gap` as transferable source.
- Do not change Task quality / extract prompts / force re-extract.
- Disease heating board unchanged in this plan.
- Run pytest from repo with `fulltext_workflow/` on `sys.path` (existing test pattern).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/config.py` | `HOTSPOT_ESTABLISHED_MIN_PAPERS` |
| `fulltext_workflow/analysis/method_maturity.py` | **New** — blacklist, classify, corpus counts, annotate helpers, score deltas |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Annotate/filter methods; `active_methods`; combo maturity; transferable pool + score |
| `fulltext_workflow/analysis/hotspot_brief.py` | System prompt: no “新兴” for established |
| `fulltext_workflow/analysis/gap_tools.py` | Tool description string for `emerging_gap_opportunities` if present |
| `fulltext_workflow/gap_ui.py` | 新苗头 caption, 本周活跃 expander, columns, top metric |
| `fulltext_workflow/tests/test_method_maturity.py` | **New** — tier unit tests |
| `fulltext_workflow/tests/test_weekly_hotspot_maturity.py` | **New** — board filter + active list |
| `fulltext_workflow/tests/test_transferable_opportunities.py` | Extend: established demotion + still listed |

---

### Task 1: `method_maturity` module + config

**Files:**
- Create: `fulltext_workflow/analysis/method_maturity.py`
- Create: `fulltext_workflow/tests/test_method_maturity.py`
- Modify: `fulltext_workflow/config.py` (add env int near other `HOTSPOT_*`)

**Interfaces:**
- Produces: `is_established_blacklist(name: str) -> bool`
- Produces: `classify_method_maturity(name: str, corpus_paper_cnt: int, *, established_min: int | None = None) -> str`  # `established` \| `emerging` \| `nascent`
- Produces: `corpus_applies_method_counts() -> dict[str, int]`  # name → distinct PMID count, active APPLIES_METHOD
- Produces: `annotate_method_rows(rows: list[dict], *, name_key: str = "name", counts: dict[str, int] | None = None) -> list[dict]`  # mutates/returns rows with `corpus_paper_cnt`, `method_maturity`
- Produces: `context_novelty_bonus(literature_paper_cnt: int, *, first_in_recent_window: bool = False) -> float`
- Produces: `maturity_penalty(maturity: str) -> float`  # established → 2.0 else 0
- Produces: `nascent_bonus(maturity: str) -> float`  # nascent → 0.5 else 0
- Config: `HOTSPOT_ESTABLISHED_MIN_PAPERS: int` default 10

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_method_maturity.py`:

```python
"""Unit tests for method maturity classification."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_maturity import (  # noqa: E402
    classify_method_maturity,
    context_novelty_bonus,
    is_established_blacklist,
    maturity_penalty,
    nascent_bonus,
)


def test_blacklist_llm_and_svm():
    assert is_established_blacklist("large language model")
    assert is_established_blacklist("Large Language Models")
    assert is_established_blacklist("llm")
    assert is_established_blacklist("support vector machine")
    assert is_established_blacklist("svm")
    assert is_established_blacklist("deep learning")  # via generic umbrellas


def test_blacklist_no_naive_substring():
    assert not is_established_blacklist("cram-enhanced lightweight dual-branch cnn")
    assert not is_established_blacklist("pathology-specific vision transformer")


def test_classify_tiers_by_count():
    assert classify_method_maturity("niche-tool-x", 1, established_min=10) == "nascent"
    assert classify_method_maturity("niche-tool-x", 5, established_min=10) == "emerging"
    assert classify_method_maturity("niche-tool-x", 12, established_min=10) == "established"


def test_blacklist_beats_low_count():
    assert classify_method_maturity("large language model", 2, established_min=10) == "established"


def test_score_helpers():
    assert context_novelty_bonus(0) == 1.5
    assert context_novelty_bonus(2) == 0.5
    assert context_novelty_bonus(0, first_in_recent_window=True) == 2.0
    assert maturity_penalty("established") == 2.0
    assert maturity_penalty("nascent") == 0.0
    assert nascent_bonus("nascent") == 0.5
    assert nascent_bonus("emerging") == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_maturity.py -v
```

Expected: FAIL (module import error / not found).

- [ ] **Step 3: Add config**

In `fulltext_workflow/config.py` next to other `HOTSPOT_*`:

```python
HOTSPOT_ESTABLISHED_MIN_PAPERS: int = int(os.getenv("HOTSPOT_ESTABLISHED_MIN_PAPERS", "10"))
```

- [ ] **Step 4: Implement `method_maturity.py`**

Create `fulltext_workflow/analysis/method_maturity.py` with:

```python
"""Method maturity for weekly hotspot novelty gating."""
from __future__ import annotations

import config
from db.schema import get_conn
from extractor.entity_normalize import _norm_key, is_generic_method

_ESTABLISHED_METHOD_ALIASES = frozenset({
    "large language model",
    "large language models",
    "llm",
    "svm",
    "support vector machine",
    "support vector machines",
    "cnn",
    "convolutional neural network",
    "convolutional neural networks",
    "random forest",
    "logistic regression",
    "xgboost",
    "extreme gradient boosting",
    "resnet",
    "resnet-50",
    "resnet50",
    "resnet-18",
    "resnet18",
})


def is_established_blacklist(name: str) -> bool:
    key = _norm_key(name)
    if key in _ESTABLISHED_METHOD_ALIASES:
        return True
    return is_generic_method(name)


def classify_method_maturity(
    name: str,
    corpus_paper_cnt: int,
    *,
    established_min: int | None = None,
) -> str:
    if is_established_blacklist(name):
        return "established"
    threshold = (
        established_min
        if established_min is not None
        else config.HOTSPOT_ESTABLISHED_MIN_PAPERS
    )
    n = int(corpus_paper_cnt or 0)
    if n >= threshold:
        return "established"
    if n <= 2:
        return "nascent"
    return "emerging"


def corpus_applies_method_counts() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.name AS name, COUNT(DISTINCT r.source_pmid) AS n
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type = 'Method'
              AND r.relation = 'APPLIES_METHOD'
              AND COALESCE(r.status, 'active') = 'active'
            GROUP BY e.id
            """
        ).fetchall()
    return {str(r["name"]): int(r["n"]) for r in rows}


def annotate_method_rows(
    rows: list[dict],
    *,
    name_key: str = "name",
    counts: dict[str, int] | None = None,
) -> list[dict]:
    counts = counts if counts is not None else corpus_applies_method_counts()
    for row in rows:
        name = str(row.get(name_key) or "")
        n = int(counts.get(name, 0))
        row["corpus_paper_cnt"] = n
        row["method_maturity"] = classify_method_maturity(name, n)
    return rows


def context_novelty_bonus(
    literature_paper_cnt: int,
    *,
    first_in_recent_window: bool = False,
) -> float:
    base = 1.5 if int(literature_paper_cnt) <= 0 else 0.5
    if first_in_recent_window:
        base += 0.5
    return base


def maturity_penalty(maturity: str) -> float:
    return 2.0 if maturity == "established" else 0.0


def nascent_bonus(maturity: str) -> float:
    return 0.5 if maturity == "nascent" else 0.0
```

Note: importing `_norm_key` is acceptable if already used elsewhere; if lint forbids private import, add a public `norm_key` alias in `entity_normalize` or duplicate the one-liner locally.

- [ ] **Step 5: Run tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_maturity.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit (if executing with commits)**

```bash
git add fulltext_workflow/config.py fulltext_workflow/analysis/method_maturity.py fulltext_workflow/tests/test_method_maturity.py
git commit -m "feat: add method maturity classification for hotspot novelty"
```

---

### Task 2: Wire maturity into weekly method boards

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`compute_emerging_entities` optional flag **or** filter in `compute_weekly_hotspots`; prefer filter in `compute_weekly_hotspots` to keep SQL unchanged)
- Create: `fulltext_workflow/tests/test_weekly_hotspot_maturity.py`

**Interfaces:**
- Consumes: `annotate_method_rows`, `corpus_applies_method_counts`
- Extends payload: `emerging_methods` (no established), `active_methods` (all window-ranked methods with maturity fields)
- Extends hot combo rows: `method_maturity`, `corpus_paper_cnt` via annotate with `name_key="method"`

- [ ] **Step 1: Write the failing integration test**

Create `fulltext_workflow/tests/test_weekly_hotspot_maturity.py` using the same `_tmp_db` / `_paper` / `_edge` helpers as `test_transferable_opportunities.py` (copy helpers into this file — do not import from the other test module):

```python
"""Emerging method board excludes established baselines."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.weekly_hotspot import compute_weekly_hotspots  # noqa: E402
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 1)
    monkeypatch.setattr(config, "HOTSPOT_ESTABLISHED_MIN_PAPERS", 10)
    init_db()
    return path


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _paper(pmid: str, days_ago: int) -> int:
    return upsert_paper(
        {
            "pmid": pmid,
            "title": pmid,
            "pub_date": _iso(days_ago),
            "year": int(_iso(days_ago)[:4]),
            "date_precision": "day",
            "extraction_done": 1,
        }
    )


def _edge(pmid: str, paper_id: int, relation: str, name: str, entity_type: str) -> None:
    entity_id = upsert_entity(name, entity_type)
    insert_relation(
        "Paper",
        paper_id,
        relation,
        entity_type,
        entity_id,
        source_pmid=pmid,
        status="active",
    )


def test_llm_excluded_from_emerging_but_in_active(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = _paper("1", 2)
    _edge("1", p1, "APPLIES_METHOD", "large language model", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    p2 = _paper("2", 3)
    _edge("2", p2, "APPLIES_METHOD", "niche-new-method", "Method")
    _edge("2", p2, "TARGETS_DISEASE", "disease-a", "Disease")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging_names = {r["name"] for r in payload["emerging_methods"]}
    active_names = {r["name"] for r in payload["active_methods"]}

    assert "large language model" not in emerging_names
    assert "niche-new-method" in emerging_names
    assert "large language model" in active_names
    llm_row = next(r for r in payload["active_methods"] if r["name"] == "large language model")
    assert llm_row["method_maturity"] == "established"
    niche = next(r for r in payload["emerging_methods"] if r["name"] == "niche-new-method")
    assert niche["method_maturity"] == "nascent"
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_weekly_hotspot_maturity.py::test_llm_excluded_from_emerging_but_in_active -v
```

Expected: FAIL (`active_methods` missing and/or LLM still in `emerging_methods`).

- [ ] **Step 3: Implement board wiring in `compute_weekly_hotspots`**

After computing `methods = compute_emerging_entities("Method", ...)`:

```python
from analysis.method_maturity import annotate_method_rows, corpus_applies_method_counts

counts = corpus_applies_method_counts()
annotate_method_rows(methods, counts=counts)
active_methods = list(methods)
emerging_methods = [r for r in methods if r.get("method_maturity") != "established"]
```

Use `emerging_methods` for payload key `emerging_methods` and top_pmids loop; add `"active_methods": active_methods`.

For `compute_hot_combos` output, after building each combo dict (or on the list before return), call:

```python
annotate_method_rows(out, name_key="method", counts=counts)
```

If `counts` is not in scope inside `compute_hot_combos`, call `annotate_method_rows(combos, name_key="method")` once in `compute_weekly_hotspots` after `combos = compute_hot_combos(...)`. Prefer single `corpus_applies_method_counts()` call per `compute_weekly_hotspots`.

Sort hot_combos for display stability:

```python
combos.sort(
    key=lambda r: (
        0 if r.get("method_maturity") != "established" else 1,
        -float(r.get("emerging_score") or 0),
    )
)
```

Update `generate_hotspot_report` method section header/caption to say 新苗头; append a short bullet list of top-5 established from `active_methods` where `method_maturity == established`.

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_weekly_hotspot_maturity.py fulltext_workflow/tests/test_weekly_hotspot.py fulltext_workflow/tests/test_weekly_hotspot_pubdate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit (if executing with commits)**

```bash
git add fulltext_workflow/analysis/weekly_hotspot.py fulltext_workflow/tests/test_weekly_hotspot_maturity.py
git commit -m "feat: filter established methods from weekly emerging board"
```

---

### Task 3: Transferable opportunities — dual pool + demotion

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`compute_emerging_gap_opportunities`, `tool_emerging_gap_opportunities` description)
- Modify: `fulltext_workflow/tests/test_transferable_opportunities.py`
- Modify: `fulltext_workflow/analysis/gap_tools.py` tool description text if it hardcodes the old formula

**Interfaces:**
- Consumes: `active_methods` and/or annotated method stats from payload; `classify_method_maturity` / score helpers
- Method heat pool = names from `active_methods` (window-active), not only filtered `emerging_methods`
- Each opportunity row includes `method_maturity`, `context_novelty_bonus`, `maturity_penalty` (expose for UI/debug)

- [ ] **Step 1: Write failing tests**

Append to `fulltext_workflow/tests/test_transferable_opportunities.py`:

```python
def test_established_method_transfer_is_demoted_not_dropped(monkeypatch):
    _tmp_db(monkeypatch)
    # LLM used on disease-a with ok task; disease-b shares task; sparse LLM×disease-b
    p1 = _paper("1", 2)
    _edge("1", p1, "APPLIES_METHOD", "large language model", "Method")
    _edge("1", p1, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("1", p1, "PERFORMS_TASK", "survival prediction", "Task")
    p2 = _paper("2", 3)
    _edge("2", p2, "TARGETS_DISEASE", "disease-b", "Disease")
    _edge("2", p2, "PERFORMS_TASK", "survival prediction", "Task")
    # Nascent method with same bridge pattern for score comparison
    p3 = _paper("3", 2)
    _edge("3", p3, "APPLIES_METHOD", "niche-transfer-method", "Method")
    _edge("3", p3, "TARGETS_DISEASE", "disease-a", "Disease")
    _edge("3", p3, "PERFORMS_TASK", "survival prediction", "Task")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    rows = compute_emerging_gap_opportunities(window_days=14, payload=payload)
    by_pair = {(r["method"], r["disease"]): r for r in rows}

    llm_hit = by_pair.get(("large language model", "disease-b"))
    niche_hit = by_pair.get(("niche-transfer-method", "disease-b"))
    assert llm_hit is not None, rows
    assert llm_hit["method_maturity"] == "established"
    assert llm_hit["maturity_penalty"] == 2.0
    assert niche_hit is not None, rows
    assert niche_hit["opportunity_score"] > llm_hit["opportunity_score"]
```

Keep existing Cartesian / bridge tests green.

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_transferable_opportunities.py::test_established_method_transfer_is_demoted_not_dropped -v
```

Expected: FAIL (LLM absent because only `emerging_methods` feed the pool, and/or missing penalty fields).

- [ ] **Step 3: Implement scoring + pool**

In `compute_emerging_gap_opportunities`:

1. Build `method_stats` from `data.get("active_methods") or data.get("emerging_methods")` (prefer active so established remain eligible). Cap still `[:20]` **or** take top 20 emerging + any established present in active top-N — simplest correct approach: annotate and use `active_methods[:20]` as heat pool (active is already score-sorted before filter).
2. When emitting a row, set:

```python
from analysis.method_maturity import (
    classify_method_maturity,
    context_novelty_bonus,
    maturity_penalty,
    nascent_bonus,
)

maturity = stats.get("method_maturity") or classify_method_maturity(
    method, int(stats.get("corpus_paper_cnt") or 0)
)
# If active_methods lacked annotation, classify via corpus count lookup once.
novelty = context_novelty_bonus(paper_cnt)  # first_in_recent_window optional; v1 may omit extra SQL
pen = maturity_penalty(maturity)
nas = nascent_bonus(maturity)
opportunity_score = round(
    hot_score
    + literature_gap_points(literature_gap)
    + bridge_bonus
    + novelty
    - pen
    + nas,
    2,
)
```

3. Attach fields: `method_maturity`, `context_novelty_bonus`, `maturity_penalty`.
4. Sort:

```python
rows.sort(
    key=lambda r: (
        -float(r["opportunity_score"]),
        0 if r.get("method_maturity") != "established" else 1,
        -int(r.get("surveys_method_paper_cnt") or 0),
    )
)
```

5. Update tool description string to mention maturity penalty + context novelty.

Apply `actionability_bump` **after** the base formula as today (add bump on top).

- [ ] **Step 4: Run transferable + maturity tests**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_transferable_opportunities.py fulltext_workflow/tests/test_weekly_hotspot_maturity.py fulltext_workflow/tests/test_method_maturity.py fulltext_workflow/tests/test_binding_enrichment.py -v
```

Expected: PASS (fix any binding test that assumes old score arithmetic if it asserts exact numbers — update expected scores only if they hard-assert absolute values).

- [ ] **Step 5: Commit (if executing with commits)**

```bash
git add fulltext_workflow/analysis/weekly_hotspot.py fulltext_workflow/analysis/gap_tools.py fulltext_workflow/tests/test_transferable_opportunities.py
git commit -m "feat: demote established methods in transferable hotspot candidates"
```

---

### Task 4: UI + LLM brief copy

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_weekly_hotspot_tab`)
- Modify: `fulltext_workflow/analysis/hotspot_brief.py` (`_BRIEF_SYSTEM`, optionally slim context includes `active_methods` top established)

**Interfaces:**
- Consumes payload keys `emerging_methods`, `active_methods`, opportunity fields from Task 3

- [ ] **Step 1: Update UI**

In `render_weekly_hotspot_tab`:

- Change methods tab caption to 新苗头；说明 established 已过滤。
- Metric「热门方法」uses `(payload.get("emerging_methods") or [{}])[0].get("name", "—")` (already does — keep).
- Under methods tab, after `safe_table(emerging_methods)`:

```python
with st.expander("本周活跃（含成熟方法）", expanded=False):
    safe_table(pd.DataFrame(payload.get("active_methods", [])))
```

- Transferable caption: established 可出但已降权；columns insert `method_maturity`, `context_novelty_bonus`, `maturity_penalty` near score columns.
- Hot combos table already shows all columns from dataframe — ensure maturity fields present from Task 2.

No new automated UI test required.

- [ ] **Step 2: Update brief prompt**

In `_BRIEF_SYSTEM` add rules:

```
- emerging_methods = 新苗头 only (non-established). Do NOT call established baselines (LLM, SVM, CNN, deep learning, etc.) 新兴热点.
- If mentioning mature methods, only as 情境迁移 / 成熟方法交叉, and only when present in emerging_gap_opportunities with method_maturity=established.
- Prefer nascent/emerging methods in 升温方向.
```

Optionally add to slim JSON: `"active_established_methods": [names…][:5]`.

- [ ] **Step 3: Smoke-check imports**

```powershell
.\.venv\Scripts\python.exe -c "from analysis.weekly_hotspot import compute_weekly_hotspots; from analysis.hotspot_brief import _BRIEF_SYSTEM; print('ok', 'established' in _BRIEF_SYSTEM.lower() or '成熟' in _BRIEF_SYSTEM)"
```

Expected: prints ok / True-ish confirmation that prompt mentions maturity guidance (Chinese 成熟 or English established).

- [ ] **Step 4: Re-run focused pytest suite**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_maturity.py fulltext_workflow/tests/test_weekly_hotspot_maturity.py fulltext_workflow/tests/test_transferable_opportunities.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit (if executing with commits)**

```bash
git add fulltext_workflow/gap_ui.py fulltext_workflow/analysis/hotspot_brief.py
git commit -m "feat(ui): show nascent methods and demote mature hotspot transfers"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Blacklist + frequency maturity | Task 1 |
| `HOTSPOT_ESTABLISHED_MIN_PAPERS` | Task 1 |
| Filter established from `emerging_methods` | Task 2 |
| `active_methods` / 本周活跃 | Task 2 + 4 |
| Combo `method_maturity` + rank preference | Task 2 |
| Transferable dual pool + demotion + novelty | Task 3 |
| Report / brief copy | Task 2 report + Task 4 brief |
| UI columns / captions | Task 4 |
| Tests for LLM/SVM / demotion / regression | Tasks 1–3 |
| No Cartesian regression | Task 3 keeps existing tests |

## Self-review notes

- No TBD placeholders.
- `active_methods` is the canonical heat source for transferable so established can still enter after main-board filter.
- Score helpers live in `method_maturity.py` to keep `weekly_hotspot.py` from growing another ad-hoc constant block.
- `first_in_recent_window` bonus is optional in v1 (default `False`) to avoid extra SQL; formula still matches spec when enabled later.
