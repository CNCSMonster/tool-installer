# Tool-Installer Context

Tool-Installer describes a declarative installation domain: modules select tools, manifests select platform-specific strategies, and execution processes an installation plan.

## Language

**Requested Version Selector**:
The version policy written in a tool reference after `@`, or `latest` when omitted. It is a request that must be reconciled against the selected manager's ability to discover and install concrete versions.
_Avoid_: raw version string, package version

**Latest Concrete Version**:
The concrete version currently resolved by a manager or upstream source for a requested version selector of `latest`. `latest` is not itself considered an installed version, and it is resolved during apply-mode manager checks rather than dry-run planning.
_Avoid_: latest as installed, newest enough

**Version Equality**:
The comparison rule for requested selectors, latest concrete versions, and probe-parsed installed versions. In v1, equality is exact string equality after removing at most one leading ASCII `v` or `V` from both sides.
_Avoid_: semver range matching, version ordering, loose coercion

**Installed-State Check**:
A manager-specific apply-mode determination that the already-installed tool satisfies the requested version selector. For `latest`, this means checking whether the current latest concrete version is already installed, not merely whether any binary exists.
_Avoid_: command exists check, presence check

**Binary Version Probe**:
A manifest-defined command and parser used to ask an installed binary for its version during apply-mode installed-state checks. In v1, its command may use only the `{bin}` placeholder to reference the manager-resolved installed binary path.
_Avoid_: default --version guess, implicit version command, PATH-only version check

**Check Error**:
An apply-mode failure to determine installed state, such as network unavailability, registry timeout, permission failure, corrupt manager metadata, failed version probe execution, or unparseable version probe output. A check error is distinct from a successful check result of not satisfied.
_Avoid_: missing tool, version mismatch

**Plan-Level Rerun Convergence**:
The recovery model where a failed installation is retried by rerunning the same command, causing tool-installer to re-resolve and re-traverse the plan while skipping check-capable tools that already satisfy their requested version selectors. It is not persistent checkpoint/resume.
_Avoid_: checkpoint resume, partial transaction recovery

**Manager Capability Table**:
The documented record of each manager's ability to perform installed-state checks and the known cases where those checks may fail. It is maintained from research and observed usage rather than assumed uniform behavior.
_Avoid_: universal manager contract, implicit manager behavior

**Check-Capable Manager**:
A manager that can reliably determine whether an installed tool satisfies the requested version selector for the cases documented in the manager capability table. Managers that are not check-capable execute their install action on every apply-mode run.
_Avoid_: partially checked manager, best-effort checker

## Example dialogue

Dev: The module requests `ruff`, so the requested version selector is `latest`.
Domain expert: Then the installed-state check must compare the installed `ruff` against the latest concrete version that the selected manager resolves during apply mode.
Dev: Should dry-run show that concrete version?
Domain expert: No. Dry-run keeps the requested selector as `latest` and must not query external sources.
Dev: If an older `ruff` binary exists, can we skip?
Domain expert: No. A binary existing is not enough to satisfy either a pinned selector or `latest`.
Dev: What if GitHub tag is `v10.2.0` but `fd --version` prints `10.2.0`?
Domain expert: v1 version equality treats those as equal by stripping one leading `v` or `V`, but does not perform semver parsing or range matching.
Dev: What if a tool like `fd` exposes `fd --version`?
Domain expert: Use a binary version probe with `{bin}` in the manifest; tool-installer must not guess a universal version command or trust PATH to point at the intended binary.
Dev: What if checking latest times out?
Domain expert: That is a check error, not a version mismatch. The tool fails unless `allow_fail` downgrades it or `force` skips the check.
Dev: If the network fails halfway through a plan, do we resume from a checkpoint?
Domain expert: No. Rerunning uses plan-level rerun convergence: satisfied check-capable tools skip, unchecked or unsatisfied tools run again, and per-tool partial recovery belongs to the manager.
Dev: What about managers with unreliable checks?
Domain expert: Their behavior belongs in the manager capability table. If a manager is not check-capable for a case, apply mode executes its install action rather than pretending a binary presence check is enough.
