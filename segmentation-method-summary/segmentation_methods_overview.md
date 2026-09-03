# 计算病理图像分割方法综述

## 研究范围与证据边界

本综述围绕“病理图像分割”方法库中的 38 篇结构化逐篇总结展开，重点梳理方法谱系、创新机制与适用场景，而不是对单篇论文进行孤立摘要。覆盖对象包括组织病理与细胞病理图像中的细胞核、全细胞、腺体、肾小球、肾皮质组织结构、肺肿瘤区域、乳腺管状结构、宫颈细胞核等；任务类型包括语义分割、实例分割、检测/中心定位、联合分类、交互式分割、弱监督分割、多任务分割以及基础模型式提示分割。

本综述严格只依据输入的结构化总结写作，不补充未在输入中出现的实验数字、数据集、结论或临床证据。输入材料中多篇论文存在证据边界，例如缺少代码仓库、参数量、FLOPs、显存、推理速度、完整消融、部分公式、外部验证或统计检验细节；因此本文在相关位置保留“论文报告”“作者称”“本地证据不足”“未说明”等不确定性表述。

需要特别强调的是：不同论文的数据集、训练/验证/测试划分、预处理、染色类型、放大倍率、评价指标和训练策略差异很大，本文不进行跨论文绝对性能排名。若某篇论文报告了优于基线的结果，也仅表示在该论文自身设置内的比较，不能直接外推为跨论文、跨数据集或跨任务的性能结论。对于 MoNuSeg、CoNIC 一类论文，其主要贡献是数据集、挑战赛或基准体系，不能把它们写成核心模型创新。

## 技术演进与分类框架

从输入材料看，病理图像分割方法大致沿五条线索演进。

第一，早期核/腺体实例分割与边界建模。该类方法关注细胞核或腺体对象的轮廓、中心、边界与实例分离，常见机制包括概率图、形状先验、轮廓分支、分隔结构预测、区域生长与后处理。代表工作包括基于深度 CNN 概率图与形状模型的核分割、轮廓感知网络、多通道腺体实例分割等。

第二，多尺度、多分辨率与结构保持。随着对象尺寸、组织结构和染色差异增大，方法开始强调多分辨率输入、空洞卷积、特征聚合、结构保持与器官特异性结构分割。该类不仅包括细胞/腺体分割，也包括肾小球、肾皮质结构、乳腺管状结构等组织学结构分割。

第三，联合核分割—分类与多任务建模。许多任务并不只要求“分出对象”，还要求判断对象类型或同步预测组织结构。该类方法通常将分割、边界、距离图、类型分类、组织类型分类或腔体/腺体预测纳入同一网络或统一训练框架。

第四，弱监督、低标注与挑战基准。为了降低像素级或实例级标注成本，出现了部分点标注、交互式点击/涂鸦提示、多模型伪标签富集与人工修正等策略。同时，MoNuSeg、ACDC@LungHP、CoNIC 等挑战赛或基准论文提供了数据、评价协议与趋势总结，其贡献主要是基准体系而非单一模型。

第五，空间注意力、特征金字塔与近期模型。近期方法更多引入注意力机制、特征金字塔、双解码器、Transformer、SAM 式提示分割、扩散模型、基础模型与多任务路由机制。该类方法通常面向更强的泛化、更细的边界、更丰富的细胞/组织表征，但也伴随更高计算资源需求或更多实现细节不确定性。

## 逐方法创新点

以下按五个类别归纳 38 篇文献的方法创新点。每条均显式标注 PMID，并保留输入证据中的不确定性。

**1. 早期核/腺体实例分割与边界建模**

- **PMID 26415167**：提出基于深度 CNN 概率图、迭代区域合并、选择式稀疏形状字典与局部排斥可变形模型的细胞核分割框架。其创新点在于将学习式中心检测与形状先验结合，用于保持单个细胞核轮廓；适用于需要后续形态学特征计算的核分割任务，但本地证据显示部分关键参数与消融不完整，且 Matlab 实现扩展性有限。

- **PMID 26863654**：提出 SC-CNN 用于细胞核中心检测，并用 Softmax CNN 与 NEP 邻域集成进行分类。其核心不是精确轮廓分割，而是以核中心检测为枢纽的检测—分类流程；适用于结肠 H&E 图像中的核检测与类型判断，但固定 patch 尺度、检测与分类分离，迁移时需重新训练与调整参数。

