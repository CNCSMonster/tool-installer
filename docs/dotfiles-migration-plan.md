# Dotfiles 迁移计划：setup.sh → tool-installer

> **Status**: 草稿，待讨论确认后执行
> **Date**: 2026-05-28
> **目标**: 将 dotfiles 的工具安装逻辑从 ~1400 行 bash 迁移到声明式 TOML + tool-installer

---

## 1. 架构：三层模型

```
Layer 0: Bootstrap (bash)
  └─ 安装 Python、gh CLI、tool-installer
  └─ 提示 gh auth login
  └─ xdotter deploy（配置文件）

Layer 1: 工具安装 (tool-installer)
  └─ tool-installer install dev
  └─ 45+ 工具，声明式 TOML

Layer 2: 后置脚本 (bash)
  └─ Helix runtime 编译
  └─ Yazi 插件安装
  └─ 字体缓存刷新
```

### 为什么三层

| 层 | 为什么独立 |
|---|---|
| Layer 0 | tool-installer 需要 Python，不能自己安装自己。gh 登录必须在 tool-installer 之前完成 |
| Layer 1 | 工具安装的核心，声明式、幂等、有 dry-run |
| Layer 2 | 依赖 Layer 1 安装的工具（yazi 需要先装好才能装插件），且逻辑复杂不适合声明化 |

---

## 2. 模块设计

### tools.toml 模块结构

```toml
[tool-installer]
manifest = "./manifest.toml"

# ── Layer 1a: 编译基础设施 ──
[build-base]
"rust@stable" = "Rust stable toolchain"

# ── Layer 1b: Cargo 工具（依赖 Rust）──
[cargo-tools]
depends = ["build-base"]
"sccache" = { desc = "编译缓存", allow_fail = true }
"wild-linker" = { desc = "快速链接器", allow_fail = true }
"bat@0.26.1" = "Cat 替代品"
"eza@0.23.4" = "ls 替代品"
"fd-find@10.4.2" = "find 替代品"
"starship@1.24.2" = "Shell prompt"
"zoxide@0.9.9" = "cd 替代品"
"tokei@14.0.0" = "代码统计"
"navi@2.24.0" = "交互式命令行"
"gitui@0.28.1" = "Git TUI"
"kondo@0.9.0" = "项目清理"
"jaq@3.0.0" = "jq 替代品"
"mdbook@0.5.2" = "文档生成器"
"mdbook-mermaid@0.17.0" = "mdbook 图表"
"gen-mdbook-summary@0.0.10" = "mdbook 目录"
"tree-sitter-cli@0.26.8" = "语法解析器"
"tree-sitter-grep@0.1.0" = "语法感知搜索"
"tree-sitter-show-ast@0.0.2" = "AST 可视化"
"macchina@6.4.0" = "系统信息"
"conceal@0.7.0" = "隐藏敏感信息"
"rust-script@0.36.0" = "Rust 脚本运行器"
"parallel-disk-usage@0.22.0" = "磁盘分析"
"nu@0.112.2" = "现代 Shell"
"uv@0.11.3" = "Python 包管理器"
"mise@2026.4.5" = "版本管理器"
"cargo-audit@0.22.1" = "依赖审计"
"cargo-fuzz" = { desc = "模糊测试", allow_fail = true }
"grcov" = { desc = "代码覆盖率", allow_fail = true }
"cargo-tarpaulin" = { desc = "代码覆盖率", allow_fail = true }
"zola@v0.22.1" = { desc = "静态网站生成器", allow_fail = true }

# ── Layer 1c: 编辑器和终端工具 ──
[editors]
depends = ["build-base"]
neovim = "Neovim 编辑器"
helix = "Helix 编辑器"
zellij = "终端复用器"
yq = "YAML/JSON 处理器"

# ── Layer 1d: 语言运行时（独立）──
[languages]
go = "Go via mise"
node = "Node.js via mise"
pnpm = "pnpm via mise"
zig = "Zig via mise"
yazi = "终端文件管理器 via mise"
gopls = "Go LSP via mise"

# ── Layer 1e: LSP 服务器 ──
[lsp-servers]
depends = ["languages"]
typescript-lsp = "TypeScript LSP"
pyright = "Python LSP"
yaml-lsp = "YAML LSP"
bash-lsp = "Bash LSP"
marksman = "Markdown LSP"
zls = "Zig LSP"
lua-lsp = "Lua LSP"
qwen-code = { desc = "Qwen Code", allow_fail = true }

# ── Layer 1f: 其他 ──
[extras]
depends = ["build-base"]
xdotter = "配置部署工具"
cargo-binstall = "Cargo 预编译安装器"

# ── 全量安装 ──
[dev]
depends = ["cargo-tools", "editors", "languages", "lsp-servers", "extras"]
```

