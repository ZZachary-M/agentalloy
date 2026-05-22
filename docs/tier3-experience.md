# Tier 3 Harness Experience

**Do I need this doc?** If you installed Skillsmith with a harness other than Claude Code,
Continue.dev, or a custom SDK integration — yes. If you're using Claude Code, skip this.

## Quick decision tree

```
Are you using Claude Code, Continue.dev, or the Python SDK?
  → Yes: You're Tier 1. Full functionality. Stop reading.
  → No: You're Tier 3. Read on.

Does your harness reload rules files when they change on disk?
  → Yes (Cursor, Windsurf): The sidecar gives you near-real-time updates.
  → Sometimes (Copilot, Cline, Gemini CLI): Requires workspace reload; less seamless.

Are you OK running a background process?
  → Yes: Run `skillsmith watch start --harness <name>` and get most of Tier 1's behavior.
  → No: You'll get the initial context only; phase transitions won't be reflected mid-session.
```

## What Tier 3 gets (with the sidecar running)

| Feature | Status |
|---|---|
| Initial workflow skill context | ✅ Present from the moment you open the harness |
| Phase transitions → rules file update | ✅ Regenerated within ~1s of `.skillsmith/phase` changing |
| Contract writes → skill injection | ✅ Regenerated within ~1s of contract write |
| System skill prose | ✅ Included as advisory text in the rules file |

## What's degraded on Tier 3

| Feature | Status | Why |
|---|---|---|
| Per-turn hook firing | ❌ Not available | Harness has no hook mechanism |
| System skill enforcement (gates) | ⚠️ Advisory only | No PreToolUse hook to block tool calls |
| Mid-session updates without reload | ⚠️ Harness-dependent | Some harnesses need workspace reload |
| Semantic gate evaluation (Qwen) | ⚠️ Falls back to `UNKNOWN` | Classifier invoked per-turn; no hook to fire it |
| Automatic phase transition detection | ⚠️ Manual via `skillsmith phase set <name>` | Signal keywords not checked per-turn |

**System skills as advisory text** means commit-safety, secret-handling, and similar system
skills are printed in the rules file, but the harness won't gate a `git commit` on them.
The paid LLM reads the advisory and can follow it, but nothing enforces it. If you need
enforcement, use a Tier 1 harness.

## Operating the sidecar

Start the watcher:

```bash
# Foreground (pair with tmux or screen)
skillsmith watch start --harness cursor

# Check status
skillsmith watch status

# Stop
skillsmith watch stop
```

**Recommended**: run under your process manager of choice.

### systemd (Linux)

```ini
# ~/.config/systemd/user/skillsmith-watch.service
[Unit]
Description=Skillsmith watcher sidecar

[Service]
ExecStart=skillsmith watch start --harness cursor
Restart=on-failure
WorkingDirectory=%h/dev/your-project

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now skillsmith-watch
```

### launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.skillsmith.watch.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.skillsmith.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/skillsmith</string>
    <string>watch</string>
    <string>start</string>
    <string>--harness</string>
    <string>cursor</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/you/dev/your-project</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.skillsmith.watch.plist
```

## Diagnosing stale rules files

```bash
# Check watcher status
skillsmith watch status

# Force regeneration by touching the phase file
touch .skillsmith/phase

# View watcher log
cat ~/.skillsmith/watch/default.log

# Manually trigger a regeneration for a specific harness
skillsmith signal evaluate-phase  # emits context to stdout
```

## Per-harness reload behavior

| Harness | When rules update takes effect |
|---|---|
| Cursor | On file save in most cases; immediate in many setups |
| Windsurf | On workspace save/reload |
| GitHub Copilot (VS Code) | Requires VS Code window reload (`Ctrl+Shift+P → Reload Window`) |
| Cline | On task start; may require reload for mid-session |
| Gemini CLI | New session required |
| Aider | `--read` file changes picked up on next `/read` or restart |

## Choosing a Tier 1 harness instead

If the above limitations are too restrictive, Claude Code is the reference Tier 1 harness:

```bash
skillsmith setup --harness claude-code
skillsmith wire claude-code
```

Continue.dev works for VS Code and JetBrains users who prefer their existing IDE:

```bash
skillsmith wire continue-closed  # system message + custom command
```

Both give you per-turn hook firing, semantic gate evaluation, and enforced system skills.
