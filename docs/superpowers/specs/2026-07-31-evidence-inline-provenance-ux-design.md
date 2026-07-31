# Evidence Literature Inline Provenance UX Design

**Date:** 2026-07-31  
**Status:** Approved for implementation planning  
**Scope:** Replace the非直观 selectbox pickers on the「证据与文献」tab with compact per-row「溯源」buttons and full titles/quotes.  
**Related:** `docs/superpowers/specs/2026-07-31-evidence-viewer-gap-ui-design.md`

## Problem summary

After embedding the evidence viewer, entry UX still uses a truncated `selectbox` below each summary table (title/quote clipped to ~40 chars). Users must reconcile the table with a separate picker, which feels disconnected and hides literature names.

## Goals

- Drill into provenance **from the row itself** (evidence or paper).
- Show **full** titles / entity labels and readable quotes (no 40-char picker truncation).
- Remove the bottom「选择证据溯源 / 选择论文溯源」selectboxes.
- Keep the existing viewer payload, soft errors, and embed behavior unchanged.

## Non-goals

- Tool-grouped folders / expanders as the primary navigation (deferred).
- Changing HTML viewer matching, DB load, or debate trajectory deep-links.
- True HTML `<table>` buttons with JS→Streamlit callbacks.
- Raising the extract_evidence quote cap beyond the current 240 chars (already set).

## Decisions

| Topic | Choice |
|-------|--------|
| Entry model | Per-row「溯源」in a compact list (not selectbox) |
| Row layout | `columns` ~5:1 — metadata left, button right |
| Cap | Show first 30 rows; remainder under expander「更多…」 |
| Viewer | Unchanged (`evidence_viewer` session + `components.html`) |

## Approaches considered

| Approach | Verdict |
|----------|---------|
| Streamlit compact row list + button | **Chosen** |
| Custom HTML table + JS callback | Fragile with Streamlit |
| Dataframe selection / radio under table | Less direct than row button |

## Information architecture

### Evidence block

1. Subheader `全文证据（N 行）`.
2. For each row with PMID (up to 30 visible):
   - Left: full `标题/实体`, `PMID`, `工具`, `证据章节`, full `摘录` (as stored, ≤240).
   - Right: button「溯源」→ `make_evidence_viewer_selection(pmid, 摘录)`.
3. Rows without PMID: text only + muted note that溯源需要 PMID.
4. If more than 30 PMID-backed rows: expander「更多证据」for the rest with the same row UI.
5. Empty state unchanged.

### Papers block

1. Subheader `论文（N）` + existing corpus-strategy caption when applicable.
2. Same compact row pattern: full `标题`, year, journal, PMID, study type, source;「溯源」→ selection with `focus_quote=None`.
3. Cap 30 + expander「更多论文」.
4. Remove paper selectbox.

### Viewer (unchanged)

- Divider +「证据溯源」+「关闭溯源」+ load/render/embed as today.
- Evidence path keeps auto-focus quote matching; unmatched caption unchanged.

## Implementation notes

- Refactor `render_evidence_literature_section` in `gap_ui.py`; extract a small helper e.g. `render_provenance_row_list(...)` for DRY between evidence and papers.
- Button keys must be stable (`pmid` + hash of quote/title), not positional indices.
- Update `tests/test_evidence_viewer_ui.py`: drop selectbox-id assumptions; cover stable key helper and “no PMID → no openable selection”.
- Do not regress `tests/test_evidence_viewer.py`.

## Acceptance

1. No evidence/paper selectbox on the tab.
2. Clicking「溯源」on an evidence row opens the viewer with that PMID + quote.
3. Clicking「溯源」on a paper row opens the viewer with that PMID only.
4. Titles are not clipped to 40 characters in the list UI.
5. Lists longer than 30 fold extras into an expander.
6. Existing viewer soft-error and highlight behavior still works.
