# Design: Transferable Gap Candidates + Task Quality

**Date:** 2026-07-29  
**Status:** Approved  
**Depends on:** Weekly hotspot (`analysis/weekly_hotspot.py`), entity normalize (`extractor/entity_normalize.py`), study prompts (`extractor/study_prompts/shared.py`)

## Problem

「空白机会」(`compute_emerging_gap_opportunities`) 有两路逻辑：

1. **热门组合升温** — 真实 method×disease 共现且 nascent/heating（相对可信，但更像「正在形成」而非空白）。
2. **笛卡尔积空洞** — `method_disease_combo_gap` 取热门方法 Top-N × 热门疾病 Top-N，共现 0/≤2 标 unexplored/minimal；再与「方法**或**疾病在周升温榜」交叉。

第 2 路会产生假机会：方法 A 因病种 A 变热、病种 B 因方法 B 变热，并不意味着方法 A×病种 B 值得做。

若改用 Task 桥接补可迁移性，当前 Task 质量不足：库内约 84 个 Task、多数仅 1 篇；存在泛化词（`classification`）、近重复（`prognosis prediction` / `prognostic prediction`）、非任务句（workshop report、cohort diversity 等）。盲信桥接会换成另一种假信号。

用户计划后续**全库重抽**，因此本设计同时改抽取侧与分析侧。

## Goals

1. 周热点主榜将「空白机会」改为 **可迁移候选**：禁止热实体笛卡尔积作为主信号。
2. Task **质量分层**（`reject` / `weak` / `ok`）；桥接默认只用 `ok`。
3. 抽取侧：prompt 收紧 + normalize 黑名单/丢弃 + **Task synonym → canonical**（重抽后落库即干净）。
4. 只读 **Task 质量审计** CLI，便于调规则与补 synonym。
5. UI / 报告文案与列字段与新语义一致。

## Non-goals

- 本轮不执行全库重抽（由用户后续跑 pipeline）。
- 不做运行时 UMLS/MeSH；Task synonym 用可维护小表。
- 不改变「热门组合」共现统计本身。
- 不强制改写辩论工具 `method_disease_combo_gap` 的存在（可保留作覆盖诊断）；**不得再作为**周热点可迁移主榜数据源。
- 不做 Limitation synonym 大表扩展（已有 reconcile 路径，本设计不碰）。

## Approach (chosen)

**Task 桥接的可迁移候选 + 抽取期 Task 质量控制 + synonym 归并**（原 brainstorm 选项 B∪3）。

Rejected:

- **仅砍笛卡尔积** — 机会变成升温组合换皮，无可迁移解释。
- **仅 OR→AND 热实体** — 仍是无桥接的笛卡尔积。
- **分层保留覆盖空洞为主展示** — 易继续被误读为研究方向。

## Task quality taxonomy

Module: `fulltext_workflow/analysis/task_quality.py`（分级纯函数，供审计与机会模块共用）。

抽取路径也可调用同一套谓词（或把黑名单/synonym 放在 `entity_normalize.py`，`task_quality` re-export / 委托），避免两套规则漂移。

### `reject` — 不当桥；抽取时应丢弃 Task 实体或整条 `PERFORMS_TASK`

| 规则 | 示例 |
|------|------|
| 泛化黑名单（归一化后整词） | `classification`, `segmentation`, `detection`, `prediction`, `diagnosis`, `prognosis`, `analysis`, `identification`, `grading`, `staging` |
| 非任务叙事/工程句启发式 | 含 `workshop`, `report`, `improving `, `developing `, `integrating ` 等；或过长（建议 >80 chars）且不像简洁名词短语 |
| 关系错型 | 非 `PERFORMS_TASK` 挂到 Task（若出现，审计标记；normalize 已有关系修正则依赖既有路径） |

### `weak` — 可留库统计，默认不参与桥接

| 规则 | 示例 |
|------|------|
| 过短 / 单 token ML 动词残留 | 长度阈值或仅一词且不在 ok 白形态 |
| 仅粗粒度、缺临床/目标修饰 | 边界个案由审计人工补黑/白名单 |

### `ok` — 可作桥接

- 具体临床或 ML 目标名词短语（如 `tumor subtype classification`, `survival prediction`, `hpv lesion classification`）。
- 关系为 `PERFORMS_TASK`。
- 不要求强制 ≥2 篇（当前语料稀疏）；有多篇或清晰 Method/Disease 共现则审计记为更高置信，可作排序加分，不作硬门槛。

配置：黑名单与长度阈值放 `entity_normalize` / `task_quality` 常量；后续可用 env 覆盖非必须。

## Task synonym merge

**位置：** `normalize_entity_name(name, "Task")` 内维护 `_TASK_SYNONYMS: dict[str, str]`（key/value 均 `_norm_key`）。

**行为：** 别名 → canonical 显示名（小写简洁短语，与现有 entity 风格一致）。

**初始条目（v1，可审计后扩充）：**

| Alias | Canonical |
|-------|-----------|
| `prognostic prediction` | `prognosis prediction` |
| `prognosis prediction` | `prognosis prediction` |
| `pathological classification` | `pathology classification`（或保留更具体子串优先策略：若已有更长具体名则不升粗） |

原则：

- 只合并**明显同义**近重复，不把 `tumor subtype classification` 并进 `classification`。
- 泛化名走 reject，不进 synonym 表当 canonical。
- 审计输出「编辑距离/词袋相近但未映射」候选，人工补表（不自动合并）。

全库重抽后，历史近重复实体可通过新抽取自然收敛；本轮**不**做离线 DB 批量 rename migration（避免与重抽计划重复劳动）。若重抽前需读旧库，机会模块对 Task 名先 `normalize_entity_name` 再分级。

