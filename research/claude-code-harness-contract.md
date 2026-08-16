# Claude Code Harness Contract — Migration from kiro-cli

**Author:** Nathan Shapiro  
**Date:** 2026-08-16  
**Purpose:** Precise, documented contract for porting Zikaron hook integration from kiro-cli to Claude Code.

---

## Status Legend

- **DOCUMENTED**: Extracted directly from official Claude Code docs (https://code.claude.com/docs/)
- **INFERRED**: Derived from context but not explicitly stated; probe before building
- **NOT FOUND**: Explicitly not covered in available docs; will need experimental verification

---

## 1. Hook Events — Complete List

**Status:** DOCUMENTED (via `hooks.md` reference)

Claude Code supports the following hook events. For each, the **firing timing** is documented:

| Event | Fires When | Can Block | Can Inject Context |
|-------|-----------|-----------|-------------------|
| `SessionStart` | Session begins or resumes | ❌ No | ✅ Yes (stdout) |
| `Setup` | Starting with `--init-only`, `--init`, or `--maintenance` in `-p` mode | ❌ No | ❓ Undocumented |
| `UserPromptSubmit` | **Before** Claude processes a user prompt | ✅ Yes (exit 2) | ✅ Yes (stdout) |
| `UserPromptExpansion` | When a user-typed command expands into a prompt | ❓ Undocumented | ❓ Undocumented |
| `PreToolUse` | **Before** a tool call executes | ✅ Yes (exit 2) | ❓ Undocumented |
| `PermissionRequest` | When a tool call needs a permission decision | ❓ Undocumented | ❓ Undocumented |
| `PermissionDenied` | When auto mode denies a tool call | ❌ No | ❓ Undocumented |
| `PostToolUse` | **After** a tool call succeeds | ❌ No (already executed) | ✅ Yes (stderr via exit 2 only) |
| `PostToolUseFailure` | **After** a tool call fails | ❌ No | ✅ Yes (stderr via exit 2) |
| `PostToolBatch` | After a full batch of parallel tool calls resolves | ❓ Undocumented | ❓ Undocumented |
| `PreCompact` | **Before** context compaction | ❓ Undocumented | ❓ Undocumented |
| `PostCompact` | **After** context compaction completes | ❓ Undocumented | ❓ Undocumented |
| `SubagentStart` | When a subagent is spawned | ❌ No | ❓ Undocumented |
| `SubagentStop` | When a subagent finishes | ❌ No | ❓ Undocumented |
| `Stop` | When Claude finishes responding | ✅ Yes (exit 2) | ❓ Undocumented |
| `StopFailure` | When the turn ends due to an API error | ❌ No | ❓ Undocumented |
| `Notification` | When Claude Code sends a notification | ❌ No | ❌ No |
| `MessageDisplay` | While assistant message text is displayed | ❓ Undocumented | ❓ Undocumented |
| `TaskCreated` | When a task is being created | ❓ Undocumented | ❓ Undocumented |
| `TaskCompleted` | When a task is being marked as completed | ❓ Undocumented | ❓ Undocumented |
| `TeammateIdle` | When an agent team teammate is about to go idle | ❓ Undocumented | ❓ Undocumented |
| `InstructionsLoaded` | When a CLAUDE.md or `.claude/rules/*.md` file is loaded | ❓ Undocumented | ❓ Undocumented |
| `ConfigChange` | When a configuration file changes during a session | ❓ Undocumented | ❓ Undocumented |
| `CwdChanged` | When the working directory changes | ❓ Undocumented | ❓ Undocumented |
| `DirectoryAdded` | When a working directory is added mid-session | ❓ Undocumented | ❓ Undocumented |
| `FileChanged` | When a watched file changes on disk | ❓ Undocumented | ❓ Undocumented |
| `WorktreeCreate` | When a worktree is being created | ❓ Undocumented | ❓ Undocumented |
| `WorktreeRemove` | When a worktree is being removed | ❓ Undocumented | ❓ Undocumented |
| `Elicitation` | When an MCP server requests user input | ❓ Undocumented | ❓ Undocumented |
| `ElicitationResult` | After a user responds to an MCP elicitation | ❓ Undocumented | ❓ Undocumented |
| `SessionEnd` | When a session terminates | ❌ No | ❓ Undocumented |

**Key differences from kiro-cli:**
- Replaced `agentSpawn` with `SessionStart` + `SubagentStart`
- Replaced `userPromptSubmit` with `UserPromptSubmit` (capitalized)
- Added `PreCompact`/`PostCompact` (kiro-cli only had manual consolidation)
- Added `SubagentStart`/`SubagentStop` (kiro-cli scoped hooks per agent in config)
- Added `PostToolUseFailure`, `PostToolBatch`, `Stop`, `StopFailure`

---

## 2. Hook Input Payload — JSON Schema

**Status:** DOCUMENTED for `SessionStart` and `UserPromptSubmit`; INFERRED for others

### Common Fields (All Events)

```json
{
  "session_id": "string (UUID format, described as 'abc123' in docs)",
  "prompt_id": "string (UUID, absent until first user input)",
  "transcript_path": "string (absolute path to transcript JSONL)",
  "cwd": "string (current working directory)",
  "permission_mode": "string (default|plan|acceptEdits|auto|dontAsk|bypassPermissions)",
  "hook_event_name": "string (event name)",
  "effort": {
    "level": "string (low|medium|high|xhigh|max)"
  },
  "agent_type": "string (subagent name, only in subagent context)",
  "agent_id": "string (only in subagent context, UNDOCUMENTED relationship to agent_type)"
}
```

### SessionStart — Complete Schema

**Status:** DOCUMENTED

```json
{
  "session_id": "abc123",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "hook_event_name": "SessionStart",
  "model": "string (optional, not guaranteed)"
}
```

**Key facts:**
- No `permission_mode` field on `SessionStart`
- `model` field is **optional and not guaranteed** — do not rely on it
- No `prompt_id` (no user input yet)
- No `agent_type`/`agent_id` (not in subagent context)

### UserPromptSubmit — Complete Schema

**Status:** DOCUMENTED

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "string (the user's prompt text)"
}
```

**Key facts:**
- Field is **`prompt`**, not `user_input` (this is the kiro-cli breakage mentioned in FINDINGS.md)
- `session_id`, `cwd`, `transcript_path` are present
- No `model` field (that is `SessionStart`-only)
- No `agent_type` (documented only for tool events)

### SubagentStart — Payload Distinction

**Status:** DOCUMENTED

```json
{
  "session_id": "abc123",
  "agent_type": "code-reviewer",
  "hook_event_name": "SubagentStart"
  // other common fields may be present
}
```

**Key facts:**
- Subagent is identified by **`agent_type`** field, which matches the subagent's `name` frontmatter
- Hook can distinguish main session vs. subagent by checking `agent_type`

### Tool Events (PreToolUse, PostToolUse, etc.) — Example

**Status:** DOCUMENTED (example given; full schema for each event INFERRED)

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "cwd": "/home/user/my-project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "effort": {
    "level": "medium"
  },
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm test",
    "description": "Run test suite",
    "timeout": 120000,
    "run_in_background": false
  },
  "tool_use_id": "toolu_01ABC123..."
}
```

