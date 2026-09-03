# 病理分割候选扩充清单

候选按 P0（优先补齐主干）、P1（扩大覆盖）、P2（观察）分层。全文状态来自本地数据库当前快照。

| 优先级 | 年份 | 候选 | 轨道 | 角色 | 引用 | 全文 | 下一步 |
|---|---:|---|---|---|---:|---|---|
| P0 | 2017 | DCAN: Deep contour-aware networks for object instance segmentation from histology images. (PMID 27898306) | `pathology_instance` | method | 514 | manual_pdf_available | 已生成总结 |
| P0 | 2016 | An Automatic Learning-Based Framework for Robust Nucleus Segmentation. (PMID 26415167) | `classical_nuclei` | method | 357 | pdf_available | 可直接生成总结 |
| P0 | 2024 | CellViT: Vision Transformers for precise cell segmentation and classification. (PMID 38507894) | `transformer_foundation` | method | 289 | manual_pdf_available | 已生成总结 |
| P0 | 2021 | Deep Learning Methods for Lung Cancer Segmentation in Whole-Slide Histopathology Images-The ACDC@LungHP Challenge 2019. (PMID 33216724) | `benchmark` | challenge | 154 | pdf_available | 可直接生成总结 |
| P0 | 2020 | NuClick: A deep learning framework for interactive segmentation of microscopic images. (PMID 32769053) | `interactive_prompt` | method | 146 | manual_pdf_available | 已生成总结 |
| P0 | 2020 | Triple U-net: Hematoxylin-aware nuclei segmentation with progressive dense feature aggregation. (PMID 32712523) | `cross_stain_generalization` | method | 145 | manual_pdf_available | 已生成总结 |
| P0 | 2023 | One model is all you need: Multi-task learning enables simultaneous histology image segmentation and classification. (PMID 36410209) | `joint_detection_typing` | method | 138 | manual_pdf_available | 已生成总结 |
| P0 | 2025 | SegAnyPath: A Foundation Model for Multi- Resolution Stain-Variant and Multi-Task Pathology Image Segmentation. (PMID 40030236) | `prompt_foundation` | foundation_model | 9 | manual_pdf_available | 已生成总结 |
| P0 | 2025 | Evaluating cell AI foundation models in kidney pathology with human-in-the-loop enrichment. (PMID 41286516) | `benchmark` | external_validation | 4 | available | 可直接生成总结 |
| P0 | 2015 | [U-Net: Convolutional Networks for Biomedical Image Segmentation](https://arxiv.org/abs/1505.04597) | `generic_semantic` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2017 | [Mask R-CNN](https://openaccess.thecvf.com/content_ICCV_2017/html/He_Mask_R-CNN_ICCV_2017_paper.html) | `generic_instance` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2018 | [StarDist: Object Detection with Star-convex Shapes](https://arxiv.org/abs/1806.03535) | `microscopy_instance` | tool_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2021 | [Cellpose: a generalist algorithm for cellular segmentation](https://www.nature.com/articles/s41592-020-01018-x) | `microscopy_instance` | tool_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2016 | Locality Sensitive Deep Learning for Detection and Classification of Nuclei in Routine Colon Cancer Histology Images. (PMID 26863654) | `joint_detection_typing` | method | 1245 | pdf_available | 可直接生成总结 |
| P1 | 2016 | A Deep Convolutional Neural Network for segmenting and classifying epithelial and stromal regions in histopathological images. (PMID 28154470) | `tissue_semantic` | method | 461 | manual_pdf_available | 已生成总结 |
| P1 | 2021 | Development and evaluation of deep learning-based segmentation of histologic structures in the kidney cortex with multiple histologic stains. (PMID 32835732) | `tissue_semantic` | external_validation | 198 | manual_pdf_available | 已生成总结 |
| P1 | 2021 | Deep Learning-Based Segmentation and Quantification in Experimental Kidney Histopathology. (PMID 33154175) | `tissue_semantic` | clinical_pipeline | 181 | manual_pdf_available | 已生成总结 |
| P1 | 2021 | NucleiSegNet: Robust deep learning architecture for the nuclei segmentation of liver cancer histopathology images. (PMID 33190012) | `pathology_instance` | method | 174 | manual_pdf_available | 已生成总结 |
| P1 | 2017 | Segmentation and classification of colon glands with deep convolutional neural networks and total variation regularization. (PMID 29018612) | `gland_instance` | method | 138 | available | 可直接生成总结 |
| P1 | 2019 | An automatic nuclei segmentation method based on deep convolutional neural networks for histopathology images. (PMID 32903361) | `pathology_instance` | method | 88 | available | 可直接生成总结 |
| P1 | 2022 | TSFD-Net: Tissue specific feature distillation network for nuclei segmentation and classification. (PMID 35367734) | `joint_detection_typing` | method | 76 | manual_pdf_available | 已生成总结 |
| P1 | 2023 | Tubule-U-Net: a novel dataset and deep learning-based tubule segmentation framework in whole slide images of breast cancer. (PMID 36599960) | `tissue_semantic` | dataset_method | 37 | available | 可直接生成总结 |
| P1 | 2023 | Enhancing gland segmentation in colon histology images using an instance-aware diffusion model. (PMID 37778210) | `generative_segmentation` | method | 34 | manual_pdf_available | 已生成总结 |
| P1 | 2023 | Cervical cell's nucleus segmentation through an improved UNet architecture. (PMID 37788295) | `pathology_instance` | method | 34 | available | 可直接生成总结 |
| P1 | 2022 | Boundary-aware glomerulus segmentation: Toward one-to-many stain generalization. (PMID 36007483) | `cross_stain_generalization` | method | 25 | manual_pdf_available | 已生成总结 |
| P1 | 2024 | Improving generalization capability of deep learning-based nuclei instance segmentation by non-deterministic train time and deterministic test time stain normalization. (PMID 38292472) | `cross_stain_generalization` | external_validation | 17 | available | 可直接生成总结 |
| P1 | 2025 | CellSAM: Advancing Pathologic Image Cell Segmentation via Asymmetric Large-Scale Vision Model Feature Distillation Aggregation Network. (PMID 39440549) | `prompt_foundation` | method | 11 | manual_pdf_available | 已生成总结 |
| P1 | 2025 | Cell Segmentation With Globally Optimized Boundaries (CSGO): A Deep Learning Pipeline for Whole-Cell Segmentation in Hematoxylin-and-Eosin-Stained Tissues. (PMID 39528162) | `whole_cell` | method | 10 | manual_pdf_available | 已生成总结 |
| P1 | 2024 | Cyto R-CNN and CytoNuke Dataset: Towards reliable whole-cell segmentation in bright-field histological images. (PMID 38781811) | `whole_cell` | dataset_method | 6 | pdf_available | 可直接生成总结 |
| P1 | 2015 | [Fully Convolutional Networks for Semantic Segmentation](https://openaccess.thecvf.com/content_cvpr_2015/html/Long_Fully_Convolutional_Networks_2015_CVPR_paper.html) | `generic_semantic` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2018 | [Encoder-Decoder with Atrous Separable Convolution for Semantic Image Segmentation](https://openaccess.thecvf.com/content_ECCV_2018/html/Liang-Chieh_Chen_Encoder-Decoder_with_Atrous_ECCV_2018_paper.html) | `generic_semantic` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2021 | [nnU-Net: a self-configuring method for deep learning-based biomedical image segmentation](https://www.nature.com/articles/s41592-020-01008-z) | `auto_config_baseline` | tool_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2021 | [TransUNet: Transformers Make Strong Encoders for Medical Image Segmentation](https://arxiv.org/abs/2102.04306) | `transformer_foundation` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2021 | [Swin-Unet: Unet-like Pure Transformer for Medical Image Segmentation](https://arxiv.org/abs/2105.05537) | `transformer_foundation` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2022 | [A deep learning-enabled segmentation of ambiguous bioimages](https://www.nature.com/articles/s41587-021-01094-0) | `whole_cell` | tool_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2023 | [Segment Anything](https://arxiv.org/abs/2304.02643) | `prompt_foundation` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2025 | [Segment Anything for Microscopy](https://www.nature.com/articles/s41592-024-02580-4) | `prompt_foundation` | tool_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P2 | 2026 | Benchmarking Deep Segmentation Architectures for Histopathological Nuclei Segmentation: A Controlled Study of Transfer Learning, Robustness, and Efficiency Across CNN, Transformer, and Hybrid Models. (PMID 42581240) | `benchmark` | controlled_benchmark |  | pdf_available | 可直接生成总结 |

总候选 38 项；详细机器可读记录见 `expansion_candidates.jsonl`。
