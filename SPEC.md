# Tool-Installer Specification

## Status

This document is the source of truth for tool-installer's user-visible behavior, configuration semantics, dependency resolution semantics, environment matching, execution behavior, warning/error handling, and exit behavior.

This document is intended to be a stable behavior contract for v1 unless explicitly revised.

## Specification Boundary

This document primarily defines language-agnostic and implementation-agnostic behavior.

It does not require a specific CLI library, internal module layout, class name, function name, test framework, or package-manager command implementation, except where those choices affect user-visible behavior, safety, compatibility, distribution, or exit semantics.

The v1 distribution contract intentionally requires a Python-based single-file executable form because portability across hosts with an existing Python interpreter and a small artifact size are user-visible compatibility requirements.

## Goal

Tool-Installer is a declarative, cross-platform, modular development-environment installation orchestrator.

It reads a fixed entry configuration file, resolves the selected module and its dependencies into a deterministic installation plan, resolves installation strategies for the current environment from a manifest file, and executes the plan strictly serially.

Tool-Installer separates:

- what should be installed, defined by `tools.toml`
- how each tool should be installed on each supported platform, defined by the manifest referenced from `tools.toml`

## Scope and Non-Goals

Tool-Installer is responsible for:

- loading and validating `tools.toml`
- loading and validating the referenced manifest file
- resolving module dependencies for one selected target module
- detecting dependency cycles in the selected dependency graph
- deduplicating shared dependency modules
- enforcing tool-name uniqueness within the selected installation scope
- resolving the current OS/Arch installation strategy for every selected tool before installation starts
- producing a dry-run installation plan
- executing tool checks and installations strictly serially
- handling installation failures according to each tool's failure policy
- providing a compact single-file executable distribution for hosts that already have Python

Tool-Installer is not a general-purpose package manager.

It does not solve package dependency conflicts, replace system package managers, maintain a global package database, perform cross-manager version resolution, automatically discover installation strategies, install tools concurrently, sandbox external manager commands, or provide transactional rollback.

Tool-Installer does not put OS/Arch, manager, or install-command selection logic in `tools.toml`. Platform-specific installation behavior belongs in the manifest file.

Tool-Installer is not required to ship a native binary or embed a Python interpreter.

## Commands

### `tool-installer install <module>`

Installs the selected target module.

`<module>` must name one module in `tools.toml`. Exactly one target module must be specified. If no target module is specified, if more than one target module is specified, or if the target module does not exist, the command must fail before installation.

The install command uses a fixed entry configuration file named `tools.toml` in the current working directory.

The command must not accept an alternate tools file path and must not accept a separate manifest file path. Unsupported options such as `--tools` or `--manifest` are CLI argument errors.

### `--dry-run`

`--dry-run` is an operation parameter for `install`.

In dry-run mode, tool-installer performs the same CLI parsing, configuration loading, dependency resolution, uniqueness checks, environment detection, and strategy resolution as apply mode, but does not install tools.

Dry-run mode must not execute installation actions, scripts, package-manager install commands, download actions, mutation commands, external version queries, or installed-state checks. It produces the ordered plan that would be processed in apply mode, including each selected tool's parsed tool name, requested version selector, selected manager, normalized OS/Arch, force flag, and failure policy.

Dry-run success means the command was able to construct a valid plan. It does not mean the tools are already installed, installable from external registries, downloadable, latest-resolvable, or compatible with the host beyond the strategy validation defined by this specification.

For a requested version selector of `latest`, dry-run output keeps the requested selector as `latest`. Dry-run must not resolve `latest` to a concrete upstream version.

## Entry Configuration

`tool-installer install <module>` must read `tools.toml` from the current working directory.

`tools.toml` must contain a reserved `[tool-installer]` table with a `manifest` field:

```toml
[tool-installer]
manifest = "./manifest.toml"
```

`[tool-installer]` is not a module. All top-level tables other than `[tool-installer]` are modules.

The `manifest` value must be a non-empty string path.

Relative manifest paths are resolved relative to the directory containing `tools.toml`. Since `tools.toml` is fixed to the current working directory, this is normally the current working directory.

Absolute manifest paths are allowed and are used as-is.

Manifest paths must not perform shell expansion. Tool-Installer must not expand `~`, environment variables, globs, command substitutions, or other shell syntax in manifest paths.

If `tools.toml` is missing, unreadable, invalid, or if the referenced manifest file is missing, unreadable, or a directory, the command must fail before dependency resolution, strategy resolution, or installation.

