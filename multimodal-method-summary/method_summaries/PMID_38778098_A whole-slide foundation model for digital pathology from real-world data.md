# A whole-slide foundation model for digital pathology from real-world data. 方法总结

> 证据说明：本地全文状态为 available，元数据显示共 25 个章节，可用正文证据约 40,557 字符。可用内容覆盖摘要、方法概述、预处理、预训练细节、下游任务、视觉-语言对齐、讨论、数据/代码可用性等；但本地文本未提供完整补充材料、公式推导、网络维度、LongNet 内部结构细节、FLOPs/显存定量值等，因此相关部分会标注“未说明”或“本地证据不足”。

## 一、论文基本信息

- **论文标题**：A whole-slide foundation model for digital pathology from real-world data.
- **作者**：Hanwen Xu, Naoto Usuyama, Jaspreet Bagga, Sheng Zhang, Rajesh Rao, Tristan Naumann, Cliff Wong, Zelalem Gero, Javier González, Yu Gu, Yanbo Xu, Mu Wei, Wenhui Wang, Shuming Ma, Furu Wei, Jianwei Yang, Chunyuan Li, Jianfeng Gao, Jaylen Rosemon, Tucker Bower, Soohee Lee, Roshanthi Weerasinghe, Bill J Wright, Ari Robicsek, Brian Piening, Carlo Bifulco, Sheng Wang, Hoifung Poon
- **发表年份**：2024
- **会议/期刊**：Nature
- **论文链接/DOI/arXiv ID**：DOI: 10.1038/s41586-024-07441-w；本地文本未提供 arXiv ID
- **代码仓库**：https://github.com/prov-gigapath/prov-gigapath
- **研究任务**：数字病理全切片基础模型预训练与下游预测，包括 pathomics、癌症亚型分类、基因突变预测、总体肿瘤突变负荷预测，以及基于病理报告的视觉-语言零样本预测。
- **数据模态**：全切片病理图像（H&E 染色和免疫组化病理切片）、病理报告文本；下游标签包括癌症亚型、基因突变状态、PD-L1/生物标志物状态、总体肿瘤突变负荷等。

## 二、论文整体概述

### 1. 核心问题

论文聚焦数字病理基础模型在真实世界临床数据上的三个主要挑战：

1. 公开病理预训练数据相对稀缺且质量不均，例如既有模型主要基于 TCGA 数据预训练，可能不足以覆盖真实世界数字病理中的异质性和噪声伪影。
2. 全切片病理图像是 gigapixel 级图像，一张切片可能包含数万甚至超过七万个 image tiles；现有方法常将 tile 独立处理或仅做小范围采样，难以同时建模局部 tile 模式和全切片全局模式。
3. 基于大规模真实世界患者数据预训练的病理基础模型通常不公开，限制了其在临床研究和应用中的可及性。

### 2. 整体方法

论文提出 Prov-GigaPath，一个基于真实世界大规模病理数据预训练的全切片病理基础模型。整体流程包括：

1. 对 WSI 进行组织分割、分辨率标准化和切块，得到 256 × 256 的 image tiles。
2. 使用 tile encoder 对每个 tile 编码为紧凑嵌入；tile encoder 采用 ViT 架构，并使用 DINOv2 自监督预训练。
3. 使用 slide encoder 对整张切片的 tile embedding 序列建模；slide encoder 采用 LongNet 架构，并结合 masked autoencoder 进行 slide-level 自监督预训练。
4. 在下游任务中，LongNet 输出 contextualized tile embeddings，再通过一个简单的 softmax attention / ABMIL 层聚合为 slide-level embedding，最后输入任务特定分类器。
5. 论文还利用病理报告进行视觉-语言继续预训练：以 Prov-GigaPath 作为视觉编码器，以 PubMedBERT 作为文本编码器，使用跨模态对比学习进行 slide-level 图文对齐。

### 3. 主要贡献

1. 构建并使用真实世界大规模病理数据集 Prov-Path，包含 171,189 张全切片、1,384,860,229 个 256 × 256 image tiles，来自超过 30,000 名患者和 31 种主要组织类型；并开放模型权重与代码。
2. 提出 GigaPath 架构，将 LongNet 适配到数字病理全切片建模，以处理数万级 tile 的超长序列 slide-level 自监督学习。
3. 建立包含 9 个癌症亚型任务和 17 个 pathomics 任务的数字病理基准，并进一步探索 slide-level 病理图像与病理报告的视觉-语言预训练。

