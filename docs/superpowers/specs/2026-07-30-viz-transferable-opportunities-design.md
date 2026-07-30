# Design: Visualization Tab → Transferable Opportunities × Fangxin

**Date:** 2026-07-30  
**Status:** Approved  
**Depends on:** `2026-07-29-transferable-gap-task-quality-design.md`  
**Primary surfaces:** `fulltext_workflow/gap_ui.py` (`render_gap_visualization_tab`), `fulltext_workflow/viz/gap_opportunity.py`

## Problem

周热点已将「空白机会」改为 Task 桥接的**可迁移候选**，禁止热实体笛卡尔积作为主信号。  
可视化页仍以 `tool_method_disease_combo_gap`（方法×疾病覆盖空洞）驱动主表 + 方信双栏，文案为「焦点空白 × 方信支撑」——这是假空白的主要 UI 入口。

## Goals

1. 可视化主表与周热点同源：`compute_emerging_gap_opportunities`（可迁移候选）。
2. 保留右侧方信详情；选中行展示桥接摘要。
3. 方法×疾病 combo gap 降为折叠「覆盖诊断」，明确非机会。
4. 空表时不回退笛卡尔积填表。

## Non-goals

- 不改 `compute_emerging_gap_opportunities` 算法。
- 不删除 `method_disease_combo_gap` 工具或辩论侧调用。
- 不重做会话漏斗/树图；不做新热力图。
- 不全库重抽；Task 稀导致空表属预期。

## Approach

**主表换源 + 诊断降级**（brainstorm 选项 A）。

Rejected:

- **B. Task×疾病为主叙事** — 与已落地的 transferable pair 行模型不一致，改动面更大。
- **C. 可视化仅辩论×方信** — 失去焦点下「可迁移 × 数据」对照台价值。

## UI changes

### Title / caption

- 「焦点空白 × 方信支撑」→「可迁移候选 × 方信支撑」
- Caption：需升温方法 + 稀疏组合 + **ok Task 桥**；无桥则空表优于假阳性。

### Data source (left pane)

- **Stop** using `tool_method_disease_combo_gap` for the main table.
- **Use** `compute_emerging_gap_opportunities(focus=侧栏焦点)`，语义与周热点「可迁移候选」一致（可复用 weekly payload 缓存或同参直接计算）。
- Require sidebar focus; without focus show setup hint.

### Main table columns

| Column | Source |
|--------|--------|
| 来源 | Corpus / Debate（保留辩论标题叠加） |
| 方法 / 疾病 | Candidate pair |
| 桥接任务 | `bridge_task` |
| 桥接模式 | `bridge_mode` (`same_paper` / `cross_paper`) |
| 文献空白 | `literature_gap` |
| 论文数 | `literature_paper_cnt` |
| 支持病种 | `support_diseases`（缩写） |
| 得分 | `opportunity_score` |
| 方信 / 数据 | Existing `map_gap_to_disease` + landscape tier |

### Controls

- Keep Top N slider.
- Remove「显示全部覆盖等级」（旧 combo 语义）；可迁移候选本身已是稀疏档。
- Summary metrics: **候选数**、文献稀缺、已映射方信、高数据占比。

### Empty states

- No focus → set sidebar focus.
- Focus but no candidates → explain need for ok Task bridge (align weekly hotspot copy); **do not** fall back to cartesian combo rows.

### Right pane (Fangxin)

- Behavior unchanged: select row → DiseaseCode → cases / subtype / molecular.
- Add one summary line under title: **bridge_task + bridge_mode + opportunity_score**.

### Debate overlay

- Keep `parse_gap_titles` + `apply_debate_overlay`.
- Unmatched titles: list only; do not fabricate rows.

### Coverage diagnostic (collapsed)

- Expander「覆盖诊断（非机会）」`expanded=False`.
- May call `tool_method_disease_combo_gap(focus=…)` with caption: **覆盖空洞 ≠ 研究方向**.
- Columns: method, disease, paper_cnt, gap; Top ~20; scarce tiers.
- Does **not** drive Fangxin selection (selection only from transferable main table).

### Session diagnostics

- Keep existing「会话诊断」funnel/treemap.
- Order: coverage diagnostic expander, then session diagnostic expander.

## Code touchpoints

| File | Change |
|------|--------|
| `viz/gap_opportunity.py` | Adapt row builder/sort for transferable fields (`bridge_*`, `opportunity_score`); prefer score in sort |
| `gap_ui.py` `render_gap_visualization_tab` | Swap source, copy, columns, controls, coverage expander |
| `gap_ui_guide.md` | One-line sync: Visualization = transferable × Fangxin |
| Tests (`test_gap_opportunity.py` + UI/helper as needed) | Main table empty does not fall back to combo; assembled rows include bridge columns |

## Testing

| Case | Expect |
|------|--------|
| Assemble from transferable rows | Columns include `bridge_task`, `bridge_mode`, `opportunity_score` |
| Sort | Higher `opportunity_score` / Debate source preferred |
| Empty transferable + focus set | Info about Task bridge; main table not filled from combo gap |
| Coverage expander | Can still show combo gaps when opened; selecting them does not change Fangxin selection |
| Debate overlay | Matched titles mark Debate; unmatched listed |

## Success criteria

1. Visualization primary opportunity signal is no longer cartesian combo holes.
2. With bridge candidates: select row → Fangxin detail works.
3. Without candidates: clear explanation; no false-gap main table.

## Risks

| Risk | Mitigation |
|------|------------|
| Task 稀 → 常空表 | Caption + weekly hotspot alignment; no cartesian fallback |
| Weekly vs viz window params drift | Share `_load_weekly_hotspot_payload` or same defaults (`HOTSPOT_WINDOW_DAYS`) |
| Debate titles hard to match new columns | Keep method/disease matching; unmatched list unchanged |
