# Fulltext ↔ Extraction Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a self-contained offline HTML demo that对照 fulltext sections with extracted KG elements for three papers of different `study_type`.

**Architecture:** A testable Python module loads papers/sections/active relations from SQLite into a JSON payload; an HTML renderer embeds that payload and implements left/right panes with click-to-highlight via vanilla JS. A thin CLI reads a PMID list and writes `output/extraction_demo.html`.

**Tech Stack:** Python 3, SQLite (`kg_fulltext.db` via `db.schema`), pytest, single-file HTML/CSS/JS (no CDN required).

**Spec:** `docs/superpowers/specs/2026-07-29-extraction-demo-design.md`

## Global Constraints

- Audience is **external presentation** (offline HTML), not gap_ui / QA tooling.
- Deliver **one self-contained** `extraction_demo.html` (data embedded; no sidecar JSON).
- Show only `status='active'` (treat NULL as active) relations; resolve entity names via `entities`.
- Highlight matching: exact → whitespace-collapsed → case-insensitive within the target section only; never fuzzy across sections.
- Fail fast if any PMID is missing / has no sections / has no active extractions — do not write a half-broken HTML.
- Do not modify `gap_ui.py` navigation.
- Do not commit `fulltext_workflow/output/` (gitignored); commit source/script/tests/pmid list only.
- Run pytest from `fulltext_workflow/` (tests add that root to `sys.path`).
- Commit only when the user asks, or when executing under an explicit “implement the plan” request that includes commits; otherwise leave the working tree dirty and note the suggested commit message.
- Do not commit secrets; do not change PubMed query groups.

---

## File map

| File | Responsibility |
|------|----------------|
| `fulltext_workflow/viz/extraction_demo.py` | **New** — ZH label maps, PMID file parse, DB → demo payload, evidence match helper (Python mirror of JS), HTML render |
| `fulltext_workflow/scripts/export_extraction_demo.py` | **New** — CLI entrypoint |
| `fulltext_workflow/data/demo_extraction_pmids.txt` | **New** — default three PMIDs + comments |
| `fulltext_workflow/tests/test_extraction_demo.py` | **New** — payload, fail-fast, match helper, HTML structure |
| `fulltext_workflow/output/extraction_demo.html` | Generated artifact (gitignored) |

Default PMID trio (finalize in Task 3):

| PMID | Display `study_type` | Rationale |
|------|----------------------|-----------|
| `42351909` | `ai_algorithm` | Rich methods/tasks/metrics; 6 datasets |
| `42200024` | `review` | Already classified review; surveys/covers |
| `42306089` | `dataset_benchmark` | Title is comprehensive benchmarking; currently mislabeled `ai_algorithm` — update DB row for consistency |

---

### Task 1: Demo payload loader + evidence match helper

**Files:**
- Create: `fulltext_workflow/viz/extraction_demo.py`
- Test: `fulltext_workflow/tests/test_extraction_demo.py`

**Interfaces:**
- Produces: `STUDY_TYPE_LABELS_ZH: dict[str, str]`
- Produces: `RELATION_LABELS_ZH: dict[str, str]`
- Produces: `OBJECT_TYPE_GROUP_ORDER: list[str]`
- Produces: `parse_pmid_list(text: str) -> list[str]`
- Produces: `load_demo_papers(pmids: list[str], db_path: str | Path | None = None) -> list[dict]`
- Produces: `match_evidence_quote(section_text: str, quote: str) -> tuple[int, int] | None`
- `load_demo_papers` raises `DemoExportError` (subclass of `ValueError`) with a clear message when a PMID fails eligibility

- [ ] **Step 1: Write the failing tests**

Create `fulltext_workflow/tests/test_extraction_demo.py`:

```python
"""Tests for fulltext ↔ extraction demo export payload."""
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


def _seed_paper(pmid: str, study_type: str = "ai_algorithm") -> int:
    pid = upsert_paper(
        {
            "pmid": pmid,
            "title": f"Title for {pmid}",
            "year": 2025,
            "journal_name": "Demo Journal",
        }
    )
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, study_type)
    insert_sections(
        pid,
        [
            {
                "section_type": "abstract",
                "title": "",
                "content": "We apply ResNet on Camelyon16.",
                "order_idx": 0,
            },
            {
                "section_type": "methods",
                "title": "Methods",
                "content": "We apply ResNet on Camelyon16 with AUC 0.91.",
                "order_idx": 1,
            },
        ],
    )
    mid = upsert_entity("resnet", "Method")
    did = upsert_entity("camelyon16", "Dataset")
    insert_relation(
        "Paper",
        pid,
        "APPLIES_METHOD",
        "Method",
        mid,
        source_pmid=pmid,
        evidence_section="methods",
        evidence_quote="We apply ResNet",
        extraction_granularity="fulltext",
        confidence=0.9,
    )
    insert_relation(
        "Paper",
        pid,
        "USES_DATASET",
        "Dataset",
        did,
        source_pmid=pmid,
        evidence_section="methods",
        evidence_quote="Camelyon16 with AUC",
        extraction_granularity="fulltext",
    )
    lim = upsert_entity("small cohort", "Limitation")
    insert_relation(
        "Paper",
        pid,
        "REPORTS_LIMITATION",
        "Limitation",
        lim,
        source_pmid=pmid,
        evidence_section="discussion",
        evidence_quote="small cohort",
        status="superseded",
    )
    return pid


def test_parse_pmid_list_skips_comments_and_blanks():
    from viz.extraction_demo import parse_pmid_list

    text = "# trio\n42351909\n\n42200024  # review\n42306089\n"
    assert parse_pmid_list(text) == ["42351909", "42200024", "42306089"]


def test_match_evidence_quote_whitespace_and_case():
    from viz.extraction_demo import match_evidence_quote

    text = "We apply ResNet on Camelyon16."
    assert match_evidence_quote(text, "We apply ResNet") == (0, 15)
    assert match_evidence_quote(text, "we   apply   resnet") is not None
    assert match_evidence_quote(text, "missing quote xyz") is None


def test_load_demo_papers_payload_shape(monkeypatch):
    from viz.extraction_demo import load_demo_papers

    _tmp_db(monkeypatch)
    _seed_paper("900001")
    papers = load_demo_papers(["900001"])
    assert len(papers) == 1
    p = papers[0]
    assert p["pmid"] == "900001"
    assert p["study_type"] == "ai_algorithm"
    assert p["study_type_label_zh"]
    assert len(p["sections"]) == 2
    assert {e["relation"] for e in p["extractions"]} == {
        "APPLIES_METHOD",
        "USES_DATASET",
    }
    method = next(e for e in p["extractions"] if e["relation"] == "APPLIES_METHOD")
    assert method["object_name"] == "resnet"
    assert method["object_type"] == "Method"
    assert method["relation_label_zh"]
    assert method["evidence_quote"] == "We apply ResNet"


def test_load_demo_papers_fail_fast_missing(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    with pytest.raises(DemoExportError, match="900999"):
        load_demo_papers(["900999"])


def test_load_demo_papers_fail_fast_no_extractions(monkeypatch):
    from viz.extraction_demo import DemoExportError, load_demo_papers

    _tmp_db(monkeypatch)
    pid = upsert_paper({"pmid": "900002", "title": "Empty"})
    mark_fulltext_status(pid, "available")
    mark_extraction_done(pid, "review")
    insert_sections(
        pid,
        [{"section_type": "abstract", "content": "Only abstract.", "order_idx": 0}],
    )
    with pytest.raises(DemoExportError, match="900002"):
        load_demo_papers(["900002"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_extraction_demo.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'viz.extraction_demo'` (or import error for symbols).

- [ ] **Step 3: Implement `viz/extraction_demo.py` (data + match; stub HTML)**

