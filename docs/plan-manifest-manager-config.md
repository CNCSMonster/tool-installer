# Implementation Plan: Manifest Manager Configuration Layer

## Overview

基于 `docs/draft-manifest-manager-config.md` 规范，将 `[_network]` 废弃并迁移到 `[_github-release]` manager 配置段，同时实现 GitHub token 自动检测和运行时告知。

## Architecture Decisions

- **废弃 `[_network]`**：字段移入 `[_github-release]`，减少不必要的配置层级
- **Token 自动检测**：`GITHUB_TOKEN` 环境变量 → `gh auth token`，和 `docker-build-test.sh` 模式一致
- **Token 失败不中断**：降级为匿名 + 警告，token 是优化手段不是必需条件
- **Mirror 永不携带 token**：`Authorization` header 只发给 `github.com` / `api.github.com`
- **保留 `_` 前缀命名空间**：`[_github-release]` 是保留段，不被当作工具名

## Dependency Graph

```
models.py (GithubReleaseConfig)
    │
    ├── parser.py (parse [_github-release] section)
    │       │
    │       ├── cli.py (pass config to registry)
    │       │       │
    │       │       └── managers/__init__.py (registry accepts config)
    │       │               │
    │       │               └── github_release.py (use config + token)
    │       │
    │       └── tests (all callers of parse_manifest_file)
    │
    └── token.py (new: GitHub token auto-detection)
            │
            └── github_release.py (use token in requests)
```

## Task List

### Phase 1: Model & Parser Migration

#### Task 1: Replace `NetworkConfig` with `GithubReleaseConfig`

**Description:** 删除 `NetworkConfig` 模型，新增 `GithubReleaseConfig`。字段完全相同（`github_mirrors`, `timeout`, `retry`），只是语义从"全局网络配置"变为"github-release manager 配置"。

**Acceptance criteria:**
- [ ] `GithubReleaseConfig` dataclass 存在于 `models.py`
- [ ] `NetworkConfig` 从 `models.py` 删除
- [ ] 所有 import `NetworkConfig` 的文件更新为 `GithubReleaseConfig`

**Verification:**
- [ ] `grep -r NetworkConfig src/` 无结果
- [ ] `python3 -m pytest` 通过

**Dependencies:** None

**Files touched:**
- `src/tool_installer/models.py`
- `src/tool_installer/parser.py`
- `src/tool_installer/cli.py`
- `src/tool_installer/managers/__init__.py`
- `src/tool_installer/managers/github_release.py`
- `tests/test_network_config.py`

**Scope:** Medium (6 files，但改动是机械重命名)

---

#### Task 2: Replace `[_network]` parsing with `[_github-release]` parsing

**Description:** parser 中将 `_parse_network_section` 改为 `_parse_github_release_section`，识别 `[_github-release]` 而非 `[_network]`。对 `[_network]` 段报配置错误并提示迁移到 `[_github-release]`。

**Acceptance criteria:**
- [ ] `[_github-release]` 段被正确解析为 `GithubReleaseConfig`
- [ ] `[_network]` 段报 `ManifestError`，提示 "use [_github-release] instead"
- [ ] 缺少 `[_github-release]` 时返回默认 `GithubReleaseConfig`
- [ ] 其他 `_*` 段（非 `_network` 非 `_github-release`）报未知保留段错误

**Verification:**
- [ ] `python3 -m pytest tests/test_network_config.py` 通过（测试内容已更新）
- [ ] `python3 -m pytest` 全量通过

**Dependencies:** Task 1

**Files touched:**
- `src/tool_installer/parser.py`
- `tests/test_network_config.py`

**Scope:** Small

---

### Phase 2: Token Auto-Detection

#### Task 3: Implement `github_token` module

**Description:** 新建 `src/tool_installer/github_token.py`，实现 token 自动检测逻辑。

