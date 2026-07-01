# Full-Text Workflow 完整流水线指南

> 工作目录：`fulltext_workflow/`  
> 数据库：`data/kg_fulltext.db`（独立于主程序 `data/kg_papers.db`）

也可使用配套脚本：`.\run_pipeline.ps1`（交互菜单或 `-Stage` 参数）。

---

## 0. 环境准备

```powershell
# 仓库根目录
cd D:\agent\prototype\build_kg_paper
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 全文抓取额外依赖（PDF/MinerU 回退）
.\.venv\Scripts\pip install scansci-pdf "mineru[core]"
```

`.env`（仓库根目录）最少需要：

```ini
PUBMED_EMAIL=your@email.com
PUBMED_API_KEY=your-ncbi-key          # 推荐

DASHSCOPE_API_KEY=sk-xxx              # 或 OPENAI_API_KEY
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=deepseek-v4-flash

# 可选：引用 enrichment 提供商（S2 403 时用 openalex）
CITATION_PROVIDER=auto

# 可选：IF 导入年份标签（默认 2024，对应 data/jcr.csv 的 2024JIF 列）
JCR_IF_YEAR=2024

# 可选：方信病理 API（idea-pipeline / gap_ui 数据可行性）
PATHOLOGY_API_BASE_URL=http://ai.gzfxyl.cn/api/v1/pathology
PATHOLOGY_API_KEY=your-key
```

进入工作目录：

```powershell
cd fulltext_workflow
$py = "..\.venv\Scripts\python.exe"
```

---

## 1. 流水线总览

```mermaid
flowchart TD
    A[init] --> B[fetch]
    B --> C{可选}
    C --> D[enrich-s2]
    C --> E[import-if]
    B --> F[fetch-fulltext]
    D --> F
    E --> F
    F --> G[extract]
    G --> H[build]
    H --> I[analyze]
    I --> J{进阶}
    J --> K[gap-debate]
    J --> L[bootstrap-landscape]
    L --> M[idea-pipeline]
    K --> M
    J --> N[gap_ui Streamlit]
```

| 阶段 | 命令 | 是否必需 | 说明 |
|------|------|----------|------|
| 初始化 | `init` | 首次 | 创建/迁移 SQLite 表结构 |
| 元数据 | `fetch` | 必需 | PubMed 14 组查询，写入 papers |
| 引用/IF | `enrich-s2` / `import-if` | 可选 | Gap 影响力加权；纯 KG 可跳过 |
| 全文 | `fetch-fulltext` | 推荐 | JATS → PDF/MinerU → unavailable |
| 抽取 | `extract` | 必需 | LLM 按章节抽三元组 |
| 建图 | `build` | 必需 | NetworkX → GEXF + HTML |
| 分析 | `analyze` | 推荐 | 静态 SQL Gap 报告 |
| 辩论/方案 | `gap-debate` / `idea-pipeline` | 可选 | 需 LLM + 可选 LIS API |
| UI | `streamlit run gap_ui.py` | 可选 | 交互式五标签页 |

---

## 2. 分步命令（推荐顺序）

### Phase 1 — 数据入库

```powershell
# 1.1 初始化数据库
& $py main.py init

# 1.2 拉取 PubMed 元数据（支持断点续传，默认跳过已有 PMID）
& $py main.py fetch

# 1.2b 每周增量：只搜 PubMed 最近入库（EDAT）的文献
& $py main.py fetch --since-days 14
# 或在 .env 设 FETCH_EDAT_DAYS=14 后直接 python main.py fetch

# 1.3 【另一终端】实时查看 fetch 进度（tqdm 在 Cursor 终端可能不刷新）
& $py main.py watch-fetch
& $py main.py watch-fetch --once          # 只看一次
& $py main.py watch-fetch -i 5            # 每 5 秒刷新

# 1.4 查看库统计
& $py main.py stats
```

**模块**：`fetcher/pubmed_fetcher.py`  
**作用**：按 `search_queries.py` 14 组检索式拉取标题、摘要、MeSH、期刊、作者等，写入 `papers` / `journals` / `authors`。

