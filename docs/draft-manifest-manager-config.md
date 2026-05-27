# DRAFT: Manifest Manager Configuration Layer

> **Status**: 草稿 v3，待讨论确认后合并入 SPEC.md
> **Date**: 2026-05-28
> **Scope**: manifest 两层结构、`[_github-release]` manager 配置、token 自动检测

---

## 1. 设计决策

| 决策 | 结论 |
|---|---|
| `[_network]` | **废弃**。字段移入各 `[_<manager>]` 段 |
| Token 来源 | 自动检测（`GITHUB_TOKEN` 环境变量 → `gh auth token`），运行时告知用户来源 |
| Token 显式配置 | 不需要。自动检测 + 日志告知，和 `docker-build-test.sh` 模式一致 |
| Mirror token | 永不支持，现在和未来都不支持 |
| Token 获取失败 | 不中断安装，降级为匿名并警告 |

## 2. Manifest 两层结构

### 2.1 层级定义

| 层 | 命名规则 | 用途 | 示例 |
|---|---|---|---|
| **Manager 配置层** | `[_<manager-name>]` | 配置某种安装方式的全局行为 | `[_github-release]` |
| **工具策略层** | `[tool-name]` | 配置某个工具的具体安装策略 | `[fd.linux]`、`[neovim]` |

`_` 前缀是保留命名空间。所有 `_` 开头的顶层 key 都不是工具名。

### 2.2 `[_network]` 废弃

`[_network]` 段不再支持。原 `[_network]` 的三个字段全部移入 `[_github-release]`：

| 原 `[_network]` 字段 | 移入 `[_github-release]` |
|---|---|
| `github_mirrors` | `[_github-release].github_mirrors` |
| `timeout` | `[_github-release].timeout` |
| `retry` | `[_github-release].retry` |

理由：v1 中这三个字段只有 `github-release` manager 使用。独立的 `[_network]` 段增加了配置层级的复杂度，却没有实际收益。未来其他 manager 需要网络配置时，各自在 `[_<manager>]` 段中定义。

### 2.3 未来 Manager 配置段

| Manager | 配置段名 | 可能的字段（未来） |
|---|---|---|
| `apt` | `[_apt]` | `sources_mirror` |
| `cargo-install` | `[_cargo-install]` | `registry_mirror` |
| `npm-global` | `[_npm-global]` | `registry` |

各 manager 的配置段独立定义，不存在跨 manager 的共享配置段。

## 3. `[_github-release]` 段规范

### 3.1 字段定义

```toml
[_github-release]
github_mirrors = ["https://mirror.ghproxy.com", "https://ghfast.top"]
timeout = 60
retry = 3
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `github_mirrors` | array of strings | no | `[]` | 镜像 URL 有序列表 |
| `timeout` | number (seconds) | no | `30` | HTTP 请求超时 |
| `retry` | integer | no | `3` | 每个 URL 的重试次数 |

### 3.2 语义

- `github_mirrors`：镜像 URL 有序列表。下载时依次尝试，每个 URL 重试 `retry` 次，全部失败后尝试下一个，最后直连 GitHub
- `timeout`：同时作用于 GitHub API 调用（`_latest_tag`）和 asset 下载的连接超时和总传输超时
- `retry`：每个 URL 的重试次数（含指数退避），重试耗尽后才切换到下一个 URL

### 3.3 Mirror 不支持 token

Mirror URL **永远不附加** `Authorization` header。用户使用 mirror 就是因为 mirror 无限制、无需认证。

## 4. GitHub Token 自动检测

### 4.1 检测机制

tool-installer 在首次需要访问 GitHub 时，按以下顺序自动检测 token：

1. **环境变量 `GITHUB_TOKEN`**：如果存在且非空，使用它
2. **`gh auth token`**：如果 `gh` 命令存在且用户已登录，使用其输出
3. **都没有**：匿名访问（无 token）

同一 install 进程内只检测一次，结果缓存。

### 4.2 运行时告知

每次安装 `github-release` 类工具时，在工具名后打印一行 token 来源信息：

```
📦 Installing fd
🔑 GitHub token: from GITHUB_TOKEN env
```

```
📦 Installing neovim
🔑 GitHub token: from gh CLI (gh auth token)
```

```
📦 Installing fd
⚠️  GitHub token: not configured (anonymous, 60 req/hour)
```

同一进程中后续工具使用缓存，打印 `(cached)`：

```
📦 Installing helix
🔑 GitHub token: (cached) from gh CLI
```

### 4.3 Token 使用方式

检测到 token 后，在 HTTP 请求中添加 header：

```
Authorization: token <TOKEN>
```

适用于：
- GitHub API 调用（`api.github.com/repos/.../releases/latest`）
- GitHub release asset 下载（`github.com/.../releases/download/...`）

**不**适用于：
- Mirror URL（永远不附加 token）

### 4.4 检测失败行为

| 场景 | 行为 |
|---|---|
| `GITHUB_TOKEN` 不存在或为空 | 尝试 `gh auth token` |
| `gh` 命令不存在 | 降级为匿名，打印警告 |
| `gh` 存在但未登录 | 降级为匿名，打印警告 |
| `gh auth token` 执行失败 | 降级为匿名，打印警告 |

**不中断安装**。Token 是优化手段（提速 + 避免 rate limit），不是必需条件。
没有 token 时以匿名方式继续，但会警告用户可能遇到 rate limit。

### 4.5 检测时机

- 在 `execute_plan` 阶段首次遇到 `github-release` 类工具时检测
- dry-run 模式下**不检测** token（dry-run 不执行外部命令、不访问网络）
- dry-run 输出中**不打印** token 信息

## 5. 安全约束

| 约束 | 说明 |
|---|---|
| **不持久化 token** | token 仅在进程内存中，不写入文件、日志、临时文件 |
| **不传递给 mirror** | `Authorization` header 只发给 `github.com` 和 `api.github.com` |
| **不传递给其他 manager** | apt、cargo、npm 等 manager 不接收 GitHub token |
| **不暴露在 dry-run 输出中** | dry-run 不得打印、记录、或暗示 token 的存在 |
| **不执行 `gh auth login`** | tool-installer 只读取现有登录状态，不触发登录流程 |
| **stderr 静默** | `gh auth token` 的 stderr 被丢弃 |
| **不支持 mirror token** | mirror 永远不附加认证信息 |

## 6. 完整 Manifest 示例

```toml
# ── Manager 配置层 ──

