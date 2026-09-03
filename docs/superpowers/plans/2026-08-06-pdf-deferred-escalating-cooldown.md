# PDF Deferred Queue + Escalating Cooldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop treating PDF-limit skips as hard failures; keep them as `jats_unavailable` for the next PDF pass; prefer never-tried papers via `fulltext_pdf_attempts`; escalate cooldown only after real PDF failures (`7→14→28→56`).

**Architecture:** Add `fulltext_pdf_attempts` + migrate. Change `requeue_cooled_fulltext_failures` to only reset cooled `unavailable` with per-attempt cooldown. Change PDF selection/order/increment; remove bulk finalize-to-unavailable. Idempotent backlog repair for `unavailable` with attempts=0.

**Tech Stack:** Python 3, SQLite, existing fulltext fetcher, pytest.

**Spec:** `docs/superpowers/specs/2026-08-06-pdf-deferred-escalating-cooldown-design.md`

## Global Constraints

- Do **not** bulk-mark leftover `jats_unavailable` as `unavailable`.
- Requeue **only** `unavailable` (force_retry also only `unavailable`).
- Increment attempts only when entering the PDF attempt loop; limit-skipped do not increment.
- Cooldown days: `min(56, base * 2**(max(a,1)-1))` with `base=FULLTEXT_RETRY_COOLDOWN_DAYS` (default 7) → 7/14/28/56.
- PDF order: `fulltext_pdf_attempts ASC, year IS NULL, year DESC, created_at DESC`.
- Do not change default `FULLTEXT_PDF_RETRY_LIMIT=500`.
- Run pytest from `fulltext_workflow/`.
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `data/`, `raw/`, `output/`, or secrets.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/db/schema.py` | Column migrate; escalate requeue; increment helper; backlog repair |
| `fulltext_workflow/fetcher/fulltext_fetcher.py` | PDF order/increment; drop bulk finalize; repair + stats |
| `fulltext_workflow/tests/test_fulltext_retry.py` | Replace outdated expectations; add new cases |
| `fulltext_workflow/PIPELINE.md` / `SCRIPTS.md` | Document new semantics |

---

### Task 1: Schema — attempts column, escalating requeue, backlog repair

**Files:**
- Modify: `fulltext_workflow/db/schema.py`
- Modify: `fulltext_workflow/db/__init__.py` (export new helpers if peers exported)
- Modify: `fulltext_workflow/tests/test_fulltext_retry.py` (requeue-related tests)

**Interfaces:**
- Produces:
  - Column `papers.fulltext_pdf_attempts INTEGER DEFAULT 0` (CREATE + `_migrate_db`)
  - `cooldown_days_for_pdf_attempts(attempts: int, *, base_days: int = 7) -> int`
  - `requeue_cooled_fulltext_failures(*, cooldown_days: int, force: bool = False) -> int` — **only** `unavailable`; escalating predicate when not force
  - `increment_fulltext_pdf_attempts(paper_id: int) -> int` — returns new count
  - `repair_misclassified_unavailable_without_pdf_attempt() -> int`

- [ ] **Step 1: Write / update failing tests**

In `tests/test_fulltext_retry.py`:

1. **Change** `test_requeue_resets_cooled_unavailable_and_jats` → rename to `test_requeue_resets_only_cooled_unavailable` and assert `jats_unavailable` is **not** reset (stays `jats_unavailable`); only `unavailable` → `pending`.

2. **Add:**

```python
from db.schema import (
    cooldown_days_for_pdf_attempts,
    increment_fulltext_pdf_attempts,
    repair_misclassified_unavailable_without_pdf_attempt,
)


def test_cooldown_days_schedule():
    assert cooldown_days_for_pdf_attempts(0) == 7
    assert cooldown_days_for_pdf_attempts(1) == 7
    assert cooldown_days_for_pdf_attempts(2) == 14
    assert cooldown_days_for_pdf_attempts(3) == 28
    assert cooldown_days_for_pdf_attempts(4) == 56
    assert cooldown_days_for_pdf_attempts(9) == 56


