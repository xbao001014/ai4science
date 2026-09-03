# 计算病理 MIL 方法短综述（精选版）

**证据范围：** 本总览基于旁系 `D:/agent/mil-method-summary/` 中 62 篇逐篇总结压缩而来；本仓 `selected_papers.jsonl` 精选 15 篇代表方法。**不做跨数据集数值排名。**

## 1. 问题设定

全切片图像（WSI）在 slide 级仅有弱标签（诊断、分级、生存等），patch 级标签通常未知。多实例学习（MIL）将每张 WSI 视为一个 bag、每个 patch 为 instance，学习置换不变的 bag 级表示并完成下游预测。计算病理 MIL 的核心张力在于：**关键区域定位、长序列计算、空间上下文、噪声弱标签与域偏移**。

## 2. 四阶段演进

### 阶段 1：注意力与聚类（基线范式）

- **AB-MIL** 用可训练注意力实现 bag 聚合，使 WSI 分类从黑盒走向关键 patch 白盒定位，成为后续病理 MIL 的事实基线。
- **CLAM** 在注意力之外引入高/低注意力 patch 的伪标签聚类，显著提升弱监督下的数据效率与实例级判别力。
- **DTFD-MIL** 进一步推导 instance 级概率，指出其比 attention score 更适合阳性区域定位；对 Ki67/IHC 代理任务有方法论参考价值。
- **ADD-MIL** 将 bag 头重构为实例特征线性加和，提供与 Shapley 等价的内在可解释性。

**选用建议：** 需要可解释基线或快速验证 WSI 弱监督可行性时，优先 AB-MIL / CLAM；需要 instance 级定位精度时参考 DTFD。

### 阶段 2：图与空间上下文

- **Patch-GCN** 将 patch 按物理邻近性构图，用 GCN 聚合局部空间上下文，适合 survival 与 TME 空间结构敏感任务。
- **WiKG** 用动态知识图与三元组注意力建模 instance 交互，克服固定邻域图的局限。

**选用建议：** NPC 等富含淋巴细胞浸润与空间异质性的癌种，可优先考虑图/上下文 MIL 而非纯无序池化。

### 阶段 3：长序列高效建模

- **TransMIL** 以 Nystrom 近似 Transformer 与 PPEG 处理长 patch 序列，是 Transformer-MIL 的代表。
- **Long-MIL** 通过 2d-ALiBi 与 FlashAttention 做长度外推，缓解显存瓶颈。
- **MambaMIL** 以 SR-Mamba 实现线性复杂度长序列建模，代表 SSM 路线。

**选用建议：** bag 极大（>10k patches）时优先 MambaMIL / Long-MIL；需要成熟生态与热图解释时可先 TransMIL。

### 阶段 4：鲁棒性、自监督与基础模型

- **Campanella et al.** 用 Top-K 放松严格 MIL 假设，展示超大规模弱监督可达临床级检测，是理解 MIL 假设演进的基础。
- **DSMIL** 将 SimCLR 自监督与双流聚合结合，缓解正负样本不平衡。
- **IBMIL / CIMIL** 分别针对 bag 级混淆与 instance 伪标签噪声，代表鲁棒训练路线。
- **Prov-GigaPath** 与 **R²T** 代表「更强 encoder / 在线重嵌入 + 传统 MIL 头」的两条抬升路径。

**选用建议：** 多中心染色差异或标签噪声明显时看 IBMIL/CIMIL/DSMIL；已有 UNI/GigaPath 特征时，MIL 头选型仍重要但上游 encoder 贡献显著。

## 3. 横向比较（定性）

| 维度 | 注意力/聚类 | 图/上下文 | 长序列 | 鲁棒/基础模型 |
|------|-------------|-----------|--------|---------------|
| 可解释热图 | 强 | 中–强 | 中–强 | 取决于头设计 |
| 超长 WSI | 中 | 中 | 强 | 强（GigaPath） |
| 空间结构 | 弱–中 | 强 | 中 | 中 |
| 实现复杂度 | 低 | 中–高 | 中–高 | 中–高 |

## 4. 与三主题 review 的衔接

- **NPC 病理 AI：** 38959144（WS-T2T-ViT）、33403013/39249584（pathomics）等已采用 MIL/弱监督 WSI 思路；TIL 定量工作可对照 DTFD/CLAM 的 instance 定位叙事。
- **HE→Ki67/IHC：** 40256728 等直接预测 IHC 状态的工作常用 MIL 聚合 patch；虚拟染色后可接 MIL 做 slide 级 labeling index。
- **方法选型起点：** 基线 AB-MIL/CLAM → 任务需要空间上下文加 Patch-GCN → bag 过大加 MambaMIL → 多中心噪声加 IBMIL/CIMIL。

## 5. 索引

完整 62 篇逐篇总结与长综述见：`D:/agent/mil-method-summary/MIL_methods_overview.md`  
本仓精选清单：`selected_papers.jsonl`
