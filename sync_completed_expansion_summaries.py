"""Synchronize completed manual-PDF summaries into topic inventories."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
TOPICS = (
    "multimodal-method-summary",
    "segmentation-method-summary",
    "virtual-staining-method-summary",
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def summary_files(topic_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in (topic_dir / "method_summaries").glob("PMID_*.md"):
        match = re.match(r"PMID_(\d+)_", path.name)
        if match:
            files[match.group(1)] = path.name
    return files


def write_index(topic_dir: Path, selected: list[dict], files: dict[str, str]) -> None:
    lines = [
        "# 逐篇方法总结索引", "",
        "本目录中的条目均由本地全文或人工核验 PDF 生成；具体证据边界见各文档开头的“证据说明”。",
        "", "| PMID | 年份 | 论文 | 纳入角色 | 方法总结 |",
        "|---:|---:|---|---|---|",
    ]
    for row in selected:
        pmid = str(row.get("pmid") or "")
        filename = files.get(pmid)
        title = str(row.get("title") or "").replace("|", "\\|")
        role = str(row.get("selection_rationale") or row.get("rationale") or row.get("role") or "方法/基准")
        role = re.sub(r"\s+", " ", role).replace("|", "\\|")[:90]
        link = f"[{filename}]({quote(filename, safe='._-()')})" if filename else "缺失"
        lines.append(f"| {pmid} | {row.get('year', '')} | {title} | {role} | {link} |")
    lines.extend(["", f"共 {len(selected)} 篇。", ""])
    (topic_dir / "method_summaries" / "README.md").write_text("\n".join(lines), encoding="utf-8")


def sync_topic(name: str) -> dict:
    topic_dir = ROOT / name
    selected_path = topic_dir / "selected_papers.jsonl"
    expansion_path = topic_dir / "expansion_candidates.jsonl"
    selected = read_jsonl(selected_path)
    expansion = read_jsonl(expansion_path)
    files = summary_files(topic_dir)
    manifest_path = topic_dir / "summary_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest_by_pmid = {str(row.get("pmid")): row for row in manifest.get("results", [])}
    selected_by_pmid = {str(row.get("pmid")): row for row in selected}
    selected_pmids = {str(row.get("pmid")) for row in selected}
    added = 0

    for row in expansion:
        pmid = str(row.get("pmid") or "")
        if not pmid or pmid not in files:
            continue
        evidence_source = manifest_by_pmid.get(pmid, {}).get("source", "local_db_fulltext")
        row["full_text_status"] = (
            "manual_pdf_available" if evidence_source == "manual_pdf" else "db_fulltext_available"
        )
        row["evidence_source"] = evidence_source
        row["next_action"] = "已生成总结"
        row["summary_file"] = f"method_summaries/{files[pmid]}"
        if pmid in selected_by_pmid:
            selected_by_pmid[pmid]["full_text_status"] = row["full_text_status"]
            selected_by_pmid[pmid]["evidence_source"] = evidence_source
            selected_by_pmid[pmid]["summary_file"] = row["summary_file"]
        if pmid not in selected_pmids:
            selected.append({
                "priority": row.get("priority", "P1"),
                "pmid": pmid,
                "doi": row.get("doi"),
                "year": row.get("year"),
                "citation_count": row.get("citation_count"),
                "title": row.get("title"),
                "track": row.get("track"),
                "role": row.get("role", "method"),
                "method_hint": row.get("rationale"),
                "selection_rationale": row.get("rationale"),
                "selection_basis": ["expansion_candidate", "manual_pdf_verified"],
                "full_text_status": row["full_text_status"],
                "evidence_source": evidence_source,
                "summary_file": f"method_summaries/{files[pmid]}",
            })
            selected_pmids.add(pmid)
            added += 1

    selected.sort(key=lambda row: (int(row.get("year") or 0), str(row.get("pmid") or "")))
    write_jsonl(selected_path, selected)
    write_jsonl(expansion_path, expansion)
    write_index(topic_dir, selected, files)

    md_path = topic_dir / "expansion_candidates.md"
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8")
        for row in expansion:
            pmid = str(row.get("pmid") or "")
            if pmid in files:
                pattern = rf"(?m)^(\|[^\n]*\(PMID {re.escape(pmid)}\)[^\n]*\|)"
                match = re.search(pattern, text)
                if match:
                    updated = match.group(1).replace("unavailable", "manual_pdf_available")
                    updated = updated.replace("补充全文后生成总结", "已生成总结")
                    text = text[:match.start()] + updated + text[match.end():]
        md_path.write_text(text, encoding="utf-8")

    readme_path = topic_dir / "README.md"
    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8")
        text = re.sub(r"首批纳入\d+篇", f"当前纳入{len(selected)}篇", text)
        readme_path.write_text(text, encoding="utf-8")

    matrix_path = topic_dir / "coverage_gap_matrix.md"
    if matrix_path.exists():
        text = matrix_path.read_text(encoding="utf-8")
        note = (
            f"> **完成快照（2026-08-24）**：本地候选已全部生成逐篇总结；"
            f"当前方法库共 {len(selected)} 篇。剩余工作仅为外部通用基线卡，不属于待补全文队列。\n"
        )
        text = re.sub(r"(?m)^> \*\*完成快照（2026-08-24）\*\*：.*\n", "", text)
        text = text.replace("\n", "\n\n" + note, 1)
        text = re.sub(r"- B批：[^\n]*", "- B批：人工补充全文已全部到位并完成总结。", text)
        matrix_path.write_text(text, encoding="utf-8")

    return {"topic": name, "selected": len(selected), "added": added, "summaries": len(files)}


def main() -> None:
    for topic in TOPICS:
        print(json.dumps(sync_topic(topic), ensure_ascii=False))


if __name__ == "__main__":
    main()