**Known gaps:**
- Schema for `PostToolUse`, `PostToolUseFailure`, `PostToolBatch` not explicitly documented (inferred from "tool already executed" behavior)
- Schema for `PreCompact`/`PostCompact` not found in docs

---

## 3. Hook Output → Model Context

**Status:** DOCUMENTED for basic behavior; PARTIALLY DOCUMENTED for placement

### Exit Code Semantics

**Status:** DOCUMENTED

| Exit Code | Behavior |
|-----------|----------|
| **0** | Success. stdout is parsed and injected into context (event-dependent; see below). |
| **2** | **Blocking error** on applicable events (`PreToolUse`, `UserPromptSubmit`, `Stop`, and others). stderr is shown to the user and the action is blocked. |
| **Other** | Non-blocking error. stdout parsed if valid JSON with schema validation; otherwise logged. |

### stdout Handling by Event

**Status:** DOCUMENTED

**First character rule (ignoring leading whitespace):**
- Starts with `{`: Parsed as JSON
- Any other character: Treated as **plain text**

**Destination by event:**

| Event | Stdout Destination |
|-------|------------------|
| `UserPromptSubmit` | **Injected as context Claude can see** |
| `SessionStart` | **Injected as context Claude can see** |
| `UserPromptExpansion` | Injected as context (inferred, not confirmed) |
| `PostToolUse` | Debug log only (cannot inject context on success) |
| `PostToolUseFailure` | Debug log only, **except stderr via exit 2 reaches Claude** |
| `Stop` | **Debug log only** (confusing: docs show `Stop` can return `{"decision":"block"}` but say stdout goes to debug log) |
| `PreToolUse` | Unknown (not explicitly stated) |
| Most other events | Debug log only |

