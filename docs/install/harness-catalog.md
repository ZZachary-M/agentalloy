# Install — Harness Catalog

Companion to [`spec.md`](./spec.md) and [`contracts.md`](./contracts.md). Authoritative for per-harness file paths, the actual injection content, and edge cases.

Each section is a single harness. Implementers should treat the **Injected content** code blocks as canonical templates — these go directly into `src/skillsmith/install/harness_templates/<harness>.md`. The `{port}` placeholder is the only template variable, substituted from the configured port (default 47950).

All injections use the standard sentinel pair:

```
<!-- BEGIN skillsmith install -->
... content ...
<!-- END skillsmith install -->
```

Sentinels are markdown comments where the harness format supports them (Claude Code, Gemini CLI, Cursor's `.cursorrules`). Where it doesn't (JSON configs), the equivalent is documented per-harness below.

---

## Claude Code

**File path:** `<repo-root>/CLAUDE.md` (project-scoped, NOT global). Created if missing; sentinel block inserted/replaced if file exists.

**Why project-scoped:** the skillsmith integration is per-project (the `skillsmith` service points at a specific port and serves a specific corpus). Injecting into `~/.claude/CLAUDE.md` would force every Claude Code session everywhere to load the instructions — unwanted overhead.

**Edge cases:**
- If user has a project-scoped `CLAUDE.md` already, append the sentinel block at the end (separated by a blank line). Do not modify existing content.
- If the file uses Windows line endings (CRLF), preserve them. Match the existing file's line ending style.

**Injected content:**

```markdown
<!-- BEGIN skillsmith install -->
## Skill API access

A local skillsmith service is running at `http://localhost:{port}` exposing a curated corpus of engineering skills.

When you need procedural guidance on a coding task — testing patterns, error handling, deployment, observability, etc. — query the service:

```bash
curl -s -X POST http://localhost:{port}/compose \
  -H 'Content-Type: application/json' \
  -d '{"task": "<describe the task in one sentence>", "phase": "build"}'
```

Phases: `spec`, `design`, `build`, `qa`, `ops`. Pass `phase` matching the lifecycle stage of the task.

The response is a JSON object with `output` (concatenated raw fragments to inject into your context) and `source_skills` (which skills contributed). Read the `output` field and incorporate the guidance into your reasoning before generating code.

Health check: `curl -s http://localhost:{port}/health` should return `{"status":"ok"}`. If it doesn't, run `python -m skillsmith.install doctor` from the skillsmith repo to diagnose.
<!-- END skillsmith install -->
```

---

## Gemini CLI

**File path:** `<repo-root>/GEMINI.md` (project-scoped).

**Edge cases:** identical structure to Claude Code. Gemini CLI auto-loads project-scoped `GEMINI.md` the same way Claude Code loads `CLAUDE.md`.

**Injected content:** structurally identical to Claude Code's, with `## Skill API access` heading. Reuse the same template with `harness_name=Gemini` substituted in the body where it says "Read the `output` field and incorporate the guidance into your reasoning."

```markdown
<!-- BEGIN skillsmith install -->
## Skill API access

A local skillsmith service is running at `http://localhost:{port}` exposing a curated corpus of engineering skills.

When you need procedural guidance on a coding task — testing patterns, error handling, deployment, observability, etc. — use your shell tool to query the service:

```bash
curl -s -X POST http://localhost:{port}/compose \
  -H 'Content-Type: application/json' \
  -d '{"task": "<describe the task in one sentence>", "phase": "build"}'
```

Phases: `spec`, `design`, `build`, `qa`, `ops`. Pass `phase` matching the lifecycle stage of the task.

The response is JSON with `output` (concatenated raw fragments) and `source_skills`. Read `output` and apply the guidance before generating code.

Health check: `curl -s http://localhost:{port}/health` returns `{"status":"ok"}`. If not, run `python -m skillsmith.install doctor` from the skillsmith repo.
<!-- END skillsmith install -->
```

---

## Cursor

**File path:** `<repo-root>/.cursor/rules/skillsmith.mdc` (preferred — Cursor's modern rules format), with fallback to `<repo-root>/.cursorrules` if the modern format isn't supported by the user's Cursor version.

**Detection:** if `<repo-root>/.cursor/` directory exists, use the modern path. Otherwise create `<repo-root>/.cursorrules`.

**Edge cases:**
- `.cursor/rules/skillsmith.mdc` is a dedicated file we own — no sentinel needed for the modern path; the entire file is ours and `uninstall` deletes it.
- `.cursorrules` (legacy) is shared with the user's other rules — sentinel-bounded injection required.

**Injected content (modern `.mdc` format):**

```markdown
---
description: Use when you need procedural guidance on a coding task (testing, error handling, deployment, observability)
globs: ["**/*"]
---

# Skill API access

A local skillsmith service is running at `http://localhost:{port}` exposing a curated corpus of engineering skills.

When you need procedural guidance:

```bash
curl -s -X POST http://localhost:{port}/compose \
  -H 'Content-Type: application/json' \
  -d '{"task": "<task description>", "phase": "build"}'
```

Phases: `spec`, `design`, `build`, `qa`, `ops`.

Health check: `curl -s http://localhost:{port}/health` returns `{"status":"ok"}`. If not, run `python -m skillsmith.install doctor` from the skillsmith repo.
```

**Injected content (legacy `.cursorrules`):** same as Claude Code's CLAUDE.md template, with markdown comments as sentinels.

---

## Continue.dev (closed model)

**File path:** `<repo-root>/.continuerc.json` (project-scoped Continue config) OR `~/.continue/config.json` (user-scoped). Default: project-scoped.

**Format:** JSON, so markdown sentinels don't apply. Use a marker key inside the JSON:

```json
{
  "models": [...],
  "_skillsmith_install_marker": {
    "managed_by": "skillsmith install",
    "begin": "skillsmith:begin",
    "end": "skillsmith:end",
    "added_paths": [
      "systemMessage.skillsmith_block",
      "customCommands.skillsmith"
    ]
  },
  "systemMessage": "...existing user content...\n\n<!-- skillsmith:begin -->\n... our injection ...\n<!-- skillsmith:end -->",
  "customCommands": [
    {
      "name": "skill",
      "description": "Query the local skillsmith for guidance on a coding task",
      "prompt": "Run: curl -s -X POST http://localhost:{port}/compose -H 'Content-Type: application/json' -d '{{\"task\":\"{input}\",\"phase\":\"build\"}}'"
    }
  ]
}
```

**`uninstall` behavior for JSON configs:**
1. Read `_skillsmith_install_marker.added_paths` to know which JSON paths were modified.
2. For string fields with sentinel comments, remove the sentinel-bounded segment.
3. For array fields where we added items, remove items matching our marker name.
4. Remove `_skillsmith_install_marker` itself.

**Injected `systemMessage` block:**

```
<!-- skillsmith:begin -->
A local skillsmith service runs at http://localhost:{port}. When the user asks for procedural guidance on testing, error handling, deployment, or similar topics, you may invoke the `/skill` custom command to fetch relevant skill fragments before answering.
<!-- skillsmith:end -->
```

---

## Continue.dev (local model)

**File path:** same as closed-model variant (`.continuerc.json`).

**Difference:** no system message injection. Just the custom command. Local models get the cheap path — minimal context overhead.

```json
{
  "_skillsmith_install_marker": {
    "managed_by": "skillsmith install",
    "added_paths": ["customCommands.skillsmith"]
  },
  "customCommands": [
    {
      "name": "skill",
      "description": "Query the local skillsmith for task guidance",
      "prompt": "curl -s -X POST http://localhost:{port}/compose -H 'Content-Type: application/json' -d '{{\"task\":\"{input}\",\"phase\":\"build\"}}'"
    }
  ]
}
```

The local model decides on its own when to invoke `/skill`; we don't bias it via system message.

---

## OpenCode (with Qwen or other local LLM)

**File path:** OpenCode reads system prompts from a config file. Path varies by version. Implementer's research action: confirm current OpenCode config layout.

**Provisional path:** `<repo-root>/.opencode/system-prompt.md` (TBD pending OpenCode docs verification).

**Integration vector:** system-prompt snippet, ~50 tokens. Minimal because the local LLM is loading this every turn.

**Injected content:**

```markdown
<!-- skillsmith:begin -->
For procedural guidance, POST to http://localhost:{port}/compose with `{"task": "...", "phase": "build|spec|design|qa|ops"}`. Read the `output` field.
<!-- skillsmith:end -->
```

---

## Aider (with local LLM)

**File path:** `<repo-root>/.aider.conf.yml`. Aider supports `read` (auto-loaded files at start) which we use to load a sentinel-bounded skill instructions file.

**Implementation:** create `<repo-root>/.skillsmith-aider-instructions.md` (a dedicated file we own) and add it to `.aider.conf.yml`'s `read:` list.

```yaml
# .aider.conf.yml
read:
  - .skillsmith-aider-instructions.md  # added by skillsmith install
```

The `.skillsmith-aider-instructions.md` file is fully ours (no sentinels needed; `uninstall` deletes it). The line in `.aider.conf.yml` is sentinel-bounded:

```yaml
# <!-- BEGIN skillsmith install -->
read:
  - .skillsmith-aider-instructions.md
# <!-- END skillsmith install -->
```

**Edge case:** if `.aider.conf.yml` already has a `read:` block, we append to it (with sentinel comments around our entry). YAML merging is deterministic via Python's `ruamel.yaml`.

**Content of `.skillsmith-aider-instructions.md`:** same as the OpenCode local-LLM snippet (~50 tokens).

---

## Cline (with local LLM)

**File path:** Cline supports custom instructions via VSCode settings: `cline.customInstructions`. This is harder to inject programmatically because VSCode `settings.json` is shared across the user's projects and editing it touches a non-skillsmith file.

**Provisional approach:** Cline also supports a `.clinerules` file at the repo root. Use that.

**File path:** `<repo-root>/.clinerules`.

**Injected content:** same template as Cursor's `.cursorrules`.

```
<!-- BEGIN skillsmith install -->
# Skill API access

A local skillsmith service runs at http://localhost:{port}. For procedural guidance on coding tasks (testing, error handling, deployment, observability), POST to /compose with `{"task":"...", "phase":"build|spec|design|qa|ops"}`. Read the `output` field.
<!-- END skillsmith install -->
```

---

## MCP fallback (any harness)

**Triggered by:** `wire-harness --harness <name> --mcp-fallback`, OR by user choice when the runbook offers the strict-tools alternative.

**File path varies by harness:**

| Harness | MCP servers config path |
|---|---|
| Claude Code | `~/.claude/mcp_servers.json` |
| Cursor | `<repo-root>/.cursor/mcp.json` |
| Continue.dev | inside `.continuerc.json` under `mcpServers` |
| Gemini CLI | TBD pending Gemini MCP support docs |

**MCP server entry:**

```json
{
  "mcpServers": {
    "skillsmith": {
      "command": "python",
      "args": ["-m", "skillsmith.install.mcp_server", "--port", "{port}"],
      "env": {}
    }
  }
}
```

The MCP server module (`src/skillsmith/install/mcp_server.py`) is a separate component, NOT part of the install CLI proper. It exposes one tool:

```json
{
  "name": "get_skill_for",
  "description": "Fetch composed skill fragments for a given task and phase",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task": {"type": "string", "description": "One-sentence task description"},
      "phase": {"type": "string", "enum": ["spec","design","build","qa","ops"]}
    },
    "required": ["task"]
  }
}
```

The implementation forwards to the local `/compose` endpoint and returns the `output` field as the tool result.

**Why this is the fallback:** ~400 tokens of always-loaded tool schema vs ~200 for markdown injection. The win is structured tool-call validation and the harness's per-tool approval UX.

---

## Harness selection summary

The runbook asks the user: "What harness are you using?" and presents this list:

1. **Claude Code** → CLAUDE.md injection
2. **Gemini CLI** → GEMINI.md injection
3. **Cursor** → `.cursor/rules/skillsmith.mdc` or `.cursorrules`
4. **Continue.dev (with Anthropic / OpenAI / other cloud model)** → `.continuerc.json` system message + custom command
5. **Continue.dev (with a local LLM)** → `.continuerc.json` custom command only
6. **OpenCode** → `.opencode/system-prompt.md` snippet (pending OpenCode docs)
7. **Aider** → `.aider.conf.yml` + `.skillsmith-aider-instructions.md`
8. **Cline** → `.clinerules`
9. **Other / I'll wire it manually** → emit a generic snippet to stdout, no file injection
10. **Use MCP server instead** → MCP fallback for whichever harness in 1–8 the user picks (compound choice)

The CLI flag `--harness <name>` takes one of: `claude-code`, `gemini-cli`, `cursor`, `continue-closed`, `continue-local`, `opencode`, `aider`, `cline`, `manual`. For the strict-tools MCP fallback, pass `--mcp-fallback` with one of the supported harnesses (claude-code, cursor, continue-closed, continue-local).

---

## Edge cases applicable across all harnesses

**Existing skillsmith install:** `wire-harness` is idempotent. If the file already contains a sentinel-bounded block, replace it. Don't append.

**Sentinel block tampered:** if the content sha256 in `install-state.json` doesn't match what's between sentinels, `wire-harness` warns and prompts for confirmation before overwriting. `uninstall` warns and skips unless `--force`.

**File doesn't exist:** create it with our injection at the top. Sentinels still wrap our content so future re-runs work the same way.

**File is read-only:** error with remediation hint.

**File is in a git worktree where `.gitignore` would catch it (e.g., `.env`):** allow but log. We're not committing these.

**Windows path separators:** all paths in `install-state.json` use forward slashes. Implementer normalizes on read/write.

**Unicode in user paths:** preserve verbatim. Don't ASCII-fold home directories.
