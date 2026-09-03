# 计算病理学多模态融合方法综述

## 研究范围与证据边界

本综述仅基于用户提供的 35 篇计算病理学多模态论文的本地逐篇总结记录撰写，不引入任何额外文献。所有关于单篇论文的输入模态、融合机制、实验结果与限制描述，均来自对应本地总结；而关于技术路线、方法谱系、趋势判断和选型建议，属于基于本地记录的跨论文综合归纳，并非某一篇论文原文的必然表述。

从任务覆盖看，这些记录涵盖癌症生存预测、诊断与分级、分子标志物预测、新辅助治疗反应预测、免疫治疗反应预测、病理视觉问答、图文检索、报告生成、空间转录组对齐与预测，以及基础模型评测等。模态覆盖 H&E 全切片图像（WSI）、局部病理图像或 ROI、IHC/PD-L1 切片、CT/MRI 等放射影像、基因突变、拷贝数变异、mRNA/miRNA/蛋白组学、临床表格变量、病理报告文本、教学视频图文对，以及空间转录组数据。

需要特别强调证据边界：不同论文使用不同数据集、编码器、患者划分、交叉验证方式和评价指标，例如 C-index、AUC、准确率、F1、检索召回率、报告生成指标等，因此本综述不进行跨论文数值排名。部分本地记录存在摘要级信息、正文截断、公式缺失、代码与超参数不完整等情况；涉及这些论文时，本综述会明确标注其证据或复现细节不足。

---

## 技术演进与分类框架

从本地记录看，计算病理学多模态融合大致沿五条谱系演进：

1. **手工特征与统计/树模型融合阶段**：以影像组学、病理组学、CellProfiler 特征、列线图为代表，融合通常发生在特征拼接或决策层，强调临床验证和可解释性，但跨模态交互建模较弱。  
2. **深度特征拼接与统一表示阶段**：开始出现 CNN、MLP、自监督图像编码器与组学/临床特征拼接，或通过无监督表示学习将多模态映射到统一空间。此类方法开始关注缺失模态、泛癌预训练和端到端生存建模。  
3. **交互式融合与生存/治疗反应建模阶段**：引入门控注意力、Kronecker 积、协同注意力、图神经网络、桥接网络、监督对比学习等机制，强调跨模态非线性交互、可解释性和患者级风险分层。  
4. **病理视觉—语言预训练与生成式助手阶段**：CLIP/CoCa 式图文对齐、指令微调、多模态问答、报告生成和零样本分类成为重点，融合从“预测特征拼接”转向“语义空间对齐与生成”。  
5. **整张切片、空间组学与新一代基础模型阶段**：从 patch 级表示扩展到 WSI 长序列建模、空间转录组配对对齐、多模态全切片预训练和大规模基础模型评测。

为便于区分，本综述在每个方法条目中标注其更偏向的类型：  
- **核心融合算法**：提出新的跨模态交互、对齐、门控、桥接或注意力融合机制。  
- **多模态预训练/对齐模型**：主要贡献是图文、图像—组学或多模态基础表示学习。  
- **临床验证型晚期融合**：融合机制相对简单，但强调临床队列、外部验证或真实诊疗场景。  
- **通用模型使用或评测范式**：重点不是提出新融合网络，而是评测或使用已有大模型/基础模型。

需要说明的是，“多一个模态”本身不自动构成算法创新。本综述更关注是否存在真正跨模态交互、语义对齐、动态权重、缺失模态处理、空间对应关系，或是否具备强临床验证。

---

## 逐方法创新点

以下按五条技术路线组织。若一篇论文同时涉及多条路线，仅放入最能体现其核心创新的一组，不重复列出。

### 1) 早期图像—组学与临床特征融合

这一组方法多处于计算病理多模态学习的早期阶段，融合位置通常较浅，常见为特征拼接、全连接层联合建模或决策层替换。其价值往往在于首次将病理图像与组学/临床变量联合建模，或提供了缺失处理、临床验证和实用化思路。

**SCNN/GSCNN**（核心融合算法）  
输入为组织学图像和少量关键基因组标志物，如 IDH 突变与 1p/19q 共缺失。SCNN 将卷积网络与 Cox 生存模型结合，GSCNN 进一步在全连接层引入基因组特征，形成端到端生存预测。其真正创新不仅是多模态输入，还包括针对肿瘤异质性的采样与推理风险过滤策略，以及证明端到端融合优于先图像风险再拼接基因组特征的浅层融合。实验基于 TCGA 胶质瘤队列并采用重复交叉验证；主要限制是 ROI 提取依赖人工/半自动审查，网络骨干与归一化层较早期，现代复现通常需要替换为更强的 WSI 聚合机制。[详细解读](method_summaries/PMID_29531073_Predicting%20cancer%20outcomes%20from%20histology%20and%20genomics%20using%20convolutional%20networks.md)

**多模态无监督泛癌预后表示框架**（核心融合算法 / 缺失模态处理）  
输入包括临床数据、mRNA、miRNA 和 WSI，将四种模态压缩到统一 512 维患者表示后接 Cox 预测。其核心创新是无监督多模态表示学习和多模态 Dropout：训练与推理时随机丢弃整个模态，从而缓解医疗数据常见的模态缺失问题。实验显示多模态 Dropout 能提升泛癌预后预测，并支持泛癌预训练迁移到多数单癌种。限制在于 WSI 处理仍较早期，采用颜色过滤和随机 patch 采样，未使用现代注意力 MIL；推理时多模态特征聚合细节在本地记录中不完全明确。[详细解读](method_summaries/PMID_31510656_Deep%20learning%20with%20multimodal%20representation%20for%20pancancer%20prognosis%20prediction.md)

**PAGE-Net**（核心融合算法 / 可解释生存建模）  
输入为 WSI、基因表达和年龄等临床变量。病理分支使用空洞卷积 CNN 提取 patch 特征，并通过两阶段 3-norm 池化聚合为 WSI 级表示；基因组分支使用基于 KEGG 等通路先验的稀疏网络；最终三类特征拼接后接 Cox 模型。其创新点在于将生物学通路先验硬编码到基因组网络中，并提供无需手动 ROI 标注的 WSI 聚合策略。实验在 GBM 上显示整合模型优于单模态基线；限制是跨模态融合仍为简单拼接，未建立显式病理—基因交互，且临床变量较简单。[详细解读](method_summaries/PMID_31797610_PAGE-Net_%20Interpretable%20and%20Integrative%20Deep%20Learning%20for%20Survival%20Analysis%20Using%20Histopathological%20Images%20and%20Genomic%20D.md)

