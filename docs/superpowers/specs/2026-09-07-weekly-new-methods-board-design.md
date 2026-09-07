# Design: Weekly “本周新方法” Board

**Date:** 2026-09-07  
**Status:** Approved (pending implementation)  
**Depends on:** Weekly hotspot (`analysis/weekly_hotspot.py`), method maturity (`analysis/method_maturity.py`), Gap UI weekly tab (`gap_ui.py`)

## Problem

用户把侧栏「最少近窗篇数」调到 1，仍难扫到本周真正新的方法。根因有两层：

1. **数据覆盖**（近窗大量未抽取）不在本设计范围内。
2. **榜单逻辑**：方法主榜先按 `emerging_score`（含 `log1p(recent_cnt)`）排序并截 `HOTSPOT_TOP_N`，再滤掉 `established`。低 count 的 `nascent` 方法容易被挤掉；主榜语义仍是「热度新苗头」，不是「本周新方法清单」。

## Goals

1. 在「每周热点 → 方法」顶部单独展示 **本周新方法** 清单，方便扫新。
2. 「新」= 现有成熟度 `nascent`（非黑名单，且全库 `corpus_paper_cnt ≤ 2`）。
3. 该模块 **固定 `min_recent=1`**，**不受**侧栏最少近窗篇数与 `HOTSPOT_TOP_N` 截断。
4. 现有「新苗头」主榜 /「本周活跃」折叠区逻辑与语义不变。

## Non-goals

- 不修近窗抽取覆盖率（pipeline / extract）。
- 不改 `emerging_score` 公式，不改 `HOTSPOT_TOP_N` 默认值。
- 不改可迁移机会、方法类别、疾病/组合榜。
- 不引入新的成熟度定义（不用 prior_cnt=0 或「全库首现」替代 nascent）。
- 不把本模块写入周快照对比的主环比逻辑（可选后续；v1 可不 persist 独立 board）。

## Approach (chosen)

**方案 1 — 独立计算 `new_methods` 字段**（否决：从宽池拆榜改截断顺序；否决：仅 UI 从 `active_methods` 过滤——仍受 Top-N）。

## Data contract

### Payload field

`compute_weekly_hotspots(...)` 增加：

```text
new_methods: list[dict]
```

每行字段与方法实体行对齐（至少）：

| Field | Notes |
|-------|--------|
| `name` | canonical method |
| `type` | `"Method"` |
| `recent_cnt` / `prior_cnt` / `velocity` / `emerging_score` | 与现有 enrichment 一致 |
| `avg_cite` / `avg_cpy` / `avg_if` | 同现有 |
| `corpus_paper_cnt` / `method_maturity` | 成熟度标注后；本列表恒为 `nascent` |
| `method_role` | 与主榜同样 annotate（便于扫角色，可不按角色分区） |
| `alias_count` / `aliases` | 若方法聚合路径已有则保留 |

### Selection rules

1. 在同一 `window_days` / `prior_days` 下，调用方法聚合路径，**强制 `min_recent=1`**。
2. `limit`：不按 `HOTSPOT_TOP_N` 截断。实现可用防护上限 `HOTSPOT_NEW_METHODS_MAX`（默认 **500**），仅防异常膨胀；正常近窗不应触达。
3. `annotate_method_rows` + `annotate_method_role`（与主榜一致）。
4. 保留 `method_maturity == "nascent"`；排除 `established` 与 `emerging`。
5. 排序：`corpus_paper_cnt` 升序，再 `emerging_score` 降序，再 `name` 升序（稳定）。

与 `emerging_methods` 关系：可重叠（nascent 且进了热度 Top-N 的仍可同时出现在两边）；本模块以完整性优先，主榜以热度优先。

### Independence from sidebar

侧栏 `SHARED_MIN_RECENT_KEY` **不**传入本模块过滤。Caption 写明：固定最少近窗篇数 = 1，与侧栏无关。

## UI

位置：`render_weekly_hotspot_tab` → tab「方法」**顶部**。

1. Caption：本周新方法 = `nascent`（全库 ≤2 篇）；固定 min_recent=1；未做热度 Top-N 截断。
2. 表格：`safe_table(pd.DataFrame(new_methods))`（不必按角色分区；角色列可保留）。
3. 空列表：`st.info` 说明本窗暂无 nascent 方法（或未抽取导致池空）。
4. 其下保持现有：按角色分区的「新苗头」+ expander「本周活跃（含成熟常用方法）」。

Markdown 报告（v1）：在 Emerging Methods 前增加短节 `## New Methods This Window (本周新方法)`，列出名称（可带 `corpus_paper_cnt`）；空则写 “None”。

## Implementation sketch

| Area | Change |
|------|--------|
| `analysis/weekly_hotspot.py` | 新增 `_compute_new_methods(...)` 或等价；`compute_weekly_hotspots` 写入 `new_methods`；报告生成引用该字段 |
| `gap_ui.py` | 方法 tab 顶部渲染 |
| `config.py` | 新增 `HOTSPOT_NEW_METHODS_MAX`（env，默认 500） |
| tests | 见下 |

性能：可复用一次宽池聚合再 filter（实现细节），对外契约仍是独立字段；避免改变现有 `compute_emerging_entities(..., limit=HOTSPOT_TOP_N)` 的默认行为。

## Testing

1. **nascent 入列**：近窗 1 篇、全库 ≤2 的方法出现在 `new_methods`。
2. **established 不入列**：黑名单或 corpus≥阈值 的方法不在 `new_methods`。
3. **emerging 不入列**：corpus∈[3,9] 的方法不在 `new_methods`。
4. **不受 Top-N / 侧栏 min_recent**：`HOTSPOT_TOP_N=2` 且调用 `min_recent=2` 时，仅近窗 1 篇的 nascent 仍在 `new_methods`；可同时验证它可能不在 `emerging_methods`。
5. **排序**：corpus_paper_cnt 更小的排前。

## Success criteria

- 用户调高侧栏最少篇数时，仍能在「本周新方法」看到近窗单篇 nascent 方法。
- 新苗头热度榜行为与改前一致（回归现有 maturity / synonym 测试）。
