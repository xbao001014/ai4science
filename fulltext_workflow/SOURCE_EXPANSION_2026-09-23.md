# Europe PMC 与 arXiv 来源扩展入库记录（2026-09-23）

## 范围

- 使用现有 `search_queries.py` 的 18 个启用主题组，年份 2015–2026。
- 运行 `main.py fetch --sources europepmc,arxiv --since-days 0`。
- Europe PMC 查询 `TITLE_ABS` 与 `FIRST_PDATE`，仅导入 MED/PPR；arXiv 查询标题、摘要等字段并按投稿日过滤。两路结果均以本地标题、摘要布尔匹配及病理领域线索再次筛查。
- 每组最多处理 2,000 条，与现有 PubMed 查询上限一致。此次 Europe PMC 各组均未达到上限；arXiv 各组也未达到上限。

## 实际入库

通过抓取前 SQLite 快照与抓取后生产库按 `papers.id` 比较：

| 指标 | 数量 |
|---|---:|
| 抓取前论文 | 9,928 |
| 抓取后论文 | 12,597 |
| 独立新增论文 | 2,669 |
| Europe PMC 新增：无 PMID 预印本 | 1,077 |
| Europe PMC 新增：有 PMID | 21 |
| arXiv 新增：无 PMID | 1,571 |
| 两路来源共同映射到同一论文 | 129 |
| 新增记录有摘要且年份在 2015–2026 | 2,669 |

Europe PMC 原始处理命中 12,834 条，来源 ID 映射到 8,018 篇独立论文；arXiv 原始处理命中 5,246 条，来源 ID 映射到 1,700 篇独立论文。原始命中可重复落入多个主题组，也包含过滤掉的离题结果，因此不能直接当作新增论文数。

抓取结束后抽取队列共有 2,677 篇，其中 2,648 篇为本次新增的无 PMID 文献，另 21 篇本次新增且有 PMID；其余 8 篇是原队列积压。此次仅完成元数据入库，没有批量运行 LLM 抽取或重新生成图谱。

## ID 与分析格式

- `papers.pmid` 只存真实 PMID；arXiv ID 和 Europe PMC PPR ID 保存在 `paper_external_ids`。
- 无 PMID 论文的 `papers.source_key` 是稳定证据键，例如 `arxiv:2609.12345`、`europepmc:PPR:PPR1252153`；后续获得 PMID 时保留原证据键。
- 以来源 ID、PMID、DOI 做精确去重，不凭相似标题自动合并预印本与期刊版。不同版本标题接近但没有共同标识符时仍需人工核对。
- 现有关系、图谱、周热点与 Gap 分析按 `COALESCE(source_key,pmid)` 关联。无 PMID 文献先以摘要分析；有 PMID 文献可走原全文抓取路径。

## 复核

- 扩源相关和回归测试 40 项通过；新增作者、期刊关联测试通过。
- 生产库已迁移，且 `get_papers_for_extraction()` 可读取新来源记录；抽样检查新记录标题、来源键和作者关联。
- 抓取前数据库快照位于 `fulltext_workflow/output/source_expansion_2026-09-23/kg_before_external_sources.db`。
