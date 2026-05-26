"""GitHub release manager."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from ..errors import InstallationError
from ..models import PlanItem
from .base import CheckResult, Manager


def _is_relative_to(path: Path, base: Path) -> bool:
    """Python 3.8-compatible Path.is_relative_to()."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


class GithubReleaseManager:
    """Manager for GitHub release downloads.

    Check-capable only when version_probe is defined in the strategy.
    Without version_probe, always returns NOT_SATISFIED (non-check-capable).
    """

    def check(self, item: PlanItem) -> CheckResult:
        version_probe = item.strategy.fields.get("version_probe")
        if not version_probe:
            # Not check-capable: always install when reached
            return CheckResult.NOT_SATISFIED

        # Execute version probe
        install_name = item.strategy.fields.get("install_name", item.tool.reference.name)
        home = os.environ.get("HOME")
        if not home:
            return CheckResult.CHECK_ERROR

        bin_path = Path(home) / ".local" / "bin" / install_name
        if not bin_path.is_file():
            return CheckResult.NOT_SATISFIED

        probe = version_probe
        command = list(probe["command"])
        # Replace {bin} placeholder
        command = [c.replace("{bin}", str(bin_path)) for c in command]

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        regex_str = probe["regex"]
        try:
            pattern = re.compile(regex_str)
        except re.error:
            return CheckResult.CHECK_ERROR

        match = pattern.search(result.stdout)
        if not match:
            return CheckResult.CHECK_ERROR

        captured_version = match.group("version")
        if not captured_version:
            return CheckResult.CHECK_ERROR

        # Compare using v1 version equality
        requested = item.tool.reference.version
        if requested == "latest":
            # For latest, we need to resolve the actual latest tag
            # and compare. If we can't resolve it, treat as check_error.
            try:
                latest_tag = self._latest_tag(item.strategy.fields["repo"])
                return self._compare_versions(captured_version, latest_tag)
            except (InstallationError, urllib.error.URLError, OSError):
                return CheckResult.CHECK_ERROR
        else:
            return self._compare_versions(captured_version, requested)

    @staticmethod
    def _compare_versions(installed: str, requested: str) -> CheckResult:
        """Compare versions using v1 equality (strip one leading v/V)."""
        def normalize(v: str) -> str:
            if v and v[0] in ("v", "V"):
                return v[1:]
            return v

        if normalize(installed) == normalize(requested):
            return CheckResult.SATISFIED
        return CheckResult.NOT_SATISFIED

    @staticmethod
    def _latest_tag(repo: str) -> str:
        with urllib.request.urlopen(f"https://api.github.com/repos/{repo}/releases/latest") as response:
            data = json.loads(response.read().decode("utf-8"))
        tag = data.get("tag_name")
        if not isinstance(tag, str) or not tag:
            raise InstallationError(f"Could not resolve latest GitHub release for {repo}")
        return tag

    def install(self, item: PlanItem) -> None:
        home = os.environ.get("HOME")
        if not home:
            raise InstallationError("HOME is required for github-release installs")

        version = item.tool.reference.version
        if version == "latest":
            version = self._latest_tag(item.strategy.fields["repo"])

        asset_name = self._asset_name(item, version)
        url = f"https://github.com/{item.strategy.fields['repo']}/releases/download/{version}/{asset_name}"

        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            downloaded = temp_dir / asset_name
            urllib.request.urlretrieve(url, downloaded)
            self._verify_checksum(item, downloaded)
            executable = self._locate_executable(item, downloaded, temp_dir)

            install_dir = Path(home) / ".local" / "bin"
            install_dir.mkdir(parents=True, exist_ok=True)
            destination = install_dir / item.strategy.fields.get("install_name", item.tool.reference.name)

            # Atomic install: create temp file in the same directory as destination
            # then use os.replace for atomic rename on same filesystem
            tmp_dest = install_dir / f".installing_{item.tool.reference.name}.tmp"
            try:
                shutil.copy2(executable, tmp_dest)
                tmp_dest.chmod(tmp_dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                os.replace(str(tmp_dest), str(destination))
            except OSError:
                # Clean up temp file if rename failed
                try:
                    tmp_dest.unlink()
                except OSError:
                    pass
                raise

    def _asset_name(self, item: PlanItem, version: str) -> str:
        return item.strategy.fields["asset"].format(
            tool=item.tool.reference.name,
            version=version,
            os=item.environment.os,
            arch=item.environment.arch,
        )

    def _verify_checksum(self, item: PlanItem, path: Path) -> None:
        expected = item.strategy.fields.get("sha256")
        if not expected:
            return
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != expected.lower():
            raise InstallationError(f"Checksum mismatch for {item.tool.reference.name}")

    def _locate_executable(self, item: PlanItem, asset: Path, temp_dir: Path) -> Path:
        bin_path = Path(item.strategy.fields["bin"])
        extract_dir = temp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        if zipfile.is_zipfile(asset):
            self._safe_extract_zip(asset, extract_dir)
            candidate = extract_dir / bin_path
        elif asset.name.endswith((".tar.gz", ".tgz", ".tar.xz")):
            self._safe_extract_tar(asset, extract_dir)
            candidate = extract_dir / bin_path
        else:
            # Single-file binary asset
            if bin_path.name == asset.name and len(bin_path.parts) == 1:
                return asset
            raise InstallationError(f"Unsupported archive or single-file asset mismatch for {item.tool.reference.name}")

        if not candidate.is_file():
            raise InstallationError(f"Executable not found in GitHub release asset: {bin_path}")

        # Verify the candidate resolves within the extracted contents
        try:
            candidate.resolve().relative_to(extract_dir.resolve())
        except ValueError:
            raise InstallationError(f"Executable resolves outside extracted contents for {item.tool.reference.name}")

        return candidate

    @staticmethod
    def _safe_extract_zip(archive: Path, dest: Path) -> None:
        """Extract a zip archive with path containment checks."""
        dest_resolved = dest.resolve()
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                # Skip the zip root directory entry
                if info.filename.endswith("/") and info.filename == Path(info.filename).name + "/":
                    continue

                target = dest_resolved / Path(info.filename)
                if not _is_relative_to(target.resolve(), dest_resolved):
                    raise InstallationError(f"Archive entry escapes extraction directory: {info.filename}")
                if info.filename.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    @staticmethod
    def _safe_extract_tar(archive: Path, dest: Path) -> None:
        """Extract a tar archive with path containment checks.

        Each entry is validated before extraction to prevent:
        - Absolute paths
        - Parent directory traversal (..)
        - Symlink targets escaping the extraction directory
        """
        dest_resolved = dest.resolve()
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                # Check for absolute paths
                if os.path.isabs(member.name):
                    raise InstallationError(f"Archive entry has absolute path: {member.name}")
                # Check for parent directory traversal
                parts = Path(member.name).parts
                if ".." in parts:
                    raise InstallationError(f"Archive entry contains parent traversal: {member.name}")

                target = dest_resolved / member.name
                if not _is_relative_to(target.resolve(), dest_resolved):
                    raise InstallationError(f"Archive entry escapes extraction directory: {member.name}")

                # Handle symlinks: resolve target must stay within dest
                if member.issym() or member.islnk():
                    link_name = member.linkname
                    if member.issym():
                        # Relative symlink from the entry's parent directory
                        link_target = (target.parent / link_name).resolve()
                    else:
                        # Hard link
                        link_target = dest_resolved / link_name
                    if not _is_relative_to(link_target, dest_resolved):
                        raise InstallationError(f"Symlink/hardlink escapes extraction directory: {member.name} -> {member.linkname}")

                # Extract the entry safely
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.issym():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() or target.is_symlink():
                        target.unlink()
                    target.symlink_to(member.linkname)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    if src is None:
                        raise InstallationError(f"Cannot extract file: {member.name}")
                    with src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    # Preserve permissions
                    mode = member.mode
                    if mode is not None:
                        target.chmod(mode)
                elif member.isdev():
                    # Device files are not supported
                    raise InstallationError(f"Device file in archive: {member.name}")
                else:
                    # Other types (block device, char device, etc.) are not supported
                    raise InstallationError(f"Unsupported archive entry type: {member.name}")

    def check_command(self, item: PlanItem) -> list:
        # Not used; check is handled via version_probe
        raise NotImplementedError

    def install_command(self, item: PlanItem) -> list:
        # Not used; install is handled via the install method
        raise NotImplementedError
