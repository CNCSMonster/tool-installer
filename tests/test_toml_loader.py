from __future__ import annotations

from pathlib import Path

import pytest

from tool_installer.errors import ConfigError
from tool_installer.toml_loader import load_toml


def test_load_toml_returns_dictionary(tmp_path: Path) -> None:
    path = tmp_path / "tools.toml"
    path.write_text('[tool-installer]\nmanifest = "./manifest.toml"\n', encoding="utf-8")

    data = load_toml(path)

    assert data == {"tool-installer": {"manifest": "./manifest.toml"}}


def test_load_toml_reports_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.toml"

    with pytest.raises(ConfigError, match="not found"):
        load_toml(path)


def test_load_toml_reports_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="directory"):
        load_toml(tmp_path)


def test_load_toml_reports_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("not = [valid\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_toml(path)


def test_load_toml_uses_vendored_fallback_when_tomllib_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    """Simulate Python 3.8-3.10 where stdlib tomllib is unavailable."""
    import builtins
    import importlib
    import sys

    import tool_installer.toml_loader as toml_loader

    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    monkeypatch.delitem(sys.modules, "tool_installer.toml_loader", raising=False)
    fallback_loader = importlib.import_module("tool_installer.toml_loader")
    try:
        path = tmp_path / "tools.toml"
        path.write_text('[tool-installer]\nmanifest = "./manifest.toml"\n', encoding="utf-8")

        assert fallback_loader.load_toml(path) == {"tool-installer": {"manifest": "./manifest.toml"}}
        assert fallback_loader._toml.__name__ == "tool_installer.vendor.tomli"  # type: ignore[attr-defined]
    finally:
        monkeypatch.setitem(sys.modules, "tool_installer.toml_loader", toml_loader)