def test_requeue_escalating_cooldown_by_attempts(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "1", "title": "A", "year": 2025})
    p2 = upsert_paper({"pmid": "2", "title": "B", "year": 2024})
    mark_fulltext_status(p1, "unavailable")
    mark_fulltext_status(p2, "unavailable")
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=1 WHERE id=?", (p1,)
        )
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=2 WHERE id=?", (p2,)
        )
    _set_fetched_at(p1, 8)   # needs 7 → eligible
    _set_fetched_at(p2, 8)   # needs 14 → not eligible
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=False)
    assert n == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: r["full_text_status"]
            for r in conn.execute("SELECT pmid, full_text_status FROM papers")
        }
    assert rows["1"] == "pending"
    assert rows["2"] == "unavailable"


def test_repair_misclassified_unavailable(monkeypatch):
    _tmp_db(monkeypatch)
    p0 = upsert_paper({"pmid": "10", "title": "Z", "year": 2025})
    p1 = upsert_paper({"pmid": "11", "title": "Y", "year": 2024})
    mark_fulltext_status(p0, "unavailable")
    mark_fulltext_status(p1, "unavailable")
    with get_conn() as conn:
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=0 WHERE id=?", (p0,)
        )
        conn.execute(
            "UPDATE papers SET fulltext_pdf_attempts=2 WHERE id=?", (p1,)
        )
    n = repair_misclassified_unavailable_without_pdf_attempt()
    assert n == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: (r["full_text_status"], r["fulltext_pdf_attempts"])
            for r in conn.execute(
                "SELECT pmid, full_text_status, fulltext_pdf_attempts FROM papers"
            )
        }
    assert rows["10"] == ("jats_unavailable", 0)
    assert rows["11"][0] == "unavailable"
```

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v --tb=short
```

- [ ] **Step 3: Implement schema pieces**

1. Add to `CREATE TABLE papers` and `_migrate_db` papers loop:

```python
("fulltext_pdf_attempts", "ALTER TABLE papers ADD COLUMN fulltext_pdf_attempts INTEGER DEFAULT 0"),
```

2. Helpers:

```python
def cooldown_days_for_pdf_attempts(
    attempts: int, *, base_days: int = 7, cap_days: int = 56
) -> int:
    a = max(int(attempts or 0), 1)
    return min(int(cap_days), int(base_days) * (2 ** (a - 1)))


def increment_fulltext_pdf_attempts(paper_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET
                   fulltext_pdf_attempts = COALESCE(fulltext_pdf_attempts, 0) + 1
               WHERE id=?""",
            (paper_id,),
        )
        row = conn.execute(
            "SELECT fulltext_pdf_attempts FROM papers WHERE id=?",
            (paper_id,),
        ).fetchone()
        return int(row[0])


def repair_misclassified_unavailable_without_pdf_attempt() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE papers SET full_text_status='jats_unavailable'
               WHERE full_text_status='unavailable'
                 AND COALESCE(fulltext_pdf_attempts, 0)=0
                 AND pmid IS NOT NULL"""
        )
        return int(cur.rowcount)


def requeue_cooled_fulltext_failures(
    *,
    cooldown_days: int,
    force: bool = False,
) -> int:
    if cooldown_days < 0:
        raise ValueError("cooldown_days must be >= 0")
    with get_conn() as conn:
        if force:
            cur = conn.execute(
                """UPDATE papers SET
                       full_text_status='pending',
                       full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE full_text_status='unavailable'
                     AND pmid IS NOT NULL"""
            )
        else:
            # Escalating: base, 2x, 4x, 8x capped at 56 (when base=7).
            cur = conn.execute(
                """UPDATE papers SET
                       full_text_status='pending',
                       full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE full_text_status='unavailable'
                     AND pmid IS NOT NULL
                     AND (
                       full_text_fetched_at IS NULL
                       OR julianday('now') - julianday(full_text_fetched_at)
                          >= CASE
                               WHEN COALESCE(fulltext_pdf_attempts, 0) <= 1
                                 THEN ?
                               WHEN fulltext_pdf_attempts = 2
                                 THEN ?
                               WHEN fulltext_pdf_attempts = 3
                                 THEN ?
                               ELSE ?
                             END
                     )""",
                (
                    float(cooldown_days_for_pdf_attempts(1, base_days=cooldown_days)),
                    float(cooldown_days_for_pdf_attempts(2, base_days=cooldown_days)),
                    float(cooldown_days_for_pdf_attempts(3, base_days=cooldown_days)),
                    float(cooldown_days_for_pdf_attempts(4, base_days=cooldown_days)),
                ),
            )
        return int(cur.rowcount)
```

