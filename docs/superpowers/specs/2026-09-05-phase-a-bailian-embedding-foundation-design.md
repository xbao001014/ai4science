# Phase A Design: Bailian Embedding Client and Cache Foundation

**Date:** 2026-09-05  
**Status:** Implemented and verified  
**Parent design:**
[`2026-09-05-external-embedding-method-taxonomy-design.md`](./2026-09-05-external-embedding-method-taxonomy-design.md)

## 1. Outcome

Phase A 建成一个可验证、默认关闭、不会影响现有周热点的百炼 Embedding 基础层。完成后项目能够：

1. 安全复用现有百炼 LLM API Key；
2. 为一组文本请求 `text-embedding-v4` 的 768 维向量；
3. 用输入指纹命中 SQLite 缓存，避免重复付费；
4. 在不请求 API 的情况下统计候选方法、缓存命中和预计费用；
5. 用 mock API 验证乱序、缺项、错误维度、重试和脱敏；
6. 用显式 `--live-probe` 才能发送极小真实请求。

Phase A 不进行方法家族判定，不修改任何 `Method` 实体，不接入 weekly pipeline 或 UI。

## 2. Fixed provider decision

| Item | Value |
|---|---|
| Provider ID | `bailian` |
| Region | 华北 2（北京） |
| API base | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Model | `text-embedding-v4` |
| Dimensions | `768` |
| Sync batch maximum | `10` |
| Vector encoding | float32, little-endian BLOB |
| Price used by estimator | `0.5 CNY / 1M input tokens`，可配置 |

同步接口用于 Phase A probe 和后续每周小规模增量；Phase B 历史回填优先使用 Batch File API。

## 3. Scope boundary

### In scope

- Embedding 配置与预检；
- OpenAI-compatible 同步客户端；
- 可注入 transport，支持完全离线 mock；
- 稳定输入构造和 SHA-256 指纹；
- SQLite cache/job/job-item 表与 CRUD；
- 候选方法查询和 dry-run 费用估算；
- CLI：`embedding-preflight` 与 `embedding-plan`；
- 单元、数据库和命令级测试；
- 一次显式、最多 2 条文本的 live probe 操作手册。

### Out of scope

- family prototype、余弦相似度、阈值和 assignment；
- 13 类 taxonomy seed 数据写入；
- 全量或 10,000+ 方法真实回填；
- Batch File API；
- 周热点 family board、snapshot 和 UI；
- 用 embedding 合并 Method/Disease canonical entity；
- vector search/ANN 或独立向量数据库。

## 4. Configuration and key reuse

在 `fulltext_workflow/config.py` 增加：

```ini
EMBEDDING_ENABLED=0
EMBEDDING_PROVIDER=bailian
EMBEDDING_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=768
EMBEDDING_BATCH_SIZE=10
EMBEDDING_MAX_CONCURRENT=2
EMBEDDING_REQUEST_TIMEOUT=60
EMBEDDING_RETRY_ATTEMPTS=5
EMBEDDING_RETRY_DELAY=1.0
EMBEDDING_MIN_INTERVAL=0.2
EMBEDDING_RATE_LIMIT_COOLDOWN=30
EMBEDDING_CONTEXT_MAX_CHARS=2000
EMBEDDING_ESTIMATED_CNY_PER_MTOK=0.5
```

Key 解析必须通过一个函数完成，顺序为：

```text
EMBEDDING_API_KEY
  → DASHSCOPE_API_KEY
  → OPENAI_API_KEY（仅当 embedding 与 LLM base 都属于 dashscope.aliyuncs.com）
  → missing
```

`embedding-preflight` 只显示：

```text
provider=bailian
base_host=dashscope.aliyuncs.com
model=text-embedding-v4
dimensions=768
batch_size=10
key_source=OPENAI_API_KEY
key_configured=yes
```

禁止显示 Key 长度、首尾字符、哈希、HTTP Authorization header 或 `.env` 内容。配置验证规则：

- `batch_size` 必须在 1–10；
- `dimensions` 初期固定允许 768，代码结构保留将来扩展；
- base 必须为 HTTPS；
- `EMBEDDING_ENABLED=0` 时 dry-run 可运行，但真实请求必须拒绝；
- provider/base 不匹配时禁止隐式复用 `OPENAI_API_KEY`。

## 5. Deterministic input contract

Phase A 实现输入构造，但不存储原文。候选集默认是至少关联一条 active `APPLIES_METHOD` 的
Method entity。每个 Method 的输入固定为：

