# Design: External Embedding API for Method Taxonomy and Weekly Hotspots

**Date:** 2026-09-05  
**Status:** Phase A complete; Phase B implemented/running  
**Depends on:** method canonicalization, `method_role`, weekly hotspot, SQLite migrations

## 1. Problem and baseline

当前周热点已有：

1. `canonical_method`：严格实体归一和分析层 alias soft mapping；
2. `method_role`：`backbone | aggregator | classical_ml | tool | unknown`；
3. 方法榜按 role 分区展示。

但当前生产库的确定性分类覆盖有限：

| 口径 | role + 初步 family 规则覆盖 |
|---|---:|
| Method 实体 | 29.0% |
| 有效 APPLIES_METHOD 关系 | 48.0% |
| 至少一个方法可分类的论文 | 62.4% |

长尾包括不透明模型名、首次出现的新方法和复合方法。继续扩展正则会导致维护成本和误分类快速上升。

## 2. Goals

1. 使用外部 Embedding API 为规则未覆盖的方法生成 `method_family` 候选。
2. 保持三层语义严格分离：
   - `canonical_method`：同一实体；
   - `method_family`：技术家族，可多标签；
   - `method_role`：架构/工作流角色，单标签。
3. 周热点新增 family 聚合榜，并支持 family → method 下钻。
4. 首次批量回填可恢复，后续仅处理新增或输入变化的方法。
5. 外部 API 不可用时，weekly、UI 和现有热点榜必须继续工作。
6. 自动分类以 precision 为先；不确定项继续保留 `unknown`。

## 3. Non-goals

- 不使用 embedding 自动合并 Method 或 Disease 实体。
- 不用向量相似度抹平方法版本、modified/baseline 差异。
- 不在 UI 请求期间同步调用外部 API。
- v1 不为全部摘要、全文章节和 relation evidence 建向量索引。
- v1 不引入独立向量数据库或常驻推理服务。

## 4. Chosen architecture

```text
Extraction / alias merge
        │
        ▼
Method entity + aliases + evidence context
        │
        ├── deterministic canonical / role / family rules
        │
        └── unresolved or dirty rows
                 │
                 ▼
        External Embedding API
                 │
                 ▼
        local vector cache (SQLite BLOB)
                 │
                 ▼
        family prototype similarity
                 │
        threshold + margin + guardrails
                 │
                 ▼
        taxonomy assignment / audit queue
                 │
                 ▼
        weekly family board (distinct PMID union)
```

外部服务只负责将文本映射为向量。类别定义、阈值、决策、审计、缓存和热点聚合全部留在本项目中，避免供应商锁定。

## 5. Taxonomy

### 5.1 Three layers

| 层 | 示例 | 合并统计 | 多标签 |
|---|---|---|---|
| canonical_method | `SVM` → `support vector machine` | 是 | 否 |
| method_family | `TransMIL` → `MIL`, `Transformer` | family 榜使用 | 是 |
| method_role | `TransMIL` → `aggregator` | 仅展示维度 | 否 |

### 5.2 Initial family catalog

- `mil`
- `cnn`
- `transformer`
- `foundation_model`
- `graph_neural_network`
- `representation_learning`
- `generative_model`
- `classical_statistics`
- `bioinformatics_omics`
- `image_processing`
- `multimodal_fusion`
- `explainability`
- `other_tooling`

每个 family 包含：稳定 ID、中英文描述、正例种子、反例/边界、父级（可空）和 taxonomy version。分类时使用描述向量和多个种子 centroid，不只比较一个类别名称。

## 6. Embedding input

只编码公开文献中的最小充分上下文：

```text
method: TransMIL
aliases: transformer multiple-instance learning
role: aggregator
contexts:
- title: ...
  evidence: ...
- title: ...
  evidence: ...
```

约束：

- 最多 3 个不同 PMID 的上下文；
- 优先 `APPLIES_METHOD` 的 methods/results evidence；
- 每条 quote 截断，整个输入默认不超过 2,000 字符；
- 不发送全文、API key、路径、会话记忆和方信病例数据；
- 输入排序固定，计算 `input_sha256`，相同输入不重复付费。

只用方法名时对 `CHIEF`、`MISTY` 等名称无法消歧，因此 evidence context 是 v1 必需输入，而不是可选增强。

## 7. External API client

新增 `analysis/embedding_client.py`，使用 OpenAI-compatible embeddings contract，但配置与现有 LLM 完全隔离。

