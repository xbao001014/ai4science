"""Synthesize per-paper multimodal summaries into a linked method overview."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "fulltext_workflow"
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))

import config  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
SUMMARY_DIR = PROJECT_DIR / "method_summaries"
OUTPUT = PROJECT_DIR / "multimodal_methods_overview.md"


def field(text: str, name: str) -> str:
    match = re.search(rf"(?m)^- \*\*{re.escape(name)}\*\*：(.+)$", text)
    return match.group(1).strip() if match else "未说明"


def section(text: str, heading: str, next_pattern: str, limit: int = 3000) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(heading)}\s*\n(.*?)(?=^{next_pattern}|\Z)", text
    )
    if not match:
        return ""
    value = "\n".join(line.rstrip() for line in match.group(1).strip().splitlines())
    return value[:limit]


def compact_record(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    h1 = next((line[2:].removesuffix(" 方法总结").strip() for line in text.splitlines()
               if line.startswith("# ")), path.stem)
    methods = re.findall(r"(?m)^### 方法 \d+：(.+)$", text)
    return {
        "pmid": path.name.split("_", 2)[1],
        "file": path.name,
        "link": f"method_summaries/{quote(path.name)}",
        "title": field(text, "论文标题") if field(text, "论文标题") != "未说明" else h1,
        "year": field(text, "发表年份"),
        "venue": field(text, "会议/期刊"),
        "task": field(text, "研究任务"),
        "modalities": field(text, "数据模态"),
        "methods": methods,
        "overall_method": section(text, "### 2. 整体方法", r"### 3\.", 1800),
        "contributions": section(text, "### 3. 主要贡献", r"---|## 三、", 2200),
        "evaluation": section(text, "#### 9. 实验与消融证据", r"#### 10\.", 2200),
        "paper_assessment": section(text, "## 四、论文级综合评价", r"## ", 2200),
    }


def call_llm(prompt: str) -> str:
    client = OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
        timeout=max(config.LLM_REQUEST_TIMEOUT, 900),
        max_retries=2,
    )
    response = client.chat.completions.create(
        model=config.LLM_MODEL_AGENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是计算病理学、多模态学习和循证文献综述领域的资深研究员。"
                    "只使用输入的本地逐篇总结事实，明确区分论文事实与跨论文综合判断；"
                    "不得虚构方法、实验结果、公式、代码或引用。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=min(config.LLM_MAX_TOKENS, 20000),
    )
    content = (response.choices[0].message.content or "").strip()
    content = re.sub(r"^```(?:markdown)?\s*", "", content, flags=re.I)
    content = re.sub(r"\s*```$", "", content)
    return content + "\n"


def main() -> None:
    paths = sorted(SUMMARY_DIR.glob("PMID_*.md"), key=lambda p: p.name.casefold())
    records = [compact_record(path) for path in paths]
    prompt = f"""请基于下面 {len(records)} 篇计算病理学多模态论文的逐篇总结记录，撰写中文 Markdown 总综述。

总体风格参照一个成熟的方法库 overview：以方法谱系为主线，不按论文逐篇堆砌；同时确保每篇论文均有入口。

输出要求：
1. 标题固定为“# 计算病理学多模态融合方法综述”。
2. 依次包含以下一级章节：
   - 研究范围与证据边界
   - 技术演进与分类框架
   - 逐方法创新点
   - 横向比较与发展趋势
   - 方法选择建议
   - 文档覆盖索引
3. “逐方法创新点”为主体，按下面五条技术路线组织二级小节：
   1) 早期图像—组学与临床特征融合；
   2) 交互式图像—组学融合与生存建模；
   3) 病理—放射—临床跨尺度融合；
   4) 病理视觉语言预训练、报告建模与多模态助手；
   5) 空间组学、整张切片与新一代多模态基础模型。
   如一篇论文跨路线，放入最能体现核心创新的一组，不要重复成两个独立方法。
4. 每项使用方法名或清晰的论文简称作为粗体名称，用 1-3 段说明：输入模态、融合位置/机制、真正创新、实验支持及关键限制。避免只复述任务。
5. 每个方法项必须附精确本地链接 `[详细解读](link)`；不得改写输入 link。
6. 明确区分：
   - 核心融合算法；
   - 多模态预训练/对齐模型；
   - 临床验证型晚期融合；
   - 通用模型使用或评测范式（如 GPT-4V in-context learning）。
7. 不把“多一个模态”自动认定为算法创新；优先评价是否有跨模态交互、对齐、动态权重、缺失模态处理或强临床验证。
8. 不进行跨论文数值排名。说明数据集、编码器、划分和指标不一致；实验数字只在输入明确且对论点必要时使用。
9. 在“横向比较与发展趋势”中至少比较：融合阶段、配对要求、缺失模态鲁棒性、可解释性、可迁移性、计算/数据成本、临床证据等级。
10. 在“方法选择建议”中分别给出面向以下目标的选择建议：病理＋组学预后、病理＋临床、病理＋放射、图文零/少样本、报告/问答、空间组学、缺失模态。
11. 文末“文档覆盖索引”逐项列出所有输入 link，确保每个 link 至少出现一次。
12. 不生成参考文献中不存在的新论文，不使用整篇代码围栏，不描述生成过程。

逐篇压缩记录：
{json.dumps(records, ensure_ascii=False, indent=2)}
"""
    content = call_llm(prompt)
    required = [
        "# 计算病理学多模态融合方法综述",
        "## 研究范围与证据边界",
        "## 技术演进与分类框架",
        "## 逐方法创新点",
        "## 横向比较与发展趋势",
        "## 方法选择建议",
        "## 文档覆盖索引",
    ]
    missing_headings = [heading for heading in required if heading not in content]
    if missing_headings:
        raise RuntimeError(f"missing headings: {missing_headings}")
    missing_links = [record["link"] for record in records if record["link"] not in content]
    if missing_links:
        by_link = {record["link"]: record for record in records}
        appendix = ["", "### 自动补全入口", ""]
        for link in missing_links:
            record = by_link[link]
            appendix.append(f'- PMID {record["pmid"]}：[{record["title"]}]({link})')
        content = content.rstrip() + "\n" + "\n".join(appendix) + "\n"
    OUTPUT.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": OUTPUT.name,
                "records": len(records),
                "chars": len(content),
                "missing_links_appended": len(missing_links),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