**CNN+患者数据皮肤病变分类与置信度路由**（临床验证型晚期融合 / 决策路由）  
输入为皮肤病理 WSI 和患者临床变量，如年龄、性别、解剖部位。论文系统比较了加权、拼接、SE 等特征融合，并提出基于 CNN 置信度阈值的“朴素方法”：当图像模型不确定时，用患者数据分类器结果替换。其真正贡献不是复杂融合网络，而是给出一个负面但实用的结论：当图像模型已很强时，强制融合低信息量临床特征未必有益；基于不确定性的决策路由反而能改善平衡准确率。限制是数据规模有限，且该方法在 AUROC 上不一定提升。[详细解读](method_summaries/PMID_33838393_Combining%20CNN-based%20histologic%20whole%20slide%20image%20analysis%20and%20patient%20data%20to%20improve%20skin%20cancer%20classification.md)

**HGSOC CellProfiler 多组学整合框架**（临床验证型晚期融合）  
输入为高级别浆液性卵巢癌的 WSI/TMA 图像、体细胞突变、mRNA 和 RPPA 蛋白数据。图像侧使用 CellProfiler 提取定量病理特征，随后与多组学特征拼接，用随机森林等模型预测分子特征并构建预后风险评分。其创新不在深度交互融合，而在于系统评估图像与多组学两两及全组合的临床价值，并通过外部 TMA 队列和决策曲线分析增强转化证据。限制是依赖手工图像特征，融合方式较浅，未建模跨模态非线性交互。[详细解读](method_summaries/PMID_34275655_Integration%20of%20histopathological%20images%20and%20multi-dimensional%20omics%20analyses%20predicts%20molecular%20features%20and%20prognosis%20i.md)

**MMAI 前列腺癌多模态系统**（临床验证型晚期融合）  
输入为前列腺癌治疗前 WSI 和临床表格变量。图像侧使用 MoCo-v2 自监督学习提取形态学特征，随后与临床特征拼接并输入 CatBoost，预测远处转移、生化失败、特异性生存和总生存等长期结局。其核心贡献在于基于 5 项 III 期随机临床试验进行训练与验证，使模型证据等级高于多数回顾性研究；同时自监督 WSI 特征降低了病理标注成本。限制是融合机制仍为轻量级特征拼接，未显式建模图像—临床深层交互，且本地记录指出缺乏完全独立的外部队列验证。[详细解读](method_summaries/PMID_35676445_Prostate%20cancer%20therapy%20personalization%20via%20multi-modal%20deep%20learning%20on%20randomized%20phase%20III%20clinical%20trials.md)

---

### 2) 交互式图像—组学融合与生存建模

这一组方法的核心不再只是“加入组学模态”，而是通过注意力、门控、张量积、桥接网络、图模型或显式缺失处理，建模病理图像与分子/临床数据之间的交互关系。多数方法面向生存预测、分子分型或治疗反应。

**Pathomic Fusion**（核心融合算法）  
输入包括组织病理图像、细胞图和基因组学数据。图像与细胞图分别由 CNN 与 GCN 编码，基因组数据由自归一化网络编码；融合阶段使用门控注意力控制模态表达，并通过 Kronecker 积构建多模态张量，显式建模成对和高阶交互。其真正创新在于将高阶张量交互与多模态归因解释结合，并证明细胞图特征可为生存预测提供额外价值。实验包括胶质瘤和透明细胞肾细胞癌的交叉验证与消融；限制是细胞图构建依赖高质量核分割，计算与工程成本较高。[详细解读](method_summaries/PMID_32881682_Pathomic%20Fusion_%20An%20Integrated%20Framework%20for%20Fusing%20Histopathology%20and%20Genomic%20Features%20for%20Cancer%20Diagnosis%20and%20Prognos.md)

**PORPOISE / MMF**（核心融合算法 / 可解释生存平台）  
输入为 H&E WSI 和分子谱数据，包括突变、拷贝数变异和 RNA-Seq。病理侧使用注意力多实例学习，组学侧使用自归一化网络；融合采用门控注意力加 Kronecker 积，并用离散时间生存损失预测风险。其创新点在于将多模态融合、泛癌生存评估、局部注意力热图和全局梯度归因整合为可交互平台，能够揭示形态学与分子特征的互补贡献。限制是分子数据仍为 bulk 级，缺乏空间分辨率，因此融合主要是患者级晚期语义融合。[详细解读](method_summaries/PMID_35944502_Pan-cancer%20integrative%20histology-genomic%20analysis%20via%20multimodal%20deep%20learning.md)

**PathIn-NL + AHM-Fusion**（核心融合算法 / 弱监督标签清洗）  
输入为 WSI 和 CNV 等基因组特征。PathIn-NL 将 patch 分类视为噪声标签问题，通过自训练清洗 WSI 级弱标签；AHM-Fusion 则包含早期特征引导和晚期注意力融合模块，用多层注意力捕获跨模态交互。其真正创新是将弱监督病理特征提取与层次化多模态融合结合，尤其关注如何在无 patch 标注下获得高质量病理表示。实验覆盖肺癌和胶质瘤分类，并提供模块消融；限制是 GCN 邻接构建细节不完全明确，且在低噪声场景下 PathIn-NL 优势可能有限。[详细解读](method_summaries/PMID_36682215_Hierarchical%20multimodal%20fusion%20framework%20based%20on%20noisy%20label%20learning%20and%20attention%20mechanism%20for%20cancer%20classification.md)

**成人/儿童脑肿瘤多模态生存融合框架**（核心融合算法比较 / 生存建模）  
输入为脑肿瘤 WSI 与基因表达数据。该框架系统实现并比较早期、晚期和联合融合，使用 CNN 提取图像特征、MLP 提取基因特征，并通过 Cox 模型输出风险。其贡献在于不是单提出一种融合，而是在成人和儿童脑肿瘤、外部 CPTAC 验证及罕见肿瘤迁移场景下比较不同融合阶段的鲁棒性。本地记录显示早期融合整体较稳健；限制是训练时每个 WSI 仅采样有限 patch，推理采用较简单平均，未充分利用 WSI 空间异质性。[详细解读](method_summaries/PMID_36991216_Multimodal%20deep%20learning%20to%20predict%20prognosis%20in%20adult%20and%20pediatric%20brain%20tumors.md)

