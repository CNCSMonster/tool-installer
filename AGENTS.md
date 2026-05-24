# Agent Instructions for tool-installer

## Project Overview

**tool-installer** is a declarative, cross-platform, modular development environment setup engine. It reads two TOML configuration files (`tools.toml` for what to install, `manifest.toml` for how to install) and orchestrates serial tool installation across different OS/Arch environments.

## Language & Stack

- **Language**: Python 3.8+
- **TOML parsing**: Standard library `tomllib` (Python 3.11+) with bundled `tomli` fallback (vendor pattern)
- **No external runtime dependencies**: all third-party libraries must be vendored

## Canonical Specification

**All implementation decisions MUST reference [SPEC.md](SPEC.md).** Do not add behavior, fields, or modes that are not defined there. If you discover an ambiguity, discuss it with the user before implementing.

## Key Design Decisions

1. **Strict serial execution** — no concurrency, no threading, no async. Tools install one by one.
2. **Strict uniqueness** — a tool name must appear in only one module across the entire resolved dependency tree. Duplicates → fatal error.
3. **Ordered dependencies** — `depends = ["A", "B"]` means A (and its subtree) completes before B starts.
4. **Implicit environment filtering** — if `manifest.toml` has no entry for a tool on the current OS, print a warning and skip. Do NOT add OS/Arch fields to `tools.toml`.
5. **Per-tool failure policy** — `allow_fail = true` in `tools.toml` means warn-and-continue. Default is fail-fast.
6. **Diamond dependency dedup** — shared modules are installed once on first encounter.
7. **Circular dependency** → fatal error.

## Architecture (Planned)

```
src/tool_installer/
├── __init__.py       # Version
├── __main__.py       # CLI entry point (argparse)
├── parser.py         # TOML loading, @ version extraction
├── resolver.py       # DAG construction, topo sort, conflict check
├── executor.py       # Serial install loop, check/force logic
├── strategy.py       # Manifest resolution (OS/Arch merge)
└── managers/         # Package manager drivers
    ├── __init__.py   # Base protocol + registry
    ├── apt.py
    ├── brew.py
    ├── cargo_binstall.py
    └── github_release.py
vendor/
    └── tomli/        # Bundled TOML parser (~100KB)
```

## Coding Conventions

- Use type hints on all public function signatures.
- Keep functions short and single-purpose.
- Prefer `try/except` with specific exceptions over bare `except`.
- Print structured messages: `✅ Skip`, `⚠️ Warning`, `❌ Error`, `📦 Installing`.
- Tests go in `tests/` using `pytest`.
- No global mutable state.
