# Visualization Focus × Fangxin Dual-Pane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Gap UI Visualization tab into a focus-driven opportunity table (left) paired with read-only Fangxin landscape detail (right), with optional debate-gap overlay.

**Architecture:** Pure logic lives in `viz/gap_opportunity.py` (row build, sort, debate match, data tiers, summary metrics). Small Plotly helpers stay in `viz/gap_viz.py`. `gap_ui.render_gap_visualization_tab` becomes a thin Streamlit shell: load combo gaps + landscape cache, call pure builders, render summary / selectbox / detail / diagnostics expander.

**Tech Stack:** Python 3.12, Streamlit, pandas, plotly (optional fallback to dataframe), pytest, existing SQLite `pathology_landscape` + `tool_method_disease_combo_gap`.

## Global Constraints

- Visualization must work **without** Gap Debate when sidebar focus + KG + landscape cache exist.
- Debate report only **enhances** (mark/sort); never invent fake combo rows for unmatched titles.
- Visualization reads landscape **cache only** — no bootstrap / force-reload / live V1.1 fan-out.
- Empty focus → metrics zero + info; **do not** call unfiltered full-corpus combo scan.
- Data tiers: `high` (≥500) / `medium` (≥200) / `low` / `none` (unmapped or no cache) — same on left and right.
- Default filter: only `unexplored` / `minimal`; top-N default 30 (slider 10–50).
- Keep funnel/treemap under collapsed **Session diagnostics**; do not delete their builders.
- Working directory for pytest: repo root `d:\agent\prototype\build_kg_paper` with `fulltext_workflow` on path (existing test pattern).
- Commit design/plan under `docs/` may need `git add -f` (directory is gitignored).

## File Structure

| File | Role |
|------|------|
| `fulltext_workflow/viz/gap_opportunity.py` | **Create** — pure opportunity-row pipeline |
| `fulltext_workflow/tests/test_gap_opportunity.py` | **Create** — unit tests for pure logic |
| `fulltext_workflow/viz/gap_viz.py` | **Modify** — add subtype/molecular bar helpers |
| `fulltext_workflow/gap_ui.py` | **Modify** — rewrite `render_gap_visualization_tab` |
| `fulltext_workflow/gap_ui_guide.md` | **Modify** — §5.3 dual-pane docs |
| `fulltext_workflow/tests/test_gap_viz.py` | **Keep green** — no behavior change required |

---

### Task 1: Data tier + summary metrics

**Files:**
- Create: `fulltext_workflow/viz/gap_opportunity.py`
- Test: `fulltext_workflow/tests/test_gap_opportunity.py`

