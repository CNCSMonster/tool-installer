"""Command-based package managers with SPEC-aligned checks."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from ..errors import InstallationError
from ..github_token import detect_github_token
from ..models import PlanItem
from .base import CheckResult, CommandManager, CommandRunner


def _selector(item: PlanItem) -> str:
    return item.tool.reference.version


def _v1_eq(a: str, b: str) -> bool:
    """v1 version equality: strip one leading v/V, then exact match."""
    def norm(v: str) -> str:
        if v and v[0] in ("v", "V"):
            return v[1:]
        return v
    return norm(a) == norm(b)


class AptManager(CommandManager):
    """APT package manager.

    Check: uses dpkg-query for installed version, apt-cache policy for candidate.
    Needs root privileges for install.

    Mirrors dotfiles setup.sh sudo_run() behavior:
    - Uses sudo when not root (password prompt in interactive terminal)
    - Runs apt-get install interactively (no DEBIAN_FRONTEND=noninteractive)
    """

    needs_privilege = True

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["dpkg-query", "-W", "-f=${Version}", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            # Package not installed
            return CheckResult.NOT_SATISFIED

        installed_version = result.stdout.strip()
        if not installed_version:
            return CheckResult.CHECK_ERROR

        requested = _selector(item)
        if requested == "latest":
            # Resolve latest candidate from apt-cache
            try:
                cand = self._get_apt_candidate(pkg)
                if cand is None:
                    return CheckResult.CHECK_ERROR
                return CheckResult.SATISFIED if _v1_eq(installed_version, cand) else CheckResult.NOT_SATISFIED
            except OSError:
                return CheckResult.CHECK_ERROR
        else:
            return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _get_apt_candidate(self, pkg: str) -> Optional[str]:
        """Get the candidate version from apt-cache policy."""
        try:
            result = self.runner.run(
                ["apt-cache", "policy", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        # Parse "Candidate: X.Y.Z" line
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Candidate:"):
                candidate = stripped.split(":", 1)[1].strip()
                if candidate and candidate != "(none)":
                    return candidate
                return None
        return None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        """Build apt install command.

        Mirrors setup.sh: sudo_run apt-get install -y <pkg>
        - Uses 'apt-get' (not 'apt') for scripting compatibility
        - Uses '-y' to auto-confirm (since we already prompted for sudo password)
        - Does NOT set DEBIAN_FRONTEND=noninteractive
          (respects user's apt configuration for any remaining interactive prompts)
        """
        pkg = item.strategy.fields["pkg"]
        if _selector(item) != "latest":
            pkg = f"{pkg}={_selector(item)}"
        return ["apt-get", "install", "-y", pkg]


class BrewManager(CommandManager):
    """Homebrew formula manager.

    Check: uses brew info/outdated metadata. Only supports latest.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["brew", "info", "--json=v2", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Find the formula in the output
        formulas = data.get("formulae", [])
        formula = None
        for f in formulas:
            if f.get("name") == pkg:
                formula = f
                break
        if formula is None:
            return CheckResult.CHECK_ERROR

        installed = formula.get("installed")
        if not installed:
            return CheckResult.NOT_SATISFIED

        # Check if outdated
        installed_version = installed[0].get("installed_version", "") if installed else ""
        latest_version = formula.get("versions", {}).get("stable", "")

        if not installed_version or not latest_version:
            return CheckResult.CHECK_ERROR

        return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        return ["brew", "install", item.strategy.fields["pkg"]]


class BrewCaskManager(CommandManager):
    """Homebrew cask manager.

    Check: uses brew info --cask. Only supports latest.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["brew", "info", "--json=v2", "--cask", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        casks = data.get("casks", [])
        cask = None
        for c in casks:
            if c.get("token") == pkg:
                cask = c
                break
        if cask is None:
            return CheckResult.CHECK_ERROR

        installed = cask.get("installed")
        if not installed:
            return CheckResult.NOT_SATISFIED

        installed_version = installed[0] if installed else ""
        latest_version = cask.get("version", "")

        if not installed_version or not latest_version:
            return CheckResult.CHECK_ERROR

        return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        return ["brew", "install", "--cask", item.strategy.fields["pkg"]]


class CargoBinstallManager(CommandManager):
    """Cargo-binstall manager.

    Non-check-capable in v1. Always installs when reached.
    """

    def check(self, item: PlanItem) -> CheckResult:
        return CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        command = ["cargo", "binstall", "-y", item.strategy.fields["pkg"]]
        if _selector(item) != "latest":
            command.extend(["--version", _selector(item)])
        return command


class CargoInstallManager(CommandManager):
    """Cargo install manager.

    Check: uses cargo install --list for tracked packages.

    When the opt-in ``binstall_first`` strategy field is true for a
    registry install, installation first tries cargo-binstall without its
    compile strategy and falls back to the normal cargo install command on
    any binstall/bootstrap failure.
    """

    _BINSTALL_RELEASE_BASE = (
        "https://github.com/cargo-bins/cargo-binstall/releases/latest/download"
    )
    _BINSTALL_TARGETS = {
        ("linux", "x86_64"): "x86_64-unknown-linux-musl",
        ("linux", "aarch64"): "aarch64-unknown-linux-musl",
        ("macos", "x86_64"): "x86_64-apple-darwin",
        ("macos", "aarch64"): "aarch64-apple-darwin",
    }

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        fields = item.strategy.fields

        # Check if tracking is available
        if fields.get("git"):
            # git-based install: hard to check installed state
            return CheckResult.CHECK_ERROR

        try:
            result = self.runner.run(
                ["cargo", "install", "--list"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        # Parse cargo install --list output
        # Format: "<pkg> v<version>:" followed by binary paths
        found_version = None
        lines = result.stdout.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Match "pkg vX.Y.Z:"
            if line.startswith(f"{pkg} v") and line.endswith(":"):
                version_part = line[len(pkg):-1].strip()
                # Remove leading 'v' or 'V'
                if version_part[0] in ("v", "V"):
                    version_part = version_part[1:]
                found_version = version_part
                break
            i += 1

        if found_version is None:
            return CheckResult.NOT_SATISFIED

        requested = _selector(item)
        if requested == "latest":
            latest_version = self._latest_registry_version(pkg)
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(found_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(found_version, requested) else CheckResult.NOT_SATISFIED

    def _latest_registry_version(self, pkg: str) -> Optional[str]:
        try:
            result = self.runner.run(
                ["cargo", "search", pkg, "--limit", "1"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        # Expected format: `ripgrep = "14.1.0" # ...`
        prefix = pkg + " = \""
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                remainder = line[len(prefix):]
                version = remainder.split("\"", 1)[0]
                return version if version else None
        return None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        """Return the normal cargo install command.

        ``binstall_first`` is intentionally implemented in ``install()`` so
        callers that inspect the command still see the deterministic source
        build fallback command.
        """
        return self._cargo_install_command(item)

    def install(self, item: PlanItem) -> None:
        fields = item.strategy.fields
        if fields.get("binstall_first") is True and "git" not in fields:
            binstall = self._ensure_binstall(item)
            if binstall is not None:
                try:
                    # Inject GITHUB_TOKEN from gh auth if not already set,
                    # so cargo-binstall can use authenticated API requests
                    token, _source = detect_github_token()
                    env = None
                    if token is not None and not os.environ.get("GITHUB_TOKEN"):
                        env = {**os.environ, "GITHUB_TOKEN": token}
                    result = self.runner.run(
                        self._binstall_command(item, binstall),
                        check=False,
                        timeout=30,
                        env=env,
                    )
                    if result.returncode == 0:
                        return
                except subprocess.TimeoutExpired:
                    pass

        result = self.runner.run(self._cargo_install_command(item), check=False)
        if result.returncode != 0:
            raise InstallationError(f"Install failed for {item.tool.reference.name} with manager {item.strategy.manager}")

    def _cargo_install_command(self, item: PlanItem) -> List[str]:
        fields = item.strategy.fields
        command = ["cargo", "install", fields["pkg"]]
        if fields.get("locked") is True:
            command.append("--locked")
        if "git" in fields:
            command.extend(["--git", fields["git"]])
            for key in ("tag", "branch", "rev"):
                if key in fields:
                    command.extend([f"--{key}", fields[key]])
        elif _selector(item) != "latest":
            command.extend(["--version", _selector(item)])
        return command

    def _binstall_command(self, item: PlanItem, invocation: List[str]) -> List[str]:
        command = list(invocation) + ["-y", "--disable-strategies", "compile"]
        if _selector(item) != "latest":
            command.extend(["--version", _selector(item)])
        command.append(item.strategy.fields["pkg"])
        return command

    def _ensure_binstall(self, item: PlanItem) -> Optional[List[str]]:
        """Return a cargo-binstall invocation, or None when unavailable.

        All bootstrap failures are intentionally non-fatal so
        ``binstall_first`` remains an optimization over the normal
        ``cargo install`` path rather than a new hard dependency.
        """
        if shutil.which("cargo-binstall") and self._verified_binstall("cargo-binstall"):
            return ["cargo", "binstall"]

        home_binary = self._cargo_home_bin() / "cargo-binstall"
        if home_binary.is_file() and os.access(home_binary, os.X_OK):
            if self._verified_binstall(str(home_binary)):
                return [str(home_binary)]
            return None

        if not self._download_binstall(item, home_binary):
            return None
        if self._verified_binstall(str(home_binary)):
            return [str(home_binary)]
        return None

    def _verified_binstall(self, binary: str) -> bool:
        try:
            result = self.runner.run([binary, "--version"], check=False, capture_output=True, text=True)
        except OSError:
            return False
        return result.returncode == 0

    def _cargo_home_bin(self) -> Path:
        cargo_home = os.environ.get("CARGO_HOME")
        if cargo_home:
            return Path(cargo_home) / "bin"
        home = os.environ.get("HOME")
        if home:
            return Path(home) / ".cargo" / "bin"
        return Path.home() / ".cargo" / "bin"

    def _download_binstall(self, item: PlanItem, destination: Path) -> bool:
        target = self._BINSTALL_TARGETS.get((item.environment.os, item.environment.arch))
        if target is None:
            return False
        asset = f"cargo-binstall-{target}.tgz"

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as temp:
                archive = Path(temp) / asset

                # Try gh CLI first (has GITHUB_TOKEN auth, avoids rate limits in CI)
                if shutil.which("gh"):
                    try:
                        self.runner.run(
                            [
                                "gh", "release", "download",
                                "latest",
                                "--repo", "cargo-bins/cargo-binstall",
                                "--pattern", asset,
                                "--dir", str(temp),
                            ],
                            check=True,
                            capture_output=True,
                            timeout=60,
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        # gh failed, fall through to urllib
                        pass

                # If gh didn't produce the file, try urllib
                if not archive.is_file():
                    url = f"{self._BINSTALL_RELEASE_BASE}/{asset}"
                    with urllib.request.urlopen(url, timeout=30) as response:
                        archive.write_bytes(response.read())

                if not archive.is_file():
                    return False

                executable = self._extract_binstall(archive, Path(temp))
                temp_dest = destination.parent / f".{destination.name}.installing"
                shutil.copy2(executable, temp_dest)
                temp_dest.chmod(temp_dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                os.replace(str(temp_dest), str(destination))
            return True
        except (OSError, tarfile.TarError, urllib.error.URLError, TimeoutError):
            try:
                temp_dest = destination.parent / f".{destination.name}.installing"
                temp_dest.unlink()
            except OSError:
                pass
            return False

    def _extract_binstall(self, archive: Path, temp_dir: Path) -> Path:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = Path(member.name).name
                if name == "cargo-binstall" and member.isfile():
                    extracted = temp_dir / "cargo-binstall.extracted"
                    source = tar.extractfile(member)
                    if source is None:
                        break
                    with source, extracted.open("wb") as dest:
                        shutil.copyfileobj(source, dest)
                    extracted.chmod(extracted.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    return extracted
        raise tarfile.TarError("cargo-binstall executable not found in archive")


class MiseManager(CommandManager):
    """Mise version manager.

    Check: uses mise list/ls to determine installed versions.
    """

    def check(self, item: PlanItem) -> CheckResult:
        plugin = item.strategy.fields["plugin"]
        requested = _selector(item)

        try:
            result = self.runner.run(
                ["mise", "ls", "--json", plugin],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Check if requested version is installed
        installed_versions = []
        if isinstance(data, list):
            for entry in data:
                version = entry.get("version", "")
                if version:
                    installed_versions.append(version)
        elif isinstance(data, dict):
            versions = data.get("versions", [])
            for v in versions:
                if isinstance(v, str):
                    installed_versions.append(v)
                elif isinstance(v, dict):
                    ver = v.get("version", "")
                    if ver:
                        installed_versions.append(ver)

        if not installed_versions:
            return CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest = self._latest_version(plugin)
            if latest is None:
                return CheckResult.CHECK_ERROR
            for iv in installed_versions:
                if _v1_eq(iv, latest):
                    return CheckResult.SATISFIED
            return CheckResult.NOT_SATISFIED

        # Check if any installed version matches
        for iv in installed_versions:
            if _v1_eq(iv, requested):
                return CheckResult.SATISFIED

        return CheckResult.NOT_SATISFIED

    def _latest_version(self, plugin: str) -> Optional[str]:
        try:
            result = self.runner.run(
                ["mise", "latest", plugin],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        latest = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return latest or None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        return ["mise", "install", f"{item.strategy.fields['plugin']}@{_selector(item)}"]


class NpmGlobalManager(CommandManager):
    """NPM global package manager.

    Check: uses npm list -g --json for global package metadata.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        requested = _selector(item)
        command = ["npm", "list", "-g", "--json", pkg]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])

        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Parse npm list output
        deps = data.get("dependencies", {})
        pkg_info = deps.get(pkg)
        if pkg_info is None:
            return CheckResult.NOT_SATISFIED

        installed_version = pkg_info.get("version")
        if not installed_version:
            return CheckResult.CHECK_ERROR

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg, item.strategy.fields.get("registry"))
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _latest_registry_version(self, pkg: str, registry: Optional[str] = None) -> Optional[str]:
        command = ["npm", "view", pkg, "version", "--json"]
        if registry:
            command.extend(["--registry", registry])
        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw.strip('"')
        return parsed if isinstance(parsed, str) and parsed else None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        package = item.strategy.fields["pkg"] if _selector(item) == "latest" else f"{item.strategy.fields['pkg']}@{_selector(item)}"
        command = ["npm", "install", "-g", package]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])
        return command