**Output size cap:**
- **10,000 characters** for hook output on most events
- Exceeding limit saves to file with preview and path shown
- **Silent truncation occurs** if overflow

**JSON schema (when hook returns JSON):**

```json
{
  "continue": true,
  "stopReason": "optional message when continue is false",
  "systemMessage": "warning message shown to user",
  "terminalSequence": "escape sequence for notifications",
  "hookSpecificOutput": {
    "hookEventName": "event name",
    "permissionDecision": "allow|deny|escalate",
    "permissionDecisionReason": "explanation",
    "additionalContext": "context for Claude",
    "updatedInput": {},
    "retry": true
  }
}
```

### Context Placement Relative to User Message

**Status:** INFERRED (NOT EXPLICITLY DOCUMENTED)

From FINDINGS.md, kiro-cli placed surfaced memories **before** the user message in the same turn. FINDINGS.md notes: "That placement is *early*, which contradicts `~/Memory`'s 'place surfaced memories late' lesson; **we cannot choose**."

**For Claude Code:** The placement of hook-injected context is NOT explicitly documented. The `hooks.md` reference says "stdout added as context Claude can see" but does not state where in the turn order this appears relative to the user message.

**Action needed:** Probe experimentally to confirm placement (before or after user message in context window).

---

## 4. Timeouts

**Status:** DOCUMENTED

| Hook Type | Default Timeout | Override on Specific Events |
|-----------|-----------------|---------------------------|
| `command` | **600 seconds** | `UserPromptSubmit`: 30s, `MessageDisplay`: 10s |
| `http` | **600 seconds** | `UserPromptSubmit`: 30s, `MessageDisplay`: 10s |
| `mcp_tool` | **600 seconds** | `UserPromptSubmit`: 30s, `MessageDisplay`: 10s |
| `prompt` | **30 seconds** | (No event-specific overrides documented) |
| `agent` | **60 seconds** | (No event-specific overrides documented) |

**Special cases:**
- `SessionEnd` hooks share a **1.5-second budget**; if you set a longer `timeout`, the budget is raised to match, up to **60 seconds**
- Timed-out hooks **do not block** (except in Agent SDK callbacks)

**Schema in settings.json:**

**Status:** INFERRED (schema location confirmed, exact keys NOT explicitly shown)

Hooks are configured under `settings.json` → `hooks` → per-event entry → `timeout` field. Expected unit: **milliseconds** (inferred from MCP_TIMEOUT env var being milliseconds). Expected format: `{ "timeout": 30000 }` or similar.

---

## 5. Environment Variables in Hook and MCP Processes

**Status:** DOCUMENTED for some; INCOMPLETE for others

### Hook Processes (spawned from `command` hook type)

**Documented env vars:**

| Var | Value | Purpose |
|-----|-------|---------|
| `CLAUDECODE` | `"1"` | Detect when script is running inside Claude Code subprocess |
| `CLAUDE_CODE_BRIDGE_SESSION_ID` | `session_<uuid>` (matches `claude.ai/code` URL) | Link back to session **only if Remote Control is active**; removed when connection ends |
| `CLAUDE_CODE_REMOTE_SESSION_ID` | — | Use in cloud sessions instead of `CLAUDE_CODE_BRIDGE_SESSION_ID` |
| `CLAUDE_CODE_CHILD_SESSION` | — | Check if spawned directly by tool/hook vs. inside MCP server |

**Critical gap:** The `session_id` from the hook's **stdin JSON payload** is the load-bearing session identifier shared between hook and MCP. **No documented environment variable carries this session ID** to the hook process. The hook must read stdin to get it.

**Undocumented but inferred:**
- Hooks inherit the parent process's `PATH`, `HOME`, shell env vars
- Tools/hooks inherit `ANTHROPIC_API_KEY` (for downstream tool calls)
- Hooks likely run in the session's `cwd` (not verified; probe this)

**Not found in docs:**
- `CLAUDE_PROJECT_DIR` is mentioned in FINDINGS.md as a Claude Code env var, but NOT documented in env-vars.md
- Whether `KIRO_SESSION_ID` has a Claude Code equivalent (it does not seem to exist)

### MCP Server Processes (stdio servers spawned by Claude Code)

**Status:** DOCUMENTED for some; LARGELY UNKNOWN for context

**Documented:**
- `CLAUDECODE` = `"1"` (same as hooks)
- Inherit provider authentication (AWS_*, gcloud config, proxies) — these pass through

