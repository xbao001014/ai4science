# Method / Disease 论文级注释：30 篇结果

## 样本与运行

- 固定 `entity_context_30_pmids.txt` 中的 30 篇原文。冻结前后每篇原文 SHA-256 均相同；30 篇都完成重抽取。
- 原数据库冻结为 1,006 条活跃关系；在独立 SQLite 副本中重抽取后为 918 条。生产库中的这 30 篇未重抽取，Method-family 发布版本未修改。
- 试验开启 `EXTRACT_ENTITY_MENTION_ANNOTATIONS`，保持此前效果不佳的宽泛 Method 缩写提示关闭。运行后对缺少注释的 Pass 2 证据作确定性回填，并剔除不在病名中的或与整个病名相同的限定词。
- 没有人工标注；以下是可追溯性和名称变化统计，不能解释为准确率或召回率。

## 实体对照

| 类型 | 修改前 | 修改后 | 新增键 | 移除键 |
|---|---:|---:|---:|---:|
| Method | 398 | 393 | 154 | 159 |
| Disease | 88 | 80 | 18 | 26 |
| 全部关系 | 1,006 | 918 | 409 | 497 |

509 个 `(PMID, relation, entity type, normalized name, metric value)` 键在两次结果中相同。`changes_only.csv` 提供逐条证据对照。名称变化既可能来自新提示，也可能来自重抽取波动或其他已经存在的代码变化；本次没有仅改变注释提示的独立重抽取对照组，因此不能把全部差异归因于本次改造。

## 注释结果

- 修改前冻结结果没有独立论文级提及记录，也没有保存 `context_text` 或 Method 全称。
- 修改后有 **639** 条活跃 Method / Disease 证据提及，其中 **512 Method**、**127 Disease**；**639/639** 的证据状态为 `located`。其中 220 条来自既有 Pass 2 证据的确定性回填。
- **24** 条 Method 提及和 **10** 条 Disease 提及有同篇论文明确写出的全称；34 条定义原句均可在原文定位。例子包括 `GCN → graph convolutional network`、`UC → ulcerative colitis`。
- **37** 条 Disease 提及保留了 **41** 个限定词。严格校验共剔除 **21** 个只在证据中出现、与病名无关或重复整段病名的候选限定词。
- 全部 639 条提及保持 `resolution_status=unresolved`：注释提供后续消歧依据，没有自动断言跨论文概念相同。

## 自动抽查发现的风险

逐条对照出现可能丢失病种细节的变化，例如 `breast invasive carcinoma → breast carcinoma`、`colorectal adenocarcinoma → colorectal cancer`，以及 `infectious oesophagitis → oesophagitis`。Method 新增项中仍出现 `endoscopists` 一类可疑名称。限定词提示也曾把队列描述当作疾病限定词，因此加了病名与定位证据双重包含校验；这个校验只能提高格式和来源可靠性，不能验证临床语义。

## 结论与状态

这阶段完成了**可定位的论文级注释存储**，并让 Method／Disease 缩写拥有独立于全库实体名的明确全称位置。30 篇试验支持可追溯性改善；没有证据证明实体抽取或归类准确率改善。按后续用户指示，`EXTRACT_ENTITY_MENTION_ANNOTATIONS` 已默认开启；注释仍不自动合并歧义缩写或疾病亚型。

## 后续接入每周热点

每周热点的 Method／Disease 榜单现展示论文内明确全称、原始写法、注释来源篇数和来源 PMID；展开区显示证据句与局部语境。最近 90 天的生产库历史证据已做确定性回填，新增 3,330 条论文级提及；旧论文未重新调用抽取模型，因此历史疾病限定词可能为空。新抽取会启用限定词提示，并继续执行病名与证据双重校验。热点排序、分数和跨论文归类均不受注释字段影响。
