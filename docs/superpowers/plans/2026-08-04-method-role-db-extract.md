# Persist Method Role (DB + Extract) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist five-value `method_role` on Method entities, backfill with rules, accept optional extract `method_role_hint` under rule authority, and show five role sections in the weekly-hotspot UI.

**Architecture:** Extend `analysis/method_role.py` (aliases + `resolve_method_role`). Add `entities.method_role` like `access_class`. Wire Method upserts in section extract + reconcile. CLI `backfill-method-roles`. Hotspot annotation prefers DB map then rules; Gap UI renders five sections.

**Tech Stack:** Python 3, SQLite (`db/schema.py`), pydantic Triple, pytest, Streamlit (`gap_ui.py`).

**Spec:** `docs/superpowers/specs/2026-08-04-method-role-db-extract-design.md`

## Global Constraints

- Roles exactly: `backbone` | `aggregator` | `classical_ml` | `tool` | `unknown`.
- **Rules authoritative:** non-`unknown` rule result always wins over LLM hint.
- LLM hint fills only when rule is `unknown` and hint is one of the five values.
- Existing non-null DB role is **not cleared** when resolve returns `unknown`.
- Do **not** change `emerging_score`, maturity gating, synonym merge, Top-N, or transferable scoring formulas.
- No bare `\battention\b` aggregator cue; no naive “any substring `cnn` ⇒ backbone” beyond intended aliases/patterns.
- Do not force full re-extract; backfill covers existing Method rows.
- Run pytest from `fulltext_workflow/` on `sys.path` (existing pattern).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/method_role.py` | Five-way classify, resolve merge, load DB map, annotate with optional map |
| `fulltext_workflow/db/schema.py` | Column + migrate + `upsert_entity(..., method_role=)` |
| `fulltext_workflow/main.py` | `backfill-method-roles` CLI |
| `fulltext_workflow/SCRIPTS.md` | Document CLI |
| `fulltext_workflow/extractor/triple_models.py` | `method_role_hint` field + coerce |
| `fulltext_workflow/extractor/study_prompts/shared.py` | Method role hint policy |
| `fulltext_workflow/extractor/GRANULARITY.md` | Short field note |
| `fulltext_workflow/extractor/section_extractor.py` | Pass hint into Method upsert |
| `fulltext_workflow/extractor/fulltext_reconcile.py` | Method upserts call resolve/role |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Annotate via DB map + fallback |
| `fulltext_workflow/gap_ui.py` | Five role sections (current tree may be a single table — restore/expand) |
| `fulltext_workflow/tests/test_method_role.py` | Extend five-way + resolve tests |
| `fulltext_workflow/tests/test_method_role_db.py` | **New** — upsert merge + migrate/backfill smoke |
| `fulltext_workflow/tests/test_triple_method_role_hint.py` | **New** — Triple coerce |
| `fulltext_workflow/scripts/audit_method_role.py` | Optional: keep if present; else skip |

---

### Task 1: Five-way classifier + `resolve_method_role`

**Files:**
- Modify: `fulltext_workflow/analysis/method_role.py`
- Modify: `fulltext_workflow/tests/test_method_role.py`

**Interfaces:**
- Produces: `MethodRole = Literal["backbone","aggregator","classical_ml","tool","unknown"]`
- Produces: `VALID_METHOD_ROLES: frozenset[str]`
- Produces: `classify_method_role(name: str) -> MethodRole`
- Produces: `resolve_method_role(name: str, llm_role: str | None = None) -> MethodRole`
- Produces: `annotate_method_role(rows, *, name_key="name", role_by_name: dict[str, str] | None = None) -> list[dict]`
- Decision order: agg aliases → backbone aliases → classical_ml aliases → tool aliases → agg heuristics → backbone heuristics → classical_ml heuristics → tool heuristics → unknown

- [ ] **Step 1: Extend failing tests**

Update/add in `tests/test_method_role.py`:

```python
from analysis.method_role import (
    annotate_method_role,
    classify_method_role,
    resolve_method_role,
)

