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
- [ ] Phase 7: Python 3.8 packaging/runtime verification

Current test status:

```text
python3 -m pytest
48 passed
```

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

Already present:

- Python package scaffold and CLI entry point.
- TOML loading with Python 3.11+ `tomllib` and vendored `tomli` fallback path.
- Basic `tools.toml` parsing with selected-scope validation.
- Manifest loading and OS/Arch strategy merge.
- Dependency traversal, cycle detection, diamond deduplication, duplicate tool detection within selected scope.
- Dry-run CLI path and example dry-run test.
- Basic manager registry and command construction for all supported managers.
- Initial `script` and `github-release` managers.
- Test suite currently passes on Python 3.12.

Known divergences from current `SPEC.md`:

- **Check model is boolean, not 3-outcome**: Executor uses `is_installed() -> bool` instead of SPEC's `satisfied`/`not_satisfied`/`check_error` outcomes.
- **All `CommandManager` checks use binary existence only**: Every package manager (apt, brew, cargo, npm, pnpm, uv, mise, rustup) checks only `command -v`, violating SPEC's requirement for metadata-based checks and the rule that binary existence alone is never sufficient.
- **`cargo-binstall` incorrectly marked check-capable**: SPEC says `cargo-binstall` is NOT check-capable in v1, but it inherits `supports_check = True` from `CommandManager`.
- **`uv-tool latest` should be non-check-capable**: SPEC says `uv-tool` `latest` checks are not check-capable in v1, but current code treats all uv-tool items as check-capable.
- **`github-release` check capability is unconditional**: SPEC says `github-release` is check-capable ONLY when `version_probe` is defined; otherwise not check-capable. Current code always has `supports_check = True` and checks file existence only.
- **`github-release` ignores `version_probe`**: The `version_probe` subtable is not validated in strategy resolution, not stored in merged strategy fields, and never executed.
- **`github-release` archive extraction is unsafe**: Uses `extractall` without path/symlink containment. SPEC requires fail-closed extraction into a staging location with absolute path, traversal, and symlink containment checks.
- **`github-release` install is not atomic**: Current code copies directly to destination. SPEC says "must not replace or remove an existing installed executable until the release asset has been downloaded, verified when `sha256` is present, and the requested `bin` has been located successfully."
- **`github-release` `version_probe` missing from strategy validation**: `_SUPPORTED["github-release"]["optional"]` does not include `version_probe`, so a manifest with `version_probe` would cause an "Unknown strategy fields" error.
- **`rustup` check doesn't verify components/targets**: SPEC says the check "must determine whether the corresponding rustup toolchain is installed, required components are installed for that toolchain, and required targets are installed for that toolchain." Current check only runs `rustup toolchain list`.
- **`allow_fail` warnings missing required fields**: SPEC says warnings "must identify the tool name, selected manager, failure phase (`check` or `install`), and the available failure reason." Current warnings are a single string without structured fields.
- **`bin` default not set in strategy resolution**: SPEC says `bin`, when supported, "defaults to the parsed logical tool name" if omitted. Strategy resolution doesn't apply this default.
- **`rustup` check_command uses shell**: `RustupManager.check_command` returns `["sh", "-c", "rustup toolchain list ... >/dev/null"]`. SPEC prefers direct argv execution where possible.

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

### Checkpoint: Current Baseline

- [x] `python3 -m pytest` passes: `22 passed`.
- [x] Example dry-run succeeds.
- [ ] Current apply-mode installed-state checks do not yet satisfy `SPEC.md`.

---

## Phase 2: Basic Executor and Command Construction

### Task 5: Basic executor and fake manager semantics

**Status:** Done, needs SPEC-alignment refactor in Phase 3

**Acceptance criteria completed:**

- [x] Executes plan in order.
- [x] Honors `force` by skipping current check path.
- [x] Skips installed items in current boolean check model.
- [x] Stops on non-allowed installation failure.
- [x] `allow_fail = true` warns and continues.

**Known follow-up:**

- [ ] Replace boolean installed check with `CheckResult` outcomes.
- [ ] Track failure phase for diagnostics.

**Verification:**

- [x] `python3 -m pytest tests/test_executor_managers.py`

**Dependencies:** Task 4

**Files touched:**

- `src/tool_installer/executor.py`
- `src/tool_installer/managers/base.py`
- `tests/test_executor_managers.py`

