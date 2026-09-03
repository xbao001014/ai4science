# H&E → Ki67 / 类似 IHC 预测筛选方案

## 1. 目标

梳理从 H&E 推断 Ki-67 增殖指数或类似 IHC 标志物（HER2、PD-L1、ER/PR 等）的代表方法，区分 **生成式虚拟染色** 与 **非生成式直接预测** 两条技术路线。

## 2. 轨 A：虚拟染色（纳入）

- 输入 H&E，输出具有目标 IHC/功能染色语义的组织图像；
- 评价除像素/结构相似外，须包含标志物阳性区域、labeling index、细胞计数或专家一致性之一；
- 配对（同切片脱色复染）与无配对迁移均纳入，但须在总览中分角色描述。

**Ki-67 优先代表：** PMID 39087085（配对 + labeling index 验证）、PMID 33784619（无配对 PC-StainGAN）。

## 3. 轨 B：非生成式预测（纳入）

- 输入 H&E patch/WSI/ROI，直接输出 Ki67 分数、阳性比例、二分类状态或有序等级；
- 不要求生成 IHC 图像；
- 须明确预测目标与 IHC 真值的对照方式（细胞级、区域级或 slide 级）。

## 4. 排除标准

- 纯 stain normalization / 颜色增强，不服务特定 IHC 标志物；
- 仅从 H&E 预测分子突变而不涉及 IHC 表型代理（除非用户扩展 scope）；
- 综述-only（可作背景，标记 `role: review`，不进核心方法比较）。

## 5. 优先级

- **P0**：Ki-67 直接相关 + 有 labeling index / 阳性细胞 / 分数对照；
- **P1**：其他 IHC（SOX10、CD163、HER2、PD-L1）作为「类似 IHC」扩展；
- **P2**：仅摘要可得或全文未就绪 — 入 `expansion_candidates.jsonl`。

## 6. 评价边界

- 虚拟染色的 SSIM/PSNR **不能替代** labeling index 或专家阅片一致性；
- intraslide 与 cross-case 泛化须分开表述（PMID 39087085 已显示二者差异）；
- 禁止跨数据集 AUC/相关系数排名。