```ini
EMBEDDING_ENABLED=0
EMBEDDING_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
# Optional. If empty, reuse the existing Bailian LLM key under the guardrails below.
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=768
EMBEDDING_BATCH_SIZE=10
EMBEDDING_MAX_CONCURRENT=2
EMBEDDING_REQUEST_TIMEOUT=60
EMBEDDING_RETRY_ATTEMPTS=5
EMBEDDING_MIN_INTERVAL=0.2
EMBEDDING_RATE_LIMIT_COOLDOWN=30
EMBEDDING_CONTEXT_MAX_CHARS=2000
```

要求：

- batch 输入；
- 指数退避 + jitter；
- 对 429、5xx、timeout 可重试，对认证/参数错误快速失败；
- 不在日志中打印 key 或完整输入；
- 校验返回条数、维度和有限浮点值；
- provider/model/dimensions 是 cache key 的一部分；
- 单批失败只标记 job item，不回滚已成功批次。

当前项目已确认 LLM 使用阿里云百炼。Key 解析顺序固定为：

1. 显式 `EMBEDDING_API_KEY`；
2. `DASHSCOPE_API_KEY`；
3. 仅当 `EMBEDDING_API_BASE` 与 `OPENAI_API_BASE` 都是 DashScope 域名时，复用
   `OPENAI_API_KEY`。

这样现阶段无需复制或暴露 Key，同时仍保留未来独立限额、审计和轮换的能力。预检与日志只输出
`key_source`，绝不输出 Key、前后缀或哈希。

百炼 `text-embedding-v4` 同步接口每次最多 10 条，所以在线/增量路径的 batch size 上限固定为
10；更大的历史回填在 Phase B 另走 Batch File API，不能把同步接口的配置直接设为 64。

## 8. Storage design

### 8.1 `embedding_cache`

| Column | Purpose |
|---|---|
| `input_sha256` | 稳定输入指纹 |
| `provider` / `model` / `dimensions` | 模型身份 |
| `vector_blob` | little-endian float32 BLOB |
| `created_at` | 缓存时间 |

Primary key: `(input_sha256, provider, model, dimensions)`。

### 8.2 `method_taxonomy_families`

| Column | Purpose |
|---|---|
| `family_id` | 稳定 slug |
| `display_name_zh/en` | UI 文案 |
| `description` | prototype 文本 |
| `seed_methods_json` | 人工正例 |
| `negative_examples_json` | 边界反例 |
| `taxonomy_version` | 类目版本 |
| `active` | 是否参与分类 |

### 8.3 `method_family_assignments`

| Column | Purpose |
|---|---|
| `method_entity_id` | Method 实体 |
| `family_id` | family |
| `is_primary` | 主 family |
| `confidence` | 校准后置信度 |
| `similarity` | cosine similarity |
| `margin` | top1 - top2 |
| `source` | `rule | embedding | manual` |
| `status` | `accepted | review | rejected | stale` |
| `input_sha256` | 上下文版本 |
| `model` / `taxonomy_version` | 可重现性 |
| `updated_at` | 更新时间 |

Unique key: `(method_entity_id, family_id, taxonomy_version)`。

### 8.4 `embedding_jobs`

记录 backfill/incremental job 的状态、游标、成功/缓存命中/失败数和错误摘要，用于断点续跑。不要将每个向量请求写入 debate memory。

## 9. Classification decision

决策顺序：

1. manual assignment；
2. 高精度 family allowlist / rule；
3. embedding prototype similarity；
4. 低置信度 → `unknown` + review queue。

初始阈值只是 shadow-run 起点，必须用标注集校准：

```text
auto accept primary:
  top1_similarity >= 0.78
  AND top1_minus_top2 >= 0.05

secondary family:
  similarity >= 0.76
  AND top1_similarity - similarity <= 0.03

otherwise:
  status = review or unknown
```

Guardrails：

- `u-net` 与 `u-net++` 可同 family，但 canonical entity 永不合并；
- family 允许多标签，role 仍是单标签；
- rule 与 embedding 冲突时不静默覆盖 rule，进入 review；
- 只有名称、无 evidence context 的不透明短名提高阈值；
- 相同方法跨上下文预测冲突时保留多个上下文结果并进入审计。

## 10. Weekly integration

推荐 weekly 顺序：

```text
fetch → fulltext → extract
→ classify-method-family --incremental
→ compute-gap-lifecycle
→ hotspot-report / hotspot-brief
```

`classify-method-family` 是 best-effort：

- API 可用：处理新增和 stale Method；
- API 失败：记录失败，使用既有 accepted/manual/rule 结果；
- 无缓存的新方法继续显示在 `unknown`；
- 不阻断 hotspot report 和 UI。

新增 payload：

- `method_family_boards`
- `method_family_members`
- 方法行增加 `method_families`, `family_confidence`, `family_source`

family 热度必须用该 family 下所有方法的 **distinct PMID union** 计算，不能相加 method count。每个 family 行展示：成员方法数、recent/prior PMID、velocity、score、top methods、top PMIDs 和 unknown/confidence coverage。

