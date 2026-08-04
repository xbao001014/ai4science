# Design: Method Role Split for Weekly Hotspot Display

**Date:** 2026-08-04  
**Status:** Approved  
**Depends on:** Weekly hotspot (`analysis/weekly_hotspot.py`), method maturity (`analysis/method_maturity.py`), method synonyms (`analysis/method_synonyms.py`), Gap UI (`gap_ui.py`)

## Problem

抽取政策（Method = 命名骨干 **或** 贡献级模块）故意保留两类实体。周热点「方法」主榜经同义词归并与成熟度闸门后仍混排，研究者难以按角色筛选「基座/骨干」与「聚合器/贡献模块」。

根因是展示层缺少 `method_role`，不是抽取错误，也不应靠再收紧抽取来解决扫榜问题。

## Goals

1. 为方法相关行增加 `method_role`：`backbone` | `aggregator` | `unknown`。
2. 「每周热点 → 方法」Tab 按三类分开展示（空类可隐藏）。
3. **不改** `emerging_score`、成熟度闸门、同义词归并、Top-N 切分与可迁移评分。
4. 分类为可维护运行时规则 + 小词典；可单测。

## Non-goals

- 不改抽取 prompt；不强制重抽；不在 DB 实体表写死角色。
- 不拆独立 Top-N 榜（基座榜 / 聚合器榜）；不按角色改排序权重。
- 不做第三档 `framework`；不做 LLM 分类。
- 不把 `method_role` 持久化进 `weekly_hotspot_snapshots` schema（v1）。
- 热门组合 / 跨病种可借鉴：不强拆 UI 分段（仅附带字段）。

## Approach (chosen)

**方案 1 — 规则模块 + 方法 Tab 分子表**

否决：

- 方案 2（单表 + 筛选器）：实现更轻，但「分类别一眼对比」弱。
- 方案 3（快照持久化角色）：对当下扫榜帮助有限，schema 更重。

分类策略：**运行时规则（词典优先 + 保守启发式）**；未命中 → `unknown`。

## Role definitions

| `method_role` | 含义 | 典型例子 |
|---------------|------|----------|
| `backbone` | 特征提取 / 预训练骨干或命名视觉编码器 | ResNet-50、ViT、UNI、CONCH、CTransPath |
| `aggregator` | 实例/切片级聚合、注意力池化、MIL head、融合模块等贡献级组件 | attention MIL、cross-attention fusion、dual-stream MIL |
| `unknown` | 规则未命中或不便硬分 | 部分整套框架名、工具名、含糊复合名 |

CLAM / TransMIL 等整套框架：若既不在骨干词典、名称又无明显聚合线索，v1 进 `unknown`，或通过词典显式标为其中一档。v1 **不**发明第三档。

## Classification module

**File:** `fulltext_workflow/analysis/method_role.py`（纯函数，风格对齐 `method_maturity.py`）

### API

- `classify_method_role(name: str) -> Literal["backbone", "aggregator", "unknown"]`
- `annotate_method_role(rows: list[dict], *, name_key: str = "name") -> list[dict]`  
  就地写入 `method_role`；返回同一 list。

输入名先经 `resolve_method_canonical`（与周热点一致），再分类。

### Decision order (first match wins)

1. **显式词典（最高优先）**
   - `_BACKBONE_ALIASES`：归一化后整串精确匹配。
   - `_AGGREGATOR_ALIASES`：归一化后整串精确匹配。
   - 若同一名误入两表：以 **聚合器表优先**（贡献级命名更特异）；模块注释写明该约定。
2. **聚合器启发式（保守）** → `aggregator`  
   例：`aggregator`；词边界 `mil`；`attention pool`；method 语境下的 `pooling`；`fusion module`；`bag.?level`；`instance.?aggregation`。  
   **避免**过宽的裸 `attention`（减少误伤 Attention U-Net 类骨干）。
3. **基座启发式** → `backbone`  
   例：`resnet`、`vit`、`swin`、`efficientnet`、`densenet`；后缀线索 `encoder` / `backbone`；常见病理基础模型别名。  
   避免「凡含 cnn 即骨干」等过宽子串（与成熟度黑名单策略一致）。
4. 否则 → `unknown`

### Maintenance

线上分错时：优先补词典别名；启发式仅在模式稳定后扩展。

## Weekly hotspot wiring

在 `compute_weekly_hotspots` 中，于成熟度 `annotate_method_rows` **之后**调用 `annotate_method_role`：

- **必须：** `emerging_methods`、`active_methods`
- **建议（v1 附带列）：** `hot_combos`、`hot_combos_by_method`、`emerging_gap_opportunities`（`name_key="method"`）

不改任何过滤、排序或分数字段。

## UI (`gap_ui.render_weekly_hotspot_tab`)

### 方法 Tab

1. 保留现有 caption（新苗头 / 同义词归并 / `min_recent`）。
2. 增加说明：方法已按角色分为基座（backbone）/ 聚合器（aggregator）/ 未分类；分类为运行时规则，**不影响热度分**。
3. 将 `emerging_methods` 按 `method_role` 拆成最多三段 `st.subheader` + 表：
   - 基座 / 骨干
   - 聚合器 / 贡献模块
   - 未分类（仅当有行时展示）
4. 每段内保持原列表相对顺序（原 `emerging_score` 序），段内不另定排序规则。
5. 折叠区「本周活跃（含成熟常用方法）」同样按三角色分段（避免成熟骨干与聚合器再混排）。

### 其他 Tab（v1）

热门组合 / 跨病种可借鉴：payload 含 `method_role` 时表格多一列即可，不强制拆段。

### 报告文案（可选）

热点文本报告列举方法时可按角色分组或旁注角色；非 v1 阻塞项。

## Testing / acceptance

1. **单元：** `classify_method_role` 覆盖骨干、聚合器、unknown、canonical 别名、易误伤名（如含 attention 的骨干）。
2. **集成：** `compute_weekly_hotspots` 方法行含 `method_role`；established 过滤与分数行为与改前一致（同窗口同数据）。
3. **UI：** 方法 Tab 可见分类小标题；展示分层不改变榜单人数与分数。

## Risks

- `unknown` 偏多：靠补词典消化，可接受。
- 启发式误伤：靠保守模式 + 单测回归；冲突时词典可覆盖。

## Out of scope follow-ups

- 第三档 `framework` 或抽取时 `method_role`。
- 按角色拆独立 Top-N / 改可迁移池过滤。
- Snapshot 持久化 `method_role` 以支持按角色周环比。
