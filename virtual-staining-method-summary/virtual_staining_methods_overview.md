# 计算病理虚拟染色与染色转换方法综述

## 研究范围与证据边界

本总览围绕“虚拟染色与染色转换”方法库中的 39 篇结构化总结展开，覆盖计算病理中与染色外观生成、染色域转换和无标记组织学重建相关的方法谱系。其任务边界包括：H&E 或其他组织化学染色的颜色标准化 / 染色归一化；不同染色之间的双向或多域迁移；未染色、无标记或替代成像模态到 H&E 样图像的虚拟染色；H&E 到免疫组化、多重免疫荧光或功能染色的虚拟推断；以及面向定量标志物、全切片扩展、错位鲁棒性和临床可信验证的生成方法。

本总览不将“虚拟染色”狭义限定为从无色到彩色的图像上色，而是将其视为一类受组织形态、染色化学、成像物理和下游病理任务共同约束的图像到图像翻译问题。相应地，染色归一化、染色迁移、虚拟组织学、虚拟 IHC、虚拟多重染色和图像质量增强均被纳入同一方法谱系，因为它们共同面对染色外观、结构保真、语义一致性和诊断可用性之间的张力。

证据边界需要明确：本文仅依据给定的逐篇结构化总结写作，不补充未在输入中出现的实验数字、数据集、临床结论或产品证据。多数方法在原始总结中缺少完整的代码仓库、参数量、计算量、显存、推理速度、外部验证或系统消融信息，因此本文对性能表述保持保守。不同研究的器官、切片制备、扫描仪、染色协议、配对方式、评价指标和验证目标差异很大，视觉相似度、像素级指标或生成图像评分不能直接等同于诊断有效性，也不应在不同评价设置之间做未经支持的横向排名。

## 技术演进与分类框架

虚拟染色与染色转换方法的发展可概括为五条相互交叉的主线。以下分类并非互斥：同一篇工作可能同时涉及无标记成像、无配对学习、结构保持、全切片扩展或临床验证。

### 1. 无标记相位、光声、自体荧光等成像到 H&E 的重建

该方向的核心是将无标记物理对比度转换为病理医师熟悉的 H&E 外观。输入模态包括定量相位显微成像、多光子虚拟组织学、反射共聚焦显微镜、未染色明场图像、多光谱图像、紫外光声遥感 / 光声组织学、自体荧光或荧光寿命成像等。其方法学挑战不仅是颜色生成，还包括物理信号与组织染色语义之间的映射、组织形变与配准、厚组织或活体成像中的伪影，以及硬件特异性。代表工作包括 PMID 30728961、31872065、34795202、36801642、37040684、37223268、37749108、38231822、38282056、38948152、39069201、39223152、39636222；PMID 38325706 则从综述层面汇总了非固定组织虚拟染色的临床证据与转化障碍。

### 2. 染色间双向和多域转换

该方向主要解决已有染色图像之间的风格迁移、颜色标准化或多染色互转问题。早期方法依赖模板、直方图匹配、染色向量估计或稀疏自编码特征分区；随后对抗学习、循环一致性、特征解耦、多域标签条件和共享编码器逐步成为主流。代表工作包括 PMID 27373749、29533895、31632974、33718644、34362386、34805215、35026572、35877646、36113326、36328671、36473344、36844704、38198253、38574542。

### 3. 无配对、对比学习与结构保持

由于病理切片很难获得严格像素级配对，许多方法采用无配对图像翻译。CycleGAN 类循环一致性、CUT 类对比学习、PatchNCE、双对比学习、边缘保持损失、病理一致性约束、自正则化损失和位置一致性生成，均是为了在改变染色外观的同时保留组织结构。代表工作包括 PMID 33718644、33784619、34362386、35877646、36268068、36328671、36764189、36844704、37040684、37852162、38282056、41888143。

### 4. 虚拟 IHC、多重染色与定量标志物

这一方向不只追求视觉相似，而是进一步要求标志物表达、阳性区域、细胞计数或定量指标可靠。典型任务包括 SOX10、Ki-67、CD163、PIN-4、PD-L1、CD3、CD8、PanCK、DAPI 等标志物的虚拟生成，以及由此提取标记指数、细胞密度、免疫评分或预后相关特征。代表工作包括 PMID 32238879、33784619、35810588、39069201、39087085、39636222、40158294、41118427。

### 5. 全切片、错位鲁棒与可信临床验证

方法能否进入病理工作流，还取决于全切片处理效率、拼接伪影、配准误差、低质量切片、域偏移、异常检测和专家验证。该方向包括高性能染色标准化引擎、重叠窗口推理、灰度中间域多域归一化、伪影校正、置信度热力图、生成与配准解耦，以及多读者阅片或非劣效评估。代表工作包括 PMID 31632974、36473344、37852162、38231822、38574542、39069201、41118427、41888143。

## 逐方法创新点

以下按入库顺序逐条概括各方法的创新点。每个条目仅依据给定结构化总结，不对不同研究做跨论文性能排名。

1. **PMID 27373749**：StaNoSA 的创新在于用稀疏 / 去噪自编码器从模板图像学习特征空间，并在该空间中按组织子类型聚类后进行分簇直方图匹配。相比全局颜色匹配，它试图降低模板与目标组织比例不平衡带来的影响；证据主要集中在 H&E 染色归一化。

