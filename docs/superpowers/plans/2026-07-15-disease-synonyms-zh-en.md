# Disease Synonyms + ZH–EN Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shared disease-concept dictionary so focus like `肠息肉` / `NPC` expands to English literature phrases and existing `focus_filter` / `disease_mapper` stop returning empty or one-way synonym misses.

**Architecture:** New `analysis/disease_synonyms.py` owns concepts (`umls_cui`, `zh`, `phrases`, sites, histology). `focus_filter` resolves focus → concept → OR-expanded SQL; free-text fallback keeps bidirectional histology tokens. `disease_mapper` imports the same aliases. Gap UI shows English resolve caption. No runtime UMLS or vectors.

**Tech Stack:** Python 3.12, SQLite `LIKE` focus clauses, pytest under `fulltext_workflow/tests/`.

**Specs:**  
- `docs/superpowers/specs/2026-07-15-disease-synonyms-design.md`  
- `docs/superpowers/specs/2026-07-15-zh-en-focus-synonyms-design.md`

## Global Constraints

- Soft expansion only via controlled phrases; never bare corpus-wide `%polyp%`.
- UMLS CUI optional/offline; **no runtime UMLS API**.
- No vector index; no PubMed ingest / `search_queries.py` changes.
- Chinese single-token focus must match `zh` list (not English `.split()` alone).
- Primary acceptance: focus `肠息肉` → papers order-of-magnitude with `colorectal polyp` (~30+, not 0) on production DB.
- Working directory for commands: `fulltext_workflow/`; use `..\.venv\Scripts\python.exe`.
- Do not commit `*.db` or secrets. Skip git commit unless user asked.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/disease_synonyms.py` | Concept table + resolve/expand helpers |
| `fulltext_workflow/analysis/focus_filter.py` | Use concept expansion in SQL/pmid/topic helpers |
| `fulltext_workflow/feasibility/disease_mapper.py` | Build keyword/alias maps from concepts |
| `fulltext_workflow/gap_ui.py` | Resolve caption under Research focus |
| `fulltext_workflow/tests/test_disease_synonyms.py` | Unit tests (no DB required for resolve/expand) |
| `fulltext_workflow/tests/test_focus_filter.py` | Fixture + coverage/SQL integration |
| `fulltext_workflow/tests/test_feasibility.py` | Mapper regressions + polyp/NPC ZH if applicable |

---

### Task 1: `disease_synonyms` module + unit tests (TDD)

**Files:**
- Create: `fulltext_workflow/analysis/disease_synonyms.py`
- Create: `fulltext_workflow/tests/test_disease_synonyms.py`

**Interfaces:**
- Produces:
  - `@dataclass DiseaseConcept` with fields: `id`, `canonical`, `phrases`, `sites`, `histology_class`, `abbreviations`, `zh`, `feasibility_keyword_zh`, `mock_disease_id`, `umls_cui` (optional `""`)
  - `HISTOLOGY_CLASSES: dict[str, list[str]]` with at least `malignant_neoplasm`
  - `DISEASE_CONCEPTS: list[DiseaseConcept]` including gastric, lung, colorectal_adenocarcinoma, **colorectal_polyp**, HCC, breast, NPC
  - `resolve_disease_concept(focus: str | None) -> DiseaseConcept | None`
  - `expand_focus_terms(focus: str | None) -> dict` with keys `concept_id`, `phrases`, `sites`, `histology`, `abbreviations`, `zh` (empty lists if unresolved)
  - `concept_match_sql_clause(column: str, concept: DiseaseConcept) -> str` — OR of escaped `LIKE` for phrases/canonical; for polyp prefer phrases first; optional `(site OR…) AND (polyp|adenoma…)` **only** with colorectal sites for `colorectal_polyp`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests for disease concept resolve/expand."""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from analysis.disease_synonyms import (
    expand_focus_terms,
    resolve_disease_concept,
)

def test_resolve_zh_intestinal_polyp():
    c = resolve_disease_concept("肠息肉")
    assert c is not None
    assert c.id == "colorectal_polyp"

def test_resolve_colon_polyp_aliases():
    assert resolve_disease_concept("结肠息肉").id == "colorectal_polyp"
    assert resolve_disease_concept("结直肠息肉").id == "colorectal_polyp"
    assert resolve_disease_concept("colorectal polyp").id == "colorectal_polyp"

def test_expand_includes_english_phrases_not_only_zh():
    exp = expand_focus_terms("肠息肉")
    phrases = [p.lower() for p in exp["phrases"]]
    assert "colorectal polyp" in phrases or any("colorectal polyp" in p for p in phrases)
    assert any("polyp" in p for p in phrases)

def test_resolve_npc_and_cancer_carcinoma():
    assert resolve_disease_concept("NPC").id == "nasopharyngeal_carcinoma"
    assert resolve_disease_concept("nasopharyngeal cancer").id == "nasopharyngeal_carcinoma"
    assert resolve_disease_concept("nasopharyngeal carcinoma").id == "nasopharyngeal_carcinoma"

def test_unknown_focus_returns_none():
    assert resolve_disease_concept("totally unknown xyzzy disease") is None
```

