# Amazon Q Developer CLI — the agent-facing side of the `knowledge` feature

> Traced 2026-09-14 against a read-only clone at `~/amazon-q-developer-cli`, single commit
> `15cc8f3` ("Update README to include issue reporting link (#3775)"). The clone has depth 1, so
> **no history is available** — every "was this recently changed?" question below is answered
> "not determined, the clone has one commit".
>
> Scope: `crates/chat-cli/` and the agent/config plumbing. `crates/semantic-search-client/` is
> treated as a black box (traced separately); it is referenced here only where the CLI's behaviour
> depends on a value defined there, and each such reference is cited.

## What this is

Amazon Q's `knowledge` feature is a **user-curated, file-backed semantic index**, not an
agent-authored memory. The unit of storage is a *context*: a named pointer at a file or directory
on disk, which a background job walks, chunks and embeds. The model gets one built-in tool,
`knowledge`, with a `command` discriminator carrying seven operations (`add`, `remove`, `clear`,
`search`, `update`, `show`, `cancel`) — the model can create and destroy contexts as well as search
them. The store lives under `~/.aws/amazonq/knowledge_bases/<agent-id>/`, is **global to the user
and partitioned by agent**, and has no relationship to the current working directory. The feature is
an opt-in experiment, default **off**, and when it is off the tool spec is *removed from the schema*
so the model never learns it exists. Critically for our purposes: **there is no system-prompt text
anywhere that tells the model this capability exists or when to use it.** The only prose the model
ever sees is the tool description and the parameter descriptions in `tool_index.json`, and the
official documentation's own advice is to prompt the model explicitly (`docs/knowledge-management.md:278`).