- **PMID 27898306**：DCAN 提出轮廓感知的多任务全卷积网络，同时预测对象概率图和轮廓概率图，用轮廓信息分离接触或聚集实例，并引入辅助监督与自然图像预训练。适用于腺体和细胞核实例分割，但输入证据指出严重退化恶性结构可能产生不准确内部轮廓。

- **PMID 28287963**：该论文的重要贡献是发布多器官细胞核边界数据集并提出 AJI 指标；方法上提出三分类 CNN，将细胞核边界作为独立像素类，并结合各向异性区域生长。适用于拥挤细胞核分割，但应同时将其视为数据集/评价基准贡献，而非单纯模型创新。

- **PMID 28358671**：提出深度多通道神经网络，将前景分割、边缘检测和目标检测三个通道并行提取区域、边界与位置线索，再通过融合网络输出腺体实例。创新点包括空洞卷积、旋转不变性增强和多线索融合；适合腺体实例分割，但依赖多个大网络，计算成本较高。

- **PMID 29018612**：提出 Object-Net 与 Separator-Net 双 CNN，分别预测腺体/背景类别与腺体间分隔结构，再用加权全变分正则化得到分割结果。其创新在于将分隔结构建模用于相邻腺体分离，并借四分类输出附带良恶性组织分类；本地证据对全变分模块独立贡献与部分数值不完整。

**2. 多尺度、多分辨率与结构保持**

- **PMID 28154470**：使用 DCNN 从子图学习特征，用于上皮/基质区域分类或分割，并比较超像素与滑动窗口生成子图的方式。该方法属于区域语义分割/分类，而非实例级分割；本地证据存在部分参数缺失与样本数不一致。

- **PMID 30580111**：Micro-Net 提出统一显微镜图像分割框架，通过多分辨率输入和绕过最大池化的额外卷积层保留弱特征。其创新在于同一架构适配细胞、细胞核和腺体等对象；论文报告了噪声鲁棒性，但边界处对象上下文不足可能影响分割。

- **PMID 30594772**：MILD-Net 提出最小信息损失单元、空洞残差单元和 ASPP，以减少下采样信息损失并处理多尺度腺体；测试时随机变换采样提供预测均值与不确定性图。扩展版 MILD-Net+ 可同步分割腺体与管腔；适合精细腺体边界建模，但推理效率较低。

- **PMID 31317118**：使用迁移学习微调 Inception v3 对肾小球进行分类，再通过分类热力图结合 Otsu、距离变换和分水岭完成全局硬化肾小球分割。创新点在于深度学习分类热力图与传统图像处理流水线结合；适用于三色染色肾小球定位，但分割敏感性有限且依赖经验阈值。

- **PMID 32835732**：在多染色肾脏皮质组织结构分割中系统评估 U-Net、染色类型、数字放大倍数和训练标注数量的影响，并公开数据、代码与教程。其贡献在于多染色、多结构、多放大倍数的肾脏组织学分割评估框架；但未验证异常病理结构。

- **PMID 33154175**：面向实验性肾脏病理构建修改版 Full CNN，用于 PAS 染色肾脏组织多类分割，并引入 tubular border 类以增强边界实例分离。其创新包括大规模标注流程、多物种/多疾病模型验证和定量组织学特征提取；但动脉和动脉腔性能相对较低，部分补充细节不足。

- **PMID 36599960**：构建乳腺癌 WSI tubule 分割数据集，并提出 Tubule-U-Net 框架，使用 reflection padding 缓解 patch 边界处不完整 tubule 结构，同时采用非对称 encoder-decoder。适合乳腺管状结构语义分割，但外部验证不足。

- **PMID 36007483**：DS-FNet 将修改后的 U-Net 语义分割流与边界检测流融合，用于肾小球分割，并面向单一 PAS 训练、多染色测试的一对多染色泛化。创新点包括注意力感知语义边界融合与新数据集；论文报告跨染色泛化，但跨染色性能仍低于同染色结果。

**3. 联合核分割—分类与多任务建模**

- **PMID 31561183**：HoVer-Net 通过预测细胞核像素到质心的水平和垂直距离图编码实例信息，并设置独立分类分支进行核类型分类。其创新在于距离图驱动的实例分离与分割—分类联合建模，同时推广 Panoptic Quality 评估并发布 CoNSeP 数据集；但质心难以定义的对象可能失效。

