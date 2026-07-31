"""Single-paper fulltext ↔ extraction viewer for gap_ui embed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config
from db.schema import get_conn
from viz.extraction_demo import (
    RELATION_LABELS_ZH,
    STUDY_TYPE_LABELS_ZH,
    _object_type_sort_key,
    _VALID_FULLTEXT_STATUSES,
    match_evidence_quote,
)


class ViewerLoadError(Exception):
    def __init__(self, code: str, message_zh: str):
        self.code = code
        self.message_zh = message_zh
        super().__init__(message_zh)

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
            overlap_length = min(len(q), len(eq))
            if overlap_length >= 8:
                score = overlap_length
        else:
            hit = match_evidence_quote(eq, q) or match_evidence_quote(q, eq)
            if hit and hit[1] - hit[0] >= 8:
                score = hit[1] - hit[0]
        # Strict improvement preserves the first-seen candidate on ties.
        if score > best_score:
            best_score = score
            best_i = i
    return best_i if best_score > 0 else None


def render_evidence_viewer_html(
    paper: dict[str, Any],
    *,
    initial_extraction_index: int | None = None,
    focus_quote: str | None = None,
    unmatched_focus: bool = False,
) -> str:
    """Render a self-contained single-paper evidence viewer."""
    payload = json.dumps(paper, ensure_ascii=False).replace("<", r"\u003c")
    init_idx = (
        "null"
        if initial_extraction_index is None
        else str(int(initial_extraction_index))
    )
    fq = json.dumps(focus_quote or None, ensure_ascii=False).replace("<", r"\u003c")
    unmatched = "true" if unmatched_focus else "false"
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>证据溯源</title>
<style>
  :root { color: #1f2937; background: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  * { box-sizing: border-box; }
  body { margin: 0; }
  .app { max-width: 1440px; margin: 0 auto; padding: 20px; }
  h1 { margin: 0 0 14px; font-size: 22px; }
  .panes { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 16px; }
  .pane { min-height: 66vh; max-height: 72vh; overflow: auto; background: #fff; border: 1px solid #dbe3ee; border-radius: 8px; }
  .pane-header { position: sticky; top: 0; z-index: 2; margin: 0; padding: 13px 16px; background: #f1f5f9; border-bottom: 1px solid #dbe3ee; font-size: 16px; }
  .paper-meta { padding: 14px 16px; border-bottom: 1px solid #e2e8f0; }
  .paper-meta h2 { margin: 0 0 6px; font-size: 17px; }
  .muted { color: #64748b; font-size: 13px; }
  .focus-banner { padding: 10px 12px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; }
  .section { padding: 0 16px 14px; }
  .section-heading { position: sticky; top: 48px; z-index: 1; margin: 0 -16px 9px; padding: 10px 16px 7px; background: #fff; border-bottom: 1px solid #eef2f7; font-size: 15px; }
  .section-content { white-space: pre-wrap; line-height: 1.7; }
  .extraction-card { margin: 10px 12px; padding: 12px; border: 1px solid #dbe3ee; border-radius: 7px; cursor: pointer; }
  .extraction-card:hover, .extraction-card.selected { border-color: #2563eb; background: #eff6ff; }
  .relation { color: #1d4ed8; font-size: 13px; font-weight: 600; }
  .object { margin: 5px 0; font-weight: 600; }
  .evidence { color: #475569; font-size: 13px; line-height: 1.45; }
  .badge { display: inline-block; margin-top: 7px; padding: 3px 6px; color: #9a3412; background: #ffedd5; border-radius: 4px; font-size: 12px; }
  .hl { background: #fde68a; color: inherit; padding: 0 1px; }
  footer { padding: 14px 2px 0; color: #64748b; font-size: 13px; }
  @media (max-width: 820px) { .app { padding: 12px; } .panes { grid-template-columns: 1fr; } .pane { min-height: 45vh; } }
</style>
</head>
<body>
<main class="app">
  <h1>证据溯源</h1>
  <div class="panes">
    <section id="fulltext-pane" class="pane" aria-label="全文内容">
      <h2 class="pane-header">全文内容</h2>
      <div id="fulltext-content"></div>
    </section>
    <section id="extraction-pane" class="pane" aria-label="抽取元素">
      <h2 class="pane-header">抽取元素</h2>
      <div id="focus-banner"></div>
      <div id="extraction-content"></div>
    </section>
  </div>
  <footer>点击右侧条目可定位左侧证据</footer>
</main>
<script>
window.VIEWER_PAPER = __PAPER_JSON__;
window.INITIAL_EXTRACTION_INDEX = __INIT_IDX__;
window.FOCUS_QUOTE = __FOCUS_QUOTE__;
window.UNMATCHED_FOCUS = __UNMATCHED__;

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function candidateSectionTypes(evidenceSection) {
  const labeled = String(evidenceSection || "").trim();
  const fallback = [
    "discussion", "limitations", "future_work", "results",
    "methods", "other", "abstract", "introduction"
  ];
  if (!labeled || labeled === "fulltext_reconcile") return fallback;
  return [labeled, ...fallback.filter((t) => t !== labeled)];
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
}

function normalizeForMatch(text) {
  return String(text)
    .replace(/[\\u2010-\\u2015\\u2212\\uFE58\\uFE63\\uFF0D]/g, "-")
    .replace(/\\u00A0/g, " ")
    .replace(/\\uFEFF/g, "");
}

function matchLiteral(sectionText, quote) {
  if (!sectionText || !quote) return null;
  let i = sectionText.indexOf(quote);
  if (i >= 0) return [i, i + quote.length];
  const parts = quote.split(/\\s+/).filter(Boolean).map(escapeRegExp);
  if (parts.length) {
    let re = new RegExp(parts.join("\\\\s+"));
    let m = re.exec(sectionText);
    if (m) return [m.index, m.index + m[0].length];
    re = new RegExp(parts.join("\\\\s+"), "i");
    m = re.exec(sectionText);
    if (m) return [m.index, m.index + m[0].length];
  }
  i = sectionText.toLowerCase().indexOf(quote.toLowerCase());
  if (i >= 0) return [i, i + quote.length];
  const normSec = normalizeForMatch(sectionText);
  const normQ = normalizeForMatch(quote);
  if (normQ !== quote || normSec !== sectionText) {
    const tokens = normQ.split(/\\s+/).filter(Boolean).map(escapeRegExp);
    if (tokens.length) {
      const re = new RegExp(tokens.join("\\\\s+"), "i");
      const m = re.exec(sectionText);
      if (m) return [m.index, m.index + m[0].length];
    }
  }
  return null;
}

function matchEllipsisOrLiteral(sectionText, quote) {
  const direct = matchLiteral(sectionText, quote);
  if (direct) return direct;
  const parts = quote.split(/\\s*(?:\\.\\.\\.|…)\\s*/).map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return null;
  const spans = [];
  for (const part of parts) {
    if (part.length < 8) continue;
    const hit = matchLiteral(sectionText, part);
    if (hit) spans.push(hit);
  }
  if (!spans.length) return null;
  if (spans.length === 1) return spans[0];
  const start = Math.min(...spans.map((s) => s[0]));
  const end = Math.max(...spans.map((s) => s[1]));
  if (end - start > 800) {
    return spans.reduce((best, s) => (s[1] - s[0] > best[1] - best[0] ? s : best));
  }
  return [start, end];
}

function matchEvidenceQuote(sectionText, quote) {
  if (!sectionText || !quote) return null;
  const direct = matchLiteral(sectionText, quote);
  if (direct) return direct;
  const fragments = quote.split(/\\s*;\\s*/).map((f) => f.trim()).filter(Boolean);
  if (fragments.length > 1) {
    let best = null;
    for (const frag of fragments) {
      const hit = matchEllipsisOrLiteral(sectionText, frag);
      if (hit && (!best || (hit[1] - hit[0]) > (best[1] - best[0]))) best = hit;
    }
    if (best) return best;
  }
  return matchEllipsisOrLiteral(sectionText, quote);
}

function sectionTitle(section) {
  return section.title || section.section_type || "未命名章节";
}

function renderPaper() {
  const paper = window.VIEWER_PAPER;
  const metadata = `<div class="paper-meta"><h2>${escapeHtml(paper.title)}</h2>
    <div class="muted">PMID: ${escapeHtml(paper.pmid)} · ${escapeHtml(paper.study_type_label_zh)} · ${escapeHtml(paper.year || "")}</div></div>`;
  document.getElementById("fulltext-content").innerHTML = metadata + paper.sections.map((section, sectionIndex) =>
    `<article class="section" id="section-${sectionIndex}"><h3 class="section-heading">${escapeHtml(sectionTitle(section))}</h3>
      <div class="section-content">${escapeHtml(section.content)}</div></article>`
  ).join("");
  document.getElementById("fulltext-pane").scrollTop = 0;

  const banner = document.getElementById("focus-banner");
  banner.innerHTML = window.UNMATCHED_FOCUS
    ? '<div class="focus-banner muted">证据未精确匹配到抽取卡</div>'
    : "";
  const extractionContent = document.getElementById("extraction-content");
  extractionContent.innerHTML = paper.extractions.map((item, itemIndex) =>
    `<article class="extraction-card" data-index="${itemIndex}">
      <div class="relation">${escapeHtml(item.relation_label_zh)}</div>
      <div class="object">${escapeHtml(item.object_name)} <span class="muted">(${escapeHtml(item.object_type)})</span></div>
      <div class="evidence">证据：${escapeHtml(item.evidence_quote || "未提供")}</div>
      ${item.metric_value != null && item.metric_value !== "" ? `<div class="muted">指标：${escapeHtml(item.metric_value)}</div>` : ""}
      <div class="muted">证据章节：${escapeHtml(item.evidence_section || "未提供")}</div>
      <div class="muted">抽取粒度：${escapeHtml(item.extraction_granularity || "未提供")}</div>
      ${item.confidence != null ? `<div class="muted">置信度：${escapeHtml(item.confidence)}</div>` : ""}
      <div class="muted">PMID: ${escapeHtml(paper.pmid)}</div>
    </article>`
  ).join("") || `<p class="muted" style="padding: 12px">暂无抽取结果。</p>`;
  extractionContent.querySelectorAll(".extraction-card").forEach((card) =>
    card.addEventListener("click", () => highlightEvidence(Number(card.dataset.index)))
  );
}

function clearHighlights() {
  document.querySelectorAll(".section-content .hl").forEach((mark) => {
    const content = mark.parentElement;
    content.textContent = content.textContent;
  });
}

function highlightMatch(sectionIndex, section, match) {
  const content = document.querySelector(`#section-${sectionIndex} .section-content`);
  content.innerHTML = escapeHtml(section.content.slice(0, match[0])) +
    `<mark class="hl">${escapeHtml(section.content.slice(match[0], match[1]))}</mark>` +
    escapeHtml(section.content.slice(match[1]));
  content.querySelector(".hl").scrollIntoView({ block: "center", behavior: "smooth" });
}

function highlightEvidence(extractionIndex) {
  const paper = window.VIEWER_PAPER;
  const extraction = paper.extractions[extractionIndex];
  if (!extraction) return;
  const cards = document.querySelectorAll(".extraction-card");
  cards.forEach((card) => {
    card.classList.remove("selected");
    const badge = card.querySelector(".badge");
    if (badge) badge.remove();
  });
  const card = cards[extractionIndex];
  if (!card) return;
  card.classList.add("selected");

  clearHighlights();
  const typeSet = new Set(candidateSectionTypes(extraction.evidence_section));
  const matchingSections = paper.sections
    .map((section, index) => ({ section, index }))
    .filter(({ section }) => typeSet.has(section.section_type));
  const labeled = String(extraction.evidence_section || "").trim();
  matchingSections.sort((a, b) => {
    const aLabeled = a.section.section_type === labeled ? 0 : 1;
    const bLabeled = b.section.section_type === labeled ? 0 : 1;
    if (aLabeled !== bLabeled) return aLabeled - bLabeled;
    return a.index - b.index;
  });
  const matchedSection = matchingSections.find(({ section }) =>
    matchEvidenceQuote(section.content, extraction.evidence_quote)
  );
  const selectedSection = matchedSection || matchingSections[0];
  const sectionIndex = selectedSection && selectedSection.index;
  const section = selectedSection && selectedSection.section;
  const match = matchedSection && matchEvidenceQuote(section.content, extraction.evidence_quote);
  const sectionElement = sectionIndex != null && document.getElementById(`section-${sectionIndex}`);

  if (!section) {
    card.insertAdjacentHTML("beforeend", '<span class="badge">证据未精确匹配</span>');
    return;
  }
  if (!match) {
    card.insertAdjacentHTML("beforeend", '<span class="badge">证据未精确匹配</span>');
    sectionElement.scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
  highlightMatch(sectionIndex, section, match);
}

function highlightFocusQuote(quote) {
  clearHighlights();
  const paper = window.VIEWER_PAPER;
  for (let sectionIndex = 0; sectionIndex < paper.sections.length; sectionIndex += 1) {
    const section = paper.sections[sectionIndex];
    const match = matchEvidenceQuote(section.content, quote);
    if (match) {
      highlightMatch(sectionIndex, section, match);
      return true;
    }
  }
  return false;
}

renderPaper();
if (window.INITIAL_EXTRACTION_INDEX != null) {
  highlightEvidence(window.INITIAL_EXTRACTION_INDEX);
} else if (window.FOCUS_QUOTE) {
  highlightFocusQuote(window.FOCUS_QUOTE);
}
</script>
</body>
</html>
""".replace("__INIT_IDX__", init_idx).replace(
        "__FOCUS_QUOTE__", fq
    ).replace("__UNMATCHED__", unmatched).replace("__PAPER_JSON__", payload)