## `tools.toml` Format

### Top-Level Structure

`tools.toml` must be a valid TOML document whose root is a table.

The root table must not contain bare top-level keys. Top-level entries must be tables.

The reserved `[tool-installer]` table is required. It must contain exactly one supported field: `manifest`.

Unknown fields in `[tool-installer]` are configuration errors.

All top-level tables other than `[tool-installer]` are modules.

### Validation Scope

The full `tools.toml` file must be valid TOML.

`[tool-installer]` must be valid regardless of which module is selected.

The target module must exist.

Full module schema validation, dependency validation, tool-reference validation, duplicate-tool detection, manifest strategy resolution, dry-run planning, and installation execution apply only to the selected target module and all modules reachable from it through `depends`.

Modules that are not reachable from the selected target module do not participate in duplicate-tool detection, strategy resolution, dry-run planning, or installation execution.

### Modules

A module name must be non-empty and is matched case-sensitively.

The module name `tool-installer` is reserved for `[tool-installer]` and cannot be used as a module name.

Other than the reserved name, this specification does not further restrict module-name characters beyond TOML table key semantics.

A module may be empty.

Within a module, `depends` is the only reserved field. If present, it must be an array of strings. The array may be empty. Every string in the array must be non-empty.

If `depends` is omitted, it is equivalent to an empty dependency list.

Each dependency name must refer to an existing module. Dependency names are matched exactly and case-sensitively.

The order of the `depends` array is significant. For a module with `depends = ["A", "B"]`, module `A` and its reachable dependencies must complete before module `B` starts, and both must complete before the declaring module starts.

A module must not depend on itself directly or indirectly. Dependency cycles are fatal errors.

If multiple dependency branches reference the same module, that module is processed once on first encounter in the ordered dependency traversal.

All keys in a module other than `depends` are tool entries. Module metadata fields are not supported in this version.

`depends` cannot be used as a tool name in a module.

### Tool References

Within a module, every key other than `depends` is interpreted as a tool reference after TOML parsing.

A tool reference must match this lexical grammar:

```text
tool-reference   = tool-name [ "@" version-selector ]

tool-name        = 1*tool-name-char
tool-name-char   = ASCII letter / ASCII digit / "." / "_" / "-" / "+"

version-selector = 1*version-char
version-char     = printable ASCII character except "@" and ASCII whitespace
```

`@` is a reserved version delimiter. A tool reference must contain at most one `@`.

If no `@` is present, the requested version policy is `latest`.

A tool key written as `tool` and a tool key written as `"tool@latest"` are equivalent after TOML parsing. In TOML source, a key containing `@` normally needs to be quoted.

If `@` is present, the part before `@` is the tool name and the part after `@` is the version selector. Both must be non-empty.

The tool reference must not contain ASCII whitespace.

The core resolver treats the version selector as a manager-specific opaque string. It must not query registries, parse, compare, normalize, or resolve version values to concrete versions.

Version satisfaction is evaluated only by the selected manager during apply-mode installed-state checks. For comparison purposes in those checks, v1 version equality is exact string equality after removing at most one leading ASCII `v` or `V` from each side. Tool-Installer must not perform semver parsing, version ordering, range matching, build metadata normalization, suffix stripping, or other loose coercion.

Tool names are matched case-sensitively.

Tool uniqueness is based on the parsed tool name only, not on the full tool reference or version selector.

### Tool Values

A tool value must be either a string or a table.

A string value is a human-readable description and is equivalent to a table with `desc` set to that string and `allow_fail = false`.

A table value may contain only these fields:

| Field | Type | Required | Default | Meaning |
|---|---|---:|---|---|
| `desc` | string | no | unspecified | Human-readable description only |
| `allow_fail` | bool | no | `false` | If true, installation failure for this tool is reported as a warning and execution continues |

Unknown fields in a tool value table are configuration errors.

A table value with no fields is valid and means no description with `allow_fail = false`.

Tool descriptions do not affect dependency resolution, strategy resolution, installation behavior, or exit behavior.

`allow_fail` applies only to installation failure of that tool. It does not suppress CLI errors, configuration errors, dependency errors, duplicate-tool errors, manifest errors, strategy resolution errors, or missing current-environment strategy errors.

A tool value table may be expressed using TOML inline table syntax or TOML table syntax, as long as the parsed value is a table attached to the tool key.

