# Visualization Transferable Opportunities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Visualization tab primary table use task-bridged transferable candidates (same semantics as Weekly Hotspot), keep Fangxin detail, and demote method×disease combo gaps to a non-opportunity diagnostic expander.

**Architecture:** Extend pure helpers in `viz/gap_opportunity.py` to normalize transferable row fields (`literature_gap` → `gap`, bridge/score passthrough) and sort by `opportunity_score`. Rewire `render_gap_visualization_tab` to call `compute_emerging_gap_opportunities` for the main table; call `tool_method_disease_combo_gap` only inside a collapsed coverage diagnostic that does not drive Fangxin selection.

**Tech Stack:** Python 3, Streamlit (`gap_ui.py`), pytest, existing `analysis/weekly_hotspot.py` + `analysis/gap_tools.py`.

## Global Constraints

- Do **not** change `compute_emerging_gap_opportunities` algorithm.
- Do **not** delete `method_disease_combo_gap` or debate-side usage.
- Main table must **never** fall back to cartesian combo rows when transferable list is empty.
- Share hotspot window default via `config.HOTSPOT_WINDOW_DAYS` (or `_load_weekly_hotspot_payload`) so viz and weekly tab do not drift.
- Chinese UI copy: title「可迁移候选 × 方信支撑」; coverage expander caption must state 覆盖空洞 ≠ 研究方向.
- Spec: `docs/superpowers/specs/2026-07-30-viz-transferable-opportunities-design.md`.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/viz/gap_opportunity.py` | Normalize transferable/combo input shapes; build/sort/filter/summarize opportunity rows for viz |
| `fulltext_workflow/tests/test_gap_opportunity.py` | Unit tests for row mapping, score sort, no-combo-fallback helper |
| `fulltext_workflow/gap_ui.py` | `render_gap_visualization_tab` UI: source swap, columns, Fangxin bridge caption, coverage expander |
| `fulltext_workflow/gap_ui_guide.md` | §5.3 Visualization one-section sync |

---

### Task 1: Transferable row model in `gap_opportunity.py`

**Files:**
- Modify: `fulltext_workflow/viz/gap_opportunity.py`
- Test: `fulltext_workflow/tests/test_gap_opportunity.py`

**Interfaces:**
- Consumes: transferable dicts from `compute_emerging_gap_opportunities` with keys `method`, `disease`, `literature_gap`, `literature_paper_cnt`, `bridge_task`, `bridge_mode`, `bridge_quality`, `support_diseases`, `opportunity_score` (plus optional legacy combo keys `gap`, `paper_cnt`).
- Produces:
  - `normalize_opportunity_gap(g: dict[str, Any]) -> dict[str, Any]` — returns a gap dict suitable for `build_opportunity_rows` with unified `gap` / `paper_cnt` plus bridge fields preserved.
  - `build_opportunity_rows(...)` — each output row includes at least: `source`, `method`, `disease`, `gap`, `paper_cnt`, `bridge_task`, `bridge_mode`, `bridge_quality`, `support_diseases`, `opportunity_score`, `disease_id`, `data`, `row_key`.
  - `sort_opportunity_rows(rows)` — key order: Debate first, then **descending** `opportunity_score`, then lit-gap rank, data rank, paper_cnt, method, disease.
  - `primary_viz_gaps(focus: str | None, *, opportunities: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]` — if `focus` falsy return `[]`; if `opportunities` is provided use it; else call `compute_emerging_gap_opportunities(focus=focus)`. **Never** calls combo gap.

- [ ] **Step 1: Write the failing tests**

Append to `fulltext_workflow/tests/test_gap_opportunity.py`:

```python
from viz.gap_opportunity import (  # extend existing import
    normalize_opportunity_gap,
    primary_viz_gaps,
)


def test_normalize_opportunity_gap_maps_transferable_fields():
    g = normalize_opportunity_gap({
        "method": "clam",
        "disease": "npc",
        "literature_gap": "unexplored",
        "literature_paper_cnt": 0,
        "bridge_task": "survival prediction",
        "bridge_mode": "same_paper",
        "bridge_quality": "ok",
        "support_diseases": "crc, brca",
        "opportunity_score": 12.5,
    })
    assert g["gap"] == "unexplored"
    assert g["paper_cnt"] == 0
    assert g["bridge_task"] == "survival prediction"
    assert g["opportunity_score"] == 12.5


