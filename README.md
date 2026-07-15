# Pathology AI Knowledge Graph

从 PubMed 抓取病理 AI 文献全文，抽取知识图谱三元组，并通过 LLM Agent 识别研究空白、生成研究提案。

本仓库仅使用 **全文管线**（`fulltext_workflow/`）：PMC / PDF 全文获取、MinerU 解析、分章节抽取、Gap 生命周期分析与 Streamlit UI。

详细流程见 [fulltext_workflow/PIPELINE.md](fulltext_workflow/PIPELINE.md)。

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

全文抓取额外依赖（PDF / MinerU 回退）：

```bash
pip install scansci-pdf "mineru[core]"
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 API Key（勿提交到 Git）
```

必填项通常包括：`PUBMED_EMAIL`、`OPENAI_API_KEY`（或 `DASHSCOPE_API_KEY`）。可选：`S2_API_KEY`、`PATHOLOGY_API_KEY`（可行性评估）。

检索词组与年份范围由根目录 [`search_queries.py`](search_queries.py) 提供；LLM 辅助函数见 [`llm_utils.py`](llm_utils.py)。

### 3. 本地数据文件（不纳入版本库）

| 文件 | 用途 |
|------|------|
| `fulltext_workflow/data/jcr.csv` | 期刊影响因子，用于引用权重 |
| `fulltext_workflow/data/kg_fulltext.db` | 全文管线数据库（运行后自动生成） |

### 4. 运行示例

```bash
cd fulltext_workflow

# 或使用交互菜单
.\run_pipeline.ps1

python main.py fetch --limit 10
python main.py extract --limit 10

# Gap 分析 UI
.\run_gap_ui.ps1
# 或: streamlit run gap_ui.py
```

## 项目结构

```
build_kg_paper/
├── search_queries.py       # PubMed 检索词组（workflow 复用）
├── llm_utils.py            # LLM 调用辅助
├── requirements.txt
├── api_document.md         # 方信病理 LIS API
├── pathology_data_api_spec.md
└── fulltext_workflow/      # 全文抽取与 Gap 生命周期
```

## 安全说明

- `.env` 已在 `.gitignore` 中排除，仅提交 `.env.example` 模板
- 数据库、PDF、解析结果、Excel 分区表等大文件不会上传
- 若曾误提交密钥，请立即轮换对应 API Key

## License

Private research project — 使用前请确认数据与 API 使用条款。