---

## 三、方法总结

### 方法 1：Prov-GigaPath / GigaPath 全切片病理基础模型

#### 1. 核心思想与解决的问题

- **目标问题**：在 gigapixel 级病理全切片上同时学习局部 tile 级病理结构和全切片级全局上下文，并支持癌症亚型、基因突变、pathomics 及视觉-语言预测等下游任务。
- **现有方法的局限**：
  - 既有公开病理基础模型多基于 TCGA 等公开数据预训练，论文认为其规模和真实世界多样性不足。
  - 许多方法将每个 tile 视为独立样本，并用 multiple instance learning 聚合，限制了对全切片复杂全局模式的建模。
  - 传统 Transformer 的自注意力计算随序列长度平方增长，难以直接处理一张 WSI 中数万级 tile 的长序列。
  - 大规模真实世界患者数据预训练的模型通常不公开。
- **核心思想**：将 WSI 中的 image tiles 先编码为 visual tokens，把一张切片表示为长序列 token 序列；随后使用 LongNet 的 dilated self-attention 进行超长序列 slide-level 建模，并结合 masked autoencoder 自监督预训练。
- **创新点**：
  - 作者声称的创新：将 LongNet 适配到数字病理全切片预训练；利用大规模真实世界 Prov-Path 数据训练开放权重基础模型；探索 slide-level 病理图像与病理报告对齐。
  - 由本地消融证据支持的创新：LongNet slide encoder 预训练对癌症亚型任务有贡献；LongNet slide encoder 优于仅使用 ABMIL 聚合；DINOv2 tile-level 预训练优于 SimCLR 和 masked autoencoder；在相同架构下，Prov-Path 预训练优于 TCGA 预训练。
  - 需要注意：新增病理报告模态本身不自动构成算法创新；本地文本中视觉-语言融合主要是标准跨模态对比学习，未说明复杂交叉注意力或细粒度融合机制。

#### 2. 详细结构与数据流

- **输入**：
  - 主输入：H&E 染色或免疫组化病理全切片图像。
  - 切块后输入：256 × 256 image tiles。
  - 视觉-语言扩展输入：与 WSI 关联的病理报告文本。
- **数据预处理**：
  - 图像预处理：
    1. 使用 Otsu 阈值在降采样分辨率下进行组织分割，以过滤背景区域。
    2. 使用 pyvips 将 WSI 标准化到 0.5 μm per pixel，即 20× magnification。
    3. 将图像裁剪为 256 × 256 tiles。
    4. 丢弃 Otsu 算法判定 occupancy 小于 0.1 的 tiles。
    5. 预处理在最多 200 个节点上并行完成，每个节点 32 CPU cores、256 GB RAM，总耗时约 157 小时。
  - 文本预处理：
    1. 移除病理报告中与癌症诊断无关的信息，如医院位置、医生姓名、患者姓名。
    2. 使用 k-means 将临床报告聚为 4 类，并选取聚类中心作为 4 个代表报告。
    3. 人工清洗这 4 个报告，形成原始报告和清洗报告对。
    4. 使用 GPT-3.5 基于这 4 个 in-context learning 示例清洗其余报告。
- **单模态编码**：
  - 图像 tile 编码：tile encoder 使用 ViT 架构，采用标准 DINOv2 设置，在 1,384,860,229 个 segmented tiles 上预训练。
  - 图像 slide 编码：slide encoder 使用 LongNet 架构，输入 tile embeddings 序列，生成考虑全切片上下文的 contextualized tile embeddings。
  - 文本编码：视觉-语言部分使用 PubMedBERT 作为文本编码器；本地文本同时提到 text-embedding-ada-002 用于文本嵌入计算，但其在训练或推理中的具体角色未说明。
- **跨模态融合**：
  - 图像模态内部：LongNet 对 tile embeddings 序列进行长上下文建模，属于图像模态内的序列上下文融合，不是图文跨模态融合。
  - 真正跨模态融合：视觉-语言阶段使用标准 cross-modal contrastive loss，对 WSI 视觉表示和病理报告文本表示进行 slide-level 对齐。
  - 本地文本未说明是否存在 tile-text 细粒度对齐、交叉注意力或其他复杂图文融合机制。
