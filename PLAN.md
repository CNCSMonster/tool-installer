# Implementation Plan: tool-installer v1

## Overview

Implement tool-installer as specified in `SPEC.md`: a Python 3.8+ declarative development-environment installation orchestrator that reads fixed `tools.toml`, resolves selected modules and dependencies, validates manifest strategies for the current OS/Arch, produces dry-run plans, and executes tool checks/installations strictly serially.

`SPEC.md` is the behavior source of truth. This file is the implementation roadmap and progress tracker for the current Python implementation.

## Current Progress

- [x] Phase 1: Foundation, parsing, resolver, strategy merge, basic CLI
- [x] Phase 2: Basic executor and command construction
- [x] Phase 3: Align installed-state check model with SPEC
- [x] Phase 4: Harden manager validation and script/github-release safety
- [x] Phase 5: Implement verified real manager checks
- [x] Phase 6: Expand conformance tests and examples
- [x] Phase 7: Python 3.8 packaging/runtime verification
- [x] Phase 8: Single-file executable distribution
- [x] Phase 9: Network configuration and GitHub mirror fallback
- [x] Phase 10: Manager configuration layer and GitHub token auto-detection
- [ ] Phase 11: cargo-install binstall_first optimization

Current test status:

```text
python3 -m pytest
171 passed
```

Final Phase 5-7 verification: `python3 -m pytest` => `143 passed`; latest documentation-closeout verification: `python3 -m pytest -q` => `143 passed in 0.28s`. Single-file distribution verification: `scripts/build-single` => `dist/tool-installer` is 29,925 bytes and examples dry-run succeeds; safe install verification is covered by `tests/test_distribution.py`; latest full verification: `python3 -m pytest -q` => `145 passed`. Phase 9 verification: `python3 -m pytest -q` => `163 passed` (16 new network config tests).

## Architecture Decisions

- Keep runtime dependency-free; use stdlib `tomllib` with vendored `tomli` fallback.
- Keep `SPEC.md` implementation-agnostic; put Python-specific work, packaging, and test sequencing here.
- Separate behavior phases: parse → resolve → strategy validation → plan → dry-run/apply.
- Dry-run must not execute installed-state checks, external version queries, downloads, scripts, or mutation commands.
- Installed-state checks must return the SPEC outcomes: `satisfied`, `not_satisfied`, or `check_error`; binary existence alone is never sufficient.
- Treat missing/ambiguous manager metadata as `not_satisfied` or `check_error` according to SPEC, not as successful skip.
- Keep manager command execution direct argv-based; avoid shell except where an external manager explicitly requires its own executable.
- Add tests before/with behavior changes; every phase should leave `python3 -m pytest` green.

## Current Implementation Snapshot

Already present and verified:

- Python package scaffold and CLI entry point.
- TOML loading with Python 3.11+ `tomllib` and vendored `tomli` fallback path.
- `tools.toml` parsing with selected-scope validation.
- Manifest loading, OS/Arch strategy merge, and `bin` defaults for managers that support binaries.
- Dependency traversal, cycle detection, diamond deduplication, and duplicate tool detection within selected scope.
- Dry-run CLI path that performs validation without executing checks, external queries, downloads, scripts, or mutations.
- Explicit installed-state check outcomes: `satisfied`, `not_satisfied`, and `check_error`.
- Manager registry and command construction for all supported v1 managers.
- Metadata/state-based installed-state checks for check-capable managers.
- Non-check-capable behavior for `cargo-binstall`, `script`, `github-release` without `version_probe`, and `uv-tool` with `latest`.
- `github-release.version_probe` validation and apply-mode probe execution.
- Fail-closed `github-release` archive extraction and atomic install behavior.
- Script manager path containment, direct execution, and environment contract.
- SPEC-derived conformance coverage, updated examples, and README.
- Single-file Python zip application build via `scripts/build-single`; generated artifact includes vendored TOML fallback, is executable, and is verified below 400 KiB.
- Safe artifact installation via `scripts/install-single`, which downloads to a temporary file, validates the artifact, and only then replaces the destination.
- Test suite passes on Python 3.12 and Python 3.8.20 (verified via `uv run --python 3.8` in devbox container).

