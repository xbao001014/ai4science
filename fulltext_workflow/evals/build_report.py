"""Build self-contained Chinese HTML reports and a local reproducibility bundle."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import statistics
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ["analysis/agent_utils.py", "analysis/evidence_contract.py", "idea_agent.py",
         "gap_agent.py", "gap_ui.py", "tests/test_idea_agent_baseline_accept.py"]
CSS = """+:root{--ink:#16312e;--muted:#536761;--line:#d5ded8;--paper:#fffef9;--bg:#f1f3ec;--green:#176d51;--red:#a13430;--amber:#8a580b}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.8 system-ui,'Microsoft YaHei',sans-serif}
header{background:#153f36;color:#fff;padding:44px max(24px,calc((100vw - 1160px)/2)) 35px;border-bottom:6px solid #a8cf84}
header p{max-width:900px;color:#deede4}h1{font-size:clamp(28px,4vw,42px);line-height:1.3;margin:12px 0}h2{font-size:25px;margin:0 0 18px}h3{font-size:19px;margin:22px 0 8px}.eyebrow{font-size:13px;letter-spacing:2px;text-transform:uppercase}
nav{display:flex;gap:20px;flex-wrap:wrap;padding:15px 24px;background:var(--paper);border-bottom:1px solid var(--line);justify-content:center}a{color:#176d51;text-underline-offset:3px}header a{color:#d3efaf}main{max-width:1208px;margin:auto;padding:28px 24px 60px}section{background:var(--paper);border:1px solid var(--line);padding:28px;margin:0 0 22px;border-radius:5px;scroll-margin-top:12px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:20px 0}.card{border-top:3px solid var(--green);background:#edf3e9;padding:20px}.metric{font-size:32px;font-weight:700;line-height:1.4}.small,small{font-size:13px;color:var(--muted)}.note{background:#fff3d9;border-left:4px solid #b08020;padding:14px 18px;margin:18px 0}.success{background:#edf5e9;border-left:4px solid var(--green);padding:14px 18px}.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;background:#eaf0e6;color:#284d42}td,th{padding:12px 13px;vertical-align:top;border-bottom:1px solid var(--line)}td:first-child{font-weight:600}td code{white-space:normal}code,pre{font-family:Consolas,monospace;font-size:13px;overflow-wrap:anywhere}pre{background:#edf0e9;padding:16px;white-space:pre-wrap;max-height:380px;overflow:auto}details{border-bottom:1px solid var(--line);padding:10px 0}summary{cursor:pointer}span.pass{color:var(--green);font-weight:700}span.fail{color:var(--red);font-weight:700}.pill{display:inline-block;border:1px solid currentColor;border-radius:4px;padding:0 7px;font-size:12px;margin-right:7px}.muted{color:var(--muted)}ul,ol{padding-left:22px}li{margin:6px 0}footer{color:var(--muted);font-size:13px;padding:0 25px 28px;text-align:center}button{border:1px solid #8b9c8e;border-radius:4px;padding:8px 15px;background:white;cursor:pointer;color:var(--ink)}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0 18px}input{font:inherit;max-width:100%;border:1px solid #9fab9f;border-radius:4px;padding:7px 10px}
@media(max-width:720px){.cards{grid-template-columns:1fr}main{padding:18px 12px}section{padding:20px 16px}header{padding:30px 20px}td,th{padding:9px}nav{gap:13px}.metric{font-size:28px}}@media print{body{background:white}header{background:white;color:#16312e;padding:20px}header p{color:#536761}nav,.toolbar,button{display:none}section{break-inside:avoid;border:0;padding:15px 0}main{padding:0}details{break-inside:avoid}pre{max-height:none}.cards{grid-template-columns:repeat(3,1fr)}}
"""


def esc(v): return html.escape(str(v))
def load(path): return json.loads(path.read_text(encoding="utf-8"))
def badge(status):
    passed = status in ("pass", "passed")
    return f'<span class="{"pass" if passed else "fail"}">{"通过" if passed else "失败"}</span>'
def score(data): return f'{data["passed"]}/{data["total"]}'
def pct(data): return f'{100*data["passed"]/data["total"]:.1f}%'
def table(head, rows):
    return '<div class="tablewrap"><table><thead><tr>'+''.join(f'<th>{h}</th>' for h in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{c}</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def section(id_, title, body): return f'<section id="{id_}"><h2>{title}</h2>{body}</section>'


FRAMEWORK = """
<p>评价对象是整条“文献抽取 → 领域检索 → 空白核验 → 提案生成/评审”链路，不能只看 Critic 的自评分。以下各层分别报告；关键证据错误具有否决权。</p>
""" + table(["层级 / 对象", "指标与判定", "本次覆盖", "后续验收"], [
    ["L0 · 执行与约束", "参数忠实、工具预算、前置条件、结果保真、未知状态、验收状态", "28 个固定场景；真实编排 + 脚本模型 + 合成工具", "所有 critical 场景通过；错误不得被高分抵消"],
    ["L1 · 模型行为", "有效终稿、必需工具、数值忠实、失败降级、嵌入指令抵抗、关系归属", "6 场景 × 2 次；实际配置模型；合成资料", "扩展为 ≥3 次/场景；单列 API 错误、波动与成本"],
    ["L2 · 文献与检索质量", "关系 precision/recall/F1、证据片段支持率、背景误归属、检索 recall@k", "仅有 2 个合成抽取场景；真实文献质量未测", "建议 64 篇、覆盖 8 类研究；按文献划分 32 开发 / 32 留出"],
    ["L3 · 空白与提案质量", "假空白率、机会召回、恰当保留判断、反证使用、可证伪性、专家盲评实用性", "仅测编排边界，未测科学新颖性", "建议 24 个证据包：支持 / 反证 / 证据不足各 8；双人标注 + 仲裁"],
    ["兼容性与资源", "已有用例回归；每任务 tokens / 调用数 / 时延 / 错误", "15 个旧测试模块，共 98 项；真实 API 用量", "不新增回归；质量过线后再优化资源，保留已知失败"],
]) + """
<div class="note">本次定向场景根据代码审查构造，改进时可以查看，因此是开发/回归集，不是隐藏留出集。28/28 表示这些已知风险场景通过，不代表真实任务准确率 100%。</div>
<h3>评分与发布规则</h3>
<p>固定输入、评分器、模型名称、温度和 token 上限；前后复用同一脚本并校验哈希。错误保留在分母中。科研评价采用按文献/证据包配对的比较，不能把一个场景重复两次当成两个独立科研样本。</p>
<p>科学层的建议起始门槛：引用 ID 有效率 100%、证据支持精度 ≥95%、假空白率 ≤10%，且机会召回及盲评实用性不下降。<strong>这些是待领域负责人校准的目标，不是本次达成的成绩。</strong>同时报告保留判断比例，防止“全部拒绝”获得虚假的高分。</p>
<p>完整标注、分层抽样、盲评、置信区间及复测协议已保存于评测目录的 <code>SCIENTIFIC_RUBRIC.md</code>。本次未使用 LLM 自评作为独立真值。</p>
"""

CHANGES = table(["问题 / 证据", "已落地的设计", "边界"], [
    ["T01–T04 参数丢失或畸形输入被执行", "保留包装器签名、保留 **kwargs、执行前拒绝非对象/畸形 JSON", "不是完整 JSON Schema 验证器；任意参数越域仍需进一步约束"],
    ["T05–T09 预算与先后条件", "每阶段总工具调用硬上限；批量响应逐条计数；覆盖检查前置；保留 SQL/重复工具护栏", "预算控制工具执行，不等于费用精确上限"],
    ["T10、T11、G02 证据被截断", "有效 JSON 压缩、根级反证/未知项优先、截断标记；跨角色传递带 call_id 的工具证据", "仍是有损压缩，不能保证所有嵌套证据保留；完整原文引用链尚待补全"],
    ["T12、L02–L04 无有效终稿", "工具迭代耗尽后预留一次无工具最终答复；缺验证必须声明", "最多额外一次模型调用；这不是零成本优化"],
    ["A02–A14 高分/模型值覆盖核验", "当前轮成功工具结果为数值真值；校验数值范围、accept、缺验证、低可行性、未知需求和冲突", "工程验收通过不等于专家认可或临床有效"],
    ["A09、G01 结束被误读为通过", "结构化 accepted / validation_status / validation_reasons；未通过说明写进提案，UI 单列状态", "Gap 的 evidence_checked 只表示证据流程检查，不表示全球文献无先例"],
    ["A10 修改轮次缺原稿", "回传上一稿及冻结需求；Gap 下一轮回传已有候选；公共证据政策标明草稿/记忆是数据", "未实现长期记忆的完整逐条来源校验"],
])

CLAUDE = """
<p>借鉴的是“可执行条件”，不是照搬一大段聊天提示词。用户提供的 <a href="https://github.com/elder-plinius/CL4R1T4S/blob/main/ANTHROPIC/Claude-Fable-5.1.md">Claude-Fable-5.1 文件</a>为社区仓库文本，不能确认其官方真实性、完整性或实际部署版本。</p>
<p>可对应的设计启发：区分用户要求与资料内嵌指令（约第 1379 行）；按任务来源选择工具（约第 1470 行）；需要时取完整来源并保留冲突（约第 1480–1490 行）；聊天检索 ID 不猜造、失败时搜索或询问（约第 1213 行）。本次分别转化为证据信任边界、角色工具边界、反证保留和缺证据不通过。</p>
<p>该文本确实写有部分“触发条件 → 工具/输出形式”的行为路由，但它不是平台服务端如何按用户输入动态拼装 system prompt 的实现文档。这里新增的预算计数、验收校验、证据台账是对项目的工程设计，不应归称为 Claude 原文已经实现的能力。</p>
"""

LIMITS = """
<ul>
<li>没有用生产论文/病人记录跑端到端流程，没有连接病理数据 API；真实模型测试发送的是合成文献片段和合成队列数值。</li>
<li>线上模型测试把工具迭代上限压到 3 次，生产 Critic 为 12 次。基线终稿失败是短预算压力现象，不能解读为生产失败率。</li>
<li>同名模型、固定温度不保证确定性；基线与改进顺序运行、未随机交错。每例 2 次太少，不声称统计显著或因果隔离。</li>
<li>这是 prompt 与运行时代码联合改进；没有做消融实验，不能把全部提升归因于新增提示词。</li>
<li>抽取模块未改，两个合成例只能作为归属关系烟雾测试。尚无真实文献金标准、完整引用支持评分或领域专家盲评。</li>
<li>未宣称全库测试通过：只运行与本次变更相关的 15 个旧模块；3 项已存在的别名预期失败保留。</li>
<li>真实模型原始 trace 保留各次 response；messages 在收集器中引用了可变会话，落盘时可能是最终会话，并非每一步发起前的不可变快照。请勿据此还原精确逐请求输入；后续应改为深拷贝并建立新评测版本。</li>
</ul>
"""


def page(title, summary, contents, comparison):
    target = 'paper-eval-baseline.html' if comparison else 'paper-eval-comparison.html'
    label = '查看基线报告' if comparison else '查看改进对比'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body>
<header><div class="eyebrow">Evidence-first evaluation · v1 · 2026-09-03</div><h1>{title}</h1><p>{summary}</p><a href="{target}">{label} ↗</a></header>
<nav><a href="#outcome">结论</a><a href="#framework">评测体系</a><a href="#cases">逐项结果</a><a href="#live">真实模型</a><a href="#limits">适用边界</a><a href="#reproduce">复现</a></nav>
<main>{contents}</main><footer>本地报告 · 无外部脚本、字体或追踪 · 所有得分由运行记录生成</footer>
<script>document.querySelectorAll('[data-filter]').forEach(x=>x.addEventListener('input',()=>{{let q=x.value.toLowerCase();document.querySelectorAll('#cases tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))}}));</script></body></html>'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runs', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    b = load(args.runs/'baseline/results.json'); a = load(args.runs/'improved-final/results.json')
    lb = load(args.runs/'live-baseline/results.json'); la = load(args.runs/'live-final/results.json')
    rb = load(args.runs/'regression-baseline/regression.json'); ra = load(args.runs/'regression-final/regression.json')
    assert b['suite_sha256'] == a['suite_sha256'], 'Offline suite changed'
    assert lb['suite_sha256'] == la['suite_sha256'], 'Live suite changed'
    categories = list(dict.fromkeys(r['category'] for r in b['cases']))
    critical = lambda d: sum(r['severity']=='critical' and r['status']!='pass' for r in d['cases'])
    old = {r['id']:r for r in b['cases']}; newer = {r['id']:r for r in a['cases']}
    beforelive = {(r['id'],r['trial']):r for r in lb['cases']}
    live_wins = sum(r['status']=='pass' and beforelive[(r['id'],r['trial'])]['status']!='pass' for r in la['cases'])
    live_losses = sum(r['status']!='pass' and beforelive[(r['id'],r['trial'])]['status']=='pass' for r in la['cases'])
    sources = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}
    manifest = {'created_at':datetime.now(timezone.utc).isoformat(), 'baseline_head':b['git_head'],
                'offline_suite_sha256':b['suite_sha256'], 'live_suite_sha256':lb['suite_sha256'],
                'final_sources':sources, 'clinical_data_used':False,
                'notes':['Frozen diagnostic suites; not held out','One legacy mock fixture adapted to fresh-evidence contract',
                         'Three pre-existing alias failures remain', 'No scientific-quality claim']}
    all_usage = Counter()
    for name in ('live-baseline','live-improved','live-final'):
        path = args.runs/name/'results.json'
        if path.exists(): all_usage.update(load(path)['usage'])
    manifest['all_recorded_live_usage'] = dict(all_usage)
    (args.output/'paper-eval-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    for comparison in (False, True):
        cards = ''.join(f'<div class="card"><div class="small">{label}</div><div class="metric">{value}</div><div class="small">{note}</div></div>' for label,value,note in [
            ('固定风险场景',f'{score(b)} → {score(a)}' if comparison else score(b),'脚本模型 / 合成工具，不是生产成功率'),
            ('真实模型短预算压力测试',f'{score(lb)} → {score(la)}' if comparison else score(lb),'6 个场景各 2 次，固定合成资料'),
            ('已有模块回归',f'{score(rb)} → {score(ra)}' if comparison else score(rb),'3 项既有别名预期失败，未掩盖'),
        ])
        lead = (f'<div class="success">已完成基线 → 改进 → 同集复测。固定场景修复 {sum(old[k]["status"]!="pass" and newer[k]["status"]=="pass" for k in old)} 项；关键场景失败 {critical(b)} → {critical(a)}。真实模型配对结果 {live_wins} 胜 / {live_losses} 负，其余相同。</div>' if comparison else
                '<div class="note">基线暴露的是证据与执行契约的缺口：参数可能丢失、预算只写在 prompt 中、模型数值可能覆盖工具结果、缺少验证仍能通过、长结果中的反证可能被截断。此页仅展示改动前测量。</div>')
        body = section('outcome','01 / 结论与覆盖',lead+'<div class="cards">'+cards+'</div><p>项目实际位置：<code>D:\\agent\\prototype\\build_kg_paper</code>。基线 Git 提交 <code>'+b['git_head']+'</code>；改进为当前未提交工作区改动，未部署、未改数据库。</p>')
        body += section('framework','02 / 适合本系统的分层 eval',FRAMEWORK)
        catrows = []
        for cat in categories:
            br = [r for r in b['cases'] if r['category']==cat]; ar = [r for r in a['cases'] if r['category']==cat]
            row = [esc(cat),f'{sum(r["status"]=="pass" for r in br)}/{len(br)}']
            if comparison: row.append(f'{sum(r["status"]=="pass" for r in ar)}/{len(ar)}')
            catrows.append(row)
        body += section('categories','03 / 哪些能力改善了',table(['能力','基线']+(['改进后'] if comparison else []),catrows))
        case_rows=[]
        for row in b['cases']:
            cells=[row['id'],esc(row['title']),'<span class="pill">'+esc(row['severity'])+'</span>',badge(row['status'])]
            if comparison: cells.append(badge(newer[row['id']]['status']))
            cells.append(esc(row['detail']))
            case_rows.append(cells)
        body += section('cases','04 / 固定场景：逐项可追溯','<div class="toolbar"><label>筛选场景 <input data-filter placeholder="例如：A03、反证、通过"></label></div>'+table(['ID','场景','级别','基线']+(['改进后'] if comparison else [])+['基线判定细节'],case_rows))
        live_rows=[]
        for row in lb['cases']:
            cells=[f'{row["id"]} · {row["trial"]}',esc(row['title']),badge(row['status']),f'{row["duration_s"]:.2f}s / {row["usage"]["requests"]} 次']
            if comparison:
                match=next(r for r in la['cases'] if (r['id'],r['trial'])==(row['id'],row['trial']))
                cells += [badge(match['status']),f'{match["duration_s"]:.2f}s / {match["usage"]["requests"]} 次']
            cells.append(', '.join(esc(k) for k,v in row['checks'].items() if not v) or '—')
            live_rows.append(cells)
        resource_rows=[]
        for label,key in [('SDK 请求数','requests'),('输入 tokens','prompt_tokens'),('输出 tokens','completion_tokens'),('API 错误','api_errors')]:
            resource_rows.append([label,str(lb['usage'][key])]+([str(la['usage'][key])] if comparison else []))
        resource_rows += [['每例时延中位数',f'{statistics.median(r["duration_s"] for r in lb["cases"]):.2f}s']+([f'{statistics.median(r["duration_s"] for r in la["cases"]):.2f}s'] if comparison else [])]
        live_text=f'<p>实际模型配置：评审 <code>{esc(lb["agent_model"])}</code>；抽取 <code>{esc(lb["extract_model"])}</code>。单请求输出上限 1,800 tokens，Critic 温度 0.3，工具迭代最多 3 次；SDK 自动重试关闭。改进版耗尽时可补 1 次无工具终稿。</p>'
        live_text+='<p>基线失败的 5 次均未形成有效评审 JSON：3 次迭代用在工具上，循环结束缺少最终答复。不能把这些缺字段判定误报成“模型伪造数据”或“注入攻击成功”。L05/L06 抽取提示词未改，作为兼容性对照。</p>'
        live_text+=table(['场景 / 次数','测试意图','基线','基线时延/调用']+(['改进后','改进时延/调用'] if comparison else [])+['基线未通过断言'],live_rows)
        live_text+='<h3>资源代价</h3>'+table(['指标','基线']+(['改进后'] if comparison else []),resource_rows)
        if comparison:
            live_text+=f'<p>包含中间版本复测，本次共记录 {all_usage["requests"]} 次 SDK 请求，输入 {all_usage["prompt_tokens"]:,} tokens，输出 {all_usage["completion_tokens"]:,} tokens；API 错误 {all_usage["api_errors"]}。未查询服务商账单，故不虚构金额。中间版为 12/12，完整记录也在证据包中，并未只保留最好的一次。</p>'
        body+=section('live','05 / 真实模型：效果与资源分开看',live_text)
        regression_text='<p>基线与最终版均保留 3 个既有失败：旧断言期待 <code>vital_status</code>，现有规范化逻辑返回 <code>death_event</code>。未为了本次提分改动这些断言。</p>'
        regression_text+=table(['测试','基线']+(['最终版'] if comparison else []),[[esc(r['test']),badge(r['status'])]+([badge(next(x['status'] for x in ra['tests'] if x['test']==r['test']))] if comparison else []) for r in rb['tests'] if r['status']!='passed'])
        if comparison:
            regression_text+='<p>首轮改进曾出现额外 4 个旧测试失败：3 个与 SQL 限额提示或虚构格式工具的恢复兼容有关，已修复运行时代码；另 1 个旧模拟器未发出成功工具证据，已补齐当前轮可行性/公共数据证据，保留“仅本轮放宽被拒绝”的原断言。因此 95/98 是最终适配后结果，不能称 98 项测试文件完全未动。28 项主评测与 12 项真实模型评分脚本则前后完全相同。</p>'
        body+=section('regression','06 / 兼容性回归与已知失败',regression_text)
        if comparison: body+=section('changes','07 / 已实施的系统改进',CHANGES+CLAUDE)
        body+=section('limits','08 / 结论不能外推到哪里',LIMITS)
        reproduce=f'<p>执行时间（UTC）：基线固定场景 {esc(b["created_at"])}；基线真实模型 {esc(lb["created_at"])}。'+(f'最终固定场景 {esc(a["created_at"])}；最终真实模型 {esc(la["created_at"])}。' if comparison else '')+'</p>'
        reproduce+='<p>报告在测量完成后汇编；基线结果文件来自修改前运行，没有用改进代码重算基线。相同基线源代码已在本地归档。运行脚本会创建临时数据库；离线主评测禁止网络和临时目录之外的 SQLite 访问。</p>'
        reproduce+=f'<details><summary>冻结脚本哈希 / 源码记录</summary><pre>{esc(json.dumps(manifest,ensure_ascii=False,indent=2))}</pre></details>'
        reproduce+='''<pre># 在项目根目录执行；每次使用新的结果目录
.\\.venv\\Scripts\\python.exe fulltext_workflow\\evals\\run_eval.py --label candidate --output tmp\\eval\\candidate
.\\.venv\\Scripts\\python.exe fulltext_workflow\\evals\\run_regression.py --output tmp\\eval\\regression-candidate
# 下条会产生模型 API 用量，需授权后执行
.\\.venv\\Scripts\\python.exe fulltext_workflow\\evals\\run_live_eval.py --label candidate --output tmp\\eval\\live-candidate
</pre><p><a href="paper-eval-evidence.zip">下载本地复现证据包</a> · <a href="paper-eval-manifest.json">版本与用量清单</a>。证据包含前后逐例记录、脚本、协议、变更源码及补丁；不含 .env、API 密钥、生产数据库或真实患者资料。</p>'''
        reproduce+='<p>工件检查：HTML 结构、内部链接和压缩包完整性通过静态校验。浏览器策略阻止自动打开本地 HTML，未完成视觉截图核验。方法参考：<a href="https://developers.openai.com/api/docs/guides/evaluation-best-practices">OpenAI 官方评测指南</a>强调任务特定测试、正常/边界/对抗案例与人类判断校准。本项目采用本地评测脚本，不依赖其托管 Evals 服务。</p>'
        body+=section('reproduce','09 / 复现、审计与下一步',reproduce)
        title='文献研究系统 · 改进前后评测报告' if comparison else '文献研究系统 · 基线评测报告'
        summary=('工具边界与证据验收已加强；真实模型压力测试改善。科研新颖性与研究价值仍需独立专家金标准验证。' if comparison else '先测量，再改进。记录现有系统的可执行约束、失败场景与真实模型行为，保留完整基线。')
        filename='paper-eval-comparison.html' if comparison else 'paper-eval-baseline.html'
        (args.output/filename).write_text(page(title,summary,body,comparison),encoding='utf-8')
    with zipfile.ZipFile(args.output/'paper-eval-evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(args.runs.rglob('*.json')):
            z.write(path,'runs/'+path.relative_to(args.runs).as_posix())
        for path in sorted((ROOT/'evals').glob('*')):
            if path.is_file() and path.suffix in ('.py','.md','.json'): z.write(path,'evals/'+path.name)
        for name in FILES: z.write(ROOT/name,'source-after/fulltext_workflow/'+name)
        archive=args.runs.parent/'eval-baseline-5595958.zip'
        with zipfile.ZipFile(archive) as original:
            for name in FILES:
                key='fulltext_workflow/'+name
                if key in original.namelist(): z.writestr('source-before/'+key,original.read(key))
        patch=subprocess.check_output(['git','diff','--no-ext-diff','--','fulltext_workflow'],cwd=ROOT.parent)
        z.writestr('tracked-changes.patch',patch)
        z.write(args.output/'paper-eval-manifest.json','manifest.json')
    print(json.dumps({'baseline':score(b),'improved':score(a),'live_baseline':score(lb),'live_final':score(la),
                      'regression_final':score(ra),'usage_all_versions':dict(all_usage)},ensure_ascii=False))


if __name__=='__main__': main()
