# Gap Debate UI 用户操作指南

本文档说明如何使用 `gap_ui.py`（Streamlit），完成：

**周热点浏览 → 文献 KG 空白辩论 → 可视化核验 → 方信数据可行性 → 研究方案生成**。

对应源码：`fulltext_workflow/gap_ui.py`。命令速查见 [SCRIPTS.md](SCRIPTS.md)，流水线见 [PIPELINE.md](PIPELINE.md)。

---

## 1. 工具简介

| 能力 | 说明 |
|------|------|
| 三角色辩论 | Opportunity Scout → Evidence Reviewer → Final Synthesizer |
| 周热点 | 发表窗口热点榜、Week-over-Week、交叉机会、LLM 简报 |
| 可视化 | Plotly：辩论漏斗、工具 treemap、method×disease、lit×data |
| 证据追溯 | PMID、证据章节、引用片段、语料 focus 匹配文献 |
| 空白报告 | Markdown Gap Report，可下载；默认写入 ops memory |
| 数据可行性 | 方信 LIS（D-01/D-02、V1.1 分布、V-01/V-02、交叉矩阵） |
| 研究方案 | Generator × Critic，可行性门控 |
| Ops memory | 同 focus 软避让近重复空白；成功后持久化 |

界面 = **侧边栏** + **七个主标签页**。

---

## 2. 启动前准备

### 2.1 环境

```powershell
cd D:\agent\prototype\build_kg_paper
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# 可视化页需要 plotly（若缺）：
.\.venv\Scripts\pip install plotly
```

根目录 `.env` 最少：

```ini
DASHSCOPE_API_KEY=sk-xxx          # 或 OPENAI_API_KEY
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=deepseek-v4-flash
LLM_MODEL_AGENT=qwen3.7-plus      # 辩论 / 方案 / hotspot-brief

# 可行性（可选）
PATHOLOGY_API_BASE_URL=http://ai.gzfxyl.cn/api/v1/pathology
PATHOLOGY_API_KEY=your-key
```

### 2.2 建议先有 KG 数据

```powershell
cd fulltext_workflow
..\.venv\Scripts\python.exe main.py run-db --limit 30 --core-only
..\.venv\Scripts\python.exe main.py enrich-s2
..\.venv\Scripts\python.exe main.py import-if          # 默认 data/jcr.csv
..\.venv\Scripts\python.exe main.py build
..\.venv\Scripts\python.exe main.py bootstrap-landscape   # 可行性；已有缓存会跳过
# 强制重载（慢）：bootstrap-landscape --force
```

周热点有内容前，建议至少跑过一次增量入库或 `hotspot-report`：

```powershell
.\run_pipeline.ps1 -Stage weekly
# 或
..\.venv\Scripts\python.exe main.py hotspot-report
```

### 2.3 启动 UI

```powershell
cd fulltext_workflow
.\run_gap_ui.ps1
# 或
..\.venv\Scripts\streamlit.exe run gap_ui.py
```

浏览器默认：`http://localhost:8501`。缺 `openai` 时请用项目 `.venv`，不要用系统 Anaconda。

---

## 3. 界面总览

```
┌──────────────────────────────────────────────────────────────────┐
│  Sidebar                                                         │
│  Corpus 统计 · focus · Top-N · 辩论/方案轮次 · ops memory 开关   │
│  Run Gap Debate                                                  │
├──────────────────────────────────────────────────────────────────┤
│  [Debate Process] [Weekly Hotspot] [Visualization]               │
│  [Evidence & Literature] [Gap Report]                            │
│  [Data Feasibility (Fangxin LIS)] [Research Proposal]            │
└──────────────────────────────────────────────────────────────────┘
```

标签页切换会尽量保持在当前页（内部 tab sync），刷新后一般不会跳回第一页。

---

## 4. 侧边栏

### 4.1 Corpus

来自 `data/kg_fulltext.db`：

- Papers / Extracted / S2 enriched / IF journals  
- Full-text rels / Landscape（病理病种缓存数）

Extracted 为 0 时先跑抽取流水线。

### 4.2 参数

| 参数 | 说明 | 默认建议 |
|------|------|----------|
| **Research focus** | 如 `breast cancer`、`radiomics`；空=全库 | 有明确方向时填写 |
| **Gap recommendations** | 最终推荐空白数（3–10） | 6 |
| **Max debate rounds** | 辩论轮次（1–3） | 2 |
| **Max Generator × Critic rounds** | 方案页迭代（1–5） | 2 |
| **Show LLM reasoning traces** | 展开推理过程 | 日常关 |
| **Use ops memory** | 注入同 focus 最近约 4 次空白，软避让重复 | 开 |
| **Persist this run** | 辩论/方案成功后写入 `ops_*` 表 | 开 |

**Ops memory for this focus**（展开）：预览当前 focus 已记住的空白标题。清空记忆：

```powershell
..\.venv\Scripts\python.exe scripts/clear_ops_memory.py --focus "breast cancer" --yes
```

