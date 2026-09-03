# Public Dataset Feasibility (V-03)

**日期:** 2026-07-22  
**范围:** extract 入库的公开数据集 → 并行可行性通道 → idea-pipeline / gap_ui / Research Proposal

## 目标

与方信 LIS **V-01** 并行，新增确定性的 **公开数据集可行性（V-03）**：按 focus/gap 经相关论文选出 `access_class=public` 的数据集，产出结构化报告、落库，并供 Research Proposal 强制参考。  
**不**并入方信 `feasibility_score`。

## 核定决策

| 项 | 选择 |
|----|------|
| 算法 | 确定性 KG 规则（无 LLM 打分；无病种→公开集策展表） |
| 入口 | idea-pipeline Stage 2 自动+落库；gap_ui「数据可行性」V-03；Proposal 必调工具 |
| 选集 | 论文中介（`resolve_v03_topic_pmids`：仅标题 / `TARGETS_DISEASE`），再经 focus-primary 过滤；**不**用数据集名匹配 focus |
| 与方信 | 并行通道；方信仍为主队列规则 |

## 数据流

```
extract (access_class) → entities / USES_DATASET
focus/gap → resolve_v03_topic_pmids (title|TARGETS_DISEASE)
→ filter_focus_primary_pmids（排除跨部位多病种论文）
→ V-03 public_dataset_assess → public_dataset_assessments
→ gap_ui V-03 / idea-pipeline Stage 2 / idea_agent Proposal
```

### Focus-primary 规则

一篇论文可为 V-03 贡献 `USES_DATASET`，当且仅当：

1. **标题**命中 focus 概念短语；或
2. `TARGETS_DISEASE` 含 focus（或同部位概念），且**不**含与 focus **部位不相交**的其他疾病概念（例如 breast + colon 对肠癌 focus → 不贡献，避免 BreakHis 等异部位基准混入）。

数据集名仍可不含 focus（如乳腺癌 focus 下的 Camelyon17）。

## 报告 JSON

`public_dataset_assess(keyword)` 返回：

- `public_coverage_score` (0–1), `status` (`OK`|`WEAK`|`NONE`)
- `match_strategy`, `topic_paper_cnt`
- `recommended_public[]`: dataset, used_by_papers, alias_hit, example_pmids
- `other_datasets[]`: private/unknown
- `gaps[]`, `roles_for_proposal`

### 状态规则

- **OK**: ≥1 public，且（任一条 `alias_hit` **或** `used_by_papers >= V03_OK_MIN_PAPERS`）
- **WEAK**: 有 public 但不满足 OK；或无 public 但有 unknown 候选
- **NONE**: 无 Dataset / 仅 private / 无 topic 论文

### 配置（`config.py`）

- `V03_OK_MIN_PAPERS`（默认 3）
- `V03_SCORE_ALIAS_BONUS`, `V03_SCORE_PER_PUBLIC`, `V03_SCORE_COVERAGE_CAP`
- `V03_EXAMPLE_PMIDS`

## 模块

| 文件 | 职责 |
|------|------|
| `analysis/public_dataset_feasibility.py` | 查询 + 打分 |
| `analysis/feasibility_tools.py` | 工具 `public_dataset_assess` |
| `db/schema.py` | 表 `public_dataset_assessments` |
| `pipeline.py` | Stage 2 / `assess_gap_feasibility` 内跑 V-03 |
| `idea_agent.py` | 必调；难度用 `recommended_public` |
| `gap_ui.py` | V-03 子页 + 快速核查展示 |

## 明确不做

- 历史 access_class 回填脚本
- LLM 解读 V-03
- 统一方信+公开总可行性分
- 病种→公开集策展表