def test_build_opportunity_rows_keeps_bridge_columns():
    gaps = [
        normalize_opportunity_gap({
            "method": "CLAM",
            "disease": "NPC",
            "literature_gap": "unexplored",
            "literature_paper_cnt": 0,
            "bridge_task": "survival prediction",
            "bridge_mode": "cross_paper",
            "bridge_quality": "ok",
            "support_diseases": "crc",
            "opportunity_score": 9.0,
        })
    ]
    rows = build_opportunity_rows(gaps, {"NPC-CODE": 600}, {"NPC": "NPC-CODE"})
    assert rows[0]["bridge_task"] == "survival prediction"
    assert rows[0]["bridge_mode"] == "cross_paper"
    assert rows[0]["opportunity_score"] == 9.0
    assert rows[0]["data"] == "high"


def test_sort_opportunity_rows_prefers_opportunity_score():
    rows = [
        {
            "source": "Corpus",
            "gap": "unexplored",
            "data": "high",
            "paper_cnt": 0,
            "method": "B",
            "disease": "X",
            "opportunity_score": 1.0,
        },
        {
            "source": "Corpus",
            "gap": "unexplored",
            "data": "low",
            "paper_cnt": 0,
            "method": "A",
            "disease": "Y",
            "opportunity_score": 10.0,
        },
        {
            "source": "Debate",
            "gap": "minimal",
            "data": "none",
            "paper_cnt": 1,
            "method": "C",
            "disease": "Z",
            "opportunity_score": 2.0,
        },
    ]
    ordered = sort_opportunity_rows(rows)
    assert [r["disease"] for r in ordered] == ["Z", "Y", "X"]


def test_primary_viz_gaps_empty_focus_and_no_combo_fallback(monkeypatch):
    assert primary_viz_gaps(None) == []
    assert primary_viz_gaps("") == []

    called = {"combo": 0, "transfer": 0}

    def fake_transfer(**kwargs):
        called["transfer"] += 1
        return []

    def fake_combo(**kwargs):
        called["combo"] += 1
        return {"gaps": [{"method": "x", "disease": "y", "gap": "unexplored", "paper_cnt": 0}]}

    monkeypatch.setattr(
        "analysis.weekly_hotspot.compute_emerging_gap_opportunities",
        fake_transfer,
    )
    # If implementation imports combo at module level, also patch that path to prove unused:
    monkeypatch.setattr(
        "analysis.gap_tools.tool_method_disease_combo_gap",
        fake_combo,
        raising=False,
    )
    out = primary_viz_gaps("nasopharyngeal carcinoma")
    assert out == []
    assert called["transfer"] == 1
    assert called["combo"] == 0


def test_primary_viz_gaps_uses_injected_list():
    rows = [{"method": "a", "disease": "b", "literature_gap": "minimal", "literature_paper_cnt": 1}]
    assert primary_viz_gaps("focus", opportunities=rows) is rows
```

Update existing `test_sort_opportunity_rows_priority` expectations: after score-aware sort, rows without `opportunity_score` treat missing as `0`. Recompute expected order for the old fixture (all scores 0) so Debate/`unexplored`/lower `paper_cnt` still win — keep the old assert if still valid under `(Debate, -score, lit, data, paper_cnt, …)`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd fulltext_workflow
py -m pytest tests/test_gap_opportunity.py::test_normalize_opportunity_gap_maps_transferable_fields tests/test_gap_opportunity.py::test_build_opportunity_rows_keeps_bridge_columns tests/test_gap_opportunity.py::test_sort_opportunity_rows_prefers_opportunity_score tests/test_gap_opportunity.py::test_primary_viz_gaps_empty_focus_and_no_combo_fallback tests/test_gap_opportunity.py::test_primary_viz_gaps_uses_injected_list -v
```

Expected: FAIL (`normalize_opportunity_gap` / `primary_viz_gaps` ImportError or AttributeError).

- [ ] **Step 3: Implement minimal helpers**

In `fulltext_workflow/viz/gap_opportunity.py`:

```python
def normalize_opportunity_gap(g: dict[str, Any]) -> dict[str, Any]:
    """Unify transferable + legacy combo shapes for build_opportunity_rows."""
    out = dict(g)
    if not out.get("gap"):
        out["gap"] = out.get("literature_gap") or ""
    if "paper_cnt" not in out or out.get("paper_cnt") is None:
        out["paper_cnt"] = int(out.get("literature_paper_cnt") or 0)
    else:
        out["paper_cnt"] = int(out.get("paper_cnt") or 0)
    # ensure bridge fields exist (default empty / 0.0)
    out.setdefault("bridge_task", "")
    out.setdefault("bridge_mode", "")
    out.setdefault("bridge_quality", "")
    out.setdefault("support_diseases", "")
    if out.get("support_diseases") is not None and not isinstance(out["support_diseases"], str):
        out["support_diseases"] = ", ".join(str(x) for x in out["support_diseases"])
    out["opportunity_score"] = float(out.get("opportunity_score") or 0.0)
    return out


def sort_opportunity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        return (
            0 if r.get("source") == "Debate" else 1,
            -float(r.get("opportunity_score") or 0.0),
            LIT_GAP_RANK.get(str(r.get("gap") or ""), 2),
            DATA_RANK.get(str(r.get("data") or "none"), 3),
            int(r.get("paper_cnt") or 0),
            str(r.get("method") or "").lower(),
            str(r.get("disease") or "").lower(),
        )
    return sorted(rows, key=key)


def build_opportunity_rows(...):  # existing signature
    ...
    g = normalize_opportunity_gap(g)  # or normalize before reading fields
    out.append({
        "source": source_default,
        "method": method,
        "disease": disease,
        "gap": g.get("gap") or "",
        "paper_cnt": int(g.get("paper_cnt") or 0),
        "bridge_task": g.get("bridge_task") or "",
        "bridge_mode": g.get("bridge_mode") or "",
        "bridge_quality": g.get("bridge_quality") or "",
        "support_diseases": g.get("support_diseases") or "",
        "opportunity_score": float(g.get("opportunity_score") or 0.0),
        "gap_kind": g.get("gap_kind") or "applied",
        "covers_disease_paper_cnt": int(g.get("covers_disease_paper_cnt") or 0),
        "surveys_method_paper_cnt": int(g.get("surveys_method_paper_cnt") or 0),
        "disease_id": did,
        "data": tier,
        "row_key": f"{method}||{disease}",
    })


def primary_viz_gaps(
    focus: str | None,
    *,
    opportunities: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Main-table source only. Never falls back to method_disease_combo_gap."""
    if not (focus or "").strip():
        return []
    if opportunities is not None:
        return opportunities
    from analysis.weekly_hotspot import compute_emerging_gap_opportunities
    return list(compute_emerging_gap_opportunities(focus=focus))


def assemble_opportunity_view(...):
    gaps = [normalize_opportunity_gap(g) for g in gaps]
    ...
```

Keep `summarize_opportunities` key `combo_count` (UI label becomes 候选数 later).

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
cd fulltext_workflow
py -m pytest tests/test_gap_opportunity.py -v
```

Expected: all PASS (including updated sort test).

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/viz/gap_opportunity.py fulltext_workflow/tests/test_gap_opportunity.py
git commit -m "feat(viz): normalize transferable opportunity rows for visualization"
```

---

### Task 2: Rewire `render_gap_visualization_tab`

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_gap_visualization_tab`, ~1352–1568)
- Test: manual checklist below + reuse Task 1 unit tests (no Streamlit test harness required)

**Interfaces:**
- Consumes: `primary_viz_gaps`, `assemble_opportunity_view`, `normalize_focus`, `map_gap_to_disease`, `_load_weekly_hotspot_payload` / `config.HOTSPOT_WINDOW_DAYS`, `tool_method_disease_combo_gap` (diagnostic only).
- Produces: updated Visualization tab UI behavior per spec.

- [ ] **Step 1: Swap main data source and copy**

In `render_gap_visualization_tab`:

1. Change subheader to `可迁移候选 × 方信支撑`.
2. Caption: explain ok Task bridge; empty better than false positives.
3. Remove checkbox `viz_show_all_coverage`.
4. Keep Top N slider.
5. Replace:

```python
gaps = list(tool_method_disease_combo_gap(focus=focus).get("gaps") or [])
```

with:

```python
from viz.gap_opportunity import primary_viz_gaps  # top-level import preferred

