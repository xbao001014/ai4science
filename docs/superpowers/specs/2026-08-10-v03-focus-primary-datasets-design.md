# V-03 Public Dataset Focus-Primary Filter

**日期:** 2026-08-10  
**范围:** 修复 Data Feasibility 公开数据集通道中异部位基准混入（如肠癌 focus 出现 BreakHis）

## 问题

V-03 经论文中介聚合 `access_class=public` 的 `USES_DATASET`。原 `resolve_topic_pmids` 会匹配**任意实体名**（含 Dataset/Task），且多病种论文（breast+colon）一旦挂上肠癌 Disease，其 BreakHis / Camelyon 等异部位公开集一并进入 `recommended_public`。

## 决策

仅改 V-03，**不**收紧全局 `resolve_topic_pmids`（文献检索 / idea agent 仍用原策略）。

| 项 | 选择 |
|----|------|
| 论文选集 | `resolve_v03_topic_pmids`：仅 title 或 `TARGETS_DISEASE` |
| 贡献过滤 | `is_focus_primary_paper` / `filter_focus_primary_pmids` |
| 数据集名 | 仍不要求含 focus（保留 Camelyon→breast 等） |
| 不做 | 病种→公开集策展表；改方信 V-01 分数 |

## 验收

- focus=`肠癌`：`recommended_public` 不含 BreakHis / BACH / Camelyon / PANDA
- 仍可出现 DigestPath、TCGA-CRC / COAD 等肠相关公开集
- `tests/test_public_dataset_feasibility.py` 全绿
