# Stain normalization using score-based diffusion model through stain separation and overlapped moving window patch strategies 方法总结

> 证据说明：本总结基于已人工核验的 7 页 PDF 正文与附录，可用文本约 3.3 万字符，覆盖摘要、引言、背景、材料与方法、结果、讨论、结论及补充实现细节。本地证据较完整，但缺少代码仓库明确声明、学习率、SNMF 具体参数、H/E 成分重组回 RGB 的完整细节、显存/参数量/FLOPs、绝对推理时间，以及更系统的组件消融；相关位置将标注“未说明”或“本地证据不足”。

## 一、论文基本信息

- **论文标题**：Stain normalization using score-based diffusion model through stain separation and overlapped moving window patch strategies
- **作者**：Jeong, Jiheon；Kim, Ki Duk；Nam, Yujin；Cho, Cristina Eunbee；Go, Heounjeong；Kim, Namkug
- **发表年份**：2023
- **会议/期刊**：Computers in Biology and Medicine
- **论文链接/DOI/arXiv ID**：DOI: 10.1016/j.compbiomed.2022.106335；链接：https://doi.org/10.1016/j.compbiomed.2022.106335；arXiv ID：未说明
- **代码仓库**：未说明；正文脚注提及 ncsnpp2 相关参考仓库 https://github.com/yang-song/score_sde_pytorch，但未明确说明该论文是否公开作者代码
- **研究任务**：H&E 病理图像染色归一化 / stain normalization，尤其是全幻灯片图像 WSI 的 patch 级与整片归一化
- **数据模态**：单模态病理图像：H&E 染色 RGB 图像 / WSI patch；方法内部使用由 SNMF 分离得到的 hematoxylin 与 eosin 染色成分表示

## 二、论文整体概述

### 1. 核心问题

H&E 染色是病理诊断中的常用染色方式，但 hematoxylin 与 eosin 的剂量比例未标准化，且两种染色褪色速度不同，导致不同图像之间染色质量差异明显。染色归一化是数字病理深度学习模型的重要预处理步骤。传统方法通常需要参考 patch 或 slide，并可能造成组织结构或纹理破坏；基于深度学习的 patch 方法又容易出现网格伪影、过拟合等问题。作者进一步指出，直接使用 score-based diffusion model 进行颜色化归一化时，由于模型生成能力较强，可能出现颜色误转移，例如本应为红色的红细胞或嗜酸性粒细胞被生成为紫色。

### 2. 整体方法

论文提出一个基于 score-based diffusion model 的 H&E 染色归一化流程。核心做法包括三部分：第一，使用 sparse non-negative matrix factorization，即 Vahadane 方法中的 color deconvolution，将 H&E 图像分离为 hematoxylin 与 eosin 成分，以限制扩散模型的生成自由度；第二，分别训练两个 score-based diffusion model，用于生成归一化后的 hematoxylin 与 eosin 空间；第三，在 WSI 推理时使用 overlapped moving window patch 策略，通过重叠区域作为后续 patch 的颜色化种子，并交替使用 colorization 与 inpainting，以减少 patch 边界处的网格伪影。

### 3. 主要贡献

1. 作者声称提出了一种基于 score-based diffusion model 的高性能 H&E 染色归一化方法。
2. 作者声称采用临床合理的 SNMF 染色分离协议，将 H&E 图像分解为 hematoxylin 与 eosin，以减少扩散模型导致的颜色误转移。
3. 作者声称通过 overlapped moving window patch 策略克服 WSI 归一化中的网格伪影。

---

## 三、方法总结

### 方法 1：基于分数扩散模型、SNMF 染色分离与重叠移动窗口的 H&E 染色归一化

#### 1. 核心思想与解决的问题

- **目标问题**：在不同年份、不同机构或不同扫描仪下，对 H&E 病理图像进行染色归一化，使图像染色外观更一致，并在 WSI 级别减少 patch 拼接造成的网格伪影。
- **现有方法的局限**：
  - Macenko、Vahadane 等传统染色归一化方法需要参考 patch 或 slide。
  - 传统方法可能导致组织结构或纹理 collapse。
  - 基于深度学习的 patch 方法在 WSI 归一化中容易出现边界网格伪影。
  - 直接使用 score-based diffusion model 进行颜色化时，因生成多样性较高，可能出现 hematoxylin 与 eosin 颜色混淆。