class PnpmGlobalManager(CommandManager):
    """PNPM global package manager.

    Check: uses pnpm list -g --json for global package metadata.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        requested = _selector(item)
        command = ["pnpm", "list", "-g", "--json", pkg]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])

        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # pnpm list returns array
        installed_version = None
        if isinstance(data, list) and data:
            installed_version = data[0].get("version")
        elif isinstance(data, dict):
            installed_version = data.get("version")

        if not installed_version:
            return CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg, item.strategy.fields.get("registry"))
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _latest_registry_version(self, pkg: str, registry: Optional[str] = None) -> Optional[str]:
        command = ["pnpm", "view", pkg, "version", "--json"]
        if registry:
            command.extend(["--registry", registry])
        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw.strip('"')
        return parsed if isinstance(parsed, str) and parsed else None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        package = item.strategy.fields["pkg"] if _selector(item) == "latest" else f"{item.strategy.fields['pkg']}@{_selector(item)}"
        command = ["pnpm", "add", "-g", package]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])
        return command


class UvToolManager(CommandManager):
    """UV tool manager.

    Check: exact versions read recorded tool metadata. latest is non-check-capable in v1.
    """

    def check(self, item: PlanItem) -> CheckResult:
        requested = _selector(item)
        if requested == "latest":
            # Non-check-capable in v1
            return CheckResult.NOT_SATISFIED

        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["uv", "tool", "list", "--output-format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Find the tool in the list
        tools = data if isinstance(data, list) else data.get("tools", [])
        for tool in tools:
            tool_name = tool.get("name", "")
            if tool_name == pkg:
                # Check if the requested version matches
                specs = tool.get("specifiers", [])
                for spec in specs:
                    # Match pkg==version pattern
                    if spec.startswith(f"{pkg}=="):
                        installed_version = spec[len(f"{pkg}=="):]
                        return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED
                # Tool is installed but version doesn't match
                return CheckResult.NOT_SATISFIED

        return CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        package = item.strategy.fields["pkg"] if _selector(item) == "latest" else f"{item.strategy.fields['pkg']}=={_selector(item)}"
        command = ["uv", "tool", "install", package]
        if "python" in item.strategy.fields:
            command.extend(["--python", item.strategy.fields["python"]])
        for dependency in item.strategy.fields.get("with", []):
            command.extend(["--with", dependency])
        return command


class RustupManager(CommandManager):
    """Rustup toolchain manager.

    Check: verifies toolchain, components, and targets via rustup show.
    """

    def check(self, item: PlanItem) -> CheckResult:
        fields = item.strategy.fields
        selector = "stable" if _selector(item) == "latest" else _selector(item)

        try:
            result = self.runner.run(
                ["rustup", "show", "active-toolchain"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        # Check the full list of installed toolchains
        try:
            list_result = self.runner.run(
                ["rustup", "toolchain", "list"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if list_result.returncode != 0:
            return CheckResult.CHECK_ERROR

        # Check if the requested toolchain is in the list
        toolchain_found = False
        for line in list_result.stdout.splitlines():
            if line.strip().startswith(selector):
                toolchain_found = True
                break

        if not toolchain_found:
            return CheckResult.NOT_SATISFIED

        # Check components
        required_components = fields.get("components", [])
        if required_components:
            try:
                comp_result = self.runner.run(
                    ["rustup", "component", "list", "--toolchain", selector],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if comp_result.returncode != 0:
                    return CheckResult.CHECK_ERROR

                for component in required_components:
                    if f"{component} (installed)" not in comp_result.stdout:
                        return CheckResult.NOT_SATISFIED
            except OSError:
                return CheckResult.CHECK_ERROR

        # Check targets
        required_targets = fields.get("targets", [])
        if required_targets:
            try:
                target_result = self.runner.run(
                    ["rustup", "target", "list", "--toolchain", selector],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if target_result.returncode != 0:
                    return CheckResult.CHECK_ERROR

                for target in required_targets:
                    if f"{target} (installed)" not in target_result.stdout:
                        return CheckResult.NOT_SATISFIED
            except OSError:
                return CheckResult.CHECK_ERROR

        if selector in ("stable", "nightly"):
            current = self._moving_channel_current(selector)
            if current is None:
                return CheckResult.CHECK_ERROR
            if not current:
                return CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED

    def _moving_channel_current(self, selector: str) -> Optional[bool]:
        try:
            result = self.runner.run(
                ["rustup", "check"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        saw_selector = False
        for line in result.stdout.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith(selector.lower()):
                saw_selector = True
                if "up to date" in stripped or "up-to-date" in stripped:
                    return True
                if "update available" in stripped or "outdated" in stripped:
                    return False
        return None if not saw_selector else None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        selector = "stable" if _selector(item) == "latest" else _selector(item)
        command = ["rustup", "toolchain", "install", selector]
        if "profile" in item.strategy.fields:
            command.extend(["--profile", item.strategy.fields["profile"]])
        for component in item.strategy.fields.get("components", []):
            command.extend(["--component", component])
        for target in item.strategy.fields.get("targets", []):
            command.extend(["--target", target])
        return command

    def install(self, item: PlanItem) -> None:
        super().install(item)
        if item.strategy.fields.get("set_default") is True:
            selector = "stable" if _selector(item) == "latest" else _selector(item)
            result = self.runner.run(["rustup", "default", selector], check=False)
            if result.returncode != 0:
                raise InstallationError(f"Install failed for {item.tool.reference.name} with manager {item.strategy.manager}")
