# tool-installer

`tool-installer` is a dependency-free Python 3.8+ development-environment installation orchestrator.
It reads a fixed `tools.toml` in the current working directory, follows module dependencies,
loads the referenced manifest, validates the selected strategies for the current OS/architecture,
and processes tools strictly serially.

## Quick start

```bash
tool-installer install <module> --dry-run
tool-installer install <module>
```

`tools.toml` must contain:

```toml
[tool-installer]
manifest = "./manifest.toml"
```

A module may depend on other modules and may mark individual tools as optional:

```toml
[base]
python = "Python via mise"
rust = "Stable Rust"

[dev]
depends = ["base"]
example-script = { desc = "local bootstrap", allow_fail = true }
```

See `examples/` for a runnable dry-run fixture and `SPEC.md` for the full behavior contract.

## Manifest and managers

Each tool has a manifest strategy. Strategies can have base fields plus OS/architecture overrides.
Supported v1 managers are:

- `apt`
- `brew`
- `brew-cask`
- `cargo-binstall`
- `cargo-install`
- `rustup`
- `mise`
- `npm-global`
- `pnpm-global`
- `uv-tool`
- `github-release`
- `script`

Example `github-release` with installed-state probing:

```toml
[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}-unknown-linux-gnu.tar.gz"
bin = "fd"

[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd (?P<version>[0-9]+\.[0-9]+\.[0-9]+)"
```


## Single-file executable

The project can build a compact single-file executable for hosts that already have Python 3.8+.
The artifact is a Python zip application with a shebang; it does not embed CPython and does not
require runtime packages from PyPI. The vendored TOML fallback is included, so it also works on
Python versions without the standard-library `tomllib` module.

Build and verify the artifact:

```bash
scripts/build-single
wc -c dist/tool-installer  # must be <= 409600 bytes
./dist/tool-installer --help
cd examples && ../dist/tool-installer install dev --dry-run
```

Install a published artifact safely from a URL:

```bash
curl -fsSL https://example.com/install-single -o /tmp/install-tool-installer
sh /tmp/install-tool-installer https://example.com/tool-installer
```

The install script downloads to a temporary file, verifies `python3 <tmp> --help`, then replaces
the destination only after validation succeeds. The default destination is
`~/.local/bin/tool-installer`; pass a second argument to choose another path.

The build script verifies that the artifact is executable, below 400 KiB, can print CLI help,
and can dry-run the example fixture. External package managers such as `apt`, `brew`, `cargo`,
`rustup`, `npm`, `pnpm`, `uv`, and `mise` remain host-provided dependencies.

## Dry-run vs apply mode

`--dry-run` resolves dependencies, merges and validates strategies, then prints the serial plan.
It does **not** execute installed-state checks, package-manager metadata queries, downloads,
version probes, scripts, or mutation commands.

Apply mode processes one tool at a time:

1. If `force = true`, skip installed-state check and install.
2. Otherwise, run the manager's installed-state check when the manager is check-capable.
3. `satisfied` skips the tool.
4. `not_satisfied` installs the tool.
5. `check_error` fails that tool and does not fall back to install.

`allow_fail = true` downgrades a check/install failure for that tool to a warning and continues.
It does not suppress configuration, dependency, or strategy errors.

## Installed-state check caveats

Managers use manager metadata, not bare binary existence. In v1:

- `cargo-binstall` and `script` are not check-capable and install whenever reached.
- `uv-tool` is check-capable only for exact non-`latest` selectors.
- `github-release` is check-capable only when `version_probe` is defined.
- `brew` and `brew-cask` only support `latest` selectors.

## Privilege requirements

Some managers, such as `apt`, require root privileges to install packages. `tool-installer`
mirrors the dotfiles `sudo_run` helper:

- If already root, commands are executed directly.
- If not root, commands are prefixed with `sudo`.

### TTY requirement

`sudo` requires an interactive TTY to prompt for a password. In non-interactive environments
(CI, cron, `nohup`, SSH without `-t`), privileged installs fail with a clear error.

Options:

```bash
# local interactive use
tool-installer install dev

# run the whole installer as root when appropriate
sudo tool-installer install dev

# allocate a TTY over SSH
ssh -t user@host "tool-installer install dev"
```

`tool-installer` does not configure passwordless sudo; it respects the system sudo policy.
