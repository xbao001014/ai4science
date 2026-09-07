"""Plan/apply conservative Method and Disease alias consolidation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.entity_alias_merge import merge_known_entity_aliases  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the transaction. Without this flag the command is read-only.",
    )
    parser.add_argument("--show", type=int, default=20, help="Number of groups to print")
    args = parser.parse_args()
    result = merge_known_entity_aliases(apply=args.apply)
    summary = {key: value for key, value in result.items() if key != "groups"}
    summary["sample_groups"] = result["groups"][: max(0, args.show)]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