**Interfaces:**
- Consumes: none
- Produces:
  - `data_support_tier(cohort_size: int | None, *, mapped: bool) -> str`
  - `summarize_opportunities(rows: list[dict]) -> dict[str, int | float]` with keys `combo_count`, `scarce_count`, `mapped_count`, `high_share` (`high_share` is 0–100 float percent of rows with `data == "high"`, or 0 if empty)

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_gap_opportunity.py`:

```python
"""Unit tests for Visualization opportunity rows (no Streamlit / plotly)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from viz.gap_opportunity import data_support_tier, summarize_opportunities  # noqa: E402


def test_data_support_tier_boundaries():
    assert data_support_tier(None, mapped=False) == "none"
    assert data_support_tier(999, mapped=False) == "none"
    assert data_support_tier(None, mapped=True) == "none"
    assert data_support_tier(0, mapped=True) == "low"
    assert data_support_tier(199, mapped=True) == "low"
    assert data_support_tier(200, mapped=True) == "medium"
    assert data_support_tier(499, mapped=True) == "medium"
    assert data_support_tier(500, mapped=True) == "high"


def test_summarize_opportunities():
    rows = [
        {"gap": "unexplored", "disease_id": "A", "data": "high"},
        {"gap": "minimal", "disease_id": "B", "data": "low"},
        {"gap": "active", "disease_id": None, "data": "none"},
    ]
    s = summarize_opportunities(rows)
    assert s["combo_count"] == 3
    assert s["scarce_count"] == 2
    assert s["mapped_count"] == 2
    assert s["high_share"] == 100 * 1 / 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_opportunity.py::test_data_support_tier_boundaries fulltext_workflow/tests/test_gap_opportunity.py::test_summarize_opportunities -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `viz.gap_opportunity`.

- [ ] **Step 3: Write minimal implementation**

Create `fulltext_workflow/viz/gap_opportunity.py`:

```python
"""Pure helpers for Visualization opportunity table (focus gaps × Fangxin)."""
from __future__ import annotations

from typing import Any


def data_support_tier(cohort_size: int | None, *, mapped: bool) -> str:
    """Map cohort size to high/medium/low/none. Unmapped or missing cache → none."""
    if not mapped or cohort_size is None:
        return "none"
    n = int(cohort_size)
    if n >= 500:
        return "high"
    if n >= 200:
        return "medium"
    return "low"


def summarize_opportunities(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate metrics for the Visualization summary strip."""
    combo_count = len(rows)
    scarce_count = sum(1 for r in rows if r.get("gap") in ("unexplored", "minimal"))
    mapped_count = sum(1 for r in rows if r.get("disease_id"))
    high_n = sum(1 for r in rows if r.get("data") == "high")
    high_share = (100.0 * high_n / combo_count) if combo_count else 0.0
    return {
        "combo_count": combo_count,
        "scarce_count": scarce_count,
        "mapped_count": mapped_count,
        "high_share": high_share,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/viz/gap_opportunity.py fulltext_workflow/tests/test_gap_opportunity.py
git commit -m "feat(viz): add data tier and opportunity summary helpers"
```

---

### Task 2: Sort + build opportunity rows from combo gaps

**Files:**
- Modify: `fulltext_workflow/viz/gap_opportunity.py`
- Modify: `fulltext_workflow/tests/test_gap_opportunity.py`

**Interfaces:**
- Consumes: `data_support_tier`
- Produces:
  - `LIT_GAP_RANK: dict[str, int]` — `unexplored=0`, `minimal=1`, default 2
  - `DATA_RANK: dict[str, int]` — `high=0`, `medium=1`, `low=2`, `none=3`
  - `sort_opportunity_rows(rows: list[dict]) -> list[dict]` (stable key as spec §2)
  - `build_opportunity_rows(gaps: list[dict], disease_cases: dict[str, int], disease_id_by_name: dict[str, str | None], *, source_default: str = "Corpus") -> list[dict]`
  - Each row dict keys: `source`, `method`, `disease`, `gap`, `paper_cnt`, `disease_id`, `data`, `row_key` (`f"{method}||{disease}"`)

Mapping rule for `build_opportunity_rows`:
- Resolve `disease_id = disease_id_by_name.get(disease_name)` (caller precomputes via aliases / `map_gap_to_disease` offline).
- If `disease_id` is truthy and `disease_id in disease_cases`, `mapped=True` and `cohort_size=disease_cases[disease_id]`.
- Elif `disease_id` truthy but not in `disease_cases`: `mapped=False` for tier purposes → `data="none"` (no cache), still keep `disease_id` on the row for the right panel empty state.
- Else: `disease_id=None`, `data="none"`.

- [ ] **Step 1: Write the failing tests**

Append to `test_gap_opportunity.py`:

```python
from viz.gap_opportunity import build_opportunity_rows, sort_opportunity_rows  # noqa: E402


def test_sort_opportunity_rows_priority():
    rows = [
        {"source": "Corpus", "gap": "minimal", "data": "high", "paper_cnt": 0, "method": "B", "disease": "X"},
        {"source": "Debate", "gap": "unexplored", "data": "low", "paper_cnt": 5, "method": "A", "disease": "Y"},
        {"source": "Corpus", "gap": "unexplored", "data": "medium", "paper_cnt": 1, "method": "A", "disease": "Z"},
        {"source": "Corpus", "gap": "unexplored", "data": "medium", "paper_cnt": 0, "method": "A", "disease": "W"},
    ]
    ordered = sort_opportunity_rows(rows)
    assert [r["disease"] for r in ordered] == ["Y", "W", "Z", "X"]


def test_build_opportunity_rows_tiers_and_keys():
    gaps = [
        {"method": "CLAM", "disease": "NPC", "paper_cnt": 0, "gap": "unexplored"},
        {"method": "MIL", "disease": "UnknownCa", "paper_cnt": 1, "gap": "minimal"},
    ]
    cases = {"NPC-CODE": 600}
    ids = {"NPC": "NPC-CODE", "UnknownCa": None}
    rows = build_opportunity_rows(gaps, cases, ids)
    assert rows[0]["row_key"] == "CLAM||NPC"
    assert rows[0]["disease_id"] == "NPC-CODE"
    assert rows[0]["data"] == "high"
    assert rows[0]["source"] == "Corpus"
    assert rows[1]["disease_id"] is None
    assert rows[1]["data"] == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_opportunity.py::test_sort_opportunity_rows_priority fulltext_workflow/tests/test_gap_opportunity.py::test_build_opportunity_rows_tiers_and_keys -v
```

Expected: FAIL (functions not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `gap_opportunity.py`:

```python
LIT_GAP_RANK = {"unexplored": 0, "minimal": 1}
DATA_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}