- **核心思想**：不直接让扩散模型从灰度图自由生成完整 H&E 颜色，而是先用 SNMF 将图像分解为 hematoxylin 与 eosin 成分，再分别用扩散模型进行受控生成；在 WSI 推理时，用重叠移动窗口将已归一化区域作为后续 patch 的条件信息，从而提升连续性。
- **创新点**：
  - 作者声称的创新：将 score-based diffusion model 用于染色归一化。
  - 作者声称的创新：使用 SNMF 染色分离约束扩散模型，避免颜色误转移。
  - 作者声称的创新：使用 overlapped moving window patch 策略减少 WSI patch 级归一化中的网格伪影。
  - 由本地证据实际支持的点：图 1 支持“无染色分离时存在误转移”的问题；图 4 与表 2 支持“重叠窗口可减少网格伪影并影响时间成本”；表 1 提供了与 Pix2PixHD、Macenko、Vahadane 的对比结果。

#### 2. 详细结构与数据流

- **输入**：
  - 训练输入：来自 Asan Medical Center 2019 年结肠 H&E WSI 的 patch，正文明确 patch 尺寸为 256 × 256。
  - 测试输入：2009、2012、2015 年的内部 WSI，以及 CAMELYON16 与 PAIP2019 外部 WSI。
  - 重叠实验中使用 2015 年 WSI 的 512 × 512 patch。
- **数据预处理**：
  - 从每张 WSI 中提取 100,000 个 256 × 256 patch；该描述出现在训练数据部分。
  - 在不使用染色分离的 naive 版本中，通过平均 RGB 通道将 patch 转为灰度图。
  - 在主方法中，使用 SNMF / color deconvolution 将 H&E 图像分离为 hematoxylin 与 eosin 成分。
  - 本地文本未说明是否对不同扫描仪或不同分辨率图像进行统一 resize、强度标准化或其他预处理。
- **单模态编码**：
  - 未说明独立的模态编码器。
  - 方法使用 ncsnpp2 架构的 score network，在 VESDE 框架下估计扰动数据的分数函数。
  - 该 score network 本质上是图像生成模型中的噪声图像分数估计器，而非传统意义上的分类或特征编码器。
- **跨模态融合**：
  - 本论文不属于多模态学习方法。
  - 没有明确的跨模态融合模块。
  - 条件信息通过 controllable generation 中的颜色通道解耦/耦合、掩膜和重叠区域注入实现；这更接近条件图像生成或图像修复，而非跨模态融合。
- **处理流程**：
  1. 对源 H&E 图像使用 SNMF / color deconvolution 分离出 hematoxylin 与 eosin 成分。
  2. 对 hematoxylin 与 eosin 分别使用训练好的 score-based diffusion model，通过 predictor-corrector 采样进行受控颜色化或归一化。
  3. 对 WSI 使用 overlapped moving window patch：先归一化起始 patch；窗口按预设重叠比例移动；已归一化的重叠区域作为后续 patch 的种子；通过交替 colorization 与 inpainting 归一化非重叠区域，最终得到 WSI 级归一化结果。
- **输出**：
  - 归一化后的病理图像或 WSI。
  - 本地文本未明确说明 hematoxylin 与 eosin 成分如何重新合并为最终 RGB 图像的具体实现细节。
- **模块在整体网络中的位置**：
  - 该方法位于数字病理深度学习模型的预处理阶段。
  - 也可作为独立的 WSI 染色归一化工具。
- **与其他模块的连接方式**：
  - 上游连接原始 H&E WSI 或 patch。
  - 内部连接 SNMF 染色分离模块、两个 score-based diffusion model、重叠移动窗口推理模块。
  - 下游可连接病理分割、分类或其他诊断模型；但本地正文未给出具体下游任务实验细节。

#### 3. 数学公式

