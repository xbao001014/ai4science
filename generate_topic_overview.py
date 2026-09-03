#!/usr/bin/env python3
"""Generate an evidence-bounded overview and a per-paper index for a topic method library."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--topic", choices=("segmentation", "virtual-staining"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL"))
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def compact(text: str, limit: int = 1000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def field(text: str, name: str) -> str:
    match = re.search(rf"(?m)^- \*\*{re.escape(name)}\*\*：(.+)$", text)
    return match.group(1).strip() if match else "未说明"


def subsection(text: str, heading: str, next_pattern: str, limit: int) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(heading)}\s*\n(.*?)(?=^{next_pattern}|\Z)", text
    )
    return compact(match.group(1), limit) if match else ""


def relative_link(path: Path, base: Path) -> str:
    rel = path.relative_to(base).as_posix()
    return quote(rel, safe="/._-()")


TOPICS = {
    "segmentation": {
        "label": "病理图像分割",
        "title": "计算病理图像分割方法综述",
        "output": "segmentation_methods_overview.md",
        "taxonomy": """建议分类框架：
1. 早期核/腺体实例分割与边界建模；
2. 多尺度、多分辨率与结构保持；
3. 联合核分割—分类与多任务建模；
4. 弱监督、低标注与挑战基准；
5. 空间注意力、特征金字塔与近期模型。

横向比较至少覆盖：语义分割与实例分割、粘连对象分离、监督粒度、跨组织泛化、细胞类型判别、计算代价、评价指标和外部验证。必须明确 MoNuSeg/CoNIC 一类论文主要贡献是数据集、挑战赛或基准体系，不能把它们写成核心模型创新。""",
    },
    "virtual-staining": {
        "label": "虚拟染色与染色转换",
        "title": "计算病理虚拟染色与染色转换方法综述",
        "output": "virtual_staining_methods_overview.md",
        "taxonomy": """建议分类框架：
1. 无标记相位/光声/自体荧光到 H&E；
2. 染色间双向和多域转换；
3. 无配对、对比学习与结构保持；
4. 虚拟 IHC/多重染色与定量标志物；
5. 全切片、错位鲁棒与可信临床验证。

