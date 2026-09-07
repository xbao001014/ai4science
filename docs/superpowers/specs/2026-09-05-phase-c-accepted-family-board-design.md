# Phase C Design: Accepted Method-Family Board

**Date:** 2026-09-05  
**Status:** C0-A/C0-B implemented; C0-C coverage review queue generated; release remains blocked  
**Depends on:** Phase B full shadow backfill, pinned 400-row expert gold set

## 1. Outcome

Phase C 将通过质量门槛的 `manual | rule | embedding` 方法家族标签发布为一个不可变 release，
并在“每周热点”的方法 Tab 默认展示 family 聚合榜，支持 family → canonical method → PMID 下钻。

核心约束：

- Phase B 的 `review` 记录永远不能被周热点读取；
- family 计数按 distinct PMID union，不能把成员方法的计数相加；
- canonical method、method family、method role 三层继续独立；
- UI 请求期间不调用 Embedding API；
- taxonomy 变更不能改写历史周快照；
- 发布失败或覆盖率不足时立即回退到现有平铺方法榜。

## 2. Preconditions

Phase C 实施可以先开发，但 activation 必须同时满足：

1. Phase B active Method 向量缓存覆盖率 ≥99%；
2. 400 条分层 gold CSV 已由专家确认并通过兼容性格式校验；
3. holdout primary precision ≥90%，目标 ≥95%；
4. paper-weighted family coverage ≥80%；
5. version collision 为 0；
6. review/manual/rule 冲突均有可追溯决策；
7. 所有 accepted 成员冻结到 release 后，才允许启用 UI feature flag。

Phase B cache coverage 和 Gold 输入门槛已经满足。precision、coverage、冲突审计与 immutable release
门槛仍未验证，所以本设计仍不授权直接把 shadow 结果提升为 accepted。

## Gold baseline audit

权威输入固定为：

```text
fulltext_workflow/output/method_family_gold_method-family-v1.csv
SHA-256: 508ebebb1008990ca75b833d8e0c26dbbc4422201bbedbdfa31469fa0507a87c
bytes: 75014
```

验收结果：

- 400 行、400 个唯一 `method_entity_id`，无重复 ID、非法 family、重复 secondary 或 primary/secondary
  重叠；
- 366 行填写了 13 类 primary；34 行 primary 为空但 `review_notes` 以 `[reject]` 开头；
- 这 34 行按本 Gold 的明确语义规范化为 `unknown`，因此 effective labeled rows 为 400；
- 不存在“primary 为空且没有 `[reject]`”的未完成行；
- secondary 只有 12 行、12 个标签，数量不足以校准 embedding multi-label threshold；
- 部分 `[reject]` 后的中文备注存在乱码。导入器只依赖稳定的 `[reject]` 前缀，不解析乱码正文，并保留
  原始文件 hash 供审计。

Primary/unknown 分布：

| Label | Gold rows |
|---|---:|
| cnn | 114 |
| classical_statistics | 51 |
| mil | 38 |
| foundation_model | 29 |
| transformer | 29 |
| bioinformatics_omics | 24 |
| unknown (`[reject]`) | 34 |
| image_processing | 18 |
| other_tooling | 14 |
| multimodal_fusion | 12 |
| explainability | 11 |
| representation_learning | 11 |
| generative_model | 10 |
| graph_neural_network | 5 |

当前 shadow top-1 在 366 个 known Gold 上命中 247 个，accuracy 为 67.49%；top-3 命中 287 个，
recall 为 78.42%。这说明 embedding 候选可用于排序和校准，但不能直接全量发布。

主要偏差是把其他 family 吸入宽泛类别：`image_processing` 的 top-1 precision 为 19.4%，
`multimodal_fusion` 为 23.5%，`mil` 为 50.8%，`generative_model` 为 60.0%。相对稳定的类别包括
`cnn`、`explainability`、`foundation_model`、`graph_neural_network` 和
`representation_learning`，但后四类样本量较小，仍需 holdout 约束。

## 3. Label precedence and promotion

决策优先级固定为：

```text
manual label
  > high-precision deterministic rule
  > calibrated embedding candidate
  > unknown
```

### Manual

- `gold_primary` 必须是 13 类稳定 family ID 之一；
- `gold_secondary` 使用 `|` 分隔，可为空、不可重复 primary；
- 对当前已固定 Gold，空 `gold_primary` + `[reject]` note 规范化为 `unknown`；
- 其他空 `gold_primary` 仍表示“尚未标注”，validator 必须拒绝；未来 Gold 应直接填写 `unknown`，
  不再生成新的 legacy `[reject]` 空值；
