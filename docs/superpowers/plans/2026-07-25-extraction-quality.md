# Extraction Quality & Fulltext Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean Dataset platform pollution, tighten `public` labeling, and add a section→fulltext reconcile pass that writes bindings and merges Limitations—validated on a small PMID pilot before any full-corpus re-extract.

**Architecture:** Keep Pass 1 (`section_extractor`) as the evidence base. After each paper’s section triples are saved, run a rule layer (blacklist + access tighten). If fulltext exists and `RECONCILE_ENABLED`, run Pass 2 (`fulltext_reconcile`) once per paper to keep/merge/drop datasets, upsert `paper_entity_bindings`, and supersede fragmented Limitations. Downstream SQL defaults to `relations.status='active'`.

**Tech Stack:** Python 3, SQLite (`fulltext_workflow/db/schema.py`), existing `llm_client.llm_call_structured`, pytest.

**Spec:** `docs/superpowers/specs/2026-07-25-extraction-quality-design.md`

## Global Constraints

- Do not implement Phase 2 hotspot/combo scoring changes; only `status='active'` filters and binding table writes.
- Prefer `superseded` over hard-delete for bad Dataset / merged Limitation edges during pilot.
- Pass 2 must not promote unlisted dataset names to `access_class=public`.
- `RECONCILE_MAX_CHARS` default `32000`; assemble with preference for methods/discussion/limitations sections.
- Pilot (20–50 PMIDs) must pass QA gates before recommending full re-extract.
- Do not commit secrets; do not change PubMed query groups.
- Run pytest from `fulltext_workflow/` (tests add that root to `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave working tree dirty and note the suggested commit message.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/extractor/dataset_access.py` | Platform blacklist; `is_literature_platform`; tighten `resolve_dataset_access` |
| `fulltext_workflow/extractor/entity_normalize.py` | Drop blacklisted Dataset triples in `postprocess_triples` |
| `fulltext_workflow/db/schema.py` | Migrations; `insert_relation` extras; clear/reextract helpers; bindings CRUD; reconcile status |
| `fulltext_workflow/config.py` | `RECONCILE_*` flags |
| `fulltext_workflow/extractor/fulltext_reconcile.py` | **New** Pass 2 assemble / LLM / apply |
| `fulltext_workflow/extractor/section_extractor.py` | Hook Pass 2; pass `extraction_pass`; pmid-list runner |
| `fulltext_workflow/main.py` | `--pmid-list`, re-extract flags, `reconcile` command |
| `fulltext_workflow/analysis/gap_tools.py` | Active-status filters on limitation/dataset SQL |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Active-status on limitation (and dataset if any) queries |
| `fulltext_workflow/analysis/public_dataset_feasibility.py` | Active `USES_DATASET` only |
| `fulltext_workflow/idea_agent.py` | Active filters on dataset/limitation tools |
| `fulltext_workflow/analysis/gap_lifecycle.py` | Active filters where `REPORTS_LIMITATION` is read |
| `fulltext_workflow/scripts/pilot_reconcile_qa.py` | **New** CSV export for pilot QA |
| `fulltext_workflow/tests/test_dataset_access.py` | Blacklist + public tighten |
| `fulltext_workflow/tests/test_fulltext_reconcile.py` | **New** assemble/apply without live LLM |
| `fulltext_workflow/tests/test_relation_status.py` | **New** supersede / active defaults |
| `fulltext_workflow/extractor/GRANULARITY.md` | Document Pass 2 |

---

### Task 1: Dataset platform blacklist + tighten `public`

**Files:**
- Modify: `fulltext_workflow/extractor/dataset_access.py`
- Modify: `fulltext_workflow/tests/test_dataset_access.py`

**Interfaces:**
- Produces: `is_literature_platform(name: str) -> bool`; `resolve_dataset_access(...)` never returns `public` for unlisted LLM hints; `LITERATURE_PLATFORM_BLOCKLIST: frozenset[str]`

- [ ] **Step 1: Write the failing tests**

Append to `fulltext_workflow/tests/test_dataset_access.py`:

```python
from extractor.dataset_access import is_literature_platform  # add to import


def test_literature_platform_blocklist():
    assert is_literature_platform("PubMed")
    assert is_literature_platform("pubmed central")
    assert is_literature_platform("NCBI GEO")
    assert is_literature_platform("Google Scholar")
    assert not is_literature_platform("camelyon16")
    assert not is_literature_platform("tcga")


def test_llm_public_hint_unlisted_becomes_unknown():
    assert resolve_dataset_access("some rare bank", access_hint="public") == "unknown"


def test_llm_private_hint_still_honored():
    assert resolve_dataset_access("some rare bank", access_hint="private") == "private"
```

Update existing `test_llm_hint_used_when_unknown` so it no longer asserts `access_hint="public"` → `"public"` (replace with the two tests above, or delete that assertion line).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; python -m pytest tests/test_dataset_access.py::test_literature_platform_blocklist tests/test_dataset_access.py::test_llm_public_hint_unlisted_becomes_unknown -v`

Expected: FAIL (`is_literature_platform` missing and/or public hint still returns public).

- [ ] **Step 3: Implement blacklist + tighten**

In `dataset_access.py`, add (near top after aliases):

```python
LITERATURE_PLATFORM_BLOCKLIST: frozenset[str] = frozenset(
    {
        "pubmed",
        "pubmed central",
        "pmc",
        "ncbi",
        "ncbi geo",
        "geo",
        "gene expression omnibus",
        "google scholar",
        "web of science",
        "scopus",
        "medline",
        "embase",
        "cochrane library",
        "cochrane",
        "europe pmc",
        "semantic scholar",
        "crossref",
        "dimensions",
        "openalex",
    }
)


def is_literature_platform(name: str) -> bool:
    key = _norm_key(name)
    if key in LITERATURE_PLATFORM_BLOCKLIST:
        return True
    for token in LITERATURE_PLATFORM_BLOCKLIST:
        if re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", key):
            return True
    return False
```

In `resolve_dataset_access`, after computing `key`, if `is_literature_platform(key)` return `"unknown"` (callers will drop the triple separately; access alone is not enough).

Change the hint branch:

```python
    if hint in ("public", "private", "unknown"):
        if hint == "public":
            # Unlisted public hints are not trusted.
            return "unknown"
        return hint  # type: ignore[return-value]
```

Optionally extend `PUBLIC_DATASET_ALIASES` with a few more pathology benchmarks if known (e.g. `tissuenet`, `nuclick`) — keep YAGNI; only add names you are sure about.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; python -m pytest tests/test_dataset_access.py -v`

Expected: PASS (all tests in file).

- [ ] **Step 5: Commit (if user requested commits)**

```bash
git add fulltext_workflow/extractor/dataset_access.py fulltext_workflow/tests/test_dataset_access.py
git commit -m "feat(extract): block literature platforms and distrust unlisted public hints"
```

---

### Task 2: Drop blacklisted Dataset triples in postprocess

**Files:**
- Modify: `fulltext_workflow/extractor/entity_normalize.py`
- Modify: `fulltext_workflow/tests/test_entity_normalize.py` (or create cases there)

**Interfaces:**
- Consumes: `is_literature_platform`, `normalize_dataset_name`
- Produces: `postprocess_triples` skips Dataset / `USES_DATASET` when platform

- [ ] **Step 1: Write the failing test**

In `tests/test_entity_normalize.py`, add a test that builds a `Triple` with `USES_DATASET` → object name `"PubMed"` and asserts it is removed after `postprocess_triples(..., "methods")`. Mirror existing Triple construction patterns in that file.

```python
def test_postprocess_drops_pubmed_as_dataset():
    from extractor.triple_models import EntitySpan, Triple
    from extractor.entity_normalize import postprocess_triples

    t = Triple(
        subject=EntitySpan(name="paper", type="Paper"),
        relation="USES_DATASET",
        object=EntitySpan(name="PubMed", type="Dataset"),
        confidence=0.9,
        evidence_quote="searched PubMed",
    )
    out = postprocess_triples([t], "methods")
    assert all(
        not (x.relation == "USES_DATASET" and "pubmed" in x.object.name.lower())
        for x in out
    )
```

(Adjust `EntitySpan` / `Triple` field names to match `triple_models.py` exactly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fulltext_workflow; python -m pytest tests/test_entity_normalize.py::test_postprocess_drops_pubmed_as_dataset -v`

Expected: FAIL (PubMed still present) or import/construct errors to fix in the test first.

- [ ] **Step 3: Implement filter**

In `postprocess_triples`, after name normalization loop (or in the final `out` loop), skip when:

```python
from extractor.dataset_access import is_literature_platform, normalize_dataset_name

# inside loop over triples destined for out:
if obj_type == "Dataset" or triple.relation == "USES_DATASET":
    canon = normalize_dataset_name(obj_name)
    if is_literature_platform(obj_name) or is_literature_platform(canon):
        continue
    obj = obj.model_copy(update={"name": canon})
```

- [ ] **Step 4: Run tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_entity_normalize.py tests/test_dataset_access.py -v`

Expected: PASS.

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/entity_normalize.py fulltext_workflow/tests/test_entity_normalize.py
git commit -m "feat(extract): drop literature-platform Dataset triples in postprocess"
```

---

### Task 3: Schema — relation status + papers reconcile + bindings table

**Files:**
- Modify: `fulltext_workflow/db/schema.py` (`SCHEMA_SQL` + `_migrate_db` + `insert_relation` + helpers)
- Create: `fulltext_workflow/tests/test_relation_status.py`

**Interfaces:**
- Produces:
  - `insert_relation(..., status: str = "active", superseded_by: int | None = None, extraction_pass: str = "section")`
  - `supersede_relation(relation_id: int, superseded_by: int | None) -> None`
  - `set_paper_reconcile_status(paper_id: int, status: str) -> None`
  - `clear_paper_kg_extractions(pmid: str) -> None` — deletes `relations` + `paper_entity_bindings` for PMID; sets `extraction_done=0`, `reconcile_status='pending'`
  - `upsert_paper_entity_binding(source_pmid, method_entity_id, disease_entity_id, dataset_entity_id, confidence, evidence_quote) -> int`
  - `get_papers_by_pmids(pmids: list[str]) -> list[Row]`

- [ ] **Step 1: Write failing tests using a temp DB**

Follow patterns from `tests/test_entity_access_class.py` / `test_date_precision_upsert.py` (patch `config.DB_PATH` or `_db_path` to a tempfile, call `init_db`).

```python
def test_insert_relation_defaults_active(tmp_path, monkeypatch):
    # init_db on tmp sqlite
    # upsert_entity + insert_relation without status
    # SELECT status, extraction_pass → ("active", "section")


def test_supersede_relation(tmp_path, monkeypatch):
    # insert two limitation edges; supersede one with superseded_by=canonical_id
    # assert status and superseded_by


def test_clear_paper_kg_extractions(tmp_path, monkeypatch):
    # insert relations + binding for pmid; clear; assert gone; extraction_done=0


def test_upsert_paper_entity_binding(tmp_path, monkeypatch):
    # insert binding; re-upsert same pmid+method+disease+dataset; count==1
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd fulltext_workflow; python -m pytest tests/test_relation_status.py -v`

Expected: FAIL (missing columns/functions).

- [ ] **Step 3: Implement schema**

1. In `SCHEMA_SQL` for fresh DBs, add to `relations`:

```sql
status                  TEXT DEFAULT 'active',
superseded_by           INTEGER,
extraction_pass         TEXT DEFAULT 'section',
```

Add to `papers`:

```sql
reconcile_status        TEXT DEFAULT 'pending',
reconcile_at            TIMESTAMP,
```

Add table:

```sql
CREATE TABLE IF NOT EXISTS paper_entity_bindings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pmid         TEXT NOT NULL,
    method_entity_id    INTEGER,
    disease_entity_id   INTEGER,
    dataset_entity_id   INTEGER,
    confidence          REAL DEFAULT 1.0,
    evidence_quote      TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_peb_pmid ON paper_entity_bindings(source_pmid);
```

2. In `_migrate_db`, `PRAGMA table_info(relations)` / `papers` and `ALTER TABLE` add missing columns; `CREATE TABLE IF NOT EXISTS paper_entity_bindings ...`.

3. Extend `insert_relation` INSERT/UPDATE to include `status`, `superseded_by`, `extraction_pass` (default active/section). On conflict update, do **not** overwrite an existing `superseded` row back to active unless explicitly passed.

4. Implement helpers listed in Interfaces.

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd fulltext_workflow; python -m pytest tests/test_relation_status.py -v`

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/db/schema.py fulltext_workflow/tests/test_relation_status.py
git commit -m "feat(db): relation status, reconcile flags, paper_entity_bindings"
```

---

### Task 4: Config flags

**Files:**
- Modify: `fulltext_workflow/config.py`

**Interfaces:**
- Produces: `RECONCILE_ENABLED: bool`, `RECONCILE_MAX_CHARS: int = 32000`

- [ ] **Step 1: Add config**

Near extraction settings (`EXTRACT_CORE_ONLY`):

```python
RECONCILE_ENABLED: bool = os.getenv("RECONCILE_ENABLED", "true").lower() in (
    "1", "true", "yes", "on",
)
RECONCILE_MAX_CHARS: int = int(os.getenv("RECONCILE_MAX_CHARS", "32000"))
```

- [ ] **Step 2: Smoke import**

Run: `cd fulltext_workflow; python -c "import config; assert config.RECONCILE_MAX_CHARS==32000"`

Expected: prints nothing, exit 0.

- [ ] **Step 3: Commit (if requested)**

```bash
git add fulltext_workflow/config.py
git commit -m "feat(config): RECONCILE_ENABLED and RECONCILE_MAX_CHARS"
```

---

### Task 5: `fulltext_reconcile` — assemble + parse (no live LLM)

**Files:**
- Create: `fulltext_workflow/extractor/fulltext_reconcile.py`
- Create: `fulltext_workflow/tests/test_fulltext_reconcile.py`

**Interfaces:**
- Produces:
  - `assemble_reconcile_text(sections: list[dict], *, max_chars: int) -> str`
  - `parse_reconcile_payload(raw: dict) -> dict` — validates/normalizes keys `datasets`, `bindings`, `limitations`
  - `RECONCILE_SYSTEM: str` prompt constant

- [ ] **Step 1: Write failing tests**

```python
def test_assemble_prefers_core_sections_and_truncates():
    from extractor.fulltext_reconcile import assemble_reconcile_text
    sections = [
        {"section_type": "introduction", "content": "INTRO " * 5000},
        {"section_type": "methods", "content": "METHODS " * 100},
        {"section_type": "discussion", "content": "DISC " * 100},
        {"section_type": "limitations", "content": "LIM " * 50},
    ]
    text = assemble_reconcile_text(sections, max_chars=2000)
    assert "METHODS" in text
    assert "LIM" in text
    assert len(text) <= 2000


def test_parse_reconcile_payload_normalizes():
    from extractor.fulltext_reconcile import parse_reconcile_payload
    raw = {
        "datasets": [{"name": "PubMed", "access": "public", "action": "drop", "reason": "platform"}],
        "bindings": [{"method": "CNN", "disease": "breast cancer", "dataset": "", "quote": "q"}],
        "limitations": [{"canonical": "small sample size", "merges": ["small n"], "quote": "q2"}],
    }
    p = parse_reconcile_payload(raw)
    assert p["datasets"][0]["action"] == "drop"
    assert p["bindings"][0]["dataset"] == ""
    assert p["limitations"][0]["canonical"] == "small sample size"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd fulltext_workflow; python -m pytest tests/test_fulltext_reconcile.py -v`

- [ ] **Step 3: Implement assemble + parse**

`assemble_reconcile_text`: order sections by priority `methods, results, discussion, limitations, future_work, abstract, introduction, other`; concatenate with headers `## {section_type}\n`; if over `max_chars`, keep priority order and truncate the concatenated string (head of high-priority content first—simple approach: fill from priority list until budget exhausted).

`parse_reconcile_payload`: coerce missing lists to `[]`; lowercase `action` into `{keep,merge,drop}`; skip rows missing required names.

Define `RECONCILE_SYSTEM` instructing JSON-only output matching the spec contract; emphasize dropping literature platforms; do not mark unlisted datasets public.

Stub for later:

```python
def call_reconcile_llm(text: str, entity_summary: str) -> dict:
    from extractor.llm_client import llm_call_structured
    user = f"ENTITY SUMMARY (Pass1):\n{entity_summary}\n\nFULLTEXT:\n{text}"
    return parse_reconcile_payload(llm_call_structured(RECONCILE_SYSTEM, user))
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd fulltext_workflow; python -m pytest tests/test_fulltext_reconcile.py -v`

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/fulltext_reconcile.py fulltext_workflow/tests/test_fulltext_reconcile.py
git commit -m "feat(extract): fulltext reconcile assemble/parse helpers"
```

---

### Task 6: `apply_reconcile_payload` — persist datasets, bindings, limitations

**Files:**
- Modify: `fulltext_workflow/extractor/fulltext_reconcile.py`
- Modify: `fulltext_workflow/tests/test_fulltext_reconcile.py`

**Interfaces:**
- Consumes: schema helpers from Task 3; `resolve_dataset_access`, `normalize_dataset_name`, `normalize_entity_name`
- Produces: `apply_reconcile_payload(paper_id: int, pmid: str, payload: dict) -> None`

**Behavior:**

1. **datasets**
   - `drop`: find `USES_DATASET` relations for `pmid` whose object name matches (normalized); `supersede_relation(id, None)` (or superseded_by null).
   - `merge`: resolve canonical name via `normalize_dataset_name`; supersede old edges; `upsert_entity` + `insert_relation` active `USES_DATASET` with `extraction_pass='fulltext_reconcile'`.
   - `keep`: optionally refresh `access_class` via `resolve_dataset_access(name, access_hint=access)` (public only if alias).

2. **limitations**
   - `canonical` → `upsert_entity(..., "Limitation")`
   - For each merge name: find matching `REPORTS_LIMITATION` for pmid; supersede with `superseded_by=canonical_id`
   - Insert one active `REPORTS_LIMITATION` with quote, `extraction_pass='fulltext_reconcile'`, `evidence_section='fulltext_reconcile'`

3. **bindings**
   - Resolve method/disease/dataset entity ids (create if needed with types Method/Disease/Dataset); skip binding if both method and disease missing; `upsert_paper_entity_binding`

- [ ] **Step 1: Write failing DB integration test**

Use temp DB: seed paper, Pass1-like `USES_DATASET` for `pubmed` and `camelyon16`, two limitation edges `small n` / `limited cohort`. Apply payload that drops pubmed, keeps camelyon16, merges limitations to `small sample size`, adds one binding. Assert active dataset names, superseded pubmed, one active limitation canonical, one binding row.

- [ ] **Step 2: Run — expect FAIL**

Run: `cd fulltext_workflow; python -m pytest tests/test_fulltext_reconcile.py::test_apply_reconcile_payload -v`

- [ ] **Step 3: Implement `apply_reconcile_payload`**

Keep SQL lookups in this module or thin helpers in `schema.py` such as:

```python
def list_relations_for_pmid(pmid: str, relation: str | None = None) -> list[sqlite3.Row]: ...
```

- [ ] **Step 4: Run full reconcile tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_fulltext_reconcile.py tests/test_relation_status.py -v`

Expected: PASS.

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/fulltext_reconcile.py fulltext_workflow/db/schema.py fulltext_workflow/tests/test_fulltext_reconcile.py
git commit -m "feat(extract): apply fulltext reconcile payload to SQLite"
```

---

### Task 7: Wire Pass 2 into `section_extractor` + extraction_pass on save

**Files:**
- Modify: `fulltext_workflow/extractor/section_extractor.py`
- Modify: `fulltext_workflow/db/schema.py` if `get_papers_by_pmids` / clear helpers need tweaks

**Interfaces:**
- Produces: `run_extraction(..., pmids: list[str] | None = None, force_reextract: bool = False)`; `_process_paper` calls reconcile when enabled

- [ ] **Step 1: Update `_save_triple` to pass `extraction_pass="section"`**

```python
insert_relation(..., extraction_pass="section", status="active")
```

- [ ] **Step 2: Add `_run_reconcile_for_paper(paper, paper_id, pmid) -> None`**

```python
def _run_reconcile_for_paper(paper, paper_id: int, pmid: str) -> None:
    import config
    from db.schema import set_paper_reconcile_status
    from extractor.fulltext_reconcile import (
        assemble_reconcile_text,
        call_reconcile_llm,
        apply_reconcile_payload,
        summarize_pass1_entities,
    )

    if not config.RECONCILE_ENABLED:
        return
    status = paper["full_text_status"]
    if status not in ("available", "pdf_available"):
        set_paper_reconcile_status(paper_id, "skipped_no_ft")
        return
    sections = get_paper_sections(paper_id)
    sec_dicts = [{"section_type": s["section_type"], "content": s["content"] or ""} for s in sections]
    if not any((s["content"] or "").strip() for s in sec_dicts):
        set_paper_reconcile_status(paper_id, "skipped_no_ft")
        return
    try:
        text = assemble_reconcile_text(sec_dicts, max_chars=config.RECONCILE_MAX_CHARS)
        summary = summarize_pass1_entities(pmid)  # implement: distinct entity names by type from relations
        payload = call_reconcile_llm(text, summary)
        apply_reconcile_payload(paper_id, pmid, payload)
        set_paper_reconcile_status(paper_id, "done")
    except Exception as e:
        print(f"\n  [Reconcile] PMID {pmid}: failed: {e}")
        set_paper_reconcile_status(paper_id, "failed")
```

Call this at end of `_process_paper` after successful `mark_extraction_done` (only when `added > 0`).

- [ ] **Step 3: Extend `run_extraction`**

```python
def run_extraction(
    limit: int | None = None,
    *,
    pmids: list[str] | None = None,
    force_reextract: bool = False,
) -> None:
```

If `pmids`:
- optionally `clear_paper_kg_extractions(pmid)` when `force_reextract`
- load via `get_papers_by_pmids(pmids)` (include already extracted)
- process those papers only

- [ ] **Step 4: Manual dry check (no LLM required for import)**

Run: `cd fulltext_workflow; python -c "from extractor.section_extractor import run_extraction; print('ok')"`

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/extractor/section_extractor.py fulltext_workflow/extractor/fulltext_reconcile.py
git commit -m "feat(extract): hook fulltext reconcile after section extraction"
```

---

### Task 8: CLI — `--pmid-list`, force re-extract, `reconcile` command

**Files:**
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/SCRIPTS.md` (short usage note)

- [ ] **Step 1: Add argparse flags to `extract`**

```python
p_ext.add_argument("--pmid-list", type=str, default=None, help="Text file, one PMID per line")
p_ext.add_argument(
    "--force-reextract",
    action="store_true",
    help="Clear relations/bindings for target PMIDs before Pass1+2",
)
```

In `cmd_extract`:

```python
pmids = None
if args.pmid_list:
    path = Path(args.pmid_list)
    pmids = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
run_extraction(limit=limit, pmids=pmids, force_reextract=bool(args.force_reextract))
```

- [ ] **Step 2: Add `reconcile` subcommand**

Pass-2-only for PMIDs that already have Pass1:

```python
def cmd_reconcile(args):
    init_db()
    # load pmids from --pmid-list or pending failed/pending with fulltext
    # for each paper: _run_reconcile_for_paper(...)
```

Export `_run_reconcile_for_paper` from `section_extractor` or move to `fulltext_reconcile.reconcile_paper(...)`.

- [ ] **Step 3: Document in SCRIPTS.md**

```markdown
### Pilot re-extract
python main.py extract --pmid-list data/pilot_pmids.txt --force-reextract --limit 0
python main.py reconcile --pmid-list data/pilot_pmids.txt
```

Note: `fulltext_workflow/data/` is gitignored — pilot file is local; document path only.

- [ ] **Step 4: Help smoke**

Run: `cd fulltext_workflow; python main.py extract -h`

Expected: shows `--pmid-list` and `--force-reextract`.

- [ ] **Step 5: Commit (if requested)**

```bash
git add fulltext_workflow/main.py fulltext_workflow/SCRIPTS.md
git commit -m "feat(cli): pmid-list extract/reconcile for pilot re-runs"
```

---

### Task 9: Downstream `status='active'` filters

**Files:**
- Modify: `fulltext_workflow/analysis/gap_tools.py`
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py`
- Modify: `fulltext_workflow/analysis/public_dataset_feasibility.py`
- Modify: `fulltext_workflow/analysis/gap_lifecycle.py`
- Modify: `fulltext_workflow/idea_agent.py`
- Modify tests that assert raw relation counts if they break

**Rule:** Any SQL selecting `REPORTS_LIMITATION` or `USES_DATASET` for analytics should add:

```sql
AND COALESCE(r.status, 'active') = 'active'
```

(`COALESCE` keeps old rows without migration backfill safe.)

- [ ] **Step 1: Grep and patch**

Run: `cd fulltext_workflow; rg -n "REPORTS_LIMITATION|USES_DATASET" analysis idea_agent.py graph`

Patch each analytical reader (not necessarily KG builder export of all edges—builder may export both, but UI tools should filter active). Prefer filtering in tools/lifecycle/hotspot/V-03/idea_agent.

- [ ] **Step 2: Run related tests**

Run: `cd fulltext_workflow; python -m pytest tests/test_public_dataset_feasibility.py tests/test_weekly_hotspot.py tests/test_gap_lifecycle.py tests/test_gap_opportunity.py -v`

Fix any failures by updating fixtures to set `status='active'` or by COALESCE in SQL.

- [ ] **Step 3: Commit (if requested)**

```bash
git add fulltext_workflow/analysis fulltext_workflow/idea_agent.py fulltext_workflow/tests
git commit -m "fix(analysis): ignore superseded relations in dataset/limitation reads"
```

---

### Task 10: Pilot QA script + GRANULARITY docs

**Files:**
- Create: `fulltext_workflow/scripts/pilot_reconcile_qa.py`
- Modify: `fulltext_workflow/extractor/GRANULARITY.md`
- Create local (untracked): `fulltext_workflow/data/pilot_pmids.txt` example content documented only

- [ ] **Step 1: Implement QA exporter**

CLI: `python scripts/pilot_reconcile_qa.py --pmid-list data/pilot_pmids.txt --out output/pilot_qa.csv`

CSV columns: `pmid, reconcile_status, active_datasets, superseded_datasets, active_limitations, superseded_limitations, binding_count, platform_hit`

`platform_hit` = 1 if any active Dataset name matches `is_literature_platform`.

- [ ] **Step 2: Document Pass 2 in GRANULARITY.md**

Short section: Pass1 section / Pass2 reconcile / status field / pilot gates (platform FP=0, public precision≥90%, limitation merge error≤10%).

- [ ] **Step 3: Dry-run script help**

Run: `cd fulltext_workflow; python scripts/pilot_reconcile_qa.py -h`

- [ ] **Step 4: Commit (if requested)**

```bash
git add fulltext_workflow/scripts/pilot_reconcile_qa.py fulltext_workflow/extractor/GRANULARITY.md
git commit -m "chore: pilot reconcile QA export and Pass2 docs"
```

---

### Task 11: Full regression + pilot handoff checklist

- [ ] **Step 1: Run broad pytest**

Run: `cd fulltext_workflow; python -m pytest tests/ -q --tb=line`

Expected: all PASS (skip or mark any test that requires live LLM/network).

- [ ] **Step 2: Write operator checklist into plan completion note (no code)**

Operator (human) after code lands:

1. Pick 20–50 PMIDs with fulltext; include suspected PubMed/GEO pollution.
2. Write `fulltext_workflow/data/pilot_pmids.txt`.
3. `python main.py extract --pmid-list data/pilot_pmids.txt --force-reextract`
4. `python scripts/pilot_reconcile_qa.py --pmid-list data/pilot_pmids.txt --out output/pilot_qa.csv`
5. Manual review against gates in the spec.
6. Only then run full-corpus force re-extract (separate ops decision).

- [ ] **Step 3: Final commit of any doc/gitignore leftovers (if requested)**

```bash
git add .gitignore docs/superpowers/plans/2026-07-25-extraction-quality.md
git commit -m "docs: extraction quality implementation plan"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Platform blacklist | 1–2 |
| Distrust unlisted `public` | 1 |
| Section Pass1 retained | 7 (unchanged core path) |
| Pass2 datasets/bindings/limitations | 5–7 |
| Limitation merge via `superseded` | 3, 6 |
| `paper_entity_bindings` | 3, 6 |
| `reconcile_status` | 3, 7 |
| Re-extract clears relations+bindings | 3, 8 |
| Pilot before full re-extract | 8, 10, 11 |
| Downstream active filters | 9 |
| Phase2 hotspot logic not implemented | Global constraint / no task |
| `RECONCILE_MAX_CHARS=32000` | 4–5 |

## Placeholder / consistency scan

- Function names aligned: `apply_reconcile_payload`, `assemble_reconcile_text`, `clear_paper_kg_extractions`, `set_paper_reconcile_status`, `is_literature_platform`.
- No TBD steps remaining.
- Commit steps are optional pending user commit policy.