## Selected Installation Scope

The install command operates on the selected target module and all modules reachable from it through `depends`.

Tool-name uniqueness is enforced only among tools declared in those reachable modules.

Tools declared in modules that are not reachable from the selected target module do not affect the install command.

If the same parsed tool name appears more than once in the selected installation scope, that is a fatal configuration error, even if the version selectors differ.

Duplicate-tool errors must be detected before any installation starts.

## Manifest Selection and Format

The manifest file is selected only by `[tool-installer].manifest` in `tools.toml`.

The install command must not accept a separate manifest file path.

The manifest file must be a valid TOML document whose root is a table.

The manifest root table must not contain bare top-level keys.

Top-level manifest tables are logical tool names. They are matched case-sensitively against parsed tool names from the selected installation scope.

Only tools in the selected installation scope require complete manifest strategy validation.

The `platforms` field is not part of the supported manifest schema. Platform support is expressed only through OS/Arch strategy tables.

## Reserved Manifest Sections

Top-level manifest keys that begin with `_` (underscore) are reserved sections and are not interpreted as tool names.

### `[_network]`

The `[_network]` section configures global network behavior. It is optional. If absent, default network settings apply.

| Field | Type | Required | Default | Meaning |
|---|---|---:|---|---|
| `github_mirrors` | array of strings | no | `[]` | Ordered list of mirror base URLs for `github-release` downloads |
| `timeout` | number (seconds) | no | `30` | HTTP request timeout for `github-release` operations |
| `retry` | integer | no | `3` | Number of retries per HTTP request attempt |

`github_mirrors` entries must be non-empty strings. Trailing slashes are stripped. The mirror URL is prepended to the full GitHub download URL path (e.g., `mirror_url/https://github.com/owner/repo/releases/...`).

For `github-release` downloads, tool-installer tries each mirror in order. If a mirror fails all retry attempts, the next mirror is tried. If all mirrors fail, the direct GitHub URL is tried with the same retry policy. If all attempts fail, the installation fails for that tool.

Other managers (`apt`, `cargo`, `npm`, etc.) manage their own network configuration through their native mechanisms (e.g., `sources.list`, `cargo/config.toml`, `.npmrc`). Tool-installer does not override those configurations.

## Environment Names

Manifest OS names are:

- `linux`
- `macos`

Windows is not supported in v1.

Manifest architecture names are:

- `x86_64`
- `aarch64`

If the current OS or architecture cannot be normalized to one of the supported names, the command must fail before installation.

## Strategy Resolution

For every tool in the selected installation scope, tool-installer must resolve an executable strategy for the current OS/Arch before any installation starts.

A tool that does not have a top-level manifest table is a fatal manifest error.

A tool whose manifest table does not contain a current-OS strategy table is a fatal strategy resolution error.

For a tool, current OS, and current architecture, the merged strategy is built from:

```text
[tool] + [tool.<os>] + [tool.<os>.<arch>]
```

Only strategy fields from each layer participate in the merge. OS and architecture subtables are structural tables, not strategy fields.

Later layers override earlier layers for fields with the same name.

The architecture table is optional if the merged `[tool] + [tool.<os>]` strategy is already executable for the current architecture.

The merged strategy must contain `manager`.

The `manager` value must name a supported manager.

The merged strategy must satisfy the selected manager's required fields.

Failure to resolve an executable strategy is fatal and must be discovered before installation starts.

Tool-Installer must not infer installation strategies from tool names, operating systems, package-manager availability, or common conventions.

## Manager Strategy Fields

For each tool in the selected installation scope, the merged strategy is validated before installation starts.

Strategy field validation applies only to merged strategies that are used by the current install command.

A merged strategy may contain only common strategy fields and fields supported by the selected manager. Unknown fields in a used merged strategy are fatal strategy configuration errors.

Unless a field contract states otherwise, required string fields must be non-empty strings, optional string fields must be non-empty strings when present, boolean fields must be booleans, and string-array fields must be arrays whose elements are non-empty strings.

Common strategy fields are:

| Field | Type | Required | Default | Meaning |
|---|---|---:|---|---|
| `manager` | string | yes | none | Manager name for the executable strategy |
| `force` | bool | no | `false` | Skip installed-state check and directly attempt installation |

`force` is a manifest strategy field. It is optional and defaults to `false`.

If `force = true`, tool-installer skips the installed-state check for that tool and directly attempts installation.