- 导入时保留 reviewer、时间和原始 CSV SHA-256。

### Rule

- 只纳入高精度、可单元测试的名称模式或严格 allowlist；
- C0-B 规则只产生 primary；当前 12 条 secondary Gold 不足以校准自动 secondary，所有 secondary
  暂时只接受 manual；
- rule 与 manual 冲突时 manual 胜出，冲突进入审计；
- 不用宽泛词 `model`、`AI`、`deep learning` 直接生成 family。
- 现有 Gold 上，CNN、传统统计、可解释性、基础模型、MIL、工具、表征学习和 Transformer 的严格
  单一名称 cue 可作为候选 rule，但必须只在 calibration split 固化并在 holdout 验证；
- 从 rule 中移除或收紧宽泛 cue：`qPCR/q-pcr`、`generative`、裸 `autoencoder`、裸 `stain`、
  裸 `multimodal` 和裸 `vision-language`。例如 RT-qPCR 是湿实验检测，virtual staining 在本 Gold 中
  属于 generative model，VLM 可能属于 foundation model。

### Embedding

- 仅使用 Phase B top-k 候选、原始 cosine、hybrid ranking score、margin 和 context quality；
- calibration set 用于选阈值，holdout 只做最终验收；
- 首版使用全局 primary threshold；某 family 的 gold 样本 ≥20 才允许 family-specific threshold；
- secondary family 使用独立、更严格的 multi-label 阈值；
- 未达到阈值继续 unknown，不追求 100% coverage。
- C0/C1 不允许 embedding 自动产生 secondary；12 个 Gold secondary 只支持 manual 或严格组合规则，
  例如 `TransMIL → mil + transformer`。积累足够 multi-label Gold 后再启用 secondary calibration。

## 4. Calibration protocol

400 条 effective labels 按 primary/unknown、method role 和频次层保持分层，确定性拆分为 70%
calibration / 30% holdout，目标为 280/120；同一 canonical method 及其 alias group 只能出现在一侧。
split seed 从 Gold SHA-256 派生，拆分 manifest 一经生成不可修改。阈值、rule 和候选 family policy
冻结前不得查看 holdout 结果；最终 embedding allowlist 只根据已冻结 policy 的 holdout pass/fail 产生。

当前类别不平衡明显：7 个 family 少于 20 条 Gold，`graph_neural_network` 仅 5 条。因此 C0 默认使用
全局 embedding threshold；只有 calibration positives ≥20 且 holdout positives ≥10 的 family 才允许
family-specific threshold。按当前规模，预计仅 CNN、传统统计和 MIL 有机会满足该条件，其余类别沿用
全局阈值或只接受 manual/rule。

阈值搜索目标：

```text
subject to holdout primary precision >= 0.90
maximize paper-weighted recall
tie-break by higher precision, then higher margin threshold
```

在全量 Gold 上做的非验收性探查显示，`ranking_score >= 0.54` 且 `margin >= 0.04` 时可接受 221/400，
entity precision 为 91.4%，paper-weighted precision 为 97.9%。该结果使用了完整 Gold，只能证明阈值
方案有可行性，不能作为正式阈值；正式参数必须只由 calibration split 产生，再仅一次运行 holdout。

全局 precision 会掩盖单类错误，所以 embedding promotion 使用 deny-by-default family gate：

- `image_processing`、`multimodal_fusion`、`generative_model` 初始禁止 embedding-only promotion；
- 其他 family 只有在 calibration 和 holdout 都通过最小支持数与 precision 门槛后才加入 embedding
  allowlist；
- 某 family 在 calibration 或 holdout 的自动接受数少于 10 时，不声称该 family 已校准，只允许
  manual/rule 发布；
- 整体 holdout primary precision 必须 ≥90%，paper-weighted precision 目标 ≥95%；
- 任何 family 在 holdout 有 ≥10 个自动接受样本时，其 precision 也必须 ≥90%，否则从 embedding
  allowlist 移除并重新计算 coverage。

报告至少包含：

- primary precision/recall/F1；
- multi-label micro/macro F1；
- 每 family precision、support 和 confusion；
- entity/relation/paper 三种 coverage；
- 高频/长尾、opaque/non-opaque、known/unknown role 分层指标；
- rule/embedding 冲突率；
- 自动拒绝/unknown 比率；
- calibration 与 holdout 指标差距。

