# Pathology AI Knowledge Graph

从 PubMed / Semantic Scholar 抓取病理 AI 文献，抽取知识图谱三元组，并通过 LLM Agent 识别研究空白、生成研究提案。

## 功能概览

- **摘要管线**（项目根目录）：`main.py` — 检索、引用 enrichment、LLM 抽取、图谱构建与可视化
- **全文管线**（`fulltext_workflow/`）：PMC / PDF 全文获取、MinerU 解析、分章节抽取、Gap 生命周期分析
- **Agent**：`gap_agent.py` / `idea_agent.py` — 研究空白发现与对抗式提案生成
- **UI**：`gap_ui.py` — Streamlit 交互界面

详细架构见 [ARCHITECTURE.md](ARCHITECTURE.md)；全文流程见 [fulltext_workflow/PIPELINE.md](fulltext_workflow/PIPELINE.md)。

## 快速开始

### 1. 环境

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 API Key（勿提交到 Git）
```

必填项通常包括：`PUBMED_EMAIL`、`OPENAI_API_KEY`（或 `DASHSCOPE_API_KEY`）。可选：`S2_API_KEY`、`PATHOLOGY_API_KEY`（可行性评估）。

### 3. 本地数据文件（不纳入版本库）

以下文件需自行放置：

| 文件 | 用途 |
|------|------|
| `jcr.csv` 或 `fulltext_workflow/data/jcr.csv` | 期刊影响因子，用于引用权重 |
| `data/kg_papers.db` | 摘要管线数据库（运行后自动生成） |
| `fulltext_workflow/data/kg_fulltext.db` | 全文管线数据库（运行后自动生成） |

影响因子表可从科睿唯安 JCR 等来源导出为 CSV，列名需与 `utils/if_importer.py` 一致。

### 4. 运行示例

```bash
# 摘要管线
python main.py fetch
python main.py extract
python main.py build-kg

# 全文管线
cd fulltext_workflow
python main.py fetch --limit 10
python main.py extract --limit 10

# Gap 分析 UI
streamlit run gap_ui.py
```

## 项目结构

```
build_kg_paper/
├── main.py                 # 摘要管线入口
├── config.py               # 全局配置（从 .env 读取）
├── search_queries.py       # PubMed 检索词组
├── fetcher/                # PubMed / S2 抓取
├── extractor/              # LLM 三元组抽取
├── graph/                  # 知识图谱构建
├── gap_agent.py            # 研究空白 Agent
├── fulltext_workflow/      # 全文抽取与 Gap 生命周期
└── data/                   # 本地数据库（gitignore）
```

## 安全说明

- `.env` 已在 `.gitignore` 中排除，仅提交 `.env.example` 模板
- 数据库、PDF、解析结果、Excel 分区表等大文件不会上传
- 若曾误提交密钥，请立即轮换对应 API Key

## License

Private research project — 使用前请确认数据与 API 使用条款。