### 4.3 Run Gap Debate

点击后清空上一次 events/report 并重新辩论。需保留结果时，先在 **Gap Report** 下载 Markdown。

运行中顶部 status：轮次、角色、工具步骤、Evidence Reviewer 置信度、修订请求。结束后侧边栏显示 Session stats。

---

## 5. 七个主标签页

### 5.1 Debate Process

- 未运行：角色说明 + 辩论流程帮助  
- 运行后：Scout / Reviewer / Synthesizer 卡片 + Step 工具调用明细  

工具类别（按 expander 着色）：

| 类别 | 代表工具 |
|------|----------|
| Corpus Diagnostics | Focus Corpus Coverage |
| Full-Text Evidence | Author-Stated Gaps、Metric Evidence Quality |
| Temporal Gap | Limitation Temporal / Gap Status、Combo Gap Temporal |
| Impact Weighting | Limitation × Impact、Hotspot Entities、Lit Impact Matrix |
| Coverage / Combination | Disease-Task Coverage、Method × Disease Combo |
| Graph Analysis | PageRank、Community Gaps、Disease-Method Reach |
| Data Feasibility | D-01/D-02、V-01/V-02、Lit × Data Matrix、V1.1 系列 |
| Weekly Hotspot | Weekly Hot × Gap（emerging_gap_opportunities） |

---

### 5.2 Weekly Hotspot

**无需先辩论即可使用。** 基于 `papers.pub_date` 发表窗口（`date_precision` ∈ day/month）与持久化快照。

| 操作 | 作用 |
|------|------|
| 窗口天数滑条 | 热点检测窗口（默认可跟 `HOTSPOT_WINDOW_DAYS`） |
| **Refresh hotspots** | 重算当前窗口榜单 |
| **Save snapshot report** | 写入 `output/weekly_hotspot_{week_id}.md` 并持久化快照 |
| **Generate LLM brief** | 用 `LLM_MODEL_AGENT` 生成中文趋势简报 |

子页大致包括：Methods / Diseases / Combos / Emerging × Gap / Limitations，以及 WoW（New / Cooled / Rank changes）。至少两次 `Save snapshot` 后 WoW 才有意义。

也可在 CLI：`main.py hotspot-report` / `hotspot-brief`。

---

### 5.3 Visualization

Focus 下的 **空白机会 × 方信对照**（不强制先辩论）：

| 区域 | 含义 |
|------|------|
| Summary | 组合数 / 文献稀缺数 / 已映射方信病种 / 高数据支持占比 |
| Left · Opportunity table | method×disease 空白行；可点选；辩论命中行标 `Debate` 并置顶 |
| Right · Fangxin detail | 选中病种的 landscape 缓存：病例规模、亚型、分子（只读，不在此 bootstrap） |
| Session diagnostics | 折叠区：辩论漏斗 + 工具 treemap |

默认只显示 `unexplored` / `minimal`；勾选 Show all coverage levels 看全部。无 focus 不扫全库。无 landscape 时请回 **Data Feasibility → Bootstrap Landscape**。

---

### 5.4 Evidence & Literature

- **Full-Text Evidence**：PMID、证据章节、quote、来源工具（辩论后才有）  
- **Papers**：辩论工具命中的文献；若无辩论但已填 focus，会按语料 focus 匹配展示论文列表  

---

### 5.5 Gap Report

顶部指标：Focus、Debate rounds、Reviewer confidence（≥7.5 更易直接定稿）、Tool calls。

正文已把 Optimist/Skeptic/Moderator 换成英文易读标签。  
**Download report (Markdown)** 下载。若开启 Persist，会写入 `ops_runs` / `ops_gap_items`。

---

### 5.6 Data Feasibility (Fangxin LIS)

**可不辩论独立使用。** 对接方信 LIS（schema V1.1）。

#### Phase 0 Landscape

| 按钮 | 作用 |
|------|------|
| **Bootstrap Landscape** | 拉取病种目录；已有缓存则跳过 |
| **Force Reload** | `--force` 全量刷新（很慢，约 20–30 分钟；会打很多 API） |

Cached landscape snapshot 可展开查看各病种 cases / subtypes / molecular 等。

#### 子标签

| 子页 | 内容 |
|------|------|
| D-01 / D-02 Catalog | 病种目录、任务类型与样本量 |
| Subtype (§7.4) | 亚型分布 |
| Attributes (§7.3) | 属性分布 |
| Molecular (§7.8) | 分子阳性率等 |
| Text Matches (§7.5–7.7) | 文本病种匹配摘要 |
| V-01 Feasibility | 假设可行性评分（队列 / labels / markers） |
| V-02 Gap Analysis | 数据瓶颈与替代方向；可从 V-01 复制参数 |
| Lit × Data Matrix | 文献空白 × 数据 × impact |
| Quick check from Gap | 从辩论空白或手写描述映射病种并评估 |