Known divergences from current `SPEC.md`: none for v1 release readiness.

---

## Phase 1: Foundation, Parsing, Resolver, Strategy Merge, Basic CLI

### Task 1: Package scaffold and test harness

**Status:** Done

**Acceptance criteria:**

- [x] Package imports from `src/tool_installer`.
- [x] `python -m tool_installer --help` reaches CLI parser.
- [x] Test runner discovers tests under `tests/`.
- [x] No external runtime dependencies are added.

**Verification:**

- [x] `python3 -m pytest tests/test_cli_smoke.py`

**Dependencies:** None

**Files touched:**

- `pyproject.toml`
- `src/tool_installer/__init__.py`
- `src/tool_installer/__main__.py`
- `src/tool_installer/cli.py`
- `tests/test_cli_smoke.py`

**Scope:** Small

### Task 2: Core models, errors, and TOML loader

**Status:** Done

**Acceptance criteria:**

- [x] Models represent tool references, modules, strategies, plan items, and environments.
- [x] Domain errors distinguish config, dependency, manifest, strategy, CLI, and installation failures.
- [x] TOML loader handles valid, invalid, missing, unreadable files.
- [x] Runtime does not require PyPI `tomli`.

**Verification:**

- [x] `python3 -m pytest tests/test_models.py tests/test_toml_loader.py`

**Dependencies:** Task 1

**Files touched:**

- `src/tool_installer/models.py`
- `src/tool_installer/errors.py`
- `src/tool_installer/toml_loader.py`
- `src/tool_installer/vendor/tomli/`
- `tests/test_models.py`
- `tests/test_toml_loader.py`

**Scope:** Medium

### Task 3: Parse `tools.toml` and manifest basics

**Status:** Done

**Acceptance criteria:**

- [x] Requires `[tool-installer].manifest`.
- [x] Rejects unknown `[tool-installer]` fields and bare top-level keys.
- [x] Parses string and table tool values.
- [x] Implements tool reference grammar and defaults missing selector to `latest`.
- [x] Validates reachable modules while leaving unreachable module tool schema out of scope.
- [x] Parses manifest top-level tool tables.

**Verification:**

- [x] `python3 -m pytest tests/test_parser_resolver_strategy.py`

**Dependencies:** Task 2

**Files touched:**

- `src/tool_installer/parser.py`
- `tests/test_parser_resolver_strategy.py`

**Scope:** Medium

### Task 4: Resolve modules and build strategy plan

**Status:** Done

**Acceptance criteria:**

- [x] Missing target/dependency handling is fatal.
- [x] Dependency order and diamond deduplication work.
- [x] Cycles and duplicate selected tool names are fatal.
- [x] Environment normalization supports `linux`/`macos` and `x86_64`/`aarch64`.
- [x] Strategy merge supports base + OS + Arch overrides.
- [x] `script.path` preflight validation exists.
- [x] Dry-run prints a plan without running scripts or installs.

**Verification:**

- [x] `python3 -m pytest tests/test_parser_resolver_strategy.py tests/test_cli_integration.py`

**Dependencies:** Task 3

**Files touched:**

- `src/tool_installer/environment.py`
- `src/tool_installer/resolver.py`
- `src/tool_installer/strategy.py`
- `src/tool_installer/cli.py`
- `src/tool_installer/executor.py`
- `tests/test_parser_resolver_strategy.py`
- `tests/test_cli_integration.py`

**Scope:** Medium

### Checkpoint: Historical Phase 1 Baseline

- [x] `python3 -m pytest` passed at the Phase 1 checkpoint: `22 passed`.
- [x] Example dry-run succeeds.
- [x] Current apply-mode installed-state checks satisfy `SPEC.md` after Phase 3-5 refactors.

---

## Phase 2: Basic Executor and Command Construction

### Task 5: Basic executor and fake manager semantics

**Status:** Done; SPEC-alignment refactor completed in Phase 3

**Acceptance criteria completed:**

- [x] Executes plan in order.
- [x] Honors `force` by skipping current check path.
- [x] Historically skipped installed items in the initial boolean check model before the Phase 3 refactor.
- [x] Stops on non-allowed installation failure.
- [x] `allow_fail = true` warns and continues.