**Acceptance criteria:**
- [ ] `detect_token() -> Tuple[Optional[str], str]` 返回 `(token, source_description)`
- [ ] 检测顺序：`GITHUB_TOKEN` 环境变量 → `gh auth token`
- [ ] 环境变量存在且非空 → 返回 token，source = `"from GITHUB_TOKEN env"`
- [ ] 环境变量不存在 → 尝试 `gh auth token`
- [ ] `gh` 存在且输出非空 → 返回 token，source = `"from gh CLI (gh auth token)"`
- [ ] `gh` 不存在或未登录或失败 → 返回 `(None, "not configured")`
- [ ] `gh auth token` 的 stderr 被丢弃
- [ ] 不执行 `gh auth login`
- [ ] 不持久化 token
- [ ] Python 3.8 兼容（`subprocess.run` 参数、类型注解）

**Verification:**
- [ ] `python3 -m pytest tests/test_github_token.py` 通过
- [ ] mock 测试覆盖所有分支

**Dependencies:** None

**Files touched:**
- `src/tool_installer/github_token.py` (new)
- `tests/test_github_token.py` (new)

**Scope:** Medium

---

#### Task 4: Integrate token detection into `GithubReleaseManager`

**Description:** `GithubReleaseManager` 使用 token 在 HTTP 请求中添加 `Authorization` header。

**Acceptance criteria:**
- [ ] `GithubReleaseManager.__init__` 接受 `GithubReleaseConfig`
- [ ] Token 检测结果缓存在 manager 实例上（同一进程只检测一次）
- [ ] `_fetch_url()` 给 github.com / api.github.com 请求添加 `Authorization: token <TOKEN>` header
- [ ] `_download_asset()` 给 github.com 请求添加 token header
- [ ] Mirror URL **不**附加 token header
- [ ] Token 为 `None` 时不添加 header
- [ ] `_build_download_urls()` 区分 mirror URL 和 github.com URL（返回结构化信息而非纯字符串列表）

**Verification:**
- [ ] `python3 -m pytest tests/test_network_config.py` 通过
- [ ] `python3 -m pytest tests/test_manager_github_release.py` 通过
- [ ] Mock 测试验证：有 token 时 header 存在、mirror 无 header

**Dependencies:** Task 1, Task 3

**Files touched:**
- `src/tool_installer/managers/github_release.py`
- `tests/test_network_config.py`
- `tests/test_manager_github_release.py`

**Scope:** Medium

---

### Phase 3: Runtime Token Reporting

#### Task 5: Add token source reporting to executor output

**Description:** executor 在安装 `github-release` 类工具时，打印一行 token 来源信息。

**Acceptance criteria:**
- [ ] 首次安装 github-release 工具时打印 `🔑 GitHub token: <source>`
- [ ] 后续工具打印 `🔑 GitHub token: (cached) <source>`
- [ ] 无 token 时打印 `⚠️  GitHub token: not configured (anonymous, 60 req/hour)`
- [ ] dry-run 模式下**不打印** token 信息
- [ ] Token 来源信息打印到 stdout（和工具安装信息一致）

**Verification:**
- [ ] `python3 -m pytest` 通过
- [ ] 手动 dry-run 验证无 token 输出
- [ ] Mock apply 验证有/无 token 的输出格式

**Dependencies:** Task 4

**Files touched:**
- `src/tool_installer/executor.py`
- `src/tool_installer/managers/github_release.py`

**Scope:** Small

---

### Checkpoint: Core Implementation

- [ ] `python3 -m pytest` 全量通过
- [ ] `[_github-release]` 段正确解析
- [ ] Token 自动检测工作（mock 验证）
- [ ] Mirror 不携带 token（mock 验证）
- [ ] 运行时告知输出正确

---

### Phase 4: SPEC & Documentation

#### Task 6: Update SPEC.md

**Description:** 删除 `[_network]` 规范，新增 `[_github-release]` 段规范和 token 检测规范。

**Acceptance criteria:**
- [ ] `[_network]` 段从 SPEC.md 中删除
- [ ] `[_github-release]` 段规范加入 Reserved Manifest Sections
- [ ] Token 自动检测行为加入新章节或 Security and Trust Model
- [ ] Mirror 不支持 token 写入规范

**Dependencies:** Task 1-5（确认设计后再更新 SPEC）

**Files touched:**
- `SPEC.md`

**Scope:** Small

---

#### Task 7: Update README.md and PLAN.md

