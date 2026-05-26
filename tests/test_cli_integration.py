from __future__ import annotations

import os
import stat
from pathlib import Path

from tool_installer.cli import main


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_cli_dry_run_outputs_plan_without_installing(tmp_path: Path, monkeypatch, capsys) -> None:
    script = tmp_path / "install-ok"
    script.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    write(tmp_path / "tools.toml", "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\ntool = ''\n")
    write(tmp_path / "manifest.toml", "[tool]\n[tool.linux]\nmanager = 'script'\npath = 'install-ok'\n")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["install", "dev", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN module=dev tool=tool version=latest manager=script os=linux arch=x86_64" in captured.out
    assert captured.err == ""


def test_cli_reports_config_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    write(tmp_path / "tools.toml", "[tool-installer]\nmanifest = ''\n[dev]\n")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["install", "dev", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "❌ Error:" in captured.err


def test_example_dry_run_succeeds(monkeypatch, capsys) -> None:
    project = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(project / "examples")

    exit_code = main(["install", "dev", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "tool=python" in captured.out
    assert "tool=example-release" in captured.out
