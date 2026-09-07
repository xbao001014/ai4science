# Phase B: Method Family Shadow Backfill

**Date:** 2026-09-05  
**Status:** Implemented and verified; authoritative gold received  
**Depends on:** Phase A embedding client/cache

## Outcome

Phase B 为 active `APPLIES_METHOD` 方法生成 13 类 method-family 的 top-3 候选，但全部写成
`status=review`、`source=embedding_shadow`。本阶段不进入周热点、UI 或 accepted 统计。

## Taxonomy and prototypes

目录版本为 `method-family-v1`：MIL、CNN、Transformer、基础模型、图神经网络、表征学习、
生成模型、传统统计与机器学习、生物信息学与组学、图像处理、多模态融合、可解释性、分析工具与平台。

每类使用英文定义和 4–5 个正例分别生成向量，再对该类 5–6 个向量求归一化 centroid。总计
68 个 prototype inputs。prototype 通过同步 API 生成并进入 Phase A cache。

## Hybrid shadow ranking

100 条纯 embedding 样本出现 `foundation_model` 泛化吸附：42% 被分入该类，平均 top1/top2 margin
仅 0.027。原因是论文上下文普遍包含 `model`，而不代表基础模型。

因此候选排序改为：

```text
ranking_score = cosine_similarity
              + high_precision_name_cue
              + compatible_method_role_prior
              - unsupported_foundation_model_penalty
```

数据库同时保留：

- `similarity`：未经修改的 cosine；
- `confidence`：当前 provisional ranking score；
- `margin`：混合排序 top1 - top2；
- `candidate_rank`：1–3。

该分数尚未经过 gold set 校准，所以无论多高都保持 `review`。修正后的同一批 100 条样本中，
`foundation_model` 降为 1%，平均 margin 提升到 0.122。

## Batch workflow

百炼 Batch JSONL 每行包含唯一 `custom_id=method-{entity_id}`、`POST /v1/embeddings` 和
`text-embedding-v4`/768 维请求。流程：

```text
submit → local job/item checkpoint → upload JSONL → create remote batch
→ status polling → download output/error → validate every vector
→ local cache → top-3 shadow assignments → delete only this job's remote files
```

输入 JSONL 本地临时文件上传后立即删除；远端 input/output/error 文件只在成功摄取后清理。
批任务状态和 file IDs 存在 `embedding_batch_jobs`，可跨进程恢复。

## Full Batch verification

2026-09-05 完成百炼 Batch `batch_c4160b5b-6eb6-4a5d-a13b-4fa82dccc1e3` 的摄取和验收：

- Batch 返回 10,519/10,519 条有效向量，0 条失败，实际计费 tokens 为 1,004,790；
- 加上此前同步缓存后，active `APPLIES_METHOD` 的 10,619 个 distinct Method 全部命中 cache，
  coverage 为 100%，missing vectors 为 0；
- 成功清理该任务的远端 input/output 两个文件；远端没有 error file；
- 每个方法保留 1 个 primary 和 3 个 current review candidates，共 10,619 个 primary、31,857 条
  `status=review` 记录；此前 100 条试运行留下 83 条 `status=stale` 历史候选；
- `status=accepted` 为 0，没有提前进入 accepted/周热点统计；
- embedding 相关表无 API Key/secret/raw input 字段；敏感值模式和完整 input 格式扫描均为 0 命中；
- Phase A/B 专项测试 22/22 通过。

Primary family 分布如下：

| Family | Methods |
|---|---:|
| image_processing | 3,581 |
| mil | 1,460 |
| bioinformatics_omics | 1,287 |
| cnn | 1,119 |
| multimodal_fusion | 957 |
| classical_statistics | 889 |
| other_tooling | 383 |
| transformer | 239 |
| representation_learning | 177 |
| generative_model | 162 |
| graph_neural_network | 159 |
| explainability | 124 |
| foundation_model | 82 |

全量平均 top-1 similarity 为 0.547253，平均 top1/top2 margin 为 0.060356。这些值只用于
shadow review 和后续 gold calibration，不能直接解释为已校准置信度。

## Gold template

`method-family-gold-export --size 400` 输出 UTF-8 CSV，按以下四个 strata 等额抽样：

1. 高频方法；
2. `method_role=unknown`；
3. 不透明短名称；
4. 最近年份方法。

CSV 带 top-3 建议和原始分数，`gold_primary`、`gold_secondary`、`review_notes` 为空，供专家标注。
没有人工 gold 标签前，不允许把 review 自动提升为 accepted。

## Commands

```powershell
$env:EMBEDDING_ENABLED='1'
& $py main.py method-family-init --embed-prototypes
& $py main.py method-family-shadow --sync --limit 100
& $py main.py method-family-batch submit
& $py main.py method-family-batch status --job-id <local-job-id>
& $py main.py method-family-batch ingest --job-id <local-job-id>
& $py main.py method-family-gold-export --size 400
```

去掉一次性环境变量后仍回到默认关闭状态。

## Release gates to Phase C

- 全量 active Method cache coverage ≥99%（已达到 100%）；
- 所有 current assignment 均为 review，无 accepted 泄漏（已通过）；
- 400 条 effective gold labels 已确认（366 个 known family + 34 个 `[reject]`/unknown，已完成）；
- 自动 accepted precision ≥90%，目标 ≥95%；
- rule/embedding 冲突单独审计；
- taxonomy/model/input 版本可追踪；
- family board 上线前按 distinct PMID union 验证计数。