**Scope:** Medium

### Task 6: Basic command construction for real managers

**Status:** Done, needs SPEC-alignment refactor in Phase 5

**Acceptance criteria completed:**

- [x] Command construction exists for apt, brew, brew-cask, cargo-binstall, cargo-install, mise, npm-global, pnpm-global, uv-tool, rustup.
- [x] Rustup install command supports components, targets, and `set_default` follow-up.
- [x] Commands are unit-tested without executing package managers.

**Known follow-up:**

- [ ] Remove binary-existence-only checks.
- [ ] Add manager-specific metadata checks.
- [ ] Add check-error behavior and tests.

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

- [ ] Introduce `CheckResult` enum or equivalent with `satisfied`, `not_satisfied`, and `check_error` outcomes.
- [ ] Manager protocol changes from `is_installed() -> bool` to `check(item) -> CheckResult`.
- [ ] Executor treats `satisfied` as skip/success.
- [ ] Executor treats `not_satisfied` as install.
- [ ] Executor treats `check_error` as installation failure for that tool (does NOT fall back to install).
- [ ] `force = true` bypasses checks and attempts installation.
- [ ] Non-check-capable managers have `check` return `not_satisfied` (or skip check entirely) and always install when reached.
- [ ] `github-release` check capability becomes conditional: check-capable only when `version_probe` is defined.
- [ ] `cargo-binstall` becomes non-check-capable.
- [ ] Existing tests are migrated away from boolean `is_installed`.

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

- [ ] Warnings identify tool name, selected manager, failure phase (`check` or `install`), and the available failure reason/status.
- [ ] Exact wording remains human-facing and not machine-stable.
- [ ] Non-allowed failures still stop execution and return non-zero through CLI.

**Verification:**

- [ ] `python3 -m pytest tests/test_executor_managers.py tests/test_cli_integration.py`

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

**Status:** Not started

**Description:** Add strategy validation for the `version_probe` subtable and preserve it in merged strategy fields.

**Acceptance criteria:**

- [ ] `version_probe` is added to `github-release` optional fields in `_SUPPORTED`.
- [ ] `version_probe` is allowed only for `github-release` manager (not for other managers in v1).
- [ ] `version_probe.command` is validated as a non-empty array of non-empty strings.
- [ ] `version_probe.command` strings are validated to use only `{bin}` placeholder.
- [ ] `version_probe.regex` is validated as a compilable regex with a named capture group `version`.
- [ ] Unknown `version_probe` fields are fatal.
- [ ] `bin` default is set to the parsed logical tool name when omitted for managers that support it.
- [ ] Dry-run does not execute probes.

**Verification:**