2. **PMID 29533895**：该方法将染色归一化建模为数据集级“染色迁移”，用对抗生成网络学习目标域染色分布，并将染色迁移网络与分类 / 分割任务网络联合训练。其创新点是让染色转换服务于下游任务，而不是只做单参考图像颜色匹配。

3. **PMID 30728961**：PhaseStain 将配对定量相位图像转换为明场染色图像，结合多模态配准、U-Net 生成器、L1 损失、全变分正则和对抗损失。其创新在于证明单通道相位信息可重建 H&E、Jones、Masson 等染色外观，并分析相位噪声鲁棒性。

4. **PMID 31632974**：该工作将 Macenko 类染色向量估计工程化为高性能 WSI 染色归一化系统，创新点包括自动 Otsu 阈值、查找表、多线程、像素采样和参数交叉检查，以兼顾速度、低质量图像鲁棒性和下游分类稳定性。

5. **PMID 31872065**：该研究并非典型染色图像生成，而是用多光子四通道无标记虚拟组织学进行癌症 / 正常分类。其方法创新在于用基于物理的图像退化增强模拟便携式术中系统，提高跨系统泛化能力，并面向术中实时诊断场景。

6. **PMID 32238879**：SOX10 虚拟 IHC 的创新在于通过同一组织层脱色复染、细胞核级配准、核中心检测和颜色阈值自动生成单细胞标签，从而训练从 H&E 预测 SOX10 核阳性状态的网络。它把虚拟染色推进到单细胞免疫表型层面。

7. **PMID 33718644**：该工作用 CycleGAN 实现细胞学 Giemsa 与 Papanicolaou 染色之间的双向无配对转换，并结合显微镜图像数据增强和专家细粒度视觉评估。其创新在于将染色互转引入细胞学场景。

8. **PMID 33784619**：PC-StainGAN 针对无配对 H&E 到 Ki-67 转换，引入病理表征网络和病理一致性约束，同时结合跳跃连接与基于 SSIM 的循环结构一致性损失。其创新是用少量专家知识约束生成图像保持病理语义。

9. **PMID 34362386**：该工作将 CycleGAN 用于日常 HE 染色图像归一化，覆盖扫描设备和染色协议差异，并用下游淋巴结肿瘤分类评估归一化收益。其创新在于把无配对循环转换与机构内染色变异建模结合。

10. **PMID 34795202**：该研究提出面向皮肤反射共聚焦显微镜的无活检在体虚拟组织学，先用 3D 相邻未染色 RCM 图像栈生成虚拟醋酸染色，再转换为伪 H&E。其创新是用离体染色时间序列构造可配准训练目标，减少直接活检染色带来的形变问题。

11. **PMID 34805215**：StainNet 的创新在于用全 1×1 卷积做像素级颜色映射，并从 StainGAN 教师网络蒸馏。它强调轻量、快速和保留源图像纹理，适合染色归一化作为大规模病理分析前置模块。

12. **PMID 35026572**：该工作提出结构特征与颜色变化特征解耦的 GAN 染色迁移框架，包括一对一 OOT 和多对多 MMT。其创新是用随机噪声替换颜色变化特征实现目标风格转换，并尝试单网络多风格迁移。

13. **PMID 35810588**：MVFStain 将 H&E 到多种功能染色的转换建模为特定域映射，使用内容编码器、风格编码器、域 ID、KL 损失和 histo 损失。其创新是单网络同时生成多个虚拟功能染色，并分析阳性信号生成的准确性。

14. **PMID 35877646**：StainCUT 将 PatchNCE 对比学习用于无配对染色归一化，不需要参考图像或配对图像。其创新在于用对比特征约束保持内容，并比较训练阶段与推理阶段应用归一化对下游分割的影响。

15. **PMID 36113326**：CAGAN 结合目标域配对监督和源域无监督一致性学习，采用双解码器一致性正则、输入颜色扰动和直方图损失。其创新是在染色归一化中同时利用目标域模板信息和无标签源域图像。

16. **PMID 36268068**：该工作在 CycleGAN 中集成预训练分割网络进行自监督语义引导，并提出额外通道机制以隐式存储解决欠定重建所需的元信息。其创新是面向下游分割任务优化染色到染色翻译，同时揭示复杂结构翻译失败的风险。

17. **PMID 36328671**：该研究系统比较 CycleGAN 中不同归一化层对虚拟染色域偏移的影响，并用下游肾小球分割和图像分布建模评估。其核心贡献是提出“视觉可信并不等于下游任务可靠”的警示性证据。

18. **PMID 36473344**：该工作将 score-based diffusion model 用于 H&E 染色归一化，先用稀疏非负矩阵分解分离 hematoxylin 和 eosin 成分，再用重叠移动窗口减少 WSI 网格伪影。其创新是用染色分离约束扩散生成自由度。

19. **PMID 36764189**：PG-GAN 在 CUT 基础上加入病理特征损失和染色标准化微调，用少量纤维化标签引导 H&E 到 Masson trichrome 的无配对转换。其创新是将专家先验用于减少纤维结构欠染或误染。