**Completed follow-up:**

- [x] Replace boolean installed check with `CheckResult` outcomes.
- [x] Track failure phase for diagnostics.

**Verification:**

- [x] `python3 -m pytest tests/test_executor_managers.py`

**Dependencies:** Task 4

**Files touched:**

- `src/tool_installer/executor.py`
- `src/tool_installer/managers/base.py`
- `tests/test_executor_managers.py`

**Scope:** Medium

### Task 6: Basic command construction for real managers

**Status:** Done; SPEC-alignment refactor completed in Phase 5

**Acceptance criteria completed:**

- [x] Command construction exists for apt, brew, brew-cask, cargo-binstall, cargo-install, mise, npm-global, pnpm-global, uv-tool, rustup.
- [x] Rustup install command supports components, targets, and `set_default` follow-up.
- [x] Commands are unit-tested without executing package managers.

**Completed follow-up:**

- [x] Remove binary-existence-only checks.
- [x] Add manager-specific metadata checks.
- [x] Add check-error behavior and tests.

**Verification:**

- [x] `python3 -m pytest tests/test_executor_managers.py`

**Dependencies:** Task 5

**Files touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_executor_managers.py`

**Scope:** Medium

---

## Phase 3: Align Installed-State Check Model with SPEC

### Task 7: Introduce explicit check outcomes

**Status:** Done

**Description:** Replace boolean `supports_check/is_installed` semantics with an explicit check result model matching `SPEC.md`.

**Acceptance criteria:**

- [x] Introduce `CheckResult` enum or equivalent with `satisfied`, `not_satisfied`, and `check_error` outcomes.
- [x] Manager protocol changes from `is_installed() -> bool` to `check(item) -> CheckResult`.
- [x] Executor treats `satisfied` as skip/success.
- [x] Executor treats `not_satisfied` as install.
- [x] Executor treats `check_error` as installation failure for that tool (does NOT fall back to install).
- [x] `force = true` bypasses checks and attempts installation.
- [x] Non-check-capable managers have `check` return `not_satisfied` (or skip check entirely) and always install when reached.
- [x] `github-release` check capability becomes conditional: check-capable only when `version_probe` is defined.
- [x] `cargo-binstall` becomes non-check-capable.
- [x] Existing tests are migrated away from boolean `is_installed`.

**Verification:**

- [x] `python3 -m pytest tests/test_executor_managers.py`
- [x] `python3 -m pytest`

**Dependencies:** Task 5

**Files likely touched:**

- `src/tool_installer/models.py`
- `src/tool_installer/managers/base.py`
- `src/tool_installer/managers/commands.py`
- `src/tool_installer/managers/github_release.py`
- `src/tool_installer/executor.py`
- `tests/test_executor_managers.py`

**Scope:** Medium

### Task 8: Improve allow_fail diagnostics

**Status:** Done

**Description:** Make warning diagnostics include the minimum fields required by `SPEC.md`.

**Acceptance criteria:**

- [x] Warnings identify tool name, selected manager, failure phase (`check` or `install`), and the available failure reason/status.
- [x] Exact wording remains human-facing and not machine-stable.
- [x] Non-allowed failures still stop execution and return non-zero through CLI.

**Verification:**

- [x] `python3 -m pytest tests/test_executor_managers.py tests/test_cli_integration.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/errors.py`
- `src/tool_installer/executor.py`
- `tests/test_executor_managers.py`
- `tests/test_cli_integration.py`

**Scope:** Small

### Checkpoint: Executor SPEC Alignment

- [x] Boolean installed checks removed.
- [x] `check_error` never falls back to install unless `force = true` bypasses the check.
- [x] `allow_fail` warnings contain required diagnostics (tool, manager, phase, reason).
- [x] `python3 -m pytest` passes.

---

## Phase 4: Harden Strategy Validation, Script, and GitHub Release Safety

### Task 9: Validate `github-release.version_probe`

**Status:** Done

**Description:** Add strategy validation for the `version_probe` subtable and preserve it in merged strategy fields.

**Acceptance criteria:**

- [x] `version_probe` is added to `github-release` optional fields in `_SUPPORTED`.
- [x] `version_probe` is allowed only for `github-release` manager (not for other managers in v1).
- [x] `version_probe.command` is validated as a non-empty array of non-empty strings.
- [x] `version_probe.command` strings are validated to use only `{bin}` placeholder.
- [x] `version_probe.regex` is validated as a compilable regex with a named capture group `version`.
- [x] Unknown `version_probe` fields are fatal.
- [x] `bin` default is set to the parsed logical tool name when omitted for managers that support it.
- [x] Dry-run does not execute probes.

**Verification:**

- [x] `python3 -m pytest tests/test_parser_resolver_strategy.py`
- [x] `python3 -m pytest`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/strategy.py`
- `src/tool_installer/models.py` (if version_probe needs structured representation)
- `tests/test_parser_resolver_strategy.py`
- `tests/test_manager_github_release.py`

