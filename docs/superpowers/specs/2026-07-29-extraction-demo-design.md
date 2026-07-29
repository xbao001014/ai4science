# Fulltext ↔ Extraction Demo Design

**Date:** 2026-07-29  
**Status:** Approved for implementation planning  
**Scope:** Offline HTML demo showing fulltext sections mapped to extracted KG elements for three papers of different `study_type`. Audience: external presentation (capability demo), not internal QA tooling.

## Problem summary

The pipeline already stores sectioned full text (`document_sections`) and extraction edges (`relations` with `evidence_quote` / `evidence_section`), but there is no viewer that lets an audience see **source text → structured elements** side by side. Existing UIs (`gap_ui` evidence tables, Pyvis graphs) show outcomes without a paper-reader对照.

## Goals

- Deliver a **single self-contained HTML file** that opens offline (double-click; no Python/DB on the presentation machine).
- Showcase **three papers** with distinct `study_type` values.
- Interaction: **left = fulltext by section**, **right = extraction cards**; clicking a card scrolls the left pane and **highlights** the matching `evidence_quote`.
- Reproducible export via a script reading `kg_fulltext.db`.

## Non-goals

- Embedding into `gap_ui` tabs or debate / 方信 / weekly hotspot flows.
- Live DB connection, re-extraction, or editing annotations.
- Fuzzy / semantic quote matching beyond literal (± whitespace / case) search.
- Pyvis graph embedding or before/after QA diff views.
- Truncating long sections for “performance theater” (full section text is required for evidence context).

## Approaches considered

| Approach | Summary | Verdict |
|----------|---------|---------|
| 1. Snapshot → single HTML | Script embeds JSON + UI into one file | **Chosen** |
| 2. HTML + sidecar JSON | Page shell + `papers.json` | Easy to desync when copying |
| 3. Streamlit tab / “Save as” | Reuse gap_ui | Poor offline story; mixes with analysis UI |

## Information architecture

### Deliverables

| Artifact | Path |
|----------|------|
| Export script | `fulltext_workflow/scripts/export_extraction_demo.py` |
| PMID list (default trio) | `fulltext_workflow/data/demo_extraction_pmids.txt` |
| Demo output | `fulltext_workflow/output/extraction_demo.html` |

### Page layout

1. **Top bar** — demo title; three paper tabs (`study_type` Chinese label + short title).
2. **Main split** — left ~50% sectioned fulltext; right ~50% grouped extraction cards.
3. **Footer** — PMID / granularity hint; “click a card to locate evidence” affordance.

### Interaction

- Selecting a paper clears highlight and resets scroll for that paper.
- Clicking an extraction card:
  1. Jump to the target `evidence_section` in the left pane.
  2. Highlight the matched quote span when found.
  3. If no match: still scroll to the section; mark the card “证据未精确匹配”.

## Paper selection

### Type slots

| Slot | `study_type` | Demo emphasis |
|------|--------------|---------------|
| 1 | `ai_algorithm` | Methods, tasks, metrics, datasets |
| 2 | `review` | `SURVEYS_METHOD` / `COVERS_DISEASE`, limitations |
| 3 | `dataset_benchmark` (preferred) or `clinical_study` | `RELEASES_DATASET` / cohort datasets |

### Eligibility (each paper)

- `full_text_status` ∈ {`available`, `pdf_available`}
- `extraction_done = 1`
- ≥10 active relations with non-empty `evidence_quote` (soft floor for a convincing demo)
- ≥8 `document_sections` rows (enough scroll/structure)

### Default candidates

- Algorithm: `42306089`
- Review: `42200024`
- Third: chosen at export-prep time; if no classified `dataset_benchmark` / `clinical_study` exists with fulltext+extraction, pick one rich paper and **set `papers.study_type`** so demo labels stay consistent with the taxonomy.

Default PMIDs live in `data/demo_extraction_pmids.txt` (one PMID per line, `#` comments allowed). CLI `--pmids` overrides the file.

## Right-pane extraction display

Show only `relations` with `status = active` (or NULL treated as active).

Per card:

- Relation type with Chinese label (aligned with study-policy naming)
- Object entity name + type badge (`Method`, `Disease`, `Dataset`, …)
- Optional `metric_value`
- `evidence_section`, `extraction_granularity`; `confidence` shown lightly if present

Group order: Method → Disease → Task → Dataset → Metric → Modality → Limitation → other.

Do not list superseded edges or Pass-2 internal bookkeeping tables as primary cards (`paper_entity_bindings` / improvement suggestions are out of scope for this demo).

## Left-pane fulltext

- Sections ordered by `order_idx`.
- Render `section_type` (and title when present) as sticky subheaders.
- Full `content` text; no truncation.

## Export data contract

Embedded JSON (one object per paper):

```json
{
  "pmid": "42306089",
  "title": "...",
  "study_type": "ai_algorithm",
  "study_type_label_zh": "算法研究",
  "full_text_status": "available",
  "journal_name": "...",
  "year": 2025,
  "sections": [
    {"section_type": "abstract", "title": null, "content": "...", "order_idx": 0}
  ],
  "extractions": [
    {
      "id": 123,
      "relation": "APPLIES_METHOD",
      "relation_label_zh": "应用方法",
      "object_name": "...",
      "object_type": "Method",
      "metric_value": null,
      "evidence_section": "methods",
      "evidence_quote": "...",
      "confidence": 0.9,
      "extraction_granularity": "fulltext"
    }
  ]
}
```

Resolve `object_name` / `object_type` via `entities` joined on `relations.object_id`. Maintain a small ZH label map for `study_type` and `relation`.

### CLI

```text
python scripts/export_extraction_demo.py
  [--pmids A,B,C]
  [--db data/kg_fulltext.db]
  [--out output/extraction_demo.html]
```

Fail fast (non-zero exit, clear message) if a PMID is missing, lacks sections, or lacks active extractions — do not write a half-broken HTML.

## Highlight matching (client JS)

1. Within the target section’s text node(s), try exact substring match of `evidence_quote`.
2. If fail: collapse whitespace on both sides and retry.
3. If fail: case-insensitive match.
4. If fail: scroll to section only; flag card as unmatched.
5. No cross-section search; no fuzzy edit-distance.

## Success criteria

- Opening the HTML offline switches among three typed papers.
- Clicking cards highlights / locates evidence on the left for matched quotes.
- Study types are visually distinct in the tab bar.
- Copying only `extraction_demo.html` to another machine is enough to present.

## Implementation notes

- Prefer vanilla HTML/CSS/JS inside the exporter template (no build step, no CDN dependency required for core demo).
- Keep styling flat and presentation-friendly; Chinese UI copy for labels.
- Script may reuse existing DB helpers from `db/schema.py` where practical; avoid coupling to Streamlit.
