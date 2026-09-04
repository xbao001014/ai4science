"""Build the P1 non-expert optimization report and evidence bundle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from db.schema import db_stats


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def esc(value) -> str:
    return html.escape(str(value))


def table(headers, rows) -> str:
    head = "".join(f"<th>{esc(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in row) + "</tr>" for row in rows)
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


CSS = """
:root{--ink:#17211d;--muted:#65736c;--paper:#f7f4ed;--card:#fffdfa;--line:#d8d4ca;--green:#126c52;--blue:#335c81;--amber:#a66008;--red:#9e3f32}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 Inter,"Microsoft YaHei",system-ui,sans-serif}header{padding:72px max(5vw,32px) 56px;background:linear-gradient(125deg,#102b24,#183d33 55%,#315b4d);color:#fff}header .eyebrow{letter-spacing:.18em;text-transform:uppercase;color:#b9dbcf;font-size:12px}h1{font:700 clamp(36px,6vw,72px)/1.05 Georgia,"Noto Serif SC",serif;margin:.3em 0}header p{max-width:850px;color:#d8e8e1;font-size:19px}nav{position:sticky;top:0;z-index:2;padding:12px 5vw;background:#fffefbe8;backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}nav a{color:var(--ink);text-decoration:none;margin-right:22px;font-size:14px}main{max-width:1180px;margin:auto;padding:48px 28px 80px}.section{margin:0 0 64px}.kicker{color:var(--green);font-size:12px;letter-spacing:.14em;text-transform:uppercase}.section h2{font:700 32px/1.2 Georgia,"Noto Serif SC",serif;margin:.3em 0 .8em}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;box-shadow:0 8px 28px #23372d0b}.metric{font:700 32px/1.2 Georgia,serif;color:var(--green);margin:.15em 0}.small{font-size:13px;color:var(--muted)}.table-wrap{overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:14px}table{border-collapse:collapse;width:100%;min-width:700px}th,td{padding:13px 16px;text-align:left;border-bottom:1px solid #e8e4dc;vertical-align:top}th{background:#edf3ef;color:#29463c;font-size:13px}.ok{color:var(--green);font-weight:700}.warn{color:var(--amber);font-weight:700}.bad{color:var(--red);font-weight:700}.note{border-left:4px solid var(--amber);background:#fff6e7;padding:16px 20px;border-radius:0 10px 10px 0;margin:20px 0}code,pre{font-family:"Cascadia Code",Consolas,monospace}pre{overflow:auto;background:#14211d;color:#d6ebe3;padding:20px;border-radius:12px}a{color:var(--blue)}footer{padding:30px 5vw;background:#e9e5db;color:var(--muted)}ul{padding-left:22px}@media(max-width:640px){header{padding-top:48px}main{padding-inline:18px}.section h2{font-size:27px}}
"""


def section(kicker: str, title: str, body: str, sid: str) -> str:
    return f"<section class='section' id='{sid}'><div class='kicker'>{esc(kicker)}</div><h2>{esc(title)}</h2>{body}</section>"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    broad_fail = load(args.runs / "final" / "results.json")
    enforce_fail = load(args.runs / "final-v3" / "results.json")
    offline = load(args.runs / "final-v4" / "results.json")
    live_before = load(args.runs / "live-chain" / "results.json")
    live_after = load(args.runs / "live-chain-v2" / "results.json")
    corpus = db_stats()
    live_before_failure = next(c for c in live_before["checks"] if not c["passed"])
    final_event = next(e for e in reversed(live_after["events"]) if e.get("type") == "final")

    group_rows = []
    for name, label in (
        ("fulltext", "全文抽取流水线"),
        ("retrieval", "检索、截止时间与反证通道"),
        ("handoff", "Scout→Skeptic→Moderator 交接"),
        ("agent_contract", "工具与提示词契约"),
    ):
        metric = offline["metrics"]["groups"][name]
        group_rows.append([label, f"<span class='ok'>{metric['passed']}/{metric['total']}</span>", "synthetic silver / offline"])

    body = section("01 / outcome", "P1 已完成：工程可测性与链路约束", f"""
<div class='cards'>
  <div class='card'><div class='small'>冻结 P1 门禁</div><div class='metric'>0/5 → 5/5</div><div class='small'>同一组失败用例，修改前后</div></div>
  <div class='card'><div class='small'>扩展离线断言</div><div class='metric'>{offline['metrics']['passed']}/{offline['metrics']['total']}</div><div class='small'>临时库，网络调用 0</div></div>
  <div class='card'><div class='small'>真实三角色链路</div><div class='metric'>{live_before['metrics']['passed']}/7 → {live_after['metrics']['passed']}/7</div><div class='small'>只测结构与出处</div></div>
  <div class='card'><div class='small'>链路模型请求</div><div class='metric'>{live_before['requests']} → {live_after['requests']}</div><div class='small'>单轮、top‑2；非延迟基准</div></div>
</div>
<div class='note'><strong>按本轮范围明确排除：</strong>没有启动领域专家标注，也没有对研究方向的新颖性、临床价值、可行性或总体质量打分。38/38 与 7/7 只能说明工程契约按当前开发样例执行。</div>
""", "outcome")

    body += section("02 / changes", "系统改动", table(
        ["P1 项", "实现", "失败时行为"],
        [
            ["全文 section 审计", "新增 <code>extraction_audits</code>：source/sent 字符数、截断、解析、后处理、保留数、原因码", "空输出、后处理全删、grounding 全拒绝与异常不再混成一个空结果"],
            ["输入硬上限", "截断标记被计入上限；记录实际发送长度", "避免配置为 N 字符却实际发送 N+marker"],
            ["Pass 2 grounding", "survey/cover/limitation/binding/recommendation 的 quote 必须在某个原始 section 定位；保存 section 与 offset", "未定位行不落库；拒绝原因写入 reconcile audit"],
            ["证据检索", "新增 <code>literature_evidence_search</code>：逐条 PMID+quote+year、focus、top_k、cutoff、snapshot、evidence_role", "空结果只表示 <code>in_corpus_only</code>；不能推出全球空白"],
            ["检索精度门槛", "长查询至少命中两个不同词项；机会证据与已完成工作反证分通道", "单一泛词命中不进入 top‑k"],
            ["候选交接", "Reviewer 分类形成 verified allowlist；最终 gap 必须带 Candidate ID", "Moderator 重新提升 false/weak 或漏 ID 时，运行时删除该 section 并留审计"],
            ["重复工具证据", "同一角色重复调用不再覆盖 ledger，使用 tool、tool#2… 保留", "多候选检索证据可以全部回放"],
        ],
    ), "changes")

    body += section("03 / offline", "离线评测：全文、检索、交接", table(["评测组", "结果", "标签/环境"], group_rows) + f"""
<p>检索 fixture 包含同疾病相关证据、截止时间后的论文、异病种干扰项和已完成工作的反证。两条查询的集合级 precision={next(c['observed'] for c in offline['checks'] if c['name']=='two_query_precision'):.1f}、recall={next(c['observed'] for c in offline['checks'] if c['name']=='two_query_recall'):.1f}。这些值来自可见合成开发集，不是对 9,713 篇真实库的无偏估计。</p>
<p>生产库快照只用于真实链路的只读工具调用：papers={corpus['papers']:,}，extracted={corpus['extracted']:,}，fulltext_available={corpus['fulltext_available']:,}。离线断言全部使用临时 SQLite。</p>
""", "offline")

    body += section("04 / failures", "保留的失败版本与修复依据", table(
        ["版本", "结果", "暴露的问题", "修复"],
        [
            ["修改前冻结门禁", "<span class='bad'>0/5</span>", "截断不可见、无 audit 表、Pass 2 无 quote hard gate、无截止检索、可重新提升候选", "建立五条运行时契约"],
            ["P1 retrieval v1", f"<span class='warn'>{broad_fail['metrics']['passed']}/{broad_fail['metrics']['total']}</span>", "只命中 breast 的 CLAM 分类论文进入 segmentation validation top‑3", "长查询至少两个不同词项命中"],
            ["handoff guard 可见但未执行", f"<span class='warn'>{live_before['metrics']['passed']}/{live_before['metrics']['total']}</span>", esc(live_before_failure['observed']['issues'][0]), "verified allowlist 自动过滤最终 gap section"],
            ["allowlist enforcement 初版", f"<span class='warn'>{enforce_fail['metrics']['passed']}/{enforce_fail['metrics']['total']}</span>", "评测错误地把审计通知中的 G02 当成未删除内容", "断言收窄到 Candidate ID 字段，保留通知"],
            ["P1 最终", f"<span class='ok'>{offline['metrics']['passed']}/{offline['metrics']['total']}；{live_after['metrics']['passed']}/{live_after['metrics']['total']}</span>", "最终 handoff issues=[]", f"运行时移除 {', '.join(final_event['handoff_enforcement']['removed_candidate_ids']) or 'none'}；保留 {', '.join(final_event['handoff_audit']['promoted_candidate_ids']) or 'none'}"],
        ],
    ), "failures")

    body += section("05 / live", "真实模型链路：测行为，不测研究价值", f"""
{table(['指标','第一次','执行约束后'], [
['结构通过', f"{live_before['metrics']['passed']}/{live_before['metrics']['total']}", f"<span class='ok'>{live_after['metrics']['passed']}/{live_after['metrics']['total']}</span>"],
['模型请求', str(live_before['requests']), str(live_after['requests'])],
['工具调用', str(live_before['tool_calls']), str(live_after['tool_calls'])],
['Moderator handoff', "needs_verification：G01 被重新提升", "handoff_checked；issues=[]"],
['运行时动作', "只标记整份报告待验证", f"删除 {', '.join(final_event['handoff_enforcement']['removed_candidate_ids'])}，allowlist={', '.join(final_event['handoff_enforcement']['verified_allowlist'])}"],
])}
<p>两次均为 breast cancer、单轮、top‑2。Skeptic 实际调用了 <code>literature_evidence_search</code>，并带 query、focus、top_k、cutoff_year。一次运行不足以估计模型稳定率；这里证明的是失败能被检测并确定性阻断。</p>
""", "live")

    body += section("06 / regression", "回归与未解决项", f"""
{table(['验证','结果','解释'], [
['P1 专项 pytest', '<span class="ok">5/5</span>', '修改前同组为 0/5'],
['P0/P1/关键链路选择集', '<span class="ok">69/69</span>', '抽取、reconcile、agent 工具约束与 P1 门禁'],
['全量 fulltext_workflow/tests', '<span class="warn">605/609</span>', '4 项失败；P1 相关新增测试均通过'],
['生产知识库写入', '0', '真实链路仅调用只读分析工具；表迁移只在临时库执行'],
])}
<p>全量 4 个失败中，3 个是前一报告已记录的 <code>vital_status</code> 与 canonical <code>death_event</code> 断言；另 1 个是 <code>test_stream_emits_difficulty_once_and_enriches_final</code> 的 feasibility_score 为空。它不在本轮 P1 修改路径，但本轮没有全量“修改前”重跑，因此不把它无证据地称为既有失败。</p>
""", "regression")

    body += section("07 / limits", "解释边界与后续门禁", """
<ul>
<li>没有领域专家 gold，不能声称真实全文关系 precision/recall、研究空白真假或方向价值已验证。</li>
<li>离线全文评测重点是 section 选择、截断可见性、Pass 2 grounding 与落库审计；LLM 语义抽取沿用 P0 的片段级实模评测，没有伪造新的全文专家标签。</li>
<li>检索 precision/recall 来自小型 synthetic silver corpus；下一步应在不做方向价值标注的前提下，建立真实 PMID 的检索 relevance pool。</li>
<li>真实链路仅各跑一次，13/15 次请求不是性能或成本结论，也未读取账单。</li>
<li>代码未提交、部署或重抽生产库；新增 schema 将在未来显式执行 <code>init_db</code> 时迁移。</li>
</ul>
<p>方法依据：<a href='https://developers.openai.com/api/docs/guides/evaluation-best-practices'>OpenAI 官方 Evaluation best practices</a>强调代表性样本、典型/边界/对抗用例、持续评测与将失败保留在分母。本轮采用同样思路，但明确停在工程契约层。</p>
""", "limits")

    body += section("08 / reproduce", "复现与证据", r"""
<pre>.venv\Scripts\python.exe -m pytest fulltext_workflow\tests\test_p1_quality.py -q
.venv\Scripts\python.exe fulltext_workflow\evals\run_p1_eval.py --output tmp\p1-final
.venv\Scripts\python.exe fulltext_workflow\evals\run_p1_chain_eval.py --output tmp\p1-live --focus "breast cancer" --top-n 2</pre>
<p><a href='paper-quality-p1-evidence.zip'>下载完整证据包</a> · <a href='paper-quality-p1-manifest.json'>查看哈希清单</a> · <a href='paper-quality-p0.html'>上一阶段 P0 报告</a></p>
""", "reproduce")

    report = args.output / "paper-quality-p1.html"
    report.write_text(f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>P1 非专家质量优化报告</title><style>{CSS}</style></head><body><header><div class='eyebrow'>P1 ENGINEERING QUALITY · 2026-09-04</div><h1>让全文、检索与交接<br>成为可回放的工程质量</h1><p>暂停领域专家标注与研究方向价值评分，完成其余 P1：全文端到端可观测、逐条出处检索、反证通道与三角色候选交接硬门禁。</p></header><nav><a href='#outcome'>结论</a><a href='#changes'>改动</a><a href='#offline'>离线评测</a><a href='#failures'>失败版本</a><a href='#live'>真实链路</a><a href='#limits'>边界</a></nav><main>{body}</main><footer>P1 本地可审计报告 · 工程契约通过不等于科研方向质量通过</footer></body></html>""", encoding="utf-8")

    source_files = [
        "../llm_utils.py", "db/schema.py", "extractor/section_extractor.py",
        "extractor/fulltext_reconcile.py", "analysis/gap_tools.py",
        "analysis/research_quality.py", "gap_agent.py", "evals/run_p1_eval.py",
        "evals/run_p1_chain_eval.py", "tests/test_p1_quality.py",
    ]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": report.name,
        "scope": "P1 excluding domain-expert annotation and research-direction quality",
        "label_tier": "synthetic_silver_development_plus_live_structural_smoke",
        "models": {"agent": config.LLM_MODEL_AGENT},
        "metrics": {
            "frozen_gate_before_after": [[0, 5], [5, 5]],
            "offline_final": offline["metrics"],
            "live_before": live_before["metrics"],
            "live_after": live_after["metrics"],
            "selected_regression": [69, 69],
            "full_regression": [605, 609],
        },
        "corpus_snapshot": {k: corpus[k] for k in ("papers", "extracted", "fulltext_available", "relations_fulltext")},
        "production_db_mutations": 0,
        "source_sha256": {
            name: sha((ROOT / name).resolve()) for name in source_files
        },
        "artifact_qa": "pending_static_validation",
    }
    manifest_path = args.output / "paper-quality-p1-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence = args.output / "paper-quality-p1-evidence.zip"
    with zipfile.ZipFile(evidence, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(args.runs.rglob("*")):
            if file.is_file():
                archive.write(file, "runs/" + file.relative_to(args.runs).as_posix())
        for name in source_files:
            archive.write((ROOT / name).resolve(), "source/" + name.replace("../", ""))
        archive.write(report, report.name)
        archive.write(manifest_path, manifest_path.name)
    print(json.dumps({"report": str(report), "manifest": str(manifest_path), "evidence": str(evidence), "metrics": manifest["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
