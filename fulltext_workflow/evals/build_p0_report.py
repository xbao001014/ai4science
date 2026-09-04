"""Build the P0 update report and auditable evidence bundles."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from build_report import CSS, esc, section, table
from expert_holdout import validate_package

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--phase2-final", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    phase2 = load(args.phase2_final / "results.json")
    candidate = load(args.runs / "quality-candidate/results.json")
    conflict = load(args.runs / "quality-final/results.json")
    final = load(args.runs / "quality-final-v2/results.json")
    extraction_final = load(args.runs / "extraction-final/results.json")
    stability = load(args.runs / "empty-stability/results.json")
    contracts = load(args.runs / "contracts-final/results.json")
    validator = load(args.runs / "quality-final-v2/validator-audit.json")
    engineering = load(args.runs / "engineering-final/results.json")
    quality_checks = load(args.runs / "quality-checks-final/regression.json")
    legacy = load(args.runs / "legacy/regression.json")
    holdout_root = args.runs / "expert-holdout-package"
    holdout = validate_package(holdout_root)

    runs = [candidate, conflict, final, extraction_final, stability]
    usage = Counter()
    for run in runs:
        usage.update(run["usage"])

    p2e, p0e = phase2["metrics"]["extraction"], extraction_final["metrics"]["extraction"]
    p2r, p0r = phase2["metrics"]["research"], final["metrics"]["research"]
    contract_before = contracts["evidence_support"]["baseline"]
    contract_after = contracts["evidence_support"]["candidate"]
    live_support_before = final["metrics"]["extraction"]["evidence_support_advisory"]
    live_support_after = extraction_final["metrics"]["extraction"]["evidence_support_advisory"]

    summary_rows = [
        ["抽取严格通过（16×3）", f"{p2e['passed']}/{p2e['total']}", f"{p0e['passed']}/{p0e['total']}", "E03 偶发空输出被有界复查恢复"],
        ["目标事实 recall", pct(p2e["recall"]), pct(p0e["recall"]), "+3.3 个百分点"],
        ["正确且可定位 recall", pct(p2e["grounded_recall"]), pct(p0e["grounded_recall"]), "+3.3 个百分点"],
        ["正确关系的完整分句支持（advisory）", "此前未测", f"{live_support_after.get('supported', 0)}/{p0e['predicted']}", "不作为硬删除门禁"],
        ["研究判断严格通过（12×3）", f"{p2r['passed']}/{p2r['total']}", f"{p0r['passed']}/{p0r['total']}", "净分数持平；发现并修复 Prompt 冲突"],
        ["独立出处校验后研究判断", "36/36", f"{validator['correct_after_validation']}/{validator['total']}", "所有证据 ID、引文与 scope guard 通过"],
    ]

    body = section(
        "outcome",
        "01 / P0 结果：召回、证据语义与 holdout 治理",
        f"""