## Prompt changes

File: `extractor/study_prompts/shared.py`（Task naming policy）。

- 明确 Task = 本篇研究的临床/ML **目标名词短语**。
- GOOD：`tumor segmentation`, `survival prediction`, `biomarker prediction`, `msi status prediction`。
- BAD：单独 `classification` / `detection`；workshop/report 标题；「improving cohort diversity」类非任务句；把 Method 骨架写成 Task。
- 继续强调 `PERFORMS_TASK` → Task，禁止 `APPLIES_METHOD` + Task。

## Transferable opportunity algorithm

Replace body of `compute_emerging_gap_opportunities` in `analysis/weekly_hotspot.py`.

### Inputs

- Weekly payload: `emerging_methods`, `heating_diseases`, `hot_combos`（可选作加分，不作唯一来源）。
- KG via SQL：`APPLIES_METHOD`, `TARGETS_DISEASE`, `PERFORMS_TASK`（`status=active`）。
- Task quality + synonym normalize.

### Candidate `(method, disease)` inclusion (all required)

1. **Method heat:** `method` ∈ top emerging methods（窗口内，沿用现 Top 截断，如 20）。
2. **Disease relevance:** `disease` ∈ top heating diseases **或**（若 focus 非空）focus 匹配病种。
3. **Sparse combo:** literature co-occurrence count of method×disease ≤ 2（全库 active 边，与现 gap 阈值一致）。
4. **Transfer prior:** method 在**至少一个其他** disease 上有共现（证明方法非单病绑定）。
5. **Task bridge:** ∃ task T with `quality(T) == ok` such that:
   - some paper has (method + T), and
   - some paper has (disease + T)  
   （允许跨篇；同篇更优可加分）。

### Scoring (transparent, heuristic)

```
opportunity_score =
  emerging_score(method)          # or 0 if not in board
  + literature_gap_points(tier)   # 0→unexplored, ≤2→minimal
  + bridge_bonus                  # e.g. same-paper bridge > cross-paper; ok only
  + context_novelty_bonus
  - maturity_penalty
  + nascent_bonus
  + actionability_bump             # binding / public-dataset support, when available
```

### Output row fields

| Field | Meaning |
|-------|---------|
| `method`, `disease` | Pair |
| `literature_gap` | `unexplored` / `minimal` |
| `literature_paper_cnt` | Co-occurrence count |
| `bridge_task` | Chosen T (highest quality / support) |
| `bridge_quality` | `ok` |
| `bridge_mode` | `same_paper` / `cross_paper` |
| `support_diseases` | Other diseases where method co-occurs (top few) |
| `recent_hot_cnt` / `velocity` / `emerging_score` | From weekly method stats when available |
| `opportunity_score` | Rank key |

### Explicitly removed from this function

- Loop over `method_disease_combo_gap` gaps filtered by `method in hot_methods or disease in hot_diseases` without bridge.

Optional: keep a **debug-only** or collapsed UI for raw coverage holes later — **not** in v1 UI.

### Tool / agent

- `tool_emerging_gap_opportunities` description 更新为可迁移语义。
- Agent prompt（`gap_agent.py`）一句同步：emerging gap = task-bridged transfer candidates，非笛卡尔积空洞。

## UI (`gap_ui.py`)

- 子 Tab「空白机会」→「可迁移候选」。
- 表展示新列：`bridge_task`, `bridge_quality`, `bridge_mode`, `support_diseases`, `opportunity_score`。
- Caption：说明需合格 Task 桥；无桥则列表为空（优于假阳性）。
- Markdown 报告同名小节。
- LLM hotspot brief system prompt：交叉机会改为「可迁移候选」，勿把无桥空洞当机会。

## Audit CLI

- Command: `main.py task-quality-audit`（或等价）。
- Output: Task 计数按档；Top reject/weak 样例；近重复未映射候选；`PERFORMS_TASK` 覆盖率。
- Write optional `output/task_quality_audit_{date}.md`；stdout 摘要即可。
- **不写** papers / relations（只读）。

## Testing

| Area | Cases |
|------|-------|
| Normalize | Generic task → dropped or rejected; synonym maps; specific phrase kept |
| Quality | reject / weak / ok fixtures |
| Opportunities | Hot M on D1 + hot D2 **without** shared ok task → **not** listed; with shared ok task + sparse M×D2 + M used elsewhere → listed with `bridge_task` |
| Regression | Cartesian-only fixture must not appear |

Use in-memory / temp DB patterns from existing `test_weekly_hotspot*.py`.

## Rollout

1. Land code + unit tests.
2. Run `task-quality-audit` on current DB（预期大量 weak/reject；机会列表可能变短或空——可接受）。
3. User full-corpus re-extract → synonym + reject 生效 → 再审计与看可迁移候选。
4. Tune synonym table from audit leftovers.

## Risks

| Risk | Mitigation |
|------|------------|
| Task 过稀导致机会为空 | Caption 说明；审计驱动补抽/补 synonym；不回退笛卡尔积 |
| 桥接 Task 仍偏泛 | reject 黑名单 + prompt；weak 不桥接 |
| synonym 过度合并 | 只合近重复；禁止并入泛化 canonical |
| 与旧报告/快照字段不一致 | 新字段向后兼容多列；旧 `opportunity_score` 含义变更在报告注明 |

## Open decisions (resolved)

- Scope: audit + opportunity filter + extract tighten + synonym（用户确认）。
- Full re-extract: user-owned follow-up，非本实现阻塞。