- **处理流程**：
  1. WSI 经组织分割、分辨率标准化和切块，得到 256 × 256 tiles。
  2. tile encoder 将每个 tile 编码为 tile embedding。
  3. slide encoder 以 tile embedding 序列为输入，使用 LongNet 生成 contextualized tile embeddings。
  4. 下游任务中，使用 softmax attention / ABMIL 层聚合 contextualized tile embeddings，得到 slide-level embedding。
  5. slide-level embedding 输入额外分类器，用于突变预测、癌症亚型分类、TMB 预测等任务。
  6. 可选地，使用 WSI-report pairs 对视觉编码器和文本编码器进行跨模态对比学习，得到视觉-语言预训练模型。
- **输出**：
  - slide-level embeddings。
  - contextualized tile embeddings。
  - 下游任务预测输出，例如基因突变状态、癌症亚型、High/Low TMB 等。
  - 视觉-语言预训练后可用于零样本癌症亚型预测和零样本基因突变预测。
- **模块在整体网络中的位置**：
  - tile encoder 位于前端，用于局部图像特征提取。
  - LongNet slide encoder 位于中部，用于全切片长序列上下文建模。
  - ABMIL/softmax attention 聚合层和任务分类头位于末端。
  - 视觉-语言模块是在图像基础模型之上的继续预训练扩展。
- **与其他模块的连接方式**：
  - tile encoder 的输出序列作为 LongNet slide encoder 的输入。
  - LongNet 的输出经过 ABMIL/softmax attention 聚合后进入下游分类器。
  - 视觉-语言阶段中，Prov-GigaPath 视觉表示与 PubMedBERT 文本表示通过对比损失对齐。

#### 3. 数学公式

本地文本不足以可靠恢复公式。原文仅提到 DINOv2、masked autoencoder、cross-modal contrastive loss、softmax attention layer / ABMIL，但未给出可恢复的数学表达式。

#### 4. 输入输出维度

| 阶段 | 张量/变量 | 维度 | 说明 |
|---|---|---|---|
| 输入 | 全切片图像 WSI | 未说明 | 本地文本仅说明为标准 gigapixel pathology slide，未给出原始 WSI 像素维度 |
| 输入 | image tiles | 256 × 256；单张 WSI 可含数万 tiles，Providence 数据中最多为 70,121 | 原文说明 tile 尺寸为 256 × 256；通道数未说明 |
| 输入 | tile 坐标网格参数 | grid size dgrid = 256；rows/columns ngrid = 1,000 | 用于 tile coordinates discretizing 的设置 |
| 中间表示 | tile embeddings | [N_tiles, d_tile]；d_tile 未说明 | tile encoder 输出，N_tiles 为单张 WSI 的 tile 数量 |
| 中间表示 | LongNet contextualized tile embeddings | [N_tiles, d_context]；d_context 未说明 | slide encoder 输出 |
| 中间表示 | 文本报告表示 | 未说明 | PubMedBERT 编码病理报告；具体向量维度未说明 |
| 输出 | slide embedding | 未说明 | 由 softmax attention / ABMIL 聚合得到 |
| 输出 | 下游任务 logits | 任务相关：18 biomarkers 多标签、5-gene 多标签、TMB 二分类、癌症亚型多分类 | 具体输出维度取决于任务；本地文本未给出统一分类头维度 |

#### 5. 实现伪代码


```python

```

#### 6. 实现提示

- **关键网络组件**：
  - tile encoder：ViT 架构，使用标准 DINOv2 设置。
  - slide encoder：LongNet 架构，用于超长序列 slide-level 建模。
  - 聚合层：softmax attention layer / ABMIL layer。
  - 下游预测头：额外分类器，具体结构未说明。
  - 视觉-语言文本编码器：PubMedBERT。
  - 视觉-语言训练代码库：OpenCLIP codebase。
