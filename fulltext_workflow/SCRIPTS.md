# Full-Text Workflow 常用脚本

> 工作目录：`fulltext_workflow/`  
> 完整流水线说明见 [PIPELINE.md](PIPELINE.md)

```powershell
cd D:\agent\prototype\build_kg_paper\fulltext_workflow
$py = "..\.venv\Scripts\python.exe"
```

---

## 1. 一键脚本（最常用）

### `run_pipeline.ps1` — 流水线菜单 / 分阶段跑

```powershell
.\run_pipeline.ps1                         # 交互菜单
.\run_pipeline.ps1 -Stage weekly           # 每周增量（推荐）
.\run_pipeline.ps1 -Stage db               # 仅建库
.\run_pipeline.ps1 -Stage landscape        # 方信 landscape（--force）
.\run_pipeline.ps1 -Stage debate           # Gap 辩论
.\run_pipeline.ps1 -Stage all              # 全量建库+建图+analyze
.\run_pipeline.ps1 -Stage stats
```

| 参数 | 说明 |
|------|------|
| `-Stage` | `init` / `fetch` / `enrich` / `fulltext` / `extract` / `build` / `analyze` / `debate` / `landscape` / `stats` / `db` / `weekly` / `all` / `quick` |
| `-SinceDays N` | fetch 只搜最近 N 天 EDAT |
| `-CoreOnly` | extract 只抽核心章节 |
| `-ExtractLimit N` | 抽取篇数（0=全量待处理） |
| `-SkipEnrich` | 跳过 enrich-s2 / import-if |
| `-NoResume` | fetch 不跳过已有 PMID |

**`-Stage weekly` 包含**：fetch(14d) → enrich-s2 → fulltext → extract(core) → compute-gap-lifecycle → hotspot-report → hotspot-brief → build → analyze → stats  

**不含**：`import-if`、`gap-debate`、`bootstrap-landscape`

### `run_gap_ui.ps1` — Gap 分析 UI

```powershell
.\run_gap_ui.ps1
# 或
..\.venv\Scripts\streamlit.exe run gap_ui.py
```

浏览器：`http://localhost:8501`

### Gap UI「运维」Tab

等价于后台执行 `-Stage weekly`（阶段进度 + 日志），并支持清空 ops 记忆：

- 周更参数：`SinceDays` / `ExtractLimit` / `SkipEnrich`
- 清空记忆：对应 `scripts/clear_ops_memory.py`（预览 + `--yes` + 可选 `--focus` / `--delete-files`）

---

## 2. 日常 `main.py` 命令

### 入库 / 元数据

```powershell
& $py main.py init
& $py main.py fetch
& $py main.py fetch --since-days 14
& $py main.py watch-fetch                 # 另开终端看 fetch 进度
& $py main.py backfill-date-precision     # 存量补 date_precision（PubMed 重拉日期）
& $py main.py backfill-date-precision --limit 200
& $py main.py backfill-method-roles       # entities.method_role 规则回填
& $py main.py enrich-s2
& $py main.py import-if                   # 默认 data/jcr.csv
& $py main.py fetch-fulltext
& $py main.py fetch-fulltext --no-retry
& $py main.py fetch-fulltext --no-retry --skip-pdf
& $py main.py fetch-fulltext --force-retry
& $py main.py fetch-fulltext --pdf-retry-limit 100
# env: FULLTEXT_RETRY_COOLDOWN_DAYS=7  FULLTEXT_PDF_RETRY_LIMIT=500
#      FULLTEXT_PUBLISHER_DIRECT=true   # needs campus/VPN IP; IEEE+Elsevier before ScanSci
# PDF 队列按 fulltext_pdf_attempts 升序优先从未尝试；失败重试冷却 7→14→28→56 天
# --skip-pdf: 跳过 Tier2 PDF/MinerU（运维周常默认勾选关闭时使用）
& $py main.py stats
```

### 抽取 / 建图 / 分析

```powershell
& $py main.py extract --limit 0 --core-only --no-upgrade-reextract
& $py main.py extract --limit 0 --core-only --upgrade-reextract
& $py main.py extract --limit 30
# env: FULLTEXT_UPGRADE_REEXTRACT=true  (default) auto-reextract abstract→fulltext upgrades
# weekly ops checkbox off (default): fetch-fulltext --no-retry --skip-pdf + extract --no-upgrade-reextract
# weekly ops checkbox on: fetch-fulltext --pdf-retry-limit N (default 50) + extract --upgrade-reextract
```

### Pilot re-extract

`data/pilot_pmids.txt` is local (`fulltext_workflow/data/` is gitignored).

