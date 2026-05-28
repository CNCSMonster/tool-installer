# DRAFT: cargo-install binstall_first

> **Status**: 草稿，待讨论确认后合并入 SPEC.md
> **Date**: 2026-05-28 (v2)

---

## 动机

tool-installer 的 `cargo-install` manager 只支持源码编译，29 个 Rust 工具在 CI 上需要 48 分钟。
约 77% 的工具有预编译二进制可用，通过 `binstall_first` 可将安装时间降至 8-15 分钟。

设计目标：
- **自给自足**：manager 内部处理 binstall 的获取，不依赖外部预装
- **困惑最少**：用户只需设置 `binstall_first = true`，无需理解 binstall 的来源
- **向后兼容**：默认 `false`，不影响现有行为

## 设计

### 新增策略字段

| Field | Type | Required | Default | 适用 Manager |
|---|---|---|---|---|
| `binstall_first` | bool | no | `false` | `cargo-install` |

### 内部流程

当 `binstall_first = true` 时，`cargo-install` manager 的安装行为：

```
1. binstall 可用性检查
   ├── cargo-binstall 在 PATH 中 → 进入阶段 2
   └── 不存在 → 自动获取
       ├── HTTP GET github release tarball
       │   URL: https://github.com/cargo-bins/cargo-binstall/releases/latest/download/
       │         cargo-binstall-{arch}-{os}.{ext}
       │   arch/os 从 platform 模块获取
       ├── 解压到 ~/.cargo/bin/
       └── 验证 cargo-binstall --version 成功 → 进入阶段 2
           获取失败 → 跳过阶段 2，直接阶段 3

2. 预编译尝试
   cargo binstall -y --disable-strategies compile [--version <ver>] <pkg>
   ├── 返回 0 → 安装成功，结束
   └── 返回非 0 → 进入阶段 3

3. 源码编译 fallback
   cargo install [--locked] [--version <ver>] <pkg>
   └── 与当前 cargo-install 行为完全一致
```

### 自动获取 binstall 的细节

- **下载方式**：复用 tool-installer 已有的 HTTP 下载能力（urllib）
- **目标目录**：优先 `$CARGO_HOME/bin/`，否则 `~/.cargo/bin/`（与 cargo 生态一致，通常已在 PATH 中）
- **平台适配**：

| 平台 | arch | 文件名 |
|---|---|---|
| Linux x86_64 | x86_64-unknown-linux-musl | cargo-binstall-x86_64-unknown-linux-musl.tgz |
| Linux aarch64 | aarch64-unknown-linux-musl | cargo-binstall-aarch64-unknown-linux-musl.tgz |
| macOS x86_64 | x86_64-apple-darwin | cargo-binstall-x86_64-apple-darwin.tgz |
| macOS aarch64 | aarch64-apple-darwin | cargo-binstall-aarch64-apple-darwin.tgz |

- **幂等**：如果 PATH 或 cargo bin 目录中的 `cargo-binstall` 已存在、可执行且 `--version` 成功，跳过下载
- **失败处理**：获取失败、校验失败、预编译尝试失败均不报错，跳到阶段 3（源码编译）；只有阶段 3 失败才导致安装失败

### 范围澄清

- `binstall_first` 仅适用于 registry crate 安装；当 `cargo-install` 使用 `git`/`tag`/`branch`/`rev` 时忽略该优化，直接保持现有 `cargo install --git ...` 行为。
- 下载的 release archive 只提取名为 `cargo-binstall` 的普通文件，不使用 archive 内路径写入目标目录，避免路径穿越类问题。
- `install_command()` 仍表示确定性的源码编译 fallback 命令；包含 binstall 尝试的实际安装流程由 manager 的 `install()` 负责。

### 阶段 2 中 `--disable-strategies compile` 的作用

binstall 阶段始终使用 `--disable-strategies compile`：
- 禁用源码编译策略，只尝试 GitHub Releases 和 QuickInstall
- 避免 binstall 内部触发源码编译（浪费 120s 超时）
- 如果用户想要 binstall 的 compile 策略，应直接用 `cargo-binstall` manager

### 与 check 的关系

`cargo-install` 的 installed-state check 不变：
- 仍然通过 cargo metadata 检查已安装版本
- `binstall_first` 只影响 install 阶段，不影响 check 阶段

### 安全约束

- 预编译二进制的来源（GitHub Releases）由 `cargo binstall` 自身管理
- tool-installer 不额外验证预编译二进制的完整性
- 如果用户关心完整性，应使用 `cargo-install`（无 `binstall_first`）强制源码编译
- binstall 自身的下载使用 HTTPS，与 tool-installer 其他下载一致

## Manifest 示例

```toml
[bat.linux]
manager = "cargo-install"
pkg = "bat"
locked = true
binstall_first = true
```

## CI 验证策略

| Job | binstall_first | 目的 |
|---|---|---|
| fast-install | `true`（默认 manifest） | 验证预编译路径 + 自动获取 binstall |
| source-compile | `false`（覆盖） | 验证源码编译路径仍可用 |

## 对现有 SPEC 的影响

- `cargo-install` manager 的 optional fields 新增 `binstall_first`
- 不改变 `cargo-binstall` manager 的行为（仍然独立、非 check-capable）
- 不改变 `cargo-install` 的 check 语义

## 设计决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| binstall 来源 | manager 内部自动获取 | 自给自足，用户零困惑 |
| 默认值 | `false` | 向后兼容，opt-in |
| 获取失败处理 | 静默 fallback 到源码编译 | 不强制依赖 binstall |
| compile 策略 | 始终禁用 | 避免意外源码编译超时 |
| 资源限制 | 不内置计算 | setup-new.sh 处理，环境变量自动继承 |
