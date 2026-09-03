# 排除与邻接候选

以下论文容易因标题、摘要关键词或引用数较高而误入多模态方法库。本文件保留筛选轨迹，避免后续周更时重复判断。

## 明确排除

| PMID | 引用快照 | 论文 | 判定 | 原因 |
|---|---:|---|---|---|
| 30224757 | 2916 | Classification and mutation prediction from non-small cell lung cancer histopathology images using deep learning | Exclude | 推理输入只有病理图像；突变是预测标签，不是联合输入模态。 |
| 33719168 | 116 | A Deep Learning Approach to Diagnostic Classification of Prostate Cancer Using Pathology-Radiology Fusion | Exclude | 模型输入为 MRI，病理仅用于提供诊断标签；不属于推理阶段的病理—放射融合。 |
| 32453636 | 97 | Deep-Learning-Based Characterization of Tumor-Infiltrating Lymphocytes in Breast Cancers From Histopathology Images and Multiomics Data | Exclude | 核心是病理 TIL 分割和图像特征—组学相关性分析，没有统一多模态预测模型。 |
| 37693852 | 364 | Multimodal data fusion for cancer biomarker discovery with deep learning | Exclude | 属于方法综述/观点性质论文，适合综述背景，不作为逐篇原创方法总结对象。 |

## Reserve：跨模态邻接方向

| PMID | 引用快照 | 论文 | 暂不纳入原因 | 后续用途 |
|---|---:|---|---|---|
| 32572199 | 521 | Integrating spatial gene expression and breast tumour morphology via deep learning | 主要任务是从组织形态预测空间表达，联合输入/融合属性弱于本期核心定义。 | 可在“跨模态预测与空间组学”小节作为 OmiCLIP 等方法的前序工作。 |

## 判定备注

- “预测另一模态”与“融合多个模态”需要分开：前者可能是重要跨模态学习，但不一定属于联合融合模型。
- “pathology-radiology fusion”若实际只输入 MRI、以病理结果为标签，也不纳入病理多模态方法库。
- 综述可用于补充方法谱系和引用追踪，但不占用逐篇方法总结名额。