On the `feature/extraction-quality` pilot branch, **`RECONCILE_ENABLED` defaults to `true`** (Pass 2 runs after Pass 1 when fulltext exists). Run pilot QA and review `output/pilot_qa.csv` **before** a full-corpus `--force-reextract`.

```powershell
& $py main.py extract --pmid-list data/pilot_pmids.txt --force-reextract --limit 0
& $py main.py reconcile --pmid-list data/pilot_pmids.txt
& $py scripts/pilot_reconcile_qa.py --pmid-list data/pilot_pmids.txt --out output/pilot_qa.csv
& $py main.py reconcile   # pending/failed with fulltext
```

```powershell
& $py main.py compute-gap-lifecycle
& $py main.py compute-gap-lifecycle --temporal-only   # 更快
& $py main.py build
& $py main.py viz
& $py main.py analyze
```

### 周热点

```powershell
& $py main.py hotspot-report              # 写 md + 持久化快照
& $py main.py hotspot-report --no-persist
& $py main.py hotspot-brief               # LLM 简报
& $py main.py compute-weekly-hotspots     # 仅打印摘要
& $py main.py task-quality-audit          # Task 实体质量审计（只读）
& $py main.py method-cluster-audit        # Method synonym 聚类审计（只读）
```

### Embedding Phase A（默认离线）

```powershell
& $py main.py embedding-preflight
& $py main.py embedding-plan --only-active --dry-run
& $py main.py embedding-plan --only-active --dry-run --limit 100
```

`embedding-preflight` 默认只检查百炼配置与本地 schema，不访问网络。只有明确设置
`EMBEDDING_ENABLED=1` 后再添加 `--live-probe`，才会发送两条固定测试文本：

```powershell
& $py main.py embedding-preflight --live-probe
```

Phase A 不支持全量真实回填，也不接入周热点；历史批量回填留到 Phase B。

### Method family Phase B（shadow only）

```powershell
$env:EMBEDDING_ENABLED='1'
& $py main.py method-family-init --embed-prototypes
& $py main.py method-family-shadow --sync --limit 100
& $py main.py method-family-batch submit
& $py main.py method-family-batch status --job-id <job-id>
& $py main.py method-family-batch ingest --job-id <job-id>
& $py main.py method-family-gold-export --size 400
Remove-Item Env:EMBEDDING_ENABLED
```

`method-family-batch ingest` 在结果完整写入本地 cache 后，默认删除该任务创建的百炼远端文件；
调试时可加 `--keep-remote-files`。Phase B assignment 始终为 `review`，不会进入用户可见周热点。

### Method family Phase C0（Gold 与离线校准）

```powershell
& $py main.py method-family-gold-validate `
  --input output/method_family_gold_method-family-v1.csv `
  --expected-sha256 508ebebb1008990ca75b833d8e0c26dbbc4422201bbedbdfa31469fa0507a87c
& $py main.py method-family-gold-import `
  --input output/method_family_gold_method-family-v1.csv `
  --expected-sha256 508ebebb1008990ca75b833d8e0c26dbbc4422201bbedbdfa31469fa0507a87c `
  --reviewer expert-v1
& $py main.py method-family-calibrate `
  --gold-set-id gold-method-family-v1-508ebebb1008990c `
  --output output/method_family_calibration_method-family-v1.json
& $py main.py method-family-rules-evaluate `
  --gold-set-id gold-method-family-v1-508ebebb1008990c `
  --output output/method_family_rules_method-family-v1.json
& $py main.py method-family-policy-preview `
  --gold-set-id gold-method-family-v1-508ebebb1008990c `
  --calibration-id cal-b9b3ec1c1122918f16827424 `
  --ruleset-id rules-4444805f9d592b1a7610271b `
  --output output/method_family_policy_preview_method-family-v1.json
& $py main.py method-family-review-queue `
  --gold-set-id gold-method-family-v1-508ebebb1008990c `
  --calibration-id cal-b9b3ec1c1122918f16827424 `
  --ruleset-id rules-4444805f9d592b1a7610271b `
  --target-paper-coverage 0.80 `
  --output output/method_family_review_queue_coverage-v1.csv
& $py main.py method-family-gold-extension-import `
  --input output/method_family_review_queue_coverage-v1.csv `
  --queue-id queue-70bf2cf4b793f4ff8e720d42 `
  --reviewer expert-coverage-v1 --rank-start 1 --rank-end 200 `
  --expected-sha256 be65e676493243133f9f9f3c271c925095a1b77595cf76c7389b6c2fe05573c9
```