若 holdout precision 不达标，Phase C 停留在 preview，不得通过降低门槛强行上线。

### Gold and calibration artifacts

Gold 和 split 不能只存在于一次性脚本内。C0 新增不可变审计记录：

```text
method_family_gold_sets
  gold_set_id, taxonomy_version, file_sha256, row_count,
  known_count, unknown_count, secondary_count, normalization_policy,
  reviewer, imported_at

method_family_gold_labels
  gold_set_id, method_entity_id, raw_primary, normalized_primary,
  secondary_json, review_notes, source_row, split, split_group

method_family_calibrations
  calibration_id, gold_set_id, split_manifest_sha256, ruleset_version,
  thresholds_json, embedding_family_allowlist_json, metrics_json,
  status, created_at

method_family_rulesets
  ruleset_id, gold_set_id, ruleset_version, rules_sha256,
  rules_json, eligible_rule_ids_json, metrics_json, status

method_family_policy_previews
  preview_id, gold_set_id, calibration_id, ruleset_id,
  graph_snapshot_sha256, metrics_json, status

method_family_review_queues
  queue_id, gold_set_id, calibration_id, ruleset_id,
  graph_snapshot_sha256, target_paper_coverage, queue_sha256,
  selection_json, metrics_json

method_family_gold_extensions / method_family_gold_extension_labels
  extension_id, queue_id, parent_gold_set_id, file_sha256,
  label_snapshot_sha256, rank range, normalized labels, metrics_json
```

`method_family_gold_sets` 以文件 SHA-256 去重；同一 hash 重复导入必须幂等。`split` 只能由尚未拆分的
Gold set 一次性生成，后续不得修改。calibration report 同时写 JSON artifact 和数据库摘要，release 通过
`calibration_id` 引用，避免只凭人工复制阈值构建版本。

### C0-A verification record

已实现并对权威 Gold 执行：

```text
gold_set_id: gold-method-family-v1-508ebebb1008990c
split_manifest_sha256: ec8c3b3519cf486e294ca2538df92565bbcec226ed0da0eceb55c88234775a5f
calibration_id: cal-b9b3ec1c1122918f16827424
calibration_version: embedding-threshold-v2
split: 280 calibration / 120 holdout
selected threshold: ranking_score >= 0.52 and margin >= 0.01
```

全局候选在 holdout 上接受 65 条、正确 59 条：entity precision 90.77%，paper-weighted precision
97.995%。逐类同时要求 calibration/holdout 至少各 10 个自动接受样本且 precision 均 ≥90% 后，首版
embedding allowlist 只有 `cnn`：holdout 接受 20/20，precision 100%。

关键拒绝原因：

- `classical_statistics`：calibration precision 89.66%，未达门槛；
- `mil`：calibration/holdout precision 分别为 66.67%/76.92%；
- `transformer`：holdout 自动接受仅 4 条，证据不足；
- 其余非预先 blocked family 也因 calibration 或 holdout 支持数不足而不自动发布；
- `generative_model`、`image_processing`、`multimodal_fusion` 继续保持 embedding-only block。

因此 C0-A 的阈值技术门槛通过，但 `release_build_eligible=false`。C0-B 继续验证 strict rules 与全量
entity/relation/paper coverage；在所有门槛通过前 `accepted` 和 active release 均保持为空。

### C0-B verification record

已实现不可变严格规则集和全库分层策略预览：

```text
ruleset_id: rules-4444805f9d592b1a7610271b
ruleset_version: method-family-rules-v2
rules_sha256: e931d7710eea74e609fde92d40596a99547128043c67cd1eddf8d804bf9b538e
preview_id: preview-3e44f15afece4ba20259e083
graph_snapshot_sha256: 6b34fda7094e00b10b2bc5abb711c7127d022a26b775475d5966577b4fad2a8b
```

规则只在 calibration 选择：全部候选命中 125/125；按每条规则至少 2 个 calibration 命中且 precision
≥95% 后，13/17 条规则进入 allowlist。holdout 最终命中 49 条、正确 48 条，entity precision
97.96%、paper-weighted precision 99.86%，unknown false accept 为 0。v2 明确规定：若高优先级规则因
支持不足未获准，则阻断低优先级回退，避免 `multimodal transformer` 被降级为普通 Transformer。

