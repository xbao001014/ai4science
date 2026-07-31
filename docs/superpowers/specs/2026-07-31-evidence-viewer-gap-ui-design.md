# Evidence Viewer in Gap UI Design

**Date:** 2026-07-31  
**Status:** Approved for implementation planning  
**Scope:** Merge the fulltext ↔ extraction对照交互 into the Streamlit「证据与文献」tab, reusing the extraction-demo viewer as a shared single-paper component.  
**Related:** `docs/superpowers/specs/2026-07-29-extraction-demo-design.md`

## Problem summary

「证据与文献」目前只展示扁表格：辩论摘录截断约 120 字，文献只有元数据。离线 `extraction_demo.html` 已具备「左全文分节 + 右抽取卡片 + 点击高亮」能力，但原设计明确不嵌入 `gap_ui`。结果是分析 UI 无法做证据溯源，demo 与产品能力脱节。

## Goals

- 在「证据与文献」中提供与 demo 同质的单篇溯源查看器。
- **双入口**：辩论证据行与论文行均可进入；共用同一查看器。
- **摘要先、溯源后**：默认仍是轻量表格；点「查看溯源」再按需加载全文与抽取。
- 从辩论证据进入时：右侧展示该文**全部** active KG 抽取，并自动选中与 `focus_quote` 最匹配的一条后高亮左侧。
- 抽出可复用模块，离线多篇 demo 导出继续可用。

## Non-goals

- 改变离线 demo 的对外叙事、默认 PMID 集，或要求每次 UI 使用都导出 HTML 文件。
- 在查看器内编辑 / 作废关系，或做 QA diff。
- 语义 / 向量模糊匹配（沿用 demo 的字面 → 空白灵活 → 大小写 → 分号片段 / 省略号逻辑）。
- 把对照器嵌进「辩论轨迹」逐步 expander。
- 预加载列表中全部论文的全文（仅当前选中 PMID）。

## Decisions (brainstorming)

| Topic | Choice |
|-------|--------|
| Content scope | Dual entry (debate evidence + literature papers), shared viewer |
| Embedding | Summary tables first; 「查看溯源」then embed full viewer |
| Debate-row right pane | All KG extractions for the paper; auto-select best match to quote |
| Architecture | Extract shared single-paper viewer; demo becomes thin multi-paper wrapper |

## Approaches considered

| Approach | Summary | Verdict |
|----------|---------|---------|
| 1. Call demo renderer as-is from gap_ui | Fast, but multi-tab HTML + fail-fast eligibility clash with UI | Rejected |
| 2. Shared `evidence_viewer` module + gap_ui wiring | Clear boundaries; focus_quote; soft errors | **Chosen** |
| 3. Pure Streamlit columns + markdown highlight | No iframe; weak scroll/highlight parity | Rejected |

## Information architecture

### Evidence tab layout

1. **全文证据（摘要表）** — from debate `tool_result` rows via existing `extract_evidence` (may slightly lengthen quote display; keep table scannable). Each row with a PMID offers **查看溯源**.
2. **论文（摘要表）** — via existing `resolve_evidence_literature_papers`. Each row offers **查看溯源**.
3. **溯源查看器（按需）** — below the tables when session selection is set: embedded single-paper HTML (left fulltext / right extractions).

### Interaction

- Clicking **查看溯源** on an evidence row sets `session_state` to `{pmid, focus_quote}`.
- Clicking **查看溯源** on a paper row sets `{pmid, focus_quote: None}`.
- Viewer loads one paper from `kg_fulltext.db`: `document_sections` + active `relations` (NULL status treated as active), same payload shape as the demo.
- If `focus_quote` is set: resolve best-matching extraction index (compare quote to each card’s `evidence_quote` with existing match helpers; prefer exact/longest contiguous hit). On load, auto-run highlight for that index. If no card matches, show a Chinese caption「证据未精确匹配到抽取卡」and still attempt section-level scroll / direct quote highlight in fulltext when possible.
- Clearing selection (optional small「关闭溯源」control) removes the embedded viewer and frees the heavy HTML.

## Module design

| Unit | Responsibility |
|------|----------------|
| `fulltext_workflow/viz/evidence_viewer.py` | Single-paper load with structured errors; `resolve_focus_extraction`; `render_evidence_viewer_html(paper, initial_index=None)` for embeddable HTML |
| `fulltext_workflow/viz/extraction_demo.py` | Keep multi-paper offline export; refactor to call shared load/match/render where practical |
| `fulltext_workflow/gap_ui.py` | Evidence tab: summary tables + selection buttons + `st.components.v1.html` embed |
| Tests | Viewer load / focus resolve / HTML initial highlight; soft-error paths; existing `test_extraction_demo` still green |

### Suggested interfaces

```python
class ViewerLoadError(Exception):
    """Structured failure: missing paper / no fulltext / no sections."""
    code: str  # e.g. "not_found", "no_fulltext", "no_sections"
    message_zh: str

def load_paper_for_viewer(pmid: str, db_path: Path | None = None) -> dict:
    """Return demo-shaped paper dict. May return extractions=[] if none active."""

def resolve_focus_extraction(paper: dict, focus_quote: str | None) -> int | None:
    """Best extraction index for focus_quote, or None."""

def render_evidence_viewer_html(
    paper: dict,
    *,
    initial_extraction_index: int | None = None,
) -> str:
    """Single-paper HTML (no multi-paper tab bar)."""
```

`load_demo_papers` may keep fail-fast `DemoExportError` for the offline exporter; UI uses `load_paper_for_viewer` which soft-fails per above.

## Data flow

```
debate events / focus literature
  → extract_evidence / resolve_evidence_literature_papers  (summary)
user clicks 查看溯源
  → session: {pmid, focus_quote?}
  → load_paper_for_viewer(pmid)
  → resolve_focus_extraction(paper, focus_quote?)
  → render_evidence_viewer_html(paper, initial_index?)
  → st.components.v1.html(..., height≈70vh)
```

## Error handling

| Case | UI behavior |
|------|-------------|
| PMID not in DB | `st.warning` — 论文不在语料 |
| No fulltext / no sections | Explain 无法溯源到正文; do not embed empty iframe |
| Fulltext present, zero active extractions | Embed viewer with left pane only; right pane explains 暂无抽取; if `focus_quote` set, try highlight quote in fulltext directly |
| `focus_quote` matches no extraction card | Open viewer; caption 证据未精确匹配到抽取卡; best-effort section / quote highlight |
| Oversized HTML risk | Load only selected PMID; ~70vh scroll panes; never preload all listed papers |

## Testing / acceptance

1. Without clicking 查看溯源, the evidence tab stays a light table (no fulltext payload).
2. From a paper row: single-paper split view; card click highlights quote.
3. From a debate evidence row: auto-selects best-matching extraction and highlights; mismatch shows explicit caption.
4. Missing data yields readable Chinese errors, not a blank iframe.
5. `export_extraction_demo` path and existing `tests/test_extraction_demo.py` still pass.
6. New tests cover `resolve_focus_extraction` and soft load errors for the viewer module.

## Out of scope follow-ups (optional later)

- Deep-link from debate trajectory cards into the same viewer.
- Export current selection as a one-paper offline HTML download button.
- Show debate-only quote as a temporary card when it matches no KG edge.
