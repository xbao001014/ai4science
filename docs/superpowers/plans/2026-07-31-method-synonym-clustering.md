# Method Synonym Soft Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate over-privatized Method names via analysis-layer soft synonyms (high-confidence auto rules + curated table) and aggregate weekly hotspot / transferable boards by canonical name.

**Architecture:** New `analysis/method_synonyms.py` owns resolve + skeleton + near-dup candidates. `weekly_hotspot` Method boards re-aggregate window stats by distinct PMID under canonical. `method_maturity` corpus counts roll up by canonical before classification. Read-only `method-cluster-audit` CLI mirrors task-quality-audit. No extract-time DB rename; no embeddings.

**Tech Stack:** Python 3, SQLite, pytest, rapidfuzz (already in requirements), Streamlit captions, argparse (`main.py`).

**Spec:** `docs/superpowers/specs/2026-07-31-method-synonym-clustering-design.md`

## Global Constraints

- Soft map only: **do not** rename `entities` rows or change extract prompts this round.
- Runtime merge = curated `_METHOD_SYNONYMS` + **narrow** auto rules; **no** fuzzy/Jaccard at runtime; **no** absorbing long phrases into umbrellas (`deep learning`, …).
- Audit candidates never auto-write the synonym table.
- Prefer **distinct PMID** aggregation when collapsing aliases (do not naively sum `recent_cnt` across aliases that share papers).
- Resolve canonical **before** `classify_method_maturity`.
- Do not change Disease/Task clustering; do not add embeddings.
- Run pytest with `fulltext_workflow/` on `sys.path` (existing test pattern).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/analysis/method_synonyms.py` | **New** — synonyms, auto rules, skeleton, near-dup candidates, audit report helper |
| `fulltext_workflow/analysis/method_maturity.py` | Roll up corpus counts by canonical (helper or annotate change) |
| `fulltext_workflow/analysis/weekly_hotspot.py` | Method board: aggregate by canonical + alias metadata |
| `fulltext_workflow/gap_ui.py` | Caption note for soft merge |
| `fulltext_workflow/main.py` | `method-cluster-audit` command |
| `fulltext_workflow/SCRIPTS.md` | Document audit command |
| `fulltext_workflow/tests/test_method_synonyms.py` | **New** — resolve / auto forbid / candidates |
| `fulltext_workflow/tests/test_weekly_hotspot_synonyms.py` | **New** — aggregation + min_recent pass via aliases |

---

### Task 1: `method_synonyms` module

**Files:**
- Create: `fulltext_workflow/analysis/method_synonyms.py`
- Create: `fulltext_workflow/tests/test_method_synonyms.py`

**Interfaces:**
- Produces: `resolve_method_canonical(name: str) -> str`
- Produces: `load_method_synonyms() -> dict[str, str]`
- Produces: `apply_auto_method_canonical(name: str) -> str`
- Produces: `method_skeleton(name: str) -> str`
- Produces: `near_duplicate_method_candidates(names: list[str], *, min_shared_tokens: int = 2, limit: int = 50) -> list[dict]`
- Curated seed: at least `llm`→`large language model` (also covered by auto), plus one example curated private alias if useful for tests

- [ ] **Step 1: Write failing tests**

Create `fulltext_workflow/tests/test_method_synonyms.py`:

```python
"""Tests for method synonym soft mapping."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.method_synonyms import (  # noqa: E402
    method_skeleton,
    near_duplicate_method_candidates,
    resolve_method_canonical,
)


def test_resolve_llm_alias():
    assert resolve_method_canonical("LLM") == "large language model"
    assert resolve_method_canonical("large language model") == "large language model"


def test_resolve_parenthetical_svm():
    assert resolve_method_canonical("support vector machine (svm)") == "support vector machine"


def test_curated_synonym_maps(monkeypatch):
    import analysis.method_synonyms as ms

    monkeypatch.setitem(
        ms._METHOD_SYNONYMS,
        "drugreflector framework",
        "drugreflector",
    )
    assert resolve_method_canonical("DrugReflector Framework") == "drugreflector"


def test_auto_does_not_absorb_long_phrase_into_deep_learning():
    name = "data fusion deep learning framework"
    assert resolve_method_canonical(name) == "data fusion deep learning framework"


def test_skeleton_strips_weak_tokens():
    sk = method_skeleton("resnet-based segmentation framework model")
    assert "framework" not in sk.split()
    assert "model" not in sk.split()


def test_near_duplicate_candidates_suggest_but_do_not_resolve():
    names = [
        "drugreflector",
        "drugreflector framework",
        "totally unrelated method xyz",
    ]
    cands = near_duplicate_method_candidates(names, min_shared_tokens=1)
    pairs = {(c["alias"], c["suggested_canonical"]) for c in cands} | {
        (c["suggested_canonical"], c["alias"]) for c in cands
    }
    assert any("drugreflector" in a and "drugreflector" in b for a, b in pairs)
    # unresolved until curated
    assert resolve_method_canonical("drugreflector framework") == "drugreflector framework"
```

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd d:\agent\prototype\build_kg_paper
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_synonyms.py -v
```

Expected: import error / FAIL.

- [ ] **Step 3: Implement `method_synonyms.py`**

```python
"""Analysis-layer Method alias → canonical soft mapping."""
from __future__ import annotations

import re
from typing import Any

from extractor.entity_normalize import _norm_key, is_generic_method
from analysis.method_maturity import _ESTABLISHED_METHOD_ALIASES

_METHOD_SYNONYMS: dict[str, str] = {
    # curated human-approved only (seeds)
    "llm": "large language model",
    "large language models": "large language model",
    "support vector machines": "support vector machine",
    "svms": "support vector machine",
}

_SAFE_PLURALS: dict[str, str] = {
    "models": "model",
    "networks": "network",
    "algorithms": "algorithm",
}

_SKELETON_DROP = frozenset({
    "framework", "frameworks", "model", "models", "based", "using",
    "approach", "method", "methods", "system", "pipeline", "tool",
    "algorithm", "algorithms", "network", "networks", "the", "a", "an",
    "with", "and", "for", "of", "in", "on", "to",
})

_PAREN_RE = re.compile(r"^(?P<head>.+?)\s*\((?P<inner>[^)]+)\)\s*$")


def load_method_synonyms() -> dict[str, str]:
    return dict(_METHOD_SYNONYMS)


def apply_auto_method_canonical(name: str) -> str:
    key = _norm_key(name)
    # parenthetical: "support vector machine (svm)"
    m = _PAREN_RE.match(key)
    if m:
        head = _norm_key(m.group("head"))
        inner = _norm_key(m.group("inner"))
        if (
            head in _ESTABLISHED_METHOD_ALIASES
            or inner in _ESTABLISHED_METHOD_ALIASES
            or head in _METHOD_SYNONYMS
            or inner in _METHOD_SYNONYMS
        ):
            # prefer longer established form when inner is short alias
            if head in _ESTABLISHED_METHOD_ALIASES or head in _METHOD_SYNONYMS.values() or len(head) >= len(inner):
                key = head
            else:
                key = inner
    # safe last-token plural
    parts = key.split()
    if parts and parts[-1] in _SAFE_PLURALS:
        parts = parts[:-1] + [_SAFE_PLURALS[parts[-1]]]
        key = " ".join(parts)
    # established alias collapse to preferred display form
    if key in ("llm", "large language models"):
        return "large language model"
    if key in ("svm", "svms", "support vector machines"):
        return "support vector machine"
    return key


def resolve_method_canonical(name: str) -> str:
    key = _norm_key(name)
    if key in _METHOD_SYNONYMS:
        return _METHOD_SYNONYMS[key]
    auto = apply_auto_method_canonical(name)
    if auto in _METHOD_SYNONYMS:
        return _METHOD_SYNONYMS[auto]
    return auto


def method_skeleton(name: str) -> str:
    tokens = [
        t for t in _norm_key(name).replace("-", " ").split()
        if t and t not in _SKELETON_DROP
    ]
    return " ".join(tokens)


def near_duplicate_method_candidates(
    names: list[str],
    *,
    min_shared_tokens: int = 2,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from rapidfuzz import fuzz

    uniq = sorted({_norm_key(n) for n in names if n and str(n).strip()})
    # skip pairs already co-resolved
    out: list[dict[str, Any]] = []
    for i, a in enumerate(uniq):
        if is_generic_method(a) or a in _ESTABLISHED_METHOD_ALIASES and len(a.split()) <= 3:
            # still allow pairing non-umbrella with umbrella only as audit skip
            pass
        sa = method_skeleton(a)
        ta = frozenset(sa.split())
        for b in uniq[i + 1 :]:
            if resolve_method_canonical(a) == resolve_method_canonical(b) and a != b:
                continue  # already merged at runtime
            sb = method_skeleton(b)
            tb = frozenset(sb.split())
            shared = ta & tb
            reason = None
            score = 0.0
            if sa and sa == sb and sa:
                reason = "skeleton"
                score = 1.0
            elif len(shared) >= min_shared_tokens:
                reason = "jaccard"
                score = len(shared) / max(len(ta | tb), 1)
            else:
                ratio = fuzz.token_set_ratio(a, b) / 100.0
                if ratio >= 0.9 and abs(len(a) - len(b)) <= max(10, len(a) // 2):
                    reason = "fuzz"
                    score = ratio
            if not reason:
                continue
            # forbid suggesting map onto umbrella generic
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if is_generic_method(shorter):
                continue
            out.append({
                "alias": longer,
                "suggested_canonical": shorter,
                "score": round(score, 3),
                "reason": reason,
                "shared_tokens": sorted(shared),
            })
    out.sort(key=lambda r: (-float(r["score"]), r["alias"]))
    return out[:limit]
```

Adjust implementation so tests pass exactly (especially near-dup with `min_shared_tokens=1` for drugreflector pair). Keep forbid rule: never return resolve that maps long phrase → `deep learning`.

Export `_ESTABLISHED_METHOD_ALIASES` usage: if private import is undesirable, add `established_method_aliases() -> frozenset[str]` public helper on `method_maturity.py` in this same task.

- [ ] **Step 4: Run tests — expect PASS**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_synonyms.py -v
```

- [ ] **Step 5: Commit (if executing with commits)**

```bash
git add fulltext_workflow/analysis/method_synonyms.py fulltext_workflow/analysis/method_maturity.py fulltext_workflow/tests/test_method_synonyms.py
git commit -m "feat: add method synonym soft mapping helpers"
```

---

### Task 2: Hotspot Method aggregation by canonical

**Files:**
- Modify: `fulltext_workflow/analysis/weekly_hotspot.py`
- Modify: `fulltext_workflow/analysis/method_maturity.py` (`annotate_method_rows` / new `corpus_counts_by_canonical`)
- Create: `fulltext_workflow/tests/test_weekly_hotspot_synonyms.py`

**Interfaces:**
- Consumes: `resolve_method_canonical`
- Produces: Method rows in `compute_emerging_entities` / `compute_weekly_hotspots` keyed by canonical, with optional `alias_count`, `aliases`
- Corpus maturity counts summed by canonical (distinct PMIDs across alias entity ids)

- [ ] **Step 1: Write failing integration test**

```python
"""Canonical method aggregation for weekly hotspots."""
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
from db.schema import init_db, insert_relation, upsert_entity, upsert_paper  # noqa: E402


def _tmp_db(monkeypatch) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "HOTSPOT_MIN_RECENT_PAPERS", 2)
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
    eid = upsert_entity(name, "Method")
    insert_relation(
        "Paper", paper_id, "APPLIES_METHOD", "Method", eid,
        source_pmid=pmid, status="active",
    )


def test_two_aliases_merge_to_pass_min_recent(monkeypatch):
    _tmp_db(monkeypatch)
    import analysis.method_synonyms as ms

    monkeypatch.setitem(ms._METHOD_SYNONYMS, "niche-tool-v2", "niche-tool")
    p1 = _paper("1", 2)
    _edge("1", p1, "niche-tool")
    p2 = _paper("2", 3)
    _edge("2", p2, "niche-tool-v2")

    payload = compute_weekly_hotspots(window_days=14, prior_days=14)
    emerging = {r["name"]: r for r in payload["emerging_methods"]}
    assert "niche-tool" in emerging
    assert emerging["niche-tool"]["recent_cnt"] >= 2
    assert emerging["niche-tool"].get("alias_count", 1) >= 2
```

- [ ] **Step 2: Run test — expect FAIL**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_weekly_hotspot_synonyms.py::test_two_aliases_merge_to_pass_min_recent -v
```

- [ ] **Step 3: Implement aggregation**

**Preferred approach (distinct PMIDs):** For `entity_type == "Method"` in `compute_emerging_entities` (or a dedicated helper called from `compute_weekly_hotspots`):

1. Query window edges:

```sql
SELECT e.name, r.source_pmid AS pmid,
       CASE WHEN p.pmid IN (SELECT pmid FROM recent_pmids) THEN 1 ELSE 0 END AS in_recent,
       CASE WHEN p.pmid IN (SELECT pmid FROM prior_pmids) THEN 1 ELSE 0 END AS in_prior,
       COALESCE(p.citation_count, 0) AS cite,
       COALESCE(j.impact_factor, 0) AS impact_factor,
       p.year
FROM relations r
JOIN entities e ON r.object_id = e.id
JOIN papers p ON r.source_pmid = p.pmid
LEFT JOIN journals j ON p.journal_id = j.id
WHERE e.type = 'Method' AND r.relation = 'APPLIES_METHOD'
  AND <eligible>
  AND (in recent OR prior window)
```

2. Group by `resolve_method_canonical(name)`:
   - `recent_pmids` / `prior_pmids` sets
   - collect raw alias names
3. Build rows: `recent_cnt=len(recent)`, `prior_cnt=len(prior)`, avg cite/cpy/if over recent papers, `alias_count`, `aliases` (comma-joined top 5).
4. Filter `recent_cnt >= min_r`, then `_enrich_entity_rows`.

Keep Disease/Task on the existing SQL path.

**Corpus counts:** Add `corpus_applies_method_counts_canonical() -> dict[str, int]` that maps each entity name through `resolve_method_canonical` and unions PMIDs (or sums distinct via dict of sets). Use this in `annotate_method_rows` when annotating Method boards (pass flag or always resolve keys).

Also resolve combo `method` field through `resolve_method_canonical` before maturity annotate / sort (optional but recommended for consistency).

- [ ] **Step 4: Run related tests**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_weekly_hotspot_synonyms.py fulltext_workflow/tests/test_weekly_hotspot_maturity.py fulltext_workflow/tests/test_method_synonyms.py fulltext_workflow/tests/test_transferable_opportunities.py -v
```

Expected: PASS (update fixtures if alias resolve changes LLM naming).

- [ ] **Step 5: Commit (if executing with commits)**

```bash
git add fulltext_workflow/analysis/weekly_hotspot.py fulltext_workflow/analysis/method_maturity.py fulltext_workflow/tests/test_weekly_hotspot_synonyms.py
git commit -m "feat: aggregate weekly method hotspots by synonym canonical"
```

---

### Task 3: Audit CLI + docs + UI caption

**Files:**
- Modify: `fulltext_workflow/analysis/method_synonyms.py` (add `run_method_cluster_audit(...) -> str`)
- Modify: `fulltext_workflow/main.py`
- Modify: `fulltext_workflow/SCRIPTS.md`
- Modify: `fulltext_workflow/gap_ui.py` (methods tab caption)

**Interfaces:**
- Produces: `run_method_cluster_audit(limit: int = 50) -> str` markdown report
- CLI: `method-cluster-audit` like `task-quality-audit`

- [ ] **Step 1: Implement audit report builder**

Load all Method entity names + paper counts from DB; call `near_duplicate_method_candidates`; format markdown with top candidates; note “curate into `_METHOD_SYNONYMS` manually”.

- [ ] **Step 2: Wire `main.py`**

Copy `cmd_task_quality_audit` pattern → `cmd_method_cluster_audit`; register parser `method-cluster-audit` with `--limit` / `--output`; dispatch map entry.

- [ ] **Step 3: Docs + UI**

`SCRIPTS.md` 周热点 section add:

```powershell
& $py main.py method-cluster-audit
```

`gap_ui.py` methods caption append: 已按 method synonym 软归并（canonical 聚合）.

- [ ] **Step 4: Smoke CLI**

```powershell
cd d:\agent\prototype\build_kg_paper\fulltext_workflow
..\.venv\Scripts\python.exe main.py method-cluster-audit --limit 10
```

Expected: writes markdown under `output/`, stdout summary, exit 0.

- [ ] **Step 5: Run unit tests again**

```powershell
.\.venv\Scripts\python.exe -m pytest fulltext_workflow/tests/test_method_synonyms.py fulltext_workflow/tests/test_weekly_hotspot_synonyms.py -v
```

- [ ] **Step 6: Commit (if executing with commits)**

```bash
git add fulltext_workflow/analysis/method_synonyms.py fulltext_workflow/main.py fulltext_workflow/SCRIPTS.md fulltext_workflow/gap_ui.py
git commit -m "feat: add method-cluster-audit CLI and UI synonym caption"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Soft map APIs + auto rules + curated table | Task 1 |
| Forbid umbrella absorption | Task 1 tests |
| Distinct-PMID hotspot aggregate + alias fields | Task 2 |
| Maturity after resolve / canonical corpus counts | Task 2 |
| Audit CLI A+C candidates, no auto-write | Task 3 |
| UI / SCRIPTS | Task 3 |
| No extract rename / no embeddings | Global |

## Self-review notes

- Aggregation must use PMID sets, not summed counts.
- Publicize established-alias frozenset if needed to avoid brittle private imports.
- Transferable pool automatically benefits once `active_methods` uses canonical names from Task 2; no separate transferable rewrite required unless method strings in bridges stay raw — verify opportunities still match entity names in KG (edges use raw names). **Important:** transferable matching joins on raw KG method strings; if boards show canonical but edges stay raw, opportunity generation must resolve both sides with `resolve_method_canonical` when comparing method keys. Fold a small resolve step into `compute_emerging_gap_opportunities` method loop in Task 2 (resolve heat-pool keys and edge method names to canonical before pairing).