- [ ] **Step 2: Run — expect ImportError**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests\test_disease_synonyms.py -v
```

- [ ] **Step 3: Implement `disease_synonyms.py`**

Include at minimum `colorectal_polyp`:

```python
DiseaseConcept(
    id="colorectal_polyp",
    canonical="colorectal polyp",
    umls_cui="",  # offline optional
    phrases=[
        "colorectal polyp", "colorectal polyps", "colonic polyp", "colon polyp",
        "intestinal polyp", "colorectal adenoma",
    ],
    sites=["colorectal", "colonic", "colon", "rectal"],
    histology_class="",  # use polyp token list in match helper instead of neoplasm class
    abbreviations=[],
    zh=["肠息肉", "结肠息肉", "直肠息肉", "结直肠息肉"],
    feasibility_keyword_zh="肠息肉",
    mock_disease_id="",
)
```

Resolve rules:
1. `normalize`-like strip; None/empty → None  
2. Exact match (casefold for Latin; keep ZH as-is) against `zh`, `phrases`, `canonical`, then abbrev whole-token  
3. Prefer longest matching phrase when multiple hit  
4. For `NPC` / `npc` require concept abbrev match  

`concept_match_sql_clause`: OR over phrases; for colorectal_polyp also allow  
`(site OR) AND (polyp OR adenoma OR polyps)` with sites listed — **do not** emit bare `%polyp%`.

- [ ] **Step 4: Pytest green**

- [ ] **Step 5: Commit only if user requested**

---

### Task 2: Wire `focus_filter` + focus tests

**Files:**
- Modify: `fulltext_workflow/analysis/focus_filter.py`
- Modify: `fulltext_workflow/tests/test_focus_filter.py`

**Interfaces:**
- Consumes: `resolve_disease_concept`, `concept_match_sql_clause`, `expand_focus_terms`
- Produces: unchanged public signatures `focus_sql_clause`, `focus_pmid_in_clause`; behavior changes when concept resolves

- [ ] **Step 1: Extend tests**

Add bidirectional histology fallback expectation + Chinese focus integration. Prefer unit-level on SQL string when no production DB in CI:

```python
from analysis.focus_filter import focus_sql_clause

def test_focus_sql_zh_polyp_expands_english():
    clause = focus_sql_clause("p.title", "肠息肉")
    assert "colorectal polyp" in clause.lower()
    assert "肠息肉" not in clause or "colorectal" in clause.lower()  # English must appear

def test_focus_sql_carcinoma_maps_like_cancer_token():
    # free-text multi-token path: breast carcinoma should include cancer synonym union somehow
    clause = focus_sql_clause("p.title", "breast carcinoma")
    assert "cancer" in clause.lower() or "carcinoma" in clause.lower()
```

Optional DB smoke (skip if heavy): call `tool_corpus_focus_coverage(focus="肠息肉")` against **production** `kg_fulltext.db` only in a manual script note — for automated test, use fixture:

```python
def _seed_polyp_fixture():
    paper = upsert_paper({
        "pmid": "91000099",
        "title": "AI for colorectal polyps detection",
        "year": 2024,
        "abstract": "Colonoscopy CAD.",
        "extraction_done": 1,
    })
    did = upsert_entity("colorectal polyps", "Disease")
    insert_relation("Paper", paper, "TARGETS_DISEASE", "Disease", did,
                    source_pmid="91000099", evidence_section="methods")

def test_corpus_coverage_zh_polyp_nonzero_on_fixture():
    _setup(); _seed_polyp_fixture()
    cov = tool_corpus_focus_coverage(focus="肠息肉")
    assert cov["focus_subset"]["papers"] >= 1
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Update `focus_sql_clause`**

```python
def focus_sql_clause(column: str, focus: str | None) -> str:
    focus = normalize_focus(focus)
    if not focus:
        return ""
    from analysis.disease_synonyms import resolve_disease_concept, concept_match_sql_clause
    concept = resolve_disease_concept(focus)
    if concept:
        return " AND (" + concept_match_sql_clause(column, concept) + ")"
    # existing phrase + token path; make histology bidirectional:
    # for each token in {"cancer","carcinoma","neoplasm","tumor","tumour"} use shared alt list
    ...
```