- **PMID 35367734**：TSFD-Net 提出组织特异特征蒸馏骨干、跨尺度加权特征融合和互联解码器，将组织类型信息引入细胞核分割与分类。适合具有组织类型辅助监督的 PanNuke 式任务，但依赖组织标签、颜色反卷积和后处理。

- **PMID 36410209**：Cerberus 提出共享编码器和多任务解码器，可同时预测细胞核、腺体、腔体和组织类型，并通过任务采样器与动态权重冻结机制整合多任务数据。适合结直肠 H&E 多结构同步分析，但强依赖任务对齐与大规模标注。

- **PMID 38507894**：CellViT 使用 Vision Transformer 或 SAM 预训练编码器与 U-Net 形状解码器，支持细胞核实例分割、分类和 token embedding 提取。其创新包括 WSI 推理流程和细胞核嵌入提取；适合大规模细胞核表征，但大模型资源需求较高，且死细胞类别性能有限。

- **PMID 39773093**：HistoNeXt 提出 ConvNeXt 编码器与双机制特征金字塔解码器，分割分支使用密集连接，分类分支使用通道注意力，并设计形态保持增强与类别感知采样。其创新在于分割/分类异构特征融合与多尺度模型变体；适合核分割与分类，但非 H&E 染色适应性未验证。

**4. 弱监督、低标注与挑战基准**

- **PMID 31647422**：MoNuSeg 论文主要是多器官细胞核分割数据集、挑战赛与基准总结，系统提炼颜色归一化、重度增强、距离/向量场预测和分水岭后处理等趋势。该论文的主要贡献是数据集、挑战赛或基准体系，不能写成单一核心模型创新。

- **PMID 32746112**：提出基于部分点标注的弱监督细胞核分割框架，包含半监督检测、背景传播自训练、Voronoi 与聚类伪标签以及 Dense CRF 损失。其创新在于以极少点标注逼近全监督性能；适合降低标注成本，但依赖检测点准确性与目标近似凸形。

- **PMID 32769053**：NuClick 提出交互式分割框架，细胞核/细胞可用单点击提示，腺体可用涂鸦提示，并将提示转换为辅助输入图。其创新在于最少交互信号下的多尺度对象分割与标注加速；但不是完全自动，且依赖用户提示质量。

- **PMID 33216724**：ACDC@LungHP 论文主要是肺癌 WSI 癌区分割挑战赛与数据集基准，总结 Top-10 深度学习方法、标签噪声处理、多模型与单模型差异等。其贡献主要是挑战赛与评价协议，不应视为单一核心模型创新。

- **PMID 38157647**：CoNIC 论文主要贡献是建立细胞核检测、分割、分类、计数及下游分析的挑战赛与基准体系，并进行大规模赛后分析。它不是单一核心模型创新，而是推动细胞核识别算法评价与下游临床关联分析的基准工作。

- **PMID 41286516**：建立肾脏病理细胞核分割评估基准，并提出 human-in-the-loop 多模型数据富集策略：用多个基础模型预测结果筛选 easy 伪标签与 hard 专家修正样本，再微调 Cellpose、StarDist、CellViT。适合降低像素级标注成本，但评级粒度较粗，且依赖基础模型预测质量。

- **PMID 42581240**：建立受控基准，在统一预处理、切片、损失、优化和评价指标下比较 CNN、Transformer 与混合架构的核分割性能、迁移学习收益、鲁棒性和效率。其主要贡献是统一评估协议，而不是提出新分割模型。

**5. 空间注意力、特征金字塔与近期模型**

- **PMID 32712523**：Triple U-net 引入 RGB 分支、Hematoxylin 分支和分割融合分支，并提出 PDFA 渐进密集特征聚合。其创新在于利用 H&E 中 Hematoxylin 对细胞核的光学先验进行边界监督；作者称无需颜色归一化，但模型对 attached nuclei 的分离能力有限，且强依赖 H&E 先验。

- **PMID 32903361**：提出将颜色归一化、Mask R-CNN 与多重推理后处理组合的细胞核分割流程，并用 U-Net 改进 DCGMM 颜色归一化。其创新在于流程化整合染色校正与测试时增强；适合 H&E 核实例分割，但本地缺少数值表，颜色归一化收益依数据集而异。

- **PMID 33190012**：NucleiSegNet 提出 robust residual block、bottleneck block 与 attention decoder block，并结合 Dice 与 Jaccard 联合损失。其面向肝癌核分割，强调形状变异与接触核处理；但模块级消融不足，且方法更偏语义/像素级核分割，不直接等同于实例分割。

