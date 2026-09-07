# Full-Text Workflow

病理 AI 文献 **全文知识图谱** 与研究空白分析管线。

- PubMed 元数据 → 全文（JATS / PDF+MinerU）→ 分章节 LLM 抽取 → NetworkX 建图  
- 静态 Gap 报告、多智能体辩论、周热点、ops memory 软去重  
- 方信 LIS 数据可行性 + 研究方案（idea-pipeline）  
- Streamlit 八标签页 UI（`gap_ui.py`，含「运维」周更）

独立数据库：`data/kg_fulltext.db`（不依赖已移除的主程序库）。

## 文档索引

| 文档 | 内容 |
|------|------|
| **[PIPELINE.md](PIPELINE.md)** | 分阶段流水线、生产跑法、weekly / ops memory |
| **[SCRIPTS.md](SCRIPTS.md)** | 常用命令与维护脚本速查 |
| **[gap_ui_guide.md](gap_ui_guide.md)** | Streamlit UI 操作说明 |
| 仓库根目录 [README.md](../README.md) | 环境安装与总入口 |

## 快速开始

在仓库根目录配置环境与 `.env`（见根 README），然后：

```powershell
cd fulltext_workflow
$py = "..\.venv\Scripts\python.exe"

.\run_pipeline.ps1                    # 交互菜单
.\run_pipeline.ps1 -Stage weekly      # 每周增量
.\run_gap_ui.ps1                      # Gap UI → http://localhost:8501
```

试跑建库：

```powershell
& $py main.py run-db --limit 30 --core-only
& $py main.py build
& $py main.py analyze
```

## 检索范围

查询组与默认年份来自仓库根目录 [`search_queries.py`](../search_queries.py)（当前默认 **2015–2025**、**17** 组启用；`pathomics_radiomics` 默认关闭，因可行性侧无影像数据）。可用环境变量覆盖：

```ini
FULLTEXT_SEARCH_YEAR_START=2015
FULLTEXT_SEARCH_YEAR_END=2026
FETCH_EDAT_DAYS=14
```

### 本地检索与实体同义词

主题检索会同时匹配 `title`、`abstract`、`keywords`、`mesh_terms`、
`source_queries` 与已抽取实体，并按字段权重排序。Disease / Method 同义表达被视为
同一个查询单元；混合查询（如 `SVM breast cancer external validation`）要求已识别的
Disease / Method 概念实际命中，避免仅凭一个高频词返回噪声文献。

实体入库采用更严格的白名单：只合并不损失疾病分型、方法版本或改造信息的别名；
宽松的检索概念不会用于持久化。存量库可先预演、再事务化回填：

```powershell
& $py scripts/merge_entity_aliases.py
& $py scripts/merge_entity_aliases.py --apply
```

原始表达保存在 `entities.aliases`，关系与 `paper_entity_bindings` 会重连到 canonical
实体。脚本幂等；生产库完成后再次预演应显示 `group_count: 0`。

## 主命令一览

```powershell
& $py main.py init | fetch | enrich-s2 | import-if | fetch-fulltext
& $py main.py extract --limit 0 --core-only
& $py main.py compute-gap-lifecycle
& $py main.py build | viz | analyze | stats
& $py main.py hotspot-report | hotspot-brief
& $py main.py backfill-method-roles [--force]
& $py main.py embedding-preflight
& $py main.py embedding-plan --only-active --dry-run
& $py main.py method-family-init --embed-prototypes
& $py main.py method-family-shadow --sync --limit 100
& $py main.py method-family-batch submit|status|ingest
& $py main.py method-family-gold-export --size 400
& $py main.py method-family-gold-validate --input output/method_family_gold_method-family-v1.csv
& $py main.py method-family-gold-import --input output/method_family_gold_method-family-v1.csv --reviewer expert-v1
& $py main.py method-family-calibrate --gold-set-id <gold-set-id>
& $py main.py method-family-rules-evaluate --gold-set-id <gold-set-id>
& $py main.py method-family-policy-preview --gold-set-id <gold-set-id> --calibration-id <calibration-id> --ruleset-id <ruleset-id>
& $py main.py method-family-review-queue --gold-set-id <gold-set-id> --calibration-id <calibration-id> --ruleset-id <ruleset-id>
& $py main.py method-family-gold-extension-import --input <annotated-queue.csv> --queue-id <queue-id> --reviewer <reviewer> --rank-end 200
& $py main.py method-family-blind-promote --evaluation-id <completed-evaluation-id> --promoted-by <reviewer>
& $py main.py bootstrap-landscape [--force]
& $py main.py gap-debate --focus "…" -o output/gap_debate_report.md
& $py main.py idea-pipeline --focus "digital pathology" --top 3
```

完整参数与周更说明见 [SCRIPTS.md](SCRIPTS.md) / [PIPELINE.md](PIPELINE.md)。

## Gap UI（八标签页）

Debate Process · Weekly Hotspot · Visualization · Evidence & Literature · Gap Report · Data Feasibility · Research Proposal · **运维**

侧边栏默认开启 **Use ops memory** / **Persist this run**，并提供同焦点会话历史、历史报告加载和未完成 checkpoint 续跑。「运维」可后台跑 weekly，并清空 ops memory。

## 能力模块