Create `fulltext_workflow/viz/extraction_demo.py` with:

- `STUDY_TYPE_LABELS_ZH`, `RELATION_LABELS_ZH`, `OBJECT_TYPE_GROUP_ORDER` (cover all relations in study policy: APPLIES/COMPARES/SURVEYS_METHOD, TARGETS/COVERS_DISEASE, OPERATES_ON, PERFORMS_TASK, USES/RELEASES_DATASET, PRETRAINS_ON, ACHIEVES_METRIC, USES_MODALITY, REPORTS_LIMITATION, RELATED_TO)
- `class DemoExportError(ValueError)`
- `parse_pmid_list(text) -> list[str]` (strip `#` comments, blank lines)
- `match_evidence_quote(section_text, quote) -> tuple[int,int] | None` (exact → whitespace-flexible regex → case-insensitive)
- `load_demo_papers(pmids, db_path=None) -> list[dict]` querying `papers` + `document_sections` + active `relations` JOIN `entities`; sort extractions by object-type group order; raise `DemoExportError` on missing / bad status / no sections / no active extractions
- `render_extraction_demo_html(papers) -> str` raise `NotImplementedError` until Task 2

Payload keys per paper must match the spec JSON contract (`pmid`, `title`, `study_type`, `study_type_label_zh`, `full_text_status`, `journal_name`, `year`, `sections[]`, `extractions[]`).

When `db_path` is provided, temporarily set `config.DB_PATH` for `get_conn()` and restore in `finally`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_extraction_demo.py -v`

Expected: all Task 1 tests PASS.

- [ ] **Step 5: Commit (only if user requested commits)**

```bash
git add fulltext_workflow/viz/extraction_demo.py fulltext_workflow/tests/test_extraction_demo.py
git commit -m "feat(demo): load fulltext-extraction demo payload from SQLite"
```

---

### Task 2: HTML renderer (dual pane + highlight JS)

**Files:**
- Modify: `fulltext_workflow/viz/extraction_demo.py` (`render_extraction_demo_html`)
- Modify: `fulltext_workflow/tests/test_extraction_demo.py`

**Interfaces:**
- Consumes: `list[dict]` from `load_demo_papers`
- Produces: `render_extraction_demo_html(papers: list[dict[str, Any]]) -> str`
- Embed JSON as `window.DEMO_PAPERS` (escape `<` as `\u003c` in JSON to avoid `</script>` breakout)
- JS `matchEvidenceQuote` mirrors Python match order

- [ ] **Step 1: Write failing HTML test**

Append to `tests/test_extraction_demo.py`:

```python
def test_render_html_embeds_papers_and_controls(monkeypatch):
    from viz.extraction_demo import load_demo_papers, render_extraction_demo_html

    _tmp_db(monkeypatch)
    _seed_paper("900001", "ai_algorithm")
    _seed_paper("900003", "review")
    html = render_extraction_demo_html(load_demo_papers(["900001", "900003"]))
    assert "<!DOCTYPE html>" in html
    assert "window.DEMO_PAPERS" in html
    assert "900001" in html and "900003" in html
    assert 'id="fulltext-pane"' in html
    assert 'id="extraction-pane"' in html
    assert "matchEvidenceQuote" in html
    assert "证据未精确匹配" in html
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_extraction_demo.py::test_render_html_embeds_papers_and_controls -v`

Expected: FAIL (`NotImplementedError` or missing markers).

- [ ] **Step 3: Implement `render_extraction_demo_html`**

Return one HTML document with:

1. **CSS:** two-column layout; sticky section headers; `.hl` highlight; selected card state; tab bar; labels「全文内容」「抽取元素」; footer tip「点击右侧条目可定位左侧证据」. Flat styling; no CDN.
2. **Body:** `#paper-tabs`, `#fulltext-pane`, `#extraction-pane`, footer.
3. **Script:**
   - `window.DEMO_PAPERS = <json>;`
   - `matchEvidenceQuote(sectionText, quote)` — exact / whitespace-flexible / case-insensitive
   - `renderPaper(index)`, card click → scroll to `evidence_section`, wrap match in `<mark class="hl">`, or badge「证据未精确匹配」
   - Escape text when injecting into HTML (`&`, `<`, `>`)
   - Switching papers clears highlight