- **PMID 36438040**：提出双解码器 U-Net，一个解码器预测前景掩码，另一个预测距离图，再经高斯平滑与标记控制分水岭生成实例；另有独立 U-Net 分类模型。其创新在于单编码器下共享特征并联合掩码/距离预测；适合 H&E 核实例分割，但测试时增强与集成增加计算成本。

- **PMID 37305563**：DCSA-Net 在 U-Net 中加入并行卷积块、密集卷积空间注意力模块和通道注意力块，以增强局部相关特征并抑制无关细节。其还发布小规模前列腺癌核分割数据集；适合语义核分割，但输入证据提到对严重重叠核与极大核存在局限。

- **PMID 37778210**：提出实例感知扩散模型用于腺体实例分割，使用图像编码器、扩散解码器、条件编码和 mask 分支。作者称这是首个将扩散模型用于腺体实例分割的方法，该“首个”判断需保留为作者陈述；多步扩散推理较慢，且小目标框可能受限。

- **PMID 37788295**：C-UNet 面向宫颈细胞核分割，提出 CSFI 跨尺度特征整合、WCU 宽上下文单元和互连解码器，同时优化分割与边界特征。适合复杂宫颈涂片图像，但本地证据中多数表格数值与公式不完整。

- **PMID 38292472**：围绕 DDU-Net 提出训练期非确定性染色归一化和测试期确定性染色归一化，并结合形态学测试时增强与模型集成。其创新在于染色归一化策略与推理增强流程，用于提升跨数据集核实例分割泛化；但推理时间增加，且仅在单一基线模型上验证。

- **PMID 38781811**：Cyto R-CNN 基于 Mask R-CNN，从细胞核候选区域按固定比例缩放生成细胞候选区域，并双分支预测核与全细胞掩码；同时发布 CytoNuke 数据集。其创新在于以核提示推导全细胞分割，并用形态特征分布评估分割可靠性；但固定缩放因子与单癌种数据限制泛化。

- **PMID 39440549**：CellSAM 在 SAM/MedSAM 框架下使用大尺度 ViT 编码器与小型 TinyViT 风格编码器，通过知识蒸馏和掩码融合模块增强细胞分割。其创新在于双编码器蒸馏与融合；适合资源受限场景的探索，但效率、复现细节和跨域泛化证据不足。

- **PMID 39528162**：CSGO 管线整合 HD-YOLO 细胞核分割、U-Net 细胞膜分割、欧氏距离变换和 watershed，以生成全细胞边界。其创新在于核与膜预测在几何后处理层面融合；适合 H&E 全细胞分析，但膜训练集较小，且论文报告 precision 较低。

- **PMID 40030236**：SegAnyPath 提出面向多分辨率、染色变异和多任务病理分割的基础模型，采用 MAE 自监督、RandStainNA 染色增强、自蒸馏、放大率预测头和任务引导 MoE 解码器。其创新在于统一处理细胞、组织和肿瘤分割；但荧光等域外数据表现有限，且资源需求较高。

## 横向比较与发展趋势

本节从八个维度进行横向比较。需要再次强调：不同论文评价设置不同，本文不进行跨论文性能排名。

**语义分割与实例分割。** 输入材料中既有区域语义分割，也有实例分割和检测式分割。区域语义分割主要回答“哪些像素属于某类结构”，例如上皮/基质分割、肾皮质结构分割、肺肿瘤区域分割、乳腺 tubule 分割等；实例分割进一步要求区分相邻对象，例如腺体、细胞核或全细胞实例。部分早期方法只进行中心检测或分类，不直接输出精确轮廓；这类方法适合计数或类型分析，但不能与实例分割方法直接比较。

**粘连对象分离。** 粘连、重叠和拥挤对象是病理图像分割的核心难点。输入材料中的解决机制包括：轮廓分支或边界分支、分隔结构预测、距离图/质心距离回归、分水岭后处理、候选框式实例分割、扩散模型实例预测以及核/膜联合后处理。轮廓感知方法适合边界较明确的腺体或核对象；距离图方法适合近似凸形且有质心意义的细胞核；候选框方法适合实例边界可由检测框引导的对象；核/膜联合后处理适合全细胞分割。不同机制依赖不同标注与后处理假设，不能简单判定孰优孰劣。

