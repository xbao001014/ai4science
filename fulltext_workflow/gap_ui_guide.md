# Gap Debate UI 用户操作指南

本文档说明如何使用 `gap_ui.py`（Streamlit 图形界面），完成**文献知识图谱研究空白辩论 → 数据可行性核验 → 研究方案生成**的完整流程。

---

## 1. 工具简介

**Gap Debate UI** 是 Pathomics/Radiomics 全文知识图谱（KG）的交互式分析界面，核心能力包括：

| 能力 | 说明 |
|------|------|
| 三角色辩论 | Opportunity Scout（机会发掘）→ Evidence Reviewer（证据审查）→ Final Synthesizer（综合定稿） |
| 证据追溯 | 从工具调用结果中提取全文引用、PMID、文献列表 |
| 空白报告 | 生成可下载的 Markdown 格式 Gap Report |
| 数据可行性 | 对接方信病理 LIS API（D-01 / D-02 / V-01 / V-02） |
| 研究方案 | 基于选定空白，由 Generator × Critic 迭代生成 Research Proposal |

界面分为 **侧边栏（参数与启动）** 和 **五个主标签页**。

---

## 2. 启动前准备

### 2.1 环境依赖

1. 在仓库根目录创建并安装虚拟环境：

```powershell
cd D:\agent\prototype\build_kg_paper
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

2. 在仓库根目录 `.env` 中配置 API 密钥（辩论与方案生成必需）：

```
DASHSCOPE_API_KEY=sk-xxx          # 或 OPENAI_API_KEY
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=deepseek-v4-flash
```

3. （推荐）先跑通数据流水线，确保知识图谱有内容：

```powershell
cd fulltext_workflow
..\.venv\Scripts\python.exe main.py run-all --limit 30
```

可选增强步骤（提升空白排序质量）：

```powershell
..\.venv\Scripts\python.exe main.py enrich-s2      # 引用数 enrichment
..\.venv\Scripts\python.exe main.py import-if data/journals_if.xlsx   # 期刊 IF
..\.venv\Scripts\python.exe main.py bootstrap-landscape --force     # 病理数据景观缓存
```

### 2.2 启动界面

在 `fulltext_workflow` 目录下任选一种方式：

```powershell
# 推荐
.\run_gap_ui.ps1

# 或
.\run_gap_ui.bat

# 或直接调用 venv 中的 streamlit
..\.venv\Scripts\streamlit.exe run gap_ui.py
```

启动后浏览器会自动打开（默认 `http://localhost:8501`）。若提示缺少 `openai` 模块，请确认使用的是项目 `.venv` 而非系统 Anaconda 环境。

---

## 3. 界面总览

