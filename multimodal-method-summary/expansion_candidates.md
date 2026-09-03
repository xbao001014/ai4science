# 病理多模态候选扩充清单

本轮重点不是继续堆叠视觉语言基础模型，而是补齐病理—组学方法主干、单模态对照、通用融合基线、缺失模态和公平评价。

| 优先级 | 年份 | 候选 | 填充方向 | 角色 | 引用 | 全文 | 下一步 |
|---|---:|---|---|---|---:|---|---|
| P0 | 2023 | Quilt-1M: One Million Image-Text Pairs for Histopathology. (PMID 38742142) | `pathology_text_dataset` | dataset | 55 | manual_pdf_available | 已生成总结 |
| P0 | 2025 | Interpretable Multimodal Fusion Model for Bridged Histology and Genomics Survival Prediction in Pan-Cancer. (PMID 40051298) | `pathology_genomics_interaction` | method | 14 | available | 可直接生成总结 |
| P0 | 2026 | Handling missing modalities in multimodal survival prediction for non-small cell lung cancer. (PMID 42332139) | `missing_modality` | method | 1 | pdf_available | 可直接生成总结 |
| P0 | 2018 | [Attention-based Deep Multiple Instance Learning](https://arxiv.org/abs/1802.04712) | `unimodal_mil_control` | baseline_control |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2021 | [Multimodal Co-Attention Transformer for Survival Prediction in Gigapixel Whole Slide Images](https://openaccess.thecvf.com/content/ICCV2021/html/Chen_Multimodal_Co-Attention_Transformer_for_Survival_Prediction_in_Gigapixel_Whole_Slide_ICCV_2021_paper.html) | `pathology_genomics_interaction` | pathology_method |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2021 | [Learning Transferable Visual Models From Natural Language Supervision](https://arxiv.org/abs/2103.00020) | `generic_vlm` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2021 | [Data-efficient and weakly supervised computational pathology on whole-slide images](https://www.nature.com/articles/s41551-020-00682-w) | `unimodal_mil_control` | baseline_control |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2023 | [Multimodal Optimal Transport-based Co-Attention Transformer with Global Structure Consistency for Survival Prediction](https://openaccess.thecvf.com/content/ICCV2023/html/Xu_Multimodal_Optimal_Transport-based_Co-Attention_Transformer_with_Global_Structure_Consistency_for_ICCV_2023_paper.html) | `pathology_genomics_interaction` | pathology_method |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2024 | [Modeling Dense Multimodal Interactions Between Biological Pathways and Histology for Survival Prediction](https://openaccess.thecvf.com/content/CVPR2024/html/Jaume_Modeling_Dense_Multimodal_Interactions_Between_Biological_Pathways_and_Histology_for_CVPR_2024_paper.html) | `pathology_genomics_interaction` | pathology_method |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2024 | Towards a general-purpose foundation model for computational pathology. (PMID 38504018) | `unimodal_wsi_control` | baseline_control | 1188 | pdf_available | 可直接生成总结 |
| P1 | 2024 | A whole-slide foundation model for digital pathology from real-world data. (PMID 38778098) | `unimodal_wsi_control` | baseline_control | 685 | available | 可直接生成总结 |
| P1 | 2024 | A pathology foundation model for cancer diagnosis and prognosis prediction. (PMID 39232164) | `unimodal_wsi_control` | baseline_control | 457 | pdf_available | 可直接生成总结 |
| P1 | 2023 | Vision-Language Transformer for Interpretable Pathology Visual Question Answering. (PMID 35358054) | `pathology_vqa_benchmark` | dataset_method | 52 | manual_pdf_available | 已生成总结 |
| P1 | 2026 | UroFusion-X: a unified multimodal deep learning framework for robust diagnosis, subtyping, and prognosis of urological cancers. (PMID 41554842) | `missing_modality` | method | 1 | available | 可直接生成总结 |
| P1 | 2017 | [Tensor Fusion Network for Multimodal Sentiment Analysis](https://aclanthology.org/D17-1115/) | `fusion_operator` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2021 | [TransMIL: Transformer based Correlated Multiple Instance Learning for Whole Slide Image Classification](https://proceedings.neurips.cc/paper/2021/hash/10c272d06794d3e5785d5e7c5356e9ff-Abstract.html) | `unimodal_mil_control` | baseline_control |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2022 | [CoCa: Contrastive Captioners are Image-Text Foundation Models](https://arxiv.org/abs/2205.01917) | `generic_vlm` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2023 | [Visual Instruction Tuning](https://arxiv.org/abs/2304.08485) | `generic_vlm` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2026 | A cancer-type-aware framework for robust multimodal survival prediction under missing modalities. (PMID 41870128) | `missing_modality` | method |  | available | 可直接生成总结 |
| P2 | 2025 | Comparing Computational Pathology Foundation Models using Representational Similarity Analysis. (PMID 40463538) | `controlled_benchmark` | benchmark | 2 | pdf_available | 可直接生成总结 |

共 20 项候选。通用方法生成精简基线卡；病理专用方法生成完整总结。