全库 preview 固定优先级为 `Gold > strict rule > calibrated CNN embedding > unknown`：10,619 个 active
Method 中覆盖 2,461 个（23.18%），14,875 条 active APPLIES_METHOD 中覆盖 5,722 条（38.47%），
5,724 篇含方法论文中覆盖 2,941 篇（51.38%）。来源分别为 Gold 366、规则 1,847、embedding 248。
由于 paper coverage 未达到 80%，状态为 `coverage_rejected`，`release_build_eligible=false`；未写入任何
`accepted`，未创建 active release，每周热点必须继续回退到现有平铺方法榜。

### C0-C coverage recovery queue

为避免通过放宽阈值追求覆盖率，新增按未覆盖 PMID 边际贡献排序的确定性人工标注队列：

```text
queue_id: queue-70bf2cf4b793f4ff8e720d42
queue_version: method-family-coverage-queue-v1
queue_sha256: fc82e47c7c093c7e946b7deaf16d023bdc0c1257e895f0608de2390c02a53deb
selected_rows: 1,434
base paper coverage: 51.38%
projected paper coverage if every row gets a usable primary: 80.01%
```

理论里程碑为：前 100 条 56.03%、前 200 条 58.46%、前 400 条 61.95%、前 800 条 68.94%、前
1,000 条 72.43%。该队列针对人工覆盖扩充进行了有偏抽样，不能作为下一版规则或 embedding 的独立
holdout；且实际标成 `unknown` 的行不会贡献覆盖，因此 80.01% 只是上限，不是上线承诺。

首批 rank 1–200 已完成并不可变导入：

```text
extension_id: goldext-15205be714d0fed5851a0cd8
source file SHA-256: be65e676493243133f9f9f3c271c925095a1b77595cf76c7389b6c2fe05573c9
label snapshot SHA-256: 5fdb0d4cf632df6ee2b5abc12b504d208bbea0a4e9c53bc301821aec0843be3b
labels: 143 known / 57 unknown / 12 secondary
actual paper coverage: 51.38% → 56.24% (+278 papers)
```

该批为覆盖优先有偏样本。Embedding top-1 在 143 个 known 中仅匹配 47.55%，top-3 recall 为
72.03%，不得据此放宽 embedding family allowlist。下一批队列必须以 56.24% 的实际覆盖集合重新执行
边际 PMID 排序，不能直接沿用旧母表第 201–400 行的理论顺序。

## 5. Immutable release model

不让 weekly 直接读取可变的 `method_family_assignments`。新增不可变发布层：

### `method_family_releases`

```sql
release_id              TEXT PRIMARY KEY
taxonomy_version        TEXT NOT NULL
provider                TEXT NOT NULL
model                   TEXT NOT NULL
dimensions              INTEGER NOT NULL
input_format_version    TEXT NOT NULL
gold_file_sha256        TEXT NOT NULL
gold_set_id             TEXT NOT NULL
calibration_id          TEXT NOT NULL
ruleset_version         TEXT NOT NULL
thresholds_json         TEXT NOT NULL
embedding_family_allowlist_json TEXT NOT NULL
secondary_policy        TEXT NOT NULL
metrics_json            TEXT NOT NULL
member_count            INTEGER NOT NULL
status                  TEXT NOT NULL  -- validated | rejected
created_at              TIMESTAMP
```

release 一旦创建不可修改；阈值或成员变化必须生成新 release。

### `method_family_release_members`

```sql
release_id              TEXT REFERENCES method_family_releases
method_entity_id        INTEGER REFERENCES entities
family_id               TEXT NOT NULL
is_primary              INTEGER NOT NULL
source                  TEXT NOT NULL  -- manual | rule | embedding
similarity              REAL
ranking_score           REAL
margin                  REAL
input_sha256            TEXT NOT NULL
PRIMARY KEY (release_id, method_entity_id, family_id)
```

只冻结通过 promotion 的 accepted 成员；不复制 review/rejected。

### `method_family_release_pointer`

单行表保存当前 active `release_id`。activation/rollback 只在一个事务中更新 pointer，不修改 release
或历史成员，因此回滚为 O(1)。

### `method_family_review_events`

append-only 保存人工导入、规则冲突、embedding promote/reject、release build 等事件。不得把人工
覆盖直接写成无法追踪的 assignment update。

## 6. Weekly aggregation contract

family board 仅 join 当前 release members：

```text
active APPLIES_METHOD relation
  → canonical Method entity
  → current immutable release member
  → family
  → paper with eligible pub_date precision
```