The integration is visibly unfinished. Five concrete defects are documented in §9 below, including
one operation the model is told about that cannot be parsed at all, one that cannot be parsed
because its required field is absent from the published schema, a documented capability ("store
text content") that the code cannot perform, and a success message that interpolates a multi-line
banner into the middle of a sentence. The `knowledge` tool file has **zero tests**.

## Operation table

The model-facing tool dispatches on `command`. Rust types: `crates/chat-cli/src/cli/chat/tools/knowledge.rs:33-87`.
Published schema: `crates/chat-cli/src/cli/chat/tools/tool_index.json:249-298`.

| `command` | Schema params (required-in-Rust in **bold**) | Deserializes? | Notes |
|---|---|---|---|
| `show` | none | yes | unit variant; returns contexts **and** operation status |
| `add` | **`name`**, **`value`** | yes | `value` must be a path — see §9 defect 3 |
| `search` | **`query`**, `context_id` (`Option`) | yes | the only read operation |
| `remove` | `name`, `context_id`, `path` (all `#[serde(default)]`) | yes | `validate` requires ≥1 non-empty |
| `update` | `path`, `context_id`, `name` (all `#[serde(default)]`) | yes | `path` required at invoke time |
| `clear` | **`confirm: bool`** | **no** — `confirm` is absent from the published schema | §9 defect 2 |
| `cancel` | **`operation_id: String`** | only if the model supplies it; schema calls it optional | §9 defect 4 |
| `status` | advertised in the `command` enum | **no** — no such Rust variant | §9 defect 1 |

---

## 1. The tool the model calls

**Registered name:** `knowledge`. Declared in the native tool list at
`crates/chat-cli/src/cli/chat/tools/mod.rs:74-87`:

```rust
pub const NATIVE_TOOLS: [&str; 9] = [
    "fs_read",
    "fs_write",
    #[cfg(windows)]
    "execute_cmd",
    #[cfg(not(windows))]
    "execute_bash",
    "use_aws",
    "gh_issue",
    "knowledge",
    "thinking",
    "todo_list",
    "delegate",
];
```

Dispatched from the model's tool-use envelope at `crates/chat-cli/src/cli/chat/tool_manager.rs:879`:

```rust
"knowledge" => Tool::Knowledge(serde_json::from_value::<Knowledge>(value.args).map_err(map_err)?),
```

**The exact description text the model sees** (`tool_index.json:251`) is one sentence:

> Store and retrieve information in knowledge base across chat sessions. Provides semantic search capabilities for files, directories, and text content.

That is the *entire* top-level description — 25 words. Compare the neighbouring `todo_list` tool at
`tool_index.json:301`, which spends 78 words telling the model *when* to reach for it ("This tool
should be requested EVERY time the user gives you a task that will take multiple steps"). The
`knowledge` description contains **no occasion, no trigger, and no guidance on when to search**.
Every remaining word of prose is in the parameter descriptions. Full verbatim text in Appendix A.

**Sub-command dispatch** is an internally-tagged serde enum
(`crates/chat-cli/src/cli/chat/tools/knowledge.rs:33-44`):

```rust
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "command", rename_all = "lowercase")]
pub enum Knowledge {
    Add(KnowledgeAdd),
    Remove(KnowledgeRemove),
    Clear(KnowledgeClear),
    Search(KnowledgeSearch),
    Update(KnowledgeUpdate),
    Show,
    /// Cancel a background operation
    Cancel(KnowledgeCancel),
}
```

So the wire shape is flat: `{"command": "search", "query": "..."}`. There is one tool with a
discriminated union of payloads, not seven tools. The JSON schema is correspondingly permissive —
**`command` is the only entry in `required`** (`tool_index.json:294-296`), and every per-operation
requirement is enforced either by serde (missing field → tool-use rejected) or by
`Knowledge::validate` (`knowledge.rs:95-151`), which returns `eyre::bail!` strings such as:

```rust
eyre::bail!("Please provide at least one of: name, context_id, or path");          // :109
eyre::bail!("Please confirm clearing knowledge base by setting confirm=true");     // :143
eyre::bail!("Path '{}' does not exist", add.value);                                // :102
```

Validation failures reach the model as a **hard tool error** — `ToolResultStatus::Error` with the
text `Failed to validate tool parameters: {err}` (`crates/chat-cli/src/cli/chat/mod.rs:3305-3314`).
Serde failures get a different, more editorial string (`tool_manager.rs:826-832`):

> Failed to validate tool parameters: {parse_error}. The model has either suggested tool parameters which are incompatible with the existing tools, or has suggested one or more tool that does not exist in the list of known tools.

## 2. What the model gets back

Every knowledge invocation returns `InvokeOutput { output: OutputKind::Text(result) }` — **one flat
string, never structured JSON** (`knowledge.rs:523-525`). Note also that the `Ok(...)` wrapper is
used for failures too (see §7), so a knowledge error is a *successful* tool result containing an
error sentence.

**Search specifically** (`knowledge.rs:427-447`):

```rust
Knowledge::Search(search) => {
    let results = store.search(&search.query, search.context_id.as_deref()).await;
    match results {
        Ok(results) => {
            if results.is_empty() {
                format!("No matching entries found for query: \"{}\"", search.query)
            } else {
                let mut output = format!("Search results for \"{}\":\n\n", search.query);
                for result in results {
                    if let Some(text) = result.text() {
                        output.push_str(&format!("{}\n\n", text));
                    }
                }
                output
            }
        },
        Err(e) => {
            format!("Search failed: {}", e)
        },
    }
}
```

So the model receives a header line and then **raw chunk text, blank-line separated, and nothing
else**:

- **No file path.** `SearchResult` carries a `DataPoint` whose `payload` is a map; the CLI reads
  exactly one key. `crates/semantic-search-client/src/types.rs:184-187`:
  ```rust
  pub fn text(&self) -> Option<&str> {
      self.point.payload.get("text").and_then(|v| v.as_str())
  }
  ```
  Whatever else the payload holds is discarded at this boundary.
- **No score.** `SearchResult.distance: f32` (`types.rs:174-175`) is used for sorting and then
  dropped.
- **No context name or id**, so the model cannot tell which knowledge base a chunk came from, and
  cannot follow up with a scoped search.
- **Results with no `text` key are silently skipped** — `if let Some(text)`, no `else`. A search
  that matched five chunks with absent payloads is indistinguishable from one that matched five
  chunks of empty prose, and both differ from the explicit "No matching entries found".

**How many results.** `KnowledgeStore::search` (`crates/chat-cli/src/util/knowledge_store.rs:375-402`)
passes `None` for the limit on both arms. `None` resolves to `config.default_results`
(`crates/semantic-search-client/src/client/async_implementation.rs:416`), whose default is **5**
(`crates/semantic-search-client/src/config.rs:89`, asserted at `config.rs:289`). Two cases:

- `context_id` given → `search_context(...)` → **5 chunks**.
- `context_id` omitted → `search_all(...)` → 5 chunks **per context**, flattened and re-sorted by
  distance with **no global cap** (`knowledge_store.rs:386-400`):
  ```rust
  for (_, context_results) in agent_results {
      flattened.extend(context_results);
  }
  flattened.sort_by(|a, b| a.distance.partial_cmp(&b.distance).unwrap_or(std::cmp::Ordering::Equal));
  ```
  A user with ten contexts gets **fifty chunks** in one tool result. `default_results` is not
  exposed as a `q settings` key (see §4 — the seven knowledge settings do not include it), so this
  is not tunable by a user.

**Truncation.** The knowledge tool applies **none**. `MAX_TOOL_RESPONSE_SIZE = 400_000`
(`crates/chat-cli/src/cli/chat/consts.rs:9`, commented "Actual service limit is 800_000") is
enforced only inside `fs_read`, `execute` and `use_aws` — grep for the constant returns
`use_aws.rs:86,96`, `execute/mod.rs:151`, `fs_read.rs:534,784`, and no knowledge site. The
knowledge result therefore reaches the request builder whole. The backstops downstream are
history-management, not tool-output management:

- `MAX_USER_MESSAGE_SIZE = 400_000` (`consts.rs:12`), applied when a tool result is folded into a
  prompt (`crates/chat-cli/src/cli/chat/message.rs:285`);
- compaction truncation at `conversation.rs:702` using `strategy.max_message_length`, which is
  `MAX_USER_MESSAGE_SIZE` by default (`cli/compact.rs:98`) and `25_000` on the retry paths
  (`chat/mod.rs:1617,1640`);
- the suffix appended on truncation is `"...content truncated due to length"` (`message.rs:79`).

So the answer to "what happens when a result exceeds the budget" is: **nothing at the tool, and
silent tail-truncation much later, with a suffix the model may or may not still be looking at.**
The chunk size that feeds this is user-settable up the scale with no compensating cap —
`knowledge.chunkSize` defaults to 512 (`config.rs:87`, asserted at `knowledge_store.rs:608`) but
`docs/knowledge-management.md:171` advertises setting it to 1024.

## 3. The user-facing surface

`crates/chat-cli/src/cli/chat/cli/knowledge.rs`. Registered at `cli/mod.rs:76-79`:

```rust
/// (Beta) Manage knowledge base for persistent context storage. Requires "q settings
/// chat.enableKnowledge true"
#[command(subcommand, hide = true)]
Knowledge(KnowledgeSubcommand),
```

Note `hide = true`: **`/knowledge` does not appear in `/help`** even when the experiment is on. It
appears only in tab-completion, via `ExperimentManager::get_commands` (`prompt.rs:153`).

**Subcommands** (`cli/knowledge.rs:27-60`, names at `:535-544`): `show`, `add`, `remove` (alias
`rm`), `update`, `clear`, `cancel`. `add` is the richest, and is **strictly more capable than the
model's `add`**:

```rust
Add {
    /// Name for the knowledge base entry
    #[arg(long, short = 'n')]
    name: String,
    /// Path to file or directory to add
    #[arg(long, short = 'p')]
    path: String,
    /// Include patterns (e.g., `**/*.ts`, `**/*.md`)
    #[arg(long, action = clap::ArgAction::Append)]
    include: Vec<String>,
    /// Exclude patterns (e.g., `node_modules/**`, `target/**`)
    #[arg(long, action = clap::ArgAction::Append)]
    exclude: Vec<String>,
    /// Index type to use (Fast, Best)
    #[arg(long)]
    index_type: Option<String>,
},
```

**The asymmetries between the two surfaces are the interesting part:**

| | model tool | slash command |
|---|---|---|
| `search` | yes | **no — absent from `KnowledgeSubcommand` entirely** |
| `status` | advertised, unparseable (§9) | no; folded into `show` |
| include/exclude patterns on `add` | no — always DB defaults (`knowledge.rs:338`) | yes, per-invocation |
| `--index-type` on `add` | no | yes |
| `clear` | `confirm: true` flag (unreachable, §9) | interactive `y/N` on stdin |
| `remove` | by `name` **or** `context_id` **or** `path` | one positional, tried as path then name |
| `cancel` with no id | schema says "cancel all" | cancels **most recent** only |

So **a user cannot search their own knowledge base from the CLI at all** — searching is exclusively
the model's affordance, and the documentation's workaround is to ask the model in English
(`docs/knowledge-management.md:278`):

> Prompt Q to use the tool with prompts like "find database connection configuration using your knowledge bases" or "using your knowledge tools can you find how to replace your laptop"

**What the user can see.** `/knowledge show` (`cli/knowledge.rs:134-244`) prints, to **stderr**, an
agent header, then per context a name + 8-char id, source path, and a stats line:

```rust
style::Print(format!("{} items", ctx.item_count)),
style::Print(" • "),
style::Print(ctx.embedding_type.description()),
style::Print(" • "),
style::Print(format!("{}", ctx.updated_at.format("%m/%d %H:%M"))),
```

followed by live operations (`:420-460`), each rendered as an emoji line, a path line, and a state
line that is one of `Cancelled` / `Failed` / `Waiting` / `{pct}% • ETA: {n}s` / `{pct}%` /
`In progress`. Errors are printed through a four-way `OperationResult` enum
(`Success`/`Info`/`Warning`/`Error`, `:62-68`, rendered at `:496-533`) with the `Error` arm
prefixing `"\nError: {msg}\n\n"`.

So **progress and ETA exist and are good — for the user.** The model gets the same `format_status_display`
logic reimplemented in `knowledge.rs:540-580` (a near-duplicate differing only in indentation and in
the progress guard: the slash command uses `should_show_progress_bar(current, total)` which also
checks `current <= total`, `cli/knowledge.rs:463-465`, while the tool checks only `op.total > 0`,
`knowledge.rs:567`) and can reach it only via `show`, never via the advertised `status`.

`/knowledge clear` is the only place the CLI reads stdin directly (`cli/knowledge.rs:376-384`) —
`⚠️  This action will remove all knowledge base entries.` then `Clear the knowledge base? (y/N): `.
It then cancels pending operations and calls `clear_immediate` (synchronous), where the model's
`clear` calls the *background* `clear()`. Note the prompt text differs from the documented one:
`docs/knowledge-management.md:157` promises `⚠️ This will remove ALL knowledge base entries. Are you
sure? (y/N):`, which no longer appears in the code.

## 4. Gating

Three independent layers.

**(a) The experiment flag.** `crates/chat-cli/src/cli/experiment/experiment_manager.rs:43-60`:

```rust
Experiment {
    experiment_name: ExperimentName::Knowledge,
    description: "Enables persistent context storage and retrieval across chat sessions (/knowledge)",
    setting_key: Setting::EnabledKnowledge,
    enabled: true,
    commands: &[
        "/knowledge",
        "/knowledge help",
        "/knowledge show",
        "/knowledge add",
        "/knowledge remove",
        "/knowledge clear",
        "/knowledge search",
        "/knowledge update",
        "/knowledge status",
        "/knowledge cancel",
    ],
},
```

The `enabled: true` field is **not the default state** — it means "this experiment is offerable".
The default is `false`, from the `unwrap_or` at `:127-137`:

```rust
pub fn is_enabled(os: &Os, experiment_type: ExperimentName) -> bool {
    let experiment = AVAILABLE_EXPERIMENTS
        .iter()
        .find(|exp| exp.experiment_name == experiment_type);
    match experiment {
        // Here we try to get value from storage, ONLY if experiment is enabled, otherwise we default
        // to false.
        Some(exp) if exp.enabled => os.database.settings.get_bool(exp.setting_key).unwrap_or(false),
        _ => false,
    }
}
```

**Default: OFF.** `docs/knowledge-management.md:12` agrees: "The knowledge feature is experimental
and disabled by default."

Two ways to enable. Out of band: `q settings chat.enableKnowledge true`. In-session: `/experiment`,
an interactive `dialoguer::Select` (`crates/chat-cli/src/cli/chat/cli/experiment.rs:30-70`) which
prints `⚠ Experimental features may be changed or removed at any time` and, on toggle, calls
`ExperimentManager::set_enabled`, which **hot-reloads the tool schema**
(`experiment_manager.rs:160-161`):

```rust
// Makes sure tools are hot-reloaded, so the ones behind experiment flags are enabled.
session.reload_builtin_tools(os).await?;
```

The out-of-band `q settings` route has no such hook, so a running session will not pick it up until
`load_tools` runs again.

**Is the tool hidden from the model when disabled? Yes — removed outright.**
`crates/chat-cli/src/cli/chat/tool_manager.rs:713-735`:

```rust
let mut tool_specs =
    serde_json::from_str::<HashMap<String, ToolSpec>>(include_str!("tools/tool_index.json"))?
        .into_iter()
        .filter(|(name, _)| { /* agent tools list */ })
        .collect::<HashMap<_, _>>();