**Brim**（核心融合算法 / 缺失模态桥接）  
输入为 H&E WSI 与突变、拷贝数变异、RNA-Seq 等分子特征。病理侧使用 Transformer 式 MIL 聚合切片表示，分子侧使用自归一化网络；核心是双向桥接网络，将病理与分子表示映射到更接近的语义空间，并可在缺少分子数据时由 WSI 生成伪分子嵌入。其真正创新在于把缺失模态问题转化为跨模态语义桥接，而不是简单丢弃样本或零填充。实验包括 TCGA 多癌种交叉验证、独立结直肠癌队列验证和语义对齐评估；限制是桥接网络具体损失与结构在本地记录中不够完整，且并非在所有癌种均优于全部基线。[详细解读](method_summaries/PMID_40051298_Interpretable%20Multimodal%20Fusion%20Model%20for%20Bridged%20Histology%20and%20Genomics%20Survival%20Prediction%20in%20Pan-Cancer.md)

**GMLF**（核心融合算法 / 图式晚期融合）  
输入为肌层浸润性膀胱癌 H&E WSI 和基因表达谱。WSI 通过 SlideGraph+ 转化为图，分别提取组织、细胞和形态学空间特征；基因表达由 MLP 编码；最终在预测分数层进行晚期融合，并用 Platt scaling 输出新辅助化疗反应概率。其创新点在于显式利用病理空间图结构，并通过代理模型 SHAP 实现模态级与基因级解释。实验包括内部交叉验证、留出测试和多组单/双模态消融；限制是融合仍发生在决策层，跨模态非线性交互弱于中期融合，且缺乏外部独立验证。[详细解读](method_summaries/PMID_40121304_Predicting%20response%20to%20neoadjuvant%20chemotherapy%20in%20muscle-invasive%20bladder%20cancer%20via%20interpretable%20multimodal%20deep%20lear.md)

**癌症类型感知缺失模态生存框架**（核心融合算法 / 缺失模态鲁棒生存预测）  
输入以组织病理图像为锚模态，同时允许 RNA 表达和临床文本缺失。三种模态投影到统一 32 维空间，缺失模态使用零张量替代，并通过带可用性掩码的门控融合机制降低缺失模态权重；共享 Transformer 编码器后接癌型特异预测头。其真正创新在于不依赖生成式插补，而是通过掩码门控和癌型特异头同时处理缺失与癌型异质性。实验包括 10 种 TCGA 癌型、不同缺失比例、跨机构和数据划分敏感性分析；限制是门控融合相对简单拼接的细粒度消融不足，部分编码器和损失细节不完整。[详细解读](method_summaries/PMID_41870128_A%20cancer-type-aware%20framework%20for%20robust%20multimodal%20survival%20prediction%20under%20missing%20modalities.md)

---

### 3) 病理—放射—临床跨尺度融合

这一组方法处理的是更明显的尺度差异：放射影像提供宏观肿瘤表型，病理提供微观组织/细胞信息，临床或组学数据提供患者背景与分子状态。核心问题是如何对齐宏观与微观特征，并处理缺失、异质性和临床验证。

**放射病理组学签名 RPS**（临床验证型晚期融合）  
输入为局部晚期直肠癌多参数 MRI 和活检 WSI。方法提取影像组学与病理组学手工特征，经 XGBoost 特征筛选后构建放射病理组学签名。其创新不在深度交互，而在于将宏观影像与微观病理特征互补用于新辅助放化疗反应预测，并在多个外部中心验证。本地记录显示其外部验证样本量较大，且 RPS 与总生存、无病生存相关；限制是依赖人工 ROI 勾画和手工特征，跨中心影像/扫描协议可能影响稳定性。[详细解读](method_summaries/PMID_32729045_Multiparametric%20MRI%20and%20Whole%20Slide%20Image-Based%20Pretreatment%20Prediction%20of%20Pathological%20Response%20to%20Neoadjuvant%20Chemorad.md)

**联合列线图：病理组学—影像组学—免疫评分—临床**（临床验证型晚期融合）  
输入包括结直肠癌肺转移患者的 WSI 病理组学特征、影像组学特征、自动免疫评分和临床因素。各模态先分别生成独立预后因子，再整合到列线图中预测总生存和无病生存。其贡献在于将免疫评分与病理/影像组学结合，形成面向术后风险分层的临床工具。限制是本地记录主要来自摘要，缺乏完整方法、基线对比和消融细节，因此算法层面的证据较弱。[详细解读](method_summaries/PMID_35073937_Development%20of%20a%20novel%20combined%20nomogram%20model%20integrating%20deep%20learning-pathomics%2C%20radiomics%20and%20immunoscore%20to%20predict.md)

**DyAM**（核心融合算法 / 缺失模态掩码）  
输入为 NSCLC 患者的 CT 放射组学、PD-L1 IHC 纹理、基因组特征和临床指标。DyAM 将不同模态视为异构实例，通过动态深度注意力分配模态权重，并用掩码机制处理缺失模态，最终预测 PD-(L)1 治疗反应。其真正创新在于注意力门控与缺失掩码结合，使模型在真实临床队列中可适应部分模态不可用的情况。实验显示多模态模型优于单模态 PD-L1 TPS、TMB 或简单线性平均；限制是单中心数据、依赖手工放射/病理特征，且缺乏外部多模态验证。[详细解读](method_summaries/PMID_36038778_Multimodal%20integration%20of%20radiology%2C%20pathology%20and%20genomics%20for%20prediction%20of%20response%20to%20PD-%28L%291%20blockade%20in%20patients%20w.md)

**HMCAT**（核心融合算法 / 跨尺度协同注意力）  
输入为 WSI 和 CT/MR 放射学特征。病理侧使用分层视觉 Transformer 捕获细胞、块和区域级信息；放射侧同时使用手工影像组学和深度学习特征。核心是分层放射学引导的协同注意力：以放射特征为 Query，引导病理实例聚合，实现早期跨模态融合。其创新在于用宏观影像引导微观病理特征选择，并将庞大 WSI 实例压缩为少量可解释视觉概念。实验包括生存预测、消融和共注意力热图；限制是肿瘤分割与数据预处理复杂，且本地记录未明确代码仓库。[详细解读](method_summaries/PMID_37030860_Survival%20Prediction%20via%20Hierarchical%20Multimodal%20Co-Attention%20Transformer_%20A%20Computational%20Histology-Radiology%20Solution.md)