---

### Phase 2 — 元数据增强（可选，Gap 分析前建议跑）

```powershell
# 2.1 引用数 enrichment（默认 OpenAlex；有 S2 key 可设 CITATION_PROVIDER=semantic_scholar）
& $py main.py enrich-s2

# 2.2 期刊影响因子（默认读取 data/jcr.csv，无需传路径）
& $py main.py import-if
& $py main.py import-if --if-year 2024   # 覆盖默认年份标签

# 自定义 IF 文件（可选）
& $py main.py import-if path/to/other.csv --if-year 2025
```

**数据文件**：`data/jcr.csv`（JCR 2024，列：期刊名称 / 2024JIF / Quartile / ISSN / eISSN）。路径与默认年份在 `config.py` 的 `JCR_IF_PATH`、`JCR_IF_YEAR` 中配置。

**模块**：`fetcher/citation_fetcher.py`、`utils/if_importer.py`  
**作用**：填充 `papers.citation_count`、`open_access`；期刊 `impact_factor` / `quartile`。供 `gap_tools` 的 `impact_score`、`cross_priority_score` 使用。

**验证**（`stats` 输出）：

| 字段 | 含义 |
|------|------|
| `s2_enriched` / `citations_openalex` | 已 enrichment 引用数的论文数 |
| `journals_with_if` | 已导入 IF 的期刊数 |

若 `journals_with_if = 0`，Gap 工具的 `avg_if`、`impact_score` 仅反映引用量（约 60% 权重），需先跑 `import-if`。

---

### Phase 3 — 全文获取

```powershell
& $py main.py fetch-fulltext
```

**模块**：`fetcher/fulltext_fetcher.py`  
**作用**：三级策略：

1. Europe PMC JATS XML → `raw/pmc_xml/` + `document_sections`
2. ScanSci PDF + MinerU → `raw/pdfs/`、`raw/mineru_output/`
3. 均失败则标记 `full_text_status=unavailable`，后续 extract 退回摘要

---

### Phase 4 — LLM 知识抽取

```powershell
# 小规模试跑（默认 limit=30）
& $py main.py extract --limit 20

# 全量待处理论文
& $py main.py extract --limit 0

# 仅核心章节（methods/results/discussion/limitations/future_work，更快）
& $py main.py extract --limit 0 --core-only

# 含 introduction/other（更慢更全）
& $py main.py extract --limit 0 --all-sections

# 并行（注意 LLM 限流，默认 workers=1）
& $py main.py extract --limit 0 --section-workers 2 --paper-workers 1
```

**模块**：`extractor/section_extractor.py`、`extractor/llm_client.py`  
**作用**：按章节调用 LLM，抽取实体（Disease/Method/Task 等）和关系，写入 `entities` / `relations`，标记 `extraction_done=1`。

**辅助脚本**（抽取失败/空结果重跑）：

```powershell
& $py scripts/reset_empty_extraction.py             # 重置 extraction_done=1 但无 relations 的论文
& $py scripts/reset_empty_extraction.py --dry-run   # 仅预览
& $py scripts/fix_pmc_mismatch.py --dry-run         # 扫描 PMC 缓存 PMID/DOI 错配
& $py scripts/fix_pmc_mismatch.py                   # 清除错配全文，改回 abstract-only
```

---

### Phase 5 — 知识图谱构建与可视化

```powershell
# 建图 + 导出 GEXF/CSV + 生成 HTML
& $py main.py build

# 仅重新生成 HTML（DB 已有数据时）
& $py main.py viz
```

**模块**：`graph/kg_builder.py`、`viz/visualize.py`  
**作用**：SQLite → NetworkX 图；输出：

- `output/kg_fulltext.gexf`
- `output/kg_fulltext_interactive.html`（论文-实体关系）
- `output/kg_entities.html`（实体共现投影）
- `output/papers_by_journal.csv` 等统计

---

### Phase 5.5 — Limitation 时间画像（Gap 分析前推荐）