def test_classical_ml_aliases():
    assert classify_method_role("random forest") == "classical_ml"
    assert classify_method_role("support vector machine") == "classical_ml"
    assert classify_method_role("xgboost") == "classical_ml"
    assert classify_method_role("lightgbm") == "classical_ml"
    assert classify_method_role("logistic regression") == "classical_ml"
    assert classify_method_role("cox proportional hazards regression") == "classical_ml"

def test_tool_aliases():
    assert classify_method_role("qupath") == "tool"
    assert classify_method_role("seurat") == "tool"
    assert classify_method_role("gsva") == "tool"
    assert classify_method_role("vosviewer") == "tool"

def test_backbone_missings():
    assert classify_method_role("hover-net") == "backbone"
    assert classify_method_role("segformer") == "backbone"
    assert classify_method_role("dinov2") == "backbone"
    assert classify_method_role("cnn") == "backbone"
    assert classify_method_role("convolutional neural network") == "backbone"
    assert classify_method_role("xception") == "backbone"
    assert classify_method_role("prov-gigapath") == "backbone"

def test_resolve_rule_beats_hint():
    assert resolve_method_role("resnet-50", "tool") == "backbone"
    assert resolve_method_role("clam", "backbone") == "aggregator"

def test_resolve_hint_fills_unknown():
    assert resolve_method_role("totally-novel-widget-xyz", "classical_ml") == "classical_ml"
    assert resolve_method_role("totally-novel-widget-xyz", "nope") == "unknown"
    assert resolve_method_role("totally-novel-widget-xyz", None) == "unknown"

def test_annotate_prefers_role_by_name():
    rows = [{"name": "weird-method"}]
    annotate_method_role(rows, role_by_name={"weird-method": "tool"})
    assert rows[0]["method_role"] == "tool"
```

Keep existing backbone/aggregator/attention tests; update `test_unknown_frameworkish_names` so `qupath` expects `tool` (not `unknown`). Keep `clam`/`transmil` as aggregator if still in aggregator aliases.

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_method_role.py -v
```

Expected: failures on new classical_ml/tool/resolve assertions.

- [ ] **Step 3: Implement five-way classifier**

Rewrite `method_role.py` roles and tables. Minimal seed sets (expand as needed for tests):

```python
MethodRole = Literal["backbone", "aggregator", "classical_ml", "tool", "unknown"]
VALID_METHOD_ROLES = frozenset(
    {"backbone", "aggregator", "classical_ml", "tool", "unknown"}
)

# Keep existing backbone/aggregator aliases+patterns; ADD backbone seeds from tests.
# ADD:
_CLASSICAL_ML_ALIASES = frozenset({...})  # names from tests + common variants
_TOOL_ALIASES = frozenset({...})

_CLASSICAL_ML_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\brandom\s+forest",
    r"\bxgboost\b",
    r"\blightgbm\b",
    r"\bcatboost\b",
    r"\blogistic\s+regression",
    r"\bsupport\s+vector",
    r"\bcox\b",
    r"\bkaplan[\s\-]?meier",
    r"\bnaive\s+bayes",
    r"\belastic\s+net\b",
    r"\bgradient\s+boost",
))

_TOOL_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\bqupath\b",
    r"\bseurat\b",
    r"\bvosviewer\b",
    r"\bcitespace\b",
))

def classify_method_role(name: str) -> MethodRole:
    key = _norm_key(resolve_method_canonical(name))
    if key in _AGGREGATOR_ALIASES:
        return "aggregator"
    if key in _BACKBONE_ALIASES:
        return "backbone"
    if key in _CLASSICAL_ML_ALIASES:
        return "classical_ml"
    if key in _TOOL_ALIASES:
        return "tool"
    if any(p.search(key) for p in _AGGREGATOR_PATTERNS):
        return "aggregator"
    if any(p.search(key) for p in _BACKBONE_PATTERNS):
        return "backbone"
    if any(p.search(key) for p in _CLASSICAL_ML_PATTERNS):
        return "classical_ml"
    if any(p.search(key) for p in _TOOL_PATTERNS):
        return "tool"
    return "unknown"

def resolve_method_role(name: str, llm_role: str | None = None) -> MethodRole:
    rule = classify_method_role(name)
    if rule != "unknown":
        return rule
    if isinstance(llm_role, str):
        hint = llm_role.strip().lower()
        if hint in VALID_METHOD_ROLES:
            return hint  # type: ignore[return-value]
    return "unknown"

def annotate_method_role(rows, *, name_key="name", role_by_name=None):
    role_by_name = role_by_name or {}
    for row in rows:
        raw = str(row.get(name_key) or "")
        key = _norm_key(resolve_method_canonical(raw))
        db = role_by_name.get(key) or role_by_name.get(raw)
        if db in VALID_METHOD_ROLES:
            row["method_role"] = db
        else:
            row["method_role"] = classify_method_role(raw)
    return rows
```

