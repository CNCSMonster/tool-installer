"""Tests for [_github-release] manifest section, mirror fallback, and token detection."""

from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tool_installer.github_token import detect_github_token
from tool_installer.managers.github_release import GithubReleaseManager
from tool_installer.models import GithubReleaseConfig
from tool_installer.parser import parse_manifest_file


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, content: str) -> Path:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def _make_mock_response(data: bytes) -> MagicMock:
    """Create a mock HTTP response that supports chunked read()."""
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.side_effect = [data, b""]
    return resp


# ---------------------------------------------------------------------------
# [_github-release] parsing
# ---------------------------------------------------------------------------


def test_gh_release_defaults_when_absent(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, '[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n')
    _, cfg = parse_manifest_file(manifest)
    assert cfg.github_mirrors == []
    assert cfg.timeout == 30.0
    assert cfg.retry == 3


def test_gh_release_full_config(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\ngithub_mirrors = ["https://m1.example.com", "https://m2.example.com"]\ntimeout = 60\nretry = 5\n\n'
        '[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    _, cfg = parse_manifest_file(manifest)
    assert cfg.github_mirrors == ["https://m1.example.com", "https://m2.example.com"]
    assert cfg.timeout == 60.0
    assert cfg.retry == 5


def test_gh_release_mirror_trailing_slash_stripped(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\ngithub_mirrors = ["https://m1.example.com/"]\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    _, cfg = parse_manifest_file(manifest)
    assert cfg.github_mirrors == ["https://m1.example.com"]


def test_gh_release_unknown_field_rejected(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\nunknown_field = true\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="Unknown.*_github-release"):
        parse_manifest_file(manifest)


def test_gh_release_mirrors_must_be_array(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\ngithub_mirrors = "not-a-list"\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="github_mirrors must be an array"):
        parse_manifest_file(manifest)


def test_gh_release_mirror_must_be_non_empty_string(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\ngithub_mirrors = [""]\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="non-empty string"):
        parse_manifest_file(manifest)


def test_gh_release_timeout_must_be_positive(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\ntimeout = 0\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="positive number"):
        parse_manifest_file(manifest)


def test_gh_release_retry_must_be_non_negative_int(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\nretry = -1\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="non-negative integer"):
        parse_manifest_file(manifest)


def test_gh_release_section_not_treated_as_tool(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_github-release]\ntimeout = 10\n\n[mytool]\n[mytool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    tools, _ = parse_manifest_file(manifest)
    assert "_github-release" not in tools
    assert "mytool" in tools


# ---------------------------------------------------------------------------
# [_network] deprecated
# ---------------------------------------------------------------------------


def test_network_section_rejected_with_migration_hint(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_network]\ntimeout = 10\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    with pytest.raises(Exception, match="no longer supported.*_github-release"):
        parse_manifest_file(manifest)


def test_unknown_reserved_section_rejected(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        '[_unknown]\nfoo = true\n\n[tool]\n[tool.linux]\nmanager = "apt"\npkg = "git"\n',
    )
    # _unknown starts with _ but is not _network or _github-release
    # It should be silently ignored (reserved but not implemented)
    tools, cfg = parse_manifest_file(manifest)
    assert "_unknown" not in tools
    assert cfg.github_mirrors == []


# ---------------------------------------------------------------------------
# Mirror fallback URL construction
# ---------------------------------------------------------------------------


def test_build_download_urls_no_mirrors() -> None:
    mgr = GithubReleaseManager(GithubReleaseConfig())
    urls = mgr._build_download_urls("owner/repo", "releases/download/v1.0/file.tar.gz")
    assert len(urls) == 1
    assert urls[0] == "https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"


def test_build_download_urls_with_mirrors() -> None:
    cfg = GithubReleaseConfig(github_mirrors=["https://m1.com", "https://m2.com"])
    mgr = GithubReleaseManager(cfg)
    urls = mgr._build_download_urls("owner/repo", "releases/download/v1.0/file.tar.gz")
    assert len(urls) == 3
    assert urls[0] == "https://m1.com/https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"
    assert urls[1] == "https://m2.com/https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"
    assert urls[2] == "https://github.com/owner/repo/releases/download/v1.0/file.tar.gz"


# ---------------------------------------------------------------------------
# Download retry and mirror fallback (mocked)
# ---------------------------------------------------------------------------


def test_download_uses_first_mirror_on_success(tmp_path: Path) -> None:
    cfg = GithubReleaseConfig(github_mirrors=["https://mirror.ok"], timeout=5, retry=0)
    mgr = GithubReleaseManager(cfg)

    dest = tmp_path / "asset"
    with patch("urllib.request.urlopen", return_value=_make_mock_response(b"binary-data")) as mock_open:
        mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)

    req = mock_open.call_args[0][0]
    call_url = req.full_url if hasattr(req, "full_url") else str(req)
    assert "mirror.ok" in call_url
    assert dest.read_bytes() == b"binary-data"


def test_download_falls_back_to_direct_after_mirror_fails(tmp_path: Path) -> None:
    cfg = GithubReleaseConfig(github_mirrors=["https://mirror.bad"], timeout=1, retry=0)
    mgr = GithubReleaseManager(cfg)

    dest = tmp_path / "asset"
    call_urls = []

    def mock_urlopen(req: Any, timeout: float = 0) -> Any:
        url = req if isinstance(req, str) else req.full_url
        call_urls.append(url)
        if "mirror.bad" in str(url):
            raise urllib.error.URLError("mirror down")
        return _make_mock_response(b"ok-data")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)

    assert len(call_urls) == 2
    assert "mirror.bad" in call_urls[0]
    assert "github.com" in call_urls[1]
    assert dest.read_bytes() == b"ok-data"


def test_download_retries_on_transient_failure(tmp_path: Path) -> None:
    cfg = GithubReleaseConfig(github_mirrors=[], timeout=1, retry=2)
    mgr = GithubReleaseManager(cfg)

    dest = tmp_path / "asset"
    attempt_count = [0]

    def mock_urlopen(req: Any, timeout: float = 0) -> Any:
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise urllib.error.URLError("transient")
        return _make_mock_response(b"retry-ok")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with patch("time.sleep"):
            mgr._download_asset("owner/repo", "releases/download/v1.0/f.tar.gz", dest)

    assert attempt_count[0] == 3
    assert dest.read_bytes() == b"retry-ok"


def test_download_raises_after_all_exhausted(tmp_path: Path) -> None:
    cfg = GithubReleaseConfig(github_mirrors=["https://m1"], timeout=1, retry=0)
    mgr = GithubReleaseManager(cfg)

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

    cfg = GithubReleaseConfig(timeout=42, retry=0)
    mgr = GithubReleaseManager(cfg)

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"tag_name": "v1.2.3"}).encode()
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_response) as mock_open:
        tag = mgr._latest_tag("owner/repo")

    assert tag == "v1.2.3"
    assert mock_open.call_args[1].get("timeout") == 42


# ---------------------------------------------------------------------------
# Token detection
# ---------------------------------------------------------------------------


def test_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
    token, source = detect_github_token()
    assert token == "ghp_test123"
    assert "GITHUB_TOKEN" in source


def test_token_from_gh_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ghp_from_gh_cli\n", stderr="")
            token, source = detect_github_token()
    assert token == "ghp_from_gh_cli"
    assert "gh CLI" in source


def test_token_env_takes_priority_over_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ghp_cli_token\n", stderr="")
            token, source = detect_github_token()
    assert token == "ghp_env_token"
    assert "GITHUB_TOKEN" in source


def test_token_none_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("shutil.which", return_value=None):
        token, source = detect_github_token()
    assert token is None
    assert "not configured" in source


def test_token_none_when_gh_not_logged_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
            token, source = detect_github_token()
    assert token is None
    assert "not configured" in source


def test_token_none_when_gh_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            token, source = detect_github_token()
    assert token is None
    assert "not configured" in source
