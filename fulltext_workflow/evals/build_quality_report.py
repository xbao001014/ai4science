"""Data-driven, self-contained phase-2 HTML report and reproducibility bundle."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import random
import statistics
import zipfile

from build_report import CSS,esc,table,section
from quality_cases import EXTRACTION,RESEARCH
from run_quality_eval import aggregate

ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def percent(n):return '未定义' if n is None else f'{100*n:.1f}%'
def change(a,b):return '—' if a is None or b is None else f'{100*(b-a):+.1f} 个百分点'
def count_pass(rows):return f'{sum(r["grade"]["pass"] and not r["error"] for r in rows)}/{len(rows)}'


def paired_interval(before,after,kind,metric):
    """Case-cluster paired bootstrap; all repeats stay together."""
    ids=sorted({r['id'] for r in before['rows'] if r['kind']==kind})
    rng=random.Random(20260903);values=[]
    group='extraction' if kind=='extraction' else 'research'
    bg={cid:[r for r in before['rows'] if r['id']==cid] for cid in ids}
    ag={cid:[r for r in after['rows'] if r['id']==cid] for cid in ids}
    for _ in range(2000):
        sampled=rng.choices(ids,k=len(ids))
        a=aggregate([r for cid in sampled for r in bg[cid]])[group][metric]
        b=aggregate([r for cid in sampled for r in ag[cid]])[group][metric]
        if a is not None and b is not None:values.append(100*(b-a))
    values.sort()
    return [values[int(len(values)*0.025)],values[min(len(values)-1,int(len(values)*0.975))]]


def main():
    p=argparse.ArgumentParser();p.add_argument('--runs',type=Path,required=True);p.add_argument('--after',default='final')
    p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    b=load(args.runs/'baseline/results.json');a=load(args.runs/args.after/'results.json')
    assert b['cases_sha256']==a['cases_sha256'] and b['grader_runner_sha256']==a['grader_runner_sha256']
    versions=[];usage=Counter()
    for folder in args.runs.iterdir():
        path=folder/'results.json'
        if path.exists():
            obj=load(path)
            if 'metrics' in obj:versions.append(obj);usage.update(obj['usage'])
    versions.sort(key=lambda d:d['started_at'])
    be,ae=b['metrics']['extraction'],a['metrics']['extraction'];br,ar=b['metrics']['research'],a['metrics']['research']
    ci={name:paired_interval(b,a,kind,metric) for name,kind,metric in
        [('grounded_recall','extraction','grounded_recall'),('research_accuracy','research','accuracy')]}
    bg={cid:[r for r in b['rows'] if r['id']==cid] for cid in [c['id'] for c in EXTRACTION+RESEARCH]}
    ag={cid:[r for r in a['rows'] if r['id']==cid] for cid in bg}
    metrics=[]
    for name,key in [('目标关系 precision','precision'),('目标关系 recall','recall'),('目标关系 F1','f1'),('引文可定位率','quote_location'),('事实正确且引文可定位的 precision','grounded_precision'),('事实正确且引文可定位的 recall','grounded_recall')]:
        metrics.append([name,percent(be[key]),percent(ae[key]),change(be[key],ae[key])])
    for name,key in [('研究判断 accuracy','accuracy'),('研究判断 macro F1','macro_f1'),('应保留判断时正确判证据不足','appropriate_abstention'),('支持机会召回','opportunity_recall'),('误判为支持的比例（越低越好）','false_supported_rate'),('必需证据 ID 覆盖率','citation_coverage')]:
        metrics.append([name,percent(br[key]),percent(ar[key]),change(br[key],ar[key])])
    body=section('outcome','01 / 结果：事实、引文与判断分别计量',f'''
<p>第二阶段基线是第一阶段改进后的系统，不是最初 Git HEAD。基线与最终版使用同一套冻结样例和评分器；没有使用模型的自评分当质量得分。</p>
<p><strong>本次提升主要在证据可追溯性和“证据不足”的正确处理。</strong>抽取事实召回率前后均为 {percent(be['recall'])}；基线和最终版都没有出现误判为支持的研究样例，因此不能声称降低了本轮未出现的研究误支持。</p>
<div class="cards"><div class="card"><div class="small">抽取完整通过 · 16 例 × 3 次</div><div class="metric">{be['passed']}/48 → {ae['passed']}/48</div><small>目标事实正确且引用可定位</small></div>
<div class="card"><div class="small">研究判断通过 · 12 例 × 3 次</div><div class="metric">{br['passed']}/36 → {ar['passed']}/36</div><small>唯一分类正确且必需证据 ID 齐全</small></div>
<div class="card"><div class="small">数据与标注等级</div><div class="metric">Silver</div><small>代理预先标注，未经领域专家仲裁</small></div></div>
<div class="note">本次测的是短文本抽取和固定证据条件下的研究判断，不是完整文献检索能力、专家研究价值或全球新颖性。4 个真实来源锚点仅为摘要短片段，其余为明确标记的受控合成资料。全部为可见开发集，不是隐藏留出集。</div>
'''+table(['指标','基线','最终版','差值'],metrics))
    body+=section('design','02 / 如何把“质量”变成可复测的定义',table(['层级','评分单位','正确 / 错误定义','防止取巧'],[
        ['事实抽取','每例预先指定关系族中的去重事实','预先定义的关系 + 名称别名 + 指标值匹配；范围内新增未知事实计 FP，漏项计 FN','不能靠少输出提分：同时报告 precision 和 recall'],
        ['证据绑定','每条目标关系的 evidence_quote','必须能定位到输入章节中的连续原文片段；空白差异归一化','事实匹配与引文定位分开；“引用存在”不代表语义蕴含'],
        ['研究判断','一个原始候选、一个分类','支持 / 直接反驳 / 证据不足；混入改写后候选或多个类别记 invalid','同时看误支持率、支持机会召回及恰当保留判断率'],
        ['引用出处','预先列出的必要 evidence_id','核对引用 ID 是否属于本轮证据，是否覆盖判定所需记录','单列 ID 正确性；不把它当成证明研究结论正确'],
    ])+f'''<p>事实评分口径：对每例预声明关系族穷尽计分，其他关系保留但不计分，所以这是“目标关系质量”，不是全知识图谱 precision。数值等价允许百分比与小数转换，别名表在基线前冻结。</p>
<p>运行配置：抽取 <code>{esc(b['extract_model'])}</code>，研究判断 <code>{esc(b['agent_model'])}</code>；温度 0.1 / 0.3，输出上限 2,400 tokens，3 个并发工作线程，固定随机顺序。相同样例各运行 3 次，版本按先后运行而非随机交错。</p>
<p>研究样例包含 3 个有限范围的支持机会、3 个直接反例、6 个证据不足场景。所有预期标签都在首次模型运行前写定；没有由受测模型给自己打分。</p>''')
    rows=[]
    for c in EXTRACTION:
        g=lambda items,k:sum(r['grade'][k] for r in items)
        rows.append([c['id'],esc(c['title']),('真实摘要短片段' if c.get('source_url') else '合成 · '+esc(c['study_type'])),
            count_pass(bg[c['id']]),count_pass(ag[c['id']]),
            f"{g(bg[c['id']],'tp')}/{g(bg[c['id']],'fp')}/{g(bg[c['id']],'fn')} → {g(ag[c['id']],'tp')}/{g(ag[c['id']],'fp')}/{g(ag[c['id']],'fn')}"])
    failed=[f'{r["id"]} / trial {r["trial"]}' for r in a['rows'] if r['kind']=='extraction' and not r['grade']['pass']]
    body+=section('extract','03 / 抽取：逐例结果',table(['ID','意图','样例来源','基线通过','最终通过','TP / FP / FN'],rows)+f'<p>总量：基线 TP={be["tp"]}、FP={be["fp"]}、FN={be["fn"]}；最终 TP={ae["tp"]}、FP={ae["fp"]}、FN={ae["fn"]}。通过要求同时满足事实集合与引文定位。最终未通过：{esc(", ".join(failed)) or "无"}。</p><p>最终 E03 的一次综述抽取返回空数组，漏掉两个已明确提及的方法；这不是 API 错误，也没有被排除在分母之外。偶发空结果依然是待优化问题。</p>')
    subrows=[]
    for name,ids in [('真实来源短片段',{c['id'] for c in EXTRACTION if c.get('source_url')}),('受控合成案例',{c['id'] for c in EXTRACTION if not c.get('source_url')})]:
        x=aggregate([r for r in b['rows'] if r['id'] in ids])['extraction'];y=aggregate([r for r in a['rows'] if r['id'] in ids])['extraction']
        subrows.append([name,f'{x["passed"]}/{x["total"]} → {y["passed"]}/{y["total"]}',percent(x['recall'])+' → '+percent(y['recall']),percent(x['grounded_recall'])+' → '+percent(y['grounded_recall'])])
    body+=section('sources','04 / 真实来源与合成样例分开看',table(['数据层','严格通过','事实 recall','事实 + 引文 recall'],subrows)+'<p>来源锚点：'+', '.join(f'<a href="{c["source_url"]}">{esc(c["title"])}</a>' for c in EXTRACTION if c.get('source_url'))+'</p><p>这些来源仅用于检查具体方法、数据集和指标的抽取，不用于证明当前研究空白。没有下载或上传生产论文库、临床数据库。</p>')
    rows=[]
    for c in RESEARCH:
        fmt=lambda rr:', '.join(f'{k}:{v}' for k,v in Counter(r['grade']['predicted'] for r in rr).items())
        rows.append([c['id'],esc(c['title']),c['expected'],esc(fmt(bg[c['id']])),esc(fmt(ag[c['id']])),esc(c['rationale'])])
    body+=section('research','05 / 研究判断：不是把谨慎都算作正确',table(['ID','判断难点','冻结标签','基线三次','最终三次','预期理由'],rows)+'''
<div class="note">标签口径必须透明：一个没有充分依据的“从未有人做过”断言，在此评价的是科学问题是否已被证实/解决，归为 insufficient；不是评价这句话的逻辑论证是否有效。基线部分回答合理指出了措辞错误，但把同一候选放进两个桶，或据此认定主题已被反驳，因此未通过这套机器可执行约定。</div>''')
    conf=[]
    for truth in ('supported','refuted','insufficient'):
        conf.append([truth]+[str(br['confusion'][truth][p])+' → '+str(ar['confusion'][truth][p]) for p in ('supported','refuted','insufficient','invalid')])
    body+=section('confusion','06 / 混淆矩阵与不确定性',table(['参考标签 ↓ / 输出 →','supported','refuted','insufficient','invalid'],conf)+f'''
<p>配对 case-cluster bootstrap（2,000 次，重复试验随同一场景整体采样）的 95% 差值区间：事实 + 引文 recall {ci['grounded_recall'][0]:+.1f} 至 {ci['grounded_recall'][1]:+.1f} 个百分点；研究判断 accuracy {ci['research_accuracy'][0]:+.1f} 至 {ci['research_accuracy'][1]:+.1f} 个百分点。</p>
<p>这是小型开发集的描述性不确定性，不是独立留出集验证或部署收益证明。3 次重复也不能把 12 个研究问题变成 36 个独立研究领域。请同时查看逐例结果与中间版本。</p>''')
    audit=load(args.runs/args.after/'validator-audit.json')
    body+=section('changes','07 / 系统落地：提示词与执行校验',table(['改动','落地位置','可测结果 / 边界'],[
        ['连续原文引文与空输出规则','extractor/study_prompts/','取消最低抽取数量，消除“87 人必然样本不足”等示例冲突；不丢弃恶意指令旁的真实事实'],
        ['引文位置校验','extractor/evidence_grounding.py + section_extractor.py','核验不通过的三元组被剔除并记录原因；输出包含章节偏移，不能把定位当作语义证明'],
        ['空结果的有界复查','section_extractor.py','实验类文本有明确作者实验动作却返回空数组时，最多追加一次复查；失败请求不重试。最终本轮未触发额外请求，因此不能把实测提升归因于此复查'],
        ['候选的互斥判断与证据用途','analysis/research_quality.py + gap_agent.py','区分直接反证与检索不足、任务错配、时点错配；保留有正面证据的局部机会'],
        ['运行时出处审计','with_evidence_records / validate_review','工具记录获得稳定证据 ID；核验 ID、引用片段、重复候选及时间边界，未通过时降级'],
        ['固定质量评分器与追踪','evals/quality_cases.py + run_quality_eval.py','前后 fixtures/grader 哈希相同；逐请求深拷贝 messages，修复第一阶段追踪快照的局限'],
    ])+f'<p>主质量数字衡量真实模型抽取入口和证据评审提示词；研究评审部分是固定证据的组件测试，不经过完整检索/Scout/Moderator，也不依靠运行时降级器“改正确答案”。另做最终输出的二级集成审计：{audit["provenance_checked"]}/{audit["total"]} 通过实际出处校验器，校验后 {audit["correct_after_validation"]}/{audit["total"]} 分类仍正确。该审计不是冻结的主评分，不混入前后主分数。</p>')
    vrows=[]
    for v in versions:
        e=v['metrics']['extraction'];r=v['metrics']['research'];u=v['usage']
        vrows.append([esc(v['label']),f'{e["passed"]}/48',percent(e['recall']),percent(e['grounded_recall']),f'{r["passed"]}/36',str(u['requests']),f'{u["prompt_tokens"]:,} / {u["completion_tokens"]:,}',str(v['metrics']['errors'])])
    body+=section('versions','08 / 全部版本与资源代价',table(['版本','抽取通过','事实 recall','事实+引文 recall','判断通过','请求数','输入 / 输出 tokens','错误'],vrows)+f'<p>本轮全部已完成质量运行累计 {usage["requests"]} 次 SDK 请求、输入 {usage["prompt_tokens"]:,} tokens、输出 {usage["completion_tokens"]:,} tokens。API 错误 {usage["api_errors"]}。未查询账单，不推算未核实的金额。</p>')
    eng=load(args.runs/'engineering-final/results.json');reg=load(args.runs/'legacy-final/regression.json')
    checks=load(args.runs/'quality-checks/regression.json')
    body+=section('limits','09 / 回归与仍未覆盖的质量',f'''
<p>第一阶段固定工程场景 {eng['passed']}/{eng['total']}；相关旧模块 {reg['passed']}/{reg['total']}；本阶段质量相关检查 {checks['passed']}/{checks['total']}（含 26 项新增规则/抽取入口测试及相关已有抽取测试，不与旧模块去重汇总）。3 项既有 vital_status / death_event 别名断言失败仍在，没有通过删改这些断言提分。</p>
<ul><li>尚无领域专家审定金标准；标签来自代理预先制定的明确规则，可能存在遗漏与偏差。</li>
<li>未测试全文抽取、切块/截断、全关系族、检索召回、全文协调 Pass 2 及入库后整个证据生命周期；Pass 1 的新引文门禁不代表 Pass 2 已同等加固。</li>
<li>来源 ID 和引文可定位只能证实出处，不保证语义支持；后者本次只通过有限参考标签检查。</li>
<li>新出处门禁可能增加生产环境的保留判断或抽取遗漏；未重抽历史库，没有改变生产记录。下一步需真实全文留出集验证召回代价。</li>
<li>prompt 与运行时联合变更，没有消融实验，不能将效果全部归于某一句提示词。</li></ul>
<p>下一步人工审阅包已生成：先核查银标，再让两位领域研究者独立判断完整论文和真实证据包，按论文 ID 隔离开发集与留出集。专家研究价值仍应采用盲评可证伪性、差异化、数据可得性、实验设计和实用性。</p>''')
    manifest={k:a[k] for k in ('label','started_at','finished_at','cases_sha256','grader_runner_sha256','source_sha256','agent_model','extract_model')}
    manifest.update(baseline_sources=b['source_sha256'],usage_all_versions=dict(usage),bootstrap_delta_pp=ci,
                    artifact_qa='static_only_browser_visual_not_performed',label_tier='silver_not_expert_gold')
    (args.output/'paper-quality-phase2-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    human=[]
    for kind,cases in [('extraction',EXTRACTION),('research',RESEARCH)]:
        for c in cases:
            human.append({'id':c['id'],'kind':kind,'input':c.get('text') or c['candidate'],
                          'source_url':c.get('source_url'),'evidence':c.get('evidence'),
                          'relations':c.get('relations'),'reviewer_id':None,'independent_label':None,
                          'supporting_spans':[],'rationale':None,'adjudication':'pending'})
    (args.output/'paper-quality-human-review.json').write_text(json.dumps(human,ensure_ascii=False,indent=2),encoding='utf-8')
    body+=section('reproduce','10 / 文件、复现与审计','''<p><a href="paper-quality-phase2-evidence.zip">完整复现证据包</a> · <a href="paper-quality-phase2-manifest.json">版本清单</a> · <a href="paper-quality-human-review.json">人工独立标注模板</a></p>
<pre># 项目根目录；会调用已配置模型 API，使用新结果目录
.\\.venv\\Scripts\\python.exe fulltext_workflow\\evals\\run_quality_eval.py --label candidate --output tmp\\quality\\candidate
# 独立质量规则测试，不调用模型
.\\.venv\\Scripts\\python.exe -m pytest fulltext_workflow\\tests\\test_quality_v2.py -q
</pre><p>评测规程见 QUALITY_PROTOCOL.md。HTML 为本地静态文件，无外部脚本和追踪；完成结构与链接校验，未做浏览器截图核验。</p>
<p>方法参考：<a href="https://developers.openai.com/api/docs/guides/evaluation-best-practices">OpenAI 官方评测指南</a>中的任务特定指标、工作流分层与人工判断校准；本方案使用本地脚本，不依赖托管 Evals 服务。</p>'''+f'<details><summary>展开版本哈希</summary><pre>{esc(json.dumps(manifest,ensure_ascii=False,indent=2))}</pre></details>')
    doc=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第二阶段 · 抽取与研究判断质量评测</title><style>{CSS}</style></head><body><header><div class="eyebrow">Phase 02 · Evidence quality · 2026-09-03</div><h1>把抽取与研究判断<br>变成可复测的质量</h1><p>从“流程执行成功”推进到“事实是否正确、引用是否真实、证据不足是否被正确识别”。保留基线、中间版本和最终结果。</p></header><nav><a href="#outcome">前后对比</a><a href="#extract">抽取明细</a><a href="#research">研究判断</a><a href="#versions">版本与成本</a><a href="#limits">适用边界</a><a href="#reproduce">复现</a></nav><main>{body}</main><footer>本地可审计报告 · 未经专家审定，不构成科研新颖性或临床价值证明</footer></body></html>'''
    (args.output/'paper-quality-phase2.html').write_text(doc,encoding='utf-8')
    with zipfile.ZipFile(args.output/'paper-quality-phase2-evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
        for file in sorted(args.runs.rglob('*')):
            if file.is_file() and file.suffix in ('.json','.zip','.xml'):z.write(file,'runs/'+file.relative_to(args.runs).as_posix())
        for file in (ROOT/'evals').glob('*'):
            if file.is_file() and file.suffix in ('.py','.md'):z.write(file,'evals/'+file.name)
        z.write(ROOT/'tests/test_quality_v2.py','tests/test_quality_v2.py')
        for name in ('paper-quality-phase2-manifest.json','paper-quality-human-review.json'):z.write(args.output/name,name)
    print(json.dumps({'before':b['metrics'],'after':a['metrics'],'bootstrap':ci,'usage':dict(usage)},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
