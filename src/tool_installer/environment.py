"""Environment normalization."""

from __future__ import annotations

import platform
from .errors import StrategyError
from .models import Environment


def detect_environment() -> Environment:
    return normalize_environment(platform.system(), platform.machine())


def normalize_environment(system: str, machine: str) -> Environment:
    os_name = system.lower()
    if os_name == "darwin":
        normalized_os = "macos"
    elif os_name == "linux":
        normalized_os = "linux"
    else:
        raise StrategyError(f"Unsupported OS: {system}")

    arch = machine.lower()
    if arch in {"x86_64", "amd64"}:
        normalized_arch = "x86_64"
    elif arch in {"aarch64", "arm64"}:
        normalized_arch = "aarch64"
    else:
        raise StrategyError(f"Unsupported architecture: {machine}")

    return Environment(os=normalized_os, arch=normalized_arch)