每个 family：

```sql
recent_cnt = COUNT(DISTINCT CASE WHEN paper in recent window THEN PMID END)
prior_cnt  = COUNT(DISTINCT CASE WHEN paper in prior window  THEN PMID END)
```

禁止以下算法：

```text
family recent_cnt = SUM(member_method.recent_cnt)  -- wrong
```

同一 PMID 使用多个同 family 方法时只计一次；多标签方法可以分别进入多个 family，这是预期行为。

family 行字段：

- `family_id`, `display_name_zh/en`；
- `recent_cnt`, `prior_cnt`, `velocity`, `emerging_score`；
- `member_method_cnt`, `recent_method_cnt`；
- `top_methods`：按 family 内 distinct recent PMID 排序；
- `top_pmids`；
- `source_mix`：manual/rule/embedding；
- `coverage` 和 `release_id`。

family 下钻的 method 行继续展示 canonical name、method_role、成熟度、recent/prior、来源、confidence、
top PMIDs；role 只用于列和筛选，不影响 family 热度。

## 7. Coverage and safe fallback

payload 同时返回三个覆盖口径：

```text
entity_coverage   = released active Methods / active Methods
relation_coverage = released active APPLIES_METHOD edges / active edges
paper_coverage    = papers with >=1 released Method / papers with Method
```

配置：

```ini
METHOD_FAMILY_BOARD_ENABLED=0
METHOD_FAMILY_MIN_PAPER_COVERAGE=0.80
METHOD_FAMILY_MIN_HOLDOUT_PRECISION=0.90
METHOD_FAMILY_DEFAULT_VIEW=family
```

只有 flag 开启、active release 存在、release validated、实时 paper coverage 达标时显示 family 默认榜。
否则：

- 现有方法榜继续工作；
- payload 返回 `method_family_available=false` 和机器可读 reason；
- UI 显示简短说明，不显示部分分类造成的误导性排名；
- hotspot report、brief 和 weekly job 不失败。

## 8. Snapshot versioning

现有 `weekly_hotspot_snapshots` 以 week 为覆盖写入，不适合保存多 taxonomy release。新增独立表，避免
危险的原表重建：

### `weekly_method_family_snapshots`

主键 `(week_id, release_id, family_id)`，保存 family 指标、top PMIDs 和 source/coverage metadata。

### `weekly_method_family_members`

主键 `(week_id, release_id, family_id, method_entity_id)`，冻结当周下钻成员、计数、排名和 assignment
来源。

WoW 只比较相同 `release_id`。release 切换后的第一周显示“分类版本变更，无可比基线”，避免把分类变化
误报为热点升降。

## 9. Payload and report changes

`compute_weekly_hotspots()` 新增：

```text
method_family_available
method_family_unavailable_reason
method_family_release
method_family_coverage
method_family_boards
method_family_members
```

现有字段 `emerging_methods`、`active_methods`、`hot_combos*` 保持不变，兼容 LLM brief、Gap UI 和外部
调用者。Markdown 报告新增 `Method Families` 段，但保留 `Emerging Methods` 段。

LLM brief 只接收 release ID、coverage、family 汇总和已发布成员，不接收 review 候选。

## 10. UI behavior

方法 Tab：

1. family 可用时默认显示 family 卡片/表格；
2. 点击或展开 family 查看 top canonical methods；
3. 行内展示角色、成熟度、标签来源和 confidence；
4. 提供 `Family 视图 | 方法平铺 | 按角色` 三种切换；
5. 页面顶部显示 release ID、paper coverage 和“仅展示已验证分类”；
6. review/unknown 只显示覆盖数量，不显示具体候选，避免用户误认为已确认；
7. family 不可用时自动显示现有 `_render_methods_by_role`。

页面缓存 key 必须包含 active release ID；切换/回滚 release 后无需等待 300 秒 TTL。

## 11. Commands

```powershell
# Validate the pinned expert labels; no release mutation
& $py main.py method-family-gold-validate `
  --input output/method_family_gold_method-family-v1.csv `
  --expected-sha256 508ebebb1008990ca75b833d8e0c26dbbc4422201bbedbdfa31469fa0507a87c

# Idempotent immutable import and deterministic split manifest
& $py main.py method-family-gold-import --input ... --reviewer expert-v1

# Produce calibration report only
& $py main.py method-family-calibrate --gold-set-id <gold-set-id> `
  --output output/method_family_calibration.json