**Unknown/Not documented:**
- Does the MCP server process receive the `session_id` by any means (env var, stdin, or not at all)?
- What is the MCP server's working directory?
- Does it inherit the session's `cwd` or run in the project root or user home?
- Are there any Claude Code session identifiers passed to the MCP server?

**Critical question for Zikaron:** If the hook and MCP server both need to refer to the same session, there must be a shared session identifier. The hook payload carries `session_id`, but **there is no documented mechanism for the MCP server to learn it**.

---

## 6. MCP Server Configuration

**Status:** DOCUMENTED (for `stdio` and `http` types; Agent SDK coverage separate)

### Where Configured

**File paths and scopes:**

| Scope | File | How to Add |
|-------|------|-----------|
| **Local** (this project only) | `.claude/.claude.json` (inferred) or `~/.claude.json` project entry | `claude mcp add --scope local` or edit `.mcp.json` |
| **Project** (shared, checked in) | `.mcp.json` in project root | `claude mcp add --scope project` or edit `.mcp.json` directly |
| **User** (all projects) | `~/.claude.json` top-level `mcpServers` key | `claude mcp add --scope user` |

**Primary source:** Edit `.mcp.json` directly for project-scoped servers (checked in, shared with team).

### `.mcp.json` Schema

**Status:** DOCUMENTED

```json
{
  "mcpServers": {
    "server-name": {
      "type": "stdio|http|sse|websocket",
      "command": "string (stdio only)",
      "args": ["array", "of", "arguments (stdio only)"],
      "url": "string (http only)",
      "env": {
        "KEY": "value"
      }
    }
  }
}
```

**Supported transports:**
- **`stdio`** (local process): `type`, `command`, `args`
- **`http`** (remote hosted): `type`, `url`
- **`sse`** (server-sent events): NOT documented in the quickstart; name only
- **`websocket`**: NOT documented in the quickstart; name only

### Tool Naming and Allowlisting in Permissions

**Status:** INFERRED (naming confirmed; allowlist format NOT explicitly shown)

**Tool naming convention:** `mcp__<server-name>__<tool-name>`

Example: For server `playwright` with tool `browser_navigate`, the full name is `mcp__playwright__browser_navigate`.

**How to allowlist in settings.json permissions:**

**Status:** INFERRED (not explicitly documented in MCP quickstart)

Expected format (educated guess based on Bash and other tool permissions):

```json
{
  "permissions": {
    "mcp": {
      "mcp__playwright__browser_navigate": true
    }
  }
}
```

Or possibly:
```json
{
  "permissions": {
    "mcp__playwright__browser_navigate": true
  }
}
```

**Action needed:** Probe experimentally to confirm the exact permission key format.

### Per-Server Pre-approval

**Status:** NOT DOCUMENTED

The docs mention "Pending approval" status for project-scoped servers (need user to approve once), but do NOT cover:
- Per-tool pre-approval (allow specific tools without prompts)
- Per-server allowlists in subagent frontmatter
- Whether `tools:` frontmatter can restrict to only one MCP server's tools (e.g., `tools: ["mcp__playwright__*"]`)

---

## 7. Subagents — Frontmatter Schema

**Status:** DOCUMENTED (complete schema provided)

### Complete Frontmatter Schema

**Location:** `.claude/agents/*.md`

```yaml
---
name: "identifier-lowercase-with-hyphens"
description: "When Claude should delegate to this subagent"
tools: ["Read", "Write", "Bash", "Glob"]          # optional; inherits all if omitted
disallowedTools: ["Bash"]                          # optional; remove from inherited
model: "sonnet|opus|haiku|fable|inherit|full-id"   # optional; defaults to inherit
permissionMode: "default|acceptEdits|auto|dontAsk|bypassPermissions|plan|manual"
maxTurns: 10                                       # optional; max agentic turns
skills: ["skill-name"]                             # optional; preload skill content
mcpServers: ["server-name"]                        # optional; or inline definitions
hooks: { }                                         # optional; lifecycle hooks (see below)
memory: "user|project|local"                       # optional; persistent cross-session memory
background: false                                  # optional; force foreground even if Claude wants background
effort: "low|medium|high|xhigh|max"               # optional; override session effort
isolation: "worktree"                              # optional; run in isolated git worktree
color: "red|blue|green|yellow|purple|orange|pink|cyan"
initialPrompt: "string"                            # optional; auto-submit as first turn
---

Your detailed subagent instructions here...
```