if !crate::cli::chat::tools::thinking::Thinking::is_enabled(os) {
    tool_specs.remove("thinking");
}
if !crate::cli::chat::tools::knowledge::Knowledge::is_enabled(os) {
    tool_specs.remove("knowledge");
}
```

The model never sees the spec. If it hallucinates a call anyway, `get_tool_from_tool_use` still has
a live `"knowledge" =>` arm (`tool_manager.rs:879`) and would happily construct and invoke it —
there is no second enablement check at invoke time. That is latent rather than exploitable, since
the name is only reachable if the model guesses it.

The **slash command** refuses separately and with a different, gentler message
(`cli/knowledge.rs:88-97`):

```rust
style::Print("\nKnowledge tool is disabled. Enable it with: q settings chat.enableKnowledge true\n"),
style::Print("💡 Your knowledge base data is preserved and will be available when re-enabled.\n\n"),
```

**(b) Agent tool visibility.** The `tools` array filters the spec map before the experiment check
(`tool_manager.rs:716-723`); `"*"` or `"@builtin"` or a literal `"knowledge"` or `"@builtin/knowledge"`
all admit it. The default agent uses `tools: vec!["*"]` (`crates/chat-cli/src/cli/agent/mod.rs:191`).

**(c) Per-call permission.** `knowledge.rs:528-537`:

```rust
pub fn eval_perm(&self, os: &Os, agent: &Agent) -> PermissionEvalResult {
    _ = self;
    _ = os;

    if is_tool_in_allowlist(&agent.allowed_tools, "knowledge", None) {
        PermissionEvalResult::Allow
    } else {
        PermissionEvalResult::Ask
    }
}
```

`_ = self` is the notable line: **permission does not depend on the operation.** `search` and
`clear` are the same decision. The default `allowed_tools` is empty — `DEFAULT_APPROVE: [&str; 0] = []`
(`tools/mod.rs:73`), spread into the set at `agent/mod.rs:192-196` — and `knowledge` is absent from
the `default_permission_label` match arms (`agent/mod.rs:853-869`), so it falls to the `_ =>` arm
and displays as `"not trusted"`. **Out of the box, every knowledge call — including a read-only
search — raises a permission prompt.**

**The settings keys.** Seven, all in `crates/chat-cli/src/database/settings.rs:29-42` (labels) and
`:103-109` (wire names):

| Key | Enum | Default |
|---|---|---|
| `chat.enableKnowledge` | `EnabledKnowledge` | false |
| `knowledge.defaultIncludePatterns` | `KnowledgeDefaultIncludePatterns` | `[]` |
| `knowledge.defaultExcludePatterns` | `KnowledgeDefaultExcludePatterns` | `[]` |
| `knowledge.maxFiles` | `KnowledgeMaxFiles` | 10000 (`config.rs:93`) |
| `knowledge.chunkSize` | `KnowledgeChunkSize` | 512 (`config.rs:87`) |
| `knowledge.chunkOverlap` | `KnowledgeChunkOverlap` | 128 (`config.rs:88`) |
| `knowledge.indexType` | `KnowledgeIndexType` | `Default::default()` for `EmbeddingType` |

Defaults asserted in `knowledge_store.rs:598-612`. `default_results` (the result count, §2) is
**not** among them.

## 5. Scoping and paths

**On disk.** `crates/chat-cli/src/util/paths.rs:66` and `:295-297`:

```rust
pub const KNOWLEDGE_BASES_DIR: &str = ".aws/amazonq/knowledge_bases";
```
```rust
pub fn knowledge_bases_dir(&self) -> Result<PathBuf> {
    Ok(home_dir(self.os)?.join(global::KNOWLEDGE_BASES_DIR))
}
```

It sits in the `global` module — "User-level paths (relative to home directory)" (`paths.rs:57-58`)
— alongside `AGENTS_DIR`, `MCP_CONFIG` and `PROMPTS_DIR`. There is a sibling `workspace` module
(`paths.rs:44-55`) holding the project-relative paths (`.amazonq/cli-agents`, `.amazonq/mcp.json`,
`.amazonq/cli-todo-lists`, …). **`knowledge_bases` is deliberately not in it.** Contrast
`todo_list`, which *is* project-scoped (`workspace::TODO_LISTS_DIR = ".amazonq/cli-todo-lists"`).

**The partition is the agent, not the directory.**
`crates/chat-cli/src/util/knowledge_store.rs:23-49`:

```rust
/// Generate a unique identifier for an agent based on its path and name
fn generate_agent_unique_id(agent: &crate::cli::Agent) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{ Hash, Hasher };

    if let Some(path) = &agent.path {
        let mut hasher = DefaultHasher::new();
        path.hash(&mut hasher);
        let path_hash = hasher.finish();
        format!("{}_{:x}", agent.name, path_hash)
    } else {
        agent.name.clone()
    }
}

