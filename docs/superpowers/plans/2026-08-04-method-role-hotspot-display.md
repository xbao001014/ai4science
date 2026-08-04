# Method Role Split for Weekly Hotspot Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Annotate weekly-hotspot method rows with `method_role` (`backbone` | `aggregator` | `unknown`) via runtime rules, and show the Gap UI methods tab as three role sections without changing scores or maturity gates.

**Architecture:** Add `analysis/method_role.py` (dictionary-first + conservative heuristics, same style as `method_maturity.py`). Wire `annotate_method_role` into `compute_weekly_hotspots` and opportunity rows. Split Streamlit method tables by role while preserving original list order.

**Tech Stack:** Python 3, pytest, Streamlit (`gap_ui.py`), existing `resolve_method_canonical` / `_norm_key`.

**Spec:** `docs/superpowers/specs/2026-08-04-method-role-hotspot-display-design.md`

## Global Constraints

- Roles are exactly: `backbone` | `aggregator` | `unknown` (no `framework` tier in v1).
- Classification is **runtime only** — do not change extract prompts, entity DB schema, or `weekly_hotspot_snapshots` columns.
- Do **not** change `emerging_score`, maturity gating, synonym merge, Top-N cuts, or transferable scoring formulas.
- Decision order: aggregator aliases → backbone aliases → aggregator heuristics → backbone heuristics → `unknown`. If a name is in both alias tables, **aggregator wins**.
- Avoid bare `\battention\b` as an aggregator cue (false positives on Attention U-Net–style backbones).
- Avoid naive “any substring `cnn` ⇒ backbone”.
- Run pytest from `fulltext_workflow/` on `sys.path` (existing test pattern).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/method_role.py` | **New** — aliases, heuristics, `classify_method_role`, `annotate_method_role` |
| `fulltext_workflow/analysis/weekly_hotspot.py` | After maturity annotate: role-annotate methods + combos; role-annotate opportunities before return |
| `fulltext_workflow/gap_ui.py` | Methods tab: caption + three role sections for emerging + active; optional `method_role` column on combo/opportunity tables |
| `fulltext_workflow/tests/test_method_role.py` | **New** — unit tests for classifier |
| `fulltext_workflow/tests/test_weekly_hotspot_method_role.py` | **New** — payload rows include `method_role`; maturity filter unchanged |

---

### Task 1: `method_role` module + unit tests

**Files:**
- Create: `fulltext_workflow/analysis/method_role.py`
- Create: `fulltext_workflow/tests/test_method_role.py`

**Interfaces:**
- Produces: `classify_method_role(name: str) -> Literal["backbone", "aggregator", "unknown"]`
- Produces: `annotate_method_role(rows: list[dict], *, name_key: str = "name") -> list[dict]`  
  Mutates each row with `method_role`; does **not** rewrite `name_key` (maturity/synonym already canonicalized on hotspot rows). Still resolves via `resolve_method_canonical` before classify so callers with raw aliases stay correct.
- Consumes: `extractor.entity_normalize._norm_key`, `analysis.method_synonyms.resolve_method_canonical`

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_method_role.py`:

```python
"""Unit tests for method role classification (backbone vs aggregator)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_role import (  # noqa: E402
    annotate_method_role,
    classify_method_role,
)


def test_backbone_aliases():
    assert classify_method_role("resnet-50") == "backbone"
    assert classify_method_role("ResNet50") == "backbone"
    assert classify_method_role("uni") == "backbone"
    assert classify_method_role("conch") == "backbone"
    assert classify_method_role("ctranspath") == "backbone"
    assert classify_method_role("vit") == "backbone"


def test_aggregator_heuristics():
    assert classify_method_role("dual-attention mil") == "aggregator"
    assert classify_method_role("cross-attention fusion module") == "aggregator"
    assert classify_method_role("attention pooling mil head") == "aggregator"
    assert classify_method_role("bag-level aggregator") == "aggregator"


def test_bare_attention_not_forced_aggregator():
    # Must NOT use bare "attention" as aggregator cue.
    # With alias `attention u-net` → backbone; without alias must still != aggregator.
    assert classify_method_role("attention u-net") == "backbone"


def test_unknown_frameworkish_names():
    assert classify_method_role("clam") == "unknown"
    assert classify_method_role("transmil") == "unknown"
    assert classify_method_role("qupath") == "unknown"


def test_aggregator_alias_beats_backbone_alias(monkeypatch):
    import analysis.method_role as mr

    monkeypatch.setattr(
        mr,
        "_BACKBONE_ALIASES",
        frozenset(set(mr._BACKBONE_ALIASES) | {"conflict-tool"}),
    )
    monkeypatch.setattr(
        mr,
        "_AGGREGATOR_ALIASES",
        frozenset(set(mr._AGGREGATOR_ALIASES) | {"conflict-tool"}),
    )
    assert classify_method_role("conflict-tool") == "aggregator"


def test_annotate_method_role_writes_field():
    rows = [{"name": "resnet-50"}, {"name": "dual-stream mil"}]
    out = annotate_method_role(rows)
    assert out is rows
    assert rows[0]["method_role"] == "backbone"
    assert rows[1]["method_role"] == "aggregator"


def test_classify_uses_canonical_before_role(monkeypatch):
    import analysis.method_role as mr

    monkeypatch.setattr(
        mr,
        "resolve_method_canonical",
        lambda name: "resnet-50" if name == "alias-rn50" else name,
    )
    assert classify_method_role("alias-rn50") == "backbone"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_method_role.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `analysis.method_role`.

- [ ] **Step 3: Write minimal implementation**

Create `fulltext_workflow/analysis/method_role.py`:

```python
"""Method architecture role for weekly hotspot display (backbone vs aggregator)."""
from __future__ import annotations

import re
from typing import Literal

from analysis.method_synonyms import resolve_method_canonical
from extractor.entity_normalize import _norm_key

MethodRole = Literal["backbone", "aggregator", "unknown"]

# Exact aliases after _norm_key. If a name appears in both tables, aggregator wins.
_BACKBONE_ALIASES = frozenset({
    "resnet",
    "resnet-18",
    "resnet18",
    "resnet-50",
    "resnet50",
    "resnet-101",
    "resnet101",
    "vit",
    "vision transformer",
    "swin",
    "swin transformer",
    "efficientnet",
    "densenet",
    "densenet-121",
    "densenet121",
    "uni",
    "conch",
    "ctranspath",
    "hibou",
    "virchow",
    "phikon",
    "gigapath",
    "h-optimus",
    "hoptimus",
    "attention u-net",
    "attention-unet",
    "u-net",
    "unet",
})

_AGGREGATOR_ALIASES = frozenset({
    # Seed empty or with a few known contribution modules; grow from mislabels.
})

# Aggregator cues — no bare \\battention\\b.
_AGGREGATOR_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\baggregator\b",
        r"\bmil\b",
        r"attention\s*pool",
        r"\bpooling\b",
        r"fusion\s+module",
        r"bag[\s\-]?level",
        r"instance[\s\-]?aggregat",
    )
)

_BACKBONE_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bresnet\b",
        r"\bvit\b",
        r"\bswin\b",
        r"\befficientnet\b",
        r"\bdensenet\b",
        r"\bencoder\b",
        r"\bbackbone\b",
    )
)


def classify_method_role(name: str) -> MethodRole:
    canonical = resolve_method_canonical(name)
    key = _norm_key(canonical)
    # Aggregator aliases before backbone aliases (conflict → aggregator).
    if key in _AGGREGATOR_ALIASES:
        return "aggregator"
    if key in _BACKBONE_ALIASES:
        return "backbone"
    if any(p.search(key) for p in _AGGREGATOR_PATTERNS):
        return "aggregator"
    if any(p.search(key) for p in _BACKBONE_PATTERNS):
        return "backbone"
    return "unknown"


def annotate_method_role(
    rows: list[dict],
    *,
    name_key: str = "name",
) -> list[dict]:
    for row in rows:
        row["method_role"] = classify_method_role(str(row.get(name_key) or ""))
    return rows