def sort_opportunity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        return (
            0 if r.get("source") == "Debate" else 1,
            LIT_GAP_RANK.get(str(r.get("gap") or ""), 2),
            DATA_RANK.get(str(r.get("data") or "none"), 3),
            int(r.get("paper_cnt") or 0),
            str(r.get("method") or "").lower(),
            str(r.get("disease") or "").lower(),
        )

    return sorted(rows, key=key)


def build_opportunity_rows(
    gaps: list[dict[str, Any]],
    disease_cases: dict[str, int],
    disease_id_by_name: dict[str, str | None],
    *,
    source_default: str = "Corpus",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for g in gaps:
        method = str(g.get("method") or "")
        disease = str(g.get("disease") or "")
        did = disease_id_by_name.get(disease)
        if did and did in disease_cases:
            tier = data_support_tier(disease_cases[did], mapped=True)
        elif did:
            tier = data_support_tier(None, mapped=False)  # no cache
        else:
            did = None
            tier = data_support_tier(None, mapped=False)
        out.append({
            "source": source_default,
            "method": method,
            "disease": disease,
            "gap": g.get("gap") or "",
            "paper_cnt": int(g.get("paper_cnt") or 0),
            "disease_id": did,
            "data": tier,
            "row_key": f"{method}||{disease}",
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Same pytest command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/viz/gap_opportunity.py fulltext_workflow/tests/test_gap_opportunity.py
git commit -m "feat(viz): build and sort focus opportunity rows"
```

---

### Task 3: Debate gap overlay matching

**Files:**
- Modify: `fulltext_workflow/viz/gap_opportunity.py`
- Modify: `fulltext_workflow/tests/test_gap_opportunity.py`

**Interfaces:**
- Consumes: `meaningful_keyword_tokens` from `analysis.focus_filter`
- Produces:
  - `apply_debate_overlay(rows: list[dict], debate_titles: list[str]) -> tuple[list[dict], list[str]]`
  - Returns `(updated_rows, unmatched_titles)`.
  - A title matches a row if ≥1 meaningful token from the title appears in `(method + " " + disease).lower()`.
  - On match: set that row’s `source` to `"Debate"` (copy-on-write; do not mutate caller’s list items in place — replace with new dicts).
  - A title that matches ≥1 row is not unmatched; titles matching zero rows go to `unmatched_titles` (preserve order, unique).

- [ ] **Step 1: Write the failing tests**

```python
from viz.gap_opportunity import apply_debate_overlay  # noqa: E402


def test_apply_debate_overlay_marks_and_unmatched():
    rows = [
        {"source": "Corpus", "method": "CLAM", "disease": "nasopharyngeal carcinoma", "row_key": "a"},
        {"source": "Corpus", "method": "MIL", "disease": "CRC", "row_key": "b"},
    ]
    titles = [
        "CLAM for nasopharyngeal carcinoma survival",
        "Radiomics habitat imaging leftover",
    ]
    updated, unmatched = apply_debate_overlay(rows, titles)
    assert updated[0]["source"] == "Debate"
    assert updated[1]["source"] == "Corpus"
    assert unmatched == ["Radiomics habitat imaging leftover"]
    # originals untouched
    assert rows[0]["source"] == "Corpus"
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_opportunity.py::test_apply_debate_overlay_marks_and_unmatched -v
```

Expected: FAIL (function missing).

- [ ] **Step 3: Write minimal implementation**

```python
from analysis.focus_filter import meaningful_keyword_tokens


def apply_debate_overlay(
    rows: list[dict[str, Any]],
    debate_titles: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    matched_title_idxs: set[int] = set()
    debate_keys: set[str] = set()
    for i, title in enumerate(debate_titles):
        tokens = meaningful_keyword_tokens(title)
        if not tokens:
            continue
        for r in rows:
            hay = f"{r.get('method', '')} {r.get('disease', '')}".lower()
            if any(t in hay for t in tokens):
                debate_keys.add(str(r.get("row_key")))
                matched_title_idxs.add(i)
    updated = []
    for r in rows:
        nr = dict(r)
        if str(nr.get("row_key")) in debate_keys:
            nr["source"] = "Debate"
        updated.append(nr)
    unmatched = [
        t for i, t in enumerate(debate_titles)
        if i not in matched_title_idxs
    ]
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in unmatched:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return updated, uniq
```

Note: stopwords like `for` are already dropped by `meaningful_keyword_tokens`, so “CLAM for nasopharyngeal…” still matches via `clam` / `nasopharyngeal` / `carcinoma` / `survival`.

- [ ] **Step 4: Run test to verify it passes**

Same pytest as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/viz/gap_opportunity.py fulltext_workflow/tests/test_gap_opportunity.py
git commit -m "feat(viz): overlay debate gaps onto opportunity rows"
```

---

### Task 4: Filter + assemble opportunity bundle

**Files:**
- Modify: `fulltext_workflow/viz/gap_opportunity.py`
- Modify: `fulltext_workflow/tests/test_gap_opportunity.py`

**Interfaces:**
- Produces:
  - `filter_opportunity_rows(rows, *, scarce_only: bool, limit: int) -> list[dict]`
  - `assemble_opportunity_view(*, gaps, disease_cases, disease_id_by_name, debate_titles, scarce_only=True, limit=30) -> dict` with keys:
    - `rows` (sorted + filtered)
    - `summary` (from **filtered** rows)
    - `unmatched_debate` (list[str])
    - `debate_matched_count` (int count of filtered rows with `source==Debate`)

- [ ] **Step 1: Write the failing test**

```python
from viz.gap_opportunity import assemble_opportunity_view  # noqa: E402


def test_assemble_opportunity_view_filters_and_debate():
    gaps = [
        {"method": "CLAM", "disease": "NPC", "paper_cnt": 0, "gap": "unexplored"},
        {"method": "MIL", "disease": "NPC", "paper_cnt": 5, "gap": "active"},
        {"method": "TransMIL", "disease": "CRC", "paper_cnt": 1, "gap": "minimal"},
    ]
    bundle = assemble_opportunity_view(
        gaps=gaps,
        disease_cases={"NPC-1": 500},
        disease_id_by_name={"NPC": "NPC-1", "CRC": None},
        debate_titles=["CLAM NPC survival"],
        scarce_only=True,
        limit=30,
    )
    assert len(bundle["rows"]) == 2  # active filtered out
    assert bundle["rows"][0]["source"] == "Debate"
    assert bundle["debate_matched_count"] == 1
    assert bundle["summary"]["combo_count"] == 2
    assert bundle["unmatched_debate"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_opportunity.py::test_assemble_opportunity_view_filters_and_debate -v
```

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def filter_opportunity_rows(
    rows: list[dict[str, Any]],
    *,
    scarce_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    out = rows
    if scarce_only:
        out = [r for r in out if r.get("gap") in ("unexplored", "minimal")]
    return out[: max(0, int(limit))]


def assemble_opportunity_view(
    *,
    gaps: list[dict[str, Any]],
    disease_cases: dict[str, int],
    disease_id_by_name: dict[str, str | None],
    debate_titles: list[str] | None = None,
    scarce_only: bool = True,
    limit: int = 30,
) -> dict[str, Any]:
    rows = build_opportunity_rows(gaps, disease_cases, disease_id_by_name)
    unmatched: list[str] = []
    if debate_titles:
        rows, unmatched = apply_debate_overlay(rows, debate_titles)
    rows = sort_opportunity_rows(rows)
    rows = filter_opportunity_rows(rows, scarce_only=scarce_only, limit=limit)
    return {
        "rows": rows,
        "summary": summarize_opportunities(rows),
        "unmatched_debate": unmatched,
        "debate_matched_count": sum(1 for r in rows if r.get("source") == "Debate"),
    }
```

- [ ] **Step 4: Run full opportunity test file**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_opportunity.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/viz/gap_opportunity.py fulltext_workflow/tests/test_gap_opportunity.py
git commit -m "feat(viz): assemble filtered opportunity view bundle"
```

---

### Task 5: Plotly helpers for subtype / molecular bars

**Files:**
- Modify: `fulltext_workflow/viz/gap_viz.py` (append near end, before or after `build_gap_viz_bundle`)
- Test: extend `fulltext_workflow/tests/test_gap_viz.py` with no-plotly-safe smoke (functions return `None` when `HAS_PLOTLY` is false — already the module pattern)

**Interfaces:**
- Produces:
  - `build_subtype_bar(distribution: list[dict], *, top_n: int = 8) -> Any | None`
  - `build_molecular_bar(positivity: list[dict], *, top_n: int = 8) -> Any | None`
  - Subtype rows use `subtype_name_zh` (fallback `name`) and `patient_count` (fallback `count`).
  - Molecular rows use `marker` / `name` and `positivity_rate` / `rate` / `patient_count` (first numeric found).
  - Empty input or no plotly → `None`.

- [ ] **Step 1: Write the failing tests**

Append to `test_gap_viz.py`:

```python
from viz.gap_viz import build_molecular_bar, build_subtype_bar  # noqa: E402


def test_subtype_bar_empty_returns_none():
    assert build_subtype_bar([]) is None


def test_molecular_bar_empty_returns_none():
    assert build_molecular_bar([]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_viz.py::test_subtype_bar_empty_returns_none fulltext_workflow/tests/test_gap_viz.py::test_molecular_bar_empty_returns_none -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Write minimal implementation**

Append to `gap_viz.py`:

```python
def build_subtype_bar(distribution: list[dict], *, top_n: int = 8) -> Any:
    if not HAS_PLOTLY or not distribution:
        return None
    rows = []
    for item in distribution:
        name = item.get("subtype_name_zh") or item.get("name") or "?"
        count = item.get("patient_count", item.get("count", 0)) or 0
        rows.append({"label": str(name), "count": int(count)})
    rows = sorted(rows, key=lambda r: -r["count"])[:top_n]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="count", y="label", orientation="h", title="Subtype distribution (top)")
    fig.update_layout(height=max(280, 28 * len(rows) + 80), yaxis=dict(autorange="reversed"), margin=dict(l=120, r=20, t=50, b=40))
    return fig


def build_molecular_bar(positivity: list[dict], *, top_n: int = 8) -> Any:
    if not HAS_PLOTLY or not positivity:
        return None
    rows = []
    for item in positivity:
        name = item.get("marker") or item.get("name") or "?"
        val = item.get("positivity_rate", item.get("rate", item.get("patient_count", 0))) or 0
        rows.append({"label": str(name), "value": float(val)})
    rows = sorted(rows, key=lambda r: -r["value"])[:top_n]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="value", y="label", orientation="h", title="Molecular positivity (top)")
    fig.update_layout(height=max(280, 28 * len(rows) + 80), yaxis=dict(autorange="reversed"), margin=dict(l=120, r=20, t=50, b=40))
    return fig
```

- [ ] **Step 4: Run tests**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_viz.py -v
```

Expected: all PASS (including existing funnel tests).

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/viz/gap_viz.py fulltext_workflow/tests/test_gap_viz.py
git commit -m "feat(viz): add subtype and molecular bar chart helpers"
```

---

### Task 6: Rewrite Visualization tab UI

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` — replace body of `render_gap_visualization_tab` (currently ~1142–1229)

**Interfaces:**
- Consumes: `assemble_opportunity_view`, `parse_gap_titles`, `map_gap_to_disease`, `get_all_landscape`, `tool_method_disease_combo_gap`, `build_debate_funnel_figure`, `build_tool_treemap`, `debate_funnel_stats`, `tool_category_stats`, `build_subtype_bar`, `build_molecular_bar`, `plotly_available`
- Produces: updated Streamlit UI only (no new public Python API)

**UI behavior (exact):**

1. Subheader: `Focus Gaps × Fangxin Support`; caption explaining left/right + debate optional.
2. If no focus (`normalize_focus(focus_hint)` is None): info “Set a Research focus in the sidebar.”; still show empty metrics (0); **do not** call `tool_method_disease_combo_gap`.
3. Controls: checkbox `Show all coverage levels` (default False); slider `Top N` 10–50 default 30.
4. Load landscape once into `disease_cases: dict[str,int]` from `payload.catalog.total_cases` (fallback 0) and build `disease_id_by_name` by mapping each distinct combo disease via `map_gap_to_disease(disease_name, known_diseases=list(catalog_names), client=None)` — **no live API client** in this tab.
5. Call `assemble_opportunity_view(...)` with debate titles from `parse_gap_titles(report_text)` when `report_text` non-empty.
6. Summary metrics row (4 columns): Combo count, Lit scarce, Mapped Fangxin, High data %.
7. Two columns:
   - Left: `st.dataframe` of display columns; `st.selectbox` of `row_key` labels (`{source} · {method} · {disease}`); persist `st.session_state["viz_selected_combo"]`; if current key not in options, reset to first.
   - Show caption for `debate_matched_count`; if `unmatched_debate`, `st.info` listing them.
   - Right: lookup landscape by selected `disease_id`; render header + 4 metrics + subtype/molecular charts or dataframe fallback; empty states per spec.
8. Expander `Session diagnostics` (default collapsed): existing funnel + treemap from `events` (reuse previous chart code paths). Heatmap/scatter optional omit (spec replaces them as primary view).

Helper inside `gap_ui.py` (local functions ok):

```python
def _landscape_indexes() -> tuple[dict[str, int], dict[str, dict], list[str]]:
    cases: dict[str, int] = {}
    by_id: dict[str, dict] = {}
    names: list[str] = []
    for row in get_all_landscape():
        did = row["disease_id"]
        payload = row.get("payload") or {}
        cat = payload.get("catalog") or {}
        cases[did] = int(cat.get("total_cases") or 0)
        by_id[did] = {**payload, "updated_at": row.get("updated_at")}
        for n in (cat.get("name_en"), cat.get("name_zh"), did):
            if n:
                names.append(str(n))
    return cases, by_id, names
```

Wrap combo fetch in try/except → `st.warning` + empty gaps.

- [ ] **Step 1: Implement rewrite of `render_gap_visualization_tab`**

Replace the function body according to the behavior above. Keep the function signature:

```python
def render_gap_visualization_tab(
    events: list[dict],
    *,
    report_text: str = "",
    focus_hint: str = "",
) -> None:
```

Import new symbols at top of `gap_ui.py`:

```python
from viz.gap_opportunity import assemble_opportunity_view
from viz.gap_viz import (
    ...,
    build_subtype_bar,
    build_molecular_bar,
)
from feasibility.disease_mapper import map_gap_to_disease
from pipeline_utils import parse_gap_titles  # if not already imported
```

(Check existing imports first; reuse rather than duplicate.)

- [ ] **Step 2: Smoke-check imports**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'd:\agent\prototype\build_kg_paper\fulltext_workflow'); import gap_ui; print('ok', hasattr(gap_ui, 'render_gap_visualization_tab'))"
```

Expected: `ok True` (may print Streamlit warnings; exit code 0).

- [ ] **Step 3: Run unit tests**

```powershell
d:\agent\prototype\build_kg_paper\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_gap_opportunity.py fulltext_workflow/tests/test_gap_viz.py -v
```

Expected: all PASS.

- [ ] **Step 4: Manual UI check (operator)**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\..\.venv\Scripts\streamlit.exe run gap_ui.py
```

Checklist:
- No focus → info, no crash
- Focus with KG → left table fills
- Select row with landscape → right metrics + bars
- After debate → Debate rows on top

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/gap_ui.py
git commit -m "feat(ui): dual-pane Visualization for focus gaps and Fangxin"
```

---

### Task 7: Update gap UI guide

**Files:**
- Modify: `fulltext_workflow/gap_ui_guide.md` §5.3 (around lines 180–191)

- [ ] **Step 1: Replace §5.3 content**

Replace the Visualization subsection with:

```markdown
### 5.3 Visualization

Focus 下的 **空白机会 × 方信对照**（不强制先辩论）：

| 区域 | 含义 |
|------|------|
| Summary | 组合数 / 文献稀缺数 / 已映射方信病种 / 高数据支持占比 |
| Left · Opportunity table | method×disease 空白行；可点选；辩论命中行标 `Debate` 并置顶 |
| Right · Fangxin detail | 选中病种的 landscape 缓存：病例规模、亚型、分子（只读，不在此 bootstrap） |
| Session diagnostics | 折叠区：辩论漏斗 + 工具 treemap |

默认只显示 `unexplored` / `minimal`；勾选 Show all coverage levels 看全部。无 focus 不扫全库。无 landscape 时请到 **Data Feasibility → Bootstrap Landscape**。
```

Also update the FAQ table row that says “看辩论漏斗/热力图 | Visualization” to “看 focus 空白 × 方信对照 | Visualization”.

- [ ] **Step 2: Commit**

```powershell
git add fulltext_workflow/gap_ui_guide.md
git commit -m "docs: describe Visualization dual-pane in gap UI guide"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Independent of debate | Task 6 (focus path) + Task 4 assemble |
| Debate overlay / prioritize | Task 3 + Task 6 |
| Summary strip | Task 1 + Task 6 |
| Left table columns/sort/filter | Task 2–4 + Task 6 |
| Right landscape read-only | Task 6 |
| Subtype/molecular charts | Task 5 + Task 6 |
| Session diagnostics | Task 6 |
| Empty focus no full scan | Task 6 |
| Tests for sort/match/tiers/summary | Tasks 1–4 |
| Guide update | Task 7 |

## Self-review notes

- No TBD placeholders in steps.
- `assemble_opportunity_view` is the single entry later tasks/UI depend on.
- `high_share` is percent float 0–100 (displayed with `:.0f` in UI).
- Disease mapping in UI uses `client=None` to stay offline; Fangxin aliases in `map_gap_to_disease` still apply.