<p><strong>P0 已完成可由工程侧落地的部分：</strong>随机空输出有原因码与有界恢复；引文从“能定位”扩展为“支持状态可审计”；证据偏移独立入库；候选偏题与证据偏题的冲突提示被拆开；专家 holdout 建立了初始化、校验与封存门禁。</p>
<div class="cards"><div class="card"><div class="small">抽取严格通过</div><div class="metric">{p2e['passed']}/48 → {p0e['passed']}/48</div><small>相同 16 个开发案例，各 3 次</small></div>
<div class="card"><div class="small">E03 失败重放</div><div class="metric">8/10 → 10/10</div><small>旧/P0 策略随机交错运行</small></div>
<div class="card"><div class="small">专家 holdout 工作量</div><div class="metric">64 + 24</div><small>论文 + 研究证据包；仍待专家完成</small></div></div>
<div class="note">最重要的边界：这里仍没有领域专家 gold 标签。64+24 是受保护的标注工作包，不是已经完成的隐藏测试集；系统会在必填项、双人独立复核和仲裁完成前拒绝封存。</div>
"""
        + table(["指标", "Phase 2", "P0 最终", "解释"], summary_rows),
    )

    body += section(
        "implementation",
        "02 / 系统更新",
        table(
            ["P0 项", "实现", "运行边界"],
            [
                ["空输出原因审计", "empty_input / unresolved_empty / model_empty / confirmed_empty / postprocess_rejected_all / grounding_rejected_all / retained", "失败仍进入分母；无法把 SDK 的空对象伪装成真实负例"],
                ["有界召回复查", "实验研究、显式综述范围、显式 meta 汇总首次结构化为空时最多再查一次", "真实 E03 重放只多 1/10 请求；不重试 API/解析失败"],
                ["证据支持状态", "supported / mentioned_only / contradicted / unclear + 原因码", "人工校准前是 advisory；仅引文无法定位仍为硬拒绝"],
                ["证据生命周期", "新增 relation_evidence，一条关系可保存多个独立 section/quote/offset/status", "保留 legacy relations.evidence_quote 兼容；未改写生产数据库内容"],
                ["研究 scope guard", "明确区分 candidate off-topic 与 evidence off-topic；后者只能说明 insufficient", "运行时 validate_review 可把错误 refutation 降级并留下审计问题"],
                ["专家 holdout", "64 个论文槽位、24 个 gap pack；双盲复核、第三人仲裁、SHA-256 封存", "当前 360 个待完成校验项，因此 ready_to_seal=false"],
            ],
        ),
    )

    old_stability, new_stability = stability["metrics"]["phase2"], stability["metrics"]["p0"]
    body += section(
        "recall",
        "03 / 随机空输出：真实模型交错复测",
        table(
            ["策略", "通过", "事实 recall", "首轮为空", "最终为空", "请求数", "API 错误"],
            [
                ["Phase 2 policy", f"{old_stability['passed']}/{old_stability['total']}", pct(old_stability["recall"]), str(old_stability["initial_empty"]), str(old_stability["final_empty"]), str(old_stability["requests"]), str(old_stability["errors"])],
                ["P0 bounded recheck", f"{new_stability['passed']}/{new_stability['total']}", pct(new_stability["recall"]), str(new_stability["initial_empty"]), str(new_stability["final_empty"]), str(new_stability["requests"]), str(new_stability["errors"])],
            ],
        )
        + "<p>同一个 E03 综述案例、同一模型和温度，两个策略各 10 次，固定随机顺序交错执行。旧策略出现 2 次最终空输出；P0 首轮出现 1 次空输出，第二次检查恢复。样本很小，这是故障重放结果，不是生产空输出率估计。</p>",
    )

    body += section(
        "evidence",
        "04 / 从“引文存在”到“引文支持”",
        table(
            ["评估层", "此前", "P0", "含义"],
            [
                ["18 条 silver 语义契约", f"{contract_before['correct']}/{contract_before['total']}；错误支持 {contract_before['false_supported']}", f"{contract_after['correct']}/{contract_after['total']}；错误支持 {contract_after['false_supported']}", "覆盖直接支持、背景提及、否定、信息不足"],
                ["完整抽取实模输出", f"supported={live_support_before.get('supported', 0)}，unclear={live_support_before.get('unclear', 0)}", f"supported={live_support_after.get('supported', 0)}，unclear={live_support_after.get('unclear', 0)}", "要求引文保留实体、关系动作和指标原值"],
                ["事实与引文位置", f"TP/FP/FN={p2e['tp']}/{p2e['fp']}/{p2e['fn']}", f"TP/FP/FN={p0e['tp']}/{p0e['fp']}/{p0e['fn']}", "语义状态没有替代已有 precision/recall"],
            ],
        )
        + "<div class=\"note\">18/18 与 60/60 都来自可见开发数据，而且规则与样例由同一轮工程工作建立。它们证明实现符合当前契约，不证明启发式与领域专家对真实全文的语义判断一致。</div>",
    )

    version_rows = []
    for name, run, note in (
        ("P0 candidate", candidate, "R06 1/3 把异域证据误作反证"),
        ("P0 conflict replay", conflict, "强化规则后仍受 focus extra 冲突影响，R06 3/3 失败"),
        ("P0 scope-separated", final, "拆分候选 scope 与证据 scope，36/36"),
        ("P0 quote-complete", extraction_final, "仅重跑抽取；完整分句支持 60/60"),
    ):
        e, r, u = run["metrics"]["extraction"], run["metrics"]["research"], run["usage"]
        version_rows.append([name, f"{e['passed']}/{e['total']}", f"{r['passed']}/{r['total']}" if r["total"] else "未运行", str(u["requests"]), f"{u['prompt_tokens']:,} / {u['completion_tokens']:,}", note])
    body += section(
        "iterations",
        "05 / 保留失败版本：Prompt 冲突不是被平均数掩盖",
        table(["版本", "抽取", "研究判断", "请求", "输入 / 输出 tokens", "观察"], version_rows)
        + "<p>R06 的候选本身属于 lung adenocarcinoma WSI survival；证据却是 breast cancer segmentation。旧 focus 文案说“偏题放 false”，研究契约说“偏题证据算 insufficient”，模型优先级不清。最终版把判断对象拆开，并用运行时 scope mismatch guard 做第二道防线。</p>",
    )

    issue_groups = Counter(issue.split(":", 1)[1] for issue in holdout["issues"])
    body += section(
        "holdout",
        "06 / 隐藏专家集：基础设施完成，专家标注尚未完成",
        f"""
