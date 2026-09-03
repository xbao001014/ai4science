# 鼻咽癌病理 AI 筛选方案

## 1. 目标

从本地 focus 核与 `nasopharyngeal_carcinoma_pathology_ai` 检索结果中，筛选能代表 NPC 病理 AI 演进的首批论文，按 **任务分轨** 组织短总览。

## 2. 纳入标准

- 研究对象含鼻咽癌（nasopharyngeal carcinoma / NPC）；
- **核心入选：** 组织病理、细胞病理、H&E/IHC/EBER 切片、WSI 或数字病理为主要输入模态；
- 任务含诊断、分类、分割/检测、弱监督 WSI、TIL/微环境定量、虚拟染色、IHC 数字定量、pathomics/radiopathomics（病理侧为必要组成）；
- 原始研究论文（非致编辑信）。

## 3. 排除 / 降级

| 类型 | 处理 |
|------|------|
| 纯 PET/MRI 放射组学，无 WSI 病理建模 | `expansion_candidates`，role=imaging_primary |
| 纯 SEER/临床变量生存预测 | Reserve，role=clinical_ml |
| 血清 IFA 等非组织病理 | Reserve |
| 综述 | 背景引用，不进核心清单 |
| 致编辑信 | Exclude |

## 4. 任务分轨

1. **诊断 / 分类：** patch 或 WSI 级 NPC vs 良性/炎症。
2. **弱监督 WSI：** 仅 slide 标签的 Transformer/MIL 分类。
3. **微环境 / TIL：** H&E WSI 淋巴细胞定量与预后。
4. **虚拟染色 / IHC 辅助：** H&E→EBER、IHC 辅助标注、IHC 蛋白定量。
5. **Pathomics / Radiopathomics：** WSI 深度特征 ± MRI，病理侧必须为建模输入之一。

## 5. 优先级

- **P0：** 病理模态为主、任务清晰、可复现价值高（诊断、TIL、弱监督 WSI）。
- **P1：** 多模态但以 WSI/pathomics 为关键组成，或 IHC 数字定量。
- **P2 / Reserve：** 影像为主或证据待补。

## 6. 评价边界

- 不做跨中心 AUC 排名；注明单中心/多中心与验证类型。
- NPC 非角化型为主，组织学相似性高——需强调 **数据增强、类别不平衡、EBV/TIL 微环境** 等域特异挑战。
