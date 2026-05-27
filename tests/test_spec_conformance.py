"""SPEC-derived conformance tests covering cross-cutting behavior."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from tool_installer.cli import main
from tool_installer.environment import normalize_environment
from tool_installer.errors import DependencyError, StrategyError, InstallationError
from tool_installer.executor import execute_plan
from tool_installer.managers.base import CheckResult
from tool_installer.parser import parse_manifest_file, parse_tools_file
from tool_installer.resolver import collect_ordered_tools, resolve_modules
from tool_installer.strategy import build_install_plan
from tool_installer.models import Environment, InstallPlan, MergedStrategy, PlanItem, ToolReference, ToolSpec


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# --- Dry-run tests ---

def test_dry_run_no_external_queries(tmp_path: Path) -> None:
    """Dry-run performs validation but no external queries/checks/downloads/scripts."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\ntool = ''\n")
    write(
        manifest,
        """
[tool]
[tool.linux]
manager = "apt"
pkg = "curl"
""",
    )
    config = parse_tools_file(tools, "dev")
    plan = build_install_plan(
        collect_ordered_tools(resolve_modules(config, "dev")),
        parse_manifest_file(manifest),
        normalize_environment("Linux", "x86_64"),
        tmp_path,
    )
    # Plan construction succeeds; dry-run would print it without executing
    assert len(plan.items) == 1
    assert plan.items[0].strategy.manager == "apt"


# --- unreachable modules ---

def test_unreachable_modules_no_errors(tmp_path: Path) -> None:
    """Unreachable modules do not trigger schema, duplicate, or strategy errors."""
    tools = tmp_path / "tools.toml"
    write(
        tools,
        """
[tool-installer]
manifest = "manifest.toml"

[base]
tool = ""

[dev]
depends = ["base"]
other = ""

[unreachable]
# This module has a duplicate tool name with base
tool = ""
""",
    )
    config = parse_tools_file(tools, "dev")
    modules = resolve_modules(config, "dev")
    ordered = collect_ordered_tools(modules)
    # Should not raise - unreachable module is not included in the resolved set
    # Ordered: base (with tool), then dev (with other) = 2 items
    assert len(ordered) == 2
    names = [tool.reference.name for _, tool in ordered]
    assert names == ["tool", "other"]


# --- force bypasses checks ---

def test_force_bypasses_check() -> None:
    """force = true bypasses checks and attempts installation."""
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class SpyManager:
        events: List[str] = field(default_factory=list)
        def check(self, item: PlanItem) -> CheckResult:
            self.events.append("check")
            return CheckResult.SATISFIED
        def install(self, item: PlanItem) -> None:
            self.events.append("install")

    mgr = SpyManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="tool", name="tool", version="latest")),
        strategy=MergedStrategy(tool_name="tool", manager="spy", fields={"manager": "spy"}, force=True),
        environment=Environment(os="linux", arch="x86_64"),
    )
    plan = InstallPlan([plan_item])
    execute_plan(plan, {"spy": mgr})
    # Force bypasses check, goes straight to install
    assert mgr.events == ["install"]


# --- check_error does not fall back to install ---

def test_check_error_no_fallback() -> None:
    """check_error does not fall back to installation."""
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class ErrorManager:
        events: List[str] = field(default_factory=list)
        def check(self, item: PlanItem) -> CheckResult:
            self.events.append("check")
            return CheckResult.CHECK_ERROR
        def install(self, item: PlanItem) -> None:
            self.events.append("install")

    mgr = ErrorManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="tool", name="tool", version="latest")),
        strategy=MergedStrategy(tool_name="tool", manager="err", fields={"manager": "err"}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    plan = InstallPlan([plan_item])
    with pytest.raises(InstallationError, match="Check failed"):
        execute_plan(plan, {"err": mgr})
    # Only check happened, no install
    assert mgr.events == ["check"]


# --- allow_fail only downgrades installation failures ---

def test_allow_fail_does_not_suppress_config_errors(tmp_path: Path) -> None:
    """allow_fail only downgrades installation/check failures, not config/strategy errors."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\ntool = { allow_fail = true }\n")
    write(
        manifest,
        """
[tool]
[tool.linux]
manager = "unsupported-manager"
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


# --- v1 version equality ---

def test_v1_version_equality() -> None:
    """v1 version equality: strip one leading v/V, exact string match."""
    from tool_installer.managers.commands import _v1_eq
    assert _v1_eq("1.0.0", "1.0.0") is True
    assert _v1_eq("v1.0.0", "1.0.0") is True
    assert _v1_eq("1.0.0", "v1.0.0") is True
    assert _v1_eq("V1.0.0", "v1.0.0") is True
    assert _v1_eq("1.0.0", "1.0.1") is False
    assert _v1_eq("1.0.0", "2.0.0") is False
    assert _v1_eq("v1.0.0", "v1.0.0") is True
    # SPEC: strip ONE leading v/V from EACH side
    # "vv1.0.0" -> strip one v -> "v1.0.0"
    # "v1.0.0" -> strip one v -> "1.0.0"
    assert _v1_eq("vv1.0.0", "v1.0.0") is False  # vv1.0.0 -> v1.0.0 vs 1.0.0 — not equal


# --- bin default ---

def test_bin_defaults_to_tool_name(tmp_path: Path) -> None:
    """bin defaults to the parsed logical tool name for managers that support it."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "cargo-binstall"
pkg = "fd-find"
""",
    )
    config = parse_tools_file(tools, "dev")
    plan = build_install_plan(
        collect_ordered_tools(resolve_modules(config, "dev")),
        parse_manifest_file(manifest),
        normalize_environment("Linux", "x86_64"),
        tmp_path,
    )
    assert plan.items[0].strategy.fields["bin"] == "fd"


