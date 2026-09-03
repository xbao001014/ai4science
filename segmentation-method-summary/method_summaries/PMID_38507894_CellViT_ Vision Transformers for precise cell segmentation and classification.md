# CellViT: Vision Transformers for precise cell segmentation and classification 方法总结

> 证据说明：元数据显示全文状态为 “manual PDF verified”，PDF 共 16 页、提取字符数 117197；但本次可见本地正文仅包含第 1、2、7、8、9、10、15、16 页，证据字符数约 69506。方法主体、数据集、训练策略、主要实验与部分公式可从本地文本恢复；但完整网络细节、损失函数公式、附录超参数、具体后处理实现、效率数值表等内容可能因本地证据不完整而标注为“未说明”或“本地证据不足”。

## 一、论文基本信息

- **论文标题**：CellViT: Vision Transformers for precise cell segmentation and classification
- **作者**：Fabian Hörst, Moritz Rempe, Lukas Heine, Constantin Seibold, Julius Keyl, Giulia Baldini, Selma Ugurel, Jens Siveke, Barbara Grünwald, Jan Egger, Jens Kleesiek
- **发表年份**：2024
- **会议/期刊**：Medical Image Analysis
- **论文链接/DOI/arXiv ID**：10.1016/j.media.2024.103143
- **代码仓库**：https://github.com/TIO-IKIM/CellViT
- **研究任务**：H&E 染色组织图像中的细胞核检测、实例分割与细胞核分类；同时支持从推理过程中提取细胞核嵌入特征
- **数据模态**：单模态数字化病理图像，具体为 H&E 染色组织图像/全切片图像（WSI）的图像块；不包含其他非图像模态

## 二、论文整体概述

### 1. 核心问题

论文关注 H&E 染色组织图像中细胞核的自动检测、实例分割和分类。该任务在数字病理中很重要，但存在以下困难：

- 细胞核在染色、大小、形状上具有较大差异；
- 细胞核边界可能重叠；
- 细胞核可能聚集；
- 数据集存在明显类别不平衡，尤其是 dead cells 类别严重不足；
- 传统 CNN 方法虽然常用，但在细胞特征提取、可解释性和下游任务衔接方面存在限制；
- 若对每个检测到的细胞再单独裁剪并运行 CNN 提取特征，会带来额外计算开销。

因此，论文希望构建一种能够同时完成细胞核实例分割、分类和细胞特征提取的模型，并利用大规模预训练提升性能。

### 2. 整体方法

论文提出 CellViT。整体结构为 U-Net 形状的 encoder-decoder 网络：

- 编码器使用 Vision Transformer，而不是传统 CNN；
- 输入图像被转换为 token 序列；
- 编码器在多个深度层输出特征，并通过 skip connections 传给解码器；
- 解码器进行上采样并生成细胞核实例分割结果；
- 模型可从 Transformer 编码器中提取与检测到的细胞核空间位置相关的 token embedding；
- 论文比较了多种预训练编码器，包括在组织学图像上预训练的 ViT256，以及 Segment Anything Model 的 ViT-B、ViT-L、ViT-H 编码器；
- 训练和主要评估在 PanNuke 数据集上进行；
- 推理阶段可使用 1024×1024 px 的大图像块，并以 64 px overlap 处理 WSI；
- 每个检测到的细胞核可导出类别、bounding-box、边界多边形、质心，以及对应的嵌入向量。

### 3. 主要贡献

1. 提出 CellViT：一种用于细胞核实例分割与分类的 U-Net 形状 Vision Transformer encoder-decoder 网络，并在 PanNuke 数据集上取得较强的检测与分割性能；消融实验显示性能提升主要来自大规模预训练编码器。
2. 提供面向 Gigapixel WSI 的快速推理流程：使用 1024×1024 px 大图像块和 64 px overlap，相比 HoVer-Net 推理流程快 1.85 倍。
3. 在推理过程中直接提取与细胞核空间位置相关的 Transformer token embedding，避免对每个细胞核再次裁剪并进行额外前向传播，从而支持下游疾病预测、治疗反应预测或生存预测等任务。

---

## 三、方法总结

### 方法 1：CellViT

#### 1. 核心思想与解决的问题

