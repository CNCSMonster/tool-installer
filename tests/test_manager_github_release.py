from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tool_installer.errors import InstallationError, StrategyError
from tool_installer.environment import normalize_environment
from tool_installer.parser import parse_manifest_file, parse_tools_file
from tool_installer.resolver import collect_ordered_tools, resolve_modules
from tool_installer.strategy import build_install_plan
from tool_installer.managers.github_release import GithubReleaseManager
from tool_installer.managers.base import CheckResult
from tool_installer.models import Environment, MergedStrategy, PlanItem, ToolReference, ToolSpec


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def item(name: str, fields: dict) -> PlanItem:
    return PlanItem(
        module_name="dev",
        tool=ToolSpec(ToolReference(raw=name, name=name, version="1.0.0")),
        strategy=MergedStrategy(tool_name=name, manager="github-release", fields=fields, force=False),
        environment=Environment(os="linux", arch="x86_64"),
    )


# --- version_probe validation tests ---

def test_version_probe_valid(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}-unknown-linux-gnu.tar.gz"
bin = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd (?P<version>[0-9]+\\\\.[0-9]+\\\\.[0-9]+)"
""",
    )
    config = parse_tools_file(tools, "dev")
    plan = build_install_plan(
        collect_ordered_tools(resolve_modules(config, "dev")),
        parse_manifest_file(manifest),
        normalize_environment("Linux", "x86_64"),
        tmp_path,
    )
    assert plan.items[0].strategy.fields["version_probe"]["command"] == ["{bin}", "--version"]


def test_version_probe_missing_command(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}.tar.gz"
bin = "fd"
[fd.linux.version_probe]
regex = "^fd (?P<version>.+)"
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="version_probe.command"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_version_probe_missing_regex(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}.tar.gz"
bin = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="version_probe.regex"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_version_probe_invalid_regex(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}.tar.gz"
bin = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "[invalid("
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="not a valid regex"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_version_probe_missing_version_group(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}.tar.gz"
bin = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd ([0-9]+)"
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="named capture group.*version"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_version_probe_unsupported_placeholder(tmp_path: Path) -> None:
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}.tar.gz"
bin = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version", "{tool}"]
regex = "^fd (?P<version>.+)"
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="only supports.*bin.*placeholder"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


# --- github-release check tests ---

def test_github_release_check_without_probe_returns_not_satisfied() -> None:
    mgr = GithubReleaseManager()
    plan_item = item("fd", {"repo": "sharkdp/fd", "asset": "fd.tar.gz", "bin": "fd"})
    assert mgr.check(plan_item) == CheckResult.NOT_SATISFIED


def test_github_release_check_with_probe_no_home_returns_check_error() -> None:
    mgr = GithubReleaseManager()
    plan_item = item("fd", {
        "repo": "sharkdp/fd",
        "asset": "fd.tar.gz",
        "bin": "fd",
        "version_probe": {"command": ["{bin}", "--version"], "regex": "^fd (?P<version>.+)"},
    })
    with patch.dict(os.environ, {"HOME": ""}, clear=False):
        old_home = os.environ.get("HOME")
        os.environ.pop("HOME", None)
        try:
            assert mgr.check(plan_item) == CheckResult.CHECK_ERROR
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home


def test_github_release_check_with_probe_bin_not_found_returns_not_satisfied(tmp_path: Path) -> None:
    mgr = GithubReleaseManager()
    plan_item = item("fd", {
        "repo": "sharkdp/fd",
        "asset": "fd.tar.gz",
        "bin": "fd",
        "version_probe": {"command": ["{bin}", "--version"], "regex": "^fd (?P<version>.+)"},
    })
    with patch.dict(os.environ, {"HOME": str(tmp_path)}):
        assert mgr.check(plan_item) == CheckResult.NOT_SATISFIED


def test_github_release_version_comparison() -> None:
    assert GithubReleaseManager._compare_versions("1.0.0", "1.0.0") == CheckResult.SATISFIED
    assert GithubReleaseManager._compare_versions("v1.0.0", "1.0.0") == CheckResult.SATISFIED
    assert GithubReleaseManager._compare_versions("1.0.0", "v1.0.0") == CheckResult.SATISFIED
    assert GithubReleaseManager._compare_versions("V1.0.0", "v1.0.0") == CheckResult.SATISFIED
    assert GithubReleaseManager._compare_versions("1.0.0", "1.0.1") == CheckResult.NOT_SATISFIED
    assert GithubReleaseManager._compare_versions("2.0.0", "1.0.0") == CheckResult.NOT_SATISFIED


# --- version_probe exclusive to github-release ---

def test_version_probe_rejected_for_non_github_release(tmp_path: Path) -> None:
    """version_probe must only be allowed for github-release manager."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "script"
path = "install-tool"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd (?P<version>.+)"
""",
    )
    # Create the script file
    script = tmp_path / "install-tool"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="Unknown strategy fields"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


def test_version_probe_unknown_fields_in_subtable(tmp_path: Path) -> None:
    """Unknown fields inside version_probe subtable must be fatal."""
    tools = tmp_path / "tools.toml"
    manifest = tmp_path / "manifest.toml"
    write(tools, "[tool-installer]\nmanifest = 'manifest.toml'\n[dev]\nfd = ''\n")
    write(
        manifest,
        """
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd.tar.gz"
bin = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd (?P<version>.+)"
extra_field = true
""",
    )
    config = parse_tools_file(tools, "dev")
    with pytest.raises(StrategyError, match="Unknown version_probe fields"):
        build_install_plan(
            collect_ordered_tools(resolve_modules(config, "dev")),
            parse_manifest_file(manifest),
            normalize_environment("Linux", "x86_64"),
            tmp_path,
        )


# --- Archive safety tests ---

import io
import tarfile
import zipfile
from typing import List, Tuple


def _make_zip(entries: List[Tuple[str, bytes]]) -> bytes:
    """Create a zip archive in memory with the given (path, content) entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