- **重要超参数**：
  - DINOv2 tile pretraining：base learning rate = 4 × 10⁻³；每 GPU batch size = 12；总有效 batch size = 384。
  - LongNet slide pretraining：learning rate = 5 × 10⁻⁴；每 GPU batch size = 4；训练 30 epochs；初始 epoch 作为 warmup。
  - slide pretraining 坐标增强：grid size dgrid = 256；rows/columns ngrid = 1,000；cropping ratio = 0.875；水平翻转 tile coordinates 概率 = 0.5。
  - 突变预测下游微调：Prov-GigaPath base learning rate = 2 × 10⁻³；weight decay = 0.01；batch size = 1；gradient accumulation steps = 32；训练 20 epochs。
  - 癌症亚型下游微调：Prov-GigaPath base learning rate = 4 × 10⁻³；weight decay = 0.001；layer-wise learning rate decay = 0.9；训练 20 epochs。
  - 视觉-语言对比预训练：learning rate = 5 × 10⁻⁴；batch size = 32；训练 10 epochs；前 100 iterations 为 warmup。
- **归一化/激活方式**：
  - 明确提到下游聚合使用 softmax attention。
  - 其他归一化或激活方式未说明。
- **维度对齐方式**：
  - tile embedding 到 LongNet 输入序列的维度对齐方式未说明。
  - 视觉与文本表示在对比学习中的投影或维度对齐方式未说明。
- **实现注意事项**：
  - 在 slide-level 自监督预训练中，tile-level encoder 被冻结以降低显存开销；论文作者也提到这可能不是最优。
  - 下游任务中，Prov-GigaPath 冻结 tile encoder，仅微调 LongNet slide-level encoder。
  - 在癌症亚型任务中，额外添加 shortcut 到 slide-level encoder，以更多关注 tile-level features。
  - 预处理选择 20× magnification；更大 magnification 会增加处理时间。
  - 患者通常有多张 WSI 时，突变预测任务选择最大 WSI，以实现 patient-level stratification。
  - 报告清洗依赖 GPT-3.5 in-context learning；本地文本未说明该步骤是否是最终模型性能的必要条件。
- **依赖的特殊算子或第三方库**：
  - LongNet / dilated self-attention。
  - DINOv2。
  - masked autoencoder。
  - pyvips，用于 WSI 分辨率标准化。
  - OpenCLIP codebase，用于视觉-语言处理。
  - PubMedBERT。
  - GPT-3.5 和 text-embedding-ada-002 用于报告处理/嵌入相关步骤；具体工程角色未完全说明。

#### 7. 计算与资源开销

- **理论计算复杂度**：本地文本未给出 LongNet 的具体复杂度公式；仅说明传统 Transformer self-attention 计算随序列长度平方增长，因此使用 LongNet 以扩展到数万 tiles。
- **参数量**：Prov-GigaPath 主模型参数量未说明；本地文本仅提到一个 23 million parameters 的小版本。
- **FLOPs/MACs**：未说明。
- **显存开销**：未给出具体数值；本地文本仅提到冻结 tile encoder 以降低 memory cost，以及 slide encoder pretraining 使用 16 nodes、每 node 4 × 80 GB A100 GPUs。
- **推理速度**：单张 WSI 平均推理时间约 0.7 秒，其中约 0.4 秒用于计算 tile embeddings，约 0.3 秒用于 LongNet inference。
- **论文是否提供效率对比**：未说明；本地文本未提供与其他方法的系统效率对比。

#### 8. 适用场景与可迁移性

- **原论文应用场景**：
  - 数字病理全切片分析。
  - 癌症亚型分类。
  - 基因突变预测。
  - 总体肿瘤突变负荷预测。
  - 17 个 pathomics 任务。
  - 基于病理报告的零样本视觉-语言预测。
- **可迁移到的任务/数据集**：
  - 论文评估中使用了 Providence 和 TCGA 数据。
  - 作者认为 GigaPath 可扩展到其他生物医学问题，包括大型 2D/3D 图像和视频，但本地文本未给出这些扩展实验。
- **迁移所需调整**：
  - 需要将 WSI 预处理为 20×、256 × 256 tiles。
  - 需要任务特定标注数据用于下游微调。
  - 需要适配任务特定分类头。
  - 若进行视觉-语言迁移，需要 WSI-report pairs 或类似图文对。
- **适用条件**：
  - 适合拥有大规模未标注 WSI 的预训练场景。
  - 适合需要全切片上下文建模的下游任务。
  - 需要较强计算资源，尤其是预训练阶段。