**监督粒度。** 方法库覆盖全监督像素级标注、实例级标注、点标注、交互式提示、伪标签富集和粗区域标注。全监督方法通常依赖高质量轮廓或实例标注；弱监督方法用点标注或点击提示降低标注成本；挑战赛或区域分割任务可能使用较粗的癌区或组织区域标注。监督粒度不同会直接影响评价方式：点标注方法不能直接与像素级全监督方法比较，交互式方法也不能与全自动方法在同一维度下简单排名。

**跨组织泛化。** 多器官、多染色和多中心是近年趋势。输入材料中既有面向多器官核分割的挑战基准，也有面向肾小球多染色泛化、肾脏多染色结构分割、泛癌核分割/分类、基础模型多器官训练等工作。染色归一化、随机染色增强、Hematoxylin 分量利用、边界感知、多分辨率预训练等机制都被用于缓解域差异。但多数泛化结论仍限于论文自身测试集，不能外推到所有组织、染色或扫描仪。

**细胞类型判别。** 细胞类型判别通常与核分割联合出现。早期方法将检测与分类分为两个阶段；后续方法在网络中加入分类分支，或同时预测核类型、组织类型和对象类别。多任务模型可以在同一网络中处理核分割、腺体分割、腔体分割和组织分类。挑战基准则将核检测、分割、分类和计数纳入统一评价。需要注意，类型判别性能受类别不平衡、标注质量和目标外观差异影响，输入材料中多篇论文均提到少样本类别性能较低。

**计算代价。** 输入材料中多数论文未完整报告参数量、FLOPs、显存、推理速度或部署成本，因此只能定性讨论。一般而言，多通道大网络、Mask R-CNN 式两阶段模型、扩散模型、测试时多次增强推理、基础模型和大尺寸 Transformer 编码器可能带来更高计算负担；轻量变体、单阶段语义分割或小型 U-Net 类模型可能更适合资源受限场景。但具体选择必须结合同一硬件环境下的实测结果，不能仅凭论文宣称判断。

**评价指标。** 不同论文使用不同指标：像素级 Dice/IoU、对象级 F1、AJI、Panoptic Quality、Hausdorff 距离、检测 F1、AP、特征分布一致性等。Dice/IoU 更关注像素重叠；对象级 F1 和 AJI 更关注检测与分割联合误差；Panoptic Quality 分解为检测质量与分割质量；Hausdorff 距离关注边界误差；AP 更偏检测/实例匹配；特征分布一致性则关注下游测量可靠性。由于指标定义和阈值不同，跨论文比较必须非常谨慎。

**外部验证。** 部分论文提供了独立数据集、多中心数据、跨染色测试或外部器官验证；也有许多论文仅在内部划分或单一数据集上评估。外部验证能更好反映泛化能力，但输入材料中并非所有方法都具备充分外部证据。对于只在内部测试集上报告结果的方法，不应将其结论外推到未见数据。

## 方法选择建议

以下建议基于输入证据中的方法机制与适用条件，不构成跨论文性能排名。

若任务是**细胞核计数或粗粒度类型分析**，且不需要精确轮廓，可关注以中心检测为核心的方法，例如早期 SC-CNN 式检测—分类流程。此类方法通常不需要完整核轮廓，但依赖中心标注或中心概率图监督。

若任务是**腺体实例分割且存在明显粘连**，可优先考虑轮廓感知、分隔结构预测、多通道区域/边界/位置融合或不确定性建模方法。若需要识别模糊区域或辅助审查，可关注提供不确定性图的方法；若计算资源有限，则应谨慎评估多网络并行或扩散式推理的成本。

若任务是**多组织细胞核实例分割并伴随细胞类型分类**，可关注距离图、多分支解码器、Transformer 编码器或特征金字塔类方法。此类方法通常适合 PanNuke、CoNSeP、MoNuSeg 等类型的数据，但不同数据集划分和指标不同，不能直接拿论文报告数值相互排名。

若任务是**低标注场景**，可选择部分点标注弱监督、交互式点击/涂鸦分割或多模型伪标签富集策略。弱监督方法能降低标注成本，但通常依赖初始检测质量、伪标签质量或人工提示质量；基础模型提示方法则需要额外验证提示稳定性与域适配。

