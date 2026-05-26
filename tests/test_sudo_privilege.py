"""Tests for sudo privilege handling matching dotfiles sudo_run semantics."""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from tool_installer.errors import InstallationError
from tool_installer.managers.base import _run_with_sudo, _is_root, _has_tty, CommandManager
from tool_installer.managers.commands import AptManager
from tool_installer.models import Environment, MergedStrategy, PlanItem, ToolReference, ToolSpec


def test_is_root_when_euid_zero() -> None:
    with patch.object(os, "geteuid", return_value=0):
        assert _is_root() is True


def test_is_root_when_euid_nonzero() -> None:
    with patch.object(os, "geteuid", return_value=1000):
        assert _is_root() is False


def test_has_tty() -> None:
    """_has_tty delegates to sys.stdin.isatty()."""
    assert isinstance(_has_tty(), bool)


def test_sudo_prepend_when_not_root_and_has_tty() -> None:
    runner = MagicMock()
    runner.run.return_value = MagicMock(returncode=0)

    with patch.object(os, "geteuid", return_value=1000):
        with patch("tool_installer.managers.base._has_tty", return_value=True):
            _run_with_sudo(["apt-get", "install", "-y", "curl"], runner=runner)

    runner.run.assert_called_once()
    args = runner.run.call_args[0][0]
    assert args[0] == "sudo"
    assert args[1:] == ["apt-get", "install", "-y", "curl"]


def test_no_sudo_when_root() -> None:
    runner = MagicMock()
    runner.run.return_value = MagicMock(returncode=0)

    with patch.object(os, "geteuid", return_value=0):
        _run_with_sudo(["apt-get", "install", "-y", "curl"], runner=runner)

    runner.run.assert_called_once()
    args = runner.run.call_args[0][0]
    assert args == ["apt-get", "install", "-y", "curl"]


def test_installation_error_when_not_root_and_no_tty() -> None:
    """Without TTY and not root, should raise InstallationError (matching dotfiles behavior)."""
    with patch.object(os, "geteuid", return_value=1000):
        with patch("tool_installer.managers.base._has_tty", return_value=False):
            with pytest.raises(InstallationError, match="no TTY is available"):
                _run_with_sudo(["apt-get", "install", "-y", "curl"])


def test_apt_manager_needs_privilege() -> None:
    """AptManager must declare needs_privilege = True."""
    assert AptManager.needs_privilege is True


def test_apt_install_uses_apt_get() -> None:
    """apt install command must use apt-get (not apt), matching setup.sh."""
    mgr = AptManager()
    item = PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw="curl@7.68", name="curl", version="7.68")),
        strategy=MergedStrategy(tool_name="curl", manager="apt", fields={"pkg": "curl"}, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )
    cmd = mgr.install_command(item)
    assert cmd == ["apt-get", "install", "-y", "curl=7.68"]
