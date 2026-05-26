"""Example fixture tests."""
from __future__ import annotations

from pathlib import Path

from tool_installer.cli import main


def test_examples_dry_run_succeeds(monkeypatch, capsys) -> None:
    examples = Path(__file__).resolve().parent.parent / "examples"
    monkeypatch.chdir(examples)
    assert main(["install", "dev", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "python" in out
    assert "rust" in out
    assert "example-script" in out
    assert "qwen-code" in out
    assert "example-release" in out