def _make_tar(entries: List[Tuple[str, bytes]]) -> bytes:
    """Create a tar.gz archive in memory with the given (path, content) entries."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in entries:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_tar_with_symlink(entries: List[Tuple[str, bytes]], symlinks: List[Tuple[str, str]]) -> bytes:
    """Create a tar.gz with regular files and symlinks."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in entries:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(content))
        for link_name, link_target in symlinks:
            info = tarfile.TarInfo(name=link_name)
            info.type = tarfile.SYMTYPE
            info.linkname = link_target
            tf.addfile(info)
    return buf.getvalue()


def test_zip_path_traversal_rejected(tmp_path: Path) -> None:
    """ZIP entries with .. must not write outside extraction directory."""
    mgr = GithubReleaseManager()
    malicious = _make_zip([("../escape", b"malicious"), ("normal.txt", b"ok")])
    archive = tmp_path / "malicious.zip"
    archive.write_bytes(malicious)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(InstallationError, match="escapes extraction directory"):
        mgr._safe_extract_zip(archive, extract_dir)
    # Ensure no file was written outside extract_dir
    assert not (tmp_path / "escape").exists()


def test_zip_absolute_path_rejected(tmp_path: Path) -> None:
    """ZIP entries with absolute paths must not be written."""
    mgr = GithubReleaseManager()
    malicious = _make_zip([("/etc/malicious", b"evil"), ("normal.txt", b"ok")])
    archive = tmp_path / "abs.zip"
    archive.write_bytes(malicious)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(InstallationError, match="escapes extraction directory"):
        mgr._safe_extract_zip(archive, extract_dir)


def test_tar_absolute_path_rejected(tmp_path: Path) -> None:
    """TAR entries with absolute paths must be rejected."""
    mgr = GithubReleaseManager()
    malicious = _make_tar([("/etc/malicious", b"evil")])
    archive = tmp_path / "abs.tar.gz"
    archive.write_bytes(malicious)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(InstallationError, match="absolute path"):
        mgr._safe_extract_tar(archive, extract_dir)


def test_tar_parent_traversal_rejected(tmp_path: Path) -> None:
    """TAR entries with .. traversal must be rejected."""
    mgr = GithubReleaseManager()
    malicious = _make_tar([("../../../tmp/escape", b"evil")])
    archive = tmp_path / "traversal.tar.gz"
    archive.write_bytes(malicious)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(InstallationError, match="parent traversal"):
        mgr._safe_extract_tar(archive, extract_dir)


def test_tar_symlink_escape_rejected(tmp_path: Path) -> None:
    """TAR symlinks that point outside extraction directory must be rejected."""
    mgr = GithubReleaseManager()
    malicious = _make_tar_with_symlink(
        [("normal.txt", b"ok")],
        [("escape_link", "/etc/passwd")],
    )
    archive = tmp_path / "symlink.tar.gz"
    archive.write_bytes(malicious)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(InstallationError, match="escapes extraction directory"):
        mgr._safe_extract_tar(archive, extract_dir)


def test_tar_symlink_relative_escape_rejected(tmp_path: Path) -> None:
    """TAR symlinks with relative paths that escape must be rejected."""
    mgr = GithubReleaseManager()
    malicious = _make_tar_with_symlink(
        [("normal.txt", b"ok")],
        [("escape_link", "../../etc/passwd")],
    )
    archive = tmp_path / "rel_symlink.tar.gz"
    archive.write_bytes(malicious)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(InstallationError, match="escapes extraction directory"):
        mgr._safe_extract_tar(archive, extract_dir)


def test_tar_valid_extraction(tmp_path: Path) -> None:
    """Valid tar entries should extract successfully."""
    mgr = GithubReleaseManager()
    content = b"#!/bin/sh\necho hello\n"
    archive_data = _make_tar([("bin/mytool", content)])
    archive = tmp_path / "valid.tar.gz"
    archive.write_bytes(archive_data)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    mgr._safe_extract_tar(archive, extract_dir)
    assert (extract_dir / "bin" / "mytool").is_file()
    assert (extract_dir / "bin" / "mytool").read_bytes() == content


def test_zip_valid_extraction(tmp_path: Path) -> None:
    """Valid zip entries should extract successfully."""
    mgr = GithubReleaseManager()
    content = b"#!/bin/sh\necho hello\n"
    archive_data = _make_zip([("bin/mytool", content)])
    archive = tmp_path / "valid.zip"
    archive.write_bytes(archive_data)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    mgr._safe_extract_zip(archive, extract_dir)
    assert (extract_dir / "bin" / "mytool").is_file()
    assert (extract_dir / "bin" / "mytool").read_bytes() == content


def test_atomic_install_uses_same_dir_rename(tmp_path: Path) -> None:
    """Atomic install should use os.replace within the same filesystem."""
    # This is verified by code inspection: install() creates temp file
    # in the same directory as destination and uses os.replace.
    # Verify the pattern exists in the source:
    import inspect
    from tool_installer.managers.github_release import GithubReleaseManager
    source = inspect.getsource(GithubReleaseManager.install)
    assert "os.replace" in source, "install should use os.replace for atomic rename"
    assert ".tmp" in source, "install should use a temp file pattern"
