# Weekly New Methods Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent `new_methods` board (nascent only, fixed `min_recent=1`, no `HOTSPOT_TOP_N` cut) and show it at the top of the Gap UI「方法」tab so users can scan this week’s new methods without fighting the heat leaderboard.

**Architecture:** Reuse `compute_emerging_entities("Method", …)` with `min_recent=1` and `limit=HOTSPOT_NEW_METHODS_MAX`, then annotate maturity/role and keep only `method_maturity == "nascent"`. Emit `new_methods` from `compute_weekly_hotspots` without changing `emerging_methods` / `active_methods` ranking. UI renders the table above the existing role-partitioned 新苗头 board; markdown report gets a short section before Emerging Methods.

**Tech Stack:** Python 3, SQLite (`db.schema`), pytest, Streamlit (`gap_ui.py`).

**Spec:** `docs/superpowers/specs/2026-09-07-weekly-new-methods-board-design.md`

## Global Constraints

- 「新」= existing `nascent` tier only (not blacklist; `corpus_paper_cnt ≤ 2`).
- `new_methods` always uses **`min_recent=1`**, independent of sidebar / `compute_weekly_hotspots(..., min_recent=…)`.
- Do **not** apply `HOTSPOT_TOP_N` to `new_methods`; use `HOTSPOT_NEW_METHODS_MAX` (default **500**) as safety cap only.
- Do **not** change `emerging_score`, `emerging_methods` filter, or WoW snapshot boards (do not add a `new_method` snapshot board in v1).
- Do not change extract coverage / transferable gaps / method families.
- Run pytest from `fulltext_workflow/` (existing `sys.path` pattern in tests).
- Commit only when the user explicitly asks; otherwise leave the tree dirty and note a suggested commit message.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/config.py` | `HOTSPOT_NEW_METHODS_MAX` (env, default 500) |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Build `new_methods`; include in payload; report section |
| `fulltext_workflow/gap_ui.py` | 「方法」tab top block for 本周新方法 |
| `fulltext_workflow/tests/test_weekly_hotspot_new_methods.py` | **New** — selection, independence from Top-N/min_recent, sort, report |
| `fulltext_workflow/tests/test_weekly_hotspot_maturity.py` | Regression only (run, no required edits) |

---

### Task 1: Config + failing selection tests

**Files:**
- Modify: `fulltext_workflow/config.py` (near other `HOTSPOT_*`)
- Create: `fulltext_workflow/tests/test_weekly_hotspot_new_methods.py`

**Interfaces:**
- Produces (config): `HOTSPOT_NEW_METHODS_MAX: int` default `500`
- Consumes later: `compute_weekly_hotspots(...) -> dict` with key `new_methods: list[dict]`

- [ ] **Step 1: Add config constant**

In `fulltext_workflow/config.py`, immediately after `HOTSPOT_TOP_N`:

```python
HOTSPOT_NEW_METHODS_MAX: int = int(os.getenv("HOTSPOT_NEW_METHODS_MAX", "500"))
```

- [ ] **Step 2: Write failing tests**

Create `fulltext_workflow/tests/test_weekly_hotspot_new_methods.py`:

```python
"""Independent 本周新方法 board (nascent, min_recent=1, no Top-N)."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.weekly_hotspot import (  # noqa: E402
    compute_weekly_hotspots,
    generate_hotspot_report,
)
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
    monkeypatch.setattr(config, "HOTSPOT_ESTABLISHED_MIN_PAPERS", 10)
    monkeypatch.setattr(config, "HOTSPOT_TOP_N", 2)
    monkeypatch.setattr(config, "HOTSPOT_NEW_METHODS_MAX", 500)
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


def _edge(pmid: str, paper_id: int, name: str) -> None:
    entity_id = upsert_entity(name, "Method")
    insert_relation(
        "Paper",
        paper_id,
        "APPLIES_METHOD",
        "Method",
        entity_id,
        source_pmid=pmid,
        status="active",
    )


def test_nascent_in_new_methods_established_and_emerging_out(monkeypatch):
    _tmp_db(monkeypatch)
    # nascent: 1 recent paper
    p_new = _paper("new-1", 2)
    _edge("new-1", p_new, "brand-new-niche-method")

    # established blacklist
    p_llm = _paper("llm-1", 2)
    _edge("llm-1", p_llm, "large language model")

    # emerging: 5 corpus papers, 1 in recent window (others older than window)
    for i in range(4):
        pmid = f"em-old-{i}"
        pid = _paper(pmid, 40 + i)
        _edge(pmid, pid, "mid-frequency-method")
    p_em = _paper("em-recent", 3)
    _edge("em-recent", p_em, "mid-frequency-method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=2)
    names = {r["name"] for r in payload["new_methods"]}
    assert "brand-new-niche-method" in names
    assert "large language model" not in names
    assert "mid-frequency-method" not in names
    row = next(r for r in payload["new_methods"] if r["name"] == "brand-new-niche-method")
    assert row["method_maturity"] == "nascent"
    assert int(row["recent_cnt"]) == 1


def test_new_methods_ignores_sidebar_min_recent_and_top_n(monkeypatch):
    _tmp_db(monkeypatch)
    # Fill heat board with two count=2 established-ish high scorers
    for name, base in (("heat-a", 10), ("heat-b", 20)):
        for j in range(2):
            pmid = f"{name}-{j}"
            pid = _paper(pmid, 2 + j)
            _edge(pmid, pid, name)

    # Single-paper nascent — filtered from emerging when min_recent=2 / Top-N=2
    p = _paper("solo-nascent", 2)
    _edge("solo-nascent", p, "solo-nascent-method")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=2)
    emerging = {r["name"] for r in payload["emerging_methods"]}
    new_names = {r["name"] for r in payload["new_methods"]}
    assert "solo-nascent-method" in new_names
    assert "solo-nascent-method" not in emerging


def test_new_methods_sorted_by_corpus_then_score(monkeypatch):
    _tmp_db(monkeypatch)
    # corpus_paper_cnt=1
    p1 = _paper("c1", 2)
    _edge("c1", p1, "alpha-one-paper")
    # corpus_paper_cnt=2 (one older outside window still counts for corpus)
    p_old = _paper("c2-old", 40)
    _edge("c2-old", p_old, "beta-two-paper")
    p_new = _paper("c2-new", 2)
    _edge("c2-new", p_new, "beta-two-paper")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=1)
    names = [r["name"] for r in payload["new_methods"]]
    assert names.index("alpha-one-paper") < names.index("beta-two-paper")


def test_report_includes_new_methods_section(monkeypatch):
    _tmp_db(monkeypatch)
    p = _paper("1", 2)
    _edge("1", p, "report-niche-method")
    report = generate_hotspot_report(
        compute_weekly_hotspots(window_days=14, prior_days=14, min_recent=1),
        wow={"has_baseline": False, "previous_week_id": "2026-W01", "boards": {}},
    )
    assert "## New Methods This Window (本周新方法)" in report
    assert "report-niche-method" in report
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
python -m pytest tests/test_weekly_hotspot_new_methods.py -v
```

Expected: FAIL — `KeyError: 'new_methods'` and/or missing report heading (config constant may already exist after Step 1).

- [ ] **Step 4: Suggested commit (only if user asked to commit)**

```text
test: add failing coverage for weekly new_methods board
```

---

### Task 2: Compute `new_methods` in `weekly_hotspot`

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py`

**Interfaces:**
- Produces: helper (name flexible) that returns `list[dict]` of nascent method rows
- Extends: `compute_weekly_hotspots` return dict with `"new_methods": list[dict]`

- [ ] **Step 1: Add helper near method board computation**

Prefer a small function after `_compute_emerging_method_entities` / near `compute_emerging_entities`:

```python
def compute_new_methods(
    *,
    window_days: int | None = None,
    prior_days: int | None = None,
    counts: dict[str, int] | None = None,
    role_by_name: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Nascent methods in the publication window (min_recent=1, no heat Top-N)."""
    window = window_days if window_days is not None else config.HOTSPOT_WINDOW_DAYS
    prior = prior_days if prior_days is not None else config.HOTSPOT_PRIOR_WINDOW_DAYS
    rows = compute_emerging_entities(
        "Method",
        window_days=window,
        prior_days=prior,
        min_recent=1,
        limit=config.HOTSPOT_NEW_METHODS_MAX,
    )
    annotate_method_rows(rows, counts=counts)
    if role_by_name is not None:
        annotate_method_role(rows, role_by_name=role_by_name)
    else:
        annotate_method_role(rows)
    nascent = [row for row in rows if row.get("method_maturity") == "nascent"]
    nascent.sort(
        key=lambda row: (
            int(row.get("corpus_paper_cnt") or 0),
            -float(row.get("emerging_score") or 0),
            str(row.get("name") or ""),
        )
    )
    return nascent