20. **PMID 36801642**：该工作系统比较未染色切片厚度、脱蜡和封片状态对虚拟 H&E 的影响，并分别用相邻切片 CycleGAN 与同切片 pix2pix 验证无监督和有监督路线。其创新在于把制片条件作为虚拟染色可行性的一级变量。

21. **PMID 36844704**：该工作改进 StarGAN-v2，实现无监督多对多染色翻译，并引入 Canny 边缘检测损失以保持组织形态。其创新是把边缘结构约束用于多染色数据增强，并验证下游乳腺癌分类收益。

22. **PMID 37040684**：该工作在无标记多光谱乳腺组织图像上比较 pix2pix、CycleGAN 和 CUT 的数字 H&E 染色效果，并提出基于颜色聚类与 EMD 的色度差异评估。其创新是系统比较配对、循环一致和对比学习三类生成范式。

23. **PMID 37223268**：该工作以 pix2pix 为基线，系统评估生成器容量对虚拟 H&E 的影响，发现密集卷积结构有助于提升结构相似度、核再现和减少幻觉伪影。其创新是把网络容量与组织学可行性评估结合起来。

24. **PMID 37749108**：该研究结合紫外光声遥感和紫外散射双对比度硬件与 CycleGAN 无监督转换，从厚组织无标记图像生成虚拟 H&E。其创新在于硬件双对比度与生成模型的联合设计，并面向术中边缘评估。

25. **PMID 37932315**：该工作从明场单精子图像虚拟生成 dsDNA 与 ssDNA 荧光图像，并结合特征匹配配准、背景直方图去噪和 pix2pix / pix2pix++。其创新在于将虚拟染色用于单细胞像素级 DFI 定量分析。

26. **PMID 37852162**：FFPE++ 用对比无配对图像翻译校正 FFPE 切片伪影，生成器引入混合通道 - 空间注意力模块，并使用自正则化损失保留低层结构。其创新是把质量增强视为染色转换的前置或伴随任务。

27. **PMID 38198253**：GramGAN 提出风格编码字典、GramLIN 归一化和 Rényi 熵正则，实现单网络多域渐进染色迁移。其创新是让网络根据当前特征与目标风格的接近程度逐步完成染色转换。

28. **PMID 38231822**：该工作构建自动化 PARS 薄透射切片全玻片扫描流程，包括自动对焦、功率校正、拼接对比度均衡，并展示同一组织后续 H&E 对比和虚拟 H&E。其创新在于无标记 WSI 采集工程化与虚拟染色工作流衔接。

29. **PMID 38282056**：DCLGAN 将双向映射与双重对比学习结合，用于未染色皮肤明场图像到虚拟 H&E，并采用重叠融合减少全切片边界伪影。其创新是用双对比机制增强输入与生成 patch 之间的互信息。

30. **PMID 38325706**：该综述的创新不在单一模型，而在按器官系统总结非固定组织光学成像虚拟染色证据，覆盖数字染色匹配、受激拉曼组织学和深度学习虚拟染色，并讨论术中快速病理的转化障碍。

31. **PMID 38574542**：MultiStain-CycleGAN 通过中间灰度域和颜色增强扩展输入分布，使模型在多个 H&E 染色域之间归一化。其创新是用灰度中间域降低对单一目标域重训的依赖，同时评估域分类和肿瘤分类。

32. **PMID 38948152**：该工作从自体荧光寿命图像生成虚拟 H&E，比较不同 FLIM 输入格式，采用强度加权假彩色寿命图像和 DISTS 损失。其创新在于把荧光寿命信息引入虚拟染色，以改善细胞细节重建。

33. **PMID 39069201**：该研究从高光谱自体荧光图像生成虚拟 H&E 和虚拟 PIN-4，并通过自动 Gleason 分级模型与多读者阅片进行临床级验证。其创新是构建从成像、虚拟染色到诊断评估的多层验证链路；其中 H&E 非劣效证据较强，PIN-4 未达统计显著非劣效。

34. **PMID 39087085**：该工作在同一组织切片上构建 H&E 到 Ki-67 IHC 的配对转换，并比较 RGB 与 optical density 空间、U-Net / Pix2Pix / CycleGAN 以及 intraslide 与 cross-case 验证。其创新是明确以 Ki-67 labeling index 作为临床相关评估指标。

35. **PMID 39223152**：该工作面向无标签光声组织学，提出 E-CUT 虚拟 H&E、U-Net 核分割和 StepFF 特征融合分类。其创新是把虚拟染色、形态学特征提取和癌症分类串联为无标记病理分析链路。

36. **PMID 39636222**：该研究从自体荧光图像生成 H&E 和多重免疫荧光虚拟染色，采用伪 IHC 中间表示和基于目标荧光强度的像素级加权损失。其创新是面向免疫肿瘤学标志物空间定量，处理低丰度和异质性标志物。

37. **PMID 40158294**：VISTA 从 H&E 生成虚拟 CD163 IHC，并同步优化 IHC 阳性区域分割和细胞核分割，进一步提取 M2-TAM 密度用于预后分析。其创新是把虚拟染色平台转化为可解释细胞密度型生物标志物发现工具。