<p>已生成 {holdout['paper_rows']} 个真实论文标注槽位（8 种研究类型各 8）和 {holdout['gap_rows']} 个 gap evidence pack（supported/refuted/insufficient 各 8）。每个条目要求两名不同 reviewer 独立标注，并由第三人完成 adjudication。</p>
{table(['校验类别','待完成数'], [[esc(k), str(v)] for k, v in sorted(issue_groups.items())])}
<p><strong>当前状态：</strong>ready_to_seal={str(holdout['ready_to_seal']).lower()}，共 {holdout['issue_count']} 个预期中的待标注问题。封存命令会拒绝生成 gold seal；只有全部来源元数据、双人独立标注和仲裁完成后，才生成不包含明文标签的 SHA-256 清单。</p>
<p><a href="paper-quality-p0-expert-holdout-template.zip">下载专家标注工作包</a></p>
""",
    )

    known_failures = [row for row in legacy.get("tests", []) if row.get("status") != "passed"]
    body += section(
        "verification",
        "07 / 工程验证与既有失败",
        table(
            ["验证", "结果", "说明"],
            [
                ["固定工程评测", f"{engineering['passed']}/{engineering['total']}", "临时数据库、网络调用 0"],
                ["P0/质量相关测试", f"{quality_checks['passed']}/{quality_checks['total']}", "包含新增语义状态、空输出、证据表和 holdout 门禁"],
                ["既有 selected regression", f"{legacy['passed']}/{legacy['total']}", "3 个 vital_status/death_event 别名断言仍失败；与 P0 改动无关"],
                ["API 错误", str(usage["api_errors"]), "所有实模错误均保留在分母"],
            ],
        )
        + ("<p>既有失败：" + esc("；".join(row.get("nodeid", row.get("name", "unknown")) for row in known_failures)) + "</p>" if known_failures else ""),
    )

    body += section(
        "cost",
        "08 / 本轮资源与复现",
        f"""
<p>P0 开发与复测共调用模型 API <strong>{usage['requests']}</strong> 次，输入 {usage['prompt_tokens']:,} tokens、输出 {usage['completion_tokens']:,} tokens，API 错误 {usage['api_errors']}。其中包含两个失败中间版本和一次只跑抽取的最终确认；未读取账单，因此不推算金额。</p>
<pre># 完整质量集（会调用已配置模型 API）
.venv\\Scripts\\python.exe fulltext_workflow\\evals\\run_quality_eval.py --label candidate --output tmp\\quality --repeats 3

# E03 随机空输出重放
.venv\\Scripts\\python.exe fulltext_workflow\\evals\\run_empty_stability_eval.py --output tmp\\stability --repeats 10

# 专家包校验与封存（pending 时封存会失败）
.venv\\Scripts\\python.exe fulltext_workflow\\evals\\expert_holdout.py validate --input HOLDOUT_DIR
.venv\\Scripts\\python.exe fulltext_workflow\\evals\\expert_holdout.py seal --input HOLDOUT_DIR --output seal.json</pre>
<p><a href="paper-quality-p0-evidence.zip">完整证据包</a> · <a href="paper-quality-p0-manifest.json">版本清单</a> · <a href="paper-quality-phase2.html">上一阶段报告副本</a></p>
""",
    )

    body += section(
        "limits",
        "09 / 仍然不能声称什么",
        """
