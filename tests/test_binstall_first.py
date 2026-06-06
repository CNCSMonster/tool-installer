"""Tests for cargo-install binstall_first optimization."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from tool_installer.managers.base import CheckResult, SubprocessRunner
from tool_installer.managers.commands import CargoInstallManager
from tool_installer.models import Environment, MergedStrategy, PlanItem, ToolReference, ToolSpec


def _make_item(name="bat", manager="cargo-install", version="latest", binstall_first=False, locked=False, fields=None):
    strategy_fields = {"manager": manager, "pkg": name, **(fields or {})}
    if binstall_first:
        strategy_fields["binstall_first"] = True
    if locked:
        strategy_fields["locked"] = True
    return PlanItem(
        module_name="cargo-tools",
        tool=ToolSpec(ToolReference(raw=name if version == "latest" else f"{name}@{version}", name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager=manager, fields=strategy_fields),
        environment=Environment(os="linux", arch="x86_64"),
    )


def _cmd_contains(call, substring):
    """Check if any arg in the call list contains the substring."""
    return any(substring in arg for arg in call)


def _is_binstall_call(call):
    """Check if the call is a binstall invocation (not cargo install)."""
    # cargo binstall calls: ["cargo", "binstall", ...] or ["/path/cargo-binstall", ...]
    has_binstall = any("binstall" in arg for arg in call)
    has_cargo_install = "cargo" in call and "install" in call
    return has_binstall and not has_cargo_install


def _is_cargo_install_call(call):
    """Check if the call is 'cargo install ...'."""
    return "cargo" in call and "install" in call and "binstall" not in call


class FakeRunner(SubprocessRunner):
    """Runner that returns predefined results."""

    def __init__(self):
        self.calls = []
        self.results = []
        self._call_index = 0

    def set_results(self, results):
        self.results = results

    def run(self, args, check=False, **kwargs):
        self.calls.append(list(args))
        if self._call_index < len(self.results):
            result = self.results[self._call_index]
            self._call_index += 1
            return result
        return mock.Mock(returncode=0, stdout="", stderr="")


class TestBinstallFirstField:
    """Test that binstall_first is a recognized optional field."""

    def test_binstall_first_in_strategy_fields(self):
        from tool_installer.strategy import _SUPPORTED
        cargo_fields = _SUPPORTED["cargo-install"]
        assert "binstall_first" in cargo_fields["optional"]

    def test_binstall_first_is_bool_field(self):
        from tool_installer.strategy import _BOOL_FIELDS
        assert "binstall_first" in _BOOL_FIELDS


class TestBinstallFirstFlow:
    """Test the binstall_first install flow."""

    def test_binstall_success_skips_cargo_install(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="cargo-binstall 1.10.22\n", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True)
        manager.install(item)

        assert len(runner.calls) == 2
        assert _is_binstall_call(runner.calls[1])
        assert not _is_cargo_install_call(runner.calls[1])

    def test_binstall_install_failure_falls_back_to_cargo_install(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="cargo-binstall 1.10.22\n", stderr=""),
            mock.Mock(returncode=1, stdout="", stderr="no prebuilt binary"),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True)
        manager.install(item)

        assert len(runner.calls) == 3
        assert _is_binstall_call(runner.calls[1])
        assert _is_cargo_install_call(runner.calls[2])

    def test_binstall_first_with_locked_flag(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="cargo-binstall 1.10.22\n", stderr=""),
            mock.Mock(returncode=1, stdout="", stderr="no binary"),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True, locked=True)
        manager.install(item)

        cargo_call = runner.calls[-1]
        assert "--locked" in cargo_call

    def test_binstall_first_with_version_selector(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="cargo-binstall 1.10.22\n", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True, version="0.26.1")
        manager.install(item)

        binstall_call = runner.calls[1]
        assert "--version" in binstall_call
        assert "0.26.1" in binstall_call

    def test_binstall_first_disabled_uses_cargo_install_directly(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=False)
        manager.install(item)

        assert len(runner.calls) == 1
        assert _is_cargo_install_call(runner.calls[0])

    def test_binstall_first_not_applied_to_git_installs(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True, fields={
            "git": "https://github.com/sharkdp/bat",
        })
        manager.install(item)

        assert len(runner.calls) == 1
        assert _is_cargo_install_call(runner.calls[0])
        assert "--git" in runner.calls[0]


class TestBinstallBootstrap:
    """Test cargo-binstall auto-download behavior."""

    def test_uses_existing_in_path(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="cargo-binstall 1.10.22\n", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True)

        with mock.patch("shutil.which", return_value="/usr/bin/cargo-binstall"):
            manager.install(item)

        assert len(runner.calls) == 2
        assert runner.calls[0] == ["cargo-binstall", "-V"]
        assert _is_binstall_call(runner.calls[1])

    def test_download_failure_silently_falls_back(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True)

        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(Path, "is_file", return_value=False), \
             mock.patch.object(manager, "_download_binstall", return_value=False):
            manager.install(item)

        # _ensure_binstall returns None → direct cargo install (single runner call)
        assert len(runner.calls) == 1
        assert _is_cargo_install_call(runner.calls[0])

    def test_download_and_install_binstall(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True)

        tmpdir = tempfile.mkdtemp()
        cargo_bin = Path(tmpdir)
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(manager, "_cargo_home_bin", return_value=cargo_bin), \
             mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(os, "access", return_value=True), \
             mock.patch.object(manager, "_verified_binstall", return_value=True):
            manager.install(item)

        # _verified_binstall mocked → returns [home_binary]
        # runner.run called once for binstall install
        assert len(runner.calls) == 1
        assert _is_binstall_call(runner.calls[0])
        assert not _is_cargo_install_call(runner.calls[0])


class TestBinstallFirstCheckUnchanged:
    """Verify binstall_first doesn't affect check semantics."""

    def test_check_with_binstall_first_enabled(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="bat v0.26.1:\n  bat\n", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True, version="0.26.1")
        result = manager.check(item)

        assert result == CheckResult.SATISFIED

    def test_check_with_binstall_first_not_installed(self):
        runner = FakeRunner()
        runner.set_results([
            mock.Mock(returncode=0, stdout="some-other v1.0:\n  other\n", stderr=""),
        ])
        manager = CargoInstallManager(runner=runner)
        item = _make_item(binstall_first=True, version="0.26.1")
        result = manager.check(item)

        assert result == CheckResult.NOT_SATISFIED