38. **PMID 41118427**：该工作提出共享 H&E 编码器 / 生成器与多个目标染色解码器的多染色生成框架，支持多种 IHC，使用无标注知识引导损失、前向与恒等正则化，以及判别器置信度自检验。其创新在于可扩展、可信和面向 WSI 的虚拟多染色。

39. **PMID 41888143**：DGR 提出解耦生成与配准的鲁棒虚拟染色框架，包含配准降噪和位置一致性生成两个模块。其创新是在不改变既有生成模型主干的前提下，提高严重组织错位条件下的虚拟染色保真度，并在推理阶段不依赖配准模块。

## 横向比较与发展趋势

由于各方法在输入模态、器官、染色类型、训练配对方式、评价指标和验证目标上差异显著，本节不做跨论文性能排名，只从关键维度归纳可比较的设计取舍。凡原文仅报告视觉相似度或像素级指标者，不能据此推断诊断等效性。

### 输入成像模态

方法库中的输入模态可分为两大类。第一类是已染色病理图像，包括 H&E、Giemsa、Papanicolaou、PAS、Masson、Jones、特殊功能染色或 IHC。此类任务主要关注颜色标准化、染色迁移或多域互转，代表方法包括 PMID 27373749、29533895、31632974、33718644、33784619、34362386、34805215、35026572、35810588、35877646、36113326、36328671、36473344、36844704、38198253、38574542、39087085、40158294、41118427。

第二类是无标记、未染色或替代物理成像，包括定量相位、多光子、反射共聚焦、未染色明场、多光谱、紫外光声遥感、光声组织学、自体荧光和荧光寿命成像。此类任务的关键不是单纯颜色迁移，而是物理对比度到组织学语义的映射，代表方法包括 PMID 30728961、31872065、34795202、36801642、37040684、37223268、37749108、37932315、38231822、38282056、38948152、39069201、39223152、39636222。PMID 38325706 从综述层面说明这些模态在非固定组织场景中的临床潜力与限制。

### 配对与非配对训练

配对训练通常依赖同一切片、脱色复染、连续切片或严格配准，适合结构对应关系明确的任务，例如 PMID 30728961、32238879、36801642 中的有监督部分、37223268、37932315、39087085、39069201、39636222、40158294。配对方法有利于像素级监督，但容易受组织处理形变、切片差异和配准误差影响。

非配对训练广泛用于染色归一化和虚拟染色，以减少昂贵配准成本，例如 CycleGAN、CUT、对比学习和多域 GAN。代表工作包括 PMID 33718644、34362386、35877646、36328671、36764189、36844704、37040684、38198253、38282056、38574542。部分方法采用半配对、任务引导或专家先验，如 PMID 33784619、36268068、36764189、41118427。总体趋势是：非配对方法提高了数据可得性，但也提高了对结构保持、语义约束和可信验证的要求。

### 目标染色

目标染色可分为三层。第一层是 H&E 或 H&E 样图像，这是最常见目标，覆盖大量无标记虚拟染色和染色归一化工作。第二层是特殊组织化学染色，如 Jones、Masson trichrome、PAS、PASM、Giemsa、Papanicolaou 等，代表工作包括 PMID 30728961、33718644、36764189、38198253。第三层是 IHC、多重免疫荧光或功能标志物染色，如 SOX10、Ki-67、CD163、PIN-4、PD-L1、CD3、CD8、PanCK、DAPI 等，代表工作包括 PMID 32238879、33784619、35810588、39069201、39087085、39636222、40158294、41118427。

从趋势看，目标染色越接近特异性分子标志物，虚拟染色越不能只依赖颜色风格迁移，而需要标志物定位、阳性区域分割、细胞级标签、定量指数或临床阅片验证。

### 配准依赖

配准依赖与训练范式高度相关。配对同切片方法通常高度依赖配准，例如 PMID 32238879、37932315、39087085、40158294。无标记到染色图像任务若使用同一或近连续切片，也需要配准或至少空间一致性处理，例如 PMID 30728961、36801642、39069201、39636222。

无配对方法降低了像素级配准要求，例如 PMID 33718644、34362386、35877646、38198253、38574542。但无配对并不意味着无需结构约束；相反，它更容易产生空间错位或语义漂移。PMID 41888143 明确将生成与配准解耦，用配准降噪和位置一致性生成处理错位鲁棒性，体现了从“依赖配准”到“容忍错位”的方法演进。

### 结构保真

结构保真是虚拟染色可信性的基础。不同方法采用不同机制：跳跃连接和结构正则用于保留目标域图像内容，如 PMID 29533895、33784619；循环一致性和 SSIM 约束用于保持重建结构，如 PMID 33784619、34362386；病理一致性损失和专家标注用于保持病灶语义，如 PMID 33784619、36764189；边缘损失用于保持形态边界，如 PMID 36844704；对比学习用于保持 patch 级特征一致，如 PMID 35877646、38282056、37852162；染色分离用于限制颜色误转移，如 PMID 36473344；密集卷积用于提升核形态再现，如 PMID 37223268；自正则化损失用于保留核轮廓和细胞质细节，如 PMID 37852162；位置一致性生成用于避免生成器隐藏结构错位，如 PMID 41888143。