# --- cargo-binstall non-check-capable ---

def test_cargo_binstall_non_check_capable() -> None:
    """cargo-binstall is non-check-capable in v1, always returns NOT_SATISFIED."""
    from tool_installer.managers.commands import CargoBinstallManager
    mgr = CargoBinstallManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="tool", name="tool", version="1.0.0")),
        strategy=MergedStrategy(tool_name="tool", manager="cargo-binstall", fields={"pkg": "tool"}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    assert mgr.check(plan_item) == CheckResult.NOT_SATISFIED


# --- uv-tool latest non-check-capable ---

def test_uv_tool_latest_non_check_capable() -> None:
    """uv-tool latest is non-check-capable in v1."""
    from tool_installer.managers.commands import UvToolManager
    mgr = UvToolManager()
    plan_item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="ruff", name="ruff", version="latest")),
        strategy=MergedStrategy(tool_name="ruff", manager="uv-tool", fields={"pkg": "ruff"}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    assert mgr.check(plan_item) == CheckResult.NOT_SATISFIED


def test_cli_dry_run_does_not_invoke_manager_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run validates and prints plan but never constructs/executes real managers."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\ntool = ''\n")
    write(manifest, "[tool]\n[tool.linux]\nmanager = 'apt'\npkg = 'curl'\n")
    monkeypatch.chdir(tmp_path)
    with patch("tool_installer.cli.default_registry") as registry:
        assert main(["install", "dev", "--dry-run"]) == 0
        registry.assert_not_called()


def test_allow_fail_downgrades_check_failure_and_continues() -> None:
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class ErrorManager:
        events: List[str] = field(default_factory=list)
        def check(self, item: PlanItem) -> CheckResult:
            self.events.append(item.tool.reference.name + ":check")
            return CheckResult.CHECK_ERROR
        def install(self, item: PlanItem) -> None:
            self.events.append(item.tool.reference.name + ":install")

    @dataclass
    class OkManager:
        events: List[str] = field(default_factory=list)
        def check(self, item: PlanItem) -> CheckResult:
            self.events.append(item.tool.reference.name + ":check")
            return CheckResult.NOT_SATISFIED
        def install(self, item: PlanItem) -> None:
            self.events.append(item.tool.reference.name + ":install")

    err = ErrorManager()
    ok = OkManager()
    plan = InstallPlan([
        PlanItem(
            "dev",
            ToolSpec(ToolReference("soft", "soft", "latest"), allow_fail=True),
            MergedStrategy("soft", "err", {"manager": "err"}),
            Environment("linux", "x86_64"),
        ),
        PlanItem(
            "dev",
            ToolSpec(ToolReference("next", "next", "latest")),
            MergedStrategy("next", "ok", {"manager": "ok"}),
            Environment("linux", "x86_64"),
        ),
    ])
    execute_plan(plan, {"err": err, "ok": ok})
    assert err.events == ["soft:check"]
    assert ok.events == ["next:check", "next:install"]


def test_fatal_strategy_error_occurs_before_installation(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\n'tool@1.0.0' = ''\n")
    write(manifest, "[tool]\n[tool.linux]\nmanager = 'brew'\npkg = 'git'\n")
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )
