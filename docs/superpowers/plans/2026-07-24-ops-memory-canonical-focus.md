# Ops Memory Canonical Focus Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ops memory `focus_key` use disease-concept canonical names so ZH/EN synonyms (e.g. `乳腺癌` / `breast cancer`) share one memory lane.

**Architecture:** Extend `normalize_focus_key` to call `resolve_disease_concept` and return `concept.canonical` when known; keep `focus_raw` as typed text. Add an idempotent migrate in `init_db` that rewrites legacy `ops_runs.focus_key` rows to canonical. Load/clear already go through `normalize_focus_key`, so no UI SQL changes.

**Tech Stack:** Python 3, SQLite (`kg_fulltext.db`), existing `analysis/disease_synonyms.py` / `analysis/ops_memory.py` / `db/schema.py`, unittest-style tests under `fulltext_workflow/tests/`.

**Spec:** [`docs/superpowers/specs/2026-07-24-ops-memory-canonical-focus-design.md`](../specs/2026-07-24-ops-memory-canonical-focus-design.md)

## Global Constraints

- Key strategy A only: store lowercase `concept.canonical` when resolve succeeds; else literal normalized string; empty → `__all__`.
- Do not expand `DISEASE_CONCEPTS`; do not change corpus `focus_filter` SQL.
- Prefer fail-loud on migrate UPDATE errors (local SQLite).
- Avoid circular imports: `db/schema.py` must late-import migrate helper from `ops_memory` only inside the migrate call (not at module top).
- Commits only when the user asks (do not auto-commit unless explicitly requested in the session).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/ops_memory.py` | Canonical `normalize_focus_key`; `migrate_ops_focus_keys(conn)` |
| `fulltext_workflow/db/schema.py` | Call migrate at end of `_migrate_db` via late import |
| `fulltext_workflow/tests/test_ops_memory.py` | ZH/EN equality, unresolved, migrate+load, clear-scope |
| `fulltext_workflow/PIPELINE.md` | One-line note that ops `focus_key` is concept canonical when known |

No new files. No schema DDL changes.

---

### Task 1: Canonical `normalize_focus_key` (TDD)

**Files:**
- Modify: `fulltext_workflow/analysis/ops_memory.py` (`normalize_focus_key`)
- Modify: `fulltext_workflow/tests/test_ops_memory.py`
- Test: `fulltext_workflow/tests/test_ops_memory.py`

**Interfaces:**
- Consumes: `analysis.disease_synonyms.resolve_disease_concept(focus: str | None) -> DiseaseConcept | None` (field `canonical: str`)
- Produces: `normalize_focus_key(focus: str | None) -> str` — empty → `__all__`; resolved → whitespace-normalized lowercase `concept.canonical`; else literal strip/lower

- [ ] **Step 1: Write the failing tests**

Add to `fulltext_workflow/tests/test_ops_memory.py` (keep existing `test_normalize_focus_key_lower_strip` — NPC string already equals its canonical):

```python
def test_normalize_focus_key_zh_en_same_lane():
    assert normalize_focus_key("乳腺癌") == "breast carcinoma"
    assert normalize_focus_key("breast cancer") == "breast carcinoma"
    assert normalize_focus_key("Breast Cancer") == "breast carcinoma"
    assert normalize_focus_key("乳腺癌") == normalize_focus_key("breast cancer")


def test_normalize_focus_key_unresolved_literal():
    assert normalize_focus_key("  Foo Bar ") == "foo bar"
```

Register both in the `if __name__ == "__main__":` `tests` list.

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd fulltext_workflow
& ..\.venv\Scripts\python.exe tests\test_ops_memory.py
```

Expected: `test_normalize_focus_key_zh_en_same_lane` fails — `"breast cancer" != "breast carcinoma"` (or `"乳腺癌" != "breast carcinoma"`).

- [ ] **Step 3: Implement minimal `normalize_focus_key`**

In `fulltext_workflow/analysis/ops_memory.py`, replace `normalize_focus_key` with:

```python
def normalize_focus_key(focus: str | None) -> str:
    if focus is None:
        return "__all__"
    s = " ".join(str(focus).strip().lower().split())
    if not s:
        return "__all__"
    from analysis.disease_synonyms import resolve_disease_concept

    concept = resolve_disease_concept(s)
    if concept is not None:
        return " ".join(str(concept.canonical).strip().lower().split())
    return s
```

Use a function-local import (same pattern as elsewhere) to keep module import light and avoid cycles.

- [ ] **Step 4: Run tests to verify they pass**

```powershell
cd fulltext_workflow
& ..\.venv\Scripts\python.exe tests\test_ops_memory.py
```

Expected: all tests PASS, including the two new ones and existing NPC / lookback tests (`npc` abbreviation resolves to `nasopharyngeal carcinoma` consistently).

- [ ] **Step 5: Commit (only if user requested commits)**

```bash
git add fulltext_workflow/analysis/ops_memory.py fulltext_workflow/tests/test_ops_memory.py
git commit -m "fix: canonicalize ops memory focus_key via disease synonyms"
```

---

### Task 2: Idempotent DB migrate of legacy `ops_runs.focus_key`

**Files:**
- Modify: `fulltext_workflow/analysis/ops_memory.py` (add `migrate_ops_focus_keys`)
- Modify: `fulltext_workflow/db/schema.py` (end of `_migrate_db`)
- Modify: `fulltext_workflow/tests/test_ops_memory.py`
- Test: `fulltext_workflow/tests/test_ops_memory.py`

**Interfaces:**
- Consumes: `normalize_focus_key` from Task 1; open `sqlite3.Connection` with `ops_runs` table
- Produces: `migrate_ops_focus_keys(conn: sqlite3.Connection) -> int` — number of rows updated; rewrites `focus_key` when `normalize_focus_key(old) != old`; skips `__all__`; idempotent

- [ ] **Step 1: Write the failing migrate + cross-language load test**

```python
def test_migrate_legacy_focus_key_then_zh_load():
    from db.schema import get_conn

    _reset_ops_db()
    # Simulate pre-fix row: literal English phrase, not canonical
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ops_runs
               (week_id, focus_raw, focus_key, source, started_at, finished_at)
               VALUES ('2026-W30', 'breast cancer', 'breast cancer', 'test',
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """INSERT INTO ops_gap_items
               (run_id, rank_pos, title, research_question, fingerprint, status)
               VALUES (?, 1, 'Legacy breast gap', 'RQ?', 'deadbeefdeadbeef', 'reported')""",
            (run_id,),
        )

    from analysis.ops_memory import migrate_ops_focus_keys

    with get_conn() as conn:
        n = migrate_ops_focus_keys(conn)
        assert n >= 1
        key = conn.execute(
            "SELECT focus_key FROM ops_runs WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        assert key == "breast carcinoma"
        # idempotent
        assert migrate_ops_focus_keys(conn) == 0

    mem = load_recent_gaps("乳腺癌")
    assert any(it.title == "Legacy breast gap" for it in mem.items)
    assert mem.focus_key == "breast carcinoma"
```

Register in `__main__` list.

- [ ] **Step 2: Run test to verify it fails**

```powershell
cd fulltext_workflow
& ..\.venv\Scripts\python.exe -c "from tests.test_ops_memory import test_migrate_legacy_focus_key_then_zh_load; test_migrate_legacy_focus_key_then_zh_load()"
```

Expected: FAIL with `ImportError` / `AttributeError` for `migrate_ops_focus_keys`.

- [ ] **Step 3: Implement `migrate_ops_focus_keys` and wire into `_migrate_db`**

Add to `fulltext_workflow/analysis/ops_memory.py`:

```python
def migrate_ops_focus_keys(conn) -> int:
    """Rewrite ops_runs.focus_key to disease canonical when resolvable. Idempotent."""
    rows = conn.execute(
        "SELECT run_id, focus_key FROM ops_runs WHERE focus_key != '__all__'"
    ).fetchall()
    updated = 0
    for row in rows:
        run_id = row["run_id"] if hasattr(row, "keys") else row[0]
        old = row["focus_key"] if hasattr(row, "keys") else row[1]
        new = normalize_focus_key(old)
        if new != old:
            conn.execute(
                "UPDATE ops_runs SET focus_key=? WHERE run_id=?",
                (new, run_id),
            )
            updated += 1
    return updated
```

At the **end** of `_migrate_db` in `fulltext_workflow/db/schema.py` (after proposal column ALTERs), add:

```python
    # Ops memory: collapse synonym spellings onto disease canonical focus_key
    try:
        from analysis.ops_memory import migrate_ops_focus_keys
    except ImportError:
        migrate_ops_focus_keys = None  # type: ignore
    if migrate_ops_focus_keys is not None:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "ops_runs" in tables:
            migrate_ops_focus_keys(conn)
```

Do **not** import `analysis.ops_memory` at the top of `schema.py`.

- [ ] **Step 4: Run full ops memory tests**

```powershell
cd fulltext_workflow
& ..\.venv\Scripts\python.exe tests\test_ops_memory.py
```

Expected: all PASS. Optionally smoke production migrate:

```powershell
& ..\.venv\Scripts\python.exe -c "from db.schema import init_db; init_db()"
```

Then confirm `breast cancer` / `肠息肉` rows (if present) show canonical keys.

- [ ] **Step 5: Commit (only if user requested commits)**

```bash
git add fulltext_workflow/analysis/ops_memory.py fulltext_workflow/db/schema.py fulltext_workflow/tests/test_ops_memory.py
git commit -m "fix: migrate ops_runs focus_key to disease canonical"
```

---

### Task 3: Docs note + acceptance check

**Files:**
- Modify: `fulltext_workflow/PIPELINE.md` (Ops memory bullet ~284–289)
- Test: manual / existing tests (no new test file)

**Interfaces:**
- Consumes: Task 1–2 behavior
- Produces: one-line doc clarifying canonical `focus_key`

- [ ] **Step 1: Update PIPELINE.md Ops memory section**

Change the `focus_key` bullet to note synonyms share a lane, e.g.:

```markdown
- 按 `focus_key`（无 focus → `__all__`；已知疾病概念 → `disease_synonyms` canonical，如 `乳腺癌`/`breast cancer` → `breast carcinoma`）回看最近 **4** 次空白，prompt **软避让**近重复方向（非硬过滤）
```

Optional one-liner under Research focus section: ops memory uses the same resolve for its lane key.

- [ ] **Step 2: Acceptance smoke (local DB)**

```powershell
cd fulltext_workflow
& ..\.venv\Scripts\python.exe -c "
from db.schema import init_db, get_conn
from analysis.ops_memory import normalize_focus_key, load_recent_gaps
init_db()
print('bc', normalize_focus_key('breast cancer'))
print('zh', normalize_focus_key('乳腺癌'))
print('items', len(load_recent_gaps('乳腺癌').items))
with get_conn() as c:
    for r in c.execute('SELECT run_id, focus_key, focus_raw FROM ops_runs'):
        print(dict(r))
"
```

Expected: both normalize to `breast carcinoma`; if a prior breast-cancer run existed, `load_recent_gaps('乳腺癌').items` non-empty; `clear_ops_memory.py --focus "乳腺癌"` (dry-run) counts that lane.

- [ ] **Step 3: Commit (only if user requested commits)**

```bash
git add fulltext_workflow/PIPELINE.md
git commit -m "docs: note ops memory focus_key uses disease canonical"
```

---

## Spec coverage (self-review)

| Spec requirement | Task |
|------------------|------|
| Canonical `normalize_focus_key` via resolve | Task 1 |
| Keep `focus_raw` as typed string | unchanged API; Task 1 only changes key |
| Migrate legacy keys on init | Task 2 |
| Load/clear ZH finds EN lane | Task 2 test + existing clear uses `normalize_focus_key` |
| Unresolved literal | Task 1 `test_normalize_focus_key_unresolved_literal` |
| Docs one-liner | Task 3 |
| No dictionary / focus_filter / fingerprint changes | out of scope — no tasks |

Placeholder scan: none. Types: `migrate_ops_focus_keys(conn) -> int` consistent across Task 2 steps.
