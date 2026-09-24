# Method / Disease 论文级注释：30 篇隔离试验

## 本次改造

- `entity_mentions` 将每条有定位证据的 Method / Disease 提及与全库 `entities` 分开保存。`entity_id` 只记录当前旧系统的规范化目标，`resolution_status=unresolved`，不表示已完成跨论文消歧。
- Method 保存抽取时的名称、论文内明确写出的全称、定义原句和可选的论文级角色提示。Disease 保存抽取时的名称、明确全称以及 `site / histology / molecular / stage / other` 限定词。
- 限定词必须同时出现在抽取的 Disease 名称和定位证据中。没有明确证据时留空；罕见或歧义疾病不强制归入宽泛父类。
- 摘要／段落 Pass 1 写入注释；全文 Pass 2 的 `SURVEYS_METHOD` 和 `COVERS_DISEASE` 也写入，旧证据可用确定性回填。定义表在抽取段落前从同篇论文收集，与段落抽取顺序无关。
- 注释提示由 `EXTRACT_ENTITY_MENTION_ANNOTATIONS` 控制。隔离试验开启；旧的宽泛 Method 缩写提示保持关闭，因为此前 30 篇试验发现它混入非 Method 缩写并有名称退化。

## 试验方法

固定使用 `entity_context_30_pmids.txt` 中的 30 篇原文。先从原数据库冻结论文和实体关系及原文 SHA-256，然后复制到独立 SQLite 数据库，重抽取这 30 篇，最后校验原文 SHA-256 未变并输出逐条实体对照与注释明细。

输出文件：`comparison/summary.json`、`comparison/changes_only.csv`、`comparison/short_methods.csv`、`mentions_after.csv`、`annotation_summary.json`。计数和新增／删除只描述抽取变化，不代表准确率；本轮按要求不做人工标注。

## 运行

从 `fulltext_workflow/` 执行（目标数据库必须不存在）：

```powershell
..\.venv\Scripts\python.exe evals\run_entity_mentions_30.py `
  --source-db data\kg_fulltext.db `
  --eval-db ..\tmp\entity_mentions_30\after.db `
  --pmids evals\entity_context_30_pmids.txt `
  --output ..\tmp\entity_mentions_30\results
```

若需要在抽取完成后重算严格证据校验和报告，可执行 `evals\finalize_entity_mentions_30.py`，指定已有试验数据库、PMID 文件和结果目录。