`force` must not bypass CLI parsing, configuration validation, dependency resolution, duplicate-tool detection, environment detection, strategy validation, or failure handling.

A non-`latest` version selector must not be silently ignored by a manager. A manager must either honor the requested version selector or fail before reporting success.

The v1 supported manager names are:

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

A manifest strategy whose `manager` is not one of these names is a fatal strategy resolution error.

### Package Manager Contracts

| Manager | Required fields | Optional fields | Version selector behavior |
|---|---|---|---|
| `apt` | `pkg` | none | `latest` installs the package manager's current candidate for `pkg`; a non-`latest` selector requests that exact package version and must fail if it cannot be honored |
| `brew` | `pkg` | none | `latest` installs the current Homebrew formula; non-`latest` selectors are not supported in v1 and are fatal for this manager |
| `brew-cask` | `pkg` | none | `latest` installs the current Homebrew cask; non-`latest` selectors are not supported in v1 and are fatal for this manager |
| `cargo-binstall` | `pkg` | `bin` | `latest` installs the current crate release; a non-`latest` selector requests that crate version |
| `cargo-install` | `pkg` | `bin`, `locked`, `git`, `tag`, `branch`, `rev` | Registry installs honor `latest` or an exact crate version; git installs use `tag`, `branch`, or `rev` and require the tool version selector to be `latest` |
| `mise` | `plugin` | none | Installs `<plugin>@<selector>`; `latest` is passed as the selector `latest` |
| `npm-global` | `pkg` | `bin`, `registry` | Installs the global npm package for the requested selector; `latest` uses the package manager's latest/default dist-tag |
| `pnpm-global` | `pkg` | `bin`, `registry` | Installs the global pnpm package for the requested selector; `latest` uses the package manager's latest/default dist-tag |
| `uv-tool` | `pkg` | `bin`, `python`, `with` | `latest` installs `pkg`; a non-`latest` selector installs the Python package requirement equivalent to `pkg==selector` |
| `github-release` | `repo`, `asset`, `bin` | `sha256`, `install_name`, `version_probe` | `latest` resolves the repository's latest release; a non-`latest` selector is an exact release tag |
| `rustup` | none | `components`, `targets`, `profile`, `set_default` | See `rustup` manager version semantics below |
| `script` | `path` | none | The selector is passed to the script through environment variables |