```text
method: {canonical entity name}
aliases: {sorted aliases, max 8}
role: {method_role or unknown}
contexts:
- pmid: {pmid}
  title: {paper title}
  evidence: {short evidence quote}
```

构造规则：

1. 只取 `relations.object_id = entities.id`、`relation='APPLIES_METHOD'`、active relation；
2. 最多选择 3 个不同 PMID；优先 methods/results evidence，其次其他 section；
3. 同优先级按 PMID 和 relation id 排序，确保重复运行文本完全一致；
4. 单条 quote 先去除控制字符、压缩空白，再截断到 400 字符；
5. 总输入截断到 `EMBEDDING_CONTEXT_MAX_CHARS=2000`；
6. 不足上下文时允许 method + alias + role，但标记 `context_quality=name_only`；
7. `input_sha256 = sha256(UTF-8 normalized input)`；
8. cache/job 表只保存 hash、字符数、估算 token 数和来源 ID，不保存完整 input。

这里的 canonical 只使用当前实体与已完成的 alias merge 结果；Embedding 不能反向改变 canonical。

## 6. Client contract

新增 `fulltext_workflow/analysis/embedding_client.py`：

```python
@dataclass(frozen=True)
class EmbeddingItem:
    item_id: str
    input_sha256: str
    text: str

@dataclass(frozen=True)
class EmbeddingVector:
    item_id: str
    input_sha256: str
    values: tuple[float, ...]
    prompt_tokens: int | None

class EmbeddingClient:
    def embed(self, items: Sequence[EmbeddingItem]) -> list[EmbeddingVector]: ...
```

实际调用：

```python
client.embeddings.create(
    model="text-embedding-v4",
    input=[item.text for item in items],
    dimensions=768,
    encoding_format="float",
)
```

返回校验：

- 请求为 1–10 条；
- `data[].index` 必须无重复且恰好覆盖 `0..n-1`；
- 按 index 重排后再与 `item_id` 对齐，不能相信响应数组顺序；
- 每个向量恰好 768 维；
- 所有值必须为有限浮点数；
- 空向量、NaN、Infinity、缺项、多项均整批失败且不写缓存；
- usage 缺失不影响向量成功，但记录为 unknown。

错误策略：

| Error | Action |
|---|---|
| 401/403 | 快速失败，`auth_error`，不重试 |
| 400/404/422 | 快速失败，`request_error`，不重试 |
| 408/429 | 指数退避；429 至少等待 cooldown |
| 500/502/503/504 | 指数退避 + jitter |
| timeout/connection | 指数退避 + jitter |
| response validation | `invalid_response`，不自动重试 |

客户端不打印文本。异常摘要先移除 Authorization、疑似 `sk-...` token、request body 和换行，再限制为
500 字符。

## 7. Storage

Phase A 只创建三张 provider 基础表，不提前创建 taxonomy assignment 表。

### `embedding_cache`

```sql
CREATE TABLE embedding_cache (
    input_sha256       TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    dimensions         INTEGER NOT NULL,
    vector_blob        BLOB NOT NULL,
    vector_norm        REAL NOT NULL,
    input_chars        INTEGER NOT NULL,
    prompt_tokens      INTEGER,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (input_sha256, provider, model, dimensions),
    CHECK (dimensions > 0),
    CHECK (length(vector_blob) = dimensions * 4)
);
```

`vector_norm` 在写入前计算，Phase B 做 cosine 时无需重复计算；取缓存时再次校验 BLOB 长度和有限值。
缓存记录没有 entity 外键，因为同一输入可被多个任务复用，entity 生命周期也不应删除付费所得向量。

### `embedding_jobs`

```sql
CREATE TABLE embedding_jobs (
    job_id              TEXT PRIMARY KEY,
    job_type            TEXT NOT NULL,
    status              TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    dimensions          INTEGER NOT NULL,
    scope_json          TEXT NOT NULL DEFAULT '{}',
    planned_items       INTEGER DEFAULT 0,
    cache_hits          INTEGER DEFAULT 0,
    requested_items     INTEGER DEFAULT 0,
    succeeded_items     INTEGER DEFAULT 0,
    failed_items        INTEGER DEFAULT 0,
    estimated_tokens    INTEGER DEFAULT 0,
    actual_tokens       INTEGER DEFAULT 0,
    estimated_cost_cny  REAL DEFAULT 0,
    error_summary       TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP
);
```

