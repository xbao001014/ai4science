# Pathology AI Knowledge Graph

从 PubMed 抓取病理 / 数字病理 AI 文献，构建**全文知识图谱**，并用 LLM Agent 做研究空白分析、周热点追踪与研究方案生成。

本仓库的主代码在 **`fulltext_workflow/`**。根目录保留共享配置与文档入口。

---

## 快速开始

### 1. 环境

```powershell
# 在目标服务器上的仓库根目录执行
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 单测 / PPTX 导出（可选）
pip install -r requirements-dev.txt
```

建议 Python **3.10–3.12**。`mineru` / `scansci-pdf` 已含在主依赖中（体积较大）。

Linux 服务器用 `python3 -m venv .venv`、`source .venv/bin/activate`；其余 Python CLI 命令在 `fulltext_workflow/` 下执行。跨服务器迁移及验收见 [部署指南](DEPLOYMENT.md)。

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
├── requirements.txt          # 核心 + Gap UI + ScanSci/MinerU
├── requirements-dev.txt      # 可选：pytest / python-pptx
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
| [DEPLOYMENT.md](DEPLOYMENT.md) | 跨服务器部署、数据迁移与验证 |
| [Docker 部署](DEPLOYMENT.md#6-docker-compose-部署) | 容器构建、持久目录与启动命令 |

---

## 能力概览

1. **建库**：PubMed / Europe PMC / arXiv → 引用/IF → 全文（冷却重试）→ LLM 抽取（摘要→全文可自动重抽）→ KG
2. **周更**：EDAT 增量 + 周热点报告 / LLM 简报（CLI 或 Gap UI「运维」后台）  
3. **Gap**：静态 SQL 报告 · 三角色辩论 · ops memory 软去重  
4. **可行性**：方信病理 LIS landscape（API 实测池，无估计 floor）+ idea-pipeline  
5. **运维 UI**：一键 weekly + 清空 ops memory  

---

## 安全说明

- `.env` 已在 `.gitignore` 中排除；仅提交 `.env.example`
- 数据库、PDF、MinerU 缓存、大 CSV 等不入库
- 若曾误提交密钥，请立即轮换

## License

Private research project — 使用前请确认数据与 API 使用条款。
