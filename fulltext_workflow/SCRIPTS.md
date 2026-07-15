# Full-Text Workflow 常用脚本

> 工作目录：`fulltext_workflow/`  
> 完整流水线说明见 [PIPELINE.md](PIPELINE.md)

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
$py = "..\.venv\Scripts\python.exe"
```

---

## 1. 一键脚本（最常用）

### `run_pipeline.ps1` — 流水线菜单 / 分阶段跑

```powershell
.\run_pipeline.ps1                         # 交互菜单
.\run_pipeline.ps1 -Stage weekly           # 每周增量（推荐）
.\run_pipeline.ps1 -Stage db               # 仅建库
.\run_pipeline.ps1 -Stage landscape        # 方信 landscape（--force）
.\run_pipeline.ps1 -Stage debate           # Gap 辩论
.\run_pipeline.ps1 -Stage all              # 全量建库+建图+analyze
.\run_pipeline.ps1 -Stage stats
```

| 参数 | 说明 |
|------|------|
| `-Stage` | `init` / `fetch` / `enrich` / `fulltext` / `extract` / `build` / `analyze` / `debate` / `landscape` / `stats` / `db` / `weekly` / `all` / `quick` |
| `-SinceDays N` | fetch 只搜最近 N 天 EDAT |
| `-CoreOnly` | extract 只抽核心章节 |
| `-ExtractLimit N` | 抽取篇数（0=全量待处理） |
| `-SkipEnrich` | 跳过 enrich-s2 / import-if |
| `-NoResume` | fetch 不跳过已有 PMID |

**`-Stage weekly` 包含**：fetch(14d) → enrich-s2 → fulltext → extract(core) → hotspot-report → hotspot-brief → build → analyze → stats  

**不含**：`import-if`、`compute-gap-lifecycle`、`gap-debate`、`bootstrap-landscape`

### `run_gap_ui.ps1` — Gap 分析 UI

```powershell
.\run_gap_ui.ps1
# 或
..\.venv\Scripts\streamlit.exe run gap_ui.py
```

浏览器：`http://localhost:8501`

---

## 2. 日常 `main.py` 命令

### 入库 / 元数据

```powershell
& $py main.py init
& $py main.py fetch
& $py main.py fetch --since-days 14
& $py main.py watch-fetch                 # 另开终端看 fetch 进度
& $py main.py enrich-s2
& $py main.py import-if                   # 默认 data/jcr.csv
& $py main.py fetch-fulltext
& $py main.py stats
```

### 抽取 / 建图 / 分析

```powershell
& $py main.py extract --limit 0 --core-only
& $py main.py extract --limit 30
& $py main.py compute-gap-lifecycle
& $py main.py compute-gap-lifecycle --temporal-only   # 更快
& $py main.py build
& $py main.py viz
& $py main.py analyze
```

### 周热点

```powershell
& $py main.py hotspot-report              # 写 md + 持久化快照
& $py main.py hotspot-report --no-persist
& $py main.py hotspot-brief               # LLM 简报
& $py main.py compute-weekly-hotspots     # 仅打印摘要
```

### Gap / 方案 / 数据景观

```powershell
& $py main.py bootstrap-landscape         # 已有缓存则跳过
& $py main.py bootstrap-landscape --force # 强制重载（慢，约 20–30 分钟）
& $py main.py gap-debate --focus "nasopharyngeal carcinoma" --top 6 -o output/gap_debate_report.md
& $py main.py gap-debate --no-ops-memory --no-ops-persist
& $py main.py idea-pipeline --focus radiomics --top 3 -o output/idea_pipeline_report.md
```

### 一键建库（Python）

```powershell
& $py main.py run-db --since-days 14 --core-only
& $py main.py run-db --skip-enrich --limit 30
& $py main.py run-all --limit 30          # fetch→fulltext→extract→build→analyze
```

---

## 3. 维护脚本 `scripts/`

在 `fulltext_workflow/` 下执行：

```powershell
# 重置「已抽取但无 relations」的论文（跳过勘误文）
& $py scripts/reset_empty_extraction.py
& $py scripts/reset_empty_extraction.py --dry-run

# 重置全部已抽取论文，准备重抽（慎用）
& $py scripts/reset_extraction.py --dry-run
& $py scripts/reset_extraction.py

# PMC 缓存 PMID/DOI 错配：预览 / 清除错配全文
& $py scripts/fix_pmc_mismatch.py --dry-run
& $py scripts/fix_pmc_mismatch.py

# 抽取质量基线（库内 Method 等 top 统计）
& $py scripts/compare_extraction_quality.py

# ── Ops memory（ops_runs / ops_gap_items / ops_proposals）──
# 默认仅预览；不影响 papers / KG / hotspot
& $py scripts/clear_ops_memory.py
& $py scripts/clear_ops_memory.py --yes
& $py scripts/clear_ops_memory.py --focus "breast cancer" --yes
& $py scripts/clear_ops_memory.py --yes --delete-files   # 同时删引用的 md

# 补全历史 proposal 的 gap_item_id / status / proposal_path（一次性）
& $py scripts/backfill_ops_proposals.py
```

| 脚本 | 作用 |
|------|------|
| `reset_empty_extraction.py` | 重置抽取完成但无三元组的论文 |
| `reset_extraction.py` | 重置全部已抽取结果（重抽） |
| `fix_pmc_mismatch.py` | 修复 PMC XML 与 PMID/DOI 错配 |
| `compare_extraction_quality.py` | 抽取质量 baseline 统计 |
| `clear_ops_memory.py` | 清空周常 ops memory（可按 focus） |
| `backfill_ops_proposals.py` | 回填 `ops_proposals` 缺失字段 |

---

## 4. 推荐组合拳

### 每周更新

```powershell
.\run_pipeline.ps1 -Stage weekly
# 可选：辩论前刷新 limitation 时间画像
& $py main.py compute-gap-lifecycle --temporal-only
& $py main.py gap-debate --focus "your topic" -o output/gap_debate_report.md
.\run_gap_ui.ps1
```

### 首次全量建库

```powershell
.\run_pipeline.ps1 -Stage all
& $py main.py compute-gap-lifecycle
& $py main.py bootstrap-landscape --force   # 若需要可行性分析
```

### 只想看库状态 / 试跑 UI

```powershell
.\run_pipeline.ps1 -Stage stats
.\run_gap_ui.ps1
```

---

## 5. 环境变量速查（`.env`）

| 变量 | 用途 |
|------|------|
| `PUBMED_EMAIL` / `PUBMED_API_KEY` | PubMed |
| `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` | LLM |
| `LLM_MODEL_EXTRACT` | 章节抽取模型 |
| `LLM_MODEL_AGENT` | gap / idea / hotspot-brief |
| `FETCH_EDAT_DAYS` | fetch 默认 EDAT 窗口 |
| `PATHOLOGY_API_KEY` | 方信 landscape / 可行性 |
| `PATHOLOGY_BOOTSTRAP_MAX_DISEASES` | landscape 最多病种（默认 30） |
| `OPS_MEMORY_ENABLED` | Gap 周常记忆软去重 |

---

## 6. 相关文档

| 文件 | 内容 |
|------|------|
| [PIPELINE.md](PIPELINE.md) | 分阶段流水线详解 |
| [gap_ui_guide.md](gap_ui_guide.md) | Streamlit UI 操作 |
| [README.md](README.md) | 沙盒概述与模块表 |