UI：

1. 方法 Tab 默认显示 family 分区；
2. family 可展开到具体 canonical methods；
3. 保留 role 作为列/筛选器；
4. 提供 `规则 / embedding / 人工` 来源和低置信度标记；
5. 保留现有平铺榜作为兼容视图。

Snapshot 增加 `method_family` board，避免 taxonomy 变化污染历史：snapshot 行同时记录 `taxonomy_version` 和 `embedding_model`。

## 11. Cost and performance controls

当前 24,613 个 Method：

- 若全部走同步接口，batch size 10 时最多约 2,462 个 request；
- Phase B 的大规模历史回填优先使用百炼 Batch File API，不以上述同步请求数作为实施方案；
- 若每个输入约 80–300 tokens，初次回填约 200 万–740 万输入 tokens；
- 768 维 float32 原始 Method 向量约 72 MB；加缓存和索引仍可由 SQLite 承载；
- weekly 增量通常只处理新增/变化项，成本远小于首次回填。

控制策略：

- 规则已高置信命中的方法默认不调用 API；
- input hash 缓存；
- 只为有 active `APPLIES_METHOD` 或近期窗口关系的方法生成上下文向量；
- backfill 支持 `--limit`, `--resume`, `--dry-run`, `--only-unknown`；
- 设置单次 job 最大 items/tokens/cost estimate；超限时停止派发新 batch，不破坏已完成结果。

## 12. Evaluation and release gates

建立 300–500 条人工 gold set：按高频/长尾、年份、role、是否不透明名称分层抽样，并对论文贡献按 PMID 加权。

指标：

- primary-family precision / recall；
- multi-label micro/macro F1；
- entity、relation、paper 三种 coverage；
- `unknown` 比率；
- rule/embedding 冲突率；
- version collision rate（必须为 0）；
- 每千项 API 成本、缓存命中率、p50/p95 batch latency。

上线门槛：

- 自动 accepted precision ≥ 90%，建议目标 95%；
- paper-weighted coverage ≥ 80%；
- version collision = 0；
- API 故障不影响 weekly 成功率；
- 同输入、同模型、同 taxonomy version 的结果可重现。

## 13. Rollout

### Phase A — client/cache foundation

- 配置、client、schema、mock API tests；
- dry-run 成本估算；
- 不接 weekly/UI。
- 详细设计见
  [`2026-09-05-phase-a-bailian-embedding-foundation-design.md`](./2026-09-05-phase-a-bailian-embedding-foundation-design.md)。

### Phase B — shadow backfill

- 只跑有 `APPLIES_METHOD` 的 10,619 个 Method；
- 写 `review`，不改变用户可见分类；
- 标注 gold set，校准阈值。
- 详细设计见
  [`2026-09-05-phase-b-method-family-shadow-design.md`](./2026-09-05-phase-b-method-family-shadow-design.md)。

### Phase C — accepted family board

- accepted/manual/rule 进入 family board；
- review/unknown 仍在未分类；
- family snapshot 和 UI 下钻上线。
- 详细设计见
  [`2026-09-05-phase-c-accepted-family-board-design.md`](./2026-09-05-phase-c-accepted-family-board-design.md)。

### Phase D — incremental weekly

- weekly 前置 best-effort 增量分类；
- 监控 API、缓存、覆盖率与 drift；
- taxonomy/model 升级走新 version，不原地覆盖历史结果。

## 14. Acceptance tests

1. 相同 input hash 不重复调用 API。
2. batch 返回乱序/缺项/维度错误时安全失败。
3. 429/5xx 重试，401 快速失败。
4. API 全故障时 weekly 仍产出报告。
5. `TransMIL` 可得到 `mil + transformer`，且 role 保持 `aggregator`。
6. `UNet` / `UNet++` 同 family、不同 canonical entity。
7. family recent count 使用 distinct PMID，不重复计数。
8. model/taxonomy version 变化只将旧 assignment 标 stale，不删除审计历史。
9. 日志、DB job error 不含 API key 和完整发送文本。

## 15. Decisions to confirm before implementation

已确认：

1. Provider 为阿里云百炼北京地域，模型从 `text-embedding-v4`、768 维开始，使用
   OpenAI-compatible `/embeddings`；
2. 复用现有百炼 LLM Key，但保留独立的 Embedding 配置入口；
3. Phase A 只发送公开文献中的 method、title 和最短 evidence quote，不发送全文、内部路径或会话数据；
4. 初始 family catalog 采用本设计的 13 类，但到 Phase B 才写入和校准；
5. Phase B 首次回填只覆盖有 active `APPLIES_METHOD` 的 Method，实际数量在 dry-run 时重新统计。