# Prefer shared weekly cache when available:
payload = _load_weekly_hotspot_payload(
    0,  # or list_weekly weeks version; simplest: use cache key consistent with hotspot tab
    int(getattr(config, "HOTSPOT_WINDOW_DAYS", 14)),
)
raw = payload.get("emerging_gap_opportunities") or []
# Recompute with focus so disease focus expands candidates:
gaps = primary_viz_gaps(
    focus,
    opportunities=None,  # always compute with focus for correctness
)
# Simpler correct path (recommended in implementation):
gaps = primary_viz_gaps(focus)  # calls compute_emerging_gap_opportunities(focus=focus)
```

**Implement the simpler correct path:** `gaps = primary_viz_gaps(focus)` (focus-aware). Do not pass unfocused weekly list as opportunities.

6. Empty states:
   - `focus is None` → existing「请在侧栏设置研究焦点」
   - `focus` set, `not gaps` → `st.info("该焦点下无可迁移候选（需升温方法×稀疏组合且存在 ok Task 桥）。")` — **do not** load combo into `gaps`.

7. Call `assemble_opportunity_view(..., scarce_only=True, limit=top_n)` always.

8. Metrics: `m1.metric("候选数", ...)`.

9. Display columns for dataframe:

```python
{
    "来源": r.get("source") or "",
    "方法": r.get("method") or "",
    "疾病": r.get("disease") or "",
    "桥接任务": r.get("bridge_task") or "",
    "桥接模式": r.get("bridge_mode") or "",
    "文献空白": r.get("gap") or "",
    "论文数": int(r.get("paper_cnt") or 0),
    "支持病种": r.get("support_diseases") or "",
    "得分": r.get("opportunity_score") or 0,
    "方信": r.get("disease_id") or "—",
    "数据": r.get("data") or "none",
}
```

10. Fangxin right pane: after disease title markdown, add:

```python
st.caption(
    f"桥接：{selected.get('bridge_task') or '—'} · "
    f"{selected.get('bridge_mode') or '—'} · "
    f"得分 {selected.get('opportunity_score') or 0}"
)
```

- [ ] **Step 2: Add coverage diagnostic expander (before session diagnostics)**

```python
with st.expander("覆盖诊断（非机会）", expanded=False):
    st.caption("方法×疾病覆盖空洞 ≠ 研究方向；不驱动右侧方信选中态。")
    if focus is None:
        st.info("设置焦点后可查看覆盖诊断。")
    else:
        try:
            diag = list(tool_method_disease_combo_gap(focus=focus).get("gaps") or [])
        except Exception as exc:
            st.warning(f"覆盖诊断不可用：{exc}")
            diag = []
        scarce = [g for g in diag if g.get("gap") in ("unexplored", "minimal")][:20]
        if scarce:
            safe_table(pd.DataFrame([
                {
                    "方法": g.get("method"),
                    "疾病": g.get("disease"),
                    "论文数": g.get("paper_cnt"),
                    "gap": g.get("gap"),
                }
                for g in scarce
            ]))
        else:
            st.info("该焦点下无稀缺覆盖空洞。")
```

Keep「会话诊断」expander after this; unchanged funnel/treemap.

- [ ] **Step 3: Fix imports**

- Add `from viz.gap_opportunity import assemble_opportunity_view, primary_viz_gaps` (keep `assemble_opportunity_view` if already imported).
- Keep `tool_method_disease_combo_gap` import for diagnostic only.

- [ ] **Step 4: Smoke-check helpers still pass**

```powershell
cd fulltext_workflow
py -m pytest tests/test_gap_opportunity.py -v
```

Expected: PASS.

Manual UI checklist (when Streamlit available):

1. No focus → hint; main table empty.
2. Focus with no bridges → transferable empty message; opening coverage expander may still show combo holes; Fangxin stays empty/unselected from diagnostic.
3. Focus with candidates → bridge columns visible; selecting row shows Fangxin + bridge caption.

- [ ] **Step 5: Commit**

```powershell
git add fulltext_workflow/gap_ui.py
git commit -m "feat(ui): drive visualization from transferable candidates"
```

---

### Task 3: Guide sync

**Files:**
- Modify: `fulltext_workflow/gap_ui_guide.md` (overview table ~L17, §5.3 ~L178–189, quick ref ~L367)

**Interfaces:**
- Consumes: Task 2 UI behavior.
- Produces: docs aligned with transferable × Fangxin.

- [ ] **Step 1: Update guide copy**

Replace Visualization blurbs:

- Overview table: `Plotly：辩论漏斗、工具 treemap、可迁移候选×方信、覆盖诊断`
- §5.3 title narrative: **可迁移候选 × 方信对照**（需 ok Task 桥；非笛卡尔覆盖空洞）
- Summary: 候选数 / 文献稀缺 / 已映射方信 / 高数据占比
- Left: transferable rows with `bridge_task` / `bridge_mode` / `opportunity_score`
- Add row for Coverage diagnostic expander
- Remove「Show all coverage levels」
- Quick ref: `看 focus 可迁移候选 × 方信对照 | Visualization`

- [ ] **Step 2: Commit**

```powershell
git add fulltext_workflow/gap_ui_guide.md
git commit -m "docs(ui): align visualization guide with transferable candidates"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Main table from transferable | Task 2 |
| Fangxin + bridge summary | Task 2 |
| Combo demoted to diagnostic | Task 2 |
| No cartesian fallback | Task 1 `primary_viz_gaps` + Task 2 empty state |
| Row fields / sort by score | Task 1 |
| Guide sync | Task 3 |
| No algorithm / tool deletion | Global constraints |

## Placeholder scan

None intentional; window sharing uses focus-aware `compute_emerging_gap_opportunities` directly (correctness over cache reuse).
