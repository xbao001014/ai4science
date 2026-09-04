"""Static artifact QA only; does not launch a browser."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import zipfile


class Document(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=[]; self.links=[]; self.sources=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if 'id' in attrs: self.ids.append(attrs['id'])
        if 'href' in attrs: self.links.append(attrs['href'])
        if 'src' in attrs: self.sources.append(attrs['src'])


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True); args=p.parse_args()
    result=[]
    for name in ('paper-eval-baseline.html','paper-eval-comparison.html'):
        path=args.output/name; content=path.read_text(encoding='utf-8'); doc=Document(); doc.feed(content)
        assert '<html lang="zh-CN">' in content and 'charset="utf-8"' in content
        assert len(doc.ids)==len(set(doc.ids))
        for link in doc.links:
            if link.startswith('#'): assert link[1:] in doc.ids, link
            elif not link.startswith('https://'): assert (path.parent/link).is_file(), link
        assert not doc.sources
        assert '\ufffd' not in content and 'sk-' not in content
        result.append({'file':name,'bytes':path.stat().st_size,'sections':len(doc.ids),'static_checks':'passed'})
    with zipfile.ZipFile(args.output/'paper-eval-evidence.zip') as archive:
        assert archive.testzip() is None
        names=archive.namelist()
        assert all(not n.endswith(('.env','.db','.sqlite','.sqlite3')) for n in names)
        assert 'source-after/fulltext_workflow/analysis/evidence_contract.py' in names
        assert 'runs/live-final/results.json' in names
        assert 'runs/baseline/results.json' in names
        for name in names:
            if name.endswith('.json'):
                data=json.loads(archive.read(name))
                def check(value):
                    if isinstance(value,dict):
                        assert not {'api_key','authorization','access_token','refresh_token'} & {str(k).lower() for k in value}
                        for v in value.values(): check(v)
                    elif isinstance(value,list):
                        for v in value: check(v)
                check(data)
    payload={'reports':result,'archive_integrity':'passed','credential_field_scan':'passed',
             'browser_visual_check':'not_performed_local_file_browser_policy_blocked'}
    (args.output/'paper-eval-artifact-qa.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