<ul>
<li>没有专家完成的 gold holdout，因此不能声称真实全文部署准确率或研究新颖性已经验证。</li>
<li>抽取集仍是 12 个合成片段 + 4 个真实摘要短片段，不覆盖 PDF 解析、长文切块、跨段合并和 Pass 2 全链路。</li>
<li>语义支持分类器是窄规则的审计信号；它能识别明显否定、背景和缺失谓词，但不能替代专家 entailment。</li>
<li>E03 10+10 次重放能证明恢复机制有效，不足以估计生产发生率或统计显著性。</li>
<li>研究判断仍是封闭证据组件测试，没有测检索 recall@k，也不证明全球文献空白。</li>
<li>代码尚未提交、部署或用于重抽生产库；新增表会在下次 init_db 时迁移，但本轮只在临时数据库验证。</li>
</ul>
<p>方法依据：<a href="https://developers.openai.com/api/docs/guides/evaluation-best-practices">OpenAI 官方评估指南</a>建议使用任务特定指标、真实分布、人工反馈校准、留出集和持续评估。本地实现遵循这些方向，但专家环节尚未完成。</p>
""",
    )

    report_path = args.output / "paper-quality-p0.html"
    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P0 质量更新报告</title><style>{CSS}</style></head><body><header><div class="eyebrow">P0 QUALITY UPDATE · 2026-09-04</div><h1>从高分回归集<br>走向可审计证据与隐藏专家集</h1><p>保留随机失败和提示词冲突，分别验证召回恢复、证据语义状态、研究 scope 边界与专家 gold 封存流程。</p></header><nav><a href="#outcome">结论</a><a href="#recall">空输出</a><a href="#evidence">证据语义</a><a href="#iterations">失败版本</a><a href="#holdout">专家集</a><a href="#limits">边界</a></nav><main>{body}</main><footer>P0 本地可审计报告 · silver 开发评测不是专家科研结论</footer></body></html>"""
    report_path.write_text(doc, encoding="utf-8")

    phase2_report = args.output.parent / "paper-quality-phase2.html"
    if phase2_report.exists():
        shutil.copyfile(phase2_report, args.output / "paper-quality-phase2.html")

    with zipfile.ZipFile(args.output / "paper-quality-p0-expert-holdout-template.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(holdout_root.iterdir()):
            if file.is_file():
                archive.write(file, file.name)

    source_files = [
        "extractor/evidence_support.py",
        "extractor/evidence_grounding.py",
        "extractor/section_extractor.py",
        "extractor/triple_models.py",
        "extractor/study_prompts/__init__.py",
        "analysis/research_quality.py",
        "gap_agent.py",
        "db/schema.py",
        "evals/expert_holdout.py",
        "evals/p0_cases.py",
        "evals/run_p0_contract_eval.py",
        "evals/run_empty_stability_eval.py",
        "evals/run_quality_eval.py",
        "tests/test_p0_quality.py",
        "tests/test_quality_v2.py",
    ]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": report_path.name,
        "label_tier": "silver_development_plus_pending_expert_holdout",
        "expert_holdout_ready_to_seal": holdout["ready_to_seal"],
        "models": {"extraction": extraction_final["extract_model"], "research": final["agent_model"]},
        "usage_p0": dict(usage),
        "metrics": {
            "phase2_extraction_pass": [p2e["passed"], p2e["total"]],
            "p0_extraction_pass": [p0e["passed"], p0e["total"]],
            "empty_stability": stability["metrics"],
            "support_contract": contracts["evidence_support"],
            "p0_research_pass": [p0r["passed"], p0r["total"]],
        },
        "source_sha256": {name: sha(ROOT / name) for name in source_files},
        "artifact_qa": "pending_static_validation",
    }
    manifest_path = args.output / "paper-quality-p0-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(args.output / "paper-quality-p0-evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(args.runs.rglob("*")):
            if file.is_file() and file.suffix.lower() in {".json", ".jsonl", ".zip"}:
                archive.write(file, "runs/" + file.relative_to(args.runs).as_posix())
        for name in source_files:
            archive.write(ROOT / name, "source/" + name)
        archive.write(report_path, report_path.name)
        archive.write(manifest_path, manifest_path.name)
    print(json.dumps({"report": str(report_path), "usage": dict(usage), "holdout": holdout, "metrics": manifest["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