- **潜在限制**：
  - Prov-Path 预训练数据为专有真实世界数据，不能公开。
  - 突变预测性能在不同任务间存在变异，论文认为某些突变可能无法仅靠病理图像充分预测。
  - 预训练时冻结 tile encoder 可能次优。
  - 仅选择 20× magnification，未探索更高 magnification。
  - 视觉-语言部分仍处于初步探索阶段，距离临床对话式助手仍有距离。

#### 9. 实验与消融证据

- **主要性能结果**：
  - 论文报告 Prov-GigaPath 在 26 个任务中的 25 个任务上优于所比较的公开病理基础模型。
  - 在 18 个任务上相对第二名方法有显著提升。
  - 在 TCGA EGFR mutation prediction 上，论文报告相对 REMEDIS 提升 23.5% AUROC 和 66.4% AUPRC。
  - 在 pan-cancer 18 biomarkers 预测上，相对最佳竞争方法平均提升 3.3% macro-AUROC 和 8.9% macro-AUPRC。
  - 在 LUAD 5-gene mutation prediction 上，平均 macro-AUROC 为 0.626。
  - 在 pan-cancer 5-gene mutation prediction 上，相对最佳竞争方法提升 6.5% macro-AUROC 和 18.7% AUPRC。
  - 在总体 TMB 预测上，平均 AUROC 为 0.708。
  - 在 9 个癌症亚型任务上，Prov-GigaPath 均优于所有比较方法，其中 6 个癌症类型相对第二名有显著提升。
  - 在零样本癌症亚型和零样本基因突变预测上，论文报告其优于 MI-Zero、BiomedCLIP、PLIP 等视觉-语言模型。
- **相对基线的提升**：
  - 与 HIPT、CtransPath、REMEDIS 等公开模型相比，论文报告多数任务有提升。
  - 在 TCGA LUAD 突变预测中，竞争方法均使用 TCGA 预训练，而 Prov-GigaPath 未使用 TCGA 预训练，仍报告优势。
- **相关消融实验**：
  - 将预训练 LongNet encoder 替换为随机初始化模型，平均 AUROC 从 0.903 降至 0.886。
  - 冻结与不冻结 LongNet encoder 在癌症亚型任务上表现相近。
  - 移除 LongNet，仅用 ABMIL 层聚合，平均性能低于 LongNet slide encoder。
  - DINOv2 tile pretraining 优于 SimCLR 和 masked autoencoder tile pretraining。
  - Prov-GigaPath 优于使用 ImageNet 训练的监督学习方法。
  - 同一 GigaPath 架构在 Prov-Path 上预训练优于在 TCGA 上预训练。
  - 在 Prov-Path 上，GigaPath 优于 HIPT。
- **作者结论**：
  - 真实世界大规模数据和全切片建模对数字病理基础模型很重要。
  - LongNet slide-level 建模有助于捕获全局病理模式。
  - slide-level 视觉-语言对齐具有潜力。
- **证据是否充分**：
  - 对图像基础模型、LongNet slide encoder、DINOv2 tile pretraining 和大规模真实世界数据价值，本地正文提供了较充分的基准和消融证据。
  - 对公式、网络维度、FLOPs、显存、效率对比、视觉-语言融合细节等，本地证据不足。

#### 10. 方法评估

| 维度 | 评价 | 依据 |
|---|---|---|
| 创新性 | 高 | 将 LongNet 用于全切片病理长序列建模，并结合真实世界超大规模数据开放权重；但视觉-语言部分主要是标准对比学习，不能仅因新增报告模态视为复杂算法创新 |
| 技术可行性 | 高 | 代码和权重公开，预训练与下游微调的关键超参数较明确；但完整复现依赖大规模数据和计算资源 |
| 实现难度 | 高 | 涉及十亿级 tile 预处理、DINOv2 tile pretraining、LongNet slide pretraining、多任务下游评测和报告清洗 |
| 架构相关性 | 高 | 架构直接针对 gigapixel WSI 的长序列、局部-全局建模问题 |
| 可迁移性 | 中 | 可迁移到其他 WSI 或高分辨率生物医学图像任务，但预训练和部署需要较大数据与算力；小模型版本可缓解部分问题 |
| 计算成本 | 高 | slide encoder pretraining 使用 16 nodes、4 × 80 GB A100 GPUs，约 2 天 / 3,072 A100 GPU hours；预处理使用 200 nodes 约 157 小时 |

#### 11. 一句话总结