以下公式均来自本地正文或附录，可可靠恢复。

前向 SDE：

\[
d\mathbf{x} = \mathbf{f}(\mathbf{x},t)dt + g(t)d\mathbf{w}
\]

反向 SDE：

\[
d\mathbf{x} = [\mathbf{f}(\mathbf{x},t) - g(t)^2 \nabla_x \log p_t(x)]dt + g(t)d\bar{\mathbf{w}}
\]

Score network 训练目标：

\[
\mathcal{E} = \arg\min_{\theta} \int_0^T \lambda(t)
\mathbb{E}_{x(0)} \mathbb{E}_{x(t)|x(0)}
\left\|
S_{\theta}(x(t),t) - \nabla_x \log p_t(x(t)|x(0))
\right\|_2^2 dt
\]

VESDE 扰动核，原文写作：

\[
p(x_t|x_0) = \mathcal{N}(x_t; x_0, \sigma_t)
\]

原文说明在 VESDE 示例中漂移系数为 0，扩散系数与 \(\sqrt{d[\sigma_t^2]/dt}\) 相关，并设置 \(\lambda(t)=\sigma(t)^2\)。

噪声调度：

\[
\sigma(t) = \sigma_{\min}
\left(
\frac{\sigma_{\max}}{\sigma_{\min}}
\right)^t,
\quad t \in [0,1]
\]

正文附录给出 \(\sigma_{\min}=0.01\)，\(\sigma_{\max}=243\)。

Predictor 更新，来自 Algorithm 2：

\[
x_i \leftarrow x_{i+1}
+ (\sigma_{i+1}^2 - \sigma_i^2)s_{\theta}^{*}(x_{i+1},\sigma_i)
+ \sqrt{\sigma_{i+1}^2 - \sigma_i^2}\,z
\]

Corrector 更新，来自 Algorithm 2：

\[
x_i \leftarrow x_i
+ \epsilon_i s_{\theta}^{*}(x_i,\sigma_i)
+ \sqrt{2\epsilon_i}\,z
\]

Colorization 中的通道解耦与耦合，原文给出：

\[
\text{couple} =
\text{einsum}(bc_1hw,c_1c_2 \to bc_2hw,\ \text{image},\ M^{-1})
\]

\[
\text{decouple} =
\text{einsum}(bc_1hw,c_1c_2 \to bc_2hw,\ \text{image},\ M)
\]

正交矩阵 \(M\) 为：

\[
M =
\begin{pmatrix}
0.577 & -0.816 & 0 \\
0.577 & 0.408 & 0.707 \\
0.577 & 0.408 & -0.707
\end{pmatrix}
\]

Colorization 中的条件注入步骤，来自 Algorithm 1：

\[
x_i \leftarrow
\text{couple}
\left(
\text{decouple}(x_i,M)\odot(1-\Omega_p)
+
(\text{decouple}(g,M)+\sigma_i z)\odot\Omega_p,
M
\right)
\]

Inpainting 中的条件注入步骤，来自 Algorithm 3：

\[
x_i \leftarrow x_i \odot (1-\Omega) + (y + \sigma_i z)\odot\Omega
\]

Pearson correlation coefficient：

\[
PCC(S,P) =
\frac{
\sum_i (S_i-\mu_S)(P_i-\mu_P)
}{
\sqrt{\sum_i (S_i-\mu_S)^2}
\sqrt{\sum_i (P_i-\mu_P)^2}
}
\]

其中 \(S\) 为源 WSI，\(P\) 为处理后 WSI，\(\mu_S\) 与 \(\mu_P\) 分别为源图像和处理后图像的均值。

#### 4. 输入输出维度