```powershell
# 计算 limitation 时间画像 + 启发式填补信号，写入派生表
& $py main.py compute-gap-lifecycle
# 可选：保留已有 limitation_temporal 行，仅重建 resolution_signals
& $py main.py compute-gap-lifecycle --no-force
```

**模块**：`analysis/gap_lifecycle.py`、`db/schema.py`（`limitation_temporal`、`limitation_resolution_signals`）  
**作用**：

- 按 `papers.year` 聚合每条 limitation 的 first/last year、recent_ratio、temporal_status
- 启发式检测后期 disease/task/method 跟进论文（resolution_signal: none/weak/moderate）
- 供 `limitation_temporal_profile`、`limitation_gap_status`、`combo_gap_temporal` 工具与 Gap Debate 使用

**流水线位置**：`extract` 之后、`analyze` / `gap-debate` 之前。

---

### Phase 6 — Gap 分析

```powershell
# 静态 SQL 报告（无 LLM）
& $py main.py analyze
# 输出：output/gap_report.md

# LLM 多智能体辩论报告
& $py main.py gap-debate --focus "digital pathology" --top 6 -o output/gap_debate_report.md
```

**模块**：`analysis/gap_tools.py`、`analysis/graph_tools.py`、`gap_agent.py`  
**作用**：

- `gap_tools`：文献空白矩阵、局限性排名、**时间画像/填补信号**、热点实体、高引论文等
- `graph_tools`：实体共现 PageRank、社区检测、疾病-方法可达性（无引文边 PageRank）
- `gap_agent`：Optimist × Skeptic × Moderator 辩论生成 Gap Report

---

### Phase 7 — 数据可行性 + 研究假说（进阶）

```powershell
# 7.1 从方信 API 加载病理数据景观到 SQLite
& $py main.py bootstrap-landscape
& $py main.py bootstrap-landscape --force    # 强制重载

# 7.2 端到端：Gap 辩论 → 可行性核验 → 假说生成
& $py main.py idea-pipeline --focus radiomics --top 3 -o output/idea_pipeline_report.md

# 仅可行性（跳过辩论和假说 LLM）
& $py main.py idea-pipeline --skip-debate --gap-report output/gap_debate_report.md --skip-ideas
```

**模块**：`pipeline.py`、`feasibility/`、`idea_agent.py`、`evolution_agent.py`  
**作用**：结合 LIS 队列数据评估研究空白的数据可行性，Generator × Critic 迭代产出研究方案。

---

### Phase 8 — 交互式 UI

```powershell
.\run_gap_ui.ps1
# 或
..\.venv\Scripts\streamlit.exe run gap_ui.py
```

浏览器打开 `http://localhost:8501`。详见 `gap_ui_guide.md`。

---

## 3. 一键流水线

```powershell
# 内置：fetch → fetch-fulltext → extract → build → analyze → stats
# 不含 enrich-s2 / import-if / bootstrap-landscape
& $py main.py run-all --limit 30

# 从头拉取（不跳过已有 PMID）
& $py main.py run-all --limit 30 --no-resume
```

---

## 4. 模块对照表

| 目录/文件 | 作用 |
|-----------|------|
| `config.py` | 路径、API Key、LLM/MinerU/引用提供商、`JCR_IF_PATH` 配置 |
| `db/schema.py` | SQLite 表定义、upsert、统计 |
| `fetcher/pubmed_fetcher.py` | PubMed Entrez 元数据抓取 |
| `fetcher/fulltext_fetcher.py` | JATS / PDF / MinerU 全文 |
| `fetcher/citation_fetcher.py` | OpenAlex/S2 引用数 enrichment |
| `extractor/section_extractor.py` | 按章节 LLM 抽取 |
| `extractor/llm_client.py` | 百炼/DeepSeek API 调用与限流 |
| `graph/kg_builder.py` | 构建 NetworkX 知识图谱 |
| `viz/visualize.py` | Pyvis HTML 可视化 |
| `analysis/gap_tools.py` | SQL Gap 工具 + impact 加权 |
| `analysis/impact_scoring.py` | citation/IF → impact_score |
| `analysis/feasibility_tools.py` | 病理数据可行性 LLM 工具 |
| `analysis/graph_tools.py` | 实体图分析（PageRank/社区/可达性） |
| `gap_agent.py` | Gap 辩论多智能体 |
| `idea_agent.py` | 研究方案 Generator × Critic |
| `pipeline.py` | idea-pipeline 编排 |
| `feasibility/` | 方信病理 LIS HTTP 客户端 |
| `gap_ui.py` | Streamlit 五标签页 UI |
| `utils/fetch_progress.py` | watch-fetch 进度轮询 |
| `utils/if_importer.py` | 期刊 IF 导入 |
| `scripts/reset_empty_extraction.py` | 重置空抽取结果 |

