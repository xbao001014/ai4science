# 病理多模态方法总结

本目录用于积累计算病理学多模态方法论文。已经完成候选筛选，并对首批
25 篇入选论文全部生成了逐篇方法总结。

## 当前文件

- `screening_protocol.md`：研究范围、纳入/排除规则及优先级定义。
- `selected_papers.jsonl`：第一批入选论文的机器可读清单，每行一篇论文。
- `screening_report.md`：面向阅读的筛选结果、分组与精读顺序。
- `excluded_candidates.md`：容易因关键词或高引用误入的论文及排除原因。
- `method_summaries/`：已完成的逐篇方法总结及索引。
- `multimodal_methods_overview.md`：基于全部入选论文的多模态融合方法综述。
- `summary_manifest.json`：本轮生成结果、源章节规模和文件名。
- `generate_summaries.py`：从本地数据库按模板生成总结的可复用脚本。
- `generate_manual_pdf_summaries.py`：从人工补充的 PDF 生成总结，并合并更新清单。
- `generate_multimodal_overview.py`：从逐篇总结增量生成总览综述的脚本。
- `manual_papers/`：人工补充且已按 PMID、DOI 命名的原始 PDF。
- `expansion_candidates.md`：下一阶段多模态候选及基线清单。
- `expansion_candidates.jsonl`：机器可读扩充队列。
- `coverage_gap_matrix.md`：现有覆盖、基线缺口和执行批次。

## 数据说明

- 文献元数据、摘要、全文状态和引用数均来自本地项目数据库。
- `citation_count` 的来源字段为 OpenAlex；这是本地数据库快照，不应解释为实时引用数。
- `full_text_status=available` 表示数据库中已有可读全文章节；`pdf_available` 表示已有 PDF/MinerU 来源；
  `jats_unavailable` 在本轮筛选中按“摘要证据为主”处理。
- PMID 是本方法库的主标识，DOI 用于外部核验和去重。

## 后续总结格式

逐篇总结将参照 `D:/agent/mil-method-summary/method_summary_template.md`。
“实现伪代码”标题保留，但代码块留空；所有无法从论文确认的信息写“未说明”，不自行补全。