[_github-release]
github_mirrors = [
    "https://mirror.ghproxy.com",
    "https://ghfast.top",
]
timeout = 60
retry = 3

# ── 工具策略层 ──

[python]
[python.linux]
manager = "mise"
plugin = "python"

[rust]
[rust.linux]
manager = "rustup"
components = ["clippy", "rustfmt"]
profile = "minimal"
set_default = true

[fd]
[fd.linux]
manager = "github-release"
repo = "sharkdp/fd"
asset = "fd-{version}-{arch}-unknown-linux-gnu.tar.gz"
bin = "fd-{version}-{arch}-unknown-linux-gnu/fd"
install_name = "fd"
[fd.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^fd (?P<version>[0-9]+\\.[0-9]+\\.[0-9]+)"

[neovim]
[neovim.linux]
manager = "github-release"
repo = "neovim/neovim"
asset = "nvim-linux-x86_64.tar.gz"
bin = "nvim-linux-x86_64/bin/nvim"
install_name = "nvim"
```

### 运行效果示例（有 gh 登录）

```
📦 Installing python
📦 Installing rust
📦 Installing fd
🔑 GitHub token: from gh CLI (gh auth token)
📦 Installing neovim
🔑 GitHub token: (cached) from gh CLI
```

### 运行效果示例（无 gh 登录）

```
📦 Installing python
📦 Installing rust
📦 Installing fd
⚠️  GitHub token: not configured (anonymous, 60 req/hour)
📦 Installing neovim
⚠️  GitHub token: (cached) not configured
```

## 7. 对现有实现的影响

### 7.1 删除

- `[_network]` 段的解析逻辑
- `NetworkConfig` 数据模型中的 `[_network]` 相关代码
- SPEC.md 中 `[_network]` 段的规范

### 7.2 新增

- `[_github-release]` 段的解析逻辑
- Token 自动检测（`GITHUB_TOKEN` → `gh auth token`）
- 运行时 token 来源告知（stdout 输出）
- `GithubReleaseManager` 使用 token header

### 7.3 修改

- `GithubReleaseManager` 的 `__init__` 接收 `[_github-release]` 配置而非 `NetworkConfig`
- `_download_asset` 和 `_fetch_url` 使用 token header（仅发给 github.com）
- `default_registry` 传递 `[_github-release]` 配置

### 7.4 不变

- 工具策略层的结构和语义不变
- Manager 的必需/可选策略字段不变
- Dry-run 行为不变
- 其他 manager 不受影响

### 7.5 向后兼容

- 没有 `[_github-release]` 段的 manifest：使用硬编码默认值（无镜像、30s、3 次重试），token 自动检测
- 旧的 `[_network]` 段：报配置错误（未知保留段），提示迁移到 `[_github-release]`

## 8. 实现计划

| 任务 | 描述 |
|---|---|
| 1 | 删除 `[_network]` 解析，新增 `[_github-release]` 解析 |
| 2 | 替换 `NetworkConfig` 为 `GithubReleaseConfig` 模型 |
| 3 | 实现 token 自动检测（`GITHUB_TOKEN` → `gh auth token`） |
| 4 | `GithubReleaseManager` 使用 token header，仅发给 github.com |
| 5 | 运行时 token 来源告知输出 |
| 6 | 更新 SPEC.md、README.md、PLAN.md |
| 7 | 更新测试和示例 |
| 8 | 全量测试 + Python 3.8 验证 |
