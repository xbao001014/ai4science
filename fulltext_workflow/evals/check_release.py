"""Engineering gate with baseline-known failures; not scientific certification."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--baseline-regression', type=Path, required=True)
    p.add_argument('--candidate-regression', type=Path, required=True)
    args = p.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    candidate, before, after = map(read, (args.candidate, args.baseline_regression, args.candidate_regression))
    failures = [r['id'] for r in candidate['cases'] if r['status'] != 'pass']
    old = {r['test']:r['status'] for r in before['tests']}
    current = {r['test']:r['status'] for r in after['tests']}
    missing = sorted(set(old)-set(current))
    regressions = sorted(k for k,v in current.items() if v != 'passed' and old.get(k) != v)
    known = sorted(k for k,v in current.items() if v != 'passed' and old.get(k) == v)
    ok = bool(candidate['cases']) and not failures and not missing and not regressions
    print(json.dumps({'engineering_gate_passed':ok, 'offline_failures':failures,
                      'new_regressions':regressions, 'missing_regression_tests':missing,
                      'known_regression_failures':known, 'scientific_quality':'not_evaluated'},ensure_ascii=False,indent=2))
    raise SystemExit(0 if ok else 1)


if __name__=='__main__': main()
