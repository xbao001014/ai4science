"""Isolated 30-paper before/after run for paper-local entity annotations."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from db.schema import init_db  # noqa: E402
from evals.entity_context_30 import freeze  # noqa: E402
from evals.finalize_entity_mentions_30 import finalize  # noqa: E402
from extractor.section_extractor import run_extraction  # noqa: E402


def main(source_db: Path, eval_db: Path, pmid_file: Path, output: Path) -> None:
    source_db, eval_db = source_db.resolve(), eval_db.resolve()
    if source_db == eval_db or eval_db == Path(config.DB_PATH).resolve():
        raise ValueError("Evaluation requires a separate database")
    if eval_db.exists():
        raise FileExistsError(f"Refusing to replace existing evaluation DB: {eval_db}")
    pmids = [line.strip() for line in pmid_file.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if len(pmids) != 30 or len(set(pmids)) != 30:
        raise ValueError("Expected 30 unique PMIDs")

    output.mkdir(parents=True, exist_ok=True)
    before = output / "before.json"
    freeze(source_db, before, pmid_file)
    eval_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_db) as src, sqlite3.connect(eval_db) as dst:
        src.backup(dst)
    config.DB_PATH = str(eval_db)
    config.EXTRACT_ENTITY_MENTION_ANNOTATIONS = True
    # The previous broad abbreviation prompt is intentionally left disabled.
    config.EXTRACT_METHOD_CONTEXT_PROMPT = False
    init_db()
    run_extraction(pmids=pmids, force_reextract=True)
    print(json.dumps(finalize(eval_db, pmid_file, output), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--eval-db", type=Path, required=True)
    parser.add_argument("--pmids", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.source_db, args.eval_db, args.pmids, args.output)