**Scope:** Medium

### Task 10: Harden `github-release` archive extraction

**Status:** Done

**Description:** Replace unsafe archive extraction with fail-closed containment checks.

**Acceptance criteria:**

- [x] Archives are extracted only into a temporary staging directory.
- [x] Absolute archive entry paths are contained before writing (not written outside staging).
- [x] Parent-directory traversal entries cannot write outside staging.
- [x] Symlink entries cannot make requested `bin` resolve outside extracted contents.
- [x] If containment cannot be enforced, installation fails and existing executable is not replaced.
- [x] `.zip`, `.tar.gz`, `.tgz`, `.tar.xz`, and single-file asset behavior remains covered.
- [x] Download → verify checksum → locate bin → install is fail-closed (existing executable not replaced until all steps succeed).

**Verification:**

- [x] `python3 -m pytest tests/test_manager_github_release.py`
- [x] `python3 -m pytest`

**Dependencies:** Task 9

**Files likely touched:**

- `src/tool_installer/managers/github_release.py`
- `tests/test_manager_github_release.py`

**Scope:** Medium

### Task 11: Confirm script manager execution contract

**Status:** Done

**Description:** Add focused tests for script-manager path containment, direct exec, environment variables, no positional args, and no check support.

**Acceptance criteria:**

- [x] Script path is relative to manifest directory and cannot escape it.
- [x] Script is executed directly (execve), not through shell.
- [x] Required `TOOL_INSTALLER_*` environment variables are provided.
- [x] No tool-installer-defined positional args are passed.
- [x] Script manager is not check-capable (`check` returns `not_satisfied`).
- [x] Non-zero script exit is installation failure subject to `allow_fail`.

**Verification:**

- [x] `python3 -m pytest tests/test_manager_script.py tests/test_executor_managers.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/script.py`
- `src/tool_installer/strategy.py`
- `tests/test_manager_script.py`

**Scope:** Medium

### Checkpoint: Safety-Critical Managers

- [x] `github-release` safety invariants have tests.
- [x] `script` manager contract has tests.
- [x] `python3 -m pytest` passes.

---

## Phase 5: Implement Verified Real Manager Checks

### Task 12: Implement apt and Homebrew checks

**Status:** Done

**Description:** Implement metadata-based installed-state checks for apt, brew, and brew-cask according to the verified SPEC table.

**Acceptance criteria:**

- [x] `apt` reads installed version from dpkg package database (`dpkg-query -W -f='${Version}'`).
- [x] `apt latest` compares installed version to local APT candidate metadata (`apt-cache policy`).
- [x] `apt` exact selector compares installed version to requested exact version using v1 equality.
- [x] If package is not installed, dpkg database unavailable, or candidate-version metadata unavailable for `latest`, result is `not_satisfied` or `check_error`.
- [x] `brew` and `brew-cask` check only `latest` (non-latest is a fatal strategy error before execution).
- [x] Homebrew checks determine current/outdated status from Homebrew metadata (`brew outdated`, `brew info`, or equivalent).
- [x] Missing/ambiguous metadata produces `not_satisfied` or `check_error`, not binary-existence success.

**Verification:**

- [x] `python3 -m pytest tests/test_manager_apt_brew.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_manager_apt_brew.py`

