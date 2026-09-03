# Abstract→Fulltext Auto Re-extract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When abstract-only extracted papers later gain fulltext, `extract` automatically clears their KG rows and re-runs fulltext Pass 1 + Pass 2 so the weekly pipeline upgrades them without a new step.

**Architecture:** At the start of corpus-queue `run_extraction`, list `skipped_no_ft` + fulltext papers, call existing `clear_paper_kg_extractions` for each (deferred clear — no empty KG window at fetch time), then use existing `get_papers_for_extraction` so upgrades compete with other pending work under the shared `--limit`.

**Tech Stack:** Python 3, SQLite via `db.schema`, existing extractor / reconcile pipeline, pytest.

**Spec:** `docs/superpowers/specs/2026-08-05-abstract-fulltext-upgrade-reextract-design.md`

## Global Constraints

- Full re-extract only (clear → Pass 1 on fulltext → Pass 2); not Pass-2-only.
- No upgrade count cap; positive `--limit` is shared with fresh pending after clear-all-eligible.
- No new reconcile status values / tables / attempt counters.
- Auto-upgrade runs only on corpus queue (`pmids is None`); `--pmid-list` unchanged (needs `--force-reextract`).
- Do not delete `document_sections` on upgrade clear.
- Default `FULLTEXT_UPGRADE_REEXTRACT=true`; env can disable.
- Weekly steps unchanged (`fetch-fulltext` → `extract`).
- Run pytest from `fulltext_workflow/` (tests insert that root on `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `fulltext_workflow/data/`, `raw/`, `output/`, or secrets.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/config.py` | `FULLTEXT_UPGRADE_REEXTRACT` bool (default true) |
| `fulltext_workflow/db/schema.py` | `list_papers_for_fulltext_upgrade()`; optionally thin wrapper that clears and returns count |
| `fulltext_workflow/extractor/section_extractor.py` | Call upgrade prep at start of corpus-queue `run_extraction` |
| `fulltext_workflow/tests/test_fulltext_upgrade_reextract.py` | **New** — eligibility, disable flag, queue after prep |
| `fulltext_workflow/PIPELINE.md` | Short note on auto upgrade |
| `fulltext_workflow/SCRIPTS.md` | Env / behavior note |

---

### Task 1: Config + list/clear upgrade helpers

**Files:**
- Modify: `fulltext_workflow/config.py`
- Modify: `fulltext_workflow/db/schema.py`
- Create: `fulltext_workflow/tests/test_fulltext_upgrade_reextract.py`

**Interfaces:**
- Consumes: `get_conn`, `clear_paper_kg_extractions`, `set_paper_reconcile_status`, `mark_fulltext_status`, `upsert_paper`, `insert_relation` / `upsert_entity` as needed for fixtures
- Produces:
  - `config.FULLTEXT_UPGRADE_REEXTRACT: bool` (default `True`; env `FULLTEXT_UPGRADE_REEXTRACT` truthy like `RECONCILE_ENABLED`)
  - `list_papers_for_fulltext_upgrade() -> list[sqlite3.Row]` — rows with at least `id`, `pmid`, ordered `year DESC, id DESC`
  - `clear_abstract_extractions_for_fulltext_upgrade() -> int` — clears all listed candidates via `clear_paper_kg_extractions`; returns count cleared

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_fulltext_upgrade_reextract.py`:

```python
"""Tests for abstract→fulltext upgrade re-extract prep."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    clear_abstract_extractions_for_fulltext_upgrade,
    get_conn,
    init_db,
    insert_relation,
    list_papers_for_fulltext_upgrade,
    mark_extraction_done,
    mark_fulltext_status,
    set_paper_reconcile_status,
    upsert_entity,
    upsert_paper,
)


def _tmp_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db()
    return path


def _seed_abstract_extracted(pmid: str, *, year: int, ft_status: str) -> int:
    pid = upsert_paper(
        {
            "pmid": pmid,
            "title": f"Title {pmid}",
            "abstract": "Abstract body long enough.",
            "year": year,
            "journal_name": "J",
        }
    )
    mark_fulltext_status(pid, ft_status)
    mark_extraction_done(pid, "ai_algorithm")
    set_paper_reconcile_status(pid, "skipped_no_ft")
    mid = upsert_entity(f"method-{pmid}", "Method")
    insert_relation(
        "Paper",
        pid,
        "APPLIES_METHOD",
        "Method",
        mid,
        source_pmid=pmid,
        evidence_section="abstract",
        evidence_quote="q",
        extraction_granularity="abstract",
        confidence=0.9,
    )
    return pid


def test_list_upgrade_candidates_only_skipped_with_fulltext(monkeypatch):
    _tmp_db(monkeypatch)
    _seed_abstract_extracted("1", year=2025, ft_status="available")
    _seed_abstract_extracted("2", year=2024, ft_status="pdf_available")
    _seed_abstract_extracted("3", year=2023, ft_status="unavailable")
    done = upsert_paper(
        {"pmid": "4", "title": "D", "abstract": "A", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(done, "available")
    mark_extraction_done(done, "ai_algorithm")
    set_paper_reconcile_status(done, "done")

    rows = list_papers_for_fulltext_upgrade()
    pmids = [r["pmid"] for r in rows]
    assert pmids == ["1", "2"]  # year DESC; unavailable + done excluded


def test_clear_upgrade_removes_relations_and_resets_flags(monkeypatch):
    _tmp_db(monkeypatch)
    _seed_abstract_extracted("10", year=2025, ft_status="available")
    _seed_abstract_extracted("11", year=2024, ft_status="unavailable")

    n = clear_abstract_extractions_for_fulltext_upgrade()
    assert n == 1

    with get_conn() as conn:
        p10 = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='10'"
        ).fetchone()
        p11 = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='11'"
        ).fetchone()
        rel10 = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='10'"
        ).fetchone()[0]
        rel11 = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='11'"
        ).fetchone()[0]
    assert p10["extraction_done"] == 0
    assert p10["reconcile_status"] == "pending"
    assert rel10 == 0
    assert p11["extraction_done"] == 1
    assert p11["reconcile_status"] == "skipped_no_ft"
    assert rel11 == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_upgrade_reextract.py -v
```

Expected: FAIL — `list_papers_for_fulltext_upgrade` / `clear_abstract_extractions_for_fulltext_upgrade` not found.

- [ ] **Step 3: Add config**

In `fulltext_workflow/config.py`, next to `RECONCILE_ENABLED`:

```python
FULLTEXT_UPGRADE_REEXTRACT: bool = os.getenv(
    "FULLTEXT_UPGRADE_REEXTRACT", "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on",
)
```

- [ ] **Step 4: Implement schema helpers**

In `fulltext_workflow/db/schema.py`, near `clear_paper_kg_extractions`:

```python
def list_papers_for_fulltext_upgrade() -> list[sqlite3.Row]:
    """Abstract-extracted papers that now have fulltext sections available."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT id, pmid, year, full_text_status, reconcile_status
               FROM papers
               WHERE extraction_done=1
                 AND reconcile_status='skipped_no_ft'
                 AND full_text_status IN ('available', 'pdf_available')
                 AND pmid IS NOT NULL
               ORDER BY year DESC, id DESC"""
        ).fetchall()


def clear_abstract_extractions_for_fulltext_upgrade() -> int:
    """Clear KG extractions for upgrade candidates; return number cleared."""
    rows = list_papers_for_fulltext_upgrade()
    for row in rows:
        clear_paper_kg_extractions(row["pmid"])
    return len(rows)
```

Export both from `fulltext_workflow/db/__init__.py` if that module re-exports peer helpers (same pattern as `clear` peers / `mark_fulltext_status`).

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_upgrade_reextract.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 6: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/config.py fulltext_workflow/db/schema.py fulltext_workflow/db/__init__.py fulltext_workflow/tests/test_fulltext_upgrade_reextract.py
git commit -m "feat: list and clear abstract extractions ready for fulltext upgrade"
```

---

### Task 2: Wire `run_extraction` + docs + disable / queue tests

**Files:**
- Modify: `fulltext_workflow/extractor/section_extractor.py`
- Modify: `fulltext_workflow/tests/test_fulltext_upgrade_reextract.py`
- Modify: `fulltext_workflow/PIPELINE.md`
- Modify: `fulltext_workflow/SCRIPTS.md`

**Interfaces:**
- Consumes: `config.FULLTEXT_UPGRADE_REEXTRACT`, `clear_abstract_extractions_for_fulltext_upgrade`, existing `get_papers_for_extraction` / `_process_paper`
- Produces: corpus-queue `run_extraction` prints `upgraded_from_abstract=N` when prep runs; no change to `--pmid-list` path

- [ ] **Step 1: Extend failing tests**

Append to `tests/test_fulltext_upgrade_reextract.py`:

```python
def test_run_extraction_upgrades_into_queue(monkeypatch):
    from extractor import section_extractor as se

    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "FULLTEXT_UPGRADE_REEXTRACT", True)
    monkeypatch.setattr(config, "DEFAULT_EXTRACT_LIMIT", 30)
    _seed_abstract_extracted("20", year=2025, ft_status="available")
    # also a plain pending paper
    upsert_paper(
        {
            "pmid": "21",
            "title": "Pending",
            "abstract": "Abstract body long enough.",
            "year": 2024,
            "journal_name": "J",
        }
    )

    seen: list[str] = []

    def fake_process(paper):
        seen.append(paper["pmid"])

    monkeypatch.setattr(se, "_process_paper", fake_process)
    se.run_extraction(limit=0)
    assert "20" in seen
    assert "21" in seen
    with get_conn() as conn:
        rel = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='20'"
        ).fetchone()[0]
    assert rel == 0  # cleared before process


def test_run_extraction_skips_upgrade_when_disabled(monkeypatch):
    from extractor import section_extractor as se

    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "FULLTEXT_UPGRADE_REEXTRACT", False)
    _seed_abstract_extracted("30", year=2025, ft_status="available")

    seen: list[str] = []
    monkeypatch.setattr(se, "_process_paper", lambda paper: seen.append(paper["pmid"]))
    se.run_extraction(limit=0)
    assert seen == []
    with get_conn() as conn:
        row = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='30'"
        ).fetchone()
        rel = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='30'"
        ).fetchone()[0]
    assert row["extraction_done"] == 1
    assert row["reconcile_status"] == "skipped_no_ft"
    assert rel == 1


def test_run_extraction_pmid_list_does_not_auto_upgrade(monkeypatch):
    from extractor import section_extractor as se

    _tmp_db(monkeypatch)
    monkeypatch.setattr(config, "FULLTEXT_UPGRADE_REEXTRACT", True)
    _seed_abstract_extracted("40", year=2025, ft_status="available")

    seen: list[str] = []
    monkeypatch.setattr(se, "_process_paper", lambda paper: seen.append(paper["pmid"]))
    se.run_extraction(limit=0, pmids=["40"], force_reextract=False)
    # Without force_reextract, paper stays extraction_done=1; get_papers_by_pmids
    # still returns it and _process_paper is called — but relations must remain
    # because auto-upgrade prep must not run on pmid-list path.
    with get_conn() as conn:
        row = conn.execute(
            "SELECT extraction_done, reconcile_status FROM papers WHERE pmid='40'"
        ).fetchone()
        rel = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_pmid='40'"
        ).fetchone()[0]
    assert row["extraction_done"] == 1
    assert row["reconcile_status"] == "skipped_no_ft"
    assert rel == 1
```

Note for implementer: if current `run_extraction(pmids=...)` always calls `_process_paper` even when `extraction_done=1`, the third test only asserts **no auto clear**. That matches the spec. If `_process_paper` no-ops when already done, `seen` may still include `"40"` — do not assert on `seen` for that test.

- [ ] **Step 2: Run new tests to verify they fail**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_upgrade_reextract.py -v
```

Expected: FAIL on missing prep wiring (upgrade paper not in queue / still has relations when flag true).

- [ ] **Step 3: Wire prep into `run_extraction`**

In `fulltext_workflow/extractor/section_extractor.py`, import:

```python
from db.schema import clear_abstract_extractions_for_fulltext_upgrade
```

(or add to existing `db.schema` import list).

Update `run_extraction` so the corpus-queue branch runs prep **before** selecting papers:

```python
def run_extraction(
    limit: int | None = None,
    *,
    pmids: list[str] | None = None,
    force_reextract: bool = False,
) -> None:
    if pmids:
        if force_reextract:
            for pmid in pmids:
                clear_paper_kg_extractions(pmid)
        papers = get_papers_by_pmids(pmids)
        lim = len(papers)
    else:
        if config.FULLTEXT_UPGRADE_REEXTRACT:
            upgraded = clear_abstract_extractions_for_fulltext_upgrade()
            print(f"[Extractor] upgraded_from_abstract={upgraded}")
        if limit is None:
            lim = config.DEFAULT_EXTRACT_LIMIT
            papers = get_papers_for_extraction(limit=lim)
        elif limit == 0:
            papers = get_papers_for_extraction(limit=0)
            lim = len(papers)
        else:
            papers = get_papers_for_extraction(limit=limit)
            lim = limit

    # ... rest unchanged (configure_concurrency, tqdm loop, etc.)
```

Do not call upgrade clear when `pmids` is provided.

- [ ] **Step 4: Update docs**

In `PIPELINE.md` Phase 4 (extract), add:

```markdown
**全文升级重抽：** 若论文曾以摘要抽取（`reconcile_status=skipped_no_ft`）且后来补到全文，`extract`（非 `--pmid-list`）会在开跑前 `clear` 并完整重抽 Pass 1+2。默认开启；`FULLTEXT_UPGRADE_REEXTRACT=false` 可关闭。周常 `fetch-fulltext` → `extract` 即可消化。
```

In `SCRIPTS.md` near extract examples:

```powershell
# env: FULLTEXT_UPGRADE_REEXTRACT=true  (default) auto-reextract abstract→fulltext upgrades
```

- [ ] **Step 5: Run the full related suite**

Run:

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_fulltext_upgrade_reextract.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit (only if user asked / plan-exec includes commits)**

```bash
git add fulltext_workflow/extractor/section_extractor.py fulltext_workflow/tests/test_fulltext_upgrade_reextract.py fulltext_workflow/PIPELINE.md fulltext_workflow/SCRIPTS.md
git commit -m "feat: auto-reextract abstract papers when fulltext becomes available"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Eligibility: skipped_no_ft + available/pdf_available | Task 1 |
| Deferred clear via `clear_paper_kg_extractions` | Task 1–2 |
| No delete of document_sections | Task 1 (reuse clear helper) |
| Corpus-queue only; pmid-list unchanged | Task 2 |
| Shared limit after clear-all-eligible | Task 2 (clear then `get_papers_for_extraction`) |
| `FULLTEXT_UPGRADE_REEXTRACT` default true | Task 1–2 |
| Log `upgraded_from_abstract=N` | Task 2 |
| Weekly steps unchanged | Global / docs |
| Unit tests for clear / skip / disable / queue | Tasks 1–2 |
| PIPELINE / SCRIPTS notes | Task 2 |

## Out of scope (do not implement)

- Pass-2-only upgrade
- Upgrade caps / Gap UI toggles
- New DB status values
- Changing `--pmid-list` to auto-clear without `--force-reextract`