Note: `role_by_name` keys should be normalized names as stored in DB (`upsert_entity` lowercases). Prefer lookup by `_norm_key(resolve_method_canonical(raw))` and by raw lower name.

- [ ] **Step 4: Run tests — expect PASS**

```bash
..\.venv\Scripts\python.exe -m pytest tests/test_method_role.py -v
```

- [ ] **Step 5: Commit** (if commits in scope)

```bash
git add fulltext_workflow/analysis/method_role.py fulltext_workflow/tests/test_method_role.py
git commit -m "feat: expand method_role to classical_ml and tool"
```

---

### Task 2: Schema column, upsert merge, backfill CLI

**Files:**
- Modify: `fulltext_workflow/db/schema.py` (`SCHEMA_SQL` entities, `_migrate_db`, `upsert_entity`)
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/SCRIPTS.md`
- Create: `fulltext_workflow/tests/test_method_role_db.py`
- Optional produce: `load_method_roles()` / `backfill_method_roles()` in `method_role.py` or small `analysis/method_role_db.py` — prefer keep in `method_role.py` to avoid extra module unless file grows unwieldy.

**Interfaces:**
- Consumes: `resolve_method_role`
- Produces: `entities.method_role` column
- Produces: `upsert_entity(name, type, cui="", access_class=None, method_role=None) -> int`
- Produces: `backfill_method_roles() -> dict[str, int]` role → count
- Produces: `load_method_roles() -> dict[str, str]` normalized name → role
- CLI: `backfill-method-roles`

- [ ] **Step 1: Write DB tests**

```python
"""Persist method_role on Method entities."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis.method_role import backfill_method_roles, load_method_roles  # noqa: E402
from db.schema import get_conn, init_db, upsert_entity  # noqa: E402


def _tmp(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def test_upsert_method_stores_resolved_role(monkeypatch):
    _tmp(monkeypatch)
    eid = upsert_entity("resnet-50", "Method", method_role="tool")  # hint ignored
    with get_conn() as conn:
        row = conn.execute(
            "SELECT method_role FROM entities WHERE id=?", (eid,)
        ).fetchone()
    assert row["method_role"] == "backbone"


def test_upsert_hint_fills_unknown_only(monkeypatch):
    _tmp(monkeypatch)
    eid = upsert_entity("novel-widget-aaa", "Method", method_role="classical_ml")
    with get_conn() as conn:
        assert conn.execute(
            "SELECT method_role FROM entities WHERE id=?", (eid,)
        ).fetchone()["method_role"] == "classical_ml"


def test_upsert_unknown_does_not_clear_existing(monkeypatch):
    _tmp(monkeypatch)
    eid = upsert_entity("novel-widget-bbb", "Method", method_role="tool")
    upsert_entity("novel-widget-bbb", "Method", method_role=None)
    with get_conn() as conn:
        assert conn.execute(
            "SELECT method_role FROM entities WHERE id=?", (eid,)
        ).fetchone()["method_role"] == "tool"


def test_backfill_sets_roles(monkeypatch):
    _tmp(monkeypatch)
    upsert_entity("random forest", "Method")
    upsert_entity("qupath", "Method")
    # force null then backfill
    with get_conn() as conn:
        conn.execute("UPDATE entities SET method_role=NULL WHERE type='Method'")
    counts = backfill_method_roles()
    assert counts.get("classical_ml", 0) >= 1
    assert counts.get("tool", 0) >= 1
    roles = load_method_roles()
    assert roles["random forest"] == "classical_ml"
    assert roles["qupath"] == "tool"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
..\.venv\Scripts\python.exe -m pytest tests/test_method_role_db.py -v
```

- [ ] **Step 3: Schema + upsert + backfill helpers**

In `SCHEMA_SQL` entities block add `method_role TEXT` next to `access_class`.

In `_migrate_db`:

```python
if "method_role" not in entity_cols:
    conn.execute("ALTER TABLE entities ADD COLUMN method_role TEXT")
```

Update `upsert_entity`:

```python
def upsert_entity(
    name: str,
    entity_type: str,
    cui: str = "",
    access_class: str | None = None,
    method_role: str | None = None,
) -> int:
    ...
    # Dataset access_class logic unchanged.
    resolved_role = None
    if entity_type == "Method":
        from analysis.method_role import resolve_method_role
        resolved_role = resolve_method_role(name, method_role)

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, access_class, method_role FROM entities WHERE name=? AND type=?",
            (normalized, entity_type),
        ).fetchone()
        if existing:
            # existing Dataset access merge...
            if entity_type == "Method" and resolved_role is not None:
                cur = existing["method_role"]
                if resolved_role != "unknown" and resolved_role != cur:
                    conn.execute(
                        "UPDATE entities SET method_role=? WHERE id=?",
                        (resolved_role, existing["id"]),
                    )
            return existing["id"]
        conn.execute(
            "INSERT INTO entities (name, type, cui, access_class, method_role) VALUES (?,?,?,?,?)",
            (
                normalized,
                entity_type,
                cui or None,
                ac if entity_type == "Dataset" else None,
                resolved_role if entity_type == "Method" else None,
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
```

**Important:** For Method **insert** with no hint and rule unknown → store `"unknown"` (or NULL). Spec allows nullable; prefer storing the resolved string including `"unknown"` on insert for simpler backfill audits. On update, unknown must not clear.

Add to `method_role.py`:

```python
def load_method_roles() -> dict[str, str]:
    from db.schema import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT name, method_role FROM entities
            WHERE type='Method' AND method_role IS NOT NULL AND method_role != ''
            """
        ).fetchall()
    return {str(r["name"]): str(r["method_role"]) for r in rows}


