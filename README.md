# tool-installer

`tool-installer` is a declarative development-environment installation orchestrator.
It reads `tools.toml` from the current working directory, resolves the selected module and its dependencies, validates install strategies from the referenced manifest, and processes tools strictly serially.

## Usage

```bash
tool-installer install <module> --dry-run
tool-installer install <module>
```

`tools.toml` must contain:

```toml
[tool-installer]
manifest = "./manifest.toml"
```

See `SPEC.md` for the complete behavior contract and `examples/` for a minimal fixture.

## Privilege Requirements

Some managers (e.g., `apt`) require root privileges to install packages. `tool-installer` mirrors the [dotfiles `sudo_run`](~/dotfiles/setup.sh) helper:

- If the process is already running as root, commands are executed directly.
- If not root, the command is prefixed with `sudo`, prompting for the user's password.

### TTY Requirement

`sudo` requires an interactive TTY to prompt for a password. If you run `tool-installer` in a non-interactive environment (e.g., CI pipeline, cron job, nohup, SSH without `-t`), the install will fail with a clear error message.

**Solutions:**

1. **Run in an interactive terminal** (recommended for local use):
   ```bash
   tool-installer install dev
   # sudo will prompt for password when needed
   ```

2. **Run as root** (use with caution):
   ```bash
   sudo tool-installer install dev
   ```

3. **Use SSH with TTY allocation**:
   ```bash
   ssh -t user@host "tool-installer install dev"
   ```

4. **For non-interactive environments**, use `sudo` with NOPASSWD or run as root directly (configure according to your security policy).

### Security Notes

- `tool-installer` does **not** support NOPASSWD configuration — it respects the system's `sudo` settings.
- If your user is configured for passwordless sudo, commands will execute without prompting.
- The credential (sudo token) lifetime is managed by the system's `sudo` configuration, not by `tool-installer`. A long download will not cause the cached credentials to expire mid-install — the entire `sudo` command runs as a single process.