# Freeze strict rules after calibration selection and one holdout evaluation
& $py main.py method-family-rules-evaluate --gold-set-id <gold-set-id> `
  --output output/method_family_rules.json

# Preview Gold > rules > calibrated embedding; never writes accepted
& $py main.py method-family-policy-preview --gold-set-id <gold-set-id> `
  --calibration-id <calibration-id> --ruleset-id <ruleset-id> `
  --output output/method_family_policy_preview.json

# Export a coverage-prioritized manual review queue
& $py main.py method-family-review-queue --gold-set-id <gold-set-id> `
  --calibration-id <calibration-id> --ruleset-id <ruleset-id> `
  --target-paper-coverage 0.80 --output output/method_family_review_queue.csv

# Import one completed rank range as immutable coverage Gold
& $py main.py method-family-gold-extension-import --input <annotated-queue.csv> `
  --queue-id <queue-id> --reviewer <reviewer> --rank-start 1 --rank-end 200

# Build immutable release; refuses failed gates
& $py main.py method-family-release build --calibration ...

# Preview family payload without changing UI
& $py main.py method-family-release preview --release-id <id>

# O(1) activation / rollback
& $py main.py method-family-release activate --release-id <id>
& $py main.py method-family-release rollback --release-id <previous-id>
```

activation 需要 `METHOD_FAMILY_BOARD_ENABLED=1`，build/calibrate 不需要。

## 12. Rollout

### C0 — calibration only

- 验证并导入固定 SHA-256 的 400 条专家 Gold；
- 将 34 个 legacy `[reject]` 规范化为 unknown，但不改写原 CSV；
- 生成并冻结 280/120 group-stratified split manifest；
- 在 calibration split 固化严格规则、排除项、embedding family allowlist 和阈值；
- 仅一次运行 holdout，输出 calibration/holdout、逐 family 和 paper-weighted 报告；
- secondary 仅保留 manual 标签，不做 rule/embedding 自动多标签；
- 不创建 active pointer。

### C1 — preview release

- 构建 immutable release；
- CLI/测试 payload 预览；
- 对比现有方法榜的 top PMID 和 distinct union；
- UI feature flag 仍关闭。

### C2 — visible family board

- 开启 feature flag；
- 方法 Tab 默认 family，保留平铺/role 视图；
- 保存 release-aware snapshots；
- 观察两个周周期后再考虑 Phase D incremental weekly。

## 13. Acceptance tests

1. `review`、`rejected`、`stale` assignment 永不进入 release/weekly payload；
2. manual > rule > embedding，冲突写 append-only event；
3. `TransMIL` 可属于 MIL + Transformer，role 仍为 aggregator；
4. `UNet`/`UNet++` 同 family、不同 canonical entity；
5. 同 PMID 同 family 多方法只计一次；
6. 多标签方法分别贡献多个 family，但每 family 内不重复 PMID；
7. family recent/prior 使用与现有榜相同 pub_date/date_precision 口径；
8. coverage 低于门槛自动 fallback，weekly 仍成功；
9. feature flag 关闭时 payload/报告与当前版本兼容；
10. release pointer 切换立即失效 UI cache；
11. release 切换后的首周不做跨 release WoW；
12. rollback 只更新 pointer，历史 release/snapshot 不变；
13. release 中不存在重复 method-family-version 成员；
14. gold holdout precision 未达门槛时 build/activate 都拒绝；
15. API/Embedding 全部离线时 family board仍可从 release 正常生成。
16. 当前 Gold 的 34 个 `[reject]` 被规范化为 unknown；空 primary 且无 `[reject]` 时校验失败；
17. Gold SHA-256 不匹配时 calibrate/release build 拒绝；
18. `image_processing`、`multimodal_fusion`、`generative_model` 不得通过 embedding-only 路径进入
    首个 release；
19. C0/C1 的 embedding secondary promotion 数量必须为 0。

## 14. Implementation boundary

Phase C 可以实现 schema、Gold validator/importer、calibration、release builder、聚合 SQL 和
feature-flagged UI。Phase B 全量 Batch 与 Gold 输入已完成，但在 holdout precision、paper coverage、
冲突审计和 preview release 验收完成前，必须保持 `METHOD_FAMILY_BOARD_ENABLED=0`。

这保证“代码准备好”和“分类质量足以上线”是两个独立状态，避免未经验证的 shadow 结果进入每周热点。