def backfill_method_roles() -> dict[str, int]:
    from collections import Counter
    from db.schema import get_conn
    counts: Counter[str] = Counter()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name FROM entities WHERE type='Method'"
        ).fetchall()
        for row in rows:
            role = classify_method_role(str(row["name"]))
            conn.execute(
                "UPDATE entities SET method_role=? WHERE id=?",
                (role, row["id"]),
            )
            counts[role] += 1
    return dict(counts)
```

CLI in `main.py` (mirror `backfill-date-precision`):

```python
def cmd_backfill_method_roles(_args):
    from analysis.method_role import backfill_method_roles
    from db.schema import init_db
    init_db()
    counts = backfill_method_roles()
    print(counts)

# parser: backfill-method-roles
```

SCRIPTS.md: one bullet under entities/hotspot maintenance:

```markdown
py main.py backfill-method-roles   # entities.method_role 规则回填
```

- [ ] **Step 4: Run tests — PASS**

```bash
..\.venv\Scripts\python.exe -m pytest tests/test_method_role_db.py tests/test_method_role.py -v
```

- [ ] **Step 5: Commit** (if in scope)

```bash
git commit -m "feat: persist entities.method_role with backfill CLI"
```

---

### Task 3: Extract hint (Triple + prompt + ingest)

**Files:**
- Modify: `fulltext_workflow/extractor/triple_models.py`
- Modify: `fulltext_workflow/extractor/study_prompts/shared.py`
- Modify: `fulltext_workflow/extractor/section_extractor.py` (Paper→X Method upsert ~112)
- Modify: `fulltext_workflow/extractor/fulltext_reconcile.py` (Method upserts ~528, ~629)
- Modify: `fulltext_workflow/extractor/GRANULARITY.md` (short note)
- Create: `fulltext_workflow/tests/test_triple_method_role_hint.py`

**Interfaces:**
- Produces: `Triple.method_role_hint` optional five-value literal
- Ingest: `upsert_entity(..., method_role=triple.method_role_hint)` for Method objects

- [ ] **Step 1: Triple coerce test**

```python
from extractor.triple_models import Triple