```

- [ ] **Step 2: Wire into `compute_weekly_hotspots`**

After `counts = corpus_applies_method_counts_canonical()` and `role_map = load_method_roles()`, and after annotating the heat method board, compute:

```python
new_methods = compute_new_methods(
    window_days=window,
    prior_days=prior,
    counts=counts,
    role_by_name=role_map,
)
```

Add to the returned dict (alongside `emerging_methods` / `active_methods`):

```python
"new_methods": new_methods,
```

Do **not** change how `methods` / `emerging_methods` / `active_methods` are built or truncated.

Optional efficiency (allowed, not required): if you already have an uncapped method pool, filter nascent from it instead of a second SQL pass — but keep heat board `limit=HOTSPOT_TOP_N` behavior identical. Prefer the explicit second call above for clarity unless profiling says otherwise.

- [ ] **Step 3: Run selection tests**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
python -m pytest tests/test_weekly_hotspot_new_methods.py::test_nascent_in_new_methods_established_and_emerging_out tests/test_weekly_hotspot_new_methods.py::test_new_methods_ignores_sidebar_min_recent_and_top_n tests/test_weekly_hotspot_new_methods.py::test_new_methods_sorted_by_corpus_then_score -v
```

Expected: PASS for those three; report test still FAIL until Task 3.