若任务是**器官特异性结构分割**，应优先选择在该器官或相似结构上验证过的方法。例如肾脏结构分割可关注肾小球边界感知、肾皮质多结构 U-Net 或实验肾脏多类分割；乳腺 tubule 分割可关注专用 tubule 数据集与 padding 策略；肺肿瘤区域分割可参考挑战赛总结，但应将其视为基准与趋势，而不是单一最佳模型。

若任务是**全细胞分割而非仅细胞核分割**，需要同时考虑细胞膜、细胞质或细胞边界可见性。基于核候选缩放的方法适合核边界清晰且细胞范围可由核推导的场景；核/膜联合距离变换与分水岭方法适合膜信号可学习的场景。若细胞膜不明显或多细胞重叠严重，应谨慎评估假阳性和边界合并问题。

若关注**部署效率**，应优先查看是否报告参数量、FLOPs、显存、推理延迟和 WSI 处理流程。输入材料中只有部分方法提供效率线索；多数方法缺少完整效率证据。因此，实际选择前应在目标数据与目标硬件上进行复测。

若关注**泛化能力**，应优先选择提供多数据集、多染色、多中心或外部测试证据的方法，并结合染色归一化、染色增强、多分辨率训练等机制。即便论文报告了泛化结果，也应在目标染色、扫描仪和组织类型上重新验证。

## 文档覆盖索引

