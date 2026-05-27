"""Single-file distribution tests."""
from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, Optional

MAX_ARTIFACT_BYTES = 400 * 1024


def run(
    args,
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(map(str, args)),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def test_build_single_creates_small_executable_with_vendored_toml(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    output = tmp_path / "tool-installer"

    result = run([project / "scripts" / "build-single", "--output", output])

    assert "built" in result.stdout
    assert output.is_file()
    assert os.access(output, os.X_OK)
    assert output.stat().st_size <= MAX_ARTIFACT_BYTES

    with output.open("rb") as f:
        assert f.readline() == b"#!/usr/bin/env python3\n"
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
    assert "__main__.py" in names
    assert "tool_installer/cli.py" in names
    assert "tool_installer/vendor/tomli/_parser.py" in names

    help_result = run([output, "--help"])
    assert "install" in help_result.stdout

    dry_run = run([output, "install", "dev", "--dry-run"], cwd=project / "examples")
    assert "PLAN " in dry_run.stdout
    assert "tool=example-script" in dry_run.stdout
    assert dry_run.stderr == ""

    sitecustomize_dir = tmp_path / "sitecustomize"
    sitecustomize_dir.mkdir()
    (sitecustomize_dir / "sitecustomize.py").write_text(
        "import builtins\n"
        "_real_import = builtins.__import__\n"
        "def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    if name == 'tomllib':\n"
        "        raise ModuleNotFoundError(\"No module named 'tomllib'\")\n"
        "    return _real_import(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = _blocked_import\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(sitecustomize_dir)
    fallback_dry_run = run([output, "install", "dev", "--dry-run"], cwd=project / "examples", env=env)
    assert "tool=example-release" in fallback_dry_run.stdout


def test_install_single_installs_only_after_downloaded_artifact_validates(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    artifact = tmp_path / "source-tool-installer"
    dest = tmp_path / "bin" / "tool-installer"

    run([project / "scripts" / "build-single", "--output", artifact])
    install = run([project / "scripts" / "install-single", artifact.as_uri(), dest])

    assert "Installed tool-installer" in install.stdout
    assert dest.is_file()
    assert os.access(dest, os.X_OK)
    help_result = run([dest, "--help"])
    assert "install" in help_result.stdout


def test_install_single_does_not_replace_existing_file_when_download_invalid(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    invalid = tmp_path / "not-a-tool-installer"
    dest = tmp_path / "bin" / "tool-installer"
    dest.parent.mkdir()
    dest.write_text("existing working version", encoding="utf-8")
    invalid.write_text("this is not a valid executable artifact", encoding="utf-8")

    result = subprocess.run(
        [str(project / "scripts" / "install-single"), invalid.as_uri(), str(dest)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert dest.read_text(encoding="utf-8") == "existing working version"
