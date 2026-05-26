from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from tool_installer.environment import normalize_environment
from tool_installer.errors import StrategyError
from tool_installer.parser import parse_manifest_file, parse_tools_file
from tool_installer.resolver import collect_ordered_tools, resolve_modules
from tool_installer.strategy import build_install_plan
from tool_installer.managers.script import ScriptManager
from tool_installer.managers.base import CheckResult
from tool_installer.models import Environment, MergedStrategy, PlanItem, ToolReference, ToolSpec


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_script_check_returns_not_satisfied() -> None:
    """Script manager is not check-capable in v1."""
    mgr = ScriptManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="mytool", name="mytool", version="latest")),
        strategy=MergedStrategy(tool_name="mytool", manager="script", fields={"path": "/tmp/fake"}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    assert mgr.check(plan_item) == CheckResult.NOT_SATISFIED


def test_script_path_escapes_rejected(tmp_path: Path) -> None:
    """Script path must not escape manifest directory."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    script = tmp_path / "scripts" / "install.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nmytool = ''\n")
    write(
        manifest,
        """
[mytool]
[mytool.linux]
manager = "script"
path = "../escape.sh"
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="safe relative path"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_script_provides_env_vars(tmp_path: Path) -> None:
    """Script manager must provide required environment variables."""
    script = tmp_path / "capture-env.sh"
    script.write_text(
        "#!/bin/sh\n"
        "echo $TOOL_INSTALLER_TOOL_NAME > /tmp/tool_name\n"
        "echo $TOOL_INSTALLER_VERSION > /tmp/tool_version\n"
        "echo $TOOL_INSTALLER_OS > /tmp/tool_os\n"
        "echo $TOOL_INSTALLER_ARCH > /tmp/tool_arch\n"
        "echo $TOOL_INSTALLER_FORCE > /tmp/tool_force\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    mgr = ScriptManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="mytool", name="mytool", version="1.2.3")),
        strategy=MergedStrategy(tool_name="mytool", manager="script", fields={"path": str(script)}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    mgr.install(plan_item)

    assert Path("/tmp/tool_name").read_text().strip() == "mytool"
    assert Path("/tmp/tool_version").read_text().strip() == "1.2.3"
    assert Path("/tmp/tool_os").read_text().strip() == "linux"
    assert Path("/tmp/tool_arch").read_text().strip() == "x86_64"
    assert Path("/tmp/tool_force").read_text().strip() == "false"


def test_script_non_zero_exit_is_installation_error(tmp_path: Path) -> None:
    """Non-zero script exit is installation failure."""
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    mgr = ScriptManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="mytool", name="mytool", version="latest")),
        strategy=MergedStrategy(tool_name="mytool", manager="script", fields={"path": str(script)}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    with pytest.raises(Exception, match="Script failed"):
        mgr.install(plan_item)
