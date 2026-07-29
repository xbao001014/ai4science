"""Fulltext ↔ extraction demo: payload loader, evidence match, HTML render (Task 2)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import config
from db.schema import get_conn

STUDY_TYPE_LABELS_ZH: dict[str, str] = {
    "ai_algorithm": "算法研究",
    "clinical_study": "临床研究",
    "review": "综述",
    "meta_analysis": "荟萃分析",
    "dataset_benchmark": "数据集基准",
    "foundation_model": "基础模型",
    "multimodal": "多模态",
    "other": "其他",
}

RELATION_LABELS_ZH: dict[str, str] = {
    "APPLIES_METHOD": "应用方法",
    "COMPARES_METHOD": "对比方法",
    "SURVEYS_METHOD": "综述方法",
    "TARGETS_DISEASE": "针对病种",
    "COVERS_DISEASE": "覆盖病种",
    "OPERATES_ON": "操作组织",
    "PERFORMS_TASK": "执行任务",
    "USES_DATASET": "使用数据集",
    "RELEASES_DATASET": "发布数据集",
    "PRETRAINS_ON": "预训练数据",
    "ACHIEVES_METRIC": "达成指标",
    "USES_MODALITY": "使用模态",
    "REPORTS_LIMITATION": "报告局限",
    "RELATED_TO": "相关",
}

OBJECT_TYPE_GROUP_ORDER: list[str] = [
    "Method",
    "Disease",
    "Task",
    "Dataset",
    "Metric",
    "Modality",
    "Limitation",
    "Tissue",
]

_VALID_FULLTEXT_STATUSES = frozenset({"available", "pdf_available"})


class DemoExportError(ValueError):
    """Raised when a PMID is ineligible for demo export."""


def parse_pmid_list(text: str) -> list[str]:
    """Parse PMID list file content; skip blank lines and ``#`` comments."""
    pmids: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped:
            stripped = stripped.split("#", 1)[0].strip()
        if stripped:
            pmids.append(stripped)
    return pmids


_DASH_RE = re.compile(r"[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]")


def candidate_section_types(evidence_section: str) -> list[str]:
    """Section types to search for an evidence quote.

    Pass-2 rows may use ``fulltext_reconcile`` (not a real section). Fall back to
    common narrative sections while keeping the labeled type first when valid.
    """
    labeled = (evidence_section or "").strip()
    fallback = [
        "discussion",
        "limitations",
        "future_work",
        "results",
        "methods",
        "other",
        "abstract",
        "introduction",
    ]
    if not labeled or labeled == "fulltext_reconcile":
        return fallback
    # Prefer the labeled type, then nearby narrative sections.
    rest = [t for t in fallback if t != labeled]
    return [labeled, *rest]


def _normalize_for_match(text: str) -> str:
    text = _DASH_RE.sub("-", text)
    text = text.replace("\u00a0", " ").replace("\ufeff", "")
    return text


def _match_literal(section_text: str, quote: str) -> tuple[int, int] | None:
    """Exact → whitespace-flexible → case-insensitive (single contiguous quote)."""
    if not quote or not section_text:
        return None

    idx = section_text.find(quote)
    if idx >= 0:
        return (idx, idx + len(quote))

    parts = quote.split()
    if parts:
        pattern = r"\s+".join(re.escape(p) for p in parts)
        m = re.search(pattern, section_text)
        if m:
            return (m.start(), m.end())
        m = re.search(pattern, section_text, re.IGNORECASE)
        if m:
            return (m.start(), m.end())

    m = re.search(re.escape(quote), section_text, re.IGNORECASE)
    if m:
        return (m.start(), m.end())

    # Dash / NBSP normalized retry (1:1 char swaps keep indices valid).
    norm_sec = _normalize_for_match(section_text)
    norm_q = _normalize_for_match(quote)
    if norm_q != quote or norm_sec != section_text:
        hit = _match_literal_raw(norm_sec, norm_q)
        if hit and len(norm_sec) == len(section_text):
            return hit
        if hit:
            tokens = norm_q.split()
            if tokens:
                pat = r"\s+".join(re.escape(t) for t in tokens)
                m = re.search(pat, section_text, re.IGNORECASE)
                if m:
                    return (m.start(), m.end())
    return None


def _match_literal_raw(section_text: str, quote: str) -> tuple[int, int] | None:
    idx = section_text.find(quote)
    if idx >= 0:
        return (idx, idx + len(quote))
    parts = quote.split()
    if parts:
        pattern = r"\s+".join(re.escape(p) for p in parts)
        m = re.search(pattern, section_text, re.IGNORECASE)
        if m:
            return (m.start(), m.end())
    m = re.search(re.escape(quote), section_text, re.IGNORECASE)
    if m:
        return (m.start(), m.end())
    return None


