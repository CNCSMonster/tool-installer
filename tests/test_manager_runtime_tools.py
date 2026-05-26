"""Tests for npm, pnpm, and uv-tool manager checks."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from typing import Any, Dict, List

import pytest

from tool_installer.managers.commands import NpmGlobalManager, PnpmGlobalManager, UvToolManager
from tool_installer.managers.base import CheckResult
from tool_installer.models import PlanItem, ToolSpec, ToolReference, MergedStrategy, Environment


def item(name: str, version: str, fields: dict) -> PlanItem:
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name, name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager="npm-global", fields=fields, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )


def item_pnpm(name: str, version: str, fields: dict) -> PlanItem:
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name, name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager="pnpm-global", fields=fields, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )


def item_uv(name: str, version: str, fields: dict) -> PlanItem:
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name, name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager="uv-tool", fields=fields, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )


def make_runner(stdout: str = "", returncode: int = 0) -> MagicMock:
    runner = MagicMock()
    runner.run.return_value = MagicMock(stdout=stdout, returncode=returncode)
    return runner


def make_runner_multi(responses: List[Dict[str, Any]]) -> MagicMock:
    runner = MagicMock()
    runner.run.side_effect = [MagicMock(stdout=r.get("stdout", ""), returncode=r.get("returncode", 0)) for r in responses]
    return runner


# --- NpmGlobalManager tests ---

def test_npm_check_not_installed() -> None:
    data = {"dependencies": {}}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_npm_check_installed_exact_match() -> None:
    data = {"dependencies": {"typescript": {"version": "5.0.0"}}}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_npm_check_installed_mismatch() -> None:
    data = {"dependencies": {"typescript": {"version": "4.9.5"}}}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_npm_check_latest_matches_registry() -> None:
    data = {"dependencies": {"typescript": {"version": "5.0.0"}}}
    runner = make_runner_multi([
        {"stdout": json.dumps(data), "returncode": 0},
        {"stdout": json.dumps("5.0.0"), "returncode": 0},
    ])
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "latest", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_npm_check_latest_outdated() -> None:
    data = {"dependencies": {"typescript": {"version": "4.9.5"}}}
    runner = make_runner_multi([
        {"stdout": json.dumps(data), "returncode": 0},
        {"stdout": json.dumps("5.0.0"), "returncode": 0},
    ])
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "latest", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_npm_check_oserror_is_check_error() -> None:
    runner = MagicMock()
    runner.run.side_effect = OSError("command not found")
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_npm_check_with_registry() -> None:
    data = {"dependencies": {"typescript": {"version": "5.0.0"}}}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = NpmGlobalManager(runner)
    plan = item("typescript", "5.0.0", {"pkg": "typescript", "registry": "https://registry.example.com"})
    mgr.check(plan)
    runner.run.assert_called_once()
    call_args = runner.run.call_args[0][0]
    assert "--registry" in call_args
    assert "https://registry.example.com" in call_args


def test_npm_install_command_latest() -> None:
    mgr = NpmGlobalManager()
    plan = item("typescript", "latest", {"pkg": "typescript"})
    assert mgr.install_command(plan) == ["npm", "install", "-g", "typescript"]


def test_npm_install_command_exact() -> None:
    mgr = NpmGlobalManager()
    plan = item("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.install_command(plan) == ["npm", "install", "-g", "typescript@5.0.0"]


# --- PnpmGlobalManager tests ---

def test_pnpm_check_not_installed() -> None:
    runner = make_runner(stdout="[]", returncode=0)
    mgr = PnpmGlobalManager(runner)
    plan = item_pnpm("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_pnpm_check_installed_exact_match() -> None:
    data = [{"name": "typescript", "version": "5.0.0"}]
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = PnpmGlobalManager(runner)
    plan = item_pnpm("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_pnpm_check_installed_mismatch() -> None:
    data = [{"name": "typescript", "version": "4.9.5"}]
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = PnpmGlobalManager(runner)
    plan = item_pnpm("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_pnpm_check_latest_matches_registry() -> None:
    data = [{"name": "typescript", "version": "5.0.0"}]
    runner = make_runner_multi([
        {"stdout": json.dumps(data), "returncode": 0},
        {"stdout": json.dumps("5.0.0"), "returncode": 0},
    ])
    mgr = PnpmGlobalManager(runner)
    plan = item_pnpm("typescript", "latest", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_pnpm_check_latest_outdated() -> None:
    data = [{"name": "typescript", "version": "4.9.5"}]
    runner = make_runner_multi([
        {"stdout": json.dumps(data), "returncode": 0},
        {"stdout": json.dumps("5.0.0"), "returncode": 0},
    ])
    mgr = PnpmGlobalManager(runner)
    plan = item_pnpm("typescript", "latest", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_pnpm_check_oserror_is_check_error() -> None:
    runner = MagicMock()
    runner.run.side_effect = OSError("command not found")
    mgr = PnpmGlobalManager(runner)
    plan = item_pnpm("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_pnpm_install_command_latest() -> None:
    mgr = PnpmGlobalManager()
    plan = item_pnpm("typescript", "latest", {"pkg": "typescript"})
    assert mgr.install_command(plan) == ["pnpm", "add", "-g", "typescript"]


def test_pnpm_install_command_exact() -> None:
    mgr = PnpmGlobalManager()
    plan = item_pnpm("typescript", "5.0.0", {"pkg": "typescript"})
    assert mgr.install_command(plan) == ["pnpm", "add", "-g", "typescript@5.0.0"]


# --- UvToolManager tests ---

def test_uv_tool_latest_non_check_capable() -> None:
    mgr = UvToolManager()
    plan = item_uv("ruff", "latest", {"pkg": "ruff"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_uv_tool_check_installed_exact_match() -> None:
    data = {
        "tools": [{
            "name": "ruff",
            "specifiers": ["ruff==0.4.0"],
        }]
    }
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = UvToolManager(runner)
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_uv_tool_check_installed_mismatch() -> None:
    data = {
        "tools": [{
            "name": "ruff",
            "specifiers": ["ruff==0.3.0"],
        }]
    }
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = UvToolManager(runner)
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_uv_tool_check_not_found() -> None:
    data = {"tools": [{"name": "black", "specifiers": ["black==24.0.0"]}]}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = UvToolManager(runner)
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_uv_tool_check_oserror_is_check_error() -> None:
    runner = MagicMock()
    runner.run.side_effect = OSError("command not found")
    mgr = UvToolManager(runner)
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_uv_tool_install_command_latest() -> None:
    mgr = UvToolManager()
    plan = item_uv("ruff", "latest", {"pkg": "ruff"})
    assert mgr.install_command(plan) == ["uv", "tool", "install", "ruff"]


def test_uv_tool_install_command_exact() -> None:
    mgr = UvToolManager()
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff"})
    assert mgr.install_command(plan) == ["uv", "tool", "install", "ruff==0.4.0"]


def test_uv_tool_install_command_with_python() -> None:
    mgr = UvToolManager()
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff", "python": "3.12"})
    assert mgr.install_command(plan) == ["uv", "tool", "install", "ruff==0.4.0", "--python", "3.12"]


def test_uv_tool_install_command_with_dependencies() -> None:
    mgr = UvToolManager()
    plan = item_uv("ruff", "0.4.0", {"pkg": "ruff", "with": ["dep1", "dep2"]})
    assert mgr.install_command(plan) == ["uv", "tool", "install", "ruff==0.4.0", "--with", "dep1", "--with", "dep2"]