Update docstring of `requeue_cooled_fulltext_failures` accordingly.

Export new symbols from `db/__init__.py` if that module re-exports peers.

- [ ] **Step 4: Run Task 1–scoped tests — expect PASS**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -k "requeue or cooldown or repair" -v
```

- [ ] **Step 5: Commit (only if plan-exec includes commits)**

```bash
git add fulltext_workflow/db/schema.py fulltext_workflow/db/__init__.py fulltext_workflow/tests/test_fulltext_retry.py
git commit -m "feat: escalate fulltext cooldown and repair misclassified unavailable"
```

---

### Task 2: Fetcher — deferred PDF queue, attempt priority, drop bulk finalize

**Files:**
- Modify: `fulltext_workflow/fetcher/fulltext_fetcher.py`
- Modify: `fulltext_workflow/tests/test_fulltext_retry.py`
- Modify: `fulltext_workflow/PIPELINE.md`
- Modify: `fulltext_workflow/SCRIPTS.md`

**Interfaces:**
- Consumes: `increment_fulltext_pdf_attempts`, `repair_misclassified_unavailable_without_pdf_attempt`, updated requeue
- Produces: `fetch_pdf_mineru_fallback` increments attempts; limit-skipped stay `jats_unavailable`; `fetch_all_fulltext` calls repair; stats include `pdf_deferred`; remove use of bulk finalize (delete function or leave unused — prefer delete if only used here)

- [ ] **Step 1: Replace outdated PDF limit test + add order/attempts tests**

Replace `test_pdf_fallback_respects_limit_and_marks_rest_unavailable` with:

```python
def test_pdf_fallback_limit_leaves_untried_as_jats_unavailable(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    # attempts=1 older year should still sort after attempts=0
    for i, (year, attempts) in enumerate(
        ((2025, 1), (2024, 0), (2023, 0)), start=1
    ):
        pid = upsert_paper(
            {
                "pmid": str(i),
                "doi": f"10.1/{i}",
                "title": f"T{i}",
                "year": year,
            }
        )
        mark_fulltext_status(pid, "jats_unavailable")
        with get_conn() as conn:
            conn.execute(
                "UPDATE papers SET fulltext_pdf_attempts=? WHERE id=?",
                (attempts, pid),
            )

    calls: list[str] = []

    def fake_download(doi, pmid):
        calls.append(pmid)
        return {"success": False}

    monkeypatch.setattr(ff, "download_pdf", fake_download)
    monkeypatch.setattr(ff, "pdf_to_sections", lambda *a, **k: [])

    ok = ff.fetch_pdf_mineru_fallback(limit=2)
    assert ok == 0
    # never-tried first (pmid 2 year 2024, pmid 3 year 2023), then attempted
    assert calls == ["2", "3"]

    with get_conn() as conn:
        rows = {
            r["pmid"]: (r["full_text_status"], r["fulltext_pdf_attempts"])
            for r in conn.execute(
                "SELECT pmid, full_text_status, fulltext_pdf_attempts FROM papers"
            )
        }
    assert rows["2"][0] == "unavailable" and rows["2"][1] == 1
    assert rows["3"][0] == "unavailable" and rows["3"][1] == 1
    assert rows["1"] == ("jats_unavailable", 1)  # not attempted this run


def test_fetch_all_does_not_finalize_deferred(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "50", "doi": "10.1/50", "title": "T", "year": 2025}
    )
    mark_fulltext_status(pid, "jats_unavailable")
    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)
    monkeypatch.setattr(
        ff, "repair_misclassified_unavailable_without_pdf_attempt", lambda: 0
    )
    # repair is imported from schema inside fetch_all — patch schema or allow real repair

    stats = ff.fetch_all_fulltext(retry=False, pdf_retry_limit=0)
    assert stats.get("pdf_deferred", 0) >= 1
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "jats_unavailable"
```

Implementer note: for `test_fetch_all_does_not_finalize_deferred`, call real `fetch_all_fulltext` with `fetch_pdf_mineru_fallback` returning 0 without consuming the jats row (mock returns 0 immediately). Ensure `finalize_jats_unavailable_as_unavailable` is **not** called. Prefer deleting that function.

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v --tb=short
```