```

Adjust alias seeds if unit tests need extra exact hits; keep heuristics conservative.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_method_role.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit** (only if commits are in scope for this execution)

```bash
git add fulltext_workflow/analysis/method_role.py fulltext_workflow/tests/test_method_role.py
git commit -m "feat: add method_role classifier for hotspot display"
```

---

### Task 2: Wire roles into weekly hotspot payload

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`compute_weekly_hotspots`, `compute_emerging_gap_opportunities`)
- Create: `fulltext_workflow/tests/test_weekly_hotspot_method_role.py`

**Interfaces:**
- Consumes: `annotate_method_role(rows, name_key=...)` from Task 1
- Produces: every row in `emerging_methods`, `active_methods`, `hot_combos`, `hot_combos_by_method` has `method_role`
- Produces: every opportunity row from `compute_emerging_gap_opportunities` has `method_role`

- [ ] **Step 1: Write the failing integration test**

Create `fulltext_workflow/tests/test_weekly_hotspot_method_role.py`:

```python
"""Weekly hotspot payload includes method_role without changing maturity gates."""
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
from db.schema import get_conn, init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


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
    return upsert_paper({
        "pmid": pmid,
        "title": pmid,
        "pub_date": _iso(days_ago),
        "year": int(_iso(days_ago)[:4]),
        "date_precision": "day",
        "extraction_done": 1,
    })


def _edge(pmid: str, paper_id: int, name: str) -> None:
    entity_id = upsert_entity(name, "Method")
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", entity_id,
        source_pmid=pmid, status="active",
    )