- **目标问题**：在 H&E 染色数字化组织样本中实现细胞核实例分割、检测和分类，并同时获得可用于下游任务的细胞核特征。
- **现有方法的局限**：
  - CNN 是现有细胞核分割方法的常见骨干，但在长程上下文建模和特征可解释性方面存在限制；
  - 手工细胞特征可能性能有限；
  - 对每个细胞单独裁剪并用 CNN 提取深度特征会带来额外计算成本；
  - 医学图像数据相对有限，而 ViT 通常需要更多数据，因此需要强预训练模型；
  - 细胞核存在重叠、聚集、染色差异、大小差异和类别不平衡。
- **核心思想**：用大规模预训练的 Vision Transformer 替换 CNN 编码器，并保留 U-Net 形状的 encoder-decoder 分割结构；利用 ViT token 与细胞核空间位置的对应关系，在分割推理的同时提取细胞核嵌入。
- **创新点**：
  - 作者声称的创新包括：用于细胞核实例分割的 U-Net 形状 ViT encoder-decoder 架构、大尺寸 WSI 推理流程、同步细胞核嵌入提取。
  - 由本地实验证据更直接支持的创新包括：大规模 in-domain 和 out-of-domain 预训练编码器显著提升检测性能；数据增强对性能提升很关键；1024×1024 px 推理流程可提升 WSI 推理效率。
  - 需要说明的是，CellViT 并非引入新的数据模态；本文没有真正的跨模态融合设计，其核心仍是单模态病理图像建模。

#### 2. 详细结构与数据流

- **输入**：
  - H&E 染色组织图像块；
  - PanNuke 训练图像为 256×256 px，分辨率 0.25 μm/px；
  - WSI 推理使用 1024×1024 px 图像块，overlap 为 64 px；
  - MoNuSeg 测试图像被 resize 到 1024×1024 px；也可构建 0.50 μm/px、512×512 px 的版本；
  - 输入图像颜色通道数在本地文本中未明确说明。
- **数据预处理**：
  - 将 WSI 切分为图像块进行推理；
  - 推理时使用 1024×1024 px 图像块和 64 px overlap；
  - 缩放输入图像时需要考虑插值方法；
  - 训练时使用基于组织类别和细胞类别的自定义过采样策略；
  - 训练时使用多种数据增强：随机 90 度旋转、水平翻转、垂直翻转、降采样、模糊、高斯噪声、颜色抖动、SLIC superpixel 表示、zoom blur、随机裁剪并缩放、弹性变换；
  - 具体增强概率和超参数在附录中，本地文本未提供。
- **单模态编码**：
  - 输入图像被切分为 flattened input sections，并转换为 token 序列；
  - 使用 Vision Transformer 编码器处理 token；
  - 文中提到常用 token 大小为 16 px；
  - 编码器变体包括：
    - ViT256：ViT-S，D=384，L=12；
    - SAM-B：ViT-B，D=768，L=12；
    - SAM-L：ViT-L，D=1024，L=24；
    - SAM-H：ViT-H，D=1280，L=32；
  - 训练初期先冻结编码器 25 个 epoch，之后训练包括编码器在内的整个模型。
- **跨模态融合**：
  - 无；
  - 本文仅使用 H&E 图像单模态；
  - 多层 skip connections 是同一图像模态内部的多尺度特征传递，不属于跨模态融合。
- **处理流程**：
  1. 输入图像块被分块为 token，并送入预训练 ViT 编码器；
  2. 编码器在多个深度层输出特征，通过 skip connections 传给专用上采样解码器；
  3. 解码器输出细胞核实例分割结果；
  4. 后处理得到每个细胞核的类别、bounding-box 坐标、边界多边形和质心；
  5. 对每个检测到的细胞核，从最后一个 Transformer block 中提取空间上对应的 token embedding；
  6. 如果一个细胞核对应多个 token，则对这些 token embedding 取平均；
  7. WSI 推理时，只处理和合并重叠区域的细胞核，并将结果导出为 JSON。
- **输出**：
  - 细胞核实例分割与分类结果；
  - 每个细胞核的类别；
  - bounding-box 坐标；
  - 形状多边形；
  - 质心位置；
  - 每个细胞核对应的嵌入向量 \(\hat{\mathbf{z}}^L_y \in \mathbb{R}^D\)。
- **模块在整体网络中的位置**：
  - CellViT 是论文唯一命名核心框架；
  - ViT 编码器负责图像特征提取；
  - 解码器负责实例分割预测；
  - token embedding 提取发生在编码器最后 Transformer block，并与检测到的细胞核空间位置关联。