`version_probe`, when supported by a manager, is a strategy subtable used for apply-mode installed-state checks. Its schema is defined in [Binary Version Probes](#binary-version-probes).

`bin`, when supported by a package-like manager, names the executable used for installed-state checks. If omitted, it defaults to the parsed logical tool name.

`locked`, when present for `cargo-install`, must be a boolean and requests locked dependency resolution for cargo installation.

For `cargo-install`, `git`, `tag`, `branch`, and `rev` must be strings when present. `tag`, `branch`, and `rev` are mutually exclusive. `tag`, `branch`, and `rev` may be used only when `git` is present. If `git` is present and the tool version selector is not `latest`, the strategy is invalid because v1 does not define two independent version sources for a git cargo install.

For `npm-global` and `pnpm-global`, `registry` is an optional package-registry URL string. Tool-Installer must pass it only to the selected manager and must not reinterpret it as a manifest source.

For `uv-tool`, `python` is an optional Python version/interpreter selector string. `with` is an optional array of additional Python package requirement strings to install into the tool environment.

The `mise` manager represents one mise-managed tool per tool entry. It must not treat an external `mise/config.toml` as an opaque profile for installing multiple hidden tools. Each mise-installed tool that should participate in dependency ordering, duplicate detection, failure policy, and dry-run planning must appear as its own tool entry in `tools.toml`.

### `rustup` Manager

For the `rustup` manager, the requested version policy is interpreted as a rustup toolchain selector.

The version policy `latest` maps to the rustup `stable` selector.

The selector `stable` means the latest stable Rust channel. The selector `nightly` means the latest nightly Rust channel. Other non-`latest` selectors are passed as rustup toolchain selectors without interpretation by tool-installer.

Rustup can install multiple toolchains. To install multiple Rust toolchains in one selected installation scope, users must declare distinct logical tool names, such as `rust`, `rust-nightly`, or `rust-1.78`. The strict tool-name uniqueness rule still applies and has no rustup-specific exception.

`components` is an optional array of rustup component names. `targets` is an optional array of rustup target names. `profile` is an optional rustup profile string.

A `rustup` strategy may set `set_default = true` to make the installed toolchain the default Rust toolchain. If omitted, `set_default` defaults to `false`.

At most one used `rustup` strategy in a single install command may set `set_default = true`. Multiple used `rustup` strategies with `set_default = true` are a fatal strategy configuration error and must be detected before installation starts.

### `github-release` Manager

`repo` must be in `owner/name` form. URL forms are not supported in v1.

`asset` names the release asset to download after placeholder substitution. It is an exact asset name, not a glob, regular expression, or shell pattern.

The supported placeholders in `asset` are:

| Placeholder | Replacement |
|---|---|
| `{tool}` | Parsed logical tool name |
| `{version}` | For a non-`latest` selector, the exact requested release tag; for `latest`, the latest release tag once it is resolved in apply mode |
| `{os}` | Normalized OS name |
| `{arch}` | Normalized architecture name |

No other placeholders are defined in v1.

Dry-run mode does not resolve the latest GitHub release tag and must not download release metadata solely for placeholder substitution. A dry-run plan may show the requested selector `latest` rather than a concrete GitHub release tag.

A non-`latest` version selector is an exact GitHub release tag. Tool-Installer must not add or remove a leading `v`, normalize semver, or search for similar tags.

`bin` is the relative path to the executable file within the downloaded asset contents. It must not be absolute, empty, or contain `..` path components.

If the asset is an archive, `bin` is resolved inside the extracted archive contents. If the asset is a single-file binary, the asset is treated as containing one file named by the asset filename, and `bin` must name that file.

`install_name`, if present, is the filename to install. It must be a non-empty filename without path separators. If omitted, it defaults to the parsed logical tool name.

A `github-release` install places the executable at `$HOME/.local/bin/<install_name>`. If `HOME` is not set or is empty, the installation fails for that tool. Tool-Installer must create `$HOME/.local/bin` if it does not exist.

`sha256`, if present, must be a 64-character hexadecimal SHA-256 digest of the downloaded asset bytes before extraction. A checksum mismatch is an installation failure and must prevent replacing the installed executable.

For `github-release`, tool-installer must not replace or remove an existing installed executable until the release asset has been downloaded, verified when `sha256` is present, and the requested `bin` has been located successfully. The installed file must be executable after a successful install.

The supported archive formats for v1 are `.zip`, `.tar.gz`, `.tgz`, and `.tar.xz`. If an asset is neither a supported archive nor a single-file binary asset matching `bin`, installation fails for that tool.

Archive extraction must be fail-closed. Tool-Installer must extract archives into a temporary staging location before installing the executable. Archive entries with absolute paths, parent-directory traversal, or other paths that would write outside the staging location must not be written outside the staging location. Symlink entries must not allow the requested `bin` to resolve outside the extracted archive contents. If tool-installer cannot enforce these containment rules for an archive, installation fails for that tool and the existing installed executable must not be replaced.

A `github-release` strategy may define `version_probe`. If present, `github-release` is check-capable for that tool. If absent, `github-release` is not check-capable for that tool and will execute its install action every time it is reached in apply mode.

### Binary Version Probes

A binary version probe is a manifest-defined command and parser used by a check-capable manager to determine the installed version of a tool during apply-mode installed-state checks.

A version probe is expressed as a `version_probe` subtable on a merged strategy:

```toml
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}-unknown-linux-gnu.tar.gz"
bin = "fd"

[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd (?P<version>v?[0-9]+\\.[0-9]+\\.[0-9]+)"
```

`version_probe.command` is required. It must be a non-empty array of non-empty strings. Tool-Installer executes it directly as an argument vector and must not execute it through a shell command string.

The only placeholder supported in `version_probe.command` for v1 is `{bin}`. `{bin}` is replaced with the manager-resolved installed executable path for the tool. Tool-Installer must not guess that the bare executable name on `PATH` refers to the intended installed binary.

No other `version_probe.command` placeholders are defined in v1. `{tool}`, `{version}`, manager fields, environment variables, shell substitutions, globs, and arbitrary template expressions are not supported.

`version_probe.regex` is required. It must be a valid regular expression containing a named capture group called `version`. The first match against stdout is used. If the regex does not match stdout, or if it matches but does not capture `version`, the probe result is a check error.

In v1, version probes parse stdout only. There is no `stream` field in v1. Tools whose version output is available only on stderr are not supported by binary version probes unless their command can be expressed so that the desired version text appears on stdout without using a shell.

A version probe runs only in apply mode as part of an installed-state check. Dry-run mode must not execute version probes.

A version probe exit status other than `0`, a timeout or execution failure, or unparseable stdout is a check error.

The version captured by the probe is compared to the requested version selector for non-`latest` tools, or to the latest concrete version resolved by the manager for `latest` tools, using v1 version equality.

### `script` Manager

The `script` manager is a constrained escape hatch for installation steps that cannot be expressed with built-in declarative managers.

A `script` strategy must contain:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `manager` | literal `"script"` | yes | Selects the script manager |
| `path` | non-empty string | yes | Relative path to an executable installer file |

`path` must be a normal relative path resolved relative to the directory containing the manifest file.

`path` must not be absolute, must not be empty, and must not contain parent-directory traversal components (`..`).

Tool-Installer must not perform shell expansion on `path`. It must not expand `~`, environment variables, globs, command substitutions, or other shell syntax.

The resolved script path must remain inside the manifest directory tree.

During strategy resolution, before any installation starts, the resolved script path must exist, must be a regular file, and must be executable. Otherwise the command fails with a fatal strategy configuration error.

The script manager executes the referenced file directly and must not execute it through a shell command string. The script file may choose its own interpreter through its shebang.

The script manager does not support installed-state checks in v1. When a script-managed tool is reached in apply mode, the script is executed regardless of `force`. Idempotency is the script author's responsibility.

When executing the script, tool-installer must provide at least these environment variables:

| Environment variable | Meaning |
|---|---|
| `TOOL_INSTALLER_TOOL_NAME` | Parsed logical tool name |
| `TOOL_INSTALLER_VERSION` | Requested version selector after applying the default version policy, for example `latest`, `stable`, or `1.2.3` |
| `TOOL_INSTALLER_OS` | Normalized OS name |
| `TOOL_INSTALLER_ARCH` | Normalized architecture name |
| `TOOL_INSTALLER_FORCE` | `true` if the merged strategy has `force = true`, otherwise `false` |

The script must receive no tool-installer-defined positional arguments in v1. Future versions may add environment variables but must not change the meaning of the variables above.

A script exit status of `0` means success. A non-zero script exit status is an installation failure and is handled according to the tool's `allow_fail` policy.

The `script` manager should be used only when built-in declarative managers cannot express the installation behavior. Script behavior is trusted external code and is not sandboxed by tool-installer.

## Installed-State Checks

In apply mode, each tool is processed serially. If the merged strategy has `force = false`, tool-installer performs the selected manager's installed-state check before attempting installation, except for managers that explicitly do not support checks.

If `force = true`, tool-installer skips the installed-state check and directly attempts installation. For a manager that does not support installed-state checks, `force = true` has no additional effect because that manager already executes its install action whenever reached in apply mode.

Installed-state checks have exactly three semantic outcomes:

| Outcome | Meaning | Next action |
|---|---|---|
| `satisfied` | The installed tool satisfies the requested version selector | Skip the tool and consider it successful |
| `not_satisfied` | The installed tool is absent or does not satisfy the requested version selector | Attempt installation |
| `check_error` | The manager could not determine installed state | Treat as an installation failure for that tool |

A `check_error` includes, but is not limited to, manager unavailability, manager metadata errors, permission errors, network failures while resolving latest concrete versions, failed binary version probes, version probe timeouts, and unparseable version probe output.

A `check_error` must not automatically fall back to installation. It is an installation failure for that tool unless `allow_fail = true` downgrades it to a warning. Users may set `force = true` to bypass a failing installed-state check and attempt installation directly.

For any requested version selector, including `latest`, a check-capable manager must not report `satisfied` unless it can verify that the installed tool satisfies the requested selector. Binary existence alone is never sufficient.

For a requested selector of `latest`, the manager resolves the latest concrete version during apply-mode installed-state check and compares the installed version to that concrete version. Dry-run mode must not resolve latest concrete versions.

For non-`latest` selectors, a manager must not report a tool as installed unless it can verify that the installed tool satisfies the requested selector. If it cannot verify selector satisfaction, it must report `not_satisfied` or `check_error`; it must not silently treat an arbitrary installed version as satisfying the request.

A manager that is not check-capable for a tool executes its install action every time that tool is reached in apply mode. The `script` manager does not support installed-state checks in v1 and always runs when reached in apply mode.

Manager check capability in v1 is defined by this table. A manager is check-capable for a tool only when this specification defines enough manager-specific behavior to verify selector satisfaction without relying only on binary existence.

| Manager | Installed-state check capability |
|---|---|
| `apt` | Check-capable. Installed version is read from the local dpkg package database. For `latest`, the candidate version is read from local APT package metadata and compared with the installed version. If the package is not installed, the dpkg database is unavailable, or candidate-version metadata is unavailable for a `latest` check, the result is `not_satisfied` or `check_error` according to the failure. |
| `brew` | Check-capable for `latest` formula installs. Installed formula versions are read from Homebrew installed-formula metadata. The check must determine whether Homebrew considers the formula current or outdated; if this cannot be determined, the result is `check_error`. Non-`latest` selectors are invalid for this manager before execution. |
| `brew-cask` | Check-capable for `latest` cask installs. Installed cask versions are read from Homebrew installed-cask metadata. The check must determine whether Homebrew considers the cask current or outdated; if this cannot be determined, the result is `check_error`. Non-`latest` selectors are invalid for this manager before execution. |
| `cargo-install` | Check-capable only when cargo installation tracking metadata exists and identifies the installed package version and source. If cargo tracking is absent, disabled, ambiguous, or source/version cannot be matched to the requested selector, the result is `check_error`. Registry installs compare the installed crate version to the requested exact version or to the current registry version for `latest`. Git installs compare the tracked git source/revision to the requested git source/revision when available; otherwise they are not satisfied. |
| `cargo-binstall` | Not independently check-capable in v1. Although it installs cargo crates, no separate authoritative cargo-binstall installed-state metadata is defined in v1. A future revision may treat it as sharing `cargo-install` tracking semantics only if verified against cargo-binstall behavior. |
| `rustup` | Check-capable. Installed toolchains are read from rustup toolchain state. The requested selector is satisfied when the corresponding rustup toolchain is installed, required components are installed for that toolchain, and required targets are installed for that toolchain. For moving channels such as `stable` or `nightly`, the check must determine whether rustup reports the installed channel as current; if update status cannot be determined, the result is `check_error`. |
| `mise` | Check-capable. Installed versions are read from mise installed-tool metadata. The requested selector is satisfied when mise reports an installed version for the requested plugin that matches the selector, or when mise reports the installed version as satisfying `latest`. If the selector is a moving alias or prefix and mise cannot determine current/latest status, the result is `check_error`. |
| `npm-global` | Check-capable. Installed package version is read from npm global package metadata. For `latest`, the latest/default registry version is read from npm package metadata and compared with the installed version. If global package metadata or registry metadata required for `latest` is unavailable, the result is `not_satisfied` or `check_error` according to the failure. |
| `pnpm-global` | Check-capable. Installed package version is read from pnpm global package metadata. For `latest`, the latest/default registry version is read from pnpm package metadata and compared with the installed version. If global package metadata or registry metadata required for `latest` is unavailable, the result is `not_satisfied` or `check_error` according to the failure. |
| `uv-tool` | Check-capable only for exact non-`latest` selectors when uv tool metadata records the version specifier used to install the tool. `latest` checks are not check-capable in v1 because this specification does not define an authoritative uv tool latest-version metadata source. |
| `github-release` | Check-capable only when the merged strategy defines `version_probe`; otherwise not check-capable. |
| `script` | Not check-capable in v1. |

A manager that is not check-capable executes its install action every time it is reached in apply mode.

A future revision may change a manager's check capability, but it must define the authoritative metadata source used for the check, how that source maps to the requested version selector, and which failures are `check_error`. A manager must not be treated as check-capable if its check only verifies that a binary exists.

Tool-Installer does not require manager command availability to be validated before the whole plan starts. A manager executable may be installed by an earlier tool in the same serial plan. Manager unavailability is therefore detected when the affected tool is installed, or when a check-capable manager checks the affected tool, and is handled as that tool's installation failure.

## Serial Execution

Tool installation is strictly serial.

After dependency and strategy resolution, the installation plan is an ordered list of tool actions. In apply mode, the implementation must process that list one item at a time, in order.

The next tool must not begin checking or installing until the previous tool has reached a terminal state: skipped, successfully installed, failed with `allow_fail = true`, or failed fatally.

Implementations must not install tools concurrently, check tools concurrently, run manager installation actions in parallel, or reorder tools for performance.

Serial execution is part of the user-visible behavior contract, not an implementation detail.

## Transaction and Rollback Semantics

Tool-Installer is not transactional.

When running in apply mode, each tool installation may modify the system through its selected manager. If a later tool fails, installations that completed earlier are not automatically undone.

If a tool installation fails and `allow_fail` is false or omitted, execution stops immediately and the command exits with a non-zero status.

If a tool installation fails and `allow_fail = true`, the failure is reported as a warning, execution continues, and that failure does not by itself cause a non-zero exit code. The warning must identify the tool name, selected manager, failure phase (`check` or `install`), and the available failure reason, such as a check error category, exception message, external command exit status, or script exit status. Exact warning wording is not stable.

In both cases, successfully completed earlier installations remain in place.

Users may fix the cause of failure and run tool-installer again.

Tool-Installer does not maintain persistent checkpoint files, transaction logs, download caches, or partial-installation recovery state in v1. Rerunning after a failure means tool-installer reloads configuration, re-resolves the plan, and traverses the plan from the beginning.

This recovery model is plan-level rerun convergence: check-capable tools that already satisfy their requested version selectors are skipped, tools that are absent or version-mismatched are installed, and tools managed by non-check-capable managers run again when reached.

Recovery of a single tool's partially completed download or installation is delegated entirely to that tool's selected manager. Tool-Installer does not define, require, or emulate per-manager resume behavior.

## Error and Exit Semantics

CLI argument errors, configuration errors, dependency errors, duplicate-tool errors, manifest errors, strategy resolution errors, unsupported current OS/Arch errors, and non-allowed installation failures are fatal and result in a non-zero exit status.

Installation failures covered by `allow_fail = true` do not make the command fail by themselves. If all non-optional tools complete successfully, are skipped by installed-state checks, or fail only under `allow_fail = true`, the command exits with status `0`.

Exact non-zero exit code values are implementation-defined. Scripts should only rely on zero versus non-zero.

## Output Semantics

Exact human-facing output wording is not stable in v1.

Warnings and errors must be visible to the user and must not be silently ignored.

Fatal errors must identify the relevant phase and, when applicable, the module, tool, manifest strategy, or path involved.

Tool-installer's own progress messages and dry-run plan output must be written to stdout.

Tool-installer's own warnings and errors must be written to stderr.

Output produced by external managers and scripts may be streamed through to the same stdout/stderr channels used by those external processes. Tool-Installer is not required to normalize, parse, translate, or make stable the output of external managers.

There is no machine-readable output mode in v1.

## Distribution

Tool-Installer v1 must be easy to distribute to machines that already have Python but may not have project-specific Python packages installed.

The project must provide:

- a compact single-file executable artifact that preserves the `tool-installer` CLI behavior;
- a safe installation path for downloading that artifact without corrupting an existing working installation when the download fails or is incomplete.

The single-file artifact must be self-contained with respect to Tool-Installer's Python code, including TOML parsing on Python versions without the `tomllib` standard-library module. It may rely on the host Python interpreter and on external package managers selected by the user's manifest; it is not required to embed CPython or bundle host package managers.

The generated artifact must remain below 400 KiB, measured as at most 409,600 bytes. Smaller artifacts are preferred when they preserve behavior and compatibility.

Release verification must prove that the artifact is executable, satisfies the size limit, works without non-standard Python packages on the target host, and can run the documented smoke checks.

## Security and Trust Model

`tools.toml`, the referenced manifest, external package managers, downloaded release assets, and script manager files are trusted inputs for the purpose of a tool-installer run.

Tool-Installer does not sandbox package managers, scripts, downloaded executables, archive extraction tools, or installed programs.

The manifest cannot define inline shell commands in v1. Custom imperative behavior must use the constrained `script` manager and point to an executable file within the manifest directory tree.

Path fields defined by this specification do not perform shell expansion unless explicitly stated otherwise.

Checksum verification, when provided by a manager contract such as `github-release.sha256`, is an integrity check for downloaded bytes, not a general security guarantee.

## Performance Boundaries

Tool-Installer is intended for interactive development-environment setup.

Configuration loading, dependency resolution, conflict checking, and dry-run planning should remain practical for O(10^2-10^3) tools and O(10^1-10^2) modules.

Common operations should scale roughly with the number of reachable modules, selected tools, and resolved strategies. Implementations should avoid visibly superlinear repeated full-graph scans where avoidable.

Installation time is dominated by external managers and is not bounded by this specification.