`scope_json` 只保存 `only_active_applies_method`、limit、输入版本等非敏感配置；禁止保存 Key 或文本。

### `embedding_job_items`

```sql
CREATE TABLE embedding_job_items (
    job_id              TEXT NOT NULL REFERENCES embedding_jobs(job_id) ON DELETE CASCADE,
    item_type           TEXT NOT NULL,
    item_id             TEXT NOT NULL,
    input_sha256        TEXT NOT NULL,
    context_quality     TEXT NOT NULL,
    input_chars         INTEGER NOT NULL,
    estimated_tokens    INTEGER NOT NULL,
    status              TEXT NOT NULL,
    cache_hit           INTEGER DEFAULT 0,
    attempts            INTEGER DEFAULT 0,
    error_code          TEXT,
    error_summary       TEXT,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, item_type, item_id)
);
```

Phase B 可直接基于 item 状态断点续跑。`input_sha256` 变化时作为新输入处理，旧缓存仍保留用于审计。

## 8. Cache algorithm and transaction boundary

```text
build normalized inputs
  → bulk lookup cache keys
  → split cached / missing
  → cached: validate, mark hit, update last_used_at
  → missing: chunks of <= 10
      → API request outside SQLite transaction
      → validate complete batch
      → one short transaction writes cache + item statuses
  → finalize job counters
```

关键约束：

- HTTP 请求期间绝不持有 SQLite write transaction；
- cache insert 使用 `INSERT ... ON CONFLICT DO NOTHING`，并发同 hash 不报错；
- 若并发者先写入，当前任务回读并校验后按成功处理；
- 单批失败不删除已成功批次；
- invalid cache row 不能返回给调用方，标记 job item 为 `cache_corrupt`；
- Phase A 不自动清理缓存，不实现破坏性 purge 命令。

## 9. Token and cost estimator

百炼在真实响应中返回 usage 时记录实际 token；dry-run 不能调用 API，因此采用保守估算：

```text
estimated_tokens = ceil(utf8_text_bytes / 3.0)
estimated_cost_cny = estimated_tokens / 1_000_000 * configured_price
```

中文和英文混合文本很难靠字符精确估计，因此报告同时输出字符数、UTF-8 bytes、估算 tokens，并明确标记
`estimate_only`。Phase B 上线前用 100–200 条 live sample 的实际 usage 校准系数。

dry-run 报告至少包含：

- active `APPLIES_METHOD` 的 distinct Method 数；
- 输入可构造数、name-only 数、无有效输入数；
- cache hit/miss 数；
- 预计同步 request 数（ceil(miss / 10)）；
- 估算 token 和实时价格成本；
- 按输入长度 p50/p95/max；
- 不输出具体 evidence 文本。

## 10. CLI

### Preflight

```powershell
python fulltext_workflow/main.py embedding-preflight
python fulltext_workflow/main.py embedding-preflight --live-probe
```

默认只校验配置、DB schema 和 client 初始化，不访问网络。`--live-probe` 需要同时满足：

- `EMBEDDING_ENABLED=1`；
- Key 已配置；
- 固定发送两个无敏感信息的测试短句；
- 最多一次请求，不写 taxonomy assignment；
- 成功后可写 cache，但 job_type 标为 `live_probe`。

### Dry-run plan

```powershell
python fulltext_workflow/main.py embedding-plan --only-active --dry-run
python fulltext_workflow/main.py embedding-plan --only-active --dry-run --limit 100
```

Phase A 的 `embedding-plan` 只允许 `--dry-run`；任何企图批量真实请求的参数都拒绝并提示等待 Phase B。
默认范围固定为 active `APPLIES_METHOD`，`--limit` 只用于测试且排序按 entity id，保证可复现。

## 11. Files to add or change

| File | Change |
|---|---|
| `fulltext_workflow/config.py` | Embedding 配置、条件 Key 复用与验证 |
| `.env.example` | 增加默认关闭的 Embedding 配置，不复制真实 Key |
| `fulltext_workflow/analysis/embedding_client.py` | API client、retry、validation、redaction |
| `fulltext_workflow/analysis/embedding_inputs.py` | Method 候选查询、上下文构造、hash、估算 |
| `fulltext_workflow/analysis/embedding_store.py` | float32 codec、cache/job CRUD |
| `fulltext_workflow/analysis/embedding_service.py` | cache-first 小批同步任务编排 |
| `fulltext_workflow/db/schema.py` | 三张 Phase A 表和索引 |
| `fulltext_workflow/main.py` | preflight 与 dry-run CLI |
| `fulltext_workflow/tests/test_embedding_client.py` | API contract/error/retry tests |
| `fulltext_workflow/tests/test_embedding_inputs.py` | 稳定输入与 privacy tests |
| `fulltext_workflow/tests/test_embedding_store.py` | schema/cache/corruption/concurrency tests |
| `fulltext_workflow/tests/test_embedding_cli.py` | 默认无网络和参数 guard tests |

不新增依赖：继续使用已有 `openai>=1.30.0`、标准库 `array`/`struct` 和 SQLite。Phase A 不引入
NumPy、FAISS、Chroma 或其他向量数据库。

## 12. Test matrix

必须覆盖：

1. 相同 normalized input 产生相同 hash；上下文变化产生新 hash；
2. alias/PMID 顺序变化不影响 normalized input；
3. 默认 preflight 和 dry-run 零网络请求；
4. 同一 cache key 第二次不调用 API；
5. response 乱序能按 index 正确复原；
6. index 缺失、重复、越界均整批失败；
7. 767/769 维、NaN、Infinity、空向量不入库；
8. 429/5xx/timeout 重试，401/400 不重试；
9. batch 11 条在发请求前失败；
10. HTTP 请求期间没有开启 DB write transaction；
11. BLOB 大小严格为 `768 * 4` bytes，往返误差符合 float32；
12. 损坏 cache 不返回；
13. error/log 中不出现测试 Key 或完整输入；
14. 非 DashScope base 不得复用 `OPENAI_API_KEY`；
15. live probe 在 enabled/key 缺失时明确拒绝；
16. 现有周热点测试不感知 Phase A 表和模块。

测试不得依赖公网或真实百炼 Key。live probe 是人工验收，不进入默认 pytest。

## 13. Acceptance gates

Phase A 完成必须同时满足：

- 新增测试全部通过；
- 全量现有测试无新增失败；
- `embedding-preflight` 默认不发网络请求；
- `embedding-plan --only-active --dry-run` 能在生产库只读完成并输出估算；
- 真实 Key 在日志、异常、DB 中零出现；
- mock 同输入运行两次，第二次 API 调用数为 0；
- live probe 返回 2 个 768 维有限向量并成功从 cache 读取；
- 不新增 weekly/UI payload，不改 Method/Disease canonical 或 role。

## 14. Implementation sequence

1. 配置和 schema migration；
2. float32 codec 与 cache/job CRUD；
3. input builder 和 dry-run estimator；
4. client、响应校验、retry 和 redaction；
5. CLI/preflight guard；
6. mock test suite；
7. 生产库 dry-run；
8. 用户显式启用后运行一次两条 live probe；
9. 输出 Phase A 验收记录，再进入 Phase B shadow backfill。

第 1–7 步不产生外部调用和新增费用。第 8 步才会使用现有百炼 Key，且只发送固定的无敏感测试文本。

## 15. Offline verification record

2026-09-05 已完成第 1–7 步：

- 配置预检通过：`bailian` / DashScope 北京端点 / `text-embedding-v4` / 768 维 / batch 10；
- 现有 Key 通过受域名保护的 `OPENAI_API_KEY` 路径复用，预检未输出凭证；
- 19 个 Phase A 专项测试通过；连同 debate memory 回归为 26 个测试通过；
- 全量回归为 644 passed、4 failed，4 项均为实施前已存在的 feasibility contract 不一致，
  Phase A 未引入新失败；
- 生产库 dry-run：10,619 个 active Method，全部具有 evidence context，缓存 miss 10,619，
  估算 1,399,177 tokens，实时价格估算约 0.699588 元；
- preflight 与 dry-run 的 `network_called=false`，未调用真实百炼 Embedding API。

随后使用一次性进程变量完成显式 `--live-probe`，未修改 `.env`：

- 首次请求发送 2 条固定测试文本，返回 2 个 768 维向量，API usage 为 13 tokens；
- 第二次运行命中 2 条缓存，`requested_items=0`、`network_called=false`；
- 生产库最终只新增 2 条 probe cache，未执行任何 Method 批量回填；
- 常态配置仍为 `EMBEDDING_ENABLED=0`，weekly 和 UI 不会触发 Embedding 请求。

Phase A 验收完成，可以进入 Phase B shadow backfill 的设计与小样本校准。