- **与其他模块的连接方式**：
  - 编码器通过多层 skip connections 连接解码器；
  - 检测到的细胞核与编码器 token embedding 建立空间对应关系；
  - 提取的细胞核嵌入可作为下游深度学习任务的输入特征；
  - 具体解码器内部层结构、输出头细节和后处理算法参数在本地文本中未完整给出。

#### 3. 数学公式

本地文本可可靠恢复的关键公式如下。

1. 训练样本采样权重，原文 Eq. (10)：

\[
p_i(\gamma_s)=
\frac{w_{\text{Tissue}}(i,\gamma_s)}
{\max_{j\in[1,N_{\text{Train}}]} w_{\text{Tissue}}(j,\gamma_s)}
+
\frac{w_{\text{Cell}}(i,\gamma_s)}
{\max_{j\in[1,N_{\text{Train}}]} w_{\text{Cell}}(j,\gamma_s)}
\]

其中 \(p_i(\gamma_s)\) 是第 \(i\) 个训练图像块的采样权重，\(\gamma_s \in [0,1]\) 控制过采样强度。

2. 组织类别权重，原文 Eq. (11)：

\[
w_{\text{Tissue}}(i,\gamma_s)=
\frac{N_{\text{Train}}}
{\gamma_s
\left(
\sum_{j\in[1,N_{\text{Train}}]}
\mathbf{1}[c_{T,j}=c_{T,i}]
\right)
+
(1-\gamma_s)N_{\text{Train}}}
\]

其中 \(c_{T,i}\) 表示第 \(i\) 个图像块所属的组织类别。

3. Panoptic Quality，原文 Eq. (9)：

\[
PQ=
\underbrace{
\frac{|TP|}
{|TP|+\frac{1}{2}|FP|+\frac{1}{2}|FN|}
}_{\text{Detection Quality}}
\times
\underbrace{
\frac{
\sum_{(y,\hat{y})\in TP} IoU(y,\hat{y})
}
{|TP|}
}_{\text{Segmentation Quality}}
\]

其中 \(y\) 是 ground-truth segment，\(\hat{y}\) 是预测 segment，匹配条件为 \(IoU(y,\hat{y})>0.5\)。

4. 二值细胞核检测指标：

\[
F1_d=
\frac{2TP_d}
{2TP_d+FP_d+FN_d}
\]

\[
P_d=
\frac{TP_d}
{TP_d+FP_d}
\]

\[
R_d=
\frac{TP_d}
{TP_d+FN_d}
\]

以下公式本地文本不足以可靠恢复：

- 细胞类别权重 \(w_{\text{Cell}}(i,\gamma_s)\) 的完整公式在本地文本中排版断裂，无法可靠恢复；
- 损失函数被提及为 Eq. (5)，并提到 Focal Tversky loss，但本地正文未包含完整公式；
- 解码器具体输出公式、实例表示公式和后处理公式未在本地文本中完整给出。

#### 4. 输入输出维度

| 阶段 | 张量/变量 | 维度 | 说明 |
|---|---|---|---|
| 输入 | H&E 图像块 | 256×256 px 或 1024×1024 px；通道数未说明 | PanNuke 训练为 256×256 px；WSI 推理为 1024×1024 px |
| 输入 | 分辨率 | 0.25 μm/px 或 0.50 μm/px | 主实验为 0.25 μm/px；下采样实验为 0.50 μm/px |
| 中间表示 | ViT token 序列 | 若按 token 大小 16 px 计算：256×256 输入对应 256 个 token；1024×1024 输入对应 4096 个 token | 由文中 token 大小 16 px 与输入尺寸推得 |
| 中间表示 | token embedding | \(\mathbb{R}^D\) | ViT256：D=384；SAM-B：D=768；SAM-L：D=1024；SAM-H：D=1280 |
| 中间表示 | 最后一层细胞核相关 token embedding | \(\hat{\mathbf{z}}^L_y \in \mathbb{R}^D\) | 若一个细胞核对应多个 token，则取平均 |
| 输出 | 细胞核实例结果 | 未说明 | 包括类别、bounding-box、形状多边形、质心 |
| 输出 | 每个细胞核的嵌入向量 | \(\mathbb{R}^D\) | 用于下游任务 |

#### 5. 实现伪代码


```python

```

#### 6. 实现提示