| 阶段 | 张量/变量 | 维度 | 说明 |
|---|---|---|---|
| 输入 | H&E 训练 patch | 256 × 256 × 3 | 正文明确训练 patch 尺寸为 256 × 256，并涉及 RGB 通道 |
| 输入 | WSI | 未说明 | 全幻灯片图像尺寸可变，本地文本未给出统一尺寸 |
| 中间表示 | 灰度图 | 未说明 | 由 RGB 通道平均得到，用于无染色分离的 naive 版本 |
| 中间表示 | Hematoxylin / Eosin 成分 | 未说明 | 由 SNMF / color deconvolution 得到，本地文本未明确每个成分的具体张量维度 |
| 中间表示 | 正交矩阵 \(M\) | 3 × 3 | 用于颜色通道解耦与耦合 |
| 中间表示 | 掩膜 \(\Omega_p\) 或 \(\Omega\) | 未说明 | 用于 colorization 或 inpainting 的条件区域，本地文本未给出具体维度 |
| 输出 | 归一化 patch / WSI | 未说明 | 本地文本未明确最终输出通道数或重组细节，仅说明得到归一化图像或 WSI |

#### 5. 实现伪代码


```python

```

#### 6. 实现提示

- **关键网络组件**：
  - ncsnpp2 score network。
  - VESDE 扰动过程。
  - Predictor-corrector sampler。
  - Reverse-diffusion predictor。
  - Langevin dynamic corrector。
  - SNMF / color deconvolution 染色分离。
  - Controllable generation 中的 colorization 与 inpainting。
  - 用于 WSI 推理的 overlapped moving window patch 策略。
- **重要超参数**：
  - 训练迭代次数：300,000。
  - 优化器：Adam。
  - batch size：64。
  - \(\sigma_{\min}=0.01\)。
  - \(\sigma_{\max}=243\)。
  - 采样步数 \(N=350\)。
  - 正文附录写作 \(M=1\)，但未说明其与 Algorithm 1 中 corrector stop \(C\) 的对应关系。
  - \(\epsilon_i = 2\gamma \frac{\|z\|_2}{\|s_{\theta}(x_i,\sigma_i)\|_2}\)，其中 \(\gamma=0.2\)。
  - 主实验重叠比例 \(\gamma_{ratio}=0.05\)。
  - 重叠比例消融：0、0.05、0.25、0.50、0.75。
  - 训练 patch 尺寸：256 × 256。
  - 每张训练 WSI 提取 100,000 个 patch。
- **归一化/激活方式**：未说明。
- **维度对齐方式**：
  - 使用正交矩阵 \(M\) 对颜色通道进行 decouple 与 couple。
  - 使用 mask \(\Omega_p\) 或 \(\Omega\) 将已知条件区域注入生成过程。
  - 重叠窗口中，已归一化区域作为后续 patch 的条件种子。
- **实现注意事项**：
  - 需要训练两个 score-based diffusion model，分别对应 hematoxylin 与 eosin。
  - 染色归一化性能可能依赖 SNMF 染色分离性能。
  - 初始 patch 的位置可能影响 WSI 归一化结果，因为初始 patch 在重叠窗口中充当颜色化种子。
  - 本地文本未说明 H/E 成分如何重组回最终 RGB 图像。
  - 本地文本未说明不同扫描仪或分辨率之间的统一处理策略。
- **依赖的特殊算子或第三方库**：
  - PyTorch。
  - einsum。
  - score_sde_pytorch 被正文脚注提及为 ncsnpp2 相关参考实现。
  - SNMF / color deconvolution 的具体实现库未说明。

#### 7. 计算与资源开销

- **理论计算复杂度**：未说明。
- **参数量**：未说明。
- **FLOPs/MACs**：未说明。
- **显存开销**：未说明。
- **推理速度**：未提供绝对推理时间；论文提供了不同重叠比例下的相对时间成本。
- **论文是否提供效率对比**：
  - 提供了重叠比例之间的相对时间成本对比。
  - 表 2 中，以 \(\gamma_{ratio}=0.75\) 为 100%，则 \(\gamma_{ratio}=0.50\) 为 30.9%，\(\gamma_{ratio}=0.25\) 为 19.8%，\(\gamma_{ratio}=0.05\) 为 11.1%，non-overlapping 为 10.1%。
  - 未提供与 Macenko、Vahadane 或 Pix2PixHD 的推理速度对比。

#### 8. 适用场景与可迁移性