---

## 5. 关键数据路径

| 路径 | 内容 |
|------|------|
| `data/kg_fulltext.db` | 主数据库 |
| `data/jcr.csv` | 默认 JCR 影响因子表（`import-if` 读取） |
| `raw/pmc_xml/` | PMC JATS 缓存 |
| `raw/pdfs/` | ScanSci 下载的 PDF |
| `raw/mineru_output/` | MinerU 解析结果 |
| `output/kg_fulltext.gexf` | 图导出 |
| `output/kg_fulltext_interactive.html` | 交互式 KG |
| `output/gap_report.md` | 静态 Gap 报告 |
| `output/gap_debate_report.md` | 辩论 Gap 报告 |
| `output/idea_pipeline_report.md` | 假说流水线报告 |

---

## 6. 推荐生产跑法（全量）

```powershell
cd fulltext_workflow
$py = "..\.venv\Scripts\python.exe"

& $py main.py init
& $py main.py fetch                              # 耗时长，另开终端 watch-fetch
& $py main.py enrich-s2                          # 可选但 Gap 推荐
& $py main.py import-if                          # 可选，默认 data/jcr.csv
& $py main.py fetch-fulltext                     # 耗时长
& $py main.py extract --limit 0 --core-only      # 全量，核心章节
& $py main.py compute-gap-lifecycle              # limitation 时间画像 + 填补信号
& $py main.py build
& $py main.py analyze
& $py main.py bootstrap-landscape --force        # 若用 idea-pipeline / gap_ui 可行性
& $py main.py gap-debate -o output/gap_debate_report.md
& $py main.py stats
```

---

## 7. 每周增量更新

首跑完成后，建议每周执行一次以追踪新文献。核心机制：

- `fetch` 默认 **resume**：已入库 PMID 自动跳过
- `--since-days N`：附加 `("last N days"[EDAT])`，只检索 PubMed **最近入库**记录
- `fetch-fulltext` / `extract` 天然只处理新增待处理论文

`.env` 可选默认值：

```ini
FULLTEXT_SEARCH_YEAR_END=2026          # 每年 1 月更新
FETCH_EDAT_DAYS=14                     # 设后 fetch 默认带 EDAT 窗口；0=关闭
```

每周一条命令：

```powershell
.\run_pipeline.ps1 -Stage weekly
# 或分步：
& $py main.py fetch --since-days 14
& $py main.py enrich-s2
& $py main.py fetch-fulltext
& $py main.py extract --limit 0 --core-only
& $py main.py compute-gap-lifecycle
& $py main.py build
& $py main.py analyze
```

**不要**每周使用 `--no-resume` 或对勘误文跑 `reset_empty_extraction`。

---

## 8. run_pipeline.ps1 用法

```powershell
.\run_pipeline.ps1                          # 交互菜单
.\run_pipeline.ps1 -Stage all               # 完整流水线（含 enrich-s2 + import-if）
.\run_pipeline.ps1 -Stage enrich            # 仅引用 + IF 导入
.\run_pipeline.ps1 -Stage all -SkipEnrich   # 跳过引用/IF
.\run_pipeline.ps1 -Stage extract -ExtractLimit 20 -CoreOnly
.\run_pipeline.ps1 -Stage weekly               # 每周增量（EDAT 14 天 + 后续步骤）
.\run_pipeline.ps1 -Stage fetch -SinceDays 14  # 仅增量 fetch
```