**Key constraints:**
- **`name` cannot contain `:`** (reserved for `plugin:agent` scoped identifiers)
- `tools: ["Agent(code-reviewer)"]` syntax restricts spawnable subagents
- Plugin subagents **ignore** `hooks`, `mcpServers`, `permissionMode`

### Hooks in Subagent Frontmatter

**Status:** DOCUMENTED

```yaml
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate.sh $TOOL_INPUT"
  PostToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "./scripts/run-linter.sh"
  Stop:
    - hooks:
      - type: command
        command: "./scripts/cleanup.sh"
```

**Scope of subagent hooks:**
- Run **only while that subagent is active**
- Cannot be scoped to avoid running for certain subagents (all-or-nothing within a subagent)
- Converted to `SubagentStop` at runtime for `Stop` event

**Session-level hooks for subagent lifecycle:**

In main `settings.json`:
```json
{
  "hooks": {
    "SubagentStart": [
      {
        "matcher": "code-reviewer",
        "hooks": [
          { "type": "command", "command": "./setup.sh" }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          { "type": "command", "command": "./cleanup.sh" }
        ]
      }
    ]
  }
}
```

---

## 8. Settings.json — Hooks Configuration Schema

**Status:** DOCUMENTED (partial); COMPLETE SCHEMA NOT EXPLICITLY SHOWN

### Hooks Configuration Location in settings.json