**Scope:** Medium

### Task 13: Implement npm, pnpm, and uv-tool checks

**Status:** Done

**Description:** Implement global package metadata checks for npm/pnpm and limited uv-tool checks.

**Acceptance criteria:**

- [x] `npm-global` reads installed package version from global package metadata (`npm list -g --json`).
- [x] `npm-global latest` resolves latest/default registry version and compares with installed version.
- [x] `pnpm-global` reads installed package version from global package metadata (`pnpm list -g --json`).
- [x] `pnpm-global latest` resolves latest/default registry version and compares with installed version.
- [x] Optional `registry` is applied to metadata queries where relevant.
- [x] `uv-tool` exact non-`latest` reads recorded tool specifier metadata when available.
- [x] `uv-tool latest` is non-check-capable in v1 (always installs when reached).
- [x] If global package metadata or registry metadata is unavailable, result is `not_satisfied` or `check_error`.

**Verification:**

- [x] `python3 -m pytest tests/test_manager_runtime_tools.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_manager_runtime_tools.py`

**Scope:** Medium

### Task 14: Implement cargo, rustup, and mise checks

**Status:** Done

**Description:** Implement metadata/state checks for cargo-install, rustup, and mise; keep cargo-binstall non-check-capable.

**Acceptance criteria:**

- [x] `cargo-install` uses cargo tracking metadata/list output and fails check on absent/ambiguous/disabled tracking.
- [x] `cargo-install latest` compares to current registry version.
- [x] `cargo-install` git checks compare tracked source/revision when available.
- [x] `cargo-binstall` is non-check-capable in v1 (always installs when reached).
- [x] `rustup` checks toolchain, components, targets, and moving-channel update status via `rustup show`/`rustup toolchain list`.
- [x] `rustup` check verifies required components and targets are installed for the toolchain.
- [x] For moving channels (`stable`, `nightly`), check determines whether rustup reports the channel as current; if update status cannot be determined, result is `check_error`.
- [x] `mise` checks installed versions and current/latest status through mise installed-tool metadata.
- [x] If mise cannot determine current/latest status for a moving alias or prefix, result is `check_error`.

**Verification:**

- [x] `python3 -m pytest tests/test_manager_rust_mise.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_manager_rust_mise.py`

**Scope:** Medium

### Task 15: Implement `github-release` version probes

**Status:** Done

**Description:** Make `github-release` check-capable only when `version_probe` is defined, and execute the probe for installed-state checks.

**Acceptance criteria:**

- [x] Without `version_probe`, github-release `check` returns `not_satisfied` (non-check-capable, always installs).
- [x] With `version_probe`, check resolves the installed executable path from `$HOME/.local/bin/<install_name>`.
- [x] Probe command replaces `{bin}` with the manager-resolved installed executable path.
- [x] Probe is executed directly (argv), not through shell.
- [x] Probe parses stdout only and captures named group `version`.
- [x] Probe non-zero exit, timeout, or unparseable stdout is `check_error`.
- [x] Non-`latest` compares probe version to requested selector using v1 equality (strip one leading `v`/`V`).
- [x] `latest` resolves latest concrete release tag during apply-mode check and compares using v1 equality.

**Verification:**

- [x] `python3 -m pytest tests/test_manager_github_release.py`

**Dependencies:** Task 9, Task 10

**Files likely touched:**

- `src/tool_installer/managers/github_release.py`
- `tests/test_manager_github_release.py`

**Scope:** Medium

### Checkpoint: Manager Check Semantics

- [x] Every manager's check-capability behavior matches SPEC table.
- [x] No manager uses binary existence as a successful installed-state check.
- [x] Non-check-capable managers install every time when reached.
- [x] `python3 -m pytest` passes.

---

## Phase 6: Expand Conformance Tests and Examples

### Task 16: Add SPEC-derived conformance tests

**Status:** Done

**Description:** Add tests that cover cross-cutting SPEC behavior rather than individual implementation units.

**Acceptance criteria:**

