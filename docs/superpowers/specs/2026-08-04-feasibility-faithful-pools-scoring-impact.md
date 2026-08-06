# Impact: API-Faithful Pools → Idea Critic & Proposal Difficulty Scores

**Date:** 2026-08-04  
**Status:** Analysis (follow-up to implementation)  
**Related spec:** `2026-08-04-feasibility-api-faithful-pools-design.md`  
**Code today:** `idea_agent.py` (Critic accept + prompts), `analysis/difficulty_scoring.py` (`fangxin_tier`), `config.py` thresholds

## Verdict

**有影响。** 忠于接口后，`feasibility_score` / `available_cohort_size` 的数值分布会变；这两项同时喂给：

1. **Idea 提出（Critic）** — LLM 维度分 + 主机强制 `accept` 门闩  
2. **研究报告 / Proposal** — 确定性 `assessed_difficulty` 的 engineering 轴（`fangxin_tier`）

`research_bar`（期刊 Q1 / IF）**不受**本改动直接影响。  
公开数据集 V-03 / `apply_public_relief` **不**改公式，但会更常被用来「救济」变差的方信 tier。

---

## 今日耦合（改动前）

### Idea Critic（`idea_agent`）

| 机制 | 规则 | 输入 |
|------|------|------|
| Prompt 软约束 | `feasibility_score < 0.5` → `technical_feasibility ≤ 5` 且 `accept=false` | Critic 读 V-01 |
| Prompt 软约束 | `score ≥ 0.8` 且 `cohort ≥ 500` → 可写 “Fangxin data feasible” | 同上 |
| 主机硬门闩 | `feas_for_accept < FEASIBILITY_SCORE_MARGINAL (0.5)` → 强制 `accept=False` | 工具/ Critic 回传的 score |
| `overall_score` (0–10) | LLM 自评，受上述约束牵引 | 间接依赖 V-01 |

未验证字段、`patient_list_coverage`：**当前未读入** accept / Critic JSON schema。

### Proposal 实现难度（`difficulty_scoring.fangxin_tier`）

```
easy:     score ≥ 0.8 AND cohort ≥ 500
moderate: score ≥ 0.5 OR  cohort ≥ 200
hard:     otherwise
engineering_bar = fangxin_tier  (+ 可选 public 降一档)
assessed_difficulty = max(research_bar, engineering_bar)
```

难度 **不** 挡 Critic `accept`（仅 UI / Markdown 标注）。

---

## 忠于接口后，数字会怎么变（相对今日估算/floor）

以 C_CA 类缓存为例（医院合计 ~2709，列表 ~560，TNM 观测 1，生存/随访原为比例估算）：

| 假说要求 | 今日（估算/floor） | 忠于接口后 | 对评分的方向 |
|----------|-------------------|------------|--------------|
| 仅 WSI | 起点 560，score≈1 | 起点 `cohort_base` 2709，score≈1，cohort 更大 | Idea 更易达 “≥500”；difficulty 更易 `easy` |
| 要 OS / 随访 | 用 2302/2031 估算，`min` 后仍较大 | **不进 min**，进 `unverified_requirements`；cohort 常接近 base | score/cohort **偏乐观**（条件未验证却不减分） |
| 要 TNM（观测=1） | floor 抬到 ~0.9×N，score 仍高 | `min(..., 1)` → score≈0 | Idea **更难 accept**；engineering → **hard** |
| 要肿瘤区域（观测=0） | floor ~0.8×N | observed 0 → cohort 0 | 同上，更严 |

结论：不是单向变严或变松，而是 **稀疏标注变严、无接口标签变「假松」（不扣分只挂未验证列表）**。

---

## 对 Idea 评分的影响

1. **硬门闩更敏感于稀疏标注**：真实 TNM=1 会使 `feasibility_score < 0.5` → 强制不接受，即使医院有两千多例。  
2. **无生存/随访接口时反而可能更容易 accept**：OS 不再压低 score；若假说仍写 OS，主机仍可能因高 score 放行（与「忠于接口、标明缺口」的产品意图不一致）。  
3. Critic `overall_score` 会随 V-01 文案变化漂移，但无新字段时模型不知道「未验证」。

### 建议后续改动（Idea）

按优先级：

1. **把 `unverified_requirements` / `patient_list_coverage` 写入 Critic 工具结果与 JSON schema**（必读字段）。  
2. **Prompt**：未验证项 ≠ 已满足；不得仅因高 `feasibility_score` 宣称 Fangxin 可行。  
3. **主机门闩（推荐产品二选一，实现前再定）**  
   - **A（严）**：`unverified_requirements` 非空 → 不得 `accept`（或最高 `overall_score` 封顶 &lt; accept 线）。  
   - **B（宽，贴近当前 faithful 规格选项 A）**：允许 accept，但强制 `data_feasibility_verification` 列出未验证项；UI 黄标。  
4. 「Fangxin data feasible」改为同时要求：`score/cohort` 门槛 **且** `unverified_requirements` 为空（或仅允许白名单无关项）。

---

## 对研究报告（Proposal difficulty）评分的影响

1. **`research_bar`：无直接影响。**  
2. **`engineering_bar` / `assessed_difficulty`：有直接影响**，因 `fangxin_tier(feasibility_score, available_cohort_size)`。  
3. **风险**：`cohort_base` 变大 → 仅靠 `cohort ≥ 200/500` 的 OR 分支更容易 `moderate`/`easy`，即使列表覆盖率低、标注实测很差。  
4. **风险**：生存类未验证时 score 虚高 → engineering 偏 `easy`，与真实落地难度不符。  
5. Public relief 可能更频繁触发（方信变 hard 时），proposal 文案更依赖公开集——需与 Fangxin-first 规则一起看。

### 建议后续改动（Difficulty）

1. **`fangxin_tier` 增加输入**：`unverified_count` 或 `data_confidence ∈ {full, partial, unknown}`。  
   - 例：`unverified_count > 0` 时，最高只给 `moderate`（或禁止 `easy`）。  
2. **Easy 门槛加覆盖率**：`enumerated / catalog_total ≥ τ`（如 0.5）或 `enumerated ≥ 500`，避免只用医院合计凑 `cohort ≥ 500`。  
3. **Breakdown / summary_line** 展示 `unverified_requirements` 与 coverage，UI 难度芯片旁加「数据置信度」。  
4. **不**建议为补偿稀疏标注而恢复 floor；若产品要「可研但数据薄」，用显式 `partial` 档，而不是假数字。

---

## 建议落地顺序（实现 faithful pools 之后）

| 步 | 内容 | 阻塞？ |
|----|------|--------|
| 1 | 实现 API-faithful pools（主规格） | — |
| 2 | 工具/UI 透出 `unverified_*` + coverage | 评分改造前置 |
| 3 | Critic prompt + schema | Idea 语义正确 |
| 4 | 选定 accept 门闩 A 或 B 并改 `idea_agent` | Idea 硬行为 |
| 5 | 扩展 `fangxin_tier` / difficulty breakdown | Proposal 标注正确 |
| 6 | 回归：C_CA 仅 WSI / +OS 未验证 / +TNM=1 三组 golden | 防回退 |

本文件 **不** 改变主规格中「未验证不参与 min」的决定；只记录对评分层的连带影响与后续选项。

## Out of scope here

- 修改 `FEASIBILITY_SCORE_*` / `DIFFICULTY_FX_*` 数值本身（可在步 4–5 一并评审）  
- Gap 文献分、跨病种 priority（不读 V-01 pools）  
- V-03 公开数据集打分公式