- PMID 26415167: [An Automatic Learning-Based Framework for Robust Nucleus Segmentation.](method_summaries/PMID_26415167_An%20Automatic%20Learning-Based%20Framework%20for%20Robust%20Nucleus%20Segmentation.md)
- PMID 26863654: [Locality Sensitive Deep Learning for Detection and Classification of Nuclei in Routine Colon Cancer Histology Images.](method_summaries/PMID_26863654_Locality%20Sensitive%20Deep%20Learning%20for%20Detection%20and%20Classification%20of%20Nuclei%20in%20Routine%20Colon%20Cancer%20Histology%20Images.md)
- PMID 28154470: [A Deep Convolutional Neural Network for segmenting and classifying epithelial and stromal regions in histopathological images.](method_summaries/PMID_28154470_A%20Deep%20Convolutional%20Neural%20Network%20for%20segmenting%20and%20classifying%20epithelial%20and%20stromal%20regions%20in%20histopathological%20i.md)
- PMID 27898306: [DCAN: Deep contour-aware networks for object instance segmentation from histology images.](method_summaries/PMID_27898306_DCAN_%20Deep%20contour-aware%20networks%20for%20object%20instance%20segmentation%20from%20histology%20images.md)
- PMID 28287963: [A Dataset and a Technique for Generalized Nuclear Segmentation for Computational Pathology.](method_summaries/PMID_28287963_A%20Dataset%20and%20a%20Technique%20for%20Generalized%20Nuclear%20Segmentation%20for%20Computational%20Pathology.md)
- PMID 28358671: [Gland Instance Segmentation Using Deep Multichannel Neural Networks.](method_summaries/PMID_28358671_Gland%20Instance%20Segmentation%20Using%20Deep%20Multichannel%20Neural%20Networks.md)
- PMID 29018612: [Segmentation and classification of colon glands with deep convolutional neural networks and total variation regularization.](method_summaries/PMID_29018612_Segmentation%20and%20classification%20of%20colon%20glands%20with%20deep%20convolutional%20neural%20networks%20and%20total%20variation%20regularizati.md)
- PMID 30580111: [Micro-Net: A unified model for segmentation of various objects in microscopy images.](method_summaries/PMID_30580111_Micro-Net_%20A%20unified%20model%20for%20segmentation%20of%20various%20objects%20in%20microscopy%20images.md)
- PMID 30594772: [MILD-Net: Minimal information loss dilated network for gland instance segmentation in colon histology images.](method_summaries/PMID_30594772_MILD-Net_%20Minimal%20information%20loss%20dilated%20network%20for%20gland%20instance%20segmentation%20in%20colon%20histology%20images.md)
- PMID 31317118: [Segmentation of Glomeruli Within Trichrome Images Using Deep Learning.](method_summaries/PMID_31317118_Segmentation%20of%20Glomeruli%20Within%20Trichrome%20Images%20Using%20Deep%20Learning.md)
- PMID 31561183: [Hover-Net: Simultaneous segmentation and classification of nuclei in multi-tissue histology images.](method_summaries/PMID_31561183_Hover-Net_%20Simultaneous%20segmentation%20and%20classification%20of%20nuclei%20in%20multi-tissue%20histology%20images.md)
- PMID 32903361: [An automatic nuclei segmentation method based on deep convolutional neural networks for histopathology images.](method_summaries/PMID_32903361_An%20automatic%20nuclei%20segmentation%20method%20based%20on%20deep%20convolutional%20neural%20networks%20for%20histopathology%20images.md)
- PMID 31647422: [A Multi-Organ Nucleus Segmentation Challenge.](method_summaries/PMID_31647422_A%20Multi-Organ%20Nucleus%20Segmentation%20Challenge.md)
- PMID 32712523: [Triple U-net: Hematoxylin-aware nuclei segmentation with progressive dense feature aggregation.](method_summaries/PMID_32712523_Triple%20U-net_%20Hematoxylin-aware%20nuclei%20segmentation%20with%20progressive%20dense%20feature%20aggregation.md)
- PMID 32746112: [Weakly Supervised Deep Nuclei Segmentation Using Partial Points Annotation in Histopathology Images.](method_summaries/PMID_32746112_Weakly%20Supervised%20Deep%20Nuclei%20Segmentation%20Using%20Partial%20Points%20Annotation%20in%20Histopathology%20Images.md)
- PMID 32769053: [NuClick: A deep learning framework for interactive segmentation of microscopic images.](method_summaries/PMID_32769053_NuClick_%20A%20deep%20learning%20framework%20for%20interactive%20segmentation%20of%20microscopic%20images.md)
- PMID 32835732: [Development and evaluation of deep learning-based segmentation of histologic structures in the kidney cortex with multiple histologic stains.](method_summaries/PMID_32835732_Development%20and%20evaluation%20of%20deep%20learning-based%20segmentation%20of%20histologic%20structures%20in%20the%20kidney%20cortex%20with%20multip.md)
- PMID 33154175: [Deep Learning-Based Segmentation and Quantification in Experimental Kidney Histopathology.](method_summaries/PMID_33154175_Deep%20Learning-Based%20Segmentation%20and%20Quantification%20in%20Experimental%20Kidney%20Histopathology.md)
- PMID 33190012: [NucleiSegNet: Robust deep learning architecture for the nuclei segmentation of liver cancer histopathology images.](method_summaries/PMID_33190012_NucleiSegNet_%20Robust%20deep%20learning%20architecture%20for%20the%20nuclei%20segmentation%20of%20liver%20cancer%20histopathology%20images.md)
- PMID 33216724: [Deep Learning Methods for Lung Cancer Segmentation in Whole-Slide Histopathology Images-The ACDC@LungHP Challenge 2019.](method_summaries/PMID_33216724_Deep%20Learning%20Methods%20for%20Lung%20Cancer%20Segmentation%20in%20Whole-Slide%20Histopathology%20Images-The%20ACDC%40LungHP%20Challenge%202019.md)
- PMID 35367734: [TSFD-Net: Tissue specific feature distillation network for nuclei segmentation and classification.](method_summaries/PMID_35367734_TSFD-Net_%20Tissue%20specific%20feature%20distillation%20network%20for%20nuclei%20segmentation%20and%20classification.md)
- PMID 36007483: [Boundary-aware glomerulus segmentation: Toward one-to-many stain generalization.](method_summaries/PMID_36007483_Boundary-aware%20glomerulus%20segmentation_%20Toward%20one-to-many%20stain%20generalization.md)
- PMID 36438040: [A dual decoder U-Net-based model for nuclei instance segmentation in hematoxylin and eosin-stained histological images.](method_summaries/PMID_36438040_A%20dual%20decoder%20U-Net-based%20model%20for%20nuclei%20instance%20segmentation%20in%20hematoxylin%20and%20eosin-stained%20histological%20images.md)
- PMID 36410209: [One model is all you need: Multi-task learning enables simultaneous histology image segmentation and classification.](method_summaries/PMID_36410209_One%20model%20is%20all%20you%20need_%20Multi-task%20learning%20enables%20simultaneous%20histology%20image%20segmentation%20and%20classification.md)
- PMID 36599960: [Tubule-U-Net: a novel dataset and deep learning-based tubule segmentation framework in whole slide images of breast cancer.](method_summaries/PMID_36599960_Tubule-U-Net_%20a%20novel%20dataset%20and%20deep%20learning-based%20tubule%20segmentation%20framework%20in%20whole%20slide%20images%20of%20breast%20canc.md)
- PMID 37305563: [Densely Convolutional Spatial Attention Network for nuclei segmentation of histological images for computational pathology.](method_summaries/PMID_37305563_Densely%20Convolutional%20Spatial%20Attention%20Network%20for%20nuclei%20segmentation%20of%20histological%20images%20for%20computational%20patholo.md)
- PMID 37778210: [Enhancing gland segmentation in colon histology images using an instance-aware diffusion model.](method_summaries/PMID_37778210_Enhancing%20gland%20segmentation%20in%20colon%20histology%20images%20using%20an%20instance-aware%20diffusion%20model.md)
- PMID 37788295: [Cervical cell's nucleus segmentation through an improved UNet architecture.](method_summaries/PMID_37788295_Cervical%20cell%27s%20nucleus%20segmentation%20through%20an%20improved%20UNet%20architecture.md)
- PMID 38157647: [CoNIC Challenge: Pushing the frontiers of nuclear detection, segmentation, classification and counting.](method_summaries/PMID_38157647_CoNIC%20Challenge_%20Pushing%20the%20frontiers%20of%20nuclear%20detection%2C%20segmentation%2C%20classification%20and%20counting.md)
- PMID 38292472: [Improving generalization capability of deep learning-based nuclei instance segmentation by non-deterministic train time and deterministic test time stain normalization.](method_summaries/PMID_38292472_Improving%20generalization%20capability%20of%20deep%20learning-based%20nuclei%20instance%20segmentation%20by%20non-deterministic%20train%20time%20.md)
- PMID 38507894: [CellViT: Vision Transformers for precise cell segmentation and classification.](method_summaries/PMID_38507894_CellViT_%20Vision%20Transformers%20for%20precise%20cell%20segmentation%20and%20classification.md)
- PMID 38781811: [Cyto R-CNN and CytoNuke Dataset: Towards reliable whole-cell segmentation in bright-field histological images.](method_summaries/PMID_38781811_Cyto%20R-CNN%20and%20CytoNuke%20Dataset_%20Towards%20reliable%20whole-cell%20segmentation%20in%20bright-field%20histological%20images.md)
- PMID 39440549: [CellSAM: Advancing Pathologic Image Cell Segmentation via Asymmetric Large-Scale Vision Model Feature Distillation Aggregation Network.](method_summaries/PMID_39440549_CellSAM_%20Advancing%20Pathologic%20Image%20Cell%20Segmentation%20via%20Asymmetric%20Large-Scale%20Vision%20Model%20Feature%20Distillation%20Aggre.md)
- PMID 39528162: [Cell Segmentation With Globally Optimized Boundaries (CSGO): A Deep Learning Pipeline for Whole-Cell Segmentation in Hematoxylin-and-Eosin-Stained Tissues.](method_summaries/PMID_39528162_Cell%20Segmentation%20With%20Globally%20Optimized%20Boundaries%20(CSGO)_%20A%20Deep%20Learning%20Pipeline%20for%20Whole-Cell%20Segmentation%20in%20Hem.md)
- PMID 39773093: [HistoNeXt: dual-mechanism feature pyramid network for cell nuclear segmentation and classification.](method_summaries/PMID_39773093_HistoNeXt_%20dual-mechanism%20feature%20pyramid%20network%20for%20cell%20nuclear%20segmentation%20and%20classification.md)
- PMID 40030236: [SegAnyPath: A Foundation Model for Multi- Resolution Stain-Variant and Multi-Task Pathology Image Segmentation.](method_summaries/PMID_40030236_SegAnyPath_%20A%20Foundation%20Model%20for%20Multi-%20Resolution%20Stain-Variant%20and%20Multi-Task%20Pathology%20Image%20Segmentation.md)
- PMID 41286516: [Evaluating cell AI foundation models in kidney pathology with human-in-the-loop enrichment.](method_summaries/PMID_41286516_Evaluating%20cell%20AI%20foundation%20models%20in%20kidney%20pathology%20with%20human-in-the-loop%20enrichment.md)
- PMID 42581240: [Benchmarking Deep Segmentation Architectures for Histopathological Nuclei Segmentation: A Controlled Study of Transfer Learning, Robustness, and Efficiency Across CNN, Transformer, and Hybrid Models.](method_summaries/PMID_42581240_Benchmarking%20Deep%20Segmentation%20Architectures%20for%20Histopathological%20Nuclei%20Segmentation_%20A%20Controlled%20Study%20of%20Transfer%20L.md)
