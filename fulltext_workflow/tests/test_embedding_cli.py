from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_embedding_key_reuse_requires_dashscope_bases(monkeypatch):
    import config

    monkeypatch.setattr(config, "EMBEDDING_API_KEY", "")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "")
    monkeypatch.setattr(config, "_EXPLICIT_OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(
        config,
        "EMBEDDING_API_BASE",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(
        config,
        "OPENAI_API_BASE",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    assert config.embedding_key_and_source() == ("openai-key", "OPENAI_API_KEY")
    monkeypatch.setattr(config, "EMBEDDING_API_BASE", "https://example.com/v1")
    assert config.embedding_key_and_source() == ("", "missing")


def test_preflight_is_offline_and_does_not_print_key(tmp_path, monkeypatch, capsys):
    import config
    import main

    secret = "sk-test-secret-123456"
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "preflight.sqlite"))
    monkeypatch.setattr(config, "EMBEDDING_API_KEY", secret)
    main.cmd_embedding_preflight(argparse.Namespace(live_probe=False))
    output = capsys.readouterr().out
    assert secret not in output
    start = output.index("{")
    payload = json.loads(output[start:])
    assert payload["network_called"] is False
    assert payload["key_source"] == "EMBEDDING_API_KEY"


def test_plan_rejects_non_dry_run():
    import main

    with pytest.raises(SystemExit, match="requires --dry-run"):
        main.cmd_embedding_plan(argparse.Namespace(dry_run=False, limit=None))
