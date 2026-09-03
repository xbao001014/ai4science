"""Generate evidence-grounded multimodal method summaries from the local KG database.

The script reads the OpenAI-compatible credentials already configured by the parent
project. It checkpoints each paper independently and never writes API credentials.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "fulltext_workflow"
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))

import config  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = Path(config.DB_PATH)
OUTPUT_DIR = PROJECT_DIR / "method_summaries"
MANIFEST_PATH = PROJECT_DIR / "summary_manifest.json"

PMIDS = [
    "29531073",
    "37592105",
    "31510656",
    "36038778",
    "35676445",
    "39779851",
    "41193692",
    "40442373",
    "35073937",
    "33838393",
    "36991216",
    "40121304",
    "41230238",
    "39572531",
    "38866050",
    "41387679",
    "32729045",
    "39637859",
]

REQUIRED_HEADINGS = [
    "## 一、论文基本信息",
    "## 二、论文整体概述",
    "## 三、方法总结",
    "#### 5. 实现伪代码",
    "## 四、论文级综合评价",
]

SYSTEM_PROMPT = """你是计算病理学、多模态学习和循证文献分析领域的资深研究员。
你的任务是根据给定的本地论文文本生成中文方法总结。

硬性规则：
1. 只使用输入中明确出现的事实；不得用常识补造作者、结构、公式、维度、参数、数据集或实验结果。
2. 无法从输入确认的内容写“未说明”或“本地证据不足”，不要猜测。
3. 区分数据预处理、单模态编码、真正的跨模态融合和最终预测头。
4. 区分作者声称的创新与由基线/消融实际支持的创新。
5. 不把新增模态本身自动判定为算法创新；需说明融合机制相对简单拼接或单模态基线的差异。
6. 不跨论文比较绝对性能，不宣称在不同数据划分下可以直接排名。
7. 保持合法 Markdown。必须完整保留指定模板的全部标题。
8. “实现伪代码”章节只输出一个空的 python 代码块，不能生成任何代码或注释。
9. 关键公式只有在原文可可靠恢复时才写；否则明确写“本地文本不足以可靠恢复公式”。
10. 一篇论文若只有一个命名核心框架，只总结为一个方法，不把普通层拆成独立方法。
"""

USER_TEMPLATE = """请根据下面的论文元数据和本地正文，严格按模板生成完整中文 Markdown。

# {{论文标题}} 方法总结

在一级标题后紧接一行：
> 证据说明：说明全文状态、可用章节规模，以及哪些部分可能因本地证据不完整而留空。

## 一、论文基本信息

- **论文标题**：
- **作者**：
- **发表年份**：
- **会议/期刊**：
- **论文链接/DOI/arXiv ID**：
- **代码仓库**：
- **研究任务**：
- **数据模态**：

## 二、论文整体概述

### 1. 核心问题

### 2. 整体方法

### 3. 主要贡献

1.
2.
3.

---

## 三、方法总结

### 方法 1：[方法或模块名称]

#### 1. 核心思想与解决的问题

- **目标问题**：
- **现有方法的局限**：
- **核心思想**：
- **创新点**：

#### 2. 详细结构与数据流

- **输入**：
- **数据预处理**：
- **单模态编码**：
- **跨模态融合**：
- **处理流程**：
  1.
  2.
  3.
- **输出**：
- **模块在整体网络中的位置**：
- **与其他模块的连接方式**：

#### 3. 数学公式

#### 4. 输入输出维度

| 阶段 | 张量/变量 | 维度 | 说明 |
|---|---|---|---|
| 输入 |  |  |  |
| 中间表示 |  |  |  |
| 输出 |  |  |  |

#### 5. 实现伪代码

```python

```

#### 6. 实现提示

- **关键网络组件**：
- **重要超参数**：
- **归一化/激活方式**：
- **维度对齐方式**：
- **实现注意事项**：
- **依赖的特殊算子或第三方库**：

#### 7. 计算与资源开销

- **理论计算复杂度**：
- **参数量**：
- **FLOPs/MACs**：
- **显存开销**：
- **推理速度**：
- **论文是否提供效率对比**：