**iSCLM**（核心融合算法 / 监督对比跨模态对齐）  
输入为胃癌治疗前增强 CT 和 H&E 活检 WSI。CT 使用 ResNet-34 编码，病理使用 ResNet-18 与图注意力网络提取空间图特征；核心是通过监督对比学习对齐跨模态特征，并用增量学习利用不可切除肿瘤数据增强特征提取器。其真正创新在于将监督对比学习用于宏观影像与微观病理的对齐，而非简单拼接；同时提供肿瘤浸润边缘、CD11c 阳性树突状细胞等生物学验证。实验包括外部测试集、前瞻性队列和消融；限制是图构建和 ROI 处理较复杂，且依赖配对治疗前数据。[详细解读](method_summaries/PMID_39637859_Interpretable%20multi-modal%20artificial%20intelligence%20model%20for%20predicting%20gastric%20cancer%20response%20to%20neoadjuvant%20chemothera.md)

**UroFusion-X**（核心融合算法 / 统一多任务缺失鲁棒框架）  
输入覆盖泌尿系统癌症的 3D 放射影像、WSI、基因组/分子谱和实验室/临床变量。各模态由专用编码器处理，随后通过跨模态共注意力交换信息，并用门控 Product-of-Experts 根据模态可用性和信号质量加权融合；训练期使用模态 dropout，同时加入影像—病理一致性约束和患者级对比学习。其创新在于统一支持诊断、分子分型和生存预后，并显式处理缺失模态。实验包括缺失模拟、留一中心验证、校准和决策曲线分析；限制是本地记录被截断，样本量、损失权重和完整超参数不够明确。[详细解读](method_summaries/PMID_41554842_UroFusion-X_%20a%20unified%20multimodal%20deep%20learning%20framework%20for%20robust%20diagnosis%2C%20subtyping%2C%20and%20prognosis%20of%20urological%20c.md)

**缺失感知 NSCLC 多模态生存框架 / ConcatODST**（核心融合算法 / 缺失感知中间融合）  
输入为不可切除 II–III 期 NSCLC 的 CT 体积、WSI 和结构化临床变量。方法先用基础模型或专用流程提取模态特征，再用缺失感知编码器处理可见输入，最后通过 ConcatODST 进行中间融合并输出连续风险评分。其真正创新在于将缺失作为模型设计约束，而不是删除不完整患者；同时系统比较早融合、晚融合和中间融合。实验报告三模态中间融合取得较高 C-index 和 td-AUC，并通过模态掩码分析评估依赖关系；限制是本地记录缺少完整架构细节、外部验证和临床净收益分析。[详细解读](method_summaries/PMID_42332139_Handling%20missing%20modalities%20in%20multimodal%20survival%20prediction%20for%20non-small%20cell%20lung%20cancer.md)

---

### 4) 病理视觉语言预训练、报告建模与多模态助手

这一组方法将病理图像与自然语言问题、报告、描述或指令结合，重点从结构化预测转向语义理解、零样本识别、问答和生成。需要区分：预训练对齐模型、任务特定 VQA/报告融合模型、生成式助手，以及通用大模型评测范式。

**TraP-VQA**（核心融合算法 / 病理 VQA）  
输入为病理图像和自然语言问题。图像使用 ResNet50 提取特征，问题使用领域语言模型 BioELMo 与 BiLSTM 编码；随后通过 Transformer 编码器融合，并用解码器生成答案。其创新在于面向病理 VQA 的可解释视觉—语言 Transformer，并结合注意力、Grad-CAM、SHAP 等解释工具。实验在 PathVQA 上显示封闭问题表现较强，但开放问题准确率仍有限；限制是损失函数、词汇表和解码细节不完全明确，跨数据集结果在本地记录中不够完整。[详细解读](method_summaries/PMID_35358054_Vision-Language%20Transformer%20for%20Interpretable%20Pathology%20Visual%20Question%20Answering.md)

**PLIP**（多模态预训练/对齐模型）  
输入为病理图像与自然语言描述，训练数据来自医疗 Twitter 等公开论坛构建的 OpenPath。PLIP 采用 CLIP 式图文对比学习，将图像与文本对齐到共享空间，用于零样本分类、线性探测和跨模态检索。其真正贡献在于利用公开社交媒体构建病理图文数据，并验证视觉—语言预训练在病理图像分析中的零样本能力。限制是本地记录对模型架构和训练细节描述不足，且社交媒体数据存在噪声、版权和去标识化问题。[详细解读](method_summaries/PMID_37592105_A%20visual-language%20foundation%20model%20for%20pathology%20image%20analysis%20using%20medical%20Twitter.md)

**CONCH**（多模态预训练/对齐模型）  
输入为人类 H&E 病理图像与文本描述，构建约 117 万图文对。模型基于 CoCa 框架，同时优化图文对比对齐和自回归字幕生成，因此兼具检索/分类与生成能力。其创新在于大规模病理专属图文清洗流水线和对比+生成联合预训练，使零样本分类、检索、分割和字幕生成均可受益。实验覆盖 13 个下游基准；限制是模型权重获取可能有机构许可要求，预训练计算成本高，且本地记录指出部分优化器细节需查补充材料。[详细解读](method_summaries/PMID_38504017_A%20visual-language%20foundation%20model%20for%20computational%20pathology.md)

**QUILT-1M / QUILTNET**（多模态预训练/对齐模型 / 数据管线）  
输入为组织病理学教育视频衍生的图像—文本对，并与 PubMed、LAION、Twitter/OpenPath 等合并为约 100 万图文对。其核心创新是视频到图文对的自动构建管线：关键帧提取、病理图像分类、放大倍率分类、语音识别、医学术语纠错、LLM 清洗和时间块对齐。QUILTNET 使用 CLIP 对比目标微调，用于零样本分类、线性探测和检索。限制是训练超参数和管线组件消融在本地记录中不完整，视频来源涉及版权、平台政策和可复现性问题。[详细解读](method_summaries/PMID_38742142_Quilt-1M_%20One%20Million%20Image-Text%20Pairs%20for%20Histopathology.md)

**PathChat**（多模态生成式病理助手）  
输入为病理图像和自然语言指令/临床上下文。PathChat 基于 LLaVA 架构，使用针对病理优化的视觉编码器、多模态投影器和 Llama 2 13B，通过预训练对齐与指令微调两阶段训练。其真正创新在于构建大规模病理指令数据集和专家评估基准，使模型能进行多轮对话、诊断解释和开放式问答。实验包括多选题、开放题和病理学家偏好评估；限制是主要面向 ROI/图像问答，WSI 级长上下文理解仍需扩展，同时生成式模型存在幻觉和临床可靠性验证需求。[详细解读](method_summaries/PMID_38866050_A%20multimodal%20generative%20AI%20copilot%20for%20human%20pathology.md)