Update `_TOKEN_SYNONYMS` so cancer/carcinoma/tumor/tumour/neoplasm all key to the same alt list.

- [ ] **Step 4: All focus_filter + disease_synonyms tests pass**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_disease_synonyms.py tests\test_focus_filter.py -v
```

---

### Task 3: `disease_mapper` consumes concepts

**Files:**
- Modify: `fulltext_workflow/feasibility/disease_mapper.py`
- Modify: `fulltext_workflow/tests/test_feasibility.py` if needed

**Interfaces:**
- Build `DISEASE_SEARCH_KEYWORDS` from concepts: for each phrase/zh/site/abbrev → `feasibility_keyword_zh`
- Keep mock `DISEASE_ALIASES` from `mock_disease_id` where set
- Ensure 肠息肉 / colorectal polyp map to keyword `肠息肉` (or documented Fangxin term); do not map polyp to CRC-ADC adenocarcinoma mock unless intentional — prefer **no mock_disease_id** for polyp (live keyword only)

- [ ] **Step 1: Test** `map_gap_to_disease` / keyword path includes polyp ZH without defaulting to BRCA

```python
def test_polyp_zh_does_not_map_to_brca():
    # if live client unavailable, at least search keyword build contains 肠息肉
    from feasibility import disease_mapper as dm
    assert any("肠息肉" in v or k == "肠息肉" for k, v in dm.DISEASE_SEARCH_KEYWORDS.items())
```

- [ ] **Step 2: Refactor mapper to import helpers from `disease_synonyms`** (generate dicts at module load). Preserve existing gastric/breast/NPC behavior.

- [ ] **Step 3: Run** `pytest tests/test_feasibility.py tests/test_disease_synonyms.py -v`

---

### Task 4: Gap UI resolve caption + light docs

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (sidebar near `focus_input`)
- Modify: `fulltext_workflow/PIPELINE.md` or `gap_ui_guide.md` — 3–5 lines

- [ ] **Step 1: After focus text input**, add caption:

```python
from analysis.disease_synonyms import resolve_disease_concept, expand_focus_terms
_foc = normalize_focus(focus_input)
if _foc:
    _c = resolve_disease_concept(_foc)
    if _c:
        st.caption(f"Resolved: {_c.canonical}" + (f" ({_c.umls_cui})" if _c.umls_cui else ""))
    elif any("\u4e00" <= ch <= "\u9fff" for ch in _foc):
        st.caption("No synonym mapping — try an English disease name")
```

Keep labels English (project UI convention).

- [ ] **Step 2: Docs note** — Chinese focus aliases supported via disease synonyms; example `肠息肉` → colorectal polyp.

- [ ] **Step 3: Manual smoke** (document in report): against `kg_fulltext.db`,

```powershell
..\.venv\Scripts\python.exe -c "from analysis.gap_tools import tool_corpus_focus_coverage; print(tool_corpus_focus_coverage(focus='肠息肉')['focus_subset']); print(tool_corpus_focus_coverage(focus='colorectal polyp')['focus_subset'])"
```

Expected: both `papers` >> 0 and same order of magnitude.

---

### Task 5: Regression + acceptance checklist

- [ ] **Step 1: Run full related suites**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_disease_synonyms.py tests\test_focus_filter.py tests\test_feasibility.py -v
```

- [ ] **Step 2: Confirm acceptance**

| # | Check |
|---|--------|
| 1 | `肠息肉` coverage ~ `colorectal polyp` |
| 2 | `结肠息肉` / `结直肠息肉` same concept |
| 3 | English colorectal polyp no regression |
| 4 | No bare `%polyp%` in generated SQL for that concept |
| 5 | NPC / cancer↔carcinoma still OK |
| 6 | No UMLS network calls in focus path |

---

## Spec coverage self-check

| Requirement | Task |
|-------------|------|
| `disease_synonyms.py` concepts + histology | 1 |
| `umls_cui` field + colorectal_polyp ZH | 1 |
| `focus_filter` concept SQL + bidirectional histology | 2 |
| `disease_mapper` shared aliases | 3 |
| Gap UI resolve caption | 4 |
| 肠息肉 acceptance | 2 fixture + 4/5 smoke |
| No runtime UMLS / vectors | Global |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-disease-synonyms-zh-en.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement in this session with checkpoints  

Which approach?
