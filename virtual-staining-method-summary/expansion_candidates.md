# 虚拟染色候选扩充清单

候选按 P0（优先补齐主干）、P1（扩大覆盖）、P2（观察）分层。全文状态来自本地数据库当前快照。

| 优先级 | 年份 | 候选 | 轨道 | 角色 | 引用 | 全文 | 下一步 |
|---|---:|---|---|---|---:|---|---|
| P0 | 2018 | Adversarial Stain Transfer for Histopathology Image Analysis. (PMID 29533895) | `unpaired_translation` | method | 236 | pdf_available | 可直接生成总结 |
| P0 | 2021 | Unpaired Stain Transfer Using Pathology-Consistent Constrained Generative Adversarial Networks. (PMID 33784619) | `unpaired_translation` | method | 151 | pdf_available | 可直接生成总结 |
| P0 | 2020 | A machine learning algorithm for simulating immunohistochemistry: development of SOX10 virtual IHC and evaluation on primarily melanocytic neoplasms. (PMID 32238879) | `virtual_ihc` | clinical_validation | 61 | manual_pdf_available | 已生成总结 |
| P0 | 2022 | MVFStain: Multiple virtual functional stain histopathology images generation based on specific domain mapping. (PMID 35810588) | `virtual_multistain` | method | 54 | manual_pdf_available | 已生成总结 |
| P0 | 2019 | Real-time intraoperative diagnosis by deep neural network driven multiphoton virtual histology. (PMID 31872065) | `label_free_to_he` | clinical_feasibility | 46 | available | 可直接生成总结 |
| P0 | 2023 | Unstained Tissue Imaging and Virtual Hematoxylin and Eosin Staining of Histologic Whole Slide Images. (PMID 36801642) | `label_free_to_he` | wsi_pipeline | 40 | manual_pdf_available | 已生成总结 |
| P0 | 2022 | CycleGAN for virtual stain transfer: Is seeing really believing? (PMID 36328671) | `benchmark` | risk_evaluation | 29 | manual_pdf_available | 已生成总结 |
| P0 | 2023 | Comparison of deep learning models for digital H&E staining from unpaired label-free multispectral microscopy images. (PMID 37040684) | `benchmark` | controlled_benchmark | 21 | manual_pdf_available | 已生成总结 |
| P0 | 2022 | StainCUT: Stain Normalization with Contrastive Learning. (PMID 35877646) | `normalization_contrastive` | method | 17 | available | 可直接生成总结 |
| P0 | 2024 | Clinical-Grade Validation of an Autofluorescence Virtual Staining System With Human Experts and a Deep Learning System for Prostate Cancer. (PMID 39069201) | `clinical_validation` | external_validation | 11 | manual_pdf_available | 已生成总结 |
| P0 | 2024 | Transformation from hematoxylin-and-eosin staining to Ki-67 immunohistochemistry digital staining images using deep learning: experimental validation on the labeling index. (PMID 39087085) | `clinical_validation` | biomarker_validation | 3 | available | 可直接生成总结 |
| P0 | 2021 | StainNet: A Fast and Robust Stain Normalization Network. (PMID 34805215) | `normalization_fast` | method | 2 | available | 可直接生成总结 |
| P0 | 2009 | [A method for normalizing histology slides for quantitative analysis](https://doi.org/10.1109/ISBI.2009.5193250) | `normalization_classical` | pathology_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2016 | [Structure-Preserving Color Normalization and Sparse Stain Separation for Histological Images](https://doi.org/10.1109/TMI.2016.2529665) | `normalization_classical` | pathology_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2017 | [Image-to-Image Translation with Conditional Adversarial Networks](https://openaccess.thecvf.com/content_cvpr_2017/html/Isola_Image-To-Image_Translation_With_CVPR_2017_paper.html) | `paired_translation` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2017 | [Unpaired Image-to-Image Translation using Cycle-Consistent Adversarial Networks](https://openaccess.thecvf.com/content_ICCV_2017/html/Zhu_Unpaired_Image-To-Image_Translation_ICCV_2017_paper.html) | `unpaired_translation` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P0 | 2019 | [StainGAN: Stain Style Transfer for Digital Histological Images](https://doi.org/10.1109/ISBI.2019.8759152) | `normalization_gan` | pathology_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2017 | Stain Normalization using Sparse AutoEncoders (StaNoSA): Application to digital pathology. (PMID 27373749) | `normalization_classical` | method | 215 | manual_pdf_available | 已生成总结 |
| P1 | 2021 | Biopsy-free in vivo virtual histology of skin using deep learning. (PMID 34795202) | `in_vivo_virtual_histology` | clinical_feasibility | 111 | available | 可直接生成总结 |
| P1 | 2019 | A High-Performance System for Robust Stain Normalization of Whole-Slide Images in Histopathology. (PMID 31632974) | `normalization_wsi` | pipeline | 110 | available | 可直接生成总结 |
| P1 | 2021 | Normalization of HE-stained histological images using cycle consistent generative adversarial networks. (PMID 34362386) | `normalization_gan` | method | 63 | available | 可直接生成总结 |
| P1 | 2022 | Colour adaptive generative networks for stain normalisation of histopathology images. (PMID 36113326) | `normalization_gan` | method | 53 | manual_pdf_available | 已生成总结 |
| P1 | 2023 | Unpaired virtual histological staining using prior-guided generative adversarial networks. (PMID 36764189) | `unpaired_translation` | method | 35 | manual_pdf_available | 已生成总结 |
| P1 | 2024 | Multi-domain stain normalization for digital pathology: A cycle-consistent adversarial network for whole slide images. (PMID 38574542) | `normalization_wsi` | method | 33 | manual_pdf_available | 已生成总结 |
| P1 | 2023 | Stain normalization using score-based diffusion model through stain separation and overlapped moving window patch strategies. (PMID 36473344) | `normalization_diffusion` | method | 23 | manual_pdf_available | 已生成总结 |
| P1 | 2022 | Stain transfer using Generative Adversarial Networks and disentangled features. (PMID 35026572) | `unpaired_translation` | method | 22 | manual_pdf_available | 已生成总结 |
| P1 | 2024 | FFPE++: Improving the quality of formalin-fixed paraffin-embedded tissue imaging via contrastive unpaired image-to-image translation. (PMID 37852162) | `structure_preservation` | method | 20 | manual_pdf_available | 已生成总结 |
| P1 | 2024 | Unsupervised Multi-Domain Progressive Stain Transfer Guided by Style Encoding Dictionary. (PMID 38198253) | `multi_domain_translation` | method | 17 | manual_pdf_available | 已生成总结 |
| P1 | 2025 | Artificial intelligence-based virtual staining platform for identifying tumor-associated macrophages from hematoxylin and eosin-stained images. (PMID 40158294) | `virtual_ihc` | biomarker_validation | 12 | manual_pdf_available | 已生成总结 |
| P1 | 2024 | Automated Whole Slide Imaging for Label-Free Histology Using Photon Absorption Remote Sensing Microscopy. (PMID 38231822) | `label_free_to_he` | wsi_pipeline | 11 | pdf_available | 可直接生成总结 |
| P1 | 2023 | Virtual staining for pixel-wise and quantitative analysis of single cell images. (PMID 37932315) | `clinical_validation` | quantitative_validation | 6 | available | 可直接生成总结 |
| P1 | 2001 | [Color transfer between images](https://doi.org/10.1109/38.946629) | `normalization_classical` | algorithm_baseline |  | external | 导入原始论文或建立精简基线卡 |
| P1 | 2020 | [Contrastive Learning for Unpaired Image-to-Image Translation](https://www.ecva.net/papers/eccv_2020/papers_ECCV/html/3229_ECCV_2020_paper.php) | `unpaired_translation` | architecture_baseline |  | external | 导入原始论文或建立精简基线卡 |

总候选 33 项；详细机器可读记录见 `expansion_candidates.jsonl`。
