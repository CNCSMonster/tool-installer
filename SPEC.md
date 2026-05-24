# Tool-Installer Specification v1.0 (Final)

## 1. Overview

**Tool-Installer** is a declarative, cross-platform, and modular development environment setup engine.

### Core Philosophy
*   **Dual-Config Decoupling**: Separates **"What to install"** (`tools.toml`) from **"How to install"** (`manifest.toml`).
*   **Modular Orchestration**: Uses explicit dependencies to compose modules and enforce installation order.
*   **Robust Execution**: Strictly serial execution to avoid resource contention and lock conflicts. No implicit overrides allowed.

---

## 2. Configuration Files

### 2.1 `tools.toml` (The Target List)
Defines **what** the user wants to install. Each section is a **Module**.

#### Key Concepts
*   **Module as Section**: Top-level TOML tables (e.g., `[base]`) represent installable modules.
*   **Dependency Order**: `depends = ["module-a", "module-b"]` ensures `module-a` completes before `module-b`. This field is **optional**; if omitted, the module has no dependencies and is treated as a root module.
*   **Version Anchoring**: Version is part of the tool key: `"tool@version" = "description"`. The parser splits the key by the **last** `@` character — the part before is the tool name, the part after is the version. If no `@` is present, version is `latest` and left to the manager's default behavior.
*   **Strict Uniqueness**: A tool name can only be defined **once** in the entire resolved dependency tree. Defining it in multiple modules is a **Fatal Error**.
*   **Per-Tool Failure Policy**: Tools may opt in to soft-failure via `allow_fail = true`. When a tool fails installation:
    - `allow_fail = false` (default) → **Fatal Error**, halt immediately.
    - `allow_fail = true` → **Warning**, continue to next tool.

#### Structure
```toml
# tools.toml

[base]
# Base has no dependencies. 
# "git" is installed with the latest version by default.
"git" = "Version control"

# Explicit versioning using @ syntax (requires quotes)
"curl@8.4" = "Network tool"

[rust-env]
# Order: must complete [base] first
depends = ["base"] 

"rustup" = "Rust toolchain"
"cargo-watch@7.0" = "Code monitor"
# ✅ Inherits "git" from base automatically.
# ❌ Cannot re-define "git" here (Strict Uniqueness).

[full-dev]
# Order: process [rust-env] (and its deps), then [web-env] (and its deps)
depends = ["rust-env", "web-env"] 

"node@20" = "Node.js environment"
# Per-tool failure policy: warn but continue if this tool fails
"docker" = { desc = "Container engine", allow_fail = true }
```

### 2.2 `manifest.toml` (The Strategy)
Defines **how** to install a specific tool based on the environment.

#### Key Concepts
*   **Version Agnostic**: This file **never** defines the version. Version comes from `tools.toml`. It only defines fallbacks or static URLs if necessary.
*   **Explicit Environment Targeting**: No implicit defaults. Strategies must be defined under specific OS/Arch keys.
*   **Hierarchical Inheritance**: `Tool -> OS -> Arch`.

#### Structure
```toml
# manifest.toml

[git]
# Top-level can hold generic info, but NO manager logic.
repo = "git/git"

# ✅ Explicit Linux Strategy
[git.linux]
manager = "apt"
pkg = "git"

# ✅ Explicit macOS Strategy
[git.macos]
manager = "brew"
pkg = "git"

# ==========================================
# Complex Example: Architecture Specific
# ==========================================
[helix]
repo = "helix-editor/helix"

[helix.linux]
manager = "github-release"

# ✅ Specific override for x86_64 architecture
[helix.linux.x86_64]
suffix = "-x86_64-unknown-linux-musl"
sha256 = "abc..."

# ✅ Specific override for aarch64 architecture
[helix.linux.aarch64]
suffix = "-aarch64-unknown-linux-musl"
sha256 = "def..."
```

---

## 3. Field Dictionary

### `tools.toml`