def match_evidence_quote(section_text: str, quote: str) -> tuple[int, int] | None:
    """Locate *quote* in *section_text*.

    Order: contiguous literal match → longest ``;`` fragment → ``...``/``…``
    ellipsis parts (prefer span covering first+last hit).
    """
    if not quote or not section_text:
        return None

    hit = _match_literal(section_text, quote)
    if hit:
        return hit

    # Multi-span evidence often joined with "; "
    fragments = [f.strip() for f in re.split(r"\s*;\s*", quote) if f.strip()]
    if len(fragments) > 1:
        best: tuple[int, int] | None = None
        for frag in fragments:
            # Also strip ellipsis inside a fragment before literal match.
            frag_hit = _match_ellipsis_or_literal(section_text, frag)
            if frag_hit and (best is None or (frag_hit[1] - frag_hit[0]) > (best[1] - best[0])):
                best = frag_hit
        if best:
            return best

    return _match_ellipsis_or_literal(section_text, quote)


def _match_ellipsis_or_literal(section_text: str, quote: str) -> tuple[int, int] | None:
    hit = _match_literal(section_text, quote)
    if hit:
        return hit
    parts = [p.strip() for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if p.strip()]
    if len(parts) < 2:
        return None
    spans: list[tuple[int, int]] = []
    for part in parts:
        if len(part) < 8:
            continue
        part_hit = _match_literal(section_text, part)
        if part_hit:
            spans.append(part_hit)
    if not spans:
        return None
    if len(spans) == 1:
        return spans[0]
    start = min(s[0] for s in spans)
    end = max(s[1] for s in spans)
    # Avoid highlighting huge ranges when parts are far apart.
    if end - start > 800:
        return max(spans, key=lambda s: s[1] - s[0])
    return (start, end)


def _object_type_sort_key(object_type: str) -> tuple[int, str]:
    try:
        return (OBJECT_TYPE_GROUP_ORDER.index(object_type), object_type)
    except ValueError:
        return (len(OBJECT_TYPE_GROUP_ORDER), object_type)


def _load_one_paper(conn: Any, pmid: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM papers WHERE pmid = ?",
        (pmid,),
    ).fetchone()
    if row is None:
        raise DemoExportError(f"PMID {pmid} not found in database")

    if row["full_text_status"] not in _VALID_FULLTEXT_STATUSES:
        raise DemoExportError(
            f"PMID {pmid} full_text_status={row['full_text_status']!r} "
            f"(need available or pdf_available)"
        )

    if not row["extraction_done"]:
        raise DemoExportError(f"PMID {pmid} extraction not done")

    paper_id = row["id"]
    section_rows = conn.execute(
        """SELECT section_type, title, content, order_idx
           FROM document_sections
           WHERE paper_id = ?
           ORDER BY order_idx""",
        (paper_id,),
    ).fetchall()
    if not section_rows:
        raise DemoExportError(f"PMID {pmid} has no document sections")

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
    if not extraction_rows:
        raise DemoExportError(f"PMID {pmid} has no active extractions")

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
                "relation_label_zh": RELATION_LABELS_ZH.get(ext["relation"], ext["relation"]),
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


