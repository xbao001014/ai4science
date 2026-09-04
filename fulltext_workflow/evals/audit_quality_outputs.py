"""Post-run integration audit: actual final reviews through production validator.

Secondary diagnostic, not part of the frozen primary before/after quality score.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quality_cases import RESEARCH
from run_quality_eval import grade_research
from analysis.research_quality import validate_review


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);args=p.parse_args()
    results=json.loads((args.run/'results.json').read_text(encoding='utf-8'));rows=[]
    for case in RESEARCH:
        for trial in range(1,results['repeats']+1):
            raw=json.loads((args.run/f'{case["id"]}-{trial}.json').read_text(encoding='utf-8'))['output']
            checked=validate_review(raw,case['evidence'],candidate_ids={case['id']},cutoff_year=int(case['cutoff'][:4]))
            rows.append({'id':case['id'],'trial':trial,'audit':checked['quality_audit'],
                         'grade_after_validation':grade_research(case,checked)})
    report={'mode':'secondary_final_validator_integration_not_frozen_primary_score','rows':rows,
            'provenance_checked':sum(r['audit']['status']=='provenance_checked' for r in rows),
            'correct_after_validation':sum(r['grade_after_validation']['correct'] for r in rows),'total':len(rows)}
    (args.run/'validator-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
    for row in rows:
        if row['audit']['issues']:print(row['id'],row['trial'],row['audit']['issues'])


if __name__=='__main__':main()