#### 8. 适用场景与可迁移性

- **原论文应用场景**：
- **可迁移到的任务/数据集**：
- **迁移所需调整**：
- **适用条件**：
- **潜在限制**：

#### 9. 实验与消融证据

- **主要性能结果**：
- **相对基线的提升**：
- **相关消融实验**：
- **作者结论**：
- **证据是否充分**：

#### 10. 方法评估

| 维度 | 评价 | 依据 |
|---|---|---|
| 创新性 | 高 / 中 / 低 |  |
| 技术可行性 | 高 / 中 / 低 |  |
| 实现难度 | 高 / 中 / 低 |  |
| 架构相关性 | 高 / 中 / 低 |  |
| 可迁移性 | 高 / 中 / 低 |  |
| 计算成本 | 高 / 中 / 低 |  |

#### 11. 一句话总结

## 四、论文级综合评价

### 1. 最值得借鉴的方法

### 2. 方法之间的关系

### 3. 复现可行性

- **代码是否公开**：
- **方法描述是否完整**：
- **关键配置是否明确**：
- **预计复现难点**：

### 4. 与当前研究方向的关系

- **可直接采用的设计**：
- **需要改造的设计**：
- **可能形成的新研究思路**：

### 5. 阅读备注

论文元数据：
<metadata>
{metadata}
</metadata>