横向比较至少覆盖：输入成像模态、配对/非配对训练、目标染色、配准依赖、结构保真、幻觉风险、定量标志物保持、病理医师评估、全切片扩展性和外部验证。不得把视觉相似度或像素指标直接等同于诊断有效性。""",
    },
}


def build_index(project_dir: Path, rows: list[dict]) -> Path:
    summary_dir = project_dir / "method_summaries"
    manifest_path = project_dir / "summary_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest_rows = manifest.get("results", manifest.get("papers", [])) if isinstance(manifest, dict) else []
    by_pmid = {str(item.get("pmid")): item for item in manifest_rows if isinstance(item, dict)}
    files = sorted(summary_dir.glob("*.md"))
    file_by_pmid = {}
    for path in files:
        match = re.search(r"_(\d+)_", path.name)
        if match:
            file_by_pmid[match.group(1)] = path

    lines = [
        "# 逐篇方法总结索引",
        "",
        "本目录中的条目均由本地全文/结构化章节生成；具体证据边界见各文档的“证据充分性与待核实项”。",
        "",
        "| PMID | 年份 | 论文 | 纳入角色 | 方法总结 |",
        "|---:|---:|---|---|---|",
    ]
    for row in rows:
        pmid = str(row.get("pmid", ""))
        path = file_by_pmid.get(pmid)
        if not path:
            candidate = by_pmid.get(pmid, {}).get("output_file")
            if candidate:
                path = Path(candidate)
        title = str(row.get("title", "")).replace("|", "\\|")
        role = str(row.get("selection_rationale", row.get("rationale", row.get("role", "方法/基准")))).replace("|", "\\|")
        role = compact(role, 90)
        link = f"[{path.name}]({quote(path.name, safe='._-()')})" if path else "缺失"
        lines.append(f"| {pmid} | {row.get('year', '')} | {title} | {role} | {link} |")
    lines.extend(["", f"共 {len(rows)} 篇。", ""])
    out = summary_dir / "README.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def load_source_records(project_dir: Path, rows: list[dict]) -> tuple[list[dict], list[str]]:
    summary_dir = project_dir / "method_summaries"
    records: list[dict] = []
    links: list[str] = []
    for row in rows:
        pmid = str(row.get("pmid", ""))
        candidates = list(summary_dir.glob(f"*_{pmid}_*.md"))
        if not candidates:
            continue
        path = candidates[0]
        text = path.read_text(encoding="utf-8")
        method_overview = subsection(text, "### 2. 整体方法", r"### 3\.", 1300)
        contributions = subsection(text, "### 3. 主要贡献", r"---|## 三、", 1300)
        evaluation = subsection(text, "#### 9. 实验与消融证据", r"#### 10\.", 1000)
        limitations = subsection(text, "#### 8. 适用场景与可迁移性", r"#### 9\.", 900)
        evidence = next((line[2:].strip() for line in text.splitlines()
                         if line.startswith("> 证据说明")), "")
        records.append({
            "pmid": pmid,
            "year": row.get("year"),
            "title": row.get("title"),
            "selection_rationale": row.get("selection_rationale", row.get("rationale", row.get("method_hint"))),
            "task_and_setting": field(text, "研究任务"),
            "modalities": field(text, "数据模态"),
            "method_overview": method_overview or compact(section(text, "方法总体概述"), 1300),
            "contributions": contributions or compact(section(text, "核心创新点"), 1300),
            "evaluation": evaluation or compact(section(text, "评估设计"), 900),
            "limitations": limitations or compact(section(text, "局限性"), 800),
            "evidence_boundary": compact(evidence or section(text, "证据充分性与待核实项"), 700),
            "file": path.name,
        })
        links.append(f"- PMID {pmid}: [{row.get('title')}]({relative_link(path, project_dir)})")
    return records, links


def call_llm(prompt: str, model: str) -> str:
    sys.path.insert(0, str(Path(__file__).parent / "multimodal-method-summary"))
    import generate_summaries as shared  # type: ignore

    shared.SYSTEM_PROMPT = (
        "你是计算病理方法学综述作者。只能依据输入的结构化逐篇总结写作；"
        "不补造实验数字、数据集、结论或临床证据。用中文 Markdown 输出。"
    )
    if model:
        shared.config.LLM_MODEL_AGENT = model
    return shared.call_llm(prompt)


def validate_overview(text: str, rows: list[dict]) -> None:
    required = [
        "研究范围与证据边界",
        "技术演进与分类框架",
        "逐方法创新点",
        "横向比较与发展趋势",
        "方法选择建议",
        "文档覆盖索引",
    ]
    missing = [heading for heading in required if f"## {heading}" not in text]
    if missing:
        raise RuntimeError(f"overview missing headings: {missing}")
    represented = sum(1 for row in rows if str(row.get("pmid")) in text)
    if represented < len(rows):
        raise RuntimeError(f"overview only mentions {represented}/{len(rows)} PMIDs")


def main() -> int:
    args = parse_args()
    project_dir = args.project_dir.resolve()
    spec = TOPICS[args.topic]
    rows = read_jsonl(project_dir / "selected_papers.jsonl")
    index_path = build_index(project_dir, rows)
    records, links = load_source_records(project_dir, rows)
    if len(records) != len(rows):
        raise RuntimeError(f"found {len(records)} summaries for {len(rows)} selected papers")

    prompt = f"""请为“{spec['label']}”方法库撰写独立总览，标题为“# {spec['title']}”。

必须依次包含以下二级标题：
## 研究范围与证据边界
## 技术演进与分类框架
## 逐方法创新点
## 横向比较与发展趋势
## 方法选择建议
## 文档覆盖索引

写作要求：
- 核心是方法谱系、创新机制与适用场景，不要写成逐篇摘要的简单拼接。
- “逐方法创新点”必须覆盖全部 {len(rows)} 篇，并在每个条目中显式写 PMID。
- 比较论文时不要跨论文做未经支持的性能排名；如果评价设置不同，明确不可直接横比。
- 严格保留来源总结中的证据不确定性，不把作者宣称改写成已确证事实。
- 在最后一节原样使用下方给出的相对链接，每篇一条，不得编造文件名。
- 建议篇幅 8000–13000 个中文字符。

{spec['taxonomy']}

逐篇结构化记录：
{json.dumps(records, ensure_ascii=False, indent=2)}

可用链接：
{chr(10).join(links)}
"""
    overview = call_llm(prompt, args.model).strip() + "\n"
    validate_overview(overview, rows)
    output = (args.output or project_dir / spec["output"]).resolve()
    output.write_text(overview, encoding="utf-8")
    print(json.dumps({"overview": str(output), "index": str(index_path), "papers": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