### 模块依赖图

```
build-base (rustup)
    │
    ├── cargo-tools (26 个 cargo 工具)
    ├── editors (neovim, helix, zellij, yq)
    └── extras (xdotter, cargo-binstall)

languages (mise: go, node, pnpm, zig, yazi, gopls)
    │
    └── lsp-servers (npm/uv/github-release LSP 工具)

dev = cargo-tools + editors + languages + lsp-servers + extras
```

---

## 3. Manifest 设计要点

### 3.1 网络配置

```toml
[_github-release]
github_mirrors = ["https://mirror.ghproxy.com"]
timeout = 60
retry = 3
```

### 3.2 Rust 工具链

```toml
[rust]
[rust.linux]
manager = "rustup"
components = ["clippy", "rustfmt", "rust-analyzer"]
profile = "minimal"
set_default = true
```

### 3.3 Cargo 工具

```toml
[bat]
[bat.linux]
manager = "cargo-install"
pkg = "bat"
locked = true

[zola]
[zola.linux]
manager = "cargo-install"
pkg = "zola"
git = "https://github.com/getzola/zola"
tag = "v0.22.1"
# 注意：git source 的版本选择器必须是 latest
```

### 3.4 GitHub Release 工具

```toml
[neovim]
[neovim.linux]
manager = "github-release"
repo = "neovim/neovim"
asset = "nvim-linux-x86_64.tar.gz"
bin = "nvim-linux-x86_64/bin/nvim"
install_name = "nvim"
[neovim.linux.version_probe]
command = ["{bin}", "--version"]
regex = "^NVIM v(?P<version>[0-9]+\\.[0-9]+\\.[0-9]+)"
```

### 3.5 Mise 工具

```toml
[go]
[go.linux]
manager = "mise"
plugin = "go"
```

### 3.6 Script Manager（复杂逻辑）

```toml
[helix-runtime]
[helix-runtime.linux]
manager = "script"
path = "scripts/install-helix-runtime"
```

---

## 4. 版本策略

| 类别 | 策略 | 原因 |
|---|---|---|
| Cargo 工具 | **固定版本**（如 `bat@0.26.1`） | 你的 setup.sh 已经固定了版本，保持一致性 |
| GitHub Release | **固定版本** | 避免 breaking changes |
| Mise 工具 | **固定版本**（从 mise/config.toml 迁移） | 保持一致性 |
| NPM LSP | **latest** | LSP 工具通常向后兼容 |
| Rust 工具链 | **stable** | rustup 会跟踪最新 stable |

---

## 5. Layer 0: Bootstrap 脚本

```bash
#!/usr/bin/env bash
set -exo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 0a: 基础系统包 ──
install_system_packages() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        # macOS: Homebrew
        if ! command -v brew &>/dev/null; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install python3 gh
    else
        # Linux: apt
        sudo apt-get update
        sudo apt-get install -y python3 curl gh
    fi
}

# ── 0b: GitHub CLI 登录 ──
ensure_gh_login() {
    if ! gh auth status &>/dev/null; then
        echo ""
        echo "⚠️  GitHub CLI 未登录。登录后可享受 5000 次/小时 API 限额（匿名仅 60 次）。"
        echo "   建议现在登录："
        echo ""
        gh auth login
    fi
    echo "✅ GitHub CLI 已登录"
}

# ── 0c: 安装 tool-installer ──
install_tool_installer() {
    mkdir -p ~/.local/bin
    # TODO: 从 release 下载单文件分发
    # curl -fsSL <release-url> -o ~/.local/bin/tool-installer
    # chmod +x ~/.local/bin/tool-installer
    echo "⚠️  tool-installer 安装待实现（当前需要 PYTHONPATH）"
}

# ── 0d: 配置部署 ──
deploy_configs() {
    # 安装 xdotter（tool-installer 会安装，但 deploy 需要它先存在）
    # 临时方案：直接 cargo install 或 GitHub release 下载
    if ! command -v xd &>/dev/null; then
        cargo install xdotter --locked 2>/dev/null || {
            echo "⚠️  xdotter 安装失败，请手动安装"
            return 1
        }
    fi
    cd "${SCRIPT_DIR}" && xd deploy --force
}

main() {
    install_system_packages
    ensure_gh_login
    install_tool_installer
    deploy_configs
    echo ""
    echo "✅ Bootstrap 完成。运行 'tool-installer install dev' 安装开发工具。"
}

main "$@"
```

---

## 6. Layer 2: 后置脚本