Prov-GigaPath 通过 DINOv2 tile-level 自监督预训练、LongNet slide-level 长序列 masked autoencoder 预训练和 ABMIL 聚合，构建了一个面向真实世界 gigapixel 病理切片的开放权重基础模型，并在癌症亚型、突变预测和病理报告视觉-语言任务中展示了全切片上下文建模的价值。

## 四、论文级综合评价

### 1. 最值得借鉴的方法

1. 两阶段病理基础模型预训练范式：先用 DINOv2 学习 tile-level 局部视觉表示，再用 LongNet masked autoencoder 学习 slide-level 全局上下文。
2. 将 WSI 表示为 tile embedding 长序列，并用长序列 Transformer 方法建模全切片上下文。
3. 下游使用简单 softmax attention / ABMIL 聚合 LongNet contextualized tile embeddings，再接任务分类头。
4. 真实世界 WSI 预处理流程：Otsu 组织分割、20× 分辨率标准化、256 × 256 切块、低组织占比 tile 过滤。
5. 利用自然存在的 WSI-report pairs 进行 slide-level 视觉-语言对比预训练，而非仅 tile-level 图文对齐。

### 2. 方法之间的关系

论文只有一个命名核心框架：Prov-GigaPath / GigaPath。其内部模块关系为：

1. tile encoder 为 slide encoder 提供输入 token。
2. LongNet slide encoder 对 tile embedding 序列进行上下文建模。
3. ABMIL/softmax attention 将 LongNet 输出聚合为 slide-level representation。
4. 下游分类器基于 slide-level representation 做预测。
5. 视觉-语言预训练是在图像基础模型之上的继续预训练扩展，不是独立于 Prov-GigaPath 的另一个核心方法。

### 3. 复现可行性

- **代码是否公开**：是；论文明确提供 GitHub 仓库，并包含模型权重和相关源码。
- **方法描述是否完整**：较完整；本地正文提供了预处理、预训练、下游微调和视觉-语言训练的关键设置，但公式、维度、LongNet 细节和分类头细节不足。
- **关键配置是否明确**：部分明确；学习率、batch size、训练轮数、坐标网格参数、推理时间等有说明；但网络维度、损失函数具体形式、显存和 FLOPs 未说明。
- **预计复现难点**：
  - Prov-Path 预训练数据为专有真实世界数据，无法公开。
  - 十亿级 tiles 的预处理和存储开销较大。
  - LongNet slide-level pretraining 需要大规模 GPU 资源。
  - 病理报告清洗涉及 GPT-3.5 和人工校验，流程较复杂。
  - 下游任务需要匹配基因突变、癌症亚型、TMB 等标签。

### 4. 与当前研究方向的关系

- **可直接采用的设计**：
  - WSI 到 256 × 256 tiles 的预处理流程。
  - 冻结 tile encoder、微调 slide encoder 的下游适配策略。
  - 使用 ABMIL/softmax attention 聚合 slide-level 表示。
  - 对长序列病理表示进行自监督预训练的思路。
  - 使用真实世界病理报告进行图文对比预训练。
- **需要改造的设计**：
  - 在算力有限时，可考虑小模型版本、子采样、局部窗口建模或分阶段训练。
  - 若需要细粒度图文对齐，需要补充 tile-text、region-text 或报告片段级对齐机制。
  - 若目标数据集染色、扫描仪或分辨率差异较大，需要重新评估 20× 和 256 tile 设置。
  - 若希望端到端优化，需要解决冻结 tile encoder 带来的潜在次优问题。
- **可能形成的新研究思路**：
  - 病理基础模型中的 scaling laws：比较不同模型规模与预训练数据规模。
  - 结合病理图像、病理报告、基因组突变和临床记录的多模态预后/预测模型。
  - 面向罕见癌型或罕见突变的零样本/少样本病理学习。
  - 从 2D WSI 扩展到 3D 病理、连续切片或视频化病理数据。

### 5. 阅读备注

本地正文足以概括 Prov-GigaPath 的总体架构、预训练策略、下游任务设置和主要消融结论，但不足以恢复完整数学公式、网络维度、LongNet 内部实现细节、FLOPs/显存定量指标和所有补充材料内容。性能比较应理解为论文在其设定数据和任务划分下的结果，不应直接外推为不同数据划分或不同基准下的绝对排名。