- **关键网络组件**：
  - Vision Transformer 编码器；
  - U-Net 形状解码器；
  - 多深度层 skip connections；
  - 上采样解码路径；
  - 细胞核实例分割输出头；
  - 后处理模块，用于生成 bounding-box、polygon、center of mass；
  - token embedding 提取模块。
- **重要超参数**：
  - 训练 130 个 epoch；
  - 使用指数学习率调度，调度因子 0.85；
  - 过采样权重因子 \(\gamma_s=0.85\)；
  - 前 25 个 epoch 冻结编码器；
  - WSI 推理 patch size 为 1024×1024 px；
  - overlap 为 64 px；
  - ViT token 大小为 16 px；
  - 检测匹配半径：0.50 μm/px 下为 6 px，0.25 μm/px 下为 12 px；
  - optimizer、batch size、loss 权重等关键训练配置在附录中，本地文本未提供。
- **归一化/激活方式**：
  - 本地文本未说明。
- **维度对齐方式**：
  - 不同 ViT 编码器的 token embedding 维度不同，分别为 384、768、1024、1280；
  - 编码器多层特征通过 skip connections 传给解码器；
  - 具体投影、上采样、特征对齐方式未在本地文本中详细说明。
- **实现注意事项**：
  - WSI 全图分割结果难以完全保存在内存中，因此论文只处理和合并重叠区域的细胞核；
  - 缩放图像时需要注意插值方法；
  - 使用较小的 64 px overlap 可以降低后处理开销；
  - 若一个细胞核对应多个 token，需要平均这些 token embedding；
  - 实验使用 automatic mixed precision；
  - 结果可导出为 JSON，并兼容 QuPath 可视化。
- **依赖的特殊算子或第三方库**：
  - PyTorch 1.13.1；
  - Albumentations；
  - 官方 STARDIST 实现；
  - CPP-Net 实现；
  - CellSeg-models 实现；
  - SAM 官方 checkpoint；
  - ViT256 checkpoint；
  - SciPy 用于统计分析；
  - 是否依赖特殊算子在本地文本中未说明。

#### 7. 计算与资源开销

- **理论计算复杂度**：未说明。
- **参数量**：未说明。
- **FLOPs/MACs**：未说明。
- **显存开销**：
  - 实验在 80 GB NVIDIA A100 GPU 上进行；
  - 文中指出 48 GB NVIDIA RTX A6000 足以训练 ViT256 和 SAM-B 模型；
  - 具体显存数值未说明。
- **推理速度**：
  - 论文声称其推理流程比 HoVer-Net 快 1.85 倍；
  - 该结论来自对 10 张食管 WSI 的推理时间测量，每张 WSI 重复 3 次并取平均；
  - 具体运行时间数值在本地文本中未给出。
- **论文是否提供效率对比**：
  - 是；
  - 对比对象包括 HoVer-Net、CellViT256、CellViT-SAM-H；
  - 比较了 256 px 和 1024 px 输入 patch 的推理设置；
  - 但本地文本未包含完整效率数值表。

#### 8. 适用场景与可迁移性

- **原论文应用场景**：
  - H&E 染色组织图像中的细胞核实例分割；
  - 细胞核检测；
  - 细胞核分类；
  - WSI 级别细胞核分析；
  - 为下游深度学习任务提取细胞核嵌入。
- **可迁移到的任务/数据集**：
  - MoNuSeg：论文将 PanNuke 训练模型直接用于 MoNuSeg 测试集，未进行 finetuning；
  - CoNSeP：用于分析提取的细胞核嵌入；
  - 潜在下游任务包括疾病预测、治疗反应预测和生存预测，但这些下游任务在本地文本中只作为应用方向被提及，未给出完整实验。
- **迁移所需调整**：
  - 根据目标数据调整图像分辨率和 patch size；
  - 对非 1024×1024 输入需要缩放或重新切块；
  - 若目标数据集没有细胞核类别标签，则无法评估分类性能；
  - 若目标域与 PanNuke 差异较大，是否需要重新训练或微调，本地文本未充分说明。
- **适用条件**：
  - 适用于 H&E 染色组织图像；
  - 需要细胞核实例分割和分类；
  - 需要获得细胞核级别特征；
  - 需要具备足够 GPU 资源；
  - 需要可获得预训练 ViT 或 SAM 编码器。
