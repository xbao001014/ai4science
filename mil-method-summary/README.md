# 计算病理 MIL 方法精选库（起步包）

本目录是 **MIL 小综述** 在本仓的精选索引与短总览，完整逐篇总结与 60+ 篇证据库位于旁系项目：

`D:/agent/mil-method-summary/`

## 目录说明

| 文件 | 用途 |
|------|------|
| `screening_protocol.md` | 精选纳入/排除与四阶段分类 |
| `selected_papers.jsonl` | 15 篇代表方法（含旁系 `summary_file` 外链） |
| `mil_methods_overview.md` | 可汇报用短综述（压缩旁系长稿） |

## 证据边界

- 范围：WSI 弱监督 / 多实例学习聚合与相关鲁棒训练。
- 不做跨数据集 AUC/C-index 排名；仅按机制演进与任务适配性归纳。
- `08_REMIX_MIL` 等材料科学误收条目不纳入病理 MIL 比较（旁系总览已标注）。

## 与旁系库关系

- 旁系 `MIL_methods_overview.md`：完整 61 篇索引级长综述。
- 本目录：面向方案撰写与汇报的 **12–15 篇精选 + 短叙事**。
- 需要逐篇细节时，沿 `selected_papers.jsonl` 中的 `summary_file` 跳转旁系 `method_summaries/`。