/// Get the knowledge base directory path for a specific agent
fn agent_knowledge_dir(os: &Os, agent: Option<&crate::cli::Agent>) -> Result<PathBuf, paths::DirectoryError> {
    let unique_id = if let Some(agent) = agent {
        generate_agent_unique_id(agent)
    } else {
        DEFAULT_AGENT_NAME.to_string()
    };
    Ok(PathResolver::new(os).global().knowledge_bases_dir()?.join(unique_id))
}
```

`agent.path` is the **agent config file's** path, set in `Agent::thaw` (`agent/mod.rs:230`). Since
agent configs live in either `.amazonq/cli-agents/` (workspace) or `~/.aws/amazonq/cli-agents/`
(global), project scoping is achieved **indirectly and only if the user defines a workspace-local
agent**: a global agent shares one knowledge base across every project the user opens with it. The
default agent is `q_cli_default` (`agent/mod.rs:74`) with no path, so its directory is the bare
name. Layout is documented at `docs/knowledge-management.md:187-207`.

Two things worth flagging. `DefaultHasher`'s output is explicitly **not guaranteed stable across
Rust releases**, so a toolchain bump can silently re-point an agent at a fresh, empty knowledge
directory while the old one lingers — nothing in the code detects or reports that. And the
singleton is keyed on the resolved directory, so switching agents mid-session tears down and
rebuilds the client (`knowledge_store.rs:160-181`):

```rust
let needs_reinit = match instance_guard.as_ref() {
    None => true,
    Some(store) => {
        let store_guard = store.lock().await;
        store_guard.agent_dir != current_agent_dir
    },
};
```

A legacy migration runs on every reinit (`:184-223`), moving loose **files** (not directories) from
the `knowledge_bases` root into the agent directory.

**The cwd is not involved in store location at all.** Its only role is implicit: relative paths from
the model are not resolved against any recorded cwd. `sanitize_path_tool_arg`
(`tools/mod.rs:383-400`) expands a leading `~` and otherwise passes components through unchanged;
`path.exists()` (`knowledge.rs:101`) and `path_buf.canonicalize()` (`knowledge_store.rs:291-293`)
then resolve against the **process** cwd. So `knowledge add` with a relative path works by
accident of process state, and the stored `source_path` is the canonicalized absolute path.

**Multiple knowledge bases coexist** — within one agent directory, each *context* is a separate
sub-directory with its own `data.json` / `bm25_data.json`. The model addresses one by
`context_id`, a uuid it can only obtain by first calling `show` (per `tool_index.json:279`: "Can
be obtained from 'show' command"). Since search results carry no context attribution (§2), the
`show`-then-`search` round trip is the *only* way the model can scope a query, and nothing in the
description tells it to.

**Cross-agent access is impossible by construction** — the client is constructed against one
directory (`knowledge_store.rs:274-286`) and has no notion of the others.

## 6. Agent configuration

**There is no knowledge-specific agent configuration.** `grep -rn -i "knowledge" schemas/ crates/agent/`
returns nothing but an unrelated false positive on the word "acknowledge"
(`crates/agent/src/agent/mod.rs:1752`).

`schemas/agent-v1.json` has thirteen properties — `$schema`, `name`, `description`, `prompt`,
`mcpServers`, `tools`, `toolAliases`, `allowedTools`, `resources`, `hooks`, `toolsSettings`,
`useLegacyMcpJson`, `model` — and none of them is knowledge-aware. The tool is reachable only as a
string in the two generic arrays:

```json
"tools": {
  "description": "List of tools the agent can see. Use \"@{MCP_SERVER_NAME}/tool_name\" to specify tools from\nmcp servers. To include all tools from a server, use \"@{MCP_SERVER_NAME}\"",
  "type": "array",
  "items": { "type": "string" },
  "default": []
},
"allowedTools": {
  "description": "List of tools the agent is explicitly allowed to use",
  "type": "array",
  "uniqueItems": true,
  "items": { "type": "string" },
  "default": []
}
```

`docs/agent-format.md:196` names it as an example of an exact-match built-in:

> - **Built-in tools**: `"fs_read"`, `"execute_bash"`, `"knowledge"`

and `:224` shows `"knowledge"` in a worked `allowedTools` array. Matching goes through
`is_tool_in_allowlist` (`crates/chat-cli/src/util/tool_permission_checker.rs:13-49`), which
accepts `@builtin`, `@builtin/`, `@builtin/*`, a bare `knowledge`, `@builtin/knowledge`, or any
glob covering it (`*`, `know*`, `?nowledge` …). Because `eval_perm` discards `self` (§4), an
allowlist entry is all-or-nothing: **there is no way to trust `search` while still prompting on
`clear`**, and no `toolsSettings` schema for `knowledge` to carry one (`toolsSettings` is a free
`HashMap<ToolSettingTarget, serde_json::Value>`, `agent/mod.rs:168`, with no knowledge consumer
anywhere).

**An agent cannot be configured with specific knowledge bases.** The binding is one-directional and
implicit: the agent determines the directory (§5), the directory determines the contexts, and there
is no field naming a context.

**The newer standalone `crates/agent/` does not have this tool at all.** Its tool modules are
`execute_cmd`, `fs_read`, `fs_write`, `grep`, `image_read`, `introspect`, `ls`, `mcp`, `mkdir`, `rm`
(`crates/agent/src/agent/tools/mod.rs:1-10`). Whether that is a deliberate drop or work in progress
is **not determined** — the clone has one commit and no history to read intent from.

## 7. Concurrency and async

**The model never blocks on indexing, and never gets a pollable handle either.**

`add` returns as soon as the job is *queued*. `knowledge_store.rs:338-357`:

```rust
match self.agent_client.add_context(request).await {
    Ok((operation_id, _)) => {
        let mut message = format!(
            "🚀 Started indexing '{}'\n📁 Path: {}\n🆔 Operation ID: {}",
            name,
            canonical_path.display(),
            &operation_id.to_string()[..8]
        );
```

Tool invocation itself is a plain `await` in the chat loop (`chat/mod.rs:2499-2507`) with a spinner
dropped afterwards (`:2509-2517`) — synchronous from the model's point of view, but the awaited
work is only the enqueue. `search`, by contrast, genuinely blocks on embedding the query.

**What the model sees while indexing is in progress:** nothing, unless it asks. There is no
progress push, no completion notification, and no mechanism to wake the model when a job finishes.
Its only poll is `command: "show"`, which returns the context list *plus* the operation block
(`knowledge.rs:448-516`, formatting at `:540-580`). The `status` command that the schema tells it
to use for exactly this does not work (§9 defect 1). And the `add` success string points it at a
**slash command it cannot execute** (`knowledge.rs:342-345`):

```rust
Ok(context_id) => format!(
    "Added '{}' to knowledge base with ID: {}. Track active jobs in '/knowledge status' with provided id.",
    add.name, context_id
),
```

`/knowledge status` is not a `KnowledgeSubcommand` variant either — `docs/knowledge-management.md:31`
records that it was folded into `show` ("This unified command replaces the previous separate
`/knowledge status` command"). So this sentence directs the model at a nonexistent slash command in
a surface the model has no access to. The same sentence is repeated verbatim on all three `update`
arms (`knowledge.rs:398`, `:407`, `:416`).

**A search against a still-indexing context returns quietly incomplete results.** Nothing compares
the context's item count against the operation's progress, and nothing in the returned string
mentions that a job is running. `docs/knowledge-management.md:332` makes this the user's problem:
"Wait for indexing: Use /knowledge show to ensure indexing is complete."

**Error surfacing is asymmetric, and the model's half is the weaker one.**

- To the **user**: a four-state `OperationResult` with colour, `Error:` prefix, warnings for
  partial failures (`cli/knowledge.rs:496-533`).
- To the **model**: almost every failure is wrapped in `Ok(...)` and returned as a *successful*
  tool result whose text happens to begin with "Failed". From `knowledge.rs` alone:
  `"Failed to add to knowledge base: {}"` (:346), `"Failed to remove context by ID: {}"` (:354),
  `"Failed to remove context by name: {}"` (:360), `"Failed to remove context by path: {}"` (:367),
  `"Failed to update context by ID: {}"` (:401), `"Failed to clear knowledge base: {}"` (:426),
  `"Search failed: {}"` (:444), `"Failed to cancel operation: {}"` (:520), plus
  `"Error: No path provided for update…"` (:378) and `"Error: Path '{}' does not exist"` (:387).
  Only `validate` failures and serde failures produce a real `ToolResultStatus::Error`. Everything
  that goes wrong *during* the operation is indistinguishable, at the protocol level, from success.

Cancellation is best-effort and per-operation: `cancel_operation(None)` cancels **the most recent**
(`knowledge_store.rs:441-447`), never all.

## 8. Prompt integration

**There is none. This is the finding.**

Searching the whole of `crates/chat-cli/src/` for `knowledge` returns exactly: the two knowledge
source files, `knowledge_store.rs`, the settings enum, the experiment entry, the four dispatch
sites in `tools/mod.rs` and `tool_manager.rs`, the slash-command registration in `cli/mod.rs`, the
path constant, and one test in `prompt.rs`. **No hit inside any system prompt, context block, or
injected instruction.**

`conversation.rs` — checked specifically, as asked — mentions knowledge nowhere. Its only grep hits
are the word "acknowledge" inside the *compaction* prompt (`conversation.rs:813`):

> This summary contains ALL relevant information from our previous conversation including tool uses, results, code analysis, and file operations. YOU MUST reference this information when answering questions and explicitly acknowledge specific details from the summary when they're relevant to the current question.

and its paired canned assistant reply (`:853`). Neither is about the knowledge feature.

`prompt.rs` — also checked specifically — touches knowledge only for **tab completion**. Line 153:

```rust
commands.extend(ExperimentManager::get_commands(os));
```

and a test at `:1007-1025` asserting that `/knowledge` and `/knowledge help` appear in the
completion list when the experiment is on. `get_commands` (`experiment_manager.rs:172-179`) filters
to enabled experiments. This is the *only* conditional behaviour keyed on the knowledge experiment
outside the tool schema, and it affects the user's terminal, not the model's context.

So the complete set of words the model ever receives about this capability is the `tool_index.json`
block reproduced in Appendix A: one 25-word description plus seven parameter descriptions. **There
is no analogue of Zikaron's `agentSpawn` write policy, no injected reminder, and no push path of
any kind.** The documentation closes the loop by telling the user to supply the missing trigger
manually (`docs/knowledge-management.md:275-278`):

> #### Effective Searching
>
> - Use natural language queries: "how to handle authentication errors using the knowledge tool"
> - Be specific about what you're looking for: "database connection configuration"
> - Try different phrasings if initial searches don't return expected results
> - Prompt Q to use the tool with prompts like "find database connection configuration using your knowledge bases" or "using your knowledge tools can you find how to replace your laptop"

## 9. Known limitations

**No `TODO`, `FIXME`, `HACK` or `XXX` comment appears in any of the three knowledge source files.**
The authors left no in-code admissions. What the code *does* admit, by disagreeing with itself:

**Defect 1 — `status` is advertised to the model and cannot be parsed.** The schema enum
(`tool_index.json:257-266`) lists `"status"`, and the `command` description documents it
(`:267`): "- 'status': Show background operation status and progress". The Rust enum
(`knowledge.rs:33-44`) is `#[serde(tag = "command", rename_all = "lowercase")]` over
`Add|Remove|Clear|Search|Update|Show|Cancel` — **there is no `Status` variant and no `#[serde(alias)]`**.
`{"command":"status"}` therefore fails `serde_json::from_value` at `tool_manager.rs:879` and the
model receives "Failed to validate tool parameters: unknown variant …". The model is told to use
`status` by the schema *and* by the `add` success message (§7), and both are dead ends. The repair
is `show`, which the schema describes as merely "List all knowledge contexts" — not mentioning that
it also returns operation status, which it does (`knowledge.rs:448-516`). *Not verified by
execution* — inferred from serde's documented behaviour for internally-tagged enums; the reasoning
is that "status" is not among the seven lowercased variant names.

**Defect 2 — `clear` is unreachable from the model.** `KnowledgeClear` requires `confirm`
(`knowledge.rs:62-65`):

```rust
pub struct KnowledgeClear {
    pub confirm: bool,
}
```

No `#[serde(default)]`, so serde requires the field. But `confirm` **is not among the schema's
properties** — `tool_index.json:254-293` publishes `command`, `name`, `value`, `context_id`,
`path`, `query`, `operation_id` and nothing else. A model that follows the schema sends
`{"command":"clear"}`, serde rejects it for a missing field it was never told about, and
`validate`'s carefully-written message — `"Please confirm clearing knowledge base by setting
confirm=true"` (`:143`) — is unreachable, because deserialization fails first. The `clear`
description (`:267`) is also the only one in the list with no parenthetical about parameters:
"- 'clear': Remove all knowledge contexts." Arguably a safe failure. It is still a lie in the
schema.

**Defect 3 — "text content" is documented at three levels and supported at none.** The tool
description says "semantic search capabilities for files, directories, and text content"
(`:251`). The `value` description says (`:275`): "Can be either text content or a file/directory
path. If it's a valid file or directory path, the content will be indexed; otherwise it's treated
as text." `validate` builds a bypass for it (`knowledge.rs:97-106`):

```rust
Knowledge::Add(add) => {
    // Check if value is intended to be a path (doesn't contain newlines)
    if !add.value.contains('\n') {
        let path = crate::cli::chat::tools::sanitize_path_tool_arg(os, &add.value);
        if !path.exists() {
            eyre::bail!("Path '{}' does not exist", add.value);
        }
    }
    Ok(())
},
```

and `invoke` preserves the original string when it is not a path (`:326-332`). But the store's
`add` canonicalizes unconditionally (`knowledge_store.rs:289-293`):

```rust
let path_buf = std::path::PathBuf::from(path_str);
let canonical_path = path_buf
    .canonicalize()
    .map_err(|_io_error| format!("❌ Path does not exist: {}", path_str))?;
```

So single-line text is rejected by `validate` ("Path '…' does not exist") and multi-line text
passes `validate`, reaches `add`, and fails with "❌ Path does not exist: <the user's prose>" —
wrapped in `Ok(...)`, so the model sees a *successful* tool result containing that. **The feature
the description advertises first cannot be performed by any input.** The slash command is honest
about this: its `add` takes `--path`, not a value.

**Defect 4 — `cancel`'s contract is wrong in three ways at once.** The schema
(`tool_index.json:289-292`) says operation_id is "Optional … If not provided, all active operations
will be cancelled". But (a) the Rust field is `pub operation_id: String` with no `#[serde(default)]`
(`knowledge.rs:83-87`), so omitting it is a parse error; (b) the doc comment on that field says
`/// Operation ID to cancel, or "all" to cancel all operations` and no code path special-cases
`"all"` — `Uuid::parse_str("all")` fails, then `find_operation_by_short_id` does
`id.to_string().starts_with(short_id)` (`crates/semantic-search-client/src/client/operation/operation_manager.rs:147-153`),
and a uuid string is hex, so `"all"` can never prefix-match; (c) even the `None` path does not
cancel all — it calls `cancel_most_recent_operation` (`knowledge_store.rs:441-447`).
`docs/knowledge-management.md:161-164` repeats both errors to users.

**Defect 5 — the `add` success message nests a multi-line banner inside a sentence.**
`store.add` returns the banner quoted in §7; `knowledge.rs:342-345` binds it to a variable named
`context_id` and interpolates it after "with ID: ". The model therefore receives, literally:

```
Added 'my-project' to knowledge base with ID: 🚀 Started indexing 'my-project'
📁 Path: /home/u/my-project
🆔 Operation ID: 3f2a9c1b. Track active jobs in '/knowledge status' with provided id.
```

The "ID" is a three-line banner, and the actual `context_id` is never returned — the id shown is an
**operation** id, which is what `cancel` wants but *not* what `search`'s and `remove`'s
`context_id` parameter wants. To get a real `context_id` the model must call `show`. Nothing says so.

**Also inconsistent, lower stakes:** the experiment's `commands` list (`experiment_manager.rs:48-59`)
advertises `/knowledge search` and `/knowledge status` to tab-completion, and neither is a
`KnowledgeSubcommand` variant (`cli/knowledge.rs:27-60`) — the user is offered two completions that
will not parse. And `format_status_display` is duplicated between `knowledge.rs:540-580` and
`cli/knowledge.rs:420-460` with a divergent progress guard (§3).

**What the tests pin down: almost nothing.**

- `crates/chat-cli/src/cli/chat/tools/knowledge.rs` — **no `#[cfg(test)]` module at all.** Not one
  test of dispatch, validation, result formatting, or permission.
- `crates/chat-cli/src/cli/chat/cli/knowledge.rs:547-708` — five tests, **all of them clap argument
  parsing** (`test_include_exclude_patterns_parsing`, `test_clap_markdown_parsing_issue`,
  `test_empty_patterns_allowed`, `test_multiple_include_patterns`,
  `test_add_command_with_name_and_path`, `test_multiple_exclude_patterns`). None executes an
  operation. One is explicitly a placeholder — `test_clap_markdown_parsing_issue` asserts only that
  `--help` returns `DisplayHelp`, with the comment "We can't easily test the exact formatting here,
  but this documents the issue" (`:606-607`).
- `crates/chat-cli/src/util/knowledge_store.rs:582-626` — two tests:
  `test_create_config_from_db_settings` (asserts the 512/128/10000 defaults) and
  `test_knowledge_bases_dir_structure`, whose entire assertion is
  `assert!(base_dir.to_string_lossy().contains("knowledge_bases"));`.
- Nothing anywhere tests that the published schema and the Rust types agree. A single round-trip
  test — deserialize one example per schema enum value — would have caught defects 1 and 2.

**What the authors say is unfinished**, in their own words, is confined to
`docs/knowledge-management.md:294-313`, and it is all about the *engine*, not the integration:
binary files ignored; "Very large files may be chunked, potentially splitting related content";
"Background operations are limited by concurrent processing limits"; "No explicit storage size
limits, but practical limits apply"; "No automatic cleanup of old or unused contexts"; "Clear
operations are irreversible with no backup functionality". **None of the agent-facing defects above
is acknowledged anywhere.**

---

## Appendix A — the complete tool description text, verbatim

`crates/chat-cli/src/cli/chat/tools/tool_index.json:249-298`, reproduced in full. This is the
entirety of what the model is told about the feature.

```json
"knowledge": {
    "name": "knowledge",
    "description": "Store and retrieve information in knowledge base across chat sessions. Provides semantic search capabilities for files, directories, and text content.",
    "input_schema": {
      "type": "object",
      "properties": {
        "command": {
          "type": "string",
          "enum": [
            "show",
            "add",
            "remove",
            "clear",
            "search",
            "update",
            "status",
            "cancel"
          ],
          "description": "The knowledge operation to perform:\n- 'show': List all knowledge contexts (no additional parameters required)\n- 'add': Add content to knowledge base (requires 'name' and 'value')\n- 'remove': Remove content from knowledge base (requires one of: 'name', 'context_id', or 'path')\n- 'clear': Remove all knowledge contexts.\n- 'search': Search across knowledge contexts (requires 'query', optional 'context_id')\n- 'update': Update existing context with new content (requires 'path' and one of: 'name', 'context_id')\n- 'status': Show background operation status and progress\n- 'cancel': Cancel background operations (optional 'operation_id' to cancel specific operation, or cancel all if not provided)"
        },
        "name": {
          "type": "string",
          "description": "A descriptive name for the knowledge context. Required for 'add' operations. Can be used for 'remove' and 'update' operations to identify the context."
        },
        "value": {
          "type": "string",
          "description": "The content to store in knowledge base. Required for 'add' operations. Can be either text content or a file/directory path. If it's a valid file or directory path, the content will be indexed; otherwise it's treated as text."
        },
        "context_id": {
          "type": "string",
          "description": "The unique context identifier for targeted operations. Can be obtained from 'show' command. Used for 'remove', 'update', and 'search' operations to specify which context to operate on."
        },
        "path": {
          "type": "string",
          "description": "File or directory path. Used in 'remove' operations to remove contexts by their source path, and required for 'update' operations to specify the new content location."
        },
        "query": {
          "type": "string",
          "description": "The search query string. Required for 'search' operations. Performs semantic search across knowledge contexts to find relevant content."
        },
        "operation_id": {
          "type": "string",
          "description": "Optional operation ID to cancel a specific operation. Used with 'cancel' command. If not provided, all active operations will be cancelled. Can be either the full operation ID or the short 8-character ID."
        }
      },
      "required": [
        "command"
      ]
    }
  },
```

The `command` description, unescaped for reading:

> The knowledge operation to perform:
> - 'show': List all knowledge contexts (no additional parameters required)
> - 'add': Add content to knowledge base (requires 'name' and 'value')
> - 'remove': Remove content from knowledge base (requires one of: 'name', 'context_id', or 'path')
> - 'clear': Remove all knowledge contexts.
> - 'search': Search across knowledge contexts (requires 'query', optional 'context_id')
> - 'update': Update existing context with new content (requires 'path' and one of: 'name', 'context_id')
> - 'status': Show background operation status and progress
> - 'cancel': Cancel background operations (optional 'operation_id' to cancel specific operation, or cancel all if not provided)

## Appendix B — every other string the model can receive

From `crates/chat-cli/src/cli/chat/tools/knowledge.rs` (format placeholders as written):

```
Added '{}' to knowledge base with ID: {}. Track active jobs in '/knowledge status' with provided id.     :343
Failed to add to knowledge base: {}                                                                      :346
Removed context with ID '{}' from knowledge base                                                         :353
Failed to remove context by ID: {}                                                                       :354
Removed context with name '{}' from knowledge base                                                       :359
Failed to remove context by name: {}                                                                     :360
Removed context with path '{}' from knowledge base                                                       :366
Failed to remove context by path: {}                                                                     :367
Error: No identifier provided for removal. Please specify name, context_id, or path.                     :370
Error: No path provided for update. Please specify a path to update with.                                :378
Error: Path '{}' does not exist                                                                          :387
Updated context with ID '{}' using path '{}'.  Track active jobs in '/knowledge status' with provided id. :398
Failed to update context by ID: {}                                                                       :401
Updated context with name '{}' using path '{}'. Track active jobs in '/knowledge status' with provided id. :407
Failed to update context by name: {}                                                                     :410
Updated context with path '{}'. Track active jobs in '/knowledge status' with provided id.               :416
Failed to update context by path: {}                                                                     :419
Failed to clear knowledge base: {}                                                                       :426
No matching entries found for query: "{}"                                                                :432
Search results for "{}":                                                                                 :434
Search failed: {}                                                                                        :444
No knowledge base entries found                                                                          :459
Knowledge base entries:                                                                                  :461
- ID: {}\n  Name: {}\n  Description: {}\n  Persistent: {}\n  Created: {}\n  Last Updated: {}\n  Items: {} :463
Status unavailable: {}                                                                                   :500
Contexts unavailable: {}                                                                                 :505
Failed to get contexts: {}\nFailed to get status: {}                                                     :511
Failed to cancel operation: {}                                                                           :520
No active operations                                                                                     :541
🔄 {} ({})                                                                                               :550
Cancelled / Failed / Waiting / {}% • ETA: {}s / {}% / In progress                                        :562-575
```

Validation errors (`ToolResultStatus::Error`, via `chat/mod.rs:3309-3311`):

```
Path '{}' does not exist                                                                                 :102
Please provide at least one of: name, context_id, or path                                                :109
Please provide either context_id, name, or path to identify the knowledge base entry to update           :127
Please confirm clearing knowledge base by setting confirm=true                                           :143
```

From `crates/chat-cli/src/util/knowledge_store.rs` (surfaced to the model through the `Ok`/`Err`
arms above):

```
❌ Path does not exist: {}                                                                               :293
🚀 Started indexing '{}'\n📁 Path: {}\n🆔 Operation ID: {}                                               :341
📋 Pattern filtering applied: / ✅ Only matching files will be indexed                                   :347-354
Failed to start indexing: {}                                                                             :363
Invalid embedding type '{}'. Valid options are: fast, best                                               :331
🚀 Started clearing all contexts in background.\n📊 Use 'knowledge status' to check progress.\n🆔 Operation ID: {}  :454
✅ Successfully cleared {} knowledge base entries                                                        :464
No context found with path '{}'                                                                          :477
No context found with name '{}'                                                                          :489
Context '{}' not found                                                                                   :539
Context with name '{}' not found                                                                         :577
No contexts found. Add a context first with 'knowledge add <name> <path>'                                :522
No context found with path '{}'\nAvailable contexts:\n{}                                                 :525
Operation '{}' not found. Available operations: {}                                                       :434
No active operations to cancel                                                                           :415
```

Note `:454` — a *second* nonexistent-command pointer, this time `'knowledge status'` without the
slash, which is the unparseable tool command of defect 1.

---

## Lessons for Zikaron

### What it gets right

**Removing the tool from the schema when disabled, rather than refusing at call time**
(`tool_manager.rs:727-728`). A disabled capability that still occupies a schema slot costs context
on every request and invites calls that can only fail. Zikaron's equivalent is D32's two tool sets:
we already do the right thing by shape, and this is confirmation that the alternative — ship it and
refuse — is the one that was not chosen by a team that had both options in front of them.

**Storage scoped to the agent identity rather than the cwd** is a genuine alternative to D8/D17
that we have not seriously examined. Q partitions by *who is asking* (agent config path hash);
Zikaron partitions by *where the work is* (project directory). Q's choice makes a specialist agent
carry its knowledge between projects. Ours makes a project's knowledge available to any agent
working in it. Both are defensible and they are not the same axis — worth naming in
`design/overview.md` §4 under D8 as a rejected-with-reasons alternative rather than an
unconsidered one, since a reader of the D8 index line would not know the agent-scoped option
exists.

**Progress, ETA and per-operation cancellation exist and are well rendered** (`cli/knowledge.rs:420-465`).
For any long-running indexing job, "N% • ETA: Ns" plus a cancel handle is the right user surface,
and it is more than Zikaron's consolidation currently offers.

**The `show`-returns-status-too consolidation** is a good instinct badly executed. One command that
answers "what do I have and what is happening" beats two, and `docs/knowledge-management.md:31`
records the merge deliberately. The failure was not updating the schema the model reads.

### What it gets wrong, and what we should take from it

**1. A tool description with no occasion is a tool that does not get called.** This is the finding
that matters most for us. Twenty-five words, all of them about *what the tool is* and none about
*when to reach for it* — while the `todo_list` tool sitting eight lines below it in the same file
spends 78 words on triggers, in capitals, and gets used. The contrast is inside one file by one
team, which makes it close to a controlled comparison. Zikaron's own 2026-08-14 change went the
other way on purpose — from "search whenever you are about to spend real effort" to four *detectable
occasions* — because a category requiring self-assessment fails mid-task (FINDINGS open question 1).
Q's description does not even attempt the self-assessment version. **This corroborates our change
from a second, independent codebase**, and it is the strongest external evidence the corpus has for
the occasion-list design. Do not overstate it: it is an argument from prompt shape, not a measured
recall rate, and we have no usage data from Q at all.

**2. No push path, and the documentation admits it.** `docs/knowledge-management.md:278` tells the
user to type "using your knowledge tools can you find…". That is a product shipping with the human
as the trigger mechanism. It is precisely the failure D12 exists to prevent, and it is the strongest
external argument for the `userPromptSubmit` injection we already built. Note the asymmetry it
creates: Q's user must remember the tool exists *and* phrase the nudge; Zikaron's user need not know
the store exists. Also note that Q could not easily have built our push path — its knowledge base
has no gists, so there is nothing cheap to inject. **The gist (D13) is what makes push affordable**,
and this is the first outside system where we can see the consequence of not having one.

**3. Returning bare chunk text with no provenance and no score is a real loss.**
`knowledge.rs:436-438` throws away the file path, the distance, and the context id, and silently
drops any result whose payload lacks a `text` key. The model cannot cite what it found, cannot
judge how good the match was, and cannot scope a follow-up search. Zikaron returns
`{uuid, gist, content}` with supersession labelling and a stated precedence rule
(`design/retrieval.md` §"Supersession: eligible, demoted, and labelled") — that is the right call
and this is what the alternative looks like in practice. **One thing to check on our side:** open
question 15 found our agent citing records by quoting gist prose rather than by subject. Q's design
makes that failure *mandatory* — prose is the only handle it returns. We should not congratulate
ourselves too early; we return the uuid, but we measured the agent preferring prose anyway.

**4. Five-per-context with no global cap is an unbounded injection.** Ten contexts, fifty chunks,
`chunkSize` user-settable to 1024, and no truncation at the tool boundary — `MAX_TOOL_RESPONSE_SIZE`
is enforced in three other tools and not this one. Zikaron's fusion depth and output budget are
separated deliberately (`design/retrieval.md`, *"Depth and budget are two different numbers"*) and M14's
`GIST_MAX_CHARACTERS = 1024` gives the injected block a *provable* ceiling. **This is the concrete
thing that bound buys**: Q has the same class of unbounded-content risk we closed in open question
11, and closed it nowhere. The parallel to M18 is also exact — Q's search result is the payload
spill problem without the spill: content that outgrows the channel, with silent truncation far
downstream instead of a pointer.

**5. Wrapping operational failures in `Ok(...)` destroys the error channel.** Sixteen distinct
failure strings reach the model as *successful* tool results beginning with "Failed". A model
cannot distinguish "the search ran and found nothing" from "the search crashed", and no retry logic
can key on status. Zikaron's error table (`design/architecture.md`) should be checked against this:
**the specific question to ask is whether any of our MCP tool paths return a failure inside a
success envelope.** I did not check, and it is worth ten minutes.

**6. The schema and the implementation disagreed in four places and no test noticed.** `status`
unparseable, `clear` missing its required field from the published schema, "text content" supported
nowhere, `cancel`'s "omit for all" wrong three ways. Every one is a *prose asserting what the
adjacent code contradicts* — the exact failure mode M18 spent 24 rounds on and named as its most
valuable methodological finding. Two things follow. First, **this is external corroboration that
the failure mode is structural rather than ours**: a large, well-resourced team shipped four
instances of it in 900 lines. Second, and more useful: **Zikaron has a mechanism Q does not.**
`tests/test_hook_write_policy.py` parses `design/write-policy.md` and compares it against the
shipped constant; `tests/test_harness_table.py` parses the D34 table. Q has no equivalent and paid
for it. The generalisable rule is narrower than "test your prompts": **wherever a document and a
constant must agree, the test should parse the document.** Worth auditing whether every
prose/constant pair in Zikaron has such a test, and worth noting the known cost — FINDINGS
current-state item 5 records that our own table-parsing test is what blocks naming the injection
budget's real unit, because the parser wants one number and one unit word and "UTF-16" has a digit
in it. The mechanism is right; that instance of it needs the fix already described there.

**7. The write path is the user's, not the agent's — and that is the deepest divergence.** Q's
model can call `add`, but `add` only points at files a human already wrote. There is no path by
which a lesson learned during the session enters the store. Q's knowledge base is a *retrieval index
over existing artifacts*; Zikaron's is a *record of what was learned by living through the work*
(D1). These are different products that share a retrieval mechanism, and the tell is that Q's
feature is squarely inside what our D1 scope line excludes: you *can* learn everything in a Q
knowledge base by reading the code, because it **is** the code. Kiro-cli shipping this built in is
therefore **not** evidence that the Zikaron niche is occupied — it is evidence that the adjacent,
easier niche is. The honest caveat: I have not traced kiro-cli's own version, only this
predecessor, and the FINDINGS note that kiro "ships this knowledge tool built in" may describe
something that has since diverged.

**8. One design question this raises for us, unresolved.** Q gives the model destructive verbs
(`clear`, `remove`) behind an all-or-nothing permission gate that discards the operation
(`eval_perm`'s `_ = self`, `knowledge.rs:529`). So an agent trusted to search is thereby trusted to
delete everything. Zikaron's D16 soft-delete makes our equivalent recoverable, which is the better
answer — but it is worth noting *why* Q's gate is coarse: the permission is evaluated against a tool
*name*, and its config schema has no vocabulary for operations. If we ever expose Zikaron's tools
through a harness whose permission model is name-scoped only, we inherit the same flattening, and
D16 is the only thing standing behind it. That is an argument for D16 being load-bearing rather than
merely tidy, and it is not currently recorded as one.

### Net assessment

The indexing engine is the part that had attention paid to it. The agent-facing integration reads
as a thin wrapper written once and not revisited: no tests, four schema/implementation
contradictions, two dead pointers to commands that do not exist, a documented capability that
cannot be performed, and no prompt integration whatsoever. For Zikaron the useful conclusion is not
"Q did this badly" but **the specific shape of what was skipped**. Every skipped piece is something
we have already built and can now say is load-bearing rather than speculative: the occasion list
over a bare capability statement, the push path over relying on the user to prompt, the gist that
makes push affordable, the provable output bound, the structured return with provenance, and the
tests that parse the prose. This is the counterfactual for a memory system built without them.
