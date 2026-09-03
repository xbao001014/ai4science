# Fulltext Retry with Cooldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `fetch-fulltext` re-enqueue cooled-down `unavailable` / `jats_unavailable` papers so weekly updates can backfill fulltext that appeared after the first failed attempt.

**Architecture:** At the start of `fetch_all_fulltext`, reset cooldown-eligible failures to `pending`. Tier-1 JATS stays uncapped. Tier-2 PDF/MinerU takes a capped, newest-first slice of `jats_unavailable`; the remainder is marked `unavailable` with a refreshed `full_text_fetched_at`. Weekly ops keep a single `fetch-fulltext` step and inherit default retry behavior.

**Tech Stack:** Python 3, SQLite via `db.schema`, existing JATS/ScanSci/MinerU fetchers, pytest, argparse CLI.

**Spec:** `docs/superpowers/specs/2026-08-04-fulltext-retry-cooldown-design.md`

## Global Constraints

- Do **not** change `extraction_done` or `reconcile_status` (abstract→fulltext upgrade is a later spec).
- Do **not** add `fulltext_attempt_count` or new status values; reuse `pending` / `unavailable` / `jats_unavailable`.
- Do **not** add a new weekly ops step; `build_weekly_argv("fetch-fulltext")` stays `["fetch-fulltext"]`.
- Defaults: `FULLTEXT_RETRY_COOLDOWN_DAYS=7`, `FULLTEXT_PDF_RETRY_LIMIT=500` (`0` = unlimited PDF).
- Never re-fetch papers already `available` or `pdf_available`.
- Run pytest from `fulltext_workflow/` (tests insert that root on `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `fulltext_workflow/data/`, `raw/`, `output/`, or secrets.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/config.py` | Add `FULLTEXT_RETRY_COOLDOWN_DAYS`, `FULLTEXT_PDF_RETRY_LIMIT` |
| `fulltext_workflow/db/schema.py` | Add `requeue_cooled_fulltext_failures(...)` |
| `fulltext_workflow/fetcher/fulltext_fetcher.py` | Enqueue retry; PDF limit + ordered selection; summary counters; wire flags |
| `fulltext_workflow/main.py` | CLI `--no-retry`, `--force-retry`, `--pdf-retry-limit` |
| `fulltext_workflow/tests/test_fulltext_retry.py` | **New** — cooldown requeue + PDF cap (temp DB, no live PMC) |
| `fulltext_workflow/tests/test_ops_jobs.py` | Assert weekly argv for `fetch-fulltext` unchanged |
| `fulltext_workflow/PIPELINE.md` | Note cooldown retry behavior |
| `fulltext_workflow/SCRIPTS.md` | Document new flags / env |

---

### Task 1: Config + requeue helper

**Files:**
- Modify: `fulltext_workflow/config.py`
- Modify: `fulltext_workflow/db/schema.py`
- Create: `fulltext_workflow/tests/test_fulltext_retry.py`

**Interfaces:**
- Consumes: `get_conn`, existing `papers.full_text_status` / `full_text_fetched_at`
- Produces:
  - `config.FULLTEXT_RETRY_COOLDOWN_DAYS: int` (default 7)
  - `config.FULLTEXT_PDF_RETRY_LIMIT: int` (default 500)
  - `requeue_cooled_fulltext_failures(*, cooldown_days: int, force: bool = False) -> int` — number of rows reset to `pending`

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_fulltext_retry.py`:

```python
"""Tests for fulltext cooldown requeue and PDF retry limit."""
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
    mark_fulltext_status,
    requeue_cooled_fulltext_failures,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _set_fetched_at(paper_id: int, days_ago: float) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE papers SET full_text_fetched_at =
                   datetime('now', ?) WHERE id=?""",
            (f"-{days_ago} days", paper_id),
        )


def test_requeue_skips_fresh_unavailable(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "1", "title": "A", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 2)
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=False)
    assert n == 0
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "unavailable"


def test_requeue_resets_cooled_unavailable_and_jats(monkeypatch):
    _tmp_db(monkeypatch)
    p1 = upsert_paper({"pmid": "1", "title": "A", "year": 2025})
    p2 = upsert_paper({"pmid": "2", "title": "B", "year": 2024})
    p3 = upsert_paper({"pmid": "3", "title": "C", "year": 2023})
    mark_fulltext_status(p1, "unavailable")
    mark_fulltext_status(p2, "jats_unavailable")
    mark_fulltext_status(p3, "available")
    _set_fetched_at(p1, 8)
    _set_fetched_at(p2, 8)
    _set_fetched_at(p3, 8)
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=False)
    assert n == 2
    with get_conn() as conn:
        rows = {
            r["pmid"]: r["full_text_status"]
            for r in conn.execute(
                "SELECT pmid, full_text_status FROM papers"
            ).fetchall()
        }
    assert rows["1"] == "pending"
    assert rows["2"] == "pending"
    assert rows["3"] == "available"


def test_force_requeue_ignores_cooldown(monkeypatch):
    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "9", "title": "F", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 0.1)
    n = requeue_cooled_fulltext_failures(cooldown_days=7, force=True)
    assert n == 1
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v
```

Expected: FAIL with `ImportError` / `requeue_cooled_fulltext_failures` not found (or similar).

- [ ] **Step 3: Add config defaults**

In `fulltext_workflow/config.py`, after the MinerU/PDF block (near `MINERU_DEVICE`), add:

```python
# Cooldown retry for papers previously marked unavailable / jats_unavailable
FULLTEXT_RETRY_COOLDOWN_DAYS: int = int(
    os.getenv("FULLTEXT_RETRY_COOLDOWN_DAYS", "7")
)
# Max ScanSci+MinerU attempts per fetch-fulltext run; 0 = unlimited
FULLTEXT_PDF_RETRY_LIMIT: int = int(os.getenv("FULLTEXT_PDF_RETRY_LIMIT", "500"))
```

- [ ] **Step 4: Implement `requeue_cooled_fulltext_failures`**

In `fulltext_workflow/db/schema.py`, near `mark_fulltext_status` / `get_papers_needing_fulltext`, add:

```python
def requeue_cooled_fulltext_failures(
    *,
    cooldown_days: int,
    force: bool = False,
) -> int:
    """Reset cooled-down unavailable/jats_unavailable papers to pending.

    Returns the number of rows updated. Does not touch available/pdf_available
    or extraction/reconcile flags.
    """
    if cooldown_days < 0:
        raise ValueError("cooldown_days must be >= 0")
    with get_conn() as conn:
        if force:
            cur = conn.execute(
                """UPDATE papers SET
                       full_text_status='pending',
                       full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE full_text_status IN ('unavailable', 'jats_unavailable')
                     AND pmid IS NOT NULL"""
            )
        else:
            cur = conn.execute(
                """UPDATE papers SET
                       full_text_status='pending',
                       full_text_fetched_at=CURRENT_TIMESTAMP
                   WHERE full_text_status IN ('unavailable', 'jats_unavailable')
                     AND pmid IS NOT NULL
                     AND (
                       full_text_fetched_at IS NULL
                       OR julianday('now') - julianday(full_text_fetched_at)
                          >= ?
                     )""",
                (float(cooldown_days),),
            )
        return int(cur.rowcount)
```

Export the symbol from `fulltext_workflow/db/__init__.py` only if that module already re-exports peer helpers; otherwise import from `db.schema` in callers (match existing pattern).

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v
```

Expected: PASS for the three requeue tests.

- [ ] **Step 6: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/config.py fulltext_workflow/db/schema.py fulltext_workflow/tests/test_fulltext_retry.py
git commit -m "feat: requeue cooled-down fulltext failures to pending"
```

---

### Task 2: PDF/MinerU limit + fetch_all_fulltext wiring

**Files:**
- Modify: `fulltext_workflow/fetcher/fulltext_fetcher.py`
- Modify: `fulltext_workflow/tests/test_fulltext_retry.py`

**Interfaces:**
- Consumes: `requeue_cooled_fulltext_failures`, `config.FULLTEXT_RETRY_COOLDOWN_DAYS`, `config.FULLTEXT_PDF_RETRY_LIMIT`, existing `fetch_jats_fulltext` / `download_pdf` / `pdf_to_sections`
- Produces:
  - `fetch_all_fulltext(cache_xml: bool = True, *, retry: bool = True, force_retry: bool = False, pdf_retry_limit: int | None = None) -> dict[str, int]`
  - Return / log keys at least: `retried_into_pending`, `pdf_attempted`, `pdf_ok`, `pdf_skipped_by_limit` (plus existing totals printed)

- [ ] **Step 1: Extend failing tests for PDF cap**

Append to `tests/test_fulltext_retry.py`:

```python
def test_pdf_fallback_respects_limit_and_marks_rest_unavailable(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    for i, year in enumerate((2025, 2024, 2023), start=1):
        pid = upsert_paper(
            {
                "pmid": str(i),
                "doi": f"10.1/{i}",
                "title": f"T{i}",
                "year": year,
            }
        )
        mark_fulltext_status(pid, "jats_unavailable")

    calls: list[str] = []

    def fake_download(doi, pmid):
        calls.append(pmid)
        return {"success": False}

    monkeypatch.setattr(ff, "download_pdf", fake_download)
    monkeypatch.setattr(ff, "pdf_to_sections", lambda *a, **k: [])

    ok = ff.fetch_pdf_mineru_fallback(limit=2)
    assert ok == 0
    assert calls == ["1", "2"]  # newest year first

    with get_conn() as conn:
        skipped = conn.execute(
            """SELECT COUNT(*) FROM papers
               WHERE full_text_status='jats_unavailable'"""
        ).fetchone()[0]
    assert skipped == 1  # pmid 3 not attempted

    n_skip = ff.finalize_jats_unavailable_as_unavailable()
    assert n_skip == 1
    with get_conn() as conn:
        rows = {
            r["pmid"]: (r["full_text_status"], r["full_text_fetched_at"] is not None)
            for r in conn.execute(
                "SELECT pmid, full_text_status, full_text_fetched_at FROM papers"
            )
        }
    assert rows["1"][0] == "unavailable"
    assert rows["2"][0] == "unavailable"
    assert rows["3"][0] == "unavailable"
    assert all(v[1] for v in rows.values())


def test_fetch_all_fulltext_no_retry_skips_requeue(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "77", "title": "X", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 30)

    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)

    stats = ff.fetch_all_fulltext(retry=False)
    assert stats["retried_into_pending"] == 0
    with get_conn() as conn:
        st = conn.execute(
            "SELECT full_text_status FROM papers WHERE id=?", (pid,)
        ).fetchone()[0]
    assert st == "unavailable"


def test_fetch_all_fulltext_default_requeues(monkeypatch):
    from fetcher import fulltext_fetcher as ff

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "88", "title": "Y", "year": 2025})
    mark_fulltext_status(pid, "unavailable")
    _set_fetched_at(pid, 30)

    monkeypatch.setattr(ff, "fetch_jats_fulltext", lambda cache_xml=True: None)
    monkeypatch.setattr(ff, "fetch_pdf_mineru_fallback", lambda limit=None: 0)

    stats = ff.fetch_all_fulltext(retry=True, force_retry=False)
    assert stats["retried_into_pending"] == 1
```

- [ ] **Step 2: Run new tests to verify they fail**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v
```

Expected: FAIL on missing `limit` / `finalize_*` / return dict.

- [ ] **Step 3: Implement PDF selection, finalize, and `fetch_all_fulltext`**

Replace / extend `fulltext_workflow/fetcher/fulltext_fetcher.py` so it matches this shape (keep the existing PDF success path intact):

```python
"""
Unified full-text fetch: JATS (Europe PMC) → ScanSci PDF + MinerU → mark unavailable.

Extraction stage (section_extractor) falls back to abstract when full_text_status
is unavailable. Cooled-down unavailable papers are requeued at the start of a run.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from tqdm import tqdm

import config
from db.schema import (
    delete_paper_sections,
    get_conn,
    insert_sections,
    mark_fulltext_status,
    requeue_cooled_fulltext_failures,
)
from fetcher.mineru_parser import pdf_to_sections
from fetcher.pmc_fetcher import fetch_jats_fulltext
from fetcher.scansci_fetcher import download_pdf


def _papers_for_pdf_fallback(limit: int | None = None) -> list[sqlite3.Row]:
    """jats_unavailable papers, newest first. limit=None or 0 → no cap."""
    sql = """
        SELECT id, pmid, doi, pmc_id, full_text_status, year, created_at
        FROM papers
        WHERE pmid IS NOT NULL AND full_text_status = 'jats_unavailable'
        ORDER BY year IS NULL, year DESC, created_at DESC
    """
    with get_conn() as conn:
        if limit is not None and limit > 0:
            return conn.execute(sql + " LIMIT ?", (int(limit),)).fetchall()
        return conn.execute(sql).fetchall()


def finalize_jats_unavailable_as_unavailable() -> int:
    """Mark leftover jats_unavailable as unavailable; refresh fetched_at."""
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE papers SET
                   full_text_status='unavailable',
                   full_text_fetched_at=CURRENT_TIMESTAMP
               WHERE full_text_status='jats_unavailable'"""
        )
        return int(cur.rowcount)


def _store_pdf_sections(paper_id: int, sections: list[dict[str, Any]]) -> bool:
    if not sections:
        return False
    delete_paper_sections(paper_id)
    insert_sections(paper_id, sections)
    return True


def fetch_pdf_mineru_fallback(limit: int | None = None) -> int:
    """Try ScanSci PDF + MinerU for papers without JATS full text."""
    pending = _papers_for_pdf_fallback(limit=limit)
    print(f"[PDF/MinerU] {len(pending)} papers to try after JATS failure.")

    if not pending:
        return 0

    success = 0
    for row in tqdm(pending, desc="  PDF+MinerU", unit="paper"):
        paper_id = row["id"]
        pmid = row["pmid"] or ""
        doi = row["doi"] or ""

        if not doi:
            mark_fulltext_status(paper_id, "unavailable")
            continue

        dl = download_pdf(doi, pmid)
        if not dl.get("success"):
            mark_fulltext_status(paper_id, "unavailable")
            continue

        try:
            sections = pdf_to_sections(dl["file"], pmid)
            if _store_pdf_sections(paper_id, sections):
                mark_fulltext_status(paper_id, "pdf_available")
                success += 1
            else:
                mark_fulltext_status(paper_id, "unavailable")
        except Exception as e:
            print(f"  [WARN] PMID {pmid} MinerU failed: {e}")
            mark_fulltext_status(paper_id, "unavailable")

    print(f"[PDF/MinerU] {success} papers with MinerU sections stored.")
    return success


def fetch_all_fulltext(
    cache_xml: bool = True,
    *,
    retry: bool = True,
    force_retry: bool = False,
    pdf_retry_limit: int | None = None,
) -> dict[str, int]:
    """Three-tier fulltext acquisition (tiers 1–2; tier 3 is abstract at extract)."""
    if pdf_retry_limit is None:
        pdf_retry_limit = config.FULLTEXT_PDF_RETRY_LIMIT

    retried = 0
    if retry or force_retry:
        retried = requeue_cooled_fulltext_failures(
            cooldown_days=config.FULLTEXT_RETRY_COOLDOWN_DAYS,
            force=force_retry,
        )
        print(
            f"[Fulltext] Requeued {retried} cooled-down failures "
            f"(force={force_retry}, cooldown_days={config.FULLTEXT_RETRY_COOLDOWN_DAYS})."
        )

    print("[Fulltext] Tier 1: Europe PMC JATS XML")
    fetch_jats_fulltext(cache_xml=cache_xml)

    with get_conn() as conn:
        jats_pool = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='jats_unavailable'"
        ).fetchone()[0]

    effective_limit = None if pdf_retry_limit == 0 else pdf_retry_limit
    pdf_attempt_cap = jats_pool if effective_limit is None else min(jats_pool, effective_limit)
    pdf_skipped_by_limit = max(0, jats_pool - pdf_attempt_cap)

    print("[Fulltext] Tier 2: ScanSci PDF + MinerU")
    pdf_ok = fetch_pdf_mineru_fallback(limit=effective_limit)

    still = finalize_jats_unavailable_as_unavailable()
    if still:
        print(
            f"[Fulltext] Marked {still} papers unavailable "
            f"(abstract-only at extract; skipped_by_pdf_limit≈{pdf_skipped_by_limit})."
        )

    with get_conn() as conn:
        jats = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='available'"
        ).fetchone()[0]
        pdf = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='pdf_available'"
        ).fetchone()[0]
        unavail = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE full_text_status='unavailable'"
        ).fetchone()[0]

    stats = {
        "retried_into_pending": retried,
        "pdf_attempted": pdf_attempt_cap,
        "pdf_ok": pdf_ok,
        "pdf_skipped_by_limit": pdf_skipped_by_limit,
        "jats_available": jats,
        "pdf_available": pdf,
        "unavailable": unavail,
        "jats_unavailable_before_tier2": jats_pool,
    }
    print(
        f"[Fulltext] Done: retried={retried}, JATS={jats}, MinerU-PDF={pdf}, "
        f"abstract-only={unavail}, pdf_skipped_by_limit={pdf_skipped_by_limit}"
    )
    return stats
```

Implementer notes:

- Prefer `ORDER BY year IS NULL, year DESC, created_at DESC` (portable across SQLite versions).
- Do not clear `extraction_done` / `reconcile_status` anywhere in this module.
- `force_retry=True` implies requeue even if `retry` were false (`if retry or force_retry`).

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/fetcher/fulltext_fetcher.py fulltext_workflow/tests/test_fulltext_retry.py
git commit -m "feat: cap PDF fulltext retries and wire cooldown requeue"
```

---

### Task 3: CLI flags, weekly argv guard, docs

**Files:**
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/tests/test_ops_jobs.py`
- Modify: `fulltext_workflow/PIPELINE.md`
- Modify: `fulltext_workflow/SCRIPTS.md`

**Interfaces:**
- Consumes: `fetch_all_fulltext(..., retry=..., force_retry=..., pdf_retry_limit=...)`
- Produces: argparse flags on `fetch-fulltext`; docs notes; test that weekly argv is unchanged

- [ ] **Step 1: Write the weekly argv assertion**

In `fulltext_workflow/tests/test_ops_jobs.py`, add:

```python
def test_build_weekly_argv_fetch_fulltext_unchanged():
    params = {"since_days": 14, "extract_limit": 0, "skip_enrich": False}
    assert oj.build_weekly_argv("fetch-fulltext", params) == ["fetch-fulltext"]
```

- [ ] **Step 2: Run the new ops test**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_ops_jobs.py::test_build_weekly_argv_fetch_fulltext_unchanged -v
```

Expected: PASS (documents the non-goal: no new weekly step).

- [ ] **Step 3: Wire CLI in `main.py`**

Replace `cmd_fetch_fulltext`:

```python
def cmd_fetch_fulltext(args: argparse.Namespace) -> None:
    from db.schema import db_stats, init_db
    from fetcher.fulltext_fetcher import fetch_all_fulltext

    init_db()
    if getattr(args, "no_retry", False) and getattr(args, "force_retry", False):
        raise SystemExit("Use only one of --no-retry / --force-retry")
    retry = not getattr(args, "no_retry", False)
    force_retry = bool(getattr(args, "force_retry", False))
    pdf_limit = getattr(args, "pdf_retry_limit", None)
    fetch_all_fulltext(
        cache_xml=True,
        retry=retry,
        force_retry=force_retry,
        pdf_retry_limit=pdf_limit,
    )
    print("\n[Fetch-Fulltext] Stats:", db_stats())
```

Replace `sub.add_parser("fetch-fulltext", ...)` with:

```python
    p_ft = sub.add_parser(
        "fetch-fulltext",
        help="Fetch full text: JATS → PDF/MinerU fallback (retries cooled-down unavailable)",
    )
    p_ft.add_argument(
        "--no-retry",
        action="store_true",
        help="Do not requeue unavailable/jats_unavailable; only process pending",
    )
    p_ft.add_argument(
        "--force-retry",
        action="store_true",
        help="Requeue all unavailable/jats_unavailable ignoring cooldown",
    )
    p_ft.add_argument(
        "--pdf-retry-limit",
        type=int,
        default=None,
        help="Max PDF/MinerU attempts this run (default: config FULLTEXT_PDF_RETRY_LIMIT; 0=unlimited)",
    )
```

`getattr` defaults keep `run-db` / `run-all` working when they pass a bare `Namespace` without these flags.

- [ ] **Step 4: Update docs**

In `PIPELINE.md` Phase 3, after the tier list, add:

```markdown
**重试：** 默认把冷却期满（`FULLTEXT_RETRY_COOLDOWN_DAYS`，默认 7 天）的 `unavailable` / `jats_unavailable` 重置为 `pending` 再抓。JATS 不限量；PDF/MinerU 受 `FULLTEXT_PDF_RETRY_LIMIT`（默认 500）限制。`--no-retry` 关闭重试；`--force-retry` 忽略冷却。周常 `fetch-fulltext` 使用默认行为，无需额外步骤。
```

In `SCRIPTS.md` near the `fetch-fulltext` line:

```powershell
& $py main.py fetch-fulltext
& $py main.py fetch-fulltext --no-retry
& $py main.py fetch-fulltext --force-retry
& $py main.py fetch-fulltext --pdf-retry-limit 100
# env: FULLTEXT_RETRY_COOLDOWN_DAYS=7  FULLTEXT_PDF_RETRY_LIMIT=500
```

- [ ] **Step 5: Run the full related suite**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_retry.py tests/test_ops_jobs.py::test_build_weekly_argv_fetch_fulltext_unchanged -v
```

Expected: all PASS.

- [ ] **Step 6: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/main.py fulltext_workflow/tests/test_ops_jobs.py fulltext_workflow/PIPELINE.md fulltext_workflow/SCRIPTS.md
git commit -m "feat: add fetch-fulltext retry CLI flags and docs"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Cooldown requeue of `unavailable` / `jats_unavailable` | Task 1 |
| JATS uncapped | Task 2 (unchanged `fetch_jats_fulltext` on all `pending`) |
| PDF/MinerU default limit 500, newest first | Task 2 |
| Leftover `jats_unavailable` → `unavailable` + refreshed `full_text_fetched_at` | Task 2 (`finalize_jats_unavailable_as_unavailable`) |
| `--no-retry` / `--force-retry` / `--pdf-retry-limit` | Task 3 |
| Config env defaults 7 / 500 | Task 1 |
| Weekly single step unchanged | Task 3 |
| No extraction/reconcile mutation | Global + Task 2 notes |
| Docs PIPELINE / SCRIPTS | Task 3 |
| Unit tests for cooldown / force / PDF cap / weekly argv | Tasks 1–3 |

## Out of scope (do not implement in this plan)

- Flipping `skipped_no_ft` → `pending` on successful fulltext upgrade
- Force-reextract after backfill
- Gap UI controls for cooldown / PDF limit
- Attempt-count / exponential backoff schema
