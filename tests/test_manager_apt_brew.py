"""Tests for apt, brew, and brew-cask manager checks."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tool_installer.managers.commands import AptManager, BrewManager, BrewCaskManager
from tool_installer.managers.base import CheckResult
from tool_installer.models import PlanItem, ToolSpec, ToolReference, MergedStrategy, Environment


def item(name: str, version: str, fields: dict) -> PlanItem:
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name, name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager="apt", fields=fields, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )


def make_runner(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    runner = MagicMock()
    runner.run.return_value = MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)
    return runner


def make_runner_multi(responses: list) -> MagicMock:
    """Create a runner that returns different responses for successive calls."""
    runner = MagicMock()
    mock_results = [MagicMock(stdout=r.get("stdout", ""), stderr=r.get("stderr", ""), returncode=r.get("returncode", 0)) for r in responses]
    runner.run.side_effect = mock_results
    return runner


# --- AptManager tests ---

def test_apt_check_not_installed() -> None:
    runner = make_runner(returncode=1)
    mgr = AptManager(runner)
    plan = item("curl", "latest", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_apt_check_installed_exact_match() -> None:
    runner = make_runner(stdout="7.68.0-1ubuntu2.10", returncode=0)
    mgr = AptManager(runner)
    plan = item("curl", "7.68.0-1ubuntu2.10", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_apt_check_installed_exact_mismatch() -> None:
    runner = make_runner(stdout="7.68.0-1ubuntu2.10", returncode=0)
    mgr = AptManager(runner)
    plan = item("curl", "7.68.0-1ubuntu2.9", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_apt_check_latest_matches_candidate() -> None:
    runner = make_runner_multi([
        {"stdout": "7.68.0-1ubuntu2.10", "returncode": 0},
        {"stdout": "\ncurl:\n  Installed: 7.68.0-1ubuntu2.10\n  Candidate: 7.68.0-1ubuntu2.10\n", "returncode": 0},
    ])
    mgr = AptManager(runner)
    plan = item("curl", "latest", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_apt_check_latest_not_latest() -> None:
    runner = make_runner_multi([
        {"stdout": "7.68.0-1ubuntu2.9", "returncode": 0},
        {"stdout": "\ncurl:\n  Installed: 7.68.0-1ubuntu2.9\n  Candidate: 7.68.0-1ubuntu2.10\n", "returncode": 0},
    ])
    mgr = AptManager(runner)
    plan = item("curl", "latest", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_apt_check_latest_no_candidate() -> None:
    runner = make_runner_multi([
        {"stdout": "7.68.0-1ubuntu2.10", "returncode": 0},
        {"stdout": "\ncurl:\n  Installed: 7.68.0-1ubuntu2.10\n  Candidate: (none)\n", "returncode": 0},
    ])
    mgr = AptManager(runner)
    plan = item("curl", "latest", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_apt_check_oserror_is_check_error() -> None:
    runner = MagicMock()
    runner.run.side_effect = OSError("command not found")
    mgr = AptManager(runner)
    plan = item("curl", "latest", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_apt_check_v_prefix_stripped() -> None:
    runner = make_runner(stdout="v1.2.3", returncode=0)
    mgr = AptManager(runner)
    plan = item("curl", "1.2.3", {"pkg": "curl"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_apt_install_command_latest() -> None:
    mgr = AptManager()
    plan = item("curl", "latest", {"pkg": "curl"})
    assert mgr.install_command(plan) == ["apt-get", "install", "-y", "curl"]


def test_apt_install_command_exact() -> None:
    mgr = AptManager()
    plan = item("curl", "1.2.3", {"pkg": "curl"})
    assert mgr.install_command(plan) == ["apt-get", "install", "-y", "curl=1.2.3"]


# --- BrewManager tests ---

def test_brew_check_oserror_is_check_error() -> None:
    runner = MagicMock()
    runner.run.side_effect = OSError("command not found")
    mgr = BrewManager(runner)
    plan = item("git", "latest", {"pkg": "git"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_brew_check_not_installed() -> None:
    data = {"formulae": [{"name": "git", "installed": []}]}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewManager(runner)
    plan = item("git", "latest", {"pkg": "git"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_brew_check_installed_and_up_to_date() -> None:
    data = {
        "formulae": [{
            "name": "git",
            "installed": [{"installed_version": "2.40.0"}],
            "versions": {"stable": "2.40.0"},
        }]
    }
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewManager(runner)
    plan = item("git", "latest", {"pkg": "git"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_brew_check_installed_but_outdated() -> None:
    data = {
        "formulae": [{
            "name": "git",
            "installed": [{"installed_version": "2.39.0"}],
            "versions": {"stable": "2.40.0"},
        }]
    }
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewManager(runner)
    plan = item("git", "latest", {"pkg": "git"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_brew_check_formula_not_found() -> None:
    data = {"formulae": []}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewManager(runner)
    plan = item("git", "latest", {"pkg": "git"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_brew_install_command() -> None:
    mgr = BrewManager()
    plan = item("git", "latest", {"pkg": "git"})
    assert mgr.install_command(plan) == ["brew", "install", "git"]


# --- BrewCaskManager tests ---

def test_brew_cask_check_oserror_is_check_error() -> None:
    runner = MagicMock()
    runner.run.side_effect = OSError("command not found")
    mgr = BrewCaskManager(runner)
    plan = item("docker", "latest", {"pkg": "docker"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_brew_cask_check_not_installed() -> None:
    data = {"casks": [{"token": "docker", "installed": []}]}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewCaskManager(runner)
    plan = item("docker", "latest", {"pkg": "docker"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_brew_cask_check_installed_and_up_to_date() -> None:
    data = {
        "casks": [{
            "token": "docker",
            "installed": ["4.20.0"],
            "version": "4.20.0",
        }]
    }
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewCaskManager(runner)
    plan = item("docker", "latest", {"pkg": "docker"})
    assert mgr.check(plan) == CheckResult.SATISFIED


def test_brew_cask_check_installed_but_outdated() -> None:
    data = {
        "casks": [{
            "token": "docker",
            "installed": ["4.19.0"],
            "version": "4.20.0",
        }]
    }
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewCaskManager(runner)
    plan = item("docker", "latest", {"pkg": "docker"})
    assert mgr.check(plan) == CheckResult.NOT_SATISFIED


def test_brew_cask_check_cask_not_found() -> None:
    data = {"casks": []}
    runner = make_runner(stdout=json.dumps(data), returncode=0)
    mgr = BrewCaskManager(runner)
    plan = item("docker", "latest", {"pkg": "docker"})
    assert mgr.check(plan) == CheckResult.CHECK_ERROR


def test_brew_cask_install_command() -> None:
    mgr = BrewCaskManager()
    plan = item("docker", "latest", {"pkg": "docker"})
    assert mgr.install_command(plan) == ["brew", "install", "--cask", "docker"]