def load_demo_papers(
    pmids: list[str],
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load demo payload for each PMID; fail fast on first ineligible paper."""
    prev_db_path = config.DB_PATH
    if db_path is not None:
        config.DB_PATH = Path(db_path)
    try:
        with get_conn() as conn:
            return [_load_one_paper(conn, pmid) for pmid in pmids]
    finally:
        config.DB_PATH = prev_db_path


def render_extraction_demo_html(papers: list[dict[str, Any]]) -> str:
    """Render a self-contained, offline fulltext-to-extraction demo."""
    papers_json = json.dumps(papers, ensure_ascii=False).replace("<", r"\u003c")
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>全文与抽取结果对照</title>
<style>
  :root { color: #1f2937; background: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  * { box-sizing: border-box; }
  body { margin: 0; }
  .app { max-width: 1440px; margin: 0 auto; padding: 20px; }
  h1 { margin: 0 0 14px; font-size: 22px; }
  .tab-bar { display: flex; gap: 8px; overflow-x: auto; margin-bottom: 14px; }
  .tab { border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; padding: 8px 12px; cursor: pointer; white-space: nowrap; }
  .tab.active { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
  .tab-title { display: block; max-width: 250px; overflow: hidden; text-overflow: ellipsis; }
  .tab-pmid { display: block; margin-top: 2px; font-size: 11px; opacity: .75; }
  .panes { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 16px; }
  .pane { min-height: 66vh; max-height: 72vh; overflow: auto; background: #fff; border: 1px solid #dbe3ee; border-radius: 8px; }
  .pane-header { position: sticky; top: 0; z-index: 2; margin: 0; padding: 13px 16px; background: #f1f5f9; border-bottom: 1px solid #dbe3ee; font-size: 16px; }
  .paper-meta { padding: 14px 16px; border-bottom: 1px solid #e2e8f0; }
  .paper-meta h2 { margin: 0 0 6px; font-size: 17px; }
  .muted { color: #64748b; font-size: 13px; }
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
  <h1>全文与结构化抽取对照</h1>
  <nav id="paper-tabs" class="tab-bar" aria-label="论文选择"></nav>
  <div class="panes">
    <section id="fulltext-pane" class="pane" aria-label="全文内容">
      <h2 class="pane-header">全文内容</h2>
      <div id="fulltext-content"></div>
    </section>
    <section id="extraction-pane" class="pane" aria-label="抽取元素">
      <h2 class="pane-header">抽取元素</h2>
      <div id="extraction-content"></div>
    </section>
  </div>
  <footer>点击右侧条目可定位左侧证据</footer>
</main>
<script>
window.DEMO_PAPERS = __PAPERS_JSON__;

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

let currentIndex = 0;

function sectionTitle(section) {
  return section.title || section.section_type || "未命名章节";
}

function shortTitle(title) {
  const text = String(title || "未命名论文");
  return text.length > 48 ? `${text.slice(0, 48)}…` : text;
}

function renderPaper(index) {
  currentIndex = index;
  const paper = window.DEMO_PAPERS[index];
  const tabs = document.getElementById("paper-tabs");
  tabs.innerHTML = window.DEMO_PAPERS.map((item, itemIndex) =>
    `<button class="tab ${itemIndex === index ? "active" : ""}" type="button">
      <span class="tab-title">${escapeHtml(item.study_type_label_zh)} · ${escapeHtml(shortTitle(item.title))}</span>
      <span class="tab-pmid">PMID: ${escapeHtml(item.pmid)}</span>
    </button>`
  ).join("");
  Array.from(tabs.children).forEach((tab, tabIndex) =>
    tab.addEventListener("click", () => renderPaper(tabIndex))
  );

  const metadata = `<div class="paper-meta"><h2>${escapeHtml(paper.title)}</h2>
    <div class="muted">PMID: ${escapeHtml(paper.pmid)} · ${escapeHtml(paper.study_type_label_zh)} · ${escapeHtml(paper.year || "")}</div></div>`;
  document.getElementById("fulltext-content").innerHTML = metadata + paper.sections.map((section, sectionIndex) =>
    `<article class="section" id="section-${sectionIndex}"><h3 class="section-heading">${escapeHtml(sectionTitle(section))}</h3>
      <div class="section-content">${escapeHtml(section.content)}</div></article>`
  ).join("");
  document.getElementById("fulltext-pane").scrollTop = 0;

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
  ).join("") || `<p class="muted" style="padding: 12px">没有可展示的抽取结果。</p>`;
  extractionContent.querySelectorAll(".extraction-card").forEach((card) =>
    card.addEventListener("click", () => highlightEvidence(Number(card.dataset.index)))
  );
}

function highlightEvidence(extractionIndex) {
  const paper = window.DEMO_PAPERS[currentIndex];
  const extraction = paper.extractions[extractionIndex];
  const cards = document.querySelectorAll(".extraction-card");
  cards.forEach((card) => {
    card.classList.remove("selected");
    const badge = card.querySelector(".badge");
    if (badge) badge.remove();
  });
  const card = cards[extractionIndex];
  card.classList.add("selected");

  document.querySelectorAll(".section-content .hl").forEach((mark) => {
    const content = mark.parentElement;
    content.textContent = content.textContent;
  });
  const typeSet = new Set(candidateSectionTypes(extraction.evidence_section));
  const matchingSections = paper.sections
    .map((section, index) => ({ section, index }))
    .filter(({ section }) => typeSet.has(section.section_type));
  // Prefer labeled type first (already ordered via candidateSectionTypes + section order).
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

  const content = document.querySelector(`#section-${sectionIndex} .section-content`);
  content.innerHTML = escapeHtml(section.content.slice(0, match[0])) +
    `<mark class="hl">${escapeHtml(section.content.slice(match[0], match[1]))}</mark>` +
    escapeHtml(section.content.slice(match[1]));
  content.querySelector(".hl").scrollIntoView({ block: "center", behavior: "smooth" });
}

if (window.DEMO_PAPERS.length) {
  renderPaper(0);
} else {
  document.getElementById("fulltext-content").innerHTML = '<p class="muted" style="padding: 12px">没有可展示的论文。</p>';
}
</script>
</body>
</html>
""".replace("__PAPERS_JSON__", papers_json)