**GPT-4V 病理图像上下文学习评测**（通用模型使用或评测范式）  
输入为病理图像 tile 与文本 prompt，通过 zero-shot/few-shot 指令和 kNN 检索示例让 GPT-4V 完成癌症病理图像分类。其核心贡献不是提出新融合算法，而是评测通用多模态大模型在病理图像上的上下文学习能力，并证明 kNN 示例检索能提升分类表现。实验覆盖结直肠癌组织亚型、息肉亚型和乳腺癌淋巴结检测等任务；限制是测试样本较小、API 成本高，且模型在碎片、黏液、基质等细粒度病理概念上表现不佳。[详细解读](method_summaries/PMID_39572531_In-context%20learning%20enables%20multimodal%20large%20language%20models%20to%20classify%20cancer%20pathology%20images.md)

**MUSK**（多模态预训练/对齐模型 / 精准肿瘤学基础模型）  
输入为病理图像和病理相关文本。MUSK 采用两阶段预训练：先在大规模无标签图像和文本上进行统一掩码建模，再在图文对上进行对比学习；并引入病理特定增强、病理图像 tokenizer、细粒度图文解码器和自举对比学习。其创新在于利用非配对与配对数据共同学习，并面向检索、VQA、分类、分子标志物预测、预后和免疫治疗反应预测等任务。实验包括 23 个基准和多项临床结局预测；限制是计算资源要求高，本地记录未提供明确代码仓库。[详细解读](method_summaries/PMID_39779851_A%20vision-language%20foundation%20model%20for%20precision%20oncology.md)

**MPath-Net**（核心融合算法 / 报告辅助 WSI 分类）  
输入为肾癌/肺癌 WSI 和病理报告文本。图像分支使用 DSMIL 式 ResNet-18 提取并聚合 WSI 特征，文本分支使用 Sentence-BERT 编码报告；融合采用特征拼接加 MLP。其贡献在于将真实病理报告引入 WSI 癌症亚型分类，并提供 Bootstrap 置信区间和文本编码器消融。限制是融合机制较浅，未使用跨注意力或张量交互；本地记录还指出图像单模态 AUC 略高于多模态，提示文本可能引入噪声或软化概率边界。[详细解读](method_summaries/PMID_41230238_Multimodal%20Data%20Fusion%20for%20Whole-Slide%20Histopathology%20Image%20Classification.md)

---

### 5) 空间组学、整张切片与新一代多模态基础模型

这一组方法不再局限于 patch 或简单图文对，而是面向 WSI 长序列建模、空间转录组配对、多模态知识蒸馏和基础模型评测。部分方法本身不是传统“融合预测模型”，但构成了新一代多模态病理学习的基础设施。

**UNI**（视觉基础模型 / 多模态支撑模型）  
输入为 H&E 诊断级 WSI 及其 patch，本地记录未提及文本或组学模态。UNI 使用超大规模 WSI 数据进行自监督预训练，并在多个计算病理任务上评估泛化能力。其贡献在于建立病理视觉基础模型和大规模评估范式，可作为后续图文、病理—组学或多模态助手的视觉编码器。需要明确的是，它本身不是跨模态融合算法；本地记录也指出方法细节和定量证据不完整，主要证据来自摘要和补充表。[详细解读](method_summaries/PMID_38504018_Towards%20a%20general-purpose%20foundation%20model%20for%20computational%20pathology.md)

**Prov-GigaPath / GigaPath**（整张切片基础模型 / 多模态扩展）  
输入为真实世界大规模 WSI，并在视觉—语言继续预训练中使用病理报告。模型采用两级结构：DINOv2 预训练的 tile encoder 编码局部图块，LongNet slide encoder 对数万级 tile embedding 进行长序列自监督建模；下游可用注意力聚合为切片表示。其创新在于将长序列 Transformer 用于全切片病理建模，并利用真实世界数据训练。论文还探索 slide 级图文对比对齐；限制是预训练数据专有、计算和存储成本高，报告清洗与视觉—语言细节在本地记录中不完全。[详细解读](method_summaries/PMID_38778098_A%20whole-slide%20foundation%20model%20for%20digital%20pathology%20from%20real-world%20data.md)

**CHIEF**（病理基础模型 / 弱监督 WSI 聚合）  
输入主要为 WSI；方法公式中出现文本特征分支，但本地记录未说明文本数据来源。CHIEF 结合无监督 tile 级预训练和弱监督 WSI 级识别，通过注意力聚合 tile 特征，并可加入文本特征形成融合表示，用于癌症检测、起源识别、IDH/MSI 预测和生存预测。其创新在于大规模、多任务、弱监督的通用病理评估框架，并提供染色归一化、对抗鲁棒性和注意力解释。限制是文本分支定义不清，预训练架构和超参数不完整，因此不能将其视为完全明确的多模态实现。[详细解读](method_summaries/PMID_39232164_A%20pathology%20foundation%20model%20for%20cancer%20diagnosis%20and%20prognosis%20prediction.md)

**OmiCLIP / Loki**（多模态预训练/对齐模型 / 空间组学）  
输入为 H&E 组织病理图像和转录组数据，包括空间转录组、单细胞 RNA-seq 和 bulk RNA-seq。其核心创新是将转录组数据“文本化”，例如拼接斑块中表达量最高的基因符号，然后用 CLIP 式对比学习将图像与组学表示对齐。基于 OmiCLIP 的 Loki 平台支持组织对齐、注释、细胞类型分解、跨模态检索和基因表达预测。实验覆盖多个模拟、公开和内部数据集；限制是模型不是生成式基因表达预测器，下游任务常需微调，且对非 Visium 高分辨率空间技术需要调整裁剪与聚合策略。[详细解读](method_summaries/PMID_40442373_A%20visual-omics%20foundation%20model%20to%20bridge%20histopathology%20with%20spatial%20transcriptomics.md)

**计算病理基础模型基准评测框架 / PathBench**（通用模型使用或评测范式）  
输入主要为 H&E WSI 切块，评测对象包括通用视觉模型、通用视觉—语言模型、病理视觉模型和病理视觉—语言模型。该框架采用冻结基础模型特征、线性探针、固定超参数和 MIL 式平均聚合，并额外测试 5 个高性能模型的多数投票晚融合。其贡献在于提供统一评测协议，比较模型规模、预训练数据规模、病理专用训练和模态类型对性能的影响。限制是表征相似性分析细节不足，视觉—语言模型下游是否使用文本及如何使用文本在本地记录中不明确。[详细解读](method_summaries/PMID_40463538_Comparing%20Computational%20Pathology%20Foundation%20Models%20using%20Representational%20Similarity%20Analysis.md)

