"""Run selected existing tests in a temporary DB sandbox, with network denied."""
import argparse
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent))
TESTS = ["test_bind_tools_sql_args", "test_select_tool_bundle", "test_sql_call_budget",
         "test_disallow_duplicate_tools", "test_phantom_format_tool", "test_idea_session_guards",
         "test_gap_agent_tool_slim", "test_idea_agent_tool_slim", "test_study_prompts",
         "test_study_policy", "test_study_type_downstream", "test_execute_kg_sql",
         "test_idea_agent_baseline_accept", "test_idea_agent_sql_guidance", "test_gap_agent_sql_guidance"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    import config
    import pytest
    records = []
    class Recorder:
        def pytest_runtest_logreport(self, report):
            if report.when == "call" or (report.when == "setup" and report.failed):
                records.append({"test":report.nodeid,"status":report.outcome,
                                "detail":str(report.longrepr) if report.failed else ""})
    def deny(*a, **kw): raise RuntimeError("REGRESSION NETWORK DENIED")
    with tempfile.TemporaryDirectory(prefix="paper-regression-") as tmp, \
         patch.object(socket.socket,"connect",deny), patch.object(socket,"create_connection",deny):
        config.DB_PATH = str(Path(tmp)/"tests.db")
        config.DATA_DIR = config.OUTPUT_DIR = tmp
        config.OPENAI_API_KEY = "offline-placeholder"
        config.OPENAI_API_BASE = "http://127.0.0.1:1/v1"
        from db.schema import init_db
        init_db()
        code = pytest.main([str(ROOT/"tests"/(n+".py")) for n in TESTS] + ["-q", "--tb=short", "-p", "no:cacheprovider"], plugins=[Recorder()])
    (args.output/"regression.json").write_text(json.dumps({"exit_code":int(code),"tests":records,
        "passed":sum(r["status"]=="passed" for r in records),"total":len(records)},ensure_ascii=False,indent=2),encoding="utf-8")
    raise SystemExit(code)


if __name__=="__main__": main()