这些机制并非互相替代，而是反映了结构保真的不同层次：像素结构、局部纹理、细胞核形态、组织区域语义和病理诊断语义。

### 幻觉风险

虚拟染色的主要风险是生成看似合理但并非真实存在的结构或标志物表达。PMID 36328671 提供了关键警示：即使 CycleGAN 生成图像视觉可信，不同归一化层和翻译方向仍可能导致下游分割性能显著变化，视觉检查不足以证明任务可靠性。

在虚拟 IHC 或虚拟多重染色中，幻觉风险更高，因为目标染色包含特异性生物标志物。PMID 39636222 指出低丰度或异质性标志物如 PD-L1、CD8 的预测更困难；PMID 41118427 引入自检验置信度热力图以增强可信度；PMID 40158294 虽然提取了 M2-TAM 密度，但仍需更大规模验证。PMID 37852162 在 FFPE 伪影校正中也提示，填充样视觉改善不一定对应真实组织内容。总体趋势是从“生成好看图像”转向“检测不可信区域、量化不确定性和引入外部验证”。

### 定量标志物保持

对于虚拟 IHC 和多重染色，定量标志物保持比像素相似度更关键。PMID 32238879 以细胞级 SOX10 阳性状态评估虚拟 IHC；PMID 33784619 用 Ki-67 阳性区域相关性评估；PMID 35810588 使用 mIOD、CNR、gCNR 等阳性信号指标；PMID 37932315 以 DFI 定量为目标；PMID 39087085 用 Ki-67 labeling index 相关性揭示 intraslide 与 cross-case 验证差异；PMID 39069201 将虚拟染色与 Gleason 分级、PIN-4 指标和专家阅片关联；PMID 39636222 关注 mIF 标志物空间定量和 CPS/TPS 相关性；PMID 40158294 将虚拟 CD163 转化为 M2-TAM 密度并做预后分析。

这些工作共同说明：如果目标是定量标志物，评价不能停留在 SSIM、PSNR、FID 或专家主观评分，而应进一步检验标志物定位、计数、指数相关性、临床分层或预后关联。但即便这些指标较好，也不能直接等同于临床诊断有效性，仍需独立验证。

### 病理医师评估

多篇工作引入病理医师评估，但评估协议差异很大。PMID 33718644 使用专家对细胞核、细胞质和细胞布局打分；PMID 36764189 使用病理医生进行纤维化分期评分；PMID 37040684、37223268、37749108、38282056、38948152、39069201、41888143 等采用不同形式的视觉评估、盲评、诊断一致性或非劣效评估；PMID 38325706 则汇总了多项非固定组织虚拟染色研究中的专家评估结果。

由于评分维度、病例构成、染色目标、阅片人数和统计目标不同，不同研究中的病理医师评估不可直接横比。专家评估能够支持可用性判断，但不能单独证明临床等效性。

### 全切片扩展性

全切片扩展性涉及处理速度、内存、拼接伪影、图块边界、域偏移和部署方式。PMID 31632974 强调高性能 WSI 染色归一化；PMID 34805215 强调轻量 1×1 卷积网络的速度优势；PMID 36473344 使用重叠移动窗口减少扩散模型 WSI 网格伪影；PMID 38282056 使用重叠和 alpha blending 消除 patch 边界；PMID 38231822 构建自动 PARS WSI 扫描与拼接流程；PMID 38574542 以 tile 为单位进行多域归一化；PMID 41118427 使用 2D Hamming 窗消除 tile 拼接伪影并部署于云平台；PMID 41888143 强调推理阶段无需配准以提升部署效率。

趋势是：虚拟染色方法正从局部 patch 演示转向 WSI 级工作流，但效率、拼接一致性和大规模验证仍是关键瓶颈。

### 外部验证与可信落地

部分方法在总结中展示了多数据集、多中心、跨扫描仪或外部测试证据，例如 PMID 31632974、34362386、35877646、36113326、36473344、38574542、39069201、40158294、41118427。但外部验证的定义、规模、器官、染色和终点并不一致，不能据此进行方法排序。

可信落地趋势包括：下游任务验证、专家阅片、非劣效设计、置信度自检验、异常检测、错位鲁棒性、染色分离、定量标志物相关性和跨病例验证。PMID 36328671 和 PMID 39087085 尤其提醒：视觉可信或同切片高相关可能高估泛化能力，跨病例、跨机构和跨染色协议验证才是临床转化的关键。

### 总体发展趋势

综合来看，虚拟染色与染色转换方法正从“颜色统计对齐”演进为“结构、语义、标志物和可信性联合约束”的方法体系。早期方法主要解决扫描仪和染色协议差异；随后 GAN 和 CycleGAN 使无配对染色迁移成为可能；对比学习、病理一致性、边缘约束和染色分离增强了结构保真；虚拟 IHC 和多重染色进一步要求分子标志物定量可靠；最新工作则更关注全切片部署、错位鲁棒、自检验和临床级验证。未来的核心问题不是生成图像是否看起来像真实染色，而是生成结果能否在明确任务、明确人群和明确验证协议下安全使用。

## 方法选择建议

以下建议面向方法选型，不构成临床推荐。实际选择应结合数据模态、标注条件、目标染色、计算资源和验证要求。

### 若目标是 H&E 染色标准化或域偏移消除