**TITAN**（多模态全切片基础模型）  
输入为 WSI 视觉特征、合成细粒度 ROI 描述和真实病理报告。TITAN 采用三阶段预训练：特征空间 iBOT 视觉自监督学习、ROI 级 CoCa 图文对齐、WSI 级 CoCa 报告对齐；并使用 2D ALiBi 位置编码支持长上下文空间外推。其真正创新在于将多尺度文本监督与 WSI 长序列建模结合，使模型支持零样本分类、检索、报告生成和生存/分子任务。实验覆盖大量任务和消融；限制是可能编码扫描仪等非生物学特征，8k 裁剪加外推可能丢失全局绝对上下文，且计算资源要求高。[详细解读](method_summaries/PMID_41193692_A%20multimodal%20whole-slide%20foundation%20model%20for%20pathology.md)

**mSTAR**（多模态全切片基础模型 / 自蒸馏预训练）  
输入包括 WSI、病理报告和 RNA-Seq。第一阶段通过跨模态对比学习和跨癌种对比学习预训练 slide aggregator，吸收三种模态知识；第二阶段将预训练 aggregator 作为教师，通过自蒸馏将 whole-slide 多模态上下文注入 patch extractor。其创新在于解决 slide 级多模态知识难以直接指导 patch 级特征提取的问题，并证明多模态扩展可能比单纯增加视觉数据更高效。实验覆盖大量肿瘤学任务和模态/目标消融；限制是依赖现有组件如 UNI、TransMIL、BioBERT/scBERT，且多模态数据清洗与配对工程成本较高。[详细解读](method_summaries/PMID_41387679_A%20multimodal%20knowledge-enhanced%20whole-slide%20pathology%20foundation%20model.md)

---

## 横向比较与发展趋势

### 融合阶段：从浅层拼接到中期交互，再到基础模型上的轻量适配

早期方法多采用特征拼接、列线图或简单全连接融合，例如手工放射/病理组学签名、CellProfiler 多组学框架、MMAI 的图像特征加临床变量。这类方法的优势是易于解释和临床转化，但跨模态交互能力有限。

中期方法开始显式建模模态间关系：Pathomic Fusion 和 PORPOISE 使用门控与 Kronecker 积，HMCAT 使用放射引导协同注意力，iSCLM 使用监督对比对齐，UroFusion-X 使用共注意力和门控 PoE，Brim 使用双向桥接。总体趋势是融合位置从决策层前移到特征层或中间层，并更关注模态互补性而非简单叠加。

新一代基础模型则倾向于将强视觉/文本/组学编码器预训练后，再用轻量聚合器或任务头适配下游任务，例如 Prov-GigaPath、TITAN、mSTAR、CHIEF 和基准评测框架中的冻结特征线性探针。这种范式降低了下游融合复杂度，但把关键问题转移到预训练数据质量、模态对齐和聚合器设计。

### 配对要求：患者级配对易得，空间级配对稀缺

多数病理—组学生存方法，如 Pathomic Fusion、PORPOISE、Brim、GMLF，依赖患者级配对，即同一患者的 WSI 与 bulk 分子数据。此类配对较易从 TCGA 等队列获得，但无法利用空间对应关系。

病理—放射方法，如 RPS、HMCAT、iSCLM、UroFusion-X 和 ConcatODST，通常需要检查时间、病灶分割或患者级影像与病理匹配。放射影像与活检/手术病理之间的时间一致性和病灶对应关系会显著影响方法可用性。

视觉—语言模型的配对形式更弱但规模更大：PLIP、CONCH、QUILT-1M、MUSK、TITAN、MPath-Net 使用图文对、报告、视频语音或合成描述。其优势是数据规模大，劣势是图文对齐粒度粗，可能存在噪声、幻觉和语义不精确。空间组学方法 OmiCLIP/Loki 则利用 Visium 等 spot 级配对，在空间对应上更强，但数据规模和器官覆盖仍受限。

### 缺失模态鲁棒性：从删除样本到掩码、桥接与锚模态设计

本地记录中缺失模态处理呈现明显演进。早期多模态无监督泛癌框架使用多模态 Dropout，通过随机丢弃整个模态增强鲁棒性。DyAM 将掩码机制嵌入注意力门控，使模型在推理时忽略缺失模态。Brim 通过桥接网络生成伪分子嵌入，在分子缺失时仍能利用 WSI 预测。癌症类型感知框架使用图像锚模态、零张量替代和 logit 掩码门控。UroFusion-X 使用门控 PoE 与模态 dropout。ConcatODST 使用缺失感知编码器和中间融合，保留不完整患者。皮肤病变分类中的置信度路由则从决策层体现“图像不确定时求助其他模态”的思想。

总体趋势是：缺失模态处理从训练正则化走向推理可用机制，并逐渐与模态质量、可用性和任务头设计结合。未来若用于真实临床，缺失模式本身可能还携带预后或诊疗路径信息，需要进一步建模。

### 可解释性：从热图到通路、细胞验证与多模态归因

可解释性是计算病理多模态方法的重要差异点。PAGE-Net 通过通路先验解释基因组贡献；Pathomic Fusion 和 PORPOISE 提供图像、细胞图/分子特征的多模态归因；HMCAT 生成放射—病理共注意力热图；iSCLM 进一步用 RNA-seq 和 IHC 验证模型关注区域；GMLF 使用代理模型 SHAP 解释模态和基因重要性；CHIEF、TITAN、mSTAR 等基础模型也依赖注意力或检索解释。

需要注意的是，热图可视化并不等同于临床因果证据。多篇本地记录指出解释性分析存在主观性或需要额外生物学验证。因此，更强的可解释性应同时满足：能定位关键区域、能关联已知生物标志物、能在独立队列或实验验证中复现。

### 可迁移性：基础模型提升泛化，但外部验证仍关键

基础模型和视觉—语言预训练显著提升了可迁移性。PLIP、CONCH、QUILTNET、MUSK、UNI、Prov-GigaPath、TITAN、mSTAR 均试图通过大规模预训练支持零样本、少样本或多任务迁移。基准评测框架进一步显示，不同模型在 TCGA、CPTAC、外部公开数据和域外数据上的表现可能不一致，多数投票晚融合在部分外部任务中可提升泛化。

然而，可迁移性不能只看预训练规模。MMAI 的随机临床试验验证、RPS 的多中心外部验证、iSCLM 的外部/前瞻性验证，以及 Brim 的独立队列验证，均说明任务特定验证仍然必要。基础模型特征是否能跨机构、跨染色、跨扫描仪保持稳定，是后续部署的关键问题。