- [ ] **Step 4: Suggested commit message**

```text
feat: emit new_methods nascent board in weekly hotspots
```

---

### Task 3: Markdown report section

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`generate_hotspot_report`)

**Interfaces:**
- Consumes: `payload["new_methods"]`
- Produces: markdown heading `## New Methods This Window (本周新方法)` before `## Emerging Methods (新苗头)`

- [ ] **Step 1: Insert report block**

In `generate_hotspot_report`, before the `## Emerging Methods (新苗头)` block, insert:

```python
lines.extend([
    "## New Methods This Window (本周新方法)",
    "",
    "_Nascent only (corpus ≤2); fixed min_recent=1; not cut by heat Top-N._",
    "",
])
new_methods = data.get("new_methods") or []
if new_methods:
    lines.extend([
        _format_table(
            new_methods,
            [
                "name",
                "method_role",
                "corpus_paper_cnt",
                "recent_cnt",
                "prior_cnt",
                "velocity",
                "emerging_score",
            ],
        ),
    ])
else:
    lines.extend(["None", ""])
```

Keep Emerging Methods section unchanged after this block.

- [ ] **Step 2: Run report test**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
python -m pytest tests/test_weekly_hotspot_new_methods.py::test_report_includes_new_methods_section -v
```

Expected: PASS

- [ ] **Step 3: Suggested commit message**

```text
docs: include 本周新方法 section in hotspot markdown report
```

---

### Task 4: Gap UI — 方法 tab top block

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_weekly_hotspot_tab`, `with tab_m:`)
- Optionally extend: `fulltext_workflow/tests/test_weekly_hotspot_method_role.py` if you add a tiny render helper; otherwise keep UI change untested beyond manual smoke (prefer a small pure helper for testability).

**Interfaces:**
- Consumes: `payload.get("new_methods", [])`

- [ ] **Step 1: Render above 新苗头**

Replace the `with tab_m:` body start so the new block comes first:

```python
with tab_m:
    st.subheader("本周新方法")
    st.caption(
        "成熟度 = **nascent**（全库 APPLIES_METHOD ≤ 2 篇，且非成熟黑名单）。"
        "固定最少近窗篇数 = **1**（与侧栏无关）；不做热度 Top-N 截断。"
    )
    new_methods = payload.get("new_methods") or []
    if new_methods:
        cols = [
            "name",
            "method_role",
            "corpus_paper_cnt",
            "recent_cnt",
            "prior_cnt",
            "velocity",
            "emerging_score",
            "method_maturity",
        ]
        df_new = pd.DataFrame(new_methods)
        ordered = [c for c in cols if c in df_new.columns]
        extra = [c for c in df_new.columns if c not in ordered]
        safe_table(df_new[ordered + extra])
    else:
        st.info("本窗暂无 nascent 新方法（也可能是近窗论文尚未抽取）。")

    st.caption(
        f"新苗头；已过滤「成熟常用」方法。已按方法同义词软归并。"
        f"当前最少近窗篇数 = **{min_recent}**。按方法角色分区展示。"
        "角色规则优先，抽取提示仅补全未知项；角色不影响热度分数。"
    )
    _render_methods_by_role(payload.get("emerging_methods", []))
    with st.expander("本周活跃（含成熟常用方法）", expanded=False):
        _render_methods_by_role(payload.get("active_methods", []))
```

- [ ] **Step 2: Smoke-check import**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
python -c "import gap_ui; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Suggested commit message**

```text
feat(ui): show 本周新方法 above weekly method heat board
```

---

### Task 5: Regression + verification

**Files:** none new

- [ ] **Step 1: Run new + maturity suites**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
python -m pytest tests/test_weekly_hotspot_new_methods.py tests/test_weekly_hotspot_maturity.py tests/test_weekly_hotspot_method_role.py -v
```

Expected: all PASS

- [ ] **Step 2: Spec checklist (manual)**

- [ ] `new_methods` present on payload  
- [ ] nascent in / established+emerging out  
- [ ] `min_recent=2` + `HOTSPOT_TOP_N=2` still lists single-paper nascent in `new_methods`  
- [ ] UI caption states fixed min=1 and independence from sidebar  
- [ ] Report heading present  
- [ ] Snapshot WoW still uses `emerging_methods` only for method board  

- [ ] **Step 3: Suggested final commit message (if bundling)**

```text
feat: add weekly 本周新方法 board independent of heat Top-N
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| `new_methods` field, nascent only | Task 2 |
| fixed min_recent=1; no Top-N; max 500 | Task 1–2 |
| sort corpus↑, score↓, name↑ | Task 1 test + Task 2 |
| UI top of 方法 tab | Task 4 |
| report short section | Task 3 |
| no snapshot WoW board | Global constraint / Task 5 checklist |
| emerging board unchanged | Task 2 + Task 5 regression |

No intentional placeholders left in steps.
