from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import List, Sequence

import pytest

from tool_installer.errors import InstallationError
from tool_installer.executor import execute_plan
from tool_installer.managers.base import CheckResult
from tool_installer.managers.commands import AptManager, CargoInstallManager, NpmGlobalManager, RustupManager, UvToolManager
from tool_installer.models import Environment, InstallPlan, MergedStrategy, PlanItem, ToolReference, ToolSpec


@dataclass
class FakeManager:
    check_result: CheckResult = CheckResult.NOT_SATISFIED
    fail: bool = False
    events: List[str] = field(default_factory=list)

    def check(self, item: PlanItem) -> CheckResult:
        self.events.append(f"check:{item.tool.reference.name}")
        return self.check_result

    def install(self, item: PlanItem) -> None:
        self.events.append(f"install:{item.tool.reference.name}")
        if self.fail:
            raise InstallationError(f"failed {item.tool.reference.name}")


def item(name: str, manager: str = "fake", version: str = "latest", force: bool = False, allow_fail: bool = False, fields: dict | None = None) -> PlanItem:
    strategy_fields = {"manager": manager, **(fields or {})}
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name if version == "latest" else f"{name}@{version}", name=name, version=version), allow_fail=allow_fail),
        strategy=MergedStrategy(tool_name=name, manager=manager, fields=strategy_fields, force=force),
        environment=Environment(os="linux", arch="x86_64"),
    )


def test_executor_runs_serial_checks_skips_and_honors_force() -> None:
    first = FakeManager(check_result=CheckResult.SATISFIED)
    second = FakeManager(check_result=CheckResult.NOT_SATISFIED)
    plan = InstallPlan([item("a", "first"), item("b", "second", force=True)])

    execute_plan(plan, {"first": first, "second": second})

    assert first.events == ["check:a"]
    assert second.events == ["install:b"]


def test_executor_allow_fail_warns_and_continues() -> None:
    failing = FakeManager(fail=True)
    succeeding = FakeManager()
    plan = InstallPlan([item("a", "failing", allow_fail=True), item("b", "succeeding")])

    execute_plan(plan, {"failing": failing, "succeeding": succeeding})

    assert failing.events == ["check:a", "install:a"]
    assert succeeding.events == ["check:b", "install:b"]


def test_executor_non_allowed_failure_stops() -> None:
    failing = FakeManager(fail=True)
    later = FakeManager()
    plan = InstallPlan([item("a", "failing"), item("b", "later")])

    with pytest.raises(InstallationError):
        execute_plan(plan, {"failing": failing, "later": later})

    assert later.events == []


def test_executor_check_error_stops_without_fallback() -> None:
    """check_error must not fall back to install."""
    error_mgr = FakeManager(check_result=CheckResult.CHECK_ERROR)
    later = FakeManager()
    plan = InstallPlan([item("a", "error"), item("b", "later")])

    with pytest.raises(InstallationError, match="Check failed"):
        execute_plan(plan, {"error": error_mgr, "later": later})

    assert later.events == []


def test_executor_check_error_allow_fail_continues() -> None:
    """check_error with allow_fail should warn and continue."""
    error_mgr = FakeManager(check_result=CheckResult.CHECK_ERROR)
    succeeding = FakeManager()
    plan = InstallPlan([item("a", "error", allow_fail=True), item("b", "succeeding")])

    execute_plan(plan, {"error": error_mgr, "succeeding": succeeding})

    assert error_mgr.events == ["check:a"]
    assert succeeding.events == ["check:b", "install:b"]


def test_executor_force_bypasses_check() -> None:
    """force=True should bypass check entirely."""
    satisfied_mgr = FakeManager(check_result=CheckResult.SATISFIED)
    plan = InstallPlan([item("a", "satisfied", force=True)])

    execute_plan(plan, {"satisfied": satisfied_mgr})

    # Force bypasses check, goes straight to install
    assert satisfied_mgr.events == ["install:a"]


def test_command_managers_construct_expected_commands() -> None:
    apt = AptManager().install_command(item("python", "apt", version="3", fields={"pkg": "python3"}))
    cargo = CargoInstallManager().install_command(item("ripgrep", "cargo-install", version="latest", fields={"pkg": "ripgrep", "locked": True}))
    npm = NpmGlobalManager().install_command(item("qwen", "npm-global", version="1.2.3", fields={"pkg": "@qwen-code/qwen-code", "registry": "https://registry.npmjs.org"}))
    uv = UvToolManager().install_command(item("ruff", "uv-tool", version="0.6.0", fields={"pkg": "ruff", "with": ["x"]}))
    rustup = RustupManager().install_command(item("rust", "rustup", fields={"components": ["clippy"], "targets": ["wasm32-unknown-unknown"], "set_default": True}))

    assert apt == ["apt-get", "install", "-y", "python3=3"]
    assert cargo == ["cargo", "install", "ripgrep", "--locked"]
    assert npm == ["npm", "install", "-g", "@qwen-code/qwen-code@1.2.3", "--registry", "https://registry.npmjs.org"]
    assert uv == ["uv", "tool", "install", "ruff==0.6.0", "--with", "x"]
    assert rustup == ["rustup", "toolchain", "install", "stable", "--component", "clippy", "--target", "wasm32-unknown-unknown"]