| 模块 | 作用 |
|------|------|
| `fetcher/` | PubMed、全文（冷却重试）、引用 enrichment |
| `extractor/` | 分章节 LLM 三元组抽取（粒度政策见 [extractor/GRANULARITY.md](extractor/GRANULARITY.md)；摘要→全文自动重抽） |
| `graph/` + `viz/` | NetworkX / Pyvis |
| `analysis/gap_tools.py` | SQL Gap + impact 加权 |
| `analysis/gap_lifecycle.py` | limitation 时间画像 |
| `analysis/weekly_hotspot.py` | 周发表热点 + WoW + method_role |
| `analysis/method_role.py` | Method 架构角色分类 / 回填 |
| `analysis/retrieval.py` | Disease / Method 查询展开、跨字段加权匹配 |
| `analysis/embedding_*.py` | 百炼 Embedding 客户端、稳定输入、SQLite 缓存与任务审计（Phase A） |
| `analysis/method_family_gold.py` | Gold 校验、不可变导入、确定性拆分与离线阈值校准（Phase C0） |
| `analysis/method_family_rules.py` | 严格名称规则验收与 Gold > rule > embedding 全库覆盖率预览（Phase C0-B） |
| `analysis/method_family_review_queue.py` | 按未覆盖 PMID 边际贡献生成增量人工标注队列（Phase C0-C） |
| `db/entity_alias_merge.py` | 严格同义词存量回填与关系重连 |
| `analysis/ops_memory.py` | 周常辩论记忆软去重 |
| `analysis/debate_memory.py` | 多角色会话 checkpoint、候选 ID、handoff 与事件留存 |
| `analysis/ops_jobs.py` | Gap UI 运维后台周更 |
| `gap_agent.py` | Opportunity Scout × Evidence Reviewer × Final Synthesizer |
| `idea_agent.py` + `pipeline.py` | 可行性门控 + 方案生成 |
| `feasibility/` | 方信 LIS（API-faithful pools，无估计 floor） |
| `ops_panel.py` | 运维 Tab UI |

## 数据路径

| 路径 | 内容 |
|------|------|
| `data/kg_fulltext.db` | SQLite 主库 |
| `data/jcr.csv` | 期刊 IF（`import-if`） |
| `raw/pmc_xml/` · `raw/pdfs/` · `raw/mineru_output/` | 全文缓存 |
| `output/` | GEXF、HTML、各类报告 |

## 测试

```powershell
& $py tests/test_feasibility.py
& $py -m pytest tests/ -q
```

## 相关仓库根文档

- [`api_document.md`](../api_document.md) — 方信病理 API  
- [`pathology_data_api_spec.md`](../pathology_data_api_spec.md) — 可行性闭环规格  
- [`docs/superpowers/specs/2026-07-15-ops-memory-design.md`](../docs/superpowers/specs/2026-07-15-ops-memory-design.md) — Ops memory 设计  
- [`docs/superpowers/specs/2026-08-04-gap-ui-ops-weekly-job-design.md`](../docs/superpowers/specs/2026-08-04-gap-ui-ops-weekly-job-design.md) — Gap UI 运维 / weekly job  
- [`docs/superpowers/specs/2026-08-04-feasibility-api-faithful-pools-design.md`](../docs/superpowers/specs/2026-08-04-feasibility-api-faithful-pools-design.md) — V-01 API-faithful pools  
- [`docs/superpowers/specs/2026-08-05-abstract-fulltext-upgrade-reextract-design.md`](../docs/superpowers/specs/2026-08-05-abstract-fulltext-upgrade-reextract-design.md) — 摘要→全文自动重抽  
- [`docs/superpowers/specs/2026-09-05-external-embedding-method-taxonomy-design.md`](../docs/superpowers/specs/2026-09-05-external-embedding-method-taxonomy-design.md) — 外部 Embedding API 方法家族分类与周热点设计
- [`docs/superpowers/specs/2026-09-05-phase-a-bailian-embedding-foundation-design.md`](../docs/superpowers/specs/2026-09-05-phase-a-bailian-embedding-foundation-design.md) — Phase A：百炼 Embedding 客户端、缓存与成本预估
- [`docs/superpowers/specs/2026-09-05-phase-b-method-family-shadow-design.md`](../docs/superpowers/specs/2026-09-05-phase-b-method-family-shadow-design.md) — Phase B：方法家族 shadow backfill、Batch 与 gold set
- [`docs/superpowers/specs/2026-09-05-phase-c-accepted-family-board-design.md`](../docs/superpowers/specs/2026-09-05-phase-c-accepted-family-board-design.md) — Phase C：校准发布、方法家族热点榜与版本化回滚

### Method family 上线门禁

Method-family 采用 `专家 Gold > 经扩展 Gold 复核的严格规则/高纯度词组 > 按家族阈值的本地监督 embedding > unknown` 的优先级。外部百炼 embedding 只用于生成并缓存向量；监督层在本机用 NumPy 训练，不新增在线推理服务。模型内同时冻结训练标签快照，后续扩展 Gold 不会改变旧模型的 preview 或 release。阈值按“支持类别精度不低于 85%，整体及论文加权精度不低于 95%，unknown 零误接收”逐类校准。上线必须同时满足独立 200 条盲测的精度门禁与生产论文覆盖门禁（80%），随后才能创建不可变 release 并激活。完成评测的盲测集可以显式退役并晋升为后续模型的训练数据，但原评测保持不可变、样本永久排除于后续盲测，且必须使用新一代盲测作为新模型发布门禁。“每周热点”的“方法类别”页只展示已激活 release，避免把 shadow 结果误当生产分类。
