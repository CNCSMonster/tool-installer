# AGENTS.md

## Environment

Use the Docker development container as the canonical development environment.

Daily commands:

```bash
devbox enter    # 进入容器
exit            # 退出容器（容器继续运行）
devbox stop     # 停止容器
devbox restart  # 重启并进入
```

首次使用或需要重建环境时：

```bash
devbox init                    # 初始化配置（已初始化可跳过）
devbox rebuild                 # 重建容器
```

Run project commands inside the container unless the user explicitly asks otherwise.

## Sensitive files

Do not read, print, grep, parse, summarize, or inspect sensitive files unless the user explicitly asks.
This includes:

- `.env`, `.env.*`
- `~/mise.toml`
- `~/.config/mise/*`
- `~/.codex/*`
- `~/.ssh/*`
- any file with token, secret, key, credential, or password in its name

Allowed checks:

```bash
test -f .env && echo present
test -n "$SOME_ENV" && echo present
```

Never print secret values.

## Host services

Use `host.docker.internal` to reach host services such as llm-proxy.
Do not assume `127.0.0.1` inside a container refers to the host.