- **潜在限制**：
  - dead cells 类别因类别不平衡和尺寸较小，性能较低；
  - 从 0.25 μm/px 下采样到 0.50 μm/px 会导致明显性能下降，尤其是 recall；
  - WSI 全图结果难以完整保存在内存中；
  - 大模型如 SAM-H 可能需要更高显存；
  - 本地文本缺少完整后处理与损失函数细节，可能影响复现。

#### 9. 实验与消融证据

- **主要性能结果**：
  - 摘要中报告，CellViT 在 PanNuke 上取得 mean panoptic quality 0.50 和 F1-detection score 0.83；
  - Table 1 中，CellViT-SAM-H + HoVer-Net decoder + CellViT hyperparameters 的二值检测结果为 \(P_d=0.84\)、\(R_d=0.81\)、\(F1_d=0.83\)；
  - Table 2 中，CellViT-SAM-H + HoVer-Net decoder 的平均 \(mPQ=0.4980\)、\(bPQ=0.6793\)；CellViT256 的平均 \(mPQ=0.4846\)、\(bPQ=0.6696\)。
- **相对基线的提升**：
  - 与随机初始化 CellViT-Random 相比，预训练 ViT256 和 SAM 编码器带来显著性能提升；
  - 与 HoVer-Net、Mask-RCNN、Micro-Net、DIST 等基线相比，CellViT 在检测指标上更强；
  - 作者特别提到，上皮类细胞核 \(F1_{Epi}\) 相对现有方法最高可提升 26%；
  - 推理速度方面，作者报告比 HoVer-Net 快 1.85 倍；
  - 需要注意：TSFD-Net 的结果基于 80/20 train-test split，而非 PanNuke 官方三折划分，因此不能与本文三折结果直接排名。
- **相关消融实验**：
  - 预训练编码器消融：比较 CellViT-Random、CellViT256、CellViT-SAM-B、CellViT-SAM-L、CellViT-SAM-H；
  - 正则化消融：比较 raw、oversampling only、augmentation only、无 Focal Tversky loss 等变体；
  - 解码器消融：比较 HoVer-Net decoder、STARDIST decoder、CPP-Net decoder；
  - 超参数消融：比较 CellViT hyperparameters 与 CPP-Net hyperparameters；
  - 分辨率消融：比较 0.25 μm/px 与 0.50 μm/px；
  - 推理设置消融：比较 1024×1024 px 单 patch 与 256×256 px 子 patch，以及 overlap 策略。
- **作者结论**：
  - 大规模 in-domain 和 out-of-domain 预训练 ViT 编码器是性能提升的关键；
  - 数据增强是关键正则化手段；
  - HoVer-Net decoder 在检测性能上优于 STARDIST 和 CPP-Net decoder；
  - CellViT-SAM-H + HoVer-Net decoder 是最佳平均模型；
  - 1024×1024 px 大 patch 推理可用于 WSI，并比 HoVer-Net 更快。
- **证据是否充分**：
  - 对预训练编码器、数据增强、解码器选择和推理效率，本地文本提供了表格或明确实验描述；
  - 但对损失函数、完整超参数、增强概率、后处理细节和具体推理时间数值，本地证据不足；
  - 因此，方法有效性的主要结论证据较充分，但完整复现细节证据不足。

#### 10. 方法评估

| 维度 | 评价 | 依据 |
|---|---|---|
| 创新性 | 中 | 核心思路是将预训练 ViT 用于细胞核实例分割，并同步提取细胞核嵌入；架构受 UNETR 和 HoVer-Net 影响，主要增益由预训练编码器和训练策略支持，而非全新结构。 |
| 技术可行性 | 高 | 代码公开，基于 PyTorch，使用已有 ViT、SAM、HoVer-Net/STARDIST/CPP-Net 相关实现，并在 PanNuke、MoNuSeg、CoNSeP 上进行实验。 |
| 实现难度 | 中 | 主体框架清晰，代码公开；但本地文本缺少解码器细节、后处理细节、损失公式和附录超参数，完整复现仍有一定工程量。 |
| 架构相关性 | 高 | 该方法是论文核心，所有检测、分割、分类、嵌入提取和 WSI 推理均围绕 CellViT 展开。 |
| 可迁移性 | 中 | 论文展示了在 MoNuSeg 上无需 finetuning 的泛化，并可在 CoNSeP 上提取嵌入；但应用仍主要限于 H&E 细胞核分割，且分辨率和数据格式需要适配。 |
| 计算成本 | 中 | 使用大型 ViT 编码器和 A100 GPU，训练成本不低；但推理流程比 HoVer-Net 更快，且较小模型可在 48 GB GPU 上训练。 |

