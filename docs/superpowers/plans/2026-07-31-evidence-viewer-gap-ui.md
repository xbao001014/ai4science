# Evidence Viewer in Gap UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed a single-paper fulltext ↔ KG extraction provenance viewer into the Streamlit「证据与文献」tab, with summary tables first and on-demand drill-in from debate evidence rows or literature rows.

**Architecture:** New `viz/evidence_viewer.py` soft-loads one paper from SQLite, resolves an optional `focus_quote` to the best matching extraction, and renders embeddable single-paper HTML (left sections / right cards / click highlight). `gap_ui` keeps light summary tables, stores `{pmid, focus_quote}` in session state on「查看溯源」, then embeds via `st.components.v1.html`. Offline multi-paper `extraction_demo` keeps fail-fast export behavior and continues to pass existing tests.

**Tech Stack:** Python 3, SQLite (`kg_fulltext.db` via `db.schema`), Streamlit (`components.html`), pytest, vanilla HTML/CSS/JS (no CDN).

**Spec:** `docs/superpowers/specs/2026-07-31-evidence-viewer-gap-ui-design.md`

## Global Constraints

- Dual entry: debate evidence rows and literature paper rows share one viewer.
- Summary tables first; load fulltext only after「查看溯源」for the selected PMID.
- From debate evidence: show **all** active KG extractions; auto-select best match to `focus_quote`.
- Soft errors for UI (`ViewerLoadError` with `code` + `message_zh`); offline demo keeps fail-fast `DemoExportError`.
- Quote matching: reuse existing literal / whitespace / case / `;` fragment / ellipsis logic — no semantic search.
- Do not embed the viewer into debate-trajectory expanders.
- Do not preload all listed papers; embed height ~70vh (`height=720` is fine).
- Run pytest from `fulltext_workflow/` (tests insert that root on `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the tree dirty and note the suggested commit message.
- Do not commit `fulltext_workflow/output/` or secrets; do not change PubMed query groups.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/viz/evidence_viewer.py` | **New** — `ViewerLoadError`, `load_paper_for_viewer`, `resolve_focus_extraction`, `render_evidence_viewer_html` |
| `fulltext_workflow/tests/test_evidence_viewer.py` | **New** — soft load, focus resolve, HTML initial highlight / empty extractions |
| `fulltext_workflow/viz/extraction_demo.py` | Keep labels + `match_evidence_quote` + fail-fast multi-paper load/render; re-export or import shared pieces only if needed to avoid duplication of SQL shape |
| `fulltext_workflow/gap_ui.py` | Evidence tab: longer quote in summary; select+「查看溯源」/「关闭溯源」; embed viewer |
| `fulltext_workflow/tests/test_extraction_demo.py` | Must remain green (no intentional behavior change to offline export) |

---

### Task 1: Soft paper loader + focus resolution

**Files:**
- Create: `fulltext_workflow/viz/evidence_viewer.py`
- Test: `fulltext_workflow/tests/test_evidence_viewer.py`

**Interfaces:**
- Consumes: `config.DB_PATH`, `db.schema.get_conn`; `viz.extraction_demo` label maps + `match_evidence_quote` + `_object_type_sort_key` equivalent (import public symbols from `extraction_demo`: `STUDY_TYPE_LABELS_ZH`, `RELATION_LABELS_ZH`, `OBJECT_TYPE_GROUP_ORDER`, `match_evidence_quote`)
- Produces: `ViewerLoadError(code: str, message_zh: str)`, `load_paper_for_viewer(pmid: str, db_path: Path | str | None = None) -> dict`, `resolve_focus_extraction(paper: dict, focus_quote: str | None) -> int | None`

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_evidence_viewer.py`:

```python
"""Tests for single-paper evidence viewer load + focus resolve."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    init_db,
    insert_relation,
    insert_sections,
    mark_extraction_done,
    mark_fulltext_status,
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


def _seed_full(pmid: str = "1001") -> int:
    pid = upsert_paper(
        {"pmid": pmid, "title": f"Title {pmid}", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, "ai_algorithm")
    insert_sections(
        pid,
        [
            {
                "section_type": "methods",
                "title": "Methods",
                "content": "We apply ResNet on Camelyon16 with AUC 0.91.",
                "order_idx": 0,
            }
        ],
    )
    mid = upsert_entity("resnet", "Method")
    did = upsert_entity("camelyon16", "Dataset")
    insert_relation(
        "Paper", pid, "APPLIES_METHOD", "Method", mid,
        source_pmid=pmid, evidence_section="methods",
        evidence_quote="We apply ResNet", extraction_granularity="fulltext",
        confidence=0.9,
    )
    insert_relation(
        "Paper", pid, "USES_DATASET", "Dataset", did,
        source_pmid=pmid, evidence_section="methods",
        evidence_quote="Camelyon16 with AUC", extraction_granularity="fulltext",
        confidence=0.8,
    )
    return pid


def test_load_paper_for_viewer_ok(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer

    _tmp_db(monkeypatch)
    _seed_full("1001")
    paper = load_paper_for_viewer("1001")
    assert paper["pmid"] == "1001"
    assert len(paper["sections"]) == 1
    assert len(paper["extractions"]) == 2
    assert paper["extractions"][0]["object_type"] in {"Method", "Dataset"}


def test_load_paper_not_found(monkeypatch):
    from viz.evidence_viewer import ViewerLoadError, load_paper_for_viewer

    _tmp_db(monkeypatch)
    with pytest.raises(ViewerLoadError) as ei:
        load_paper_for_viewer("missing")
    assert ei.value.code == "not_found"
    assert "语料" in ei.value.message_zh or "不在" in ei.value.message_zh


def test_load_paper_no_fulltext(monkeypatch):
    from viz.evidence_viewer import ViewerLoadError, load_paper_for_viewer

    _tmp_db(monkeypatch)
    upsert_paper({"pmid": "1002", "title": "T", "year": 2025, "journal_name": "J"})
    with pytest.raises(ViewerLoadError) as ei:
        load_paper_for_viewer("1002")
    assert ei.value.code == "no_fulltext"


def test_load_paper_allows_empty_extractions(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "1003", "title": "T", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")
    insert_sections(
        pid,
        [{"section_type": "abstract", "title": "", "content": "Hello world.", "order_idx": 0}],
    )
    paper = load_paper_for_viewer("1003")
    assert paper["extractions"] == []
    assert paper["sections"][0]["content"] == "Hello world."


def test_resolve_focus_extraction_exact_and_none():
    from viz.evidence_viewer import resolve_focus_extraction

    paper = {
        "extractions": [
            {"evidence_quote": "We apply ResNet"},
            {"evidence_quote": "Camelyon16 with AUC"},
        ]
    }
    assert resolve_focus_extraction(paper, "Camelyon16 with AUC") == 1
    assert resolve_focus_extraction(paper, "We apply ResNet") == 0
    assert resolve_focus_extraction(paper, None) is None
    assert resolve_focus_extraction(paper, "totally unrelated xyz") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer.py -v`

Expected: FAIL with `ModuleNotFoundError` / import error for `viz.evidence_viewer`.

- [ ] **Step 3: Implement loader + focus resolve**

Create `fulltext_workflow/viz/evidence_viewer.py`:

```python
"""Single-paper fulltext ↔ extraction viewer for gap_ui embed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config
from db.schema import get_conn
from viz.extraction_demo import (
    OBJECT_TYPE_GROUP_ORDER,
    RELATION_LABELS_ZH,
    STUDY_TYPE_LABELS_ZH,
    match_evidence_quote,
)

_VALID_FULLTEXT_STATUSES = frozenset({"available", "pdf_available"})


class ViewerLoadError(Exception):
    def __init__(self, code: str, message_zh: str):
        self.code = code
        self.message_zh = message_zh
        super().__init__(message_zh)


def _object_type_sort_key(object_type: str) -> tuple[int, str]:
    try:
        return (OBJECT_TYPE_GROUP_ORDER.index(object_type), object_type)
    except ValueError:
        return (len(OBJECT_TYPE_GROUP_ORDER), object_type)


def load_paper_for_viewer(
    pmid: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    prev = config.DB_PATH
    if db_path is not None:
        config.DB_PATH = Path(db_path)
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE pmid = ?", (pmid,)
            ).fetchone()
            if row is None:
                raise ViewerLoadError("not_found", f"PMID {pmid} 不在语料中")
            if row["full_text_status"] not in _VALID_FULLTEXT_STATUSES:
                raise ViewerLoadError(
                    "no_fulltext",
                    f"PMID {pmid} 无可用全文，无法溯源到正文",
                )
            paper_id = row["id"]
            section_rows = conn.execute(
                """SELECT section_type, title, content, order_idx
                   FROM document_sections
                   WHERE paper_id = ?
                   ORDER BY order_idx""",
                (paper_id,),
            ).fetchall()
            if not section_rows:
                raise ViewerLoadError(
                    "no_sections",
                    f"PMID {pmid} 无分节正文，无法溯源到正文",
                )
            extraction_rows = conn.execute(
                """SELECT r.id, r.relation, r.metric_value, r.evidence_section,
                          r.evidence_quote, r.confidence, r.extraction_granularity,
                          e.name AS object_name, e.type AS object_type
                   FROM relations r
                   JOIN entities e ON e.id = r.object_id
                   WHERE r.subject_type = 'Paper'
                     AND r.subject_id = ?
                     AND (r.status = 'active' OR r.status IS NULL)
                   ORDER BY r.id""",
                (paper_id,),
            ).fetchall()
            study_type = row["study_type"] or "other"
            sections = [
                {
                    "section_type": sec["section_type"],
                    "title": sec["title"] or None,
                    "content": sec["content"],
                    "order_idx": sec["order_idx"],
                }
                for sec in section_rows
            ]
            extractions = sorted(
                [
                    {
                        "id": ext["id"],
                        "relation": ext["relation"],
                        "relation_label_zh": RELATION_LABELS_ZH.get(
                            ext["relation"], ext["relation"]
                        ),
                        "object_name": ext["object_name"],
                        "object_type": ext["object_type"],
                        "metric_value": ext["metric_value"] or None,
                        "evidence_section": ext["evidence_section"],
                        "evidence_quote": ext["evidence_quote"],
                        "confidence": ext["confidence"],
                        "extraction_granularity": ext["extraction_granularity"],
                    }
                    for ext in extraction_rows
                ],
                key=lambda e: _object_type_sort_key(e["object_type"]),
            )
            return {
                "pmid": pmid,
                "title": row["title"],
                "study_type": study_type,
                "study_type_label_zh": STUDY_TYPE_LABELS_ZH.get(study_type, study_type),
                "full_text_status": row["full_text_status"],
                "journal_name": row["journal_name"],
                "year": row["year"],
                "sections": sections,
                "extractions": extractions,
            }
    finally:
        config.DB_PATH = prev


def resolve_focus_extraction(
    paper: dict[str, Any],
    focus_quote: str | None,
) -> int | None:
    if not focus_quote or not str(focus_quote).strip():
        return None
    q = str(focus_quote).strip()
    best_i: int | None = None
    best_score = 0
    for i, ext in enumerate(paper.get("extractions") or []):
        eq = str(ext.get("evidence_quote") or "").strip()
        if not eq:
            continue
        if eq == q:
            return i
        score = 0
        if q in eq or eq in q:
            score = min(len(q), len(eq))
        else:
            hit = match_evidence_quote(eq, q) or match_evidence_quote(q, eq)
            if hit:
                score = hit[1] - hit[0]
        if score > best_score:
            best_score = score
            best_i = i
    return best_i if best_score > 0 else None
```

Leave `render_evidence_viewer_html` for Task 2 (or stub raising `NotImplementedError` if preferred).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer.py -v`

Expected: PASS for all Task 1 tests.

- [ ] **Step 5: Commit** (if executing with commits enabled)

```bash
git add fulltext_workflow/viz/evidence_viewer.py fulltext_workflow/tests/test_evidence_viewer.py
git commit -m "feat: add evidence viewer soft loader and focus resolve"
```

---

### Task 2: Single-paper HTML renderer

**Files:**
- Modify: `fulltext_workflow/viz/evidence_viewer.py`
- Modify: `fulltext_workflow/tests/test_evidence_viewer.py`

**Interfaces:**
- Consumes: paper dict from Task 1
- Produces: `render_evidence_viewer_html(paper: dict, *, initial_extraction_index: int | None = None, focus_quote: str | None = None, unmatched_focus: bool = False) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evidence_viewer.py`:

```python
def test_render_html_single_paper_no_tabs(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer, render_evidence_viewer_html

    _tmp_db(monkeypatch)
    _seed_full("2001")
    paper = load_paper_for_viewer("2001")
    html = render_evidence_viewer_html(paper, initial_extraction_index=0)
    assert "paper-tabs" not in html
    assert "DEMO_PAPERS" in html or "VIEWER_PAPER" in html
    assert "We apply ResNet" in html
    assert "initial_extraction_index" in html or "INITIAL_EXTRACTION_INDEX" in html
    assert "highlightEvidence" in html


def test_render_html_empty_extractions_and_focus_quote(monkeypatch):
    from viz.evidence_viewer import load_paper_for_viewer, render_evidence_viewer_html

    _tmp_db(monkeypatch)
    pid = upsert_paper(
        {"pmid": "2002", "title": "T", "year": 2025, "journal_name": "J"}
    )
    mark_fulltext_status(pid, "available")
    insert_sections(
        pid,
        [{
            "section_type": "abstract",
            "title": "",
            "content": "UniqueFocusQuoteXYZ appears here.",
            "order_idx": 0,
        }],
    )
    paper = load_paper_for_viewer("2002")
    html = render_evidence_viewer_html(
        paper, focus_quote="UniqueFocusQuoteXYZ", unmatched_focus=True
    )
    assert "暂无抽取" in html or "没有可展示的抽取" in html
    assert "UniqueFocusQuoteXYZ" in html
    assert "证据未精确匹配到抽取卡" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer.py::test_render_html_single_paper_no_tabs tests/test_evidence_viewer.py::test_render_html_empty_extractions_and_focus_quote -v`

Expected: FAIL (`render_evidence_viewer_html` missing or incomplete).

- [ ] **Step 3: Implement `render_evidence_viewer_html`**

Adapt the CSS/JS from `viz/extraction_demo.py` `render_extraction_demo_html`, with these deliberate differences:

1. Embed **one** paper as `window.VIEWER_PAPER = {...}` (not a list + tab bar). Remove `#paper-tabs` / multi-paper UI.
2. Inject:
   - `window.INITIAL_EXTRACTION_INDEX = <int|null>`
   - `window.FOCUS_QUOTE = <string|null>`
   - `window.UNMATCHED_FOCUS = <bool>`
3. On load: `renderPaper()` then if `INITIAL_EXTRACTION_INDEX != null` call `highlightEvidence(INITIAL_EXTRACTION_INDEX)`; else if `FOCUS_QUOTE` try direct fulltext highlight across sections (reuse `matchEvidenceQuote` on each section); if `UNMATCHED_FOCUS` show a muted banner「证据未精确匹配到抽取卡」above the right pane.
4. Empty `extractions`: right pane text「暂无抽取结果。」
5. Escape `<` in JSON the same way as demo: `.replace("<", r"\u003c")`.
6. Keep click-to-highlight behavior identical to demo for cards that exist.

Minimal Python wrapper shape:

```python
def render_evidence_viewer_html(
    paper: dict[str, Any],
    *,
    initial_extraction_index: int | None = None,
    focus_quote: str | None = None,
    unmatched_focus: bool = False,
) -> str:
    payload = json.dumps(paper, ensure_ascii=False).replace("<", r"\u003c")
    init_idx = (
        "null"
        if initial_extraction_index is None
        else str(int(initial_extraction_index))
    )
    fq = json.dumps(focus_quote or None, ensure_ascii=False).replace("<", r"\u003c")
    unmatched = "true" if unmatched_focus else "false"
    # return HTML string with placeholders replaced:
    # __PAPER_JSON__, __INIT_IDX__, __FOCUS_QUOTE__, __UNMATCHED__
    ...
```

Copy match/highlight JS from the demo (same functions). Title can be「证据溯源」; footer「点击右侧条目可定位左侧证据」.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer.py -v`

Expected: PASS.

Also run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_extraction_demo.py -v`

Expected: PASS (unchanged).

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/viz/evidence_viewer.py fulltext_workflow/tests/test_evidence_viewer.py
git commit -m "feat: render embeddable single-paper evidence viewer HTML"
```

---

### Task 3: Wire「证据与文献」tab in gap_ui

**Files:**
- Modify: `fulltext_workflow/gap_ui.py` (`extract_evidence` quote length; new helper; both evidence-tab branches ~2030 and ~2129)
- Test: `fulltext_workflow/tests/test_evidence_viewer_ui.py` (pure helpers, no Streamlit runtime)

**Interfaces:**
- Consumes: `load_paper_for_viewer`, `resolve_focus_extraction`, `render_evidence_viewer_html`, `ViewerLoadError`
- Produces: `set_evidence_viewer_selection(pmid: str, focus_quote: str | None = None) -> dict` (session payload shape), `clear_evidence_viewer_selection() -> None` pattern via returned empty dict; `render_evidence_literature_section(events, focus)` used by both pre/post-debate branches

- [ ] **Step 1: Write failing helper tests**

Create `fulltext_workflow/tests/test_evidence_viewer_ui.py`:

```python
"""Pure helpers for evidence-tab viewer selection (no Streamlit)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_evidence_viewer_selection_payload():
    from gap_ui import make_evidence_viewer_selection

    assert make_evidence_viewer_selection("123", "quote A") == {
        "pmid": "123",
        "focus_quote": "quote A",
    }
    assert make_evidence_viewer_selection("123", None) == {
        "pmid": "123",
        "focus_quote": None,
    }
    assert make_evidence_viewer_selection("  ", "x") is None
    assert make_evidence_viewer_selection("", None) is None


def test_extract_evidence_keeps_longer_quote():
    from gap_ui import extract_evidence

    events = [{
        "type": "tool_result",
        "name": "author_stated_gaps",
        "result": {
            "data": [{
                "source_pmid": "999",
                "title": "Gap entity",
                "evidence_section": "discussion",
                "evidence_quote": "A" * 200,
            }]
        },
    }]
    rows = extract_evidence(events)
    assert len(rows) == 1
    assert len(rows[0]["摘录"]) == 200  # was 120; now allow up to 240 or full if shorter
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer_ui.py -v`

Expected: FAIL (`make_evidence_viewer_selection` missing and/or quote still truncated to 120).

- [ ] **Step 3: Implement helpers + tab UI**

In `gap_ui.py`:

1. Change `extract_evidence` quote truncation from `[:120]` to `[:240]`.

2. Add near other extract helpers:

```python
def make_evidence_viewer_selection(
    pmid: str | None,
    focus_quote: str | None = None,
) -> dict | None:
    pid = str(pmid or "").strip()
    if not pid:
        return None
    fq = str(focus_quote).strip() if focus_quote else None
    return {"pmid": pid, "focus_quote": fq or None}
```

3. Add `render_evidence_literature_section(events: list[dict], focus: str | None) -> None` that:
   - Builds `evidence = extract_evidence(events)` and `papers, lit_strategy = resolve_evidence_literature_papers(events, focus, limit=50)`.
   - Renders evidence subheader + `safe_table` (or info if empty).
   - If any evidence rows have PMID: `st.selectbox` options like `f"{pmid} · {title[:40]} · {quote[:40]}"` with index mapping; button「查看溯源（证据）」sets `st.session_state["evidence_viewer"] = make_evidence_viewer_selection(pmid, full_quote)` where `full_quote` is the row’s raw摘录 (use a parallel list of dicts with untruncated quote — keep full quote in extract_evidence 摘录 up to 240, which is enough for focus match).
   - Renders papers table similarly with selectbox +「查看溯源（论文）」setting `focus_quote=None`.
   - If `st.session_state.get("evidence_viewer")`: show divider, title「证据溯源」, optional caption for unmatched,「关闭溯源」button clearing the key; try `load_paper_for_viewer(pmid)`; on `ViewerLoadError` show `st.warning(err.message_zh)` and return; else `idx = resolve_focus_extraction(paper, focus_quote)`; `unmatched = bool(focus_quote) and idx is None`; `html = render_evidence_viewer_html(paper, initial_extraction_index=idx, focus_quote=focus_quote if unmatched else None, unmatched_focus=unmatched)`; `components.html(html, height=720, scrolling=True)`.

4. Replace both evidence-tab bodies (empty-events branch and events branch) with calls to `render_evidence_literature_section(...)`.

Init key once with other session defaults if needed: `"evidence_viewer": None`.

- [ ] **Step 4: Run tests**

Run:

```
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer_ui.py tests/test_evidence_viewer.py tests/test_extraction_demo.py -v
```

Expected: PASS.

Manual smoke (optional): `streamlit run gap_ui.py`, set focus, open「证据与文献」, select a corpus paper,「查看溯源」— split view appears; close clears it.

- [ ] **Step 5: Commit** (if enabled)

```bash
git add fulltext_workflow/gap_ui.py fulltext_workflow/tests/test_evidence_viewer_ui.py
git commit -m "feat: embed evidence provenance viewer in 证据与文献 tab"
```

---

### Task 4: Regression + acceptance checklist

**Files:** none new (verification only)

- [ ] **Step 1: Run full related pytest**

```
cd fulltext_workflow
..\.venv\Scripts\python.exe -m pytest tests/test_evidence_viewer.py tests/test_evidence_viewer_ui.py tests/test_extraction_demo.py -v
```

Expected: all PASS.

- [ ] **Step 2: Spec acceptance mapping**

Confirm mentally / manually:

| Acceptance (spec) | Covered by |
|-------------------|------------|
| Light table until drill-in | Task 3: load only when session set |
| Paper row → split view | Task 3 paper selectbox |
| Debate row → auto-select + highlight | Task 1 resolve + Task 2 initial index |
| Mismatch caption | Task 2 `unmatched_focus` |
| Soft Chinese errors | Task 1 `ViewerLoadError` + Task 3 warning |
| Demo tests green | Task 2/4 regression |

- [ ] **Step 3: Commit** only if there are leftover fixes; otherwise note “no further commit”.

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Dual entry shared viewer | Task 3 |
| Summary then drill-in | Task 3 |
| All KG + auto-select focus quote | Task 1 `resolve_focus_extraction` + Task 2/3 |
| Shared module + demo still works | Tasks 1–2, 4 |
| Soft errors / empty extractions + direct quote | Tasks 1–2 |
| No trajectory embed / no semantic match / no preload all | Global constraints |
| Longer summary quotes | Task 3 `[:240]` |

No TBD placeholders. Interface names consistent: `load_paper_for_viewer`, `resolve_focus_extraction`, `render_evidence_viewer_html`, `ViewerLoadError`, `make_evidence_viewer_selection`.