如果任务只是减少 H&E 颜色差异、提高下游模型稳定性，可优先考虑轻量或工程化方法，例如 PMID 27373749 的分簇直方图匹配、PMID 31632974 的高速 WSI 归一化、PMID 34805215 的轻量像素映射。若数据无配对且希望学习机构间风格差异，可考虑 CycleGAN 或对比学习方法，例如 PMID 34362386、35877646、36113326、38574542。若关注多域泛化和减少重训，可关注灰度中间域或风格字典方法，如 PMID 38574542、38198253。

### 若目标是从无标记成像生成虚拟 H&E

应首先根据硬件模态选择方法。定量相位可参考 PMID 30728961；多光子虚拟组织学可参考 PMID 31872065；皮肤 RCM 可参考 PMID 34795202；未染色明场可参考 PMID 36801642、37223268、38282056；多光谱可参考 PMID 37040684；紫外光声或光声组织学可参考 PMID 37749108、39223152；PARS WSI 可参考 PMID 38231822；自体荧光或荧光寿命可参考 PMID 38948152、39069201、39636222。选择时应重点评估物理信号是否包含足够的核与基质对比、训练目标是否可配准、组织形变是否可控，以及是否具备病理医师阅片验证。

### 若目标是染色间互转或数据增强

若两种染色之间存在较多无配对图像，可使用 CycleGAN 类双向转换，例如 PMID 33718644、34362386；若希望减少循环一致性开销并用对比特征保持内容，可考虑 CUT / StainCUT 类方法，例如 PMID 35877646；若需要多染色单网络转换，可考虑多域方法，例如 PMID 35026572、36844704、38198253、41118427。若转换图像仅用于数据增强，应进一步验证增强后下游分类、分割或检测任务是否稳定提升，而不是只看生成图像真实感。

### 若目标是虚拟 IHC、多重染色或定量标志物

此类任务应优先选择具有细胞级、标志物级或临床指标验证的方法。PMID 32238879 适合单细胞核标志物概念验证；PMID 33784619 和 PMID 39087085 适合 Ki-67 相关任务，但需特别注意跨病例泛化；PMID 35810588 适合多功能染色生成；PMID 39069201 适合自体荧光到 H&E / PIN-4 的临床级验证场景；PMID 39636222 适合多重免疫荧光空间定量；PMID 40158294 适合从 H&E 提取免疫细胞密度型生物标志物；PMID 41118427 适合多染色可扩展生成和可信自检验。若目标标志物表达稀疏、异质性强或依赖胞膜 / 胞浆定位，应谨慎评估假阳性、假阴性和定量偏倚。

### 若目标是全切片部署、错位鲁棒或伪影校正

全切片场景应优先考虑效率、拼接一致性和异常处理。PMID 31632974 和 PMID 34805215 适合高速归一化；PMID 36473344 适合关注 WSI 网格伪影的扩散模型方案；PMID 37852162 适合 FFPE 伪影校正；PMID 38231822 适合无标记 WSI 采集与虚拟染色衔接；PMID 38574542 适合多域 tile 级归一化；PMID 41118427 适合多染色 WSI 云平台部署；PMID 41888143 适合配对数据存在组织错位或形变的场景。若训练数据配准质量差，应优先考虑错位鲁棒方法，而不是直接提高生成器容量。

### 若目标是临床级验证或可信落地

临床级验证不能只依赖生成模型指标。应优先选择包含下游任务、专家阅片、非劣效设计、置信度估计或跨病例验证的方法，例如 PMID 39069201、41118427、41888143、40158294。同时应参考 PMID 36328671 的警示：视觉可信不等于任务可靠；参考 PMID 39087085 的结论：intraslide 评估可能高估性能。对于任何虚拟 IHC 或虚拟多重染色，若没有独立外部验证和明确临床终点，不应将其视为已确证的诊断替代方案。

## 文档覆盖索引