- [x] Dry-run performs validation but no external queries/checks/downloads/scripts.
- [x] Unreachable modules do not trigger schema, duplicate, or strategy errors.
- [x] Fatal configuration/strategy errors occur before installation.
- [x] `force = true` bypasses checks and attempts installation.
- [x] `check_error` does not fall back to installation.
- [x] `allow_fail` only downgrades installation/check failures, not config/strategy/dependency errors.
- [x] stdout/stderr boundaries are covered for tool-installer-owned output.
- [x] v1 version equality (strip one leading `v`/`V`, exact string match) is tested.

**Verification:**

- [x] `python3 -m pytest tests/test_spec_conformance.py`
- [x] `python3 -m pytest`

**Dependencies:** Tasks 7-15 as relevant

**Files likely touched:**

- `tests/test_spec_conformance.py`
- Existing tests as needed

**Scope:** Medium

### Task 17: Update examples and README

**Status:** Done

**Description:** Keep examples and user-facing documentation aligned with the current SPEC and implemented behavior.

**Acceptance criteria:**

- [x] Example `tools.toml` includes dependency traversal and optional failures.
- [x] Example manifest demonstrates `mise`, `rustup`, `script`, `github-release`, and at least one check-capable package manager.
- [x] Example `github-release` includes a realistic `version_probe` when intended to skip installed versions.
- [x] README explains fixed `tools.toml`, manifest reference, dry-run, apply mode, strict serial execution, and manager check caveats.
- [x] Example dry-run succeeds.

**Verification:**

- [x] `python3 -m pytest tests/test_cli_integration.py tests/test_examples.py`
- [x] Manual dry-run against `examples/` if needed.

**Dependencies:** Tasks 9, 15, 16

**Files likely touched:**

- `README.md`
- `examples/tools.toml`
- `examples/manifest.toml`
- `examples/scripts/install-example`
- `tests/test_examples.py`

**Scope:** Medium

---

## Phase 7: Python 3.8 Packaging and Runtime Verification

### Task 18: Verify Python 3.8 compatibility

**Status:** Done

**Description:** Validate that the implementation actually runs on Python 3.8, including vendored TOML fallback and type syntax.

**Acceptance criteria:**

- [x] Code does not use syntax unsupported by Python 3.8 (e.g., `list[str]` vs `List[str]`, `|` union syntax, `match` statements).
- [x] Vendored `tomli` fallback imports and parses TOML under Python 3.8.
- [x] Python 3.8 runtime verified in devbox container via `uv run --python 3.8`; full test suite passes.
- [x] Any Python 3.8-incompatible type syntax is replaced.

**Verification:**

- [x] `uv run --python 3.8 --with pytest python -m pytest -q` => `147 passed in 2.81s` (devbox container, Python 3.8.20).
- [x] Syntax and static compatibility checks also pass on Python 3.12.

**Dependencies:** Current codebase

**Files likely touched:**

- Python source files using 3.9+/3.10+ syntax, if any
- `pyproject.toml`
- tests as needed

**Scope:** Medium

### Task 19: Final release-readiness review

**Status:** Done

**Description:** Perform a final implementation-vs-SPEC review and clean up documentation before v1.

**Acceptance criteria:**

- [x] Every normative SPEC section has implementation coverage or an explicit deferred decision.
- [x] All tests pass.
- [x] README and examples match current behavior.
- [x] No known unsafe github-release extraction behavior remains.
- [x] No manager uses binary existence as successful version satisfaction.
- [x] No external runtime dependencies are introduced.

**Verification:**

- [x] `python3 -m pytest`
- [x] Review `git diff HEAD`
- [x] Optional code/security/test review agents after changes are committed or run without worktree isolation.

**Dependencies:** Tasks 1-18

**Files likely touched:**

- `PLAN.md`
- `README.md`
- tests/docs as needed

