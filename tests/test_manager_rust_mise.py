"""Tests for cargo, rustup, and mise manager checks."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from typing import Any, Dict, List

from tool_installer.errors import InstallationError
from tool_installer.managers.base import CheckResult
from tool_installer.managers.commands import CargoBinstallManager, CargoInstallManager, MiseManager, RustupManager
from tool_installer.models import Environment, MergedStrategy, PlanItem, ToolReference, ToolSpec


def item(manager: str, name: str, version: str, fields: dict) -> PlanItem:
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name, name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager=manager, fields=fields, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )


def runner(stdout: str = "", returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.run.return_value = MagicMock(stdout=stdout, returncode=returncode)
    return r


def runner_multi(responses: List[Dict[str, Any]]) -> MagicMock:
    r = MagicMock()
    r.run.side_effect = [MagicMock(stdout=x.get("stdout", ""), returncode=x.get("returncode", 0)) for x in responses]
    return r


# cargo-binstall

def test_cargo_binstall_non_check_capable() -> None:
    assert CargoBinstallManager().check(item("cargo-binstall", "ripgrep", "latest", {"pkg": "ripgrep"})) == CheckResult.NOT_SATISFIED


def test_cargo_binstall_commands() -> None:
    mgr = CargoBinstallManager()
    assert mgr.install_command(item("cargo-binstall", "ripgrep", "latest", {"pkg": "ripgrep"})) == ["cargo", "binstall", "-y", "ripgrep"]
    assert mgr.install_command(item("cargo-binstall", "ripgrep", "1.0.0", {"pkg": "ripgrep"})) == ["cargo", "binstall", "-y", "ripgrep", "--version", "1.0.0"]


# cargo-install

def test_cargo_install_exact_satisfied() -> None:
    out = "ripgrep v14.1.0:\n    rg\n"
    mgr = CargoInstallManager(runner(out))
    assert mgr.check(item("cargo-install", "ripgrep", "14.1.0", {"pkg": "ripgrep"})) == CheckResult.SATISFIED


def test_cargo_install_exact_mismatch() -> None:
    out = "ripgrep v14.0.0:\n    rg\n"
    mgr = CargoInstallManager(runner(out))
    assert mgr.check(item("cargo-install", "ripgrep", "14.1.0", {"pkg": "ripgrep"})) == CheckResult.NOT_SATISFIED


def test_cargo_install_not_installed() -> None:
    out = "fd-find v10.0.0:\n    fd\n"
    mgr = CargoInstallManager(runner(out))
    assert mgr.check(item("cargo-install", "ripgrep", "14.1.0", {"pkg": "ripgrep"})) == CheckResult.NOT_SATISFIED


def test_cargo_install_latest_satisfied_from_registry_metadata() -> None:
    mgr = CargoInstallManager(runner_multi([
        {"stdout": "ripgrep v14.1.0:\n    rg\n", "returncode": 0},
        {"stdout": "ripgrep = \"14.1.0\" # search recursively\n", "returncode": 0},
    ]))
    assert mgr.check(item("cargo-install", "ripgrep", "latest", {"pkg": "ripgrep"})) == CheckResult.SATISFIED


def test_cargo_install_latest_outdated_from_registry_metadata() -> None:
    mgr = CargoInstallManager(runner_multi([
        {"stdout": "ripgrep v14.0.0:\n    rg\n", "returncode": 0},
        {"stdout": "ripgrep = \"14.1.0\" # search recursively\n", "returncode": 0},
    ]))
    assert mgr.check(item("cargo-install", "ripgrep", "latest", {"pkg": "ripgrep"})) == CheckResult.NOT_SATISFIED


def test_cargo_install_git_check_error() -> None:
    mgr = CargoInstallManager(runner(""))
    assert mgr.check(item("cargo-install", "tool", "latest", {"pkg": "tool", "git": "https://example/repo.git"})) == CheckResult.CHECK_ERROR


def test_cargo_install_command_exact_locked() -> None:
    mgr = CargoInstallManager()
    assert mgr.install_command(item("cargo-install", "ripgrep", "14.1.0", {"pkg": "ripgrep", "locked": True})) == ["cargo", "install", "ripgrep", "--locked", "--version", "14.1.0"]


def test_cargo_install_command_git_rev() -> None:
    mgr = CargoInstallManager()
    assert mgr.install_command(item("cargo-install", "tool", "latest", {"pkg": "tool", "git": "https://example/repo.git", "rev": "abc"})) == ["cargo", "install", "tool", "--git", "https://example/repo.git", "--rev", "abc"]


# mise

def test_mise_exact_satisfied_list_output() -> None:
    mgr = MiseManager(runner(json.dumps([{"version": "20.0.0"}])))
    assert mgr.check(item("mise", "node", "20.0.0", {"plugin": "node"})) == CheckResult.SATISFIED


def test_mise_exact_satisfied_dict_output() -> None:
    mgr = MiseManager(runner(json.dumps({"versions": [{"version": "20.0.0"}]})))
    assert mgr.check(item("mise", "node", "20.0.0", {"plugin": "node"})) == CheckResult.SATISFIED


def test_mise_exact_not_satisfied() -> None:
    mgr = MiseManager(runner(json.dumps([{"version": "18.0.0"}])))
    assert mgr.check(item("mise", "node", "20.0.0", {"plugin": "node"})) == CheckResult.NOT_SATISFIED


def test_mise_latest_satisfied() -> None:
    mgr = MiseManager(runner_multi([
        {"stdout": json.dumps([{"version": "20.0.0"}]), "returncode": 0},
        {"stdout": "20.0.0\n", "returncode": 0},
    ]))
    assert mgr.check(item("mise", "node", "latest", {"plugin": "node"})) == CheckResult.SATISFIED


def test_mise_latest_outdated() -> None:
    mgr = MiseManager(runner_multi([
        {"stdout": json.dumps([{"version": "18.0.0"}]), "returncode": 0},
        {"stdout": "20.0.0\n", "returncode": 0},
    ]))
    assert mgr.check(item("mise", "node", "latest", {"plugin": "node"})) == CheckResult.NOT_SATISFIED


def test_mise_command() -> None:
    assert MiseManager().install_command(item("mise", "node", "20.0.0", {"plugin": "node"})) == ["mise", "install", "node@20.0.0"]


# rustup

def test_rustup_toolchain_missing() -> None:
    mgr = RustupManager(runner_multi([
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "nightly-x86_64-unknown-linux-gnu", "returncode": 0},
    ]))
    assert mgr.check(item("rustup", "rust", "latest", {})) == CheckResult.NOT_SATISFIED


def test_rustup_satisfied_without_components_or_targets() -> None:
    mgr = RustupManager(runner_multi([
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu - Up to date\n", "returncode": 0},
    ]))
    assert mgr.check(item("rustup", "rust", "latest", {})) == CheckResult.SATISFIED


def test_rustup_satisfied_with_components_targets() -> None:
    mgr = RustupManager(runner_multi([
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "rustfmt (installed)\nclippy (installed)\n", "returncode": 0},
        {"stdout": "wasm32-unknown-unknown (installed)\n", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu - Up to date\n", "returncode": 0},
    ]))
    assert mgr.check(item("rustup", "rust", "latest", {"components": ["rustfmt", "clippy"], "targets": ["wasm32-unknown-unknown"]})) == CheckResult.SATISFIED


def test_rustup_missing_component() -> None:
    mgr = RustupManager(runner_multi([
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "rustfmt (installed)\nclippy\n", "returncode": 0},
    ]))
    assert mgr.check(item("rustup", "rust", "latest", {"components": ["clippy"]})) == CheckResult.NOT_SATISFIED


def test_rustup_command_and_set_default() -> None:
    mgr = RustupManager()
    plan = item("rustup", "rust", "latest", {"components": ["rustfmt"], "targets": ["wasm32-unknown-unknown"], "profile": "minimal"})
    assert mgr.install_command(plan) == ["rustup", "toolchain", "install", "stable", "--profile", "minimal", "--component", "rustfmt", "--target", "wasm32-unknown-unknown"]


def test_rustup_install_default_failure() -> None:
    r = runner_multi([
        {"returncode": 0},
        {"returncode": 1},
    ])
    mgr = RustupManager(r)
    plan = item("rustup", "rust", "latest", {"set_default": True})
    try:
        mgr.install(plan)
    except InstallationError:
        pass
    else:
        raise AssertionError("expected InstallationError")


def test_rustup_moving_channel_outdated() -> None:
    mgr = RustupManager(runner_multi([
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu - Update available\n", "returncode": 0},
    ]))
    assert mgr.check(item("rustup", "rust", "latest", {})) == CheckResult.NOT_SATISFIED


def test_rustup_moving_channel_unknown_status_is_check_error() -> None:
    mgr = RustupManager(runner_multi([
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu (default)", "returncode": 0},
        {"stdout": "stable-x86_64-unknown-linux-gnu - unknown status\n", "returncode": 0},
    ]))
    assert mgr.check(item("rustup", "rust", "latest", {})) == CheckResult.CHECK_ERROR