- [ ] `python3 -m pytest tests/test_parser_resolver_strategy.py`
- [ ] `python3 -m pytest`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/strategy.py`
- `src/tool_installer/models.py` (if version_probe needs structured representation)
- `tests/test_parser_resolver_strategy.py`
- `tests/test_manager_github_release.py`

**Scope:** Medium

### Task 10: Harden `github-release` archive extraction

**Status:** Not started

**Description:** Replace unsafe archive extraction with fail-closed containment checks.

**Acceptance criteria:**

- [ ] Archives are extracted only into a temporary staging directory.
- [ ] Absolute archive entry paths are contained before writing (not written outside staging).
- [ ] Parent-directory traversal entries cannot write outside staging.
- [ ] Symlink entries cannot make requested `bin` resolve outside extracted contents.
- [ ] If containment cannot be enforced, installation fails and existing executable is not replaced.
- [ ] `.zip`, `.tar.gz`, `.tgz`, `.tar.xz`, and single-file asset behavior remains covered.
- [ ] Download → verify checksum → locate bin → install is fail-closed (existing executable not replaced until all steps succeed).

**Verification:**

- [ ] `python3 -m pytest tests/test_manager_github_release.py`
- [ ] `python3 -m pytest`

**Dependencies:** Task 9

**Files likely touched:**

- `src/tool_installer/managers/github_release.py`
- `tests/test_manager_github_release.py`

**Scope:** Medium

### Task 11: Confirm script manager execution contract

**Status:** Not started

**Description:** Add focused tests for script-manager path containment, direct exec, environment variables, no positional args, and no check support.

**Acceptance criteria:**

- [ ] Script path is relative to manifest directory and cannot escape it.
- [ ] Script is executed directly (execve), not through shell.
- [ ] Required `TOOL_INSTALLER_*` environment variables are provided.
- [ ] No tool-installer-defined positional args are passed.
- [ ] Script manager is not check-capable (`check` returns `not_satisfied`).
- [ ] Non-zero script exit is installation failure subject to `allow_fail`.

**Verification:**

- [ ] `python3 -m pytest tests/test_manager_script.py tests/test_executor_managers.py`

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

**Status:** Not started

**Description:** Implement metadata-based installed-state checks for apt, brew, and brew-cask according to the verified SPEC table.

**Acceptance criteria:**

- [ ] `apt` reads installed version from dpkg package database (`dpkg-query -W -f='${Version}'`).
- [ ] `apt latest` compares installed version to local APT candidate metadata (`apt-cache policy`).
- [ ] `apt` exact selector compares installed version to requested exact version using v1 equality.
- [ ] If package is not installed, dpkg database unavailable, or candidate-version metadata unavailable for `latest`, result is `not_satisfied` or `check_error`.
- [ ] `brew` and `brew-cask` check only `latest` (non-latest is a fatal strategy error before execution).
- [ ] Homebrew checks determine current/outdated status from Homebrew metadata (`brew outdated`, `brew info`, or equivalent).
- [ ] Missing/ambiguous metadata produces `not_satisfied` or `check_error`, not binary-existence success.

**Verification:**

- [ ] `python3 -m pytest tests/test_manager_apt_brew.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_manager_apt_brew.py`

**Scope:** Medium

### Task 13: Implement npm, pnpm, and uv-tool checks

**Status:** Not started

**Description:** Implement global package metadata checks for npm/pnpm and limited uv-tool checks.

**Acceptance criteria:**

- [ ] `npm-global` reads installed package version from global package metadata (`npm list -g --json`).
- [ ] `npm-global latest` resolves latest/default registry version and compares with installed version.
- [ ] `pnpm-global` reads installed package version from global package metadata (`pnpm list -g --json`).
- [ ] `pnpm-global latest` resolves latest/default registry version and compares with installed version.
- [ ] Optional `registry` is applied to metadata queries where relevant.
- [ ] `uv-tool` exact non-`latest` reads recorded tool specifier metadata when available.
- [ ] `uv-tool latest` is non-check-capable in v1 (always installs when reached).
- [ ] If global package metadata or registry metadata is unavailable, result is `not_satisfied` or `check_error`.

**Verification:**

- [ ] `python3 -m pytest tests/test_manager_runtime_tools.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_manager_runtime_tools.py`

**Scope:** Medium

### Task 14: Implement cargo, rustup, and mise checks

**Status:** Not started

**Description:** Implement metadata/state checks for cargo-install, rustup, and mise; keep cargo-binstall non-check-capable.

**Acceptance criteria:**

- [ ] `cargo-install` uses cargo tracking metadata/list output and fails check on absent/ambiguous/disabled tracking.
- [ ] `cargo-install latest` compares to current registry version.
- [ ] `cargo-install` git checks compare tracked source/revision when available.
- [ ] `cargo-binstall` is non-check-capable in v1 (always installs when reached).
- [ ] `rustup` checks toolchain, components, targets, and moving-channel update status via `rustup show`/`rustup toolchain list`.
- [ ] `rustup` check verifies required components and targets are installed for the toolchain.
- [ ] For moving channels (`stable`, `nightly`), check determines whether rustup reports the channel as current; if update status cannot be determined, result is `check_error`.
- [ ] `mise` checks installed versions and current/latest status through mise installed-tool metadata.
- [ ] If mise cannot determine current/latest status for a moving alias or prefix, result is `check_error`.

**Verification:**

- [ ] `python3 -m pytest tests/test_manager_rust_mise.py`

**Dependencies:** Task 7

**Files likely touched:**

- `src/tool_installer/managers/commands.py`
- `tests/test_manager_rust_mise.py`

**Scope:** Medium

### Task 15: Implement `github-release` version probes

**Status:** Not started

**Description:** Make `github-release` check-capable only when `version_probe` is defined, and execute the probe for installed-state checks.

**Acceptance criteria:**

- [ ] Without `version_probe`, github-release `check` returns `not_satisfied` (non-check-capable, always installs).
- [ ] With `version_probe`, check resolves the installed executable path from `$HOME/.local/bin/<install_name>`.
- [ ] Probe command replaces `{bin}` with the manager-resolved installed executable path.
- [ ] Probe is executed directly (argv), not through shell.
- [ ] Probe parses stdout only and captures named group `version`.
- [ ] Probe non-zero exit, timeout, or unparseable stdout is `check_error`.
- [ ] Non-`latest` compares probe version to requested selector using v1 equality (strip one leading `v`/`V`).
- [ ] `latest` resolves latest concrete release tag during apply-mode check and compares using v1 equality.

**Verification:**

- [ ] `python3 -m pytest tests/test_manager_github_release.py`

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

**Status:** Not started

**Description:** Add tests that cover cross-cutting SPEC behavior rather than individual implementation units.

**Acceptance criteria:**

- [ ] Dry-run performs validation but no external queries/checks/downloads/scripts.
- [ ] Unreachable modules do not trigger schema, duplicate, or strategy errors.
- [ ] Fatal configuration/strategy errors occur before installation.
- [ ] `force = true` bypasses checks and attempts installation.
- [ ] `check_error` does not fall back to installation.
- [ ] `allow_fail` only downgrades installation/check failures, not config/strategy/dependency errors.
- [ ] stdout/stderr boundaries are covered for tool-installer-owned output.
- [ ] v1 version equality (strip one leading `v`/`V`, exact string match) is tested.

**Verification:**

- [ ] `python3 -m pytest tests/test_spec_conformance.py`
- [ ] `python3 -m pytest`

**Dependencies:** Tasks 7-15 as relevant

**Files likely touched:**

- `tests/test_spec_conformance.py`
- Existing tests as needed

**Scope:** Medium

### Task 17: Update examples and README

**Status:** Not started

**Description:** Keep examples and user-facing documentation aligned with the current SPEC and implemented behavior.

**Acceptance criteria:**

- [ ] Example `tools.toml` includes dependency traversal and optional failures.
- [ ] Example manifest demonstrates `mise`, `rustup`, `script`, `github-release`, and at least one check-capable package manager.
- [ ] Example `github-release` includes a realistic `version_probe` when intended to skip installed versions.
- [ ] README explains fixed `tools.toml`, manifest reference, dry-run, apply mode, strict serial execution, and manager check caveats.
- [ ] Example dry-run succeeds.

**Verification:**

- [ ] `python3 -m pytest tests/test_cli_integration.py tests/test_examples.py`
- [ ] Manual dry-run against `examples/` if needed.

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

**Status:** Not started

**Description:** Validate that the implementation actually runs on Python 3.8, including vendored TOML fallback and type syntax.

**Acceptance criteria:**

- [ ] Code does not use syntax unsupported by Python 3.8 (e.g., `list[str]` vs `List[str]`, `|` union syntax, `match` statements).
- [ ] Vendored `tomli` fallback imports and parses TOML under Python 3.8.
- [ ] Test suite or compatibility smoke test runs under Python 3.8.
- [ ] Any Python 3.8-incompatible type syntax is replaced.

**Verification:**

- [ ] `python3.8 -m pytest` if Python 3.8 is available.
- [ ] Otherwise document that local Python 3.8 runtime is unavailable and run syntax/static compatibility checks feasible in this environment.

**Dependencies:** Current codebase

**Files likely touched:**

- Python source files using 3.9+/3.10+ syntax, if any
- `pyproject.toml`
- tests as needed

**Scope:** Medium

### Task 19: Final release-readiness review

**Status:** Not started

**Description:** Perform a final implementation-vs-SPEC review and clean up documentation before v1.

**Acceptance criteria:**

- [ ] Every normative SPEC section has implementation coverage or an explicit deferred decision.
- [ ] All tests pass.
- [ ] README and examples match current behavior.
- [ ] No known unsafe github-release extraction behavior remains.
- [ ] No manager uses binary existence as successful version satisfaction.
- [ ] No external runtime dependencies are introduced.

**Verification:**

- [ ] `python3 -m pytest`
- [ ] Review `git diff HEAD`
- [ ] Optional code/security/test review agents after changes are committed or run without worktree isolation.

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
| Python 3.8 support may be broken by modern type syntax | Medium | Run Python 3.8 or static compatibility checks before v1 |
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