**Scope:** Medium

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---:|---|
| Manager check semantics are hard to implement consistently | High | Use explicit `CheckResult`; unit-test command parsing and metadata failure cases per manager |
| Package-manager docs differ from installed versions | Medium | Treat unknown/ambiguous outputs as `check_error`; avoid binary-existence success |
| `github-release` archive extraction is security-sensitive | High | Implement containment tests before changing extraction code |
| `github-release latest` requires external network during apply check | Medium | Keep dry-run network-free; surface network failures as `check_error` |
| Cargo tracking can be disabled or incomplete | Medium | Treat absent/ambiguous tracking as `check_error`; keep cargo-binstall non-check-capable until verified |
| `uv-tool latest` semantics are underdocumented | Medium | Keep `latest` non-check-capable in v1 |
| Python 3.8 support may be broken by modern type syntax | ~~Medium~~ Resolved | Verified: `147 passed` on Python 3.8.20 via `uv run --python 3.8` in devbox container |
| Script manager executes trusted arbitrary code | Medium | Preserve path containment, direct exec, no shell expansion, and trust-model docs |

## Open Questions

None blocking for the next implementation slice.

Future non-v1 refinements may include:

- Machine-readable dry-run output.
- Configurable GitHub release install directory.
- `apt-repo` or `brew-tap` manager.
- `pipx` / `go-install` manager.
- Optional check script for `script` manager.
- Broader `uv-tool latest` semantics if official metadata behavior is documented.
- Independent `cargo-binstall` installed-state semantics if verified.

## Update Protocol

When completing a task:

1. Update that task's **Status** and checkboxes.
2. Update **Current Progress** if a phase/checkpoint changes.
3. Record the verification command and result.
4. Keep `SPEC.md` as behavior source of truth; update `PLAN.md` only for implementation progress and Python-specific planning.
---

## Phase 8: Single-file Executable Distribution

### Task 20: Build and verify compact single-file artifact

**Status:** Done

**Description:** Implement the `SPEC.md` distribution contract for a Python-based single-file executable that works on hosts with Python but without non-standard runtime packages.

**Acceptance criteria:**

- [x] A repository command builds one regular executable file at `dist/tool-installer`.
- [x] A repository install script safely installs a downloaded artifact without replacing an existing destination until validation succeeds.
- [x] The artifact uses an existing host Python interpreter and does not embed CPython.
- [x] The artifact includes all runtime Python code, including the vendored TOML parser fallback.
- [x] The artifact does not require installing runtime packages from PyPI on the target host.
- [x] The artifact exposes the same CLI behavior as the packaged `tool-installer` command.
- [x] The artifact is verified to be at most 409,600 bytes.
- [x] Verification covers executable permission, `--help`, and `examples/` dry-run behavior.
- [x] Verification covers safe install success and invalid-download failure preserving an existing destination.
- [x] Distribution documentation is present in `README.md`.

**Verification:**

- [x] `scripts/build-single`
- [x] `python3 -m pytest tests/test_distribution.py`
- [x] `python3 -m pytest`

**Files touched:**

- `scripts/build-single`
- `scripts/install-single`
- `tests/test_distribution.py`
- `.gitignore`
- `README.md`
- `SPEC.md`
- `PLAN.md`

**Scope:** Medium

---

## Phase 9: Network Configuration and GitHub Mirror Fallback

### Task 21: Manifest `[_network]` section and mirror-aware downloads

**Status:** Done

**Description:** Add a reserved `[_network]` manifest section for global network configuration, and implement mirror fallback with retry/timeout for `github-release` downloads.

**Acceptance criteria:**

- [x] `[_network]` is a reserved manifest section (underscore prefix) that is not treated as a tool name.
- [x] `[_network].github_mirrors` is an ordered list of mirror base URLs.
- [x] `[_network].timeout` sets HTTP request timeout in seconds (default 30).
- [x] `[_network].retry` sets retry count per request (default 3).
- [x] `github-release` downloads try mirrors in order, then fall back to direct GitHub URL.
- [x] Each URL attempt retries with exponential backoff before moving to the next mirror.
- [x] `_latest_tag()` API calls respect timeout and retry settings.
- [x] Other managers are not affected by `[_network]`.
- [x] Unknown `[_network]` fields are fatal manifest errors.
- [x] Missing `[_network]` uses defaults (no mirrors, 30s timeout, 3 retries).
- [x] `NetworkConfig` flows from manifest → parser → cli → registry → GithubReleaseManager.

**Verification:**

- [x] `python3 -m pytest tests/test_network_config.py` => `16 passed`.
- [x] `python3 -m pytest -q` => `163 passed`.
- [x] `examples/dotfiles/` dry-run succeeds.