def test_method_role_hint_normalized():
    t = Triple.model_validate({
        "subject": {"name": "paper", "type": "Method"},
        "relation": "APPLIES_METHOD",
        "object": {"name": "resnet-50", "type": "Method"},
        "method_role_hint": "BackBone",
    })
    assert t.method_role_hint == "backbone"

def test_method_role_hint_invalid_dropped():
    t = Triple.model_validate({
        "subject": {"name": "paper", "type": "Method"},
        "relation": "APPLIES_METHOD",
        "object": {"name": "resnet-50", "type": "Method"},
        "method_role_hint": "framework",
    })
    assert t.method_role_hint is None
```

- [ ] **Step 2: Run — FAIL until model updated**

- [ ] **Step 3: Implement Triple + ingest + prompt**

`triple_models.py`:

```python
method_role_hint: Optional[Literal[
    "backbone", "aggregator", "classical_ml", "tool", "unknown"
]] = None
```

In `coerce_llm_quirks`, normalize like `access_hint` against the five values.

`section_extractor.py` Paper→X branch:

```python
method_role = None
if triple.object.type == "Method":
    method_role = triple.method_role_hint
obj_id = upsert_entity(
    obj_name,
    triple.object.type,
    access_class=access_class,
    method_role=method_role,
)
```

Also handle Method–Method / non-Paper subject path if it upserts Method objects (lines ~81–82): pass `method_role=triple.method_role_hint` when `triple.object.type == "Method"` (and subject Method if ever needed — object is enough for APPLIES).

`fulltext_reconcile.py`: for Method upserts without LLM hint, `upsert_entity(name, "Method")` still runs resolve on insert (rule-only). No change strictly required; optional comment.

Prompt in `shared.py` Method policy (after Method naming policy):

```text
Method role hint (optional method_role_hint on triples whose object is Method):
  - backbone: named visual/feature/segmentation backbone or foundation encoder
  - aggregator: MIL head, attention pooling, fusion/aggregation module
  - classical_ml: classical ML / statistical / survival models (RF, SVM, Cox, …)
  - tool: software/platform/omics tools (QuPath, Seurat, …) — not a neural backbone
  - unknown: omit or unknown when unsure
  - Rules in post-ingest may override; prefer accurate hints over guessing
```

GRANULARITY.md: one row noting `entities.method_role` + rule > hint.

- [ ] **Step 4: Integration smoke test (optional in same file)**

```python
def test_section_upsert_uses_hint(monkeypatch, tmp_path):
    # If heavy, skip — covered by upsert unit tests + Triple coerce.
    pass
```

Prefer not adding heavy extract integration; Triple + upsert tests suffice.

Run:

```bash
..\.venv\Scripts\python.exe -m pytest tests/test_triple_method_role_hint.py tests/test_method_role_db.py -v
```

- [ ] **Step 5: Commit** (if in scope)

```bash
git commit -m "feat: extract method_role_hint into Method entities"
```

---

### Task 4: Hotspot DB annotation + five-section UI

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py` (`annotate_method_role` call sites)
- Modify: `fulltext_workflow/gap_ui.py` (methods tab; restore section helper if missing)
- Modify: `fulltext_workflow/tests/test_weekly_hotspot_method_role.py` (assert new roles still annotate; optional DB preference)