def test_emerging_and_active_have_method_role(monkeypatch):
    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
    for i, pmid in enumerate(("1", "2"), start=1):
        pid = _paper(pmid, i)
        _edge(pmid, pid, "niche-mil-aggregator-x")
    for i, pmid in enumerate(("3", "4"), start=1):
        pid = _paper(pmid, i + 2)
        _edge(pmid, pid, "resnet-50")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging = {r["name"]: r for r in payload["emerging_methods"]}
    active = {r["name"]: r for r in payload["active_methods"]}

    assert emerging["niche-mil-aggregator-x"]["method_role"] == "aggregator"
    assert active["resnet-50"]["method_role"] == "backbone"
    # resnet-50 is established blacklist → excluded from emerging
    assert "resnet-50" not in emerging
    assert "resnet-50" in active
    for row in payload.get("hot_combos") or []:
        assert row.get("method_role") in {"backbone", "aggregator", "unknown"}
    for row in payload.get("hot_combos_by_method") or []:
        assert row.get("method_role") in {"backbone", "aggregator", "unknown"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_weekly_hotspot_method_role.py -v
```

Expected: FAIL on missing `method_role` key.

- [ ] **Step 3: Wire annotation into `weekly_hotspot.py`**

Near top imports (with maturity imports), add:

```python
from analysis.method_role import annotate_method_role
```

In `compute_weekly_hotspots`, annotate roles on the full `methods` list **after** maturity annotation and **before** splitting into emerging/active (shared row dicts inherit the field):

```python
    annotate_method_rows(methods, counts=counts)
    annotate_method_role(methods)
    active_methods = list(methods)
    emerging_methods = [
        row for row in methods if row.get("method_maturity") != "established"
    ]
    annotate_method_rows(combos, name_key="method", counts=counts)
    annotate_method_rows(combos_by_method, name_key="method", counts=counts)
    annotate_method_role(combos, name_key="method")
    annotate_method_role(combos_by_method, name_key="method")
```

At the end of `compute_emerging_gap_opportunities`, before returning the final opportunities list, add:

```python
    annotate_method_role(rows, name_key="method")
    return rows
```

(Locate the exact variable that is returned — annotate that list, not an intermediate discarded copy.)

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_weekly_hotspot_method_role.py tests/test_method_role.py tests/test_weekly_hotspot_synonyms.py tests/test_method_maturity.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit** (only if commits are in scope)

```bash
git add fulltext_workflow/analysis/weekly_hotspot.py fulltext_workflow/tests/test_weekly_hotspot_method_role.py
git commit -m "feat: annotate weekly hotspot methods with method_role"
```

---

### Task 3: Gap UI methods tab by role

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`render_weekly_hotspot_tab`, methods tab ~2142–2149; combo/opportunity column lists)

**Interfaces:**
- Consumes: payload rows with `method_role` from Task 2
- Produces: helper `_render_methods_by_role(rows: list[dict]) -> None` (module-private in `gap_ui.py`) that partitions preserving order

- [ ] **Step 1: Add helper and update methods tab UI**

Near other private helpers in `gap_ui.py` (above `render_weekly_hotspot_tab` is fine), add:

```python
_METHOD_ROLE_SECTIONS = (
    ("backbone", "基座 / 骨干"),
    ("aggregator", "聚合器 / 贡献模块"),
    ("unknown", "未分类"),
)


def _render_methods_by_role(rows: list[dict]) -> None:
    """Split method rows into role sections; preserve relative order within each."""
    buckets: dict[str, list[dict]] = {key: [] for key, _ in _METHOD_ROLE_SECTIONS}
    for row in rows or []:
        role = str(row.get("method_role") or "unknown")
        if role not in buckets:
            role = "unknown"
        buckets[role].append(row)
    for key, title in _METHOD_ROLE_SECTIONS:
        part = buckets[key]
        if not part:
            continue
        st.subheader(title)
        safe_table(pd.DataFrame(part))
```

Replace the methods tab body:

```python
    with tab_m:
        st.caption(
            f"新苗头；已过滤「成熟常用」方法。已按方法同义词软归并。"
            f"当前最少近窗篇数 = **{min_recent}**。"
        )
        st.caption(
            "方法已按角色分为基座（backbone）/ 聚合器（aggregator）/ 未分类；"
            "分类为运行时规则，不影响热度分。"
        )
        _render_methods_by_role(payload.get("emerging_methods") or [])
        with st.expander("本周活跃（含成熟常用方法）", expanded=False):
            _render_methods_by_role(payload.get("active_methods") or [])
```

- [ ] **Step 2: Add `method_role` column to combo and opportunity tables**

In hot-combo `cols` list (after `method`), insert `"method_role"`.

In opportunity `opp_cols` list (after `method`), insert `"method_role"`.

Existing `ordered = [c for c in cols if c in df_m.columns]` pattern already hides missing columns safely.

- [ ] **Step 3: Smoke-check manually (optional but recommended)**

With Streamlit already running `gap_ui.py`, refresh 「每周热点 → 方法」:

- See role subheaders when that role has rows.
- Empty roles hidden.
- Scores / row counts match pre-change expectation for the same window (display-only).

No automated UI test required in v1.

- [ ] **Step 4: Run related pytest once more**

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_method_role.py tests/test_weekly_hotspot_method_role.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit** (only if commits are in scope)

```bash
git add fulltext_workflow/gap_ui.py
git commit -m "feat: show weekly hotspot methods split by method_role"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| `method_role` values backbone/aggregator/unknown | Task 1 |
| Runtime rules: aliases → heuristics → unknown; aggregator wins conflicts | Task 1 |
| No bare attention aggregator cue | Task 1 test + patterns |
| Annotate emerging/active/combos | Task 2 |
| Annotate opportunities (`name_key=method`) | Task 2 |
| No score/maturity/Top-N changes | Task 2 (annotate only) |
| Methods tab three sections + caption | Task 3 |
| Active expander also segmented | Task 3 |
| Combo/opportunity column only | Task 3 |
| No snapshot schema / no extract changes | Global constraints / omitted |
| Report text grouping optional | Omitted (non-blocking) |

## Out of scope (do not implement in this plan)

- Third role `framework`, LLM labeling, extract-time `method_role`
- Independent Top-N boards per role
- Persisting `method_role` on snapshots
- Hotspot markdown report regrouping