**Description:** 更新文档反映新设计。

**Acceptance criteria:**
- [ ] README.md 的 Network configuration 部分改为 `[_github-release]` 示例
- [ ] README.md 说明 token 自动检测行为
- [ ] PLAN.md 添加 Phase 10 记录
- [ ] PLAN.md 更新测试计数

**Dependencies:** Task 6

**Files touched:**
- `README.md`
- `PLAN.md`

**Scope:** Small

---

### Phase 5: Examples & Tests

#### Task 8: Update examples

**Description:** 更新 `examples/dotfiles/manifest.toml` 使用 `[_github-release]` 而非 `[_network]`。

**Acceptance criteria:**
- [ ] `examples/dotfiles/manifest.toml` 使用 `[_github-release]` 段
- [ ] `examples/manifest.toml` 不含 `[_network]`（如有的话）
- [ ] `examples/dotfiles/` dry-run 成功
- [ ] `examples/` dry-run 成功

**Dependencies:** Task 2

**Files touched:**
- `examples/dotfiles/manifest.toml`
- `examples/manifest.toml` (if exists)

**Scope:** Small

---

#### Task 9: Update and expand tests

**Description:** 更新现有测试，新增 token 检测和 `[_github-release]` 解析测试。

**Acceptance criteria:**
- [ ] `tests/test_network_config.py` 重命名为 `tests/test_github_release_config.py`（或内容更新）
- [ ] 测试 `[_github-release]` 解析（有效配置、默认值、验证错误）
- [ ] 测试 `[_network]` 被拒绝并提示迁移
- [ ] 测试 token 检测所有分支（env、gh、无 token、gh 失败）
- [ ] 测试 token header 在请求中存在/不存在
- [ ] 测试 mirror URL 不携带 token
- [ ] 测试 token 来源告知输出格式
- [ ] 测试 dry-run 不打印 token 信息

**Dependencies:** Task 1-5

**Files touched:**
- `tests/test_network_config.py` (or `tests/test_github_release_config.py`)
- `tests/test_github_token.py`
- `tests/test_executor_managers.py` (if token output tests go here)

**Scope:** Medium

---

#### Task 10: Full verification

**Description:** 全量测试 + Python 3.8 容器验证。

**Acceptance criteria:**
- [ ] `python3 -m pytest -q` 全量通过（host Python 3.12）
- [ ] `uv run --python 3.8 --with pytest python -m pytest -q` 通过（容器内）
- [ ] `examples/dotfiles/` dry-run 成功
- [ ] `examples/` dry-run 成功
- [ ] `PLAN.md`、`README.md`、`SPEC.md` 内容一致

**Dependencies:** Task 1-9

**Files touched:** None (verification only)

**Scope:** Small

---

### Checkpoint: Complete

- [ ] 所有测试通过（Python 3.12 + 3.8）
- [ ] `[_network]` 完全移除，`[_github-release]` 正确工作
- [ ] Token 自动检测 + 运行时告知
- [ ] SPEC/README/PLAN 文档一致
- [ ] 示例 dry-run 成功
- [ ] 准备提交

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `gh auth token` 在某些环境行为不一致 | Medium | Mock 测试覆盖所有分支；失败降级为匿名 |
| `GITHUB_TOKEN` 环境变量可能包含恶意值 | Low | Token 仅用于 HTTP header，不执行、不 eval |
| 删除 `[_network]` 破坏已有用户配置 | Medium | 报明确错误提示迁移到 `[_github-release]` |
| Token 泄露到日志或 dry-run 输出 | High | dry-run 不检测；输出只显示来源描述，不显示 token 值 |
| `urllib.request` 对 `Authorization` header 的处理 | Low | `urllib.request.Request.add_header` 标准用法 |

## Parallelization

- **Task 1 + Task 3** 可并行（model 重命名 vs token 模块，无依赖）
- **Task 2 依赖 Task 1**
- **Task 4 依赖 Task 1 + Task 3**
- **Task 5 依赖 Task 4**
- **Task 6-7 依赖 Task 1-5 确认**
- **Task 8-9 依赖 Task 1-5**
- **Task 10 依赖全部**
