"""Static structure, local-link, bundle, and credential-field checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

from validate_report import Document


def inspect(value):
    if isinstance(value, dict):
        assert not {"api_key", "authorization", "access_token", "refresh_token"} & {str(key).lower() for key in value}
        for child in value.values():
            inspect(child)
    elif isinstance(value, list):
        for child in value:
            inspect(child)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = args.output / "paper-quality-p0.html"
    text = path.read_text(encoding="utf-8")
    doc = Document()
    doc.feed(text)
    assert len(doc.ids) == len(set(doc.ids)) and not doc.sources
    assert 'charset="utf-8"' in text and "\ufffd" not in text
    for link in doc.links:
        if link.startswith("#"):
            assert link[1:] in doc.ids
        elif not link.startswith("https://"):
            assert (path.parent / link).is_file(), link
    for name in ("paper-quality-p0-evidence.zip", "paper-quality-p0-expert-holdout-template.zip"):
        with zipfile.ZipFile(args.output / name) as archive:
            assert archive.testzip() is None
            for member in archive.namelist():
                assert not member.lower().endswith((".env", ".db", ".sqlite", ".sqlite3"))
                if member.endswith(".json"):
                    inspect(json.loads(archive.read(member)))
    manifest_path = args.output / "paper-quality-p0-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_qa"] = "static_structure_links_zip_and_credential_fields_passed"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    qa = {
        "html_static_checks": "passed",
        "local_links": "passed",
        "zip_integrity": "passed",
        "credential_field_scan": "passed",
        "browser_visual_qa": "not_performed",
        "report_bytes": path.stat().st_size,
        "unique_section_ids": len(doc.ids),
    }
    (args.output / "paper-quality-p0-qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