**Documented structure (from hooks.md):**

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "regex or tool name",
        "hooks": [
          {
            "type": "command|http|prompt|agent",
            "command": "shell command",
            "timeout": 30000,
            "// other fields depending on type"
          }
        ]
      }
    ]
  }
}
```

### Matcher Semantics

**Status:** INFERRED (examples given; formal definition NOT explicit)

- **For tool events** (`PreToolUse`, `PostToolUse`): `matcher` is a regex matching the tool name (e.g., `"Bash"`, `"Edit|Write"`)
- **For other events**: `matcher` may be optional or take different values (e.g., subagent `name` for `SubagentStart`)
- **No matcher:** hook always fires for that event

### Hook Types

**Documented types:**
- `command` — shell command (details: `command` field)
- `http` — HTTP POST request (details: likely `url`, `method`, `body`)
- `prompt` — Claude model evaluation (details: likely `prompt` field)
- `agent` — Delegate to a subagent (details: not shown)
- `mcp_tool` — Call an MCP tool (mentioned in docs but not detailed)

### Settings File Merge Behavior

**Status:** DOCUMENTED (for some settings; hook merge specifics NOT fully clear)

- **User** (`~/.claude/settings.json`) applied first (lowest priority)
- **Project** (`.claude/settings.json`) overrides user
- **Local** (`.claude/settings.local.json`) overrides project (highest priority)

**For arrays** (like `hooks`): **Arrays merge** (not replace). The hook list from all three files is combined.

**Precedence for conflicting keys:** Not explicitly stated for hooks; assumed last-wins or merge-all.

---

## 9. Model IDs and Fallback Behavior

**Status:** DOCUMENTED (for aliases and models; fallback behavior PARTIALLY documented)

### Available Models and Aliases

**Status:** DOCUMENTED (excerpt from model-config.md)

| Alias | Behavior |
|-------|----------|
| `sonnet` | Latest Sonnet model (currently Claude Sonnet 5) |
| `opus` | Latest Opus model (if available) |
| `haiku` | Latest Haiku model (Haiku 4.5 or Haiku 3.5) |
| `fable` | Fable 5 or Fable 3 (depending on availability) |
| `default` | System default (controlled by admin) |

### Unknown/Undocumented Model

**Status:** PARTIALLY DOCUMENTED

For **subagent frontmatter `model:`** field:
- **Error behavior NOT documented** — does it error on unknown model, or silent fallback?
- Inference: Likely errors or falls back to `inherit` (the default), but unconfirmed

**For Claude Code CLI:**
- `ANTHROPIC_MODEL` env var can pin a model
- Unknown model names are likely caught at startup

**Action needed:** Test a subagent with `model: "unknown-model-xyz"` to verify behavior.

---

## 10. Sessions — Stability Across Lifecycle Events

**Status:** DOCUMENTED (for resume); INFERRED for compact

### Session ID Stability

**Across `--resume`:**
- ✅ **DOCUMENTED:** `session_id` is restored and stable. Same conversation, same session ID.

**Across `/compact`:**
- ❓ **NOT DOCUMENTED.** The sessions.md page covers `/compact` (replace history with summary) but does NOT state whether `session_id` changes after compaction.
- Inference: Likely remains the same (cosmetic operation on history, not session boundary), but UNCONFIRMED.

**Across `/clear`:**
- ✅ **DOCUMENTED:** Creates a new session (new `session_id`). Previous conversation is saved and resumable separately.

### Visibility to Hook and MCP Server

**Status:** DOCUMENTED for hook; NOT DOCUMENTED for MCP server

**In hook process:**
- ✅ Hook receives `session_id` in stdin JSON payload
- ✅ `CLAUDE_CODE_BRIDGE_SESSION_ID` env var carries the session ID (only if Remote Control is active)

**In MCP server process:**
- ❌ **NOT DOCUMENTED.** No env var documented that carries `session_id` to an MCP stdio server
- ❌ No documented mechanism for MCP server to learn the session ID
- ❓ Unclear whether the same MCP server process is reused across multiple user turns in a session, or forked per turn

**Critical question for linked sessions (Zikaron's need):**
- Hook and MCP server need to agree on a session ID to coordinate (e.g., "which session's memory should I search?")
- **There is no documented mechanism for MCP server to learn the session ID**
- **This is the Harness section's "No session-id environment variable exists" point in FINDINGS.md**

---

## Summary of Load-Bearing Unknowns

These are the critical unknowns that will break Zikaron if not verified:

1. **Session ID for MCP servers:** How does an MCP stdio server learn which session it is operating in?
   - Hypothesis: Either (a) it doesn't, and each invocation is stateless, or (b) the session ID is passed via stdin, env var, or command args.
   - Impact: Blocks linked session design if MCP and hook cannot coordinate.
   - **Probe:** Add debug stdout to MCP server startup and hook invocation; compare session IDs and see if MCP can be made aware of them.

2. **Hook context placement:** Where in the turn does hook-injected stdout appear relative to the user message?
   - Hypothesis: Before (like kiro), but documented as "cannot choose."
   - Impact: Design of what information to inject and how it is presented.
   - **Probe:** Inject a unique marker string in a `UserPromptSubmit` hook; capture the transcript and measure position.

3. **Subagent per-tool allowlists:** Can tools be pre-approved per subagent, or is pre-approval only per-session?
   - Hypothesis: Likely per-session (permissions.defaultMode in settings), not per-subagent.
   - Impact: Whether Zikaron's consolidator subagent can avoid permission prompts.
   - **Probe:** Try `permissionMode: dontAsk` in subagent frontmatter and check if MCP tools fire without prompts.

4. **MCP server working directory and lifetime:** Does the MCP server stay alive across turns, and what is its working directory?
   - Hypothesis: Likely one process per session (keep state), working directory is project root or session's cwd.
   - Impact: Where Zikaron's socket endpoint can be placed and how it persists across turns.
   - **Probe:** Add a debug file write in MCP server startup and check if it persists across multiple tool calls.

5. **Exit 2 behavior on PostToolUse vs. PostToolUseFailure:** Docs say "exit 2 shows stderr to Claude" on both, but how does it differ?
   - Hypothesis: Tool already executed; exit 2 just injects stderr as context, cannot block the tool result.
   - Impact: Whether the hook can nudge the model after a tool failure.
   - **Probe:** Return exit 2 on PostToolUseFailure and verify stderr appears in the next turn's context.

6. **CompactPre/PostCompact payload and hook behavior:** What is in the payload for these events, and can they inject context?
   - Hypothesis: Likely carries transcript metadata, can inject context to summarize.
   - Impact: Whether Zikaron can capture compaction signals.
   - **Probe:** Add hook to PreCompact/PostCompact and examine stdin payload.

---

## Conclusion

Claude Code's hook system is **broadly compatible** with kiro-cli's model, with these key changes:
- **Payload field names changed:** `prompt` not `user_input`; `agent_type` identifies subagents
- **No shared session ID mechanism** between hook and MCP (this is a design gap, not documented)
- **Hook scoping changed:** subagent hooks are in frontmatter, not per-agent config; session-level hooks can matcher on subagent type
- **New events available:** `PreCompact`/`PostCompact`, `SubagentStart`/`SubagentStop`, `PostToolUseFailure`, etc.
- **Context placement not documented**, and **session ID not passed to MCP servers** (both unknowns blocking linked session design)

The above probes should resolve all unknowns before full integration work begins.