- PMID 27373749: [Stain Normalization using Sparse AutoEncoders (StaNoSA): Application to digital pathology.](method_summaries/PMID_27373749_Stain%20Normalization%20using%20Sparse%20AutoEncoders%20(StaNoSA)_%20Application%20to%20digital%20pathology.md)
- PMID 29533895: [Adversarial Stain Transfer for Histopathology Image Analysis.](method_summaries/PMID_29533895_Adversarial%20Stain%20Transfer%20for%20Histopathology%20Image%20Analysis.md)
- PMID 30728961: [PhaseStain: the digital staining of label-free quantitative phase microscopy images using deep learning.](method_summaries/PMID_30728961_PhaseStain_%20the%20digital%20staining%20of%20label-free%20quantitative%20phase%20microscopy%20images%20using%20deep%20learning.md)
- PMID 31632974: [A High-Performance System for Robust Stain Normalization of Whole-Slide Images in Histopathology.](method_summaries/PMID_31632974_A%20High-Performance%20System%20for%20Robust%20Stain%20Normalization%20of%20Whole-Slide%20Images%20in%20Histopathology.md)
- PMID 31872065: [Real-time intraoperative diagnosis by deep neural network driven multiphoton virtual histology.](method_summaries/PMID_31872065_Real-time%20intraoperative%20diagnosis%20by%20deep%20neural%20network%20driven%20multiphoton%20virtual%20histology.md)
- PMID 32238879: [A machine learning algorithm for simulating immunohistochemistry: development of SOX10 virtual IHC and evaluation on primarily melanocytic neoplasms.](method_summaries/PMID_32238879_A%20machine%20learning%20algorithm%20for%20simulating%20immunohistochemistry_%20development%20of%20SOX10%20virtual%20IHC%20and%20evaluation%20on%20pri.md)
- PMID 33718644: [Mutual stain conversion between Giemsa and Papanicolaou in cytological images using cycle generative adversarial network.](method_summaries/PMID_33718644_Mutual%20stain%20conversion%20between%20Giemsa%20and%20Papanicolaou%20in%20cytological%20images%20using%20cycle%20generative%20adversarial%20network.md)
- PMID 33784619: [Unpaired Stain Transfer Using Pathology-Consistent Constrained Generative Adversarial Networks.](method_summaries/PMID_33784619_Unpaired%20Stain%20Transfer%20Using%20Pathology-Consistent%20Constrained%20Generative%20Adversarial%20Networks.md)
- PMID 34362386: [Normalization of HE-stained histological images using cycle consistent generative adversarial networks.](method_summaries/PMID_34362386_Normalization%20of%20HE-stained%20histological%20images%20using%20cycle%20consistent%20generative%20adversarial%20networks.md)
- PMID 34795202: [Biopsy-free in vivo virtual histology of skin using deep learning.](method_summaries/PMID_34795202_Biopsy-free%20in%20vivo%20virtual%20histology%20of%20skin%20using%20deep%20learning.md)
- PMID 34805215: [StainNet: A Fast and Robust Stain Normalization Network.](method_summaries/PMID_34805215_StainNet_%20A%20Fast%20and%20Robust%20Stain%20Normalization%20Network.md)
- PMID 35026572: [Stain transfer using Generative Adversarial Networks and disentangled features.](method_summaries/PMID_35026572_Stain%20transfer%20using%20Generative%20Adversarial%20Networks%20and%20disentangled%20features.md)
- PMID 35810588: [MVFStain: Multiple virtual functional stain histopathology images generation based on specific domain mapping.](method_summaries/PMID_35810588_MVFStain_%20Multiple%20virtual%20functional%20stain%20histopathology%20images%20generation%20based%20on%20specific%20domain%20mapping.md)
- PMID 35877646: [StainCUT: Stain Normalization with Contrastive Learning.](method_summaries/PMID_35877646_StainCUT_%20Stain%20Normalization%20with%20Contrastive%20Learning.md)
- PMID 36113326: [Colour adaptive generative networks for stain normalisation of histopathology images.](method_summaries/PMID_36113326_Colour%20adaptive%20generative%20networks%20for%20stain%20normalisation%20of%20histopathology%20images.md)
- PMID 36268068: [Improving unsupervised stain-to-stain translation using self-supervision and meta-learning.](method_summaries/PMID_36268068_Improving%20unsupervised%20stain-to-stain%20translation%20using%20self-supervision%20and%20meta-learning.md)
- PMID 36328671: [CycleGAN for virtual stain transfer: Is seeing really believing?](method_summaries/PMID_36328671_CycleGAN%20for%20virtual%20stain%20transfer_%20Is%20seeing%20really%20believing_.md)
- PMID 36473344: [Stain normalization using score-based diffusion model through stain separation and overlapped moving window patch strategies.](method_summaries/PMID_36473344_Stain%20normalization%20using%20score-based%20diffusion%20model%20through%20stain%20separation%20and%20overlapped%20moving%20window%20patch%20strate.md)
- PMID 36764189: [Unpaired virtual histological staining using prior-guided generative adversarial networks.](method_summaries/PMID_36764189_Unpaired%20virtual%20histological%20staining%20using%20prior-guided%20generative%20adversarial%20networks.md)
- PMID 36801642: [Unstained Tissue Imaging and Virtual Hematoxylin and Eosin Staining of Histologic Whole Slide Images.](method_summaries/PMID_36801642_Unstained%20Tissue%20Imaging%20and%20Virtual%20Hematoxylin%20and%20Eosin%20Staining%20of%20Histologic%20Whole%20Slide%20Images.md)
- PMID 36844704: [Unsupervised many-to-many stain translation for histological image augmentation to improve classification accuracy.](method_summaries/PMID_36844704_Unsupervised%20many-to-many%20stain%20translation%20for%20histological%20image%20augmentation%20to%20improve%20classification%20accuracy.md)
- PMID 37040684: [Comparison of deep learning models for digital H&E staining from unpaired label-free multispectral microscopy images.](method_summaries/PMID_37040684_Comparison%20of%20deep%20learning%20models%20for%20digital%20H%26E%20staining%20from%20unpaired%20label-free%20multispectral%20microscopy%20images.md)
- PMID 37223268: [The effect of neural network architecture on virtual H&E staining: Systematic assessment of histological feasibility.](method_summaries/PMID_37223268_The%20effect%20of%20neural%20network%20architecture%20on%20virtual%20H%26E%20staining_%20Systematic%20assessment%20of%20histological%20feasibility.md)
- PMID 37749108: [Deep learning-enabled realistic virtual histology with ultraviolet photoacoustic remote sensing microscopy.](method_summaries/PMID_37749108_Deep%20learning-enabled%20realistic%20virtual%20histology%20with%20ultraviolet%20photoacoustic%20remote%20sensing%20microscopy.md)
- PMID 37932315: [Virtual staining for pixel-wise and quantitative analysis of single cell images.](method_summaries/PMID_37932315_Virtual%20staining%20for%20pixel-wise%20and%20quantitative%20analysis%20of%20single%20cell%20images.md)
- PMID 37852162: [FFPE++: Improving the quality of formalin-fixed paraffin-embedded tissue imaging via contrastive unpaired image-to-image translation.](method_summaries/PMID_37852162_FFPE%2B%2B_%20Improving%20the%20quality%20of%20formalin-fixed%20paraffin-embedded%20tissue%20imaging%20via%20contrastive%20unpaired%20image-to-image.md)
- PMID 38198253: [Unsupervised Multi-Domain Progressive Stain Transfer Guided by Style Encoding Dictionary.](method_summaries/PMID_38198253_Unsupervised%20Multi-Domain%20Progressive%20Stain%20Transfer%20Guided%20by%20Style%20Encoding%20Dictionary.md)
- PMID 38231822: [Automated Whole Slide Imaging for Label-Free Histology Using Photon Absorption Remote Sensing Microscopy.](method_summaries/PMID_38231822_Automated%20Whole%20Slide%20Imaging%20for%20Label-Free%20Histology%20Using%20Photon%20Absorption%20Remote%20Sensing%20Microscopy.md)
- PMID 38282056: [Dual contrastive learning based image-to-image translation of unstained skin tissue into virtually stained H&E images.](method_summaries/PMID_38282056_Dual%20contrastive%20learning%20based%20image-to-image%20translation%20of%20unstained%20skin%20tissue%20into%20virtually%20stained%20H%26E%20images.md)
- PMID 38325706: [Virtual Staining of Nonfixed Tissue Histology.](method_summaries/PMID_38325706_Virtual%20Staining%20of%20Nonfixed%20Tissue%20Histology.md)
- PMID 38574542: [Multi-domain stain normalization for digital pathology: A cycle-consistent adversarial network for whole slide images.](method_summaries/PMID_38574542_Multi-domain%20stain%20normalization%20for%20digital%20pathology_%20A%20cycle-consistent%20adversarial%20network%20for%20whole%20slide%20images.md)
- PMID 38948152: [Deep learning-based virtual H&E staining from label-free autofluorescence lifetime images.](method_summaries/PMID_38948152_Deep%20learning-based%20virtual%20H%26%20E%20staining%20from%20label-free%20autofluorescence%20lifetime%20images.md)
- PMID 39069201: [Clinical-Grade Validation of an Autofluorescence Virtual Staining System With Human Experts and a Deep Learning System for Prostate Cancer.](method_summaries/PMID_39069201_Clinical-Grade%20Validation%20of%20an%20Autofluorescence%20Virtual%20Staining%20System%20With%20Human%20Experts%20and%20a%20Deep%20Learning%20System%20f.md)
- PMID 39087085: [Transformation from hematoxylin-and-eosin staining to Ki-67 immunohistochemistry digital staining images using deep learning: experimental validation on the labeling index.](method_summaries/PMID_39087085_Transformation%20from%20hematoxylin-and-eosin%20staining%20to%20Ki-67%20immunohistochemistry%20digital%20staining%20images%20using%20deep%20lear.md)
- PMID 39223152: [Deep learning-based virtual staining, segmentation, and classification in label-free photoacoustic histology of human specimens.](method_summaries/PMID_39223152_Deep%20learning-based%20virtual%20staining%2C%20segmentation%2C%20and%20classification%20in%20label-free%20photoacoustic%20histology%20of%20human%20sp.md)
- PMID 39636222: [Autofluorescence Virtual Staining System for H&E Histology and Multiplex Immunofluorescence Applied to Immuno-Oncology Biomarkers in Lung Cancer.](method_summaries/PMID_39636222_Autofluorescence%20Virtual%20Staining%20System%20for%20H%26E%20Histology%20and%20Multiplex%20Immunofluorescence%20Applied%20to%20Immuno-Oncology%20B.md)
- PMID 40158294: [Artificial intelligence-based virtual staining platform for identifying tumor-associated macrophages from hematoxylin and eosin-stained images.](method_summaries/PMID_40158294_Artificial%20intelligence-based%20virtual%20staining%20platform%20for%20identifying%20tumor-associated%20macrophages%20from%20hematoxylin%20an.md)
- PMID 41118427: [Scalable, trustworthy generative model for virtual multi-staining from H&E whole slide images.](method_summaries/PMID_41118427_Scalable%2C%20trustworthy%20generative%20model%20for%20virtual%20multi-staining%20from%20H%26E%20whole%20slide%20images.md)
- PMID 41888143: [Generative AI for misalignment-resistant virtual staining to accelerate histopathology workflows.](method_summaries/PMID_41888143_Generative%20AI%20for%20misalignment-resistant%20virtual%20staining%20to%20accelerate%20histopathology%20workflows.md)
