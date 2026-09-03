# H&E 预测 Ki67 / 类似 IHC 方法库（起步包）

本目录聚焦 **从 H&E 组织病理图像推断 Ki-67 或类似 IHC/生物标志物状态**，是 `virtual-staining-method-summary/` 的 **应用切面**，不替代虚拟染色全库。

## 双轨定义

| 轨道 | 任务 | 代表证据 |
|------|------|----------|
| **轨 A：虚拟染色** | H&E → IHC/功能染色图像，再计 labeling index 等 | 链至虚拟染色库逐篇总结 |
| **轨 B：非生成式预测** | 直接从 H&E 回归/分类 Ki67、HER2、PD-L1 等 | 本地库检索 + 清单标注 |

## 目录说明

| 文件 | 用途 |
|------|------|
| `screening_protocol.md` | 双轨纳入/排除 |
| `selected_papers.jsonl` | 核心入选（12 篇：虚拟染色 6、直接预测 6） |
| `expansion_candidates.jsonl` | 待补全文或扩库候选 |
| `he_ihc_prediction_overview.md` | 短总览 |

## 相关资源

- 虚拟染色全库：`../virtual-staining-method-summary/`
- 检索查询组：`search_queries.py` 中 `ihc_biomarker_prediction_ai`、`virtual_staining_image_translation`
- MIL 聚合对照：`../mil-method-summary/`（PD-L1 等 slide 级预测）
- 本研究定向综述：`../docs/reviews/he_wsi_ki67_mil_background_review.md`
