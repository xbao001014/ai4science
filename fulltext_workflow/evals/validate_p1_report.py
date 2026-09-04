"""Static integrity checks for the P1 HTML report and evidence package."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = args.output / "paper-quality-p1.html"
    manifest_path = args.output / "paper-quality-p1-manifest.json"
    evidence = args.output / "paper-quality-p1-evidence.zip"
    text = report.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inspector = Inspector()
    inspector.feed(text)
    checks = {}
    checks["doctype_and_charset"] = text.lower().startswith("<!doctype html>") and "charset='utf-8'" in text.lower()
    checks["required_sections"] = set(("outcome", "changes", "offline", "failures", "live", "regression", "limits", "reproduce")) <= inspector.ids
    checks["no_replacement_characters"] = "�" not in text
    checks["scope_exclusion_visible"] = "没有启动领域专家标注" in text and "不测研究价值" in text
    local_links = [link for link in inspector.links if not link.startswith(("#", "http://", "https://"))]
    checks["local_links_exist"] = all((args.output / link).exists() for link in local_links)
    checks["report_nontrivial"] = report.stat().st_size > 9000
    checks["manifest_source_hashes"] = all(
        hashlib.sha256((ROOT / name).resolve().read_bytes()).hexdigest() == digest
        for name, digest in manifest["source_sha256"].items()
    )
    try:
        with zipfile.ZipFile(evidence) as archive:
            bad = archive.testzip()
            names = set(archive.namelist())
        checks["evidence_zip_integrity"] = bad is None
        checks["evidence_has_failure_and_final"] = {
            "runs/final/results.json", "runs/final-v4/results.json",
            "runs/live-chain/results.json", "runs/live-chain-v2/results.json",
        } <= names
    except Exception:
        checks["evidence_zip_integrity"] = False
        checks["evidence_has_failure_and_final"] = False
    qa = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "note": "Static artifact QA only; no domain-expert or research-direction-quality review.",
    }
    qa_path = args.output / "paper-quality-p1-qa.json"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["artifact_qa"] = qa["status"] + "_static"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    temp_zip = evidence.with_suffix(".tmp.zip")
    with zipfile.ZipFile(evidence) as source, zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename not in {manifest_path.name, qa_path.name}:
                target.writestr(item, source.read(item.filename))
        target.write(manifest_path, manifest_path.name)
        target.write(qa_path, qa_path.name)
    temp_zip.replace(evidence)
    print(json.dumps(qa, ensure_ascii=False, indent=2))
    raise SystemExit(0 if qa["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
