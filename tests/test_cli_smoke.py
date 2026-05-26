from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tool_installer.cli import main


def test_main_accepts_install_module_dry_run(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "install-tool"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    (tmp_path / "tools.toml").write_text("[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\ntool = ''\n", encoding="utf-8")
    (tmp_path / "manifest.toml").write_text("[tool]\n[tool.linux]\nmanager = 'script'\npath = 'install-tool'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["install", "dev", "--dry-run"]) == 0


def test_module_help_reaches_cli_entry_point() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "-m", "tool_installer", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "tool-installer" in result.stdout
    assert "install" in result.stdout