V-01 常用字段：`disease_id`、`task_type`、`min_followup_months`、`required_labels` / `required_molecular_markers` / `required_annotations`。

矩阵为空时：先 `extract` + `bootstrap-landscape`，并建议 `enrich-s2` + `import-if`。

---

### 5.7 Research Proposal

1. 先完成 Gap Debate，或 **Enter manually** 手写空白  
2. **Select from report** / **Enter manually**  
3. 侧边栏设好 Generator × Critic 轮次  
4. **Generate Research Proposal**  

结果含 Final score、迭代轮次、Markdown 方案与 **Download**。开启 Persist 时会写入 `ops_proposals`。

---

## 6. 推荐工作流

### A. 周常闭环

```
1. run_pipeline.ps1 -Stage weekly          # 增量 + 热点
2. （可选）main.py compute-gap-lifecycle --temporal-only
3. .\run_gap_ui.ps1
4. Weekly Hotspot 浏览 → 侧边栏 focus → Run Gap Debate
5. Visualization / Evidence / Gap Report 审阅
6. Data Feasibility → Quick check from Gap
7. Research Proposal → Generate → 下载
```

### B. 首次小规模试跑

```
1. main.py run-db --limit 30 --core-only
2. main.py build && main.py bootstrap-landscape
3. 启动 UI → Run Gap Debate → 各标签页走通
```

### C. 仅测 LIS API

```
1. 启动 UI → Data Feasibility
2. Bootstrap Landscape → V-01 / V-02 / Subtype 等
```

### D. 已有空白，仅写方案

```
Research Proposal → Enter manually → Generate
```

---

## 7. 三角色辩论

| 角色 | 职责 |
|------|------|
| Opportunity Scout | 查 KG，提出 Top-N 候选空白 |
| Evidence Reviewer | 独立核验真空白 / 假阳性 / 弱证据，置信度 0–10 |
| Final Synthesizer | 综合定稿，或要求进入下一轮修订 |

单轮：Scout → Reviewer → Synthesizer。置信度 ≥7.5 更易直接发布终稿。

---

## 8. 常见问题

### Q1：Missing dependency: openai

用 `.\run_gap_ui.ps1`，或 `..\.venv\Scripts\pip install -r ..\requirements.txt`。

### Q2：报告空 / 工具 0 条

Extracted > 0？focus 是否过窄？API Key / 余额是否正常？

### Q3：Data Feasibility 无病种

点 **Bootstrap Landscape**；检查 VPN/网络与 `PATHOLOGY_API_*`。Force Reload 很慢属正常。

### Q4：Visualization 报缺 plotly

```powershell
..\.venv\Scripts\pip install plotly
```

### Q5：Weekly Hotspot 几乎为空

先增量 `fetch` 或跑 `hotspot-report`；WoW 需要至少两周持久化快照。

### Q6：每次辩论空白都很像

确认 **Use ops memory** 已开且同 focus 有历史；或 CLI 查 `scripts/clear_ops_memory.py` 预览后按需清理。

### Q7：Research Proposal 按钮灰

需选定/输入非空 gap；Select from report 为空时先跑辩论。

### Q8：离线测可行性

`.env` 设 `PATHOLOGY_DATA_PROVIDER=mock`。

### Q9：辩论/方案很慢

属正常（多轮 LLM + 工具）。可减 rounds、关 reasoning traces、缩小 Gap recommendations。

---

## 9. 相关文档

| 文件 | 内容 |
|------|------|
| [README.md](README.md) | 管线概述 |
| [PIPELINE.md](PIPELINE.md) | 分阶段流水线 |
| [SCRIPTS.md](SCRIPTS.md) | 常用命令 / clear_ops_memory 等 |
| [../README.md](../README.md) | 仓库最外层入口 |
| [../api_document.md](../api_document.md) | 方信 LIS API |
| [../pathology_data_api_spec.md](../pathology_data_api_spec.md) | 可行性规格 |
| `debate_labels.py` | 角色显示名映射 |
| `docs/.../2026-07-15-ops-memory-design.md` | Ops memory 设计 |

---

## 10. 快捷参考

| 我想… | 操作 |
|--------|------|
| 看本周新兴方向 | Weekly Hotspot → Save / LLM brief |
| 发现研究空白 | Sidebar focus → Run Gap Debate → Gap Report |
| 看 focus 空白 × 方信对照 | Visualization |
| 查证据与 PMID | Evidence & Literature |
| 评估数据能否支撑空白 | Data Feasibility → Quick check from Gap |
| 手动测病种样本量 | Data Feasibility → V-01 |
| 生成可立项方案 | Research Proposal → Generate |
| 避免每周重复空白 | 保持 Use ops memory + Persist this run |
| 导出结果 | Gap Report / Proposal 的 Download |

---

*文档对应当前 `gap_ui.py`（七标签页 + ops memory + Weekly Hotspot + Visualization）。界面变更后以源码为准。*