- **原论文应用场景**：
  - H&E 染色病理图像归一化。
  - 长期或多中心数字病理研究中的染色质量统一。
  - WSI 级染色归一化。
  - 内部数据为结肠 H&E WSI；外部验证包括 CAMELYON16 与 PAIP2019。
- **可迁移到的任务/数据集**：
  - 本地证据支持其在不同年份、不同外部数据集上的 H&E WSI 归一化应用。
  - 是否适用于其他器官、其他染色协议或其他扫描仪，本地证据不足。
- **迁移所需调整**：
  - 可能需要重新训练 score-based diffusion model。
  - 可能需要调整 SNMF 染色分离参数。
  - 可能需要调整 patch 尺寸与重叠比例。
  - 本地文本未提供系统化迁移配置。
- **适用条件**：
  - 输入为 H&E 或可被合理分离为有限染色成分的病理图像。
  - 需要无参考染色归一化时，该方法不要求参考 patch 或 slide。
  - 需要能够承担扩散模型训练与采样开销。
- **潜在限制**：
  - 染色归一化性能可能依赖 SNMF 分离性能。
  - 初始 patch 位置可能影响 WSI 结果。
  - 作者指出目前缺少染色归一化的金标准定量指标。
  - 本地文本未说明更多中心、更多时间线或更多扫描仪的广泛验证。

#### 9. 实验与消融证据

- **主要性能结果**：
  - 论文在 2009、2012、2015 年内部数据以及 PAIP2019、CAMELYON16 外部数据上评估 UQI、ERGAS、MS-SSIM、PSNR、RMSE 和 PCC。
  - 作者称本方法在多数指标上优于 Vahadane 和 Macenko。
  - 本地表 1 显示不同年份和数据集上各方法指标互有高低，例如 2009 年 Macenko 在 UQI、ERGAS、PSNR、RMSE 上高于或优于本方法，但本方法 PCC 更高。
- **相对基线的提升**：
  - 与 Pix2PixHD 相比，作者指出 Pix2PixHD 出现网格伪影，而本方法未观察到网格伪影。
  - 与 Macenko、Vahadane 相比，作者认为传统方法在不同协议图像上可能过拟合本机构图像，外部验证表现较差。
  - 本地证据不支持跨论文或跨数据划分下的绝对性能排名，只能依据本文报告的同一实验设置进行描述。
- **相关消融实验**：
  - 无染色分离版本：图 1 显示红细胞或嗜酸性粒细胞等本应红色区域被误生成为紫色，用于说明染色分离的必要性。
  - 重叠比例消融：表 2 与图 4 比较 \(\gamma_{ratio}=0\)、0.05、0.25、0.50、0.75，说明 non-overlapping 会出现颜色不一致或网格伪影，重叠后可减少网格伪影。
  - 未提供更完整的组件消融，例如不同 SNMF 方案、不同扩散采样步数、单模型与双模型对比、不同网络架构对比等。
- **作者结论**：
  - 该方法可实现高性能染色归一化。
  - 染色分离可避免扩散模型颜色误转移。
  - 重叠移动窗口可减少 WSI 归一化中的网格伪影。
  - 方法在未见外部数据集上表现稳健。
- **证据是否充分**：
  - 对“无染色分离会导致误转移”有定性证据。
  - 对“重叠窗口减少网格伪影”有定性和定量证据。
  - 对整体性能有与多个基线的表格比较。
  - 但对核心组件的系统消融、计算资源、最终 RGB 重组细节和代码可复现性证据不足。

#### 10. 方法评估

| 维度 | 评价 | 依据 |
|---|---|---|
| 创新性 | 中 | 方法基于已有 score-based diffusion / ncsnpp2 框架，主要新意在于用 SNMF 染色分离约束生成，并用重叠移动窗口处理 WSI 伪影。 |
| 技术可行性 | 中 | 论文提供了算法流程、部分超参数和实验结果，但扩散采样步数较多、需要两个模型，且缺少显存、速度和完整工程细节。 |
| 实现难度 | 高 | 需要整合 SNMF、score-based diffusion、predictor-corrector 采样、colorization/inpainting 和 WSI 重叠窗口推理。 |
| 架构相关性 | 高 | 方法直接面向 H&E 染色归一化和 WSI 级伪影问题，与数字病理预处理高度相关。 |
| 可迁移性 | 中 | 外部数据集验证支持一定泛化性，但迁移到新数据仍需重训模型并调整染色分离、patch 和重叠策略。 |
| 计算成本 | 高 | 使用 350 步采样、两个扩散模型和重叠窗口；论文提供相对时间成本但未提供显存或绝对速度，整体开销可能较高。 |

