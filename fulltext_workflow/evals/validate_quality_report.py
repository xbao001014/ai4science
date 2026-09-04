"""Non-browser integrity/links/privacy-field checks for phase-2 deliverables."""
import argparse
import json
from pathlib import Path
import zipfile
from validate_report import Document


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    path=args.output/'paper-quality-phase2.html';text=path.read_text(encoding='utf-8')
    doc=Document();doc.feed(text)
    assert len(doc.ids)==len(set(doc.ids)) and not doc.sources
    assert 'charset="utf-8"' in text and '\ufffd' not in text
    for link in doc.links:
        if link.startswith('#'):assert link[1:] in doc.ids
        elif not link.startswith('https://'):assert (path.parent/link).is_file(),link
    def inspect(value):
        if isinstance(value,dict):
            assert not {'api_key','authorization','access_token','refresh_token'} & {str(k).lower() for k in value}
            for v in value.values():inspect(v)
        elif isinstance(value,list):
            for v in value:inspect(v)
    with zipfile.ZipFile(args.output/'paper-quality-phase2-evidence.zip') as z:
        assert z.testzip() is None
        for name in z.namelist():
            assert not name.endswith(('.env','.sqlite','.db','.sqlite3'))
            if name.endswith('.json'):inspect(json.loads(z.read(name)))
    qa={'html_static_checks':'passed','local_links':'passed','zip_integrity':'passed',
        'credential_field_scan':'passed','browser_visual_qa':'not_performed',
        'report_bytes':path.stat().st_size,'unique_section_ids':len(doc.ids)}
    (args.output/'paper-quality-phase2-qa.json').write_text(json.dumps(qa,indent=2),encoding='utf-8')
    print(json.dumps(qa,indent=2))


if __name__=='__main__':main()