JS match sketch:

```javascript
function matchEvidenceQuote(sectionText, quote) {
  if (!sectionText || !quote) return null;
  let i = sectionText.indexOf(quote);
  if (i >= 0) return [i, i + quote.length];
  const collapse = (s) => s.replace(/\s+/g, " ").trim();
  const ct = collapse(sectionText), cq = collapse(quote);
  if (cq) {
    const parts = cq.split(" ").filter(Boolean).map(
      (p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    );
    if (parts.length) {
      const re = new RegExp(parts.join("\\s+"), "i");
      const m = re.exec(sectionText);
      if (m) return [m.index, m.index + m[0].length];
    }
  }
  i = sectionText.toLowerCase().indexOf(quote.toLowerCase());
  if (i >= 0) return [i, i + quote.length];
  return null;
}
```

- [ ] **Step 4: Run all demo tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_extraction_demo.py -v`

Expected: PASS.

- [ ] **Step 5: Commit (only if user requested commits)**

```bash
git add fulltext_workflow/viz/extraction_demo.py fulltext_workflow/tests/test_extraction_demo.py
git commit -m "feat(demo): render offline dual-pane extraction HTML"
```

---

### Task 3: CLI + PMID list + third-paper study_type

**Files:**
- Create: `fulltext_workflow/scripts/export_extraction_demo.py`
- Create: `fulltext_workflow/data/demo_extraction_pmids.txt`
- Modify: live DB only — `papers.study_type` for `42306089` → `dataset_benchmark` (do not commit `.db`)
- Modify: `fulltext_workflow/tests/test_extraction_demo.py` (CLI smoke via `importlib`)

**Interfaces:**
- Consumes: `parse_pmid_list`, `load_demo_papers`, `render_extraction_demo_html`
- Produces: CLI `main(argv: list[str] | None = None) -> int` writing UTF-8 HTML

- [ ] **Step 1: Write PMID list file**

Create `fulltext_workflow/data/demo_extraction_pmids.txt`:

```text
# Fulltext ↔ extraction demo trio (study_type slots)
42351909   # ai_algorithm
42200024   # review
42306089   # dataset_benchmark (update papers.study_type if still ai_algorithm)
```

- [ ] **Step 2: Update third paper study_type in DB**

```powershell
cd fulltext_workflow
..\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/kg_fulltext.db'); print(c.execute(\"SELECT pmid, study_type FROM papers WHERE pmid='42306089'\").fetchone()); c.execute(\"UPDATE papers SET study_type='dataset_benchmark' WHERE pmid='42306089'\"); c.commit(); print(c.execute(\"SELECT pmid, study_type FROM papers WHERE pmid='42306089'\").fetchone())"
```

Expected: `('42306089', 'dataset_benchmark')`. If PMID missing on this machine, query for another benchmarking-like extracted paper and update the pmid file — do not invent PMIDs.

- [ ] **Step 3: Implement CLI**

Create `fulltext_workflow/scripts/export_extraction_demo.py`:

```python
"""Export offline HTML: fulltext sections ↔ extracted elements."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from viz.extraction_demo import (  # noqa: E402
    DemoExportError,
    load_demo_papers,
    parse_pmid_list,
    render_extraction_demo_html,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmids", default="", help="Comma-separated PMIDs")
    parser.add_argument(
        "--pmid-file",
        default=str(ROOT / "data" / "demo_extraction_pmids.txt"),
    )
    parser.add_argument("--db", default="", help="SQLite path")
    parser.add_argument(
        "--out",
        default=str(ROOT / "output" / "extraction_demo.html"),
    )
    args = parser.parse_args(argv)

    if args.pmids.strip():
        pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
    else:
        pmids = parse_pmid_list(Path(args.pmid_file).read_text(encoding="utf-8"))

    try:
        papers = load_demo_papers(pmids, db_path=args.db or None)
        html = render_extraction_demo_html(papers)
    except DemoExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(papers)} papers, {out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: CLI test via importlib**

```python
def test_cli_main_writes_html(monkeypatch, tmp_path):
    import importlib.util

    _tmp_db(monkeypatch)
    _seed_paper("900001")
    path = _ROOT / "scripts" / "export_extraction_demo.py"
    spec = importlib.util.spec_from_file_location("export_extraction_demo", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    out = tmp_path / "demo.html"
    assert mod.main(["--pmids", "900001", "--out", str(out)]) == 0
    assert "DEMO_PAPERS" in out.read_text(encoding="utf-8")
```

- [ ] **Step 5: Run tests**

Run: `cd fulltext_workflow; ..\.venv\Scripts\python.exe -m pytest tests/test_extraction_demo.py -v`

Expected: PASS.

- [ ] **Step 6: Commit (only if user requested commits)**

```bash
git add fulltext_workflow/scripts/export_extraction_demo.py fulltext_workflow/data/demo_extraction_pmids.txt fulltext_workflow/tests/test_extraction_demo.py
git commit -m "feat(demo): add CLI and default PMIDs for extraction demo export"
```

---

### Task 4: Real-DB export smoke + manual interaction check

**Files:**
- Generate: `fulltext_workflow/output/extraction_demo.html` (gitignored)

- [ ] **Step 1: Export against live DB**

```powershell
cd fulltext_workflow
..\.venv\Scripts\python.exe scripts/export_extraction_demo.py
```

Expected: `Wrote ...\extraction_demo.html (3 papers, ... bytes)`, exit 0.

- [ ] **Step 2: Sanity-check HTML content**

```powershell
..\.venv\Scripts\python.exe -c "from pathlib import Path; h=Path('output/extraction_demo.html').read_text(encoding='utf-8'); assert '42351909' in h and '42200024' in h and '42306089' in h; assert 'matchEvidenceQuote' in h; print('ok', len(h))"
```

Expected: `ok <size>`.

- [ ] **Step 3: Manual browser check**

Open `fulltext_workflow/output/extraction_demo.html` and verify:
1. Three tabs switch papers.
2. Left sections / right grouped cards.
3. Clicking a card highlights and scrolls when quote matches.
4. Switching papers clears highlight.

- [ ] **Step 4: Suggested final source commit** (if user requested commits)

```bash
git add fulltext_workflow/viz/extraction_demo.py fulltext_workflow/scripts/export_extraction_demo.py fulltext_workflow/data/demo_extraction_pmids.txt fulltext_workflow/tests/test_extraction_demo.py
git commit -m "feat(demo): ship fulltext-to-extraction offline HTML exporter"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Single self-contained HTML | Task 2–4 |
| Three study_type slots + PMID file | Task 3 |
| Left fulltext / right cards | Task 2 |
| Click → scroll + highlight quote | Task 2 |
| Active relations only + entity names | Task 1 |
| ZH labels | Task 1–2 |
| Match order exact → whitespace → case | Task 1–2 |
| Fail-fast CLI | Task 1, 3 |
| No gap_ui / no CDN | Task 2 + constraints |
| Third-type DB label fix | Task 3 |
| Soft eligibility floors (≥10 quotes, ≥8 sections) | Selection-time via curated PMIDs; export fail-fast requires ≥1 section and ≥1 active extraction only |

## Name consistency

- `parse_pmid_list`, `load_demo_papers`, `match_evidence_quote`, `render_extraction_demo_html`, `DemoExportError`, CLI `main`
- DOM ids: `paper-tabs`, `fulltext-pane`, `extraction-pane`
- Output: `fulltext_workflow/output/extraction_demo.html`