#### 11. 一句话总结

该论文提出用 SNMF 分离 hematoxylin 与 eosin，并结合重叠移动窗口条件下的 score-based diffusion colorization/inpainting，以实现无参考、少网格伪影的 H&E 病理 WSI 染色归一化。

## 四、论文级综合评价

### 1. 最值得借鉴的方法

最值得借鉴的是将染色分离作为扩散模型的条件约束，而不是让模型直接从灰度图自由生成 H&E 颜色。这种设计限制了生成模型的自由度，减少临床上有意义的颜色误转移。其次，重叠移动窗口策略将已归一化区域作为后续 patch 的种子，对 patch 级生成模型处理 WSI 时的边界不一致问题具有参考价值。

### 2. 方法之间的关系

本论文只有一个命名核心框架：基于 score-based diffusion model、通过 stain separation 和 overlapped moving window patch 策略进行染色归一化。SNMF 是前处理与条件约束模块，两个 score-based diffusion model 是生成模块，重叠移动窗口是 WSI 推理与拼接策略。三者共同组成一个染色归一化管线，而不是彼此独立的方法体系。

### 3. 复现可行性

- **代码是否公开**：未说明；正文仅提及 ncsnpp2 相关参考仓库，未明确作者代码是否公开。
- **方法描述是否完整**：较完整，包含 VESDE、PC sampler、colorization、inpainting、正交矩阵、部分训练超参数和重叠策略；但缺少 SNMF 具体参数、H/E 重组回 RGB 的细节、数据预处理细节和计算资源信息。
- **关键配置是否明确**：部分明确，包括训练迭代次数、batch size、Adam、\(\sigma_{\min}\)、\(\sigma_{\max}\)、采样步数、重叠比例等；未说明学习率、SNMF 参数、图像分辨率统一策略和最终输出重组方式。
- **预计复现难点**：
  - 扩散模型训练与采样成本较高。
  - 需要稳定实现 SNMF / color deconvolution。
  - 需要处理 WSI 级重叠窗口、掩膜注入和结果拼接。
  - 初始 patch 位置可能影响结果，需要设计稳定的初始化策略。
  - 缺少作者代码时会增加工程复现难度。

### 4. 与当前研究方向的关系

- **可直接采用的设计**：
  - 使用染色分离约束颜色生成，避免病理上有意义的颜色误转移。
  - 使用重叠窗口作为条件种子，减少 patch 级生成模型在 WSI 上的边界伪影。
  - 使用无参考染色归一化思路，减少对固定参考图像的依赖。
- **需要改造的设计**：
  - 可考虑更高效的扩散采样器，降低推理成本。
  - 可补充 H/E 成分重组回 RGB 的明确可复现流程。
  - 可扩展到更多染色类型、更多扫描仪和更多中心数据。
  - 可加入下游诊断任务评估，而不仅是图像质量指标。
- **可能形成的新研究思路**：
  - 将染色分离与条件扩散结合，用于病理图像质量控制或跨中心标准化。
  - 将重叠窗口条件生成推广到大规模 WSI 的其他图像翻译任务。
  - 研究扩散模型在病理染色归一化中的不确定性与可审计性。

### 5. 阅读备注

本文不是多模态学习方法，不应将其强行解释为跨模态融合。其核心是单模态病理图像生成与染色归一化，条件信息来自灰度图、染色分离成分、掩膜和重叠区域。论文的主要证据集中在图像质量指标和定性可视化，未提供下游病理诊断任务提升的直接证据；同时，作者也指出染色归一化尚缺乏金标准定量指标。
