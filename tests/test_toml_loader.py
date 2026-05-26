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