Gold 导入以文件 SHA-256 幂等，原 CSV 不会被改写。当前文件的空 primary + `[reject]` 会规范化为
`unknown`；其他空 primary 会被拒绝。校准只生成不可变审计记录和 JSON 报告，不创建 release、不写
`accepted`，也不需要调用 Embedding API。规则评估采用 calibration 选规则、holdout 一次验收；未获准的
高优先级规则会阻断低优先级回退。当前 v2 规则 holdout precision 为 97.96%，但分层策略的论文覆盖率
只有 51.38%，低于 80% 门槛，因此 preview 状态为 `coverage_rejected`，每周热点继续使用原有平铺榜。
`method-family-review-queue` 以未覆盖 PMID 的边际增益做确定性贪心排序；当前达到 80% 的理论投影需
1,434 条新增有效 primary 标签。该队列用于人工覆盖扩充，不得作为新的独立模型 holdout。
前 200 条实标结果为 143 个 family、57 个 `[reject] → unknown`、12 个 secondary，实际新增覆盖
278 篇，paper coverage 从 51.38% 升至 56.24%。导入器会核对所有不可编辑队列字段，并按文件和标签
快照生成不可变 extension；不会写 `accepted`。

模型差距队列会在不可变队列元数据中冻结 `base_model_id`。后续分批导入时，覆盖增益以该模型的训练标签快照和已接受预测为基线重算，不回退到早期规则/阈值 preview 的覆盖口径。

### Gap / 方案 / 数据景观

```powershell
& $py main.py bootstrap-landscape         # 已有缓存则跳过
& $py main.py bootstrap-landscape --force # 强制重载（慢，约 20–30 分钟）
& $py main.py gap-debate --focus "nasopharyngeal carcinoma" --top 6 -o output/gap_debate_report.md
& $py main.py gap-debate --no-ops-memory --no-ops-persist
& $py main.py idea-pipeline --focus "digital pathology" --top 3 -o output/idea_pipeline_report.md
```

### 一键建库（Python）

```powershell
& $py main.py run-db --since-days 14 --core-only
& $py main.py run-db --skip-enrich --limit 30
& $py main.py run-all --limit 30          # fetch→fulltext→extract→build→analyze
```

---

## 3. 维护脚本 `scripts/`

在 `fulltext_workflow/` 下执行：

```powershell
# 重置「已抽取但无 relations」的论文（跳过勘误文）
& $py scripts/reset_empty_extraction.py
& $py scripts/reset_empty_extraction.py --dry-run

# 重置全部已抽取论文，准备重抽（慎用）
& $py scripts/reset_extraction.py --dry-run
& $py scripts/reset_extraction.py

# PMC 缓存 PMID/DOI 错配：预览 / 清除错配全文
& $py scripts/fix_pmc_mismatch.py --dry-run
& $py scripts/fix_pmc_mismatch.py

# 抽取质量基线（库内 Method 等 top 统计）
& $py scripts/compare_extraction_quality.py

# Method / Disease 严格同义词回填（默认只预演）
& $py scripts/merge_entity_aliases.py
& $py scripts/merge_entity_aliases.py --apply

# ── Ops memory（ops_runs / ops_gap_items / ops_proposals）──
# 默认仅预览；不影响 papers / KG / hotspot
& $py scripts/clear_ops_memory.py
& $py scripts/clear_ops_memory.py --yes
& $py scripts/clear_ops_memory.py --focus "breast cancer" --yes
& $py scripts/clear_ops_memory.py --yes --delete-files   # 同时删引用的 md

# 清空整个 kg_fulltext.db（删文件并重建空表；不动 raw/）
& $py scripts/clear_database.py           # 预览
& $py scripts/clear_database.py --yes     # 确认清空

# 补全历史 proposal 的 gap_item_id / status / proposal_path（一次性）
& $py scripts/backfill_ops_proposals.py
```

| 脚本 | 作用 |
|------|------|
| `reset_empty_extraction.py` | 重置抽取完成但无三元组的论文 |
| `reset_extraction.py` | 重置全部已抽取结果（重抽） |
| `fix_pmc_mismatch.py` | 修复 PMC XML 与 PMID/DOI 错配 |
| `compare_extraction_quality.py` | 抽取质量 baseline 统计 |
| `merge_entity_aliases.py` | 预演/应用 Method、Disease 严格同义词合并与关系重连 |
| `clear_ops_memory.py` | 清空周常 ops memory（可按 focus） |
| `clear_database.py` | 清空整个 `kg_fulltext.db`（需 `--yes`；不动 `raw/`） |
| `backfill_ops_proposals.py` | 回填 `ops_proposals` 缺失字段 |
| `pilot_reconcile_qa.py` | Pass 2 pilot 审阅 CSV（active/superseded datasets、platform_hit） |