本地论文文本：
<paper_text>
{paper_text}
</paper_text>
"""


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def paper_record(pmid: str) -> dict:
    with db_conn() as conn:
        paper = conn.execute("SELECT * FROM papers WHERE pmid=?", (pmid,)).fetchone()
        if paper is None:
            raise KeyError(f"PMID not found: {pmid}")
        authors = conn.execute(
            """SELECT a.name FROM paper_authors pa
               JOIN authors a ON a.id=pa.author_id
               WHERE pa.paper_id=? ORDER BY pa.author_order""",
            (paper["id"],),
        ).fetchall()
        sections = conn.execute(
            """SELECT section_type, title, content, order_idx
               FROM document_sections WHERE paper_id=? ORDER BY order_idx""",
            (paper["id"],),
        ).fetchall()
    record = dict(paper)
    record["authors"] = [row["name"] for row in authors]
    record["sections"] = [dict(row) for row in sections]
    return record


def build_paper_text(record: dict, max_chars: int = 72000) -> str:
    abstract = " ".join((record.get("abstract") or "").split())
    chunks = [f"[Abstract]\n{abstract}"] if abstract else []
    sections = record.get("sections") or []
    scored: list[tuple[int, int, dict]] = []
    priority_words = (
        "method", "architecture", "model", "training", "fusion", "attention",
        "experiment", "result", "ablation", "comparison", "limitation",
        "discussion", "data", "dataset", "implementation", "pretrain",
    )
    for index, section in enumerate(sections):
        title = (section.get("title") or "").lower()
        section_type = (section.get("section_type") or "").lower()
        score = sum(3 for word in priority_words if word in title)
        if section_type in {"methods", "results", "limitations", "discussion"}:
            score += 5
        scored.append((-score, index, section))
    used = sum(len(chunk) for chunk in chunks)
    chosen: list[tuple[int, str]] = []
    for _, index, section in sorted(scored):
        content = (section.get("content") or "").strip()
        if not content:
            continue
        title = section.get("title") or section.get("section_type") or f"Section {index}"
        chunk = f"[{section.get('section_type')}: {title}]\n{content}"
        remaining = max_chars - used
        if remaining <= 500:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining] + "\n[本节因输入长度限制而截断]"
        chosen.append((index, chunk))
        used += len(chunk)
    chunks.extend(chunk for _, chunk in sorted(chosen))
    return "\n\n".join(chunks)


def output_path(record: dict) -> Path:
    title = re.sub(r'[<>:"/\\|?*]', "_", record["title"])
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")[:120]
    return OUTPUT_DIR / f"PMID_{record['pmid']}_{title}.md"


def complete(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 2500:
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return all(heading in text for heading in REQUIRED_HEADINGS)


def empty_pseudocode(text: str) -> str:
    pattern = r"(#### 5\. 实现伪代码\s*\n).*?(?=\n#### 6\. 实现提示)"
    replacement = r"\1\n```python\n\n```\n"
    return re.sub(pattern, replacement, text, flags=re.DOTALL)


def normalize_header_order(text: str) -> str:
    """Put the H1 before an LLM-emitted leading evidence note."""
    stripped = text.lstrip()
    if not stripped.startswith("> 证据说明"):
        return text
    lines = stripped.splitlines()
    try:
        h1_index = next(i for i, line in enumerate(lines) if line.startswith("# "))
    except StopIteration:
        return text
    leading = lines[:h1_index]
    rest = lines[h1_index + 1 :]
    return "\n".join([lines[h1_index], "", *leading, *rest]).strip() + "\n"


def call_llm(prompt: str, retries: int = 5) -> str:
    client = OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
        timeout=max(config.LLM_REQUEST_TIMEOUT, 600),
        max_retries=0,
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=config.LLM_MODEL_AGENT,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=min(config.LLM_MAX_TOKENS, 20000),
            )
            content = (response.choices[0].message.content or "").strip()
            content = re.sub(r"^```(?:markdown)?\s*", "", content, flags=re.I)
            content = re.sub(r"\s*```$", "", content)
            if len(content) < 2500:
                raise RuntimeError(f"LLM response too short: {len(content)} chars")
            return normalize_header_order(empty_pseudocode(content) + "\n")
        except Exception as exc:  # provider-specific errors vary
            last_error = exc
            if attempt < retries - 1:
                time.sleep(min(45, 3 * (2**attempt)))
    raise RuntimeError(f"LLM failed after {retries} attempts: {last_error}")


def generate_one(pmid: str, force: bool = False) -> dict:
    record = paper_record(pmid)
    target = output_path(record)
    if not force and complete(target):
        return {"pmid": pmid, "status": "skipped", "file": target.name}
    metadata = {
        "pmid": record.get("pmid"),
        "doi": record.get("doi"),
        "title": record.get("title"),
        "authors": record.get("authors"),
        "year": record.get("year"),
        "journal": record.get("journal_name"),
        "full_text_status": record.get("full_text_status"),
        "section_count": len(record.get("sections") or []),
        "section_chars": sum(len(s.get("content") or "") for s in record.get("sections") or []),
    }
    prompt = USER_TEMPLATE.format(
        metadata=json.dumps(metadata, ensure_ascii=False, indent=2),
        paper_text=build_paper_text(record),
    )
    content = call_llm(prompt)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in content]
    if missing:
        raise RuntimeError(f"PMID {pmid} missing headings: {missing}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "pmid": pmid,
        "status": "generated",
        "file": target.name,
        "chars": len(content),
        "source_sections": metadata["section_count"],
        "source_chars": metadata["section_chars"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pmid", action="append", help="Generate only selected PMID(s)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    pmids = args.pmid or PMIDS
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(generate_one, pmid, args.force): pmid for pmid in pmids}
        for future in as_completed(futures):
            pmid = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"pmid": pmid, "status": "failed", "error": str(exc)}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    order = {pmid: index for index, pmid in enumerate(pmids)}
    results.sort(key=lambda row: order.get(row["pmid"], 9999))
    existing_results: list[dict] = []
    if MANIFEST_PATH.exists():
        try:
            existing_results = json.loads(
                MANIFEST_PATH.read_text(encoding="utf-8")
            ).get("results", [])
        except (json.JSONDecodeError, AttributeError):
            existing_results = []
    by_pmid = {row["pmid"]: row for row in existing_results}
    for row in results:
        by_pmid[row["pmid"]] = row
    merged_results = sorted(by_pmid.values(), key=lambda row: row["pmid"])
    MANIFEST_PATH.write_text(
        json.dumps(
            {"model": config.LLM_MODEL_AGENT, "results": merged_results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    failed = [row for row in results if row["status"] == "failed"]
    print(f"completed={len(results) - len(failed)} failed={len(failed)}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
