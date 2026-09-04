"""Offline, network-denied behavioral regression eval. No clinical data or live LLM.

The same cases exercise real orchestration with scripted completions and synthetic tools.
Outputs are measurements of harness reliability, NOT model intelligence or scientific novelty.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import inspect
import io
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent))
CASES = []
TRACE = []


def case(cid, category, title, severity="critical"):
    def register(fn):
        CASES.append((cid, category, title, severity, fn))
        return fn
    return register


def require(ok, detail):
    if not ok:
        raise AssertionError(detail)


def msg(content=None, calls=None):
    tc = [NS(id=f"c{i}", function=NS(name=n, arguments=a if isinstance(a, str) else json.dumps(a)))
          for i, (n, a) in enumerate(calls or [])]
    data = {"role": "assistant", "content": content}
    if tc:
        data["tool_calls"] = [{"id": t.id, "type": "function", "function": {
            "name": t.function.name, "arguments": t.function.arguments}} for t in tc]
    return NS(choices=[NS(message=NS(content=content, tool_calls=tc,
        model_dump=lambda **_: copy.deepcopy(data)), finish_reason="tool_calls" if tc else "stop")])


def schema(name, properties=None):
    return {"type": "function", "function": {"name": name, "description": "Synthetic eval fixture",
        "parameters": {"type": "object", "properties": properties or {}}}}


def loop(tools, replies, **options):
    requests = []
    replies = iter(replies)
    def create(**kwargs):
        requests.append(copy.deepcopy(kwargs))
        return next(replies, msg("# Finished from available evidence"))
    # A baseline lacking an optional contract is exercised as-is, not counted as import error.
    supported = inspect.signature(au.run_tool_agent).parameters
    opts = {k: v for k, v in options.items() if k in supported}
    messages = [{"role": "system", "content": "Synthetic evaluation. Follow the tool contract."}]
    with patch.object(au._client.chat.completions, "create", create):
        events = list(au.run_tool_agent(messages, tools, [schema(n) for n in tools],
                                       role="eval", max_iters=3, **opts))
    TRACE.append({"requests": requests, "events": events, "messages": messages})
    return messages, events


@case("T01", "参数与工具执行", "keyword 包装保留模型指定检索词")
def keyword():
    def tool(keyword): return {"keyword": keyword}
    wrapped = idea.bind_idea_tools({"lookup": tool}, "nasopharyngeal carcinoma survival")
    result = au._safe_invoke_tool(wrapped["lookup"], {"keyword": "nasopharyngeal carcinoma prognostic biomarkers"})
    require(result.get("keyword") == "nasopharyngeal carcinoma prognostic biomarkers", str(result))


@case("T02", "参数与工具执行", "通用 kwargs 工具不丢参")
def kwargs():
    require(au._safe_invoke_tool(lambda **kw: kw, {"disease_id": "TEST-D"}) == {"disease_id": "TEST-D"}, "kwargs 被过滤")


@case("T03", "参数与工具执行", "省略 focus 时注入领域", "normal")
def focus():
    def tool(focus=None): return {"focus": focus}
    wrapped = au.bind_tools_with_focus({"lookup": tool}, "test disease")
    require(au._safe_invoke_tool(wrapped["lookup"], {}) == {"focus": "test disease"}, "未注入")


@case("T04", "参数与工具执行", "畸形 JSON 不得变成空参执行")
def malformed():
    calls = []
    def tool(): calls.append(1); return {"ok": True}
    loop({"lookup": tool}, [msg(calls=[("lookup", "{broken")]), msg("done")])
    require(not calls, "畸形参数被修复为空对象后执行了工具")


@case("T05", "工具预算与前置条件", "单次响应批量调用也受总预算限制")
def total_budget():
    calls = []
    def tool(): calls.append(1); return {"ok": True}
    loop({"lookup": tool}, [msg(calls=[("lookup", {})]*4), msg("done")], max_tool_calls=2)
    require(len(calls) == 2, f"预算 2，实际执行 {len(calls)}")


@case("T06", "工具预算与前置条件", "先覆盖验证后才能调用下游工具")
def prerequisite():
    calls = []
    def tool(): calls.append("downstream"); return {"ok": True}
    loop({"coverage": lambda: {"papers": 23}, "downstream": tool},
         [msg(calls=[("downstream", {})]), msg("done")], first_tool="coverage")
    require(not calls, "未完成覆盖验证就执行下游工具")


@case("T07", "工具预算与前置条件", "SQL 两次成功预算", "normal")
def sql_budget():
    calls = []
    def tool(sql): calls.append(sql); return {"row_count": 1, "data": [{"n": 1}]}
    loop({"execute_kg_sql": tool}, [msg(calls=[("execute_kg_sql", {"sql": "SELECT 1"})]*3), msg("done")], max_sql_calls=2)
    require(len(calls) == 2, str(calls))


@case("T08", "工具预算与前置条件", "未知工具不会执行", "normal")
def unknown():
    _, events = loop({}, [msg(calls=[("invented", {})]), msg("done")])
    require(any(e["type"] == "tool_error" for e in events), "缺少错误事件")


@case("T09", "工具预算与前置条件", "重复工具护栏", "normal")
def duplicate():
    calls = []
    def tool(): calls.append(1); return {"ok": True}
    loop({"lookup": tool}, [msg(calls=[("lookup", {}), ("lookup", {})]), msg("done")], disallow_duplicate_tools=True)
    require(len(calls) == 1, str(calls))


def large_result():
    return {"data": [{"text": "x"*250} for _ in range(30)], "counter_evidence": ["DIRECT_REFUTATION"],
            "unverified_requirements": ["followup"], "feasibility_score": 0.3}


@case("T10", "证据传递", "长工具结果压缩后仍是有效 JSON")
def json_result():
    with patch.object(config, "LLM_MAX_TOOL_RESULT_CHARS", 700):
        messages, _ = loop({"lookup": large_result}, [msg(calls=[("lookup", {})]), msg("done")])
    content = next(m["content"] for m in messages if m["role"] == "tool")
    json.loads(content)


@case("T11", "证据传递", "长结果尾部的反证与未知项保留")
def protected_result():
    with patch.object(config, "LLM_MAX_TOOL_RESULT_CHARS", 700):
        messages, _ = loop({"lookup": large_result}, [msg(calls=[("lookup", {})]), msg("done")])
    content = next(m["content"] for m in messages if m["role"] == "tool")
    require("DIRECT_REFUTATION" in content and "followup" in content, "关键反证被截断")


@case("T12", "工具预算与前置条件", "最后一次迭代调用工具后仍有正文收口")
def finalization():
    messages, _ = loop({"lookup": lambda: {"ok": True}}, [msg(calls=[("lookup", {})])]*3 + [msg("# Final report")])
    require(any(m.get("content") and m["role"] == "assistant" and not m.get("tool_calls") for m in messages), "循环结束仅有工具结果")


DRAFT = "## 1. Background\nPREVIOUS_DRAFT_SENTINEL\n" + "Synthetic study design evidence. "*25


def run_idea(*, actual=0.9, claimed=0.9, cohort=800, claimed_cohort=800, decision=True,
             score=9.0, public=True, tool_error=False, rounds=1, relaxed=False,
             unverified=False, reviewer_valid=True):
    requests = []
    scripts = []
    for r in range(rounds):
        scripts += [msg(calls=[("public_dataset_assess", {"keyword": "test disease"})]), msg(DRAFT)]
        calls = []
        if actual is not None:
            args = {"disease_id": "TEST-D", "task_type": "classification", "required_annotations": ["tumor_region"]}
            calls.append(("feasibility_assess", args))
            if relaxed:
                calls.append(("feasibility_assess", {**args, "required_annotations": []}))
        if public: calls.append(("public_dataset_assess", {"keyword": "test disease"}))
        if calls: scripts.append(msg(calls=calls))
        review = {"overall_score": score, "accept": decision if r == rounds-1 else False,
            "feasibility_score": claimed, "available_cohort_size": claimed_cohort,
            "critical_issues": [], "dimension_scores": {}, "strengths": [],
            "kg_verification": "synthetic", "revision_priority": "Keep the previous design"}
        scripts.append(msg(json.dumps(review) if reviewer_valid else "not a JSON review"))
    replies = iter(scripts)
    def create(**kw):
        requests.append(copy.deepcopy(kw))
        return next(replies, msg("# No more synthetic responses"))
    def feasibility_assess(disease_id, task_type=None, required_annotations=None):
        if tool_error: return {"error": "fixture_api_unavailable"}
        return {"feasibility_score": actual, "available_cohort_size": cohort,
                "unverified_requirements": ["followup"] if unverified else []}
    def public_dataset_assess(keyword):
        return {"status": "NONE", "recommended_public": [], "keyword": keyword}
    def bundle(role):
        tools = {"public_dataset_assess": public_dataset_assess}
        if role == "critic": tools["feasibility_assess"] = feasibility_assess
        return tools, [schema(n) for n in tools]
    difficulty = {"target_difficulty": "moderate", "assessed_difficulty": "moderate", "difficulty_delta": 0,
                  "color": "green", "summary_line": "fixture", "q_coverage_low": False, "breakdown": {}}
    with contextlib.ExitStack() as stack:
        for name, val in {"build_idea_role_tool_bundle": bundle, "_gap_disease_hint": lambda _: ("TEST-D", "fixture"),
            "_gap_anchor_block": lambda _: "Synthetic frozen scope TEST-D", "_ensure_proposal_draft": lambda *a, **k: (DRAFT, False),
            "load_supporting_papers_for_keyword": lambda *_: [], "load_public_datasets_for_keyword": lambda *_: [],
            "assess_implementation_difficulty": lambda **_: difficulty, "_prepend_difficulty_header": lambda c, r: c}.items():
            stack.enter_context(patch.object(idea, name, val))
        stack.enter_context(patch.object(au._client.chat.completions, "create", create))
        events = list(idea.stream_idea_agent("test disease classification", max_rounds=rounds))
    TRACE.append({"requests": requests, "events": events})
    feedback = [e for e in events if e["type"] == "feedback"]
    return feedback, next(e for e in reversed(events) if e["type"] == "final"), requests


@case("A01", "验收与事实一致性", "有效工具证据与一致评审可通过", "normal")
def valid_accept():
    fb, _, _ = run_idea()
    require(fb[-1]["accept"] is True, str(fb))


@case("A02", "验收与事实一致性", "缺少可行性验证不得通过")
def missing_feas():
    fb, _, _ = run_idea(actual=None)
    require(fb[-1]["accept"] is False, "无真实可行性验证却通过")


@case("A03", "验收与事实一致性", "Critic 不得抬高低可行性工具值")
def overwritten_score():
    fb, _, _ = run_idea(actual=0.3, claimed=0.9)
    require(not fb[-1]["accept"] and fb[-1]["feasibility_score"] == 0.3, str(fb[-1]))


@case("A04", "验收与事实一致性", "Critic 不得改写队列规模")
def overwritten_cohort():
    fb, final, _ = run_idea(claimed_cohort=9000)
    require(not fb[-1]["accept"] and final["available_cohort_size"] == 800, str(final))


@case("A05", "验收与事实一致性", "高分不能覆盖显式拒绝")
def reviewer_reject():
    fb, _, _ = run_idea(decision=False, score=9)
    require(fb[-1]["accept"] is False, "显式 accept=false 被高分覆盖")


@case("A06", "验收与事实一致性", "缺少公共数据核验不得通过")
def missing_public():
    fb, _, _ = run_idea(public=False)
    require(fb[-1]["accept"] is False, "评审阶段遗漏必需工具仍通过")


@case("A07", "验收与事实一致性", "可行性工具报错不能当作已验证")
def failed_feas():
    fb, _, _ = run_idea(tool_error=True)
    require(fb[-1]["accept"] is False, "API error 被模型自报结果掩盖")


@case("A08", "验收与事实一致性", "参数放宽护栏仍有效", "normal")
def relaxed():
    fb, _, _ = run_idea(relaxed=True)
    require(fb[-1]["accept"] is False, "放宽研究规格未阻止通过")


@case("A09", "跨轮与完成状态", "达到轮数上限不等于验证通过")
def final_state():
    _, final, _ = run_idea(actual=None)
    require(final.get("validation_status") == "needs_verification" and final.get("accepted") is False, str(final))


@case("A10", "跨轮与完成状态", "修改轮次包含上一版完整草稿")
def previous_draft():
    _, _, requests = run_idea(rounds=2, score=6, decision=False)
    gen_requests = [r for r in requests if "proposal designer" in r["messages"][0]["content"]]
    # First model request of second generator phase: system + user only.
    starts = [r for r in gen_requests if len(r["messages"]) == 2]
    require(len(starts) >= 2 and "PREVIOUS_DRAFT_SENTINEL" in starts[1]["messages"][1]["content"], "第二轮没有上一版草稿")


@case("A11", "验收与事实一致性", "未知关键需求不得视为验证完成")
def unverified():
    fb, _, _ = run_idea(unverified=True)
    require(not fb[-1]["accept"], "unverified_requirements 未阻止通过")


@case("A12", "验收与事实一致性", "非法数值评审应降级而非崩溃")
def invalid_score():
    fb, final, _ = run_idea(score="not-a-number")
    require(not fb[-1]["accept"] and final.get("validation_status") != "verified", "非法评分未降级")


@case("A13", "验收与事实一致性", "低可行性且评审如实报告不得通过", "normal")
def low_feas():
    fb, _, _ = run_idea(actual=0.3, claimed=0.3)
    require(not fb[-1]["accept"], "低可行性仍通过")


@case("A14", "验收与事实一致性", "评审解析失败不得通过", "normal")
def invalid_review():
    fb, _, _ = run_idea(reviewer_valid=False)
    require(not fb[-1]["accept"], "解析失败仍通过")


def run_gap(long_review=False):
    requests = []
    reviewer = {"overall_confidence": 9.0, "verified_gaps": [{"title": "g", "evidence": "x"*4500 if long_review else "fixture"}],
                "false_gaps": [{"title": "bad", "counter_evidence": "TAIL_REFUTATION"}],
                "weak_evidence_gaps": [], "corpus_limitations": "23 papers only"}
    replies = iter([msg("## Candidate g"), msg(json.dumps(reviewer)), msg("# Final unverified research report")])
    def create(**kw): requests.append(copy.deepcopy(kw)); return next(replies, msg("# finish"))
    with patch.object(gap, "_corpus_context", lambda _: "Synthetic corpus 23"), \
         patch.object(gap, "resolve_ops_memory_block", lambda *_: ""), \
         patch.object(gap, "build_role_tool_bundle", lambda _: ({}, [])), \
         patch.object(au._client.chat.completions, "create", create):
        events = list(gap.stream_gap_debate_agent("test disease", max_debate_rounds=1))
    TRACE.append({"requests": requests, "events": events})
    return events[-1], requests


@case("G01", "跨轮与完成状态", "Gap 缺少必需工具不能标记已验证")
def gap_missing():
    final, _ = run_gap()
    require(final.get("validation_status") == "needs_verification", str(final))


@case("G02", "证据传递", "Synthesizer 接收评审尾部反证")
def gap_tail():
    _, requests = run_gap(long_review=True)
    require("TAIL_REFUTATION" in requests[-1]["messages"][1]["content"], "评审 JSON 前缀截断丢失反证")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "results.json").exists():
        raise SystemExit("Refusing to overwrite an existing run; choose a fresh output directory")
    global config, au, idea, gap
    blocked_network = []
    def deny_network(*a, **kw):
        blocked_network.append("blocked")
        raise RuntimeError("EVAL NETWORK DENIED")
    with tempfile.TemporaryDirectory(prefix="paper-eval-") as temp, \
         patch.object(socket.socket, "connect", deny_network), \
         patch.object(socket, "create_connection", deny_network):
        import config
        config.DB_PATH = str(Path(temp) / "fixture.db")
        config.DATA_DIR = temp
        config.OUTPUT_DIR = temp
        config.OPENAI_API_KEY = "offline-eval-placeholder"
        config.OPENAI_API_BASE = "http://127.0.0.1:1/v1"
        config.OPS_MEMORY_ENABLED = False
        real_connect = sqlite3.connect
        def safe_connect(database, *a, **kw):
            if str(database) != ":memory:" and not Path(str(database)).resolve().is_relative_to(Path(temp).resolve()):
                raise RuntimeError("EVAL refused database outside temporary sandbox")
            return real_connect(database, *a, **kw)
        with patch.object(sqlite3, "connect", safe_connect):
            from db.schema import init_db
            init_db()
            import analysis.agent_utils as au
            import idea_agent as idea
            import gap_agent as gap
            results = []
            for cid, category, title, severity, fn in CASES:
                TRACE.clear()
                start = time.perf_counter()
                log = io.StringIO()
                try:
                    with contextlib.redirect_stdout(log): fn()
                    status, detail = "pass", "All assertions satisfied"
                except Exception as exc:
                    status, detail = "fail", f"{type(exc).__name__}: {exc}"
                row = {"id": cid, "category": category, "title": title, "severity": severity,
                       "status": status, "detail": detail, "duration_ms": round((time.perf_counter()-start)*1000, 2)}
                results.append(row)
                (args.output / f"{cid}.trace.json").write_text(json.dumps({"case": row, "trace": TRACE,
                    "log": log.getvalue()}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                print(cid, status, title)
    files = ["analysis/agent_utils.py", "idea_agent.py", "gap_agent.py", "analysis/idea_session_guards.py"]
    data = {"label": args.label, "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_scripted_model_synthetic_tools", "live_model_calls": 0,
        "network_attempts_blocked": len(blocked_network), "clinical_data_used": False,
        "suite_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
        "cases": results, "passed": sum(r["status"] == "pass" for r in results), "total": len(results),
        "limitations": ["No live model behavior measured", "No expert-labelled paper gold set",
                        "No scientific novelty or clinical efficacy assessment", "Targeted diagnostic suite, not holdout"]}
    (args.output / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{data['passed']}/{data['total']} passed; network calls=0; label={args.label}")


if __name__ == "__main__":
    main()
