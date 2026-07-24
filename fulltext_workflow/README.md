# Full-Text Workflow

病理 AI 文献 **全文知识图谱** 与研究空白分析管线。

- PubMed 元数据 → 全文（JATS / PDF+MinerU）→ 分章节 LLM 抽取 → NetworkX 建图  
- 静态 Gap 报告、多智能体辩论、周热点、ops memory 软去重  
- 方信 LIS 数据可行性 + 研究方案（idea-pipeline）  
- Streamlit 七标签页 UI（`gap_ui.py`）

独立数据库：`data/kg_fulltext.db`（不依赖已移除的主程序库）。

## 文档索引

| 文档 | 内容 |
|------|------|
| **[PIPELINE.md](PIPELINE.md)** | 分阶段流水线、生产跑法、weekly / ops memory |
| **[SCRIPTS.md](SCRIPTS.md)** | 常用命令与维护脚本速查 |
| **[gap_ui_guide.md](gap_ui_guide.md)** | Streamlit UI 操作说明 |
| 仓库根目录 [README.md](../README.md) | 环境安装与总入口 |

## 快速开始

在仓库根目录配置环境与 `.env`（见根 README），然后：

```powershell
cd fulltext_workflow
$py = "..\.venv\Scripts\python.exe"

.\run_pipeline.ps1                    # 交互菜单
.\run_pipeline.ps1 -Stage weekly      # 每周增量
.\run_gap_ui.ps1                      # Gap UI → http://localhost:8501
```

试跑建库：

```powershell
& $py main.py run-db --limit 30 --core-only
& $py main.py build
& $py main.py analyze
```

## 检索范围

查询组与默认年份来自仓库根目录 [`search_queries.py`](../search_queries.py)（当前默认 **2015–2025**、**14** 组启用；`pathomics_radiomics` 默认关闭，因可行性侧无影像数据）。可用环境变量覆盖：

```ini
FULLTEXT_SEARCH_YEAR_START=2015
FULLTEXT_SEARCH_YEAR_END=2026
FETCH_EDAT_DAYS=14
```

## 主命令一览

```powershell
& $py main.py init | fetch | enrich-s2 | import-if | fetch-fulltext
& $py main.py extract --limit 0 --core-only
& $py main.py compute-gap-lifecycle
& $py main.py build | viz | analyze | stats
& $py main.py hotspot-report | hotspot-brief
& $py main.py bootstrap-landscape [--force]
& $py main.py gap-debate --focus "…" -o output/gap_debate_report.md
& $py main.py idea-pipeline --focus "digital pathology" --top 3
```

完整参数与周更说明见 [SCRIPTS.md](SCRIPTS.md) / [PIPELINE.md](PIPELINE.md)。

## Gap UI（七标签页）

Debate Process · Weekly Hotspot · Visualization · Evidence & Literature · Gap Report · Data Feasibility · Research Proposal

侧边栏默认开启 **Use ops memory** / **Persist this run**。

## 能力模块

| 模块 | 作用 |
|------|------|
| `fetcher/` | PubMed、全文、引用 enrichment |
| `extractor/` | 分章节 LLM 三元组抽取（粒度政策见 [extractor/GRANULARITY.md](extractor/GRANULARITY.md)） |
| `graph/` + `viz/` | NetworkX / Pyvis |
| `analysis/gap_tools.py` | SQL Gap + impact 加权 |
| `analysis/gap_lifecycle.py` | limitation 时间画像 |
| `analysis/weekly_hotspot.py` | 周发表热点 + WoW |
| `analysis/ops_memory.py` | 周常辩论记忆软去重 |
| `gap_agent.py` | Opportunity Scout × Evidence Reviewer × Final Synthesizer |
| `idea_agent.py` + `pipeline.py` | 可行性门控 + 方案生成 |
| `feasibility/` | 方信 LIS HTTP 客户端 |

## 数据路径

| 路径 | 内容 |
|------|------|
| `data/kg_fulltext.db` | SQLite 主库 |
| `data/jcr.csv` | 期刊 IF（`import-if`） |
| `raw/pmc_xml/` · `raw/pdfs/` · `raw/mineru_output/` | 全文缓存 |
| `output/` | GEXF、HTML、各类报告 |

## 测试

```powershell
& $py tests/test_feasibility.py
& $py -m pytest tests/ -q
```

## 相关仓库根文档

- [`api_document.md`](../api_document.md) — 方信病理 API  
- [`pathology_data_api_spec.md`](../pathology_data_api_spec.md) — 可行性闭环规格  
- [`docs/superpowers/specs/2026-07-15-ops-memory-design.md`](../docs/superpowers/specs/2026-07-15-ops-memory-design.md) — Ops memory 设计  