**Note:** Current `gap_ui.py` methods tab may be a single `safe_table` without `_render_methods_by_role` (local WIP may have dropped earlier UI). Re-introduce helper with **five** sections.

**Interfaces:**
- Consumes: `load_method_roles()`, `annotate_method_role(..., role_by_name=...)`
- UI sections order: backbone → aggregator → classical_ml → tool → unknown

- [ ] **Step 1: Wire weekly_hotspot**

Where `annotate_method_role(methods)` (and combos / opportunities) is called:

```python
from analysis.method_role import annotate_method_role, load_method_roles

role_map = load_method_roles()
annotate_method_role(methods, role_by_name=role_map)
...
annotate_method_role(combos, name_key="method", role_by_name=role_map)
annotate_method_role(combos_by_method, name_key="method", role_by_name=role_map)
# opportunities:
annotate_method_role(rows, name_key="method", role_by_name=load_method_roles())
```

Calling `load_method_roles()` once per `compute_weekly_hotspots` is enough; pass the same map into opportunity compute if payload already annotated methods — opportunities can call `load_method_roles()` once at start of `compute_emerging_gap_opportunities`.

- [ ] **Step 2: Gap UI five sections**

```python
_METHOD_ROLE_SECTIONS = (
    ("backbone", "基座 / 骨干"),
    ("aggregator", "聚合器 / 贡献模块"),
    ("classical_ml", "传统 ML"),
    ("tool", "工具 / 平台"),
    ("unknown", "未分类"),
)

def _render_methods_by_role(rows: list[dict]) -> None:
    buckets = {k: [] for k, _ in _METHOD_ROLE_SECTIONS}
    for row in rows or []:
        role = str(row.get("method_role") or "unknown")
        if role not in buckets:
            role = "unknown"
        buckets[role].append(row)
    if not any(buckets[k] for k, _ in _METHOD_ROLE_SECTIONS):
        st.info("本窗口暂无方法条目。")
        return
    for key, title in _METHOD_ROLE_SECTIONS:
        part = buckets[key]
        if not part:
            continue
        st.subheader(f"{title}（{len(part)}）")
        safe_table(pd.DataFrame(part))
```

Methods tab captions + emerging/active both use `_render_methods_by_role`.

Ensure combo/opportunity column lists include `method_role` after `method`.

- [ ] **Step 3: Test**

Extend `test_weekly_hotspot_method_role.py` with one case: insert Method with stored role differing from pure heuristic if easy — or assert `classical_ml` name gets that role after annotate with map.

At minimum re-run:

```bash
..\.venv\Scripts\python.exe -m pytest tests/test_method_role.py tests/test_method_role_db.py tests/test_weekly_hotspot_method_role.py tests/test_triple_method_role_hint.py -v
```

- [ ] **Step 4: Manual** — run `py main.py backfill-method-roles` on real DB once (operator); refresh Streamlit 每周热点.

- [ ] **Step 5: Commit** (if in scope)

```bash
git commit -m "feat: use DB method_role in hotspot UI five sections"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Five-value vocabulary + rule order | Task 1 |
| `resolve_method_role` merge | Task 1 |
| `entities.method_role` + migrate | Task 2 |
| upsert insert/update policy | Task 2 |
| backfill CLI + SCRIPTS | Task 2 |
| Triple `method_role_hint` + prompt | Task 3 |
| Section ingest wiring | Task 3 |
| Hotspot prefers DB | Task 4 |
| UI five sections | Task 4 |
| No score/maturity changes | Global / Tasks 2–4 annotate-only |

## Out of scope

- Finer roles, snapshot role column, LLM-primary authority, forced re-extract.