**Files touched:**

- `src/tool_installer/models.py`
- `src/tool_installer/parser.py`
- `src/tool_installer/cli.py`
- `src/tool_installer/managers/__init__.py`
- `src/tool_installer/managers/github_release.py`
- `SPEC.md`
- `README.md`
- `PLAN.md`
- `tests/test_network_config.py`
- `examples/dotfiles/tools.toml`
- `examples/dotfiles/manifest.toml`

**Scope:** Medium

---

## Phase 10: Manager Configuration Layer and GitHub Token Auto-Detection

### Task 22: `[_github-release]` config section, token detection, and `[_network]` deprecation

**Status:** Done

**Description:** Replace `[_network]` with `[_github-release]` manager config section. Implement GitHub token auto-detection from `GITHUB_TOKEN` env and `gh auth token`. Add runtime token source reporting.

**Acceptance criteria:**

- [x] `[_github-release]` section replaces `[_network]` in manifest parsing
- [x] `[_network]` section raises `ManifestError` with migration hint
- [x] `GithubReleaseConfig` replaces `NetworkConfig` model
- [x] Token auto-detection: `GITHUB_TOKEN` env → `gh auth token` → anonymous
- [x] Token only sent to `github.com` / `api.github.com`, never to mirrors
- [x] Runtime token source reporting in apply mode stdout
- [x] Dry-run does not detect or report token
- [x] Token detection failures degrade to anonymous (no install interruption)
- [x] `github_token.py` module with `detect_github_token()` function

**Verification:**

- [x] `python3 -m pytest -q` => `171 passed`
- [x] `examples/dotfiles/` dry-run succeeds
- [x] `examples/` dry-run succeeds

**Files touched:**

- `src/tool_installer/models.py`
- `src/tool_installer/parser.py`
- `src/tool_installer/cli.py`
- `src/tool_installer/managers/__init__.py`
- `src/tool_installer/managers/github_release.py`
- `src/tool_installer/github_token.py` (new)
- `src/tool_installer/executor.py`
- `SPEC.md`
- `README.md`
- `PLAN.md`
- `tests/test_network_config.py`
- `examples/dotfiles/manifest.toml`

**Scope:** Medium

---

## Phase 11: cargo-install binstall_first Optimization

### Task 23: cargo-install binstall_first field and self-bootstrapping

**Status:** Pending

**Description:** Add `binstall_first` optional field to `cargo-install` manager. When enabled, the manager self-bootstraps cargo-binstall from GitHub Releases, attempts precompiled binary installation, and falls back to `cargo install` on failure.

**Acceptance criteria:**

- [x] `binstall_first` is an optional bool field on `cargo-install` strategies (default `false`)
- [x] When `true`, install flow is: check PATH → auto-download binstall if missing → `cargo binstall --disable-strategies compile` → fallback `cargo install`
- [x] Auto-download binstall to `~/.cargo/bin/`, skip if already present and executable
- [x] binstall download failure silently falls back to `cargo install`
- [x] binstall install failure falls back to `cargo install`
- [x] `--disable-strategies compile` always used in binstall phase
- [x] `--locked` flag respected in fallback phase when `locked = true`
- [x] check semantics unchanged (cargo metadata-based)
- [x] Unit tests for binstall_first flow (mocked subprocesses)
- [x] SPEC.md updated with binstall_first documentation
- [x] docs/draft-cargo-binstall-first.md merged into SPEC.md

**Verification:**

- [ ] `python3 -m pytest tests/test_binstall_first.py`
- [ ] `python3 -m pytest -q` => 171+ passed
- [ ] dotfiles cargo-tools module uses `binstall_first = true`

**Files touched:**

- `src/tool_installer/strategy.py` (binstall_first field)
- `src/tool_installer/managers/commands.py` (CargoInstallManager install method)
- `src/tool_installer/managers/binstall_bootstrap.py` (new — binstall auto-download)
- `tests/test_binstall_first.py` (new)
- `SPEC.md`
- `docs/draft-cargo-binstall-first.md`

**Scope:** Medium