#### 11. 一句话总结

CellViT 用大规模预训练 Vision Transformer 替换 U 形细胞核分割网络的编码器，在 H&E 病理图像中实现细胞核检测、实例分割、分类，并同步提取与细胞核空间位置对应的 token 嵌入。

## 四、论文级综合评价

### 1. 最值得借鉴的方法

- 使用大规模预训练 ViT 编码器替代 CNN 编码器，用于细胞核实例分割；
- 利用 ViT token 与细胞核空间位置的对应关系，在推理时直接提取细胞核嵌入；
- 采用 1024×1024 px 大 patch 和 64 px overlap 的 WSI 推理策略；
- 使用同时考虑组织类别和细胞类别的过采样策略；
- 使用强数据增强缓解细胞核形态、染色和纹理变化；
- 将检测结果导出为 JSON，并保留类别、bbox、polygon、center of mass 和嵌入向量，便于下游分析。

### 2. 方法之间的关系

论文只提出一个命名核心框架：CellViT。CellViT 内部包含以下关系：

- ViT 编码器负责提取 token 特征；
- 多层 encoder 特征通过 skip connections 输入解码器；
- 解码器生成细胞核实例分割结果；
- 后处理将分割结果转换为可分析的细胞核对象；
- token embedding 与检测到的细胞核空间位置绑定，形成细胞级特征；
- HoVer-Net、STARDIST、CPP-Net 在本文中主要作为解码器或对比变体出现，不应被拆成独立命名方法。

### 3. 复现可行性

- **代码是否公开**：是，代码公开于 https://github.com/TIO-IKIM/CellViT。
- **方法描述是否完整**：部分完整。本地正文给出了整体结构、编码器选择、训练策略、推理设置和主要实验，但缺少完整附录、损失函数公式、增强概率、后处理细节和部分效率数值。
- **关键配置是否明确**：部分明确。明确配置包括 130 epochs、学习率调度因子 0.85、\(\gamma_s=0.85\)、前 25 epochs 冻结编码器、1024×1024 推理 patch、64 px overlap、ViT/SAM 编码器维度与层数；未明确配置包括 optimizer、batch size、loss 权重、具体增强参数、解码器细节。
- **预计复现难点**：
  - 细胞核实例分割后处理，尤其是重叠细胞核合并；
  - HoVer-Net/STARDIST/CPP-Net decoder 的具体输出表示；
  - 大规模预训练权重的加载与冻结策略；
  - WSI 推理中的内存管理和 overlap 合并；
  - 附录超参数缺失导致的训练配置不一致。

### 4. 与当前研究方向的关系

- **可直接采用的设计**：
  - 使用预训练 ViT 作为病理图像细胞核分割编码器；
  - 在分割推理过程中同步提取 token-level 细胞核嵌入；
  - 使用大 patch WSI 推理和小 overlap 降低后处理负担；
  - 使用组织类别和细胞类别联合过采样缓解类别不平衡。
- **需要改造的设计**：
  - 若引入文本、基因组、临床表格或其他模态，需要额外设计真正的跨模态融合模块；
  - 若目标数据集不是 H&E 或不是细胞核任务，需要重新评估编码器预训练域；
  - 若需要更精细的细胞核边界或更复杂实例表示，需要改造解码器和后处理；
  - 若计算资源有限，需要用更小 ViT 或更低分辨率输入替代 SAM-H。
- **可能形成的新研究思路**：
  - 将细胞核 token embedding 作为下游生存预测、治疗反应预测或疾病分型的细胞级特征；
  - 将细胞核嵌入与空间图模型、组织区域图或多实例学习结合；
  - 研究不同预训练域对细胞核分割和嵌入质量的影响；
  - 在单模态细胞核嵌入基础上扩展为病理图像-文本或多模态病理基础模型。

### 5. 阅读备注

- 本地正文未包含完整方法页和附录，因此不能完整恢复所有网络细节；
- 论文中提到的 Eq. (5) 损失函数、增强概率、优化器细节和完整超参数表未在本地文本中出现；
- 本文不是多模态方法论文，其“特征提取”主要指从单模态图像编码器中提取细胞核 token embedding；
- 在比较 TSFD-Net 时，需要注意其使用不同数据划分，不能与 PanNuke 官方三折结果直接排名。