```
┌─────────────────────────────────────────────────────────────┐
│  侧边栏 Sidebar                                              │
│  · 语料库统计（论文数、已抽取、S2、IF、景观缓存等）           │
│  · Research focus / Gap 数量 / 辩论轮次 / 方案轮次           │
│  · Run Gap Debate 按钮                                       │
├─────────────────────────────────────────────────────────────┤
│  主区域 — 五个标签页                                          │
│  [Debate Process] [Evidence & Literature] [Gap Report]       │
│  [Data Feasibility] [Research Proposal]                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 侧边栏操作

### 4.1 语料库统计（Corpus）

侧边栏顶部显示当前 SQLite 数据库 `data/kg_fulltext.db` 的概况：

- **Papers**：已入库文献数
- **Extracted**：已完成 KG 抽取的文献数
- **S2 enriched**：已 enrichment 引用数的文献数
- **IF journals**：已导入影响因子期刊数
- **Full-text rels**：来自全文的关系三元组数
- **Landscape**：已缓存的病理病种数

若 Papers / Extracted 为 0，需先运行 `main.py` 流水线（见 §2.1）。

### 4.2 参数设置

| 参数 | 说明 | 建议 |
|------|------|------|
| **Research focus** | 研究聚焦关键词，如 `radiomics`、`breast cancer`；留空则分析全语料 | 首次可留空；有明确方向时填写以缩小范围 |
| **Gap recommendations** | 最终报告推荐的空白数量（3–10） | 默认 6 |
| **Max debate rounds** | 辩论最大轮次（1–3） | 默认 2；证据不足时可增至 3 |
| **Max Generator × Critic rounds** | 研究方案标签页中生成器与批评者的迭代轮次（1–5） | 默认 2 |
| **Show LLM reasoning traces** | 是否展开显示各角色的 LLM 推理过程 | 调试时勾选；日常使用可关闭 |

### 4.3 运行辩论

点击 **Run Gap Debate**（主按钮）启动三角色辩论。运行期间页面顶部会出现实时状态面板，显示：

- 当前辩论轮次
- 各角色阶段（带颜色徽章）
- 工具调用步骤与返回记录数
- Evidence Reviewer 置信度（0–10）
- Final Synthesizer 的修订请求（如需多轮）

辩论结束后，侧边栏会显示本次会话统计：工具调用次数、检索记录数、证据行数。

> **注意**：每次点击 Run Gap Debate 会**清空**上一次辩论的 events 和 report，重新开始。如需保留报告，请先在 Gap Report 标签页下载 Markdown。

---

## 5. 五个标签页详解

### 5.1 Debate Process（辩论过程）

**用途**：查看完整辩论轨迹与工具调用明细。

**未运行辩论时**：显示三角色说明卡片和辩论流程帮助。

**运行后**：

1. **角色卡片摘要** — Opportunity Scout / Evidence Reviewer / Final Synthesizer 的职责说明
2. **辩论卡片**（可展开）：
   - Opportunity Scout 候选空白列表
   - Evidence Reviewer 审查结论与置信度
   - Final Synthesizer 修订意见
3. **工具调用步骤**（Step 1, Step 2, …）— 每步可展开查看：
   - 调用角色
   - 工具名称（如 Author-Stated Gaps、Lit Impact Matrix 等）
   - 返回数据表格或可行性评分

工具按类别着色，主要包括：

| 类别 | 代表工具 |
|------|----------|
| Full-Text Evidence | Author-Stated Gaps、Metric Evidence Quality |
| Impact Weighting | Limitation × Impact、Hotspot Entities、Lit Impact Matrix |
| Coverage / Combination Gap | Disease-Task Coverage、Method × Disease Combo Gap |
| Graph Analysis | Entity PageRank、Community Gaps、Disease-Method Reach |
| Data Feasibility | D-01 Disease Catalog、V-01/V-02 可行性评估 |

---

### 5.2 Evidence & Literature（证据与文献）

**用途**：从辩论过程中自动汇总的可追溯证据。

**两个表格**：

1. **Full-Text Evidence** — 每条证据包含 PMID、标题/实体、证据章节、引用原文片段、来源工具
2. **Papers** — 辩论中检索到的文献元数据（标题、年份、期刊、PMID、研究类型、全文状态）

若表格为空，说明当前 focus 下工具未返回带 `evidence_quote` 或 `pmid` 的记录，可尝试扩大 focus 或先完成更多文献抽取。

---

### 5.3 Gap Report（空白报告）

**用途**：查看并导出 Final Synthesizer 产出的最终研究报告。

**顶部指标**：

- Focus（本次聚焦主题）
- Debate rounds（实际辩论轮数）
- Reviewer confidence（Evidence Reviewer 综合置信度，0–10；≥7.5 时更可能直接定稿）
- Tool calls（工具调用总次数）

报告正文中，技术角色名已替换为易懂标签（Opportunity Scout / Evidence Reviewer / Final Synthesizer）。

点击 **Download report (Markdown)** 可下载带时间戳的 `.md` 文件，便于存档或分享给合作者。

---

### 5.4 Data Feasibility（方信病理数据 API）

**用途**：独立测试或配合辩论结果，评估研究假设在方信 LIS 数据上的可行性。

> 此标签页**无需先运行辩论**即可使用（例如直接测试 API）。

#### Phase 0：数据景观缓存

页面顶部显示 SQLite `pathology_landscape` 中已缓存的病种数。

| 按钮 | 作用 |
|------|------|
| **Bootstrap Landscape** | 从 LIS API 拉取病种目录与样本统计（若已有缓存则跳过） |
| **Force Reload** | 强制重新从 API 全量刷新 |

首次使用或下拉框无病种时，请先点击 Bootstrap Landscape。

#### 子标签说明

**D-01 / D-02 Catalog**

- **D-01**：按器官系统、最小病例数筛选病种目录
- **D-02**：选择某一 `disease_id`，查看该病种支持的任务类型及样本量

**V-01 Feasibility**

填写研究假设参数后运行可行性评估：

| 字段 | 说明 |
|------|------|
| disease_id | 病种编码（如 GC-ADC） |
| task_type | 任务类型：生存预测、分级分类、分子亚型、区域分割等 |
| min_followup_months | 最短随访月数（生存类任务） |
| required_labels | 必需标签，逗号分隔（如 `overall_survival_months, death_event`） |
| required_molecular_markers | 必需分子标志物（如 `MSI_status, HER2`） |
| required_annotations | 必需标注字段（如 `tnm_stage, who_grade`） |

结果展示：Feasibility Score（0–1）、队列规模、Recommendation、样本分项 breakdown。

**V-02 Gap Analysis**

与 V-01 使用相同假设，但额外输出**数据瓶颈**和**替代研究方向建议**。可点击 **Copy from V-01 form & run V-02** 一键复用 V-01 表单参数。

**Lit × Data Matrix**

输入文献聚焦关键词（默认继承 sidebar 的 focus），生成「文献空白 × 数据队列 × 引用/IF 影响」交叉矩阵。`cross_priority_score` 越高，表示该方向文献缺口大且数据与影响力条件较好。

> 若矩阵为空，请先运行 `enrich-s2` 和 `import-if`，并确保 KG 已抽取。

**Quick check from Gap**

将辩论报告中的空白标题映射到病种并自动评估可行性：

1. 若已运行辩论且报告中有空白列表 → 下拉选择空白 → **Assess selected gap**
2. 否则在文本框手动输入空白描述 → **Assess manual gap**

结果包含映射的 `disease_id`、映射置信度、V-01/V-02 评估详情及 evolution log。

---

### 5.5 Research Proposal（研究方案）

**用途**：针对某一研究空白，由 Generator（生成器）与 Critic（批评者）多轮迭代，输出完整研究方案。

#### 操作步骤

1. **先完成 Gap Debate**（或在「Enter manually」模式下手动输入空白）
2. 选择空白来源：
   - **Select from report** — 从辩论报告解析出的空白标题列表中选择
   - **Enter manually** — 自行输入空白描述
3. 在侧边栏设置 **Max Generator × Critic rounds**（方案迭代轮次）
4. 点击 **Generate Research Proposal**

运行过程中可看到每轮的工具调用、草稿长度、Critic 评分（0–10）及是否接受。

#### 结果

- **Final score**：Critic 对最终方案的评分
- **Rounds**：实际迭代轮数
- 正文为 Markdown 格式研究方案（含背景、方法、数据、预期成果等，具体结构由 agent 生成）
- 点击 **Download proposal (Markdown)** 下载

---

## 6. 推荐工作流

### 流程 A：完整闭环（首次使用）

```
1. main.py run-all --limit 30          # 建库 + 抽取
2. main.py bootstrap-landscape         # 缓存病理数据景观
3. 启动 gap_ui.py
4. 侧边栏设置 focus → Run Gap Debate
5. Gap Report 标签页审阅并下载报告
6. Data Feasibility → Quick check from Gap 核验 Top 空白
7. Research Proposal → 选择最优空白 → Generate
8. 下载 proposal .md
```

### 流程 B：已有 Gap Report，仅生成方案

```
1. 启动 gap_ui.py
2. Research Proposal → Enter manually → 粘贴空白描述
3. Generate Research Proposal
```

### 流程 C：仅测试病理 API（无需 LLM 辩论）

```
1. 启动 gap_ui.py
2. 直接进入 Data Feasibility 标签页
3. Bootstrap Landscape → V-01 / V-02 手动填参测试
```

---

## 7. 三角色辩论机制说明

| 角色 | 英文名 | 职责 |
|------|--------|------|
| 机会发掘 | Opportunity Scout | 查询 KG，提出 Top-N 候选研究空白 |
| 证据审查 | Evidence Reviewer | 独立复核查证，区分真空白 / 假阳性 / 弱证据，给出 0–10 置信度 |
| 综合定稿 | Final Synthesizer | 合并双方观点，结合方信数据支持，输出最终报告；或要求修订进入下一轮 |

**单轮流程**：Opportunity Scout 提案 → Evidence Reviewer 审查 → Final Synthesizer 定稿或发回修订。

**置信度参考**：Evidence Reviewer 评分 ≥7.5 时，Final Synthesizer 更倾向于直接发布终稿；低于此值可能触发额外辩论轮次（取决于 Max debate rounds 设置）。

---

## 8. 常见问题

### Q1：点击 Run Gap Debate 后报错「Missing dependency: openai」

使用项目虚拟环境启动：`.\run_gap_ui.ps1`，或手动执行 `..\.venv\Scripts\pip install -r ..\requirements.txt`。

### Q2：辩论很快结束但报告为空 / 工具返回 0 条记录

- 检查 `data/kg_fulltext.db` 是否有已抽取文献（侧边栏 Extracted > 0）
- 若 focus 过窄，尝试留空或换关键词
- 检查 `.env` 中 LLM API Key 是否有效、余额是否充足

### Q3：Data Feasibility 下拉框无病种

点击 **Bootstrap Landscape**；若仍失败，检查网络与 `PATHOLOGY_API_BASE_URL` / `PATHOLOGY_API_KEY`（见仓库根 `.env` 与 `api_document.md`）。

### Q4：Lit × Data Matrix 为空

知识图谱可能未构建或无匹配文献；先运行 `main.py extract` 和 `main.py build`，可选 `enrich-s2` + `import-if`。

### Q5：Research Proposal 按钮灰色不可点

需先选择或输入非空白的 gap 文本；若选「Select from report」但列表为空，请先完成 Gap Debate。

### Q6：辩论或方案生成很慢

属正常现象：每轮涉及多次 LLM 调用与数据库/ API 查询。可减少 debate rounds、关闭 reasoning traces，或缩小 Gap recommendations 数量。

### Q7：如何离线测试数据可行性

在 `.env` 设置 `PATHOLOGY_DATA_PROVIDER=mock`，使用 `feasibility/mock_data/` 中的 fixtures（无需连接方信 API）。

---

## 9. 相关文档

| 文件 | 内容 |
|------|------|
| `fulltext_workflow/README.md` | 命令行流水线总览 |
| `api_document.md` | 方信病理 LIS API 接口说明 |
| `pathology_data_api_spec.md` | D-01 / V-01 / V-02 数据规范 |
| `debate_labels.py` | 角色标签与报告人性化替换规则 |

---

## 10. 快捷参考

| 我想… | 操作 |
|--------|------|
| 发现研究空白 | Sidebar → Run Gap Debate → Gap Report |
| 查看证据出处 | Evidence & Literature 标签页 |
| 评估数据能否支撑某空白 | Data Feasibility → Quick check from Gap |
| 手动测试某病种样本量 | Data Feasibility → V-01 Feasibility |
| 生成可立项的研究方案 | Research Proposal → 选空白 → Generate |
| 导出结果 | Gap Report / Research Proposal 页的 Download 按钮 |

---

*文档对应 `fulltext_workflow/gap_ui.py` 当前版本。界面更新后请以源码为准。*