- [ ] **Step 3: Implement fetcher changes**

```python
from db.schema import (
    ...
    increment_fulltext_pdf_attempts,
    repair_misclassified_unavailable_without_pdf_attempt,
)

def _papers_for_pdf_fallback(limit: int | None = None) -> list[sqlite3.Row]:
    _validate_pdf_retry_limit(limit, param="limit")
    sql = """
        SELECT id, pmid, doi, pmc_id, full_text_status, year, created_at,
               COALESCE(fulltext_pdf_attempts, 0) AS fulltext_pdf_attempts
        FROM papers
        WHERE pmid IS NOT NULL AND full_text_status = 'jats_unavailable'
        ORDER BY COALESCE(fulltext_pdf_attempts, 0) ASC,
                 year IS NULL, year DESC, created_at DESC
    """
    ...


def fetch_pdf_mineru_fallback(limit: int | None = None) -> int:
    pending = _papers_for_pdf_fallback(limit=limit)
    ...
    for row in tqdm(...):
        paper_id = row["id"]
        increment_fulltext_pdf_attempts(paper_id)
        ...
        # existing failure paths mark unavailable; success pdf_available


def fetch_all_fulltext(...):
    repaired = repair_misclassified_unavailable_without_pdf_attempt()
    if repaired:
        print(f"[Fulltext] Repaired {repaired} misclassified unavailable→jats_unavailable.")

    # requeue as today (updated semantics)
    ...
    fetch_jats_fulltext(...)
    # count pool, run PDF with limit
    pdf_ok = fetch_pdf_mineru_fallback(limit=effective_limit)

    with get_conn() as conn:
        deferred = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='jats_unavailable'"
        ).fetchone()[0]
        ...

    # DO NOT call finalize_jats_unavailable_as_unavailable
    stats = {..., "pdf_deferred": deferred, ...}
```

Delete `finalize_jats_unavailable_as_unavailable` if unused.

- [ ] **Step 4: Docs**

`PIPELINE.md` Phase 3 / retry note: deferred `jats_unavailable`, attempts priority, escalating cooldown, no bulk finalize.

`SCRIPTS.md`: one-line mention of `fulltext_pdf_attempts` / escalating cooldown.

- [ ] **Step 5: Full related suite**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit (only if plan-exec includes commits)**

```bash
git add fulltext_workflow/fetcher/fulltext_fetcher.py fulltext_workflow/tests/test_fulltext_retry.py fulltext_workflow/PIPELINE.md fulltext_workflow/SCRIPTS.md
git commit -m "feat: defer PDF-limit skips and prioritize never-tried papers"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `fulltext_pdf_attempts` column | Task 1 |
| Requeue only unavailable + escalating 7/14/28/56 | Task 1 |
| force_retry only unavailable | Task 1 |
| Backlog repair attempts=0 | Task 1–2 |
| PDF order attempts ASC | Task 2 |
| Increment only on attempt | Task 2 |
| No bulk finalize | Task 2 |
| `pdf_deferred` log/stats | Task 2 |
| Docs | Task 2 |
| Tests listed in spec | Tasks 1–2 |

## Out of scope

- Changing PDF limit default
- Ops UI controls
- Requeueing `jats_unavailable` under force_retry