| Field | Location | Type | Description |
| :--- | :--- | :--- | :--- |
| **depends** | `[Module]` | List | Ordered list of modules to install **before** this one. **Optional**; if omitted, module is a root. |
| **Key** | `Key = "Value"` | String | Tool name. If version is needed, use `"name@version"`. |
| **Value** | `Key = Value` | String or Table | Description (human-readable only). Can also be an inline table: `{ desc = "...", allow_fail = true }`. |
| **allow_fail** | Inline value | Bool | Default `false`. If `true`, installation failure prints a warning and continues instead of halting. |

### `manifest.toml`

| Field | Location | Type | Description |
| :--- | :--- | :--- | :--- |
| **manager** | Strategy | String | The driver to use (e.g., `apt`, `brew`, `cargo-binstall`, `github-release`). |
| **pkg** | Strategy | String | The package name for the manager (e.g., `git`, `bat`). |
| **force** | Strategy | Bool | Default `false`. If `true`, skip environment check and reinstall/upgrade. |
| **repo** | Strategy | String | For `github-release`, the owner/repo path. |
| **platforms**| Strategy | List | `["linux", "macos"]`. If current OS not in list, skip installation. |

---

## 4. Execution Engine Logic

### Phase 1: Dependency Graph Construction
1.  **Parse** `tools.toml` to build the DAG.
2.  **Module Deduplication (Diamond Dependency)**: If multiple branches depend on the same module, it is installed only **once** on its first encounter. Example: `D → [A, B]`, and both `A` and `B` depend on `C`. The order is `C → A → B → D`, not `C → A → C → B → D`.
3.  **Circular Dependency Detection**: If a cycle is detected (e.g., `A → B → A`), the installer halts immediately with a **FATAL ERROR**.
4.  **Topological Sort**: Order modules based on `depends` array order, respecting the depth-first resolution. Example: If `D` depends on `["A", "B"]`, and `A` depends on `C`, the order is `C → A → B → D`.
5.  **Strict Conflict Check**:
    *   Merge all tools from the resolved tree.
    *   If any tool appears more than once → **FATAL ERROR**.

### Phase 2: Serial Installation
The engine iterates through the sorted modules and tools sequentially.

1.  **Environment Detection**: Determine `OS` (linux/darwin) and `Arch` (x86_64/aarch64).
2.  **Strategy Resolution**:
    *   Look up `tool` in `manifest.toml`.
    *   If the tool is **not found at all** in `manifest.toml` → **FATAL ERROR**.
    *   Merge configs: `[tool]` + `[tool.OS]` + `[tool.OS.Arch]`.
    *   If a tool is found but has no strategy for the current OS → **Skip with Warning** (implicit environment filtering).
3.  **Dry-Run Mode**: When `--dry-run` is passed, perform all validation (DAG construction, conflict check, strategy resolution) but skip all actual installation commands. Print the full installation plan instead.
4.  **Check or Force**:
    *   **If `force = true`**: Execute `manager.install()`.
    *   **If `force = false`** (Default):
        1.  Attempt `manager.check(tool, version)`.
        2.  **Check Success**:
            *   Installed & Version OK → **Skip**.
            *   Missing/Version Mismatch → **Install**.
        3.  **Check Not Implemented**:
            *   Print **Warning**: "Manager does not support check, installing blindly."
            *   Execute `manager.install()`.
5.  **Installation Failure Handling**:
    *   If a tool installation returns a non-zero exit code:
        - `allow_fail = false` (default) → **FATAL ERROR**. Halt immediately, reporting the failed module and tool.
        - `allow_fail = true` → **Warning**. Print the error, then continue to the next tool.

---

## 5. Design Constraints (The "Why")

*   **No Concurrency**: Installation is strictly serial. This prevents locking issues (e.g., two apt processes) and OOM during heavy compilations.
*   **No Implicit Overrides**: To prevent "hidden" behaviors where a submodule silently breaks a base module, we enforce **Strict Uniqueness**. Shared tools must be defined in a common ancestor module (e.g., `base`), not in sibling modules.
*   **Explicit Targets**: We assume nothing about the environment. Every tool must explicitly define its installation method for each supported OS.