```bash
#!/usr/bin/env bash
set -exo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 2a: Helix runtime（需要 themes/queries/tutor + 编译 grammars）──
install_helix_runtime() {
    # 保留现有的 install-helix-runtime 逻辑
    source "${SCRIPT_DIR}/shells/common/install-functions.sh"
    install-helix-runtime
}

# ── 2b: Yazi 插件（依赖 yazi 已安装）──
install_yazi_plugins() {
    source "${SCRIPT_DIR}/shells/common/install-functions.sh"
    install-yazi-plugins
}

# ── 2c: 字体缓存刷新 ──
refresh_fonts() {
    if command -v fc-cache &>/dev/null; then
        fc-cache -f
        echo "✅ 字体缓存已刷新"
    fi
}

main() {
    install_helix_runtime
    install_yazi_plugins
    refresh_fonts
    echo ""
    echo "✅ 后置配置完成。"
}

main "$@"
```

---

## 7. 迁移后的 setup.sh

```bash
#!/usr/bin/env bash
set -exo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "用法: $0 [选项]"
    echo "  无参数      完整安装（bootstrap + deploy + install + post）"
    echo "  --bootstrap 仅 Layer 0：系统包 + gh 登录 + tool-installer"
    echo "  --deploy    仅配置部署（xdotter）"
    echo "  --install   仅 Layer 1：tool-installer 安装工具"
    echo "  --post      仅 Layer 2：后置脚本"
    echo "  --dry-run   显示 tool-installer 安装计划"
}

do_bootstrap() { bash "${SCRIPT_DIR}/scripts/layer0-bootstrap.sh"; }
do_deploy()    { cd "${SCRIPT_DIR}" && xd deploy --force; }
do_install()   { tool-installer install dev; }
do_post()      { bash "${SCRIPT_DIR}/scripts/layer2-post.sh"; }

main() {
    case "${1:-}" in
        --bootstrap) do_bootstrap ;;
        --deploy)    do_deploy ;;
        --install)   do_install ;;
        --post)      do_post ;;
        --dry-run)   tool-installer install dev --dry-run ;;
        "")
            do_bootstrap
            do_deploy
            do_install
            do_post
            echo ""
            echo "=========================================="
            echo "✅ 全部安装完成"
            echo "=========================================="
            ;;
        *) usage; exit 1 ;;
    esac
}

main "$@"
```

---

## 8. 迁移步骤

### Phase 1: 准备（不影响现有 setup.sh）

1. 在 `dotfiles/` 下创建 `tools.toml` 和 `manifest.toml`
2. 创建 `scripts/layer0-bootstrap.sh` 和 `scripts/layer2-post.sh`
3. 在容器中 dry-run 验证所有策略解析通过
4. 在容器中 apply 测试单个模块（如 `tool-installer install build-base`）

### Phase 2: 并行验证

5. 保留原 `setup.sh` 不动
6. 新增 `setup-new.sh` 使用三层架构
7. 在新容器中对比：`setup.sh` vs `setup-new.sh` 安装结果

### Phase 3: 切换

8. `setup.sh` 改为三层架构（原逻辑移到 `setup-legacy.sh` 备份）
9. 更新 README 说明新用法
10. 更新 Dockerfile 使用新 setup.sh

### Phase 4: 清理

11. 确认稳定后删除 `setup-legacy.sh`
12. 清理 `install-functions.sh` 中已被 tool-installer 替代的函数

---

## 9. 风险和缓解

| 风险 | 缓解 |
|---|---|
| tool-installer 尚未发布到可下载位置 | Phase 1 用 PYTHONPATH；Phase 3 前发布单文件分发 |
| Cargo 工具版本不匹配 | manifest 里固定版本，和 setup.sh 保持一致 |
| Neovim nightly 版本不可控 | 用 version_probe 检查已装版本，避免重复下载 |
| Zola git source 需要编译 | `allow_fail = true`，编译失败不阻断其他工具 |
| 网络问题导致安装失败 | `[_github-release]` 镜像配置 + gh token 自动检测 |
| 现有用户习惯改变 | 保留 `--deploy` / `--install` 选项，行为兼容 |

---

## 10. 待讨论

1. **Cargo 工具用 `cargo-binstall` 还是 `cargo-install`？**
   - `cargo-binstall`：快（下载预编译），但不是 check-capable
   - `cargo-install`：慢（源码编译），但是 check-capable
   - 建议：先 `cargo-install`（稳定），后续可切换

2. **是否需要 `tool-installer install build-base` 单独模块？**
   - 用于 CI 只装 Rust 不装其他工具
   - 建议：保留，CI 场景有用

3. **mise 工具版本从 `mise/config.toml` 迁移还是独立声明？**
   - 迁移：版本来源单一
   - 独立：tool-installer manifest 里声明，mise/config.toml 删除
   - 建议：独立，manifest 成为唯一的工具声明来源