---

## 4. 推荐组合拳

### 每周更新

```powershell
.\run_pipeline.ps1 -Stage weekly
# weekly 已含 compute-gap-lifecycle；可直接辩论
& $py main.py gap-debate --focus "your topic" -o output/gap_debate_report.md
.\run_gap_ui.ps1
```

### 首次全量建库

```powershell
.\run_pipeline.ps1 -Stage all   # 已含 compute-gap-lifecycle
& $py main.py bootstrap-landscape --force   # 若需要可行性分析
```

### 只想看库状态 / 试跑 UI

```powershell
.\run_pipeline.ps1 -Stage stats
.\run_gap_ui.ps1
```

---

## 5. 环境变量速查（`.env`）

| 变量 | 用途 |
|------|------|
| `PUBMED_EMAIL` / `PUBMED_API_KEY` | PubMed |
| `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` | LLM |
| `LLM_MODEL_EXTRACT` | 章节抽取模型 |
| `LLM_MODEL_AGENT` | gap / idea / hotspot-brief |
| `FETCH_EDAT_DAYS` | fetch 默认 EDAT 窗口 |
| `PATHOLOGY_API_KEY` | 方信 landscape / 可行性 |
| `PATHOLOGY_BOOTSTRAP_MAX_DISEASES` | landscape 最多病种（默认 30） |
| `OPS_MEMORY_ENABLED` | Gap 周常记忆软去重 |
| `V03_OK_MIN_PAPERS` | 公开数据集 V-03：无 alias 时达到 OK 的最少相关论文数（默认 3） |

---

## 6. 相关文档

| 文件 | 内容 |
|------|------|
| [PIPELINE.md](PIPELINE.md) | 分阶段流水线详解 |
| [gap_ui_guide.md](gap_ui_guide.md) | Streamlit UI 操作 |
| [README.md](README.md) | 沙盒概述与模块表 |

---

## 7. Method-family 独立盲测与发布

```powershell
# 1) 生成不含任何模型提示的独立盲测集
python main.py method-family-blind-export `
  --gold-set-id <gold-set-id> --size 200 --output output/method_family_blind_eval-v1.csv

# 2) 用 Gold + coverage extensions + 已退役盲测训练本地监督层（只读 embedding 缓存）
python main.py method-family-model-train `
  --gold-set-id <gold-set-id> --ruleset-id <ruleset-id> --output output/model.json
python main.py method-family-model-preview --model-id <model-id>

# 3) 专家完成盲测后冻结提交并评估
python main.py method-family-blind-import `
  --input <annotated.csv> --blind-set-id <blind-set-id> --reviewer <reviewer>
python main.py method-family-blind-evaluate `
  --model-id <model-id> --submission-id <submission-id> --output output/blind_eval.json

# 4) 评测完成后可显式退役该盲测，并仅用于未来模型训练
python main.py method-family-blind-promote `
  --evaluation-id <completed-evaluation-id> --promoted-by <reviewer>

# 5) 只有新一代盲测和 80% 论文覆盖双门禁均通过时才能构建、激活 release
python main.py method-family-release-build `
  --model-id <model-id> --evaluation-id <evaluation-id> --output output/release.json
python main.py method-family-release-activate `
  --release-id <release-id> --activated-by <operator>
```

在明确接受风险时，可执行受控人工豁免发布。该路径仍要求训练期精度、论文加权精度、unknown 零误接和支持类别精度门槛通过，并将审批人、原因、实际覆盖率及被豁免门槛写入不可变 release：

```powershell
python main.py method-family-release-build `
  --model-id <model-id> --evaluation-id <evaluation-id> `
  --manual-override --approved-by <operator> `
  --approval-reason <reason> --minimum-paper-coverage 0.70 `
  --output output/release_override.json
```

严格规则和监督词组会在完整的折外训练标签上再次复核；未达到支持度、95% 精度或 unknown 零误接收要求的固定来源自动回退到 embedding。家族阈值先保证每个有支持类别至少 85% 精度，再逐类收紧到整体及论文加权精度均至少 95%。模型携带训练标签快照，禁止旧模型在 Gold 后续扩展后静默改变结果。

盲测标签在当前评测期间不会进入训练集。评测完成后，可通过 `method-family-blind-promote` 显式退役并晋升为未来训练数据；原评测不可变，相关方法永久排除于后续盲测，新模型必须使用新一代独立盲测。Release 与激活记录均为追加式不可变快照；“每周热点 → 方法类别”只读取最新已激活 release，没有 release 时明确显示未上线，不回退到 shadow 预测。
