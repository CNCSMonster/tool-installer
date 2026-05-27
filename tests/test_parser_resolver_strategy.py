from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tool_installer.environment import normalize_environment
from tool_installer.errors import ConfigError, DependencyError, ManifestError, StrategyError
from tool_installer.parser import parse_manifest_file, parse_tools_file
from tool_installer.resolver import collect_ordered_tools, resolve_modules
from tool_installer.strategy import build_install_plan


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_parse_tools_file_accepts_reachable_modules_and_tool_values(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    write(
        tools,
        """
[tool-installer]
manifest = "./manifest.toml"

[base]
python = "Python runtime"
"ruff@0.6.0" = { desc = "linter", allow_fail = true }

[dev]
depends = ["base"]
node = {}

[unreachable]
bad = { unknown = true }
""",
    )

    config = parse_tools_file(tools, "dev")

    assert config.manifest_path == tmp_path / "manifest.toml"
    assert config.modules["base"].tools[0].reference.version == "latest"
    assert config.modules["base"].tools[1].allow_fail is True


def test_parse_tools_file_rejects_global_installer_errors(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    write(tools, "[tool-installer]\nmanifest = './manifest.toml'\nextra = true\n[dev]\n")

    with pytest.raises(ConfigError):
        parse_tools_file(tools, "dev")


def test_resolver_preserves_dependency_order_and_deduplicates_diamonds(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    write(
        tools,
        """
[tool-installer]
manifest = "manifest.toml"
[shared]
a = ""
[left]
depends = ["shared"]
b = ""
[right]
depends = ["shared"]
c = ""
[dev]
depends = ["left", "right"]
d = ""
""",
    )
    config = parse_tools_file(tools, "dev")

    modules = resolve_modules(config, "dev")

    assert [module.name for module in modules] == ["shared", "left", "right", "dev"]


def test_resolver_detects_cycles_and_duplicate_selected_tools(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    write(
        tools,
        """
[tool-installer]
manifest = "manifest.toml"
[a]
depends = ["b"]
dup = ""
[b]
depends = ["a"]
other = ""
""",
    )
    config = parse_tools_file(tools, "a")
    with pytest.raises(DependencyError):
        resolve_modules(config, "a")

    write(
        tools,
        """
[tool-installer]
manifest = "manifest.toml"
[a]
dup = ""
[b]
depends = ["a"]
"dup@1" = ""
[unreachable]
dup = ""
""",
    )
    config = parse_tools_file(tools, "b")
    with pytest.raises(DependencyError):
        collect_ordered_tools(resolve_modules(config, "b"))


def test_manifest_and_strategy_merge_validate_current_environment(tmp_path: Path) -> None:
    script = tmp_path / "install-tool"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\ntool = { allow_fail = true }\n")
    write(
        manifest,
        """
[tool]
manager = "script"
force = false
[tool.linux]
path = "install-tool"
[tool.linux.x86_64]
force = true
""",
    )

    config = parse_tools_file(tools, "dev")
    manifest_data, _ = parse_manifest_file(manifest)
    plan = build_install_plan(
        collect_ordered_tools(resolve_modules(config, "dev")),
        manifest_data,
        normalize_environment("Linux", "x86_64"),
        tmp_path,
    )

    item = plan.items[0]
    assert item.strategy.manager == "script"
    assert item.strategy.force is True
    assert item.strategy.fields["path"] == str(script.resolve())
    assert item.tool.allow_fail is True


def test_strategy_rejects_unsupported_and_manager_specific_errors(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\n'brewtool@1' = ''\n")
    write(manifest, "[brewtool]\n[brewtool.linux]\nmanager = 'brew'\npkg = 'brewtool'\n")
    config = parse_tools_file(tools, "dev")
    manifest_data, _ = parse_manifest_file(manifest)

    with pytest.raises(StrategyError):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            manifest_data,
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_environment_rejects_unsupported_platform() -> None:
    with pytest.raises(StrategyError):
        normalize_environment("Windows", "x86_64")
    with pytest.raises(StrategyError):
        normalize_environment("Linux", "riscv64")
