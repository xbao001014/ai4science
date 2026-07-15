# Pathology AI Knowledge Graph

从 PubMed 抓取病理 / 数字病理 AI 文献，构建**全文知识图谱**，并用 LLM Agent 做研究空白分析、周热点追踪与研究方案生成。

本仓库的主代码在 **`fulltext_workflow/`**。根目录保留共享配置与文档入口。

---

## 快速开始

### 1. 环境

```powershell
cd D:\agent\prototype\build_kg_paper
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 全文 PDF / MinerU 回退（可选）
pip install scansci-pdf "mineru[core]"
```

### 2. 配置

```powershell
cp .env.example .env
# 编辑 .env：PUBMED_EMAIL、DASHSCOPE_API_KEY（或 OPENAI_API_KEY）等
```

检索词组：[`search_queries.py`](search_queries.py)。  
LLM 辅助：[`llm_utils.py`](llm_utils.py)（部分工具复用）。

### 3. 跑流水线

```powershell
cd fulltext_workflow

.\run_pipeline.ps1                 # 交互菜单
.\run_pipeline.ps1 -Stage weekly   # 每周增量
.\run_gap_ui.ps1                   # Gap 分析 UI → http://localhost:8501
```

---

## 仓库结构

```
build_kg_paper/
├── README.md                 ← 本文件（最外层入口）
├── .env.example
├── requirements.txt
├── search_queries.py         # PubMed 检索组与年份
├── llm_utils.py
├── api_document.md           # 方信 LIS API
├── pathology_data_api_spec.md
├── docs/                     # 设计稿 / specs
└── fulltext_workflow/        # ★ 主工作区
    ├── README.md             # 管线说明
    ├── PIPELINE.md           # 分步流水线
    ├── SCRIPTS.md            # 常用命令速查
    ├── main.py               # CLI
    ├── run_pipeline.ps1
    ├── run_gap_ui.ps1
    ├── gap_ui.py
    └── data/kg_fulltext.db   # 运行后生成（不入库）
```

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [fulltext_workflow/README.md](fulltext_workflow/README.md) | 管线概述与模块 |
| [fulltext_workflow/PIPELINE.md](fulltext_workflow/PIPELINE.md) | 完整阶段说明与生产跑法 |
| [fulltext_workflow/SCRIPTS.md](fulltext_workflow/SCRIPTS.md) | 脚本与命令速查 |
| [fulltext_workflow/gap_ui_guide.md](fulltext_workflow/gap_ui_guide.md) | Streamlit UI |

---

## 能力概览

1. **建库**：PubMed → 引用/IF → 全文 → LLM 抽取 → KG  
2. **周更**：EDAT 增量 + 周热点报告 / LLM 简报  
3. **Gap**：静态 SQL 报告 · 三角色辩论 · ops memory 软去重  
4. **可行性**：方信病理 LIS landscape + idea-pipeline  

---

## 安全说明

- `.env` 已在 `.gitignore` 中排除；仅提交 `.env.example`
- 数据库、PDF、MinerU 缓存、大 CSV 等不入库
- 若曾误提交密钥，请立即轮换

## License

Private research project — 使用前请确认数据与 API 使用条款。