### 计算与数据成本：从手工特征到超大规模预训练

手工特征方法，如 RPS、CellProfiler 多组学和列线图，计算成本相对较低，但常依赖人工 ROI 勾画、特征工程或免疫评分流程。深度 WSI 方法则面临存储、I/O 和 GPU 成本，尤其当涉及数万级 patch、图构建或长序列 slide encoder 时。

视觉—语言基础模型和全切片基础模型的数据与算力成本最高。CONCH、QUILT-1M、MUSK、Prov-GigaPath、TITAN、mSTAR 均涉及百万级图文对、十亿级 tile、超大规模文本或复杂清洗管线。对于资源有限团队，更现实的路线是使用已发布基础模型作为冻结编码器，再结合轻量融合头或缺失感知模块。

### 临床证据等级：差异显著，不能只看算法复杂度

本地记录中的临床证据差异很大。MMAI 基于随机 III 期临床试验，证据等级较高；RPS 有多中心外部验证；iSCLM 有外部测试和前瞻性队列，并提供生物学验证；DyAM 为单中心免疫治疗队列；多数 TCGA 式生存模型主要依赖内部交叉验证；联合列线图本地记录仅为摘要级证据；视觉—语言基础模型主要证明基准任务能力，尚未等同于临床终点验证。

因此，方法选择不能只看融合机制复杂度。对于临床预后或治疗决策，外部验证、试验设计、校准、决策曲线和真实缺失模式往往比单一内部指标更重要。

---

## 方法选择建议

以下建议基于本地 35 篇记录的方法特征，不构成交叉性能排名。实际选择应结合数据规模、模态完整性、标注质量、算力预算和临床验证目标。

### 面向病理＋组学预后

若目标是 H&E WSI 与突变、CNV、RNA-Seq 等分子数据联合生存预测：

- 若数据完整且希望显式建模高阶交互，可优先考虑 **Pathomic Fusion** 或 **PORPOISE/MMF**。两者均有较成熟的门控/张量融合和解释流程。
- 若分子模态可能缺失，优先考虑 **Brim**，其双向桥接可生成伪分子嵌入；也可考虑 **癌症类型感知缺失模态生存框架**，尤其当同时存在 RNA 和临床文本缺失时。
- 若更关注生物学通路解释且数据量较小，**PAGE-Net** 的通路先验设计仍有参考价值。
- 若只需要快速基线，可采用 AMIL/SNN 或 MIL+MLP 的晚期拼接，但应通过消融验证拼接是否真正优于单模态。

### 面向病理＋临床

若主要模态是 WSI 与临床表格/报告：

- 若追求较强临床验证证据，**MMAI 前列腺癌多模态系统** 是重要参考，其基于随机临床试验，融合虽简单但临床证据较强。
- 若图像模型已很强而临床变量信息有限，可参考皮肤病变分类中的 **置信度路由**，避免强制融合引入噪声。
- 若临床信息以病理报告文本形式存在，可考虑 **MPath-Net**；若需要生成式问答或报告解释，可考虑 **PathChat**。
- 若临床文本可能缺失，可参考 **癌症类型感知缺失模态生存框架** 的锚模态和掩码门控设计。

### 面向病理＋放射

若目标是 CT/MRI 与病理跨尺度融合：

- 若需要宏观影像引导微观病理聚合，优先考虑 **HMCAT** 的协同注意力设计。
- 若面向治疗反应预测且配对数据质量较高，**iSCLM** 的监督对比对齐和生物学验证值得参考。
- 若数据以手工特征为主且强调多中心临床验证，**RPS** 是经典放射病理组学路线。
- 若需要统一多任务并处理缺失模态，**UroFusion-X** 提供了较完整的共注意力加门控 PoE 方案。
- 若面向小样本生存预测且希望保留缺失患者，**ConcatODST** 的缺失感知中间融合可作为参考。

### 面向图文零样本/少样本

若目标是零样本分类、检索或少样本适配：

- 若需要病理专属图文预训练模型，优先考虑 **CONCH**、**PLIP**、**QUILTNET** 或 **MUSK**。
- 若更关注 WSI 级零样本和报告理解，可考虑 **TITAN** 或 **Prov-GigaPath** 的视觉—语言扩展。
- 若希望快速评测而不训练模型，可参考 **GPT-4V in-context learning** 范式，但要注意 API 成本、样本量限制和细粒度病理理解不足。
- 选择时应重点检查数据来源、图文对齐粒度、许可证和是否支持 WSI 级聚合。

### 面向报告生成/问答

若目标是病理报告、问答或交互式助手：

- 若需要多轮对话和诊断解释，**PathChat** 是最直接的病理生成式助手。
- 若面向标准 VQA，可参考 **TraP-VQA**，但开放问答性能仍需改进。
- 若需要图文检索或字幕生成基础能力，**CONCH**、**MUSK**、**TITAN** 更适合作为预训练底座。
- 若报告作为辅助分类模态，**MPath-Net** 提供了简单但可复现的拼接融合基线。

### 面向空间组学

若目标是 H&E 与空间转录组或转录组数据对齐：

- 首选 **OmiCLIP/Loki**，其直接面向图像—转录组对齐、注释、细胞类型分解、检索和基因表达预测。
- 若希望将空间组学纳入更大规模病理基础模型，可参考 **mSTAR** 的多模态预训练思想，但本地记录中 mSTAR 并非空间组学专用模型。
- 空间组学方法的关键不是模型规模，而是 spot 级配对质量、组织覆盖范围、基因词表设计和下游微调策略。

### 面向缺失模态

若真实场景中模态经常缺失：

- 若缺失的是分子/组学数据，优先考虑 **Brim** 的伪分子桥接，或 **癌症类型感知缺失模态生存框架** 的图像锚模态加掩码门控。
- 若多种临床模态均可能缺失，**UroFusion-X** 的门控 PoE 与模态 dropout 较系统。
- 若希望保留不完整患者且不做插补，**ConcatODST** 的缺失感知编码和中间融合值得参考。
- 若只是训练阶段增强鲁棒性，可借鉴早期泛癌框架的 **多模态 Dropout**。
- 若缺失发生在决策层且主模态模型置信度可用，可参考皮肤病变分类的 **置信度路由**。

---

## 文档覆盖索引

