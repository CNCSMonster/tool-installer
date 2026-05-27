"""Tests for [_network] manifest section and mirror fallback."""

from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tool_installer.managers.github_release import GithubReleaseManager
from tool_installer.models import NetworkConfig
from tool_installer.parser import parse_manifest_file


# ---------------------------------------------------------------------------
# _network parsing
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, content: str) -> Path:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def test_network_defaults_when_absent(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, '[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n')
    _, net = parse_manifest_file(manifest)
    assert net.github_mirrors == []
    assert net.timeout == 30.0
    assert net.retry == 3


def test_network_full_config(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ngithub_mirrors = ["https://m1.example.com", "https://m2.example.com"]\ntimeout = 60\nretry = 5\n\n'
        '[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    _, net = parse_manifest_file(manifest)
    assert net.github_mirrors == ["https://m1.example.com", "https://m2.example.com"]
    assert net.timeout == 60.0
    assert net.retry == 5


def test_network_mirror_trailing_slash_stripped(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ngithub_mirrors = ["https://m1.example.com/"]\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    _, net = parse_manifest_file(manifest)
    assert net.github_mirrors == ["https://m1.example.com"]


def test_network_unknown_field_rejected(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\nunknown_field = true\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="Unknown.*_network"):
        parse_manifest_file(manifest)


def test_network_mirrors_must_be_array(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ngithub_mirrors = "not-a-list"\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="github_mirrors must be an array"):
        parse_manifest_file(manifest)


def test_network_mirror_must_be_non_empty_string(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ngithub_mirrors = [""]\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="non-empty string"):
        parse_manifest_file(manifest)


def test_network_timeout_must_be_positive(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ntimeout = 0\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="positive number"):
        parse_manifest_file(manifest)


def test_network_retry_must_be_non_negative_int(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\nretry = -1\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="non-negative integer"):
        parse_manifest_file(manifest)


def test_network_section_not_treated_as_tool(tmp_path: Path) -> None:
    """[_network] must not appear as a tool in the manifest dict."""
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ntimeout = 10\n\n[mytool]\n[mytool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    tools, _ = parse_manifest_file(manifest)
    assert "_network" not in tools
    assert "mytool" in tools


# ---------------------------------------------------------------------------
# Mirror fallback URL construction
# ---------------------------------------------------------------------------


def test_build_download_urls_no_mirrors() -> None:
    mgr = GithubReleaseManager(NetworkConfig())
    urls = mgr._build_download_urls("owner/repo", "releases/download/v1.0/file.tar.gz")
    assert len(urls) == 1
    assert urls[0] == "https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"


def test_build_download_urls_with_mirrors() -> None:
    net = NetworkConfig(github_mirrors=["https://m1.com", "https://m2.com"])
    mgr = GithubReleaseManager(net)
    urls = mgr._build_download_urls("owner/repo", "releases/download/v1.0/file.tar.gz")
    assert len(urls) == 3
    assert urls[0] == "https://m1.com/https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"
    assert urls[1] == "https://m2.com/https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"
    assert urls[2] == "https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"


# ---------------------------------------------------------------------------
# Download retry and mirror fallback (mocked)
# ---------------------------------------------------------------------------


def test_download_uses_first_mirror_on_success(tmp_path: Path) -> None:
    net = NetworkConfig(github_mirrors=["https://mirror.ok"], timeout=5, retry=0)
    mgr = GithubReleaseManager(net)

    fake_response = MagicMock()
    fake_response.read.return_value = b"binary-data"
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)

    dest = tmp_path / "asset"
    with patch("urllib.request.urlopen", return_value=fake_response) as mock_open:
        mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)

    req = mock_open.call_args[0][0]
    call_url = req.full_url if hasattr(req, "full_url") else str(req)
    assert "mirror.ok" in call_url
    assert dest.read_bytes() == b"binary-data"


def test_download_falls_back_to_direct_after_mirror_fails(tmp_path: Path) -> None:
    net = NetworkConfig(github_mirrors=["https://mirror.bad"], timeout=1, retry=0)
    mgr = GithubReleaseManager(net)

    success_response = MagicMock()
    success_response.read.return_value = b"ok-data"
    success_response.__enter__ = MagicMock(return_value=success_response)
    success_response.__exit__ = MagicMock(return_value=False)

    dest = tmp_path / "asset"
    call_urls = []

    def mock_urlopen(req: Any, timeout: float = 0) -> Any:
        url = req if isinstance(req, str) else req.full_url
        call_urls.append(url)
        if "mirror.bad" in str(url):
            raise urllib.error.URLError("mirror down")
        return success_response

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)

    assert len(call_urls) == 2  # mirror failed, then direct succeeded
    assert "mirror.bad" in call_urls[0]
    assert "github.com" in call_urls[1]
    assert dest.read_bytes() == b"ok-data"


def test_download_retries_on_transient_failure(tmp_path: Path) -> None:
    net = NetworkConfig(github_mirrors=[], timeout=1, retry=2)
    mgr = GithubReleaseManager(net)

    success_response = MagicMock()
    success_response.read.return_value = b"retry-ok"
    success_response.__enter__ = MagicMock(return_value=success_response)
    success_response.__exit__ = MagicMock(return_value=False)

    dest = tmp_path / "asset"
    attempt_count = [0]

    def mock_urlopen(req: Any, timeout: float = 0) -> Any:
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise urllib.error.URLError("transient")
        return success_response

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with patch("time.sleep"):
            mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)

    assert attempt_count[0] == 3  # 2 failures + 1 success
    assert dest.read_bytes() == b"retry-ok"


def test_download_raises_after_all_exhausted(tmp_path: Path) -> None:
    net = NetworkConfig(github_mirrors=["https://m1"], timeout=1, retry=0)
    mgr = GithubReleaseManager(net)

    dest = tmp_path / "asset"

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("always fail")):
        with patch("time.sleep"):
            with pytest.raises(Exception, match="Failed to download"):
                mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)


# ---------------------------------------------------------------------------
# _latest_tag uses timeout
# ---------------------------------------------------------------------------


def test_latest_tag_uses_timeout() -> None:
    import json

    net = NetworkConfig(timeout=42, retry=0)
    mgr = GithubReleaseManager(net)

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"tag_name": "v1.2.3"}).encode()
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_response) as mock_open:
        tag = mgr._latest_tag("owner/repo")

    assert tag == "v1.2.3"
    assert mock_open.call_args[1].get("timeout") == 42