1. [详细解读](method_summaries/PMID_29531073_Predicting%20cancer%20outcomes%20from%20histology%20and%20genomics%20using%20convolutional%20networks.md)
2. [详细解读](method_summaries/PMID_31510656_Deep%20learning%20with%20multimodal%20representation%20for%20pancancer%20prognosis%20prediction.md)
3. [详细解读](method_summaries/PMID_31797610_PAGE-Net_%20Interpretable%20and%20Integrative%20Deep%20Learning%20for%20Survival%20Analysis%20Using%20Histopathological%20Images%20and%20Genomic%20D.md)
4. [详细解读](method_summaries/PMID_32729045_Multiparametric%20MRI%20and%20Whole%20Slide%20Image-Based%20Pretreatment%20Prediction%20of%20Pathological%20Response%20to%20Neoadjuvant%20Chemorad.md)
5. [详细解读](method_summaries/PMID_32881682_Pathomic%20Fusion_%20An%20Integrated%20Framework%20for%20Fusing%20Histopathology%20and%20Genomic%20Features%20for%20Cancer%20Diagnosis%20and%20Prognos.md)
6. [详细解读](method_summaries/PMID_33838393_Combining%20CNN-based%20histologic%20whole%20slide%20image%20analysis%20and%20patient%20data%20to%20improve%20skin%20cancer%20classification.md)
7. [详细解读](method_summaries/PMID_34275655_Integration%20of%20histopathological%20images%20and%20multi-dimensional%20omics%20analyses%20predicts%20molecular%20features%20and%20prognosis%20i.md)
8. [详细解读](method_summaries/PMID_35073937_Development%20of%20a%20novel%20combined%20nomogram%20model%20integrating%20deep%20learning-pathomics%2C%20radiomics%20and%20immunoscore%20to%20predict.md)
9. [详细解读](method_summaries/PMID_35358054_Vision-Language%20Transformer%20for%20Interpretable%20Pathology%20Visual%20Question%20Answering.md)
10. [详细解读](method_summaries/PMID_35676445_Prostate%20cancer%20therapy%20personalization%20via%20multi-modal%20deep%20learning%20on%20randomized%20phase%20III%20clinical%20trials.md)
11. [详细解读](method_summaries/PMID_35944502_Pan-cancer%20integrative%20histology-genomic%20analysis%20via%20multimodal%20deep%20learning.md)
12. [详细解读](method_summaries/PMID_36038778_Multimodal%20integration%20of%20radiology%2C%20pathology%20and%20genomics%20for%20prediction%20of%20response%20to%20PD-%28L%291%20blockade%20in%20patients%20w.md)
13. [详细解读](method_summaries/PMID_36682215_Hierarchical%20multimodal%20fusion%20framework%20based%20on%20noisy%20label%20learning%20and%20attention%20mechanism%20for%20cancer%20classification.md)
14. [详细解读](method_summaries/PMID_36991216_Multimodal%20deep%20learning%20to%20predict%20prognosis%20in%20adult%20and%20pediatric%20brain%20tumors.md)
15. [详细解读](method_summaries/PMID_37030860_Survival%20Prediction%20via%20Hierarchical%20Multimodal%20Co-Attention%20Transformer_%20A%20Computational%20Histology-Radiology%20Solution.md)
16. [详细解读](method_summaries/PMID_37592105_A%20visual-language%20foundation%20model%20for%20pathology%20image%20analysis%20using%20medical%20Twitter.md)
17. [详细解读](method_summaries/PMID_38504017_A%20visual-language%20foundation%20model%20for%20computational%20pathology.md)
18. [详细解读](method_summaries/PMID_38504018_Towards%20a%20general-purpose%20foundation%20model%20for%20computational%20pathology.md)
19. [详细解读](method_summaries/PMID_38742142_Quilt-1M_%20One%20Million%20Image-Text%20Pairs%20for%20Histopathology.md)
20. [详细解读](method_summaries/PMID_38778098_A%20whole-slide%20foundation%20model%20for%20digital%20pathology%20from%20real-world%20data.md)
21. [详细解读](method_summaries/PMID_38866050_A%20multimodal%20generative%20AI%20copilot%20for%20human%20pathology.md)
22. [详细解读](method_summaries/PMID_39232164_A%20pathology%20foundation%20model%20for%20cancer%20diagnosis%20and%20prognosis%20prediction.md)
23. [详细解读](method_summaries/PMID_39572531_In-context%20learning%20enables%20multimodal%20large%20language%20models%20to%20classify%20cancer%20pathology%20images.md)
24. [详细解读](method_summaries/PMID_39637859_Interpretable%20multi-modal%20artificial%20intelligence%20model%20for%20predicting%20gastric%20cancer%20response%20to%20neoadjuvant%20chemothera.md)
25. [详细解读](method_summaries/PMID_39779851_A%20vision-language%20foundation%20model%20for%20precision%20oncology.md)
26. [详细解读](method_summaries/PMID_40051298_Interpretable%20Multimodal%20Fusion%20Model%20for%20Bridged%20Histology%20and%20Genomics%20Survival%20Prediction%20in%20Pan-Cancer.md)
27. [详细解读](method_summaries/PMID_40121304_Predicting%20response%20to%20neoadjuvant%20chemotherapy%20in%20muscle-invasive%20bladder%20cancer%20via%20interpretable%20multimodal%20deep%20lear.md)
28. [详细解读](method_summaries/PMID_40442373_A%20visual-omics%20foundation%20model%20to%20bridge%20histopathology%20with%20spatial%20transcriptomics.md)
29. [详细解读](method_summaries/PMID_40463538_Comparing%20Computational%20Pathology%20Foundation%20Models%20using%20Representational%20Similarity%20Analysis.md)
30. [详细解读](method_summaries/PMID_41193692_A%20multimodal%20whole-slide%20foundation%20model%20for%20pathology.md)
31. [详细解读](method_summaries/PMID_41230238_Multimodal%20Data%20Fusion%20for%20Whole-Slide%20Histopathology%20Image%20Classification.md)
32. [详细解读](method_summaries/PMID_41387679_A%20multimodal%20knowledge-enhanced%20whole-slide%20pathology%20foundation%20model.md)
33. [详细解读](method_summaries/PMID_41554842_UroFusion-X_%20a%20unified%20multimodal%20deep%20learning%20framework%20for%20robust%20diagnosis%2C%20subtyping%2C%20and%20prognosis%20of%20urological%20c.md)
34. [详细解读](method_summaries/PMID_41870128_A%20cancer-type-aware%20framework%20for%20robust%20multimodal%20survival%20prediction%20under%20missing%20modalities.md)
35. [详细解读](method_summaries/PMID_42332139_Handling%20missing%20modalities%20in%20multimodal%20survival%20prediction%20for%20non-small%20cell%20lung%20cancer.md)
