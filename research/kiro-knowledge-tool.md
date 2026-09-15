# kiro-cli's `knowledge` tool: what it does, and whether Zikaron needs an equivalent

## Brief

Zikaron's D1 says Zikaron is **not** a codebase knowledge base — "a separate system handles code
structure, symbols and repo maps." In kiro-cli, the candidate for that separate system is the
built-in experimental `knowledge` tool. We are migrating to Claude Code, which has no equivalent.
This note documents exactly what kiro-cli's tool does — its indexing mechanics, agent-facing
surface, update/staleness semantics, retrieval behavior, scoping, and experimental-status caveats —
so the researcher can decide whether Zikaron (or something else) needs to fill that gap in Claude
Code, and so that a later source-tracing pass has a documentation baseline to check against.

## Methodology

Read the primary source in full, then followed its linked pages and searched for adjacent kiro-cli
docs (settings reference, CLI commands reference, built-in tools reference, experimental features
overview). All via WebFetch against the live kiro.dev docs site plus one WebSearch to locate the
built-in-tools reference page (not linked from the knowledge-management page itself). No source code
was read — this note is documentation-only, as requested; a gap noted here is a gap for the
source-tracing pass to answer, not something to be guessed.

Queries/pages consulted:
- `https://kiro.dev/docs/cli/experimental/knowledge-management/` (primary)
- `https://kiro.dev/docs/reference/settings/` (config keys for `knowledge.*`)
- `https://kiro.dev/docs/cli/chat/context/` (how knowledge bases relate to other context mechanisms)
- `https://kiro.dev/docs/reference/cli-commands/` (checked for `/knowledge` — not present there)
- `https://kiro.dev/docs/reference/built-in-tools/` (the model-facing `knowledge` tool, and the
  separate `code` tool)
- `https://kiro.dev/docs/cli/experimental/` (experimental-status definition and feature list)
- WebSearch: `kiro-cli knowledge tool semantic search tool name model calls "knowledge" MCP tool`
  (surfaced the built-in-tools page and unrelated third-party/Crew material, noted below and
  excluded from the main synthesis as out of scope)

## Findings

### 1. What the tool actually is

A **knowledge base** is a named, persistent index of text-based content, built from either a file
or a directory. Per the docs it indexes: "Text files: .txt, .log, .rtf, .tex, .rst," Markdown, JSON,
config formats (.ini, .conf, .cfg, .properties, .env), data formats (.csv, .tsv), and a long list of
source-code extensions (Rust, Python, JavaScript, Java, C++, Go, Ruby, PHP, Swift, Kotlin, C#,
Shell, HTML, XML, CSS, SQL, YAML, TOML), plus special files like `Dockerfile` and `Makefile`.
"Binary files [are] ignored during indexing." Each entry is a named object with metadata including
"creation dates, item counts, and persistence status," and carries its own include/exclude glob
patterns.

**How many a user can have:** the docs do not state a cap on the *number* of knowledge base entries.
They do cap size per entry: `knowledge.maxFiles` ("Maximum files for indexing"), default 10,000 per
the knowledge-management page's stated default (the settings-reference page itself gives no default
value for any `knowledge.*` key — the 10,000 figure comes only from the knowledge-management page).

### 2. The agent-facing surface — two distinct things

**The slash-command / CLI surface** (human- or agent-typed in chat, not a tool call):
- `/knowledge show` — lists all entries with details
- `/knowledge add --name <name> --path <path> [--include pattern] [--exclude pattern] [--index-type Fast|Best]`
- `/knowledge remove <name|path>`
- `/knowledge update [path]` — refresh one entry or all entries; "Original include/exclude patterns
  are preserved"
- `/knowledge clear` — removes all entries
- `/knowledge cancel [operation-id|all]`

Notably, `/knowledge` does **not** appear on the general CLI commands reference page
(`docs/reference/cli-commands/`), which documents `kiro-cli chat`, `kiro-cli agent`, `/chat new`,
etc. — it lives only under the experimental-features doc.

**The tool the model itself calls** is documented separately, on the built-in-tools reference page,
as one of 18 built-in tools:

> **Tool name:** `knowledge`
> **Description:** "Store and retrieve information in a knowledge base across chat sessions.
> Provides semantic search capabilities for files, directories, and text content."

The built-in-tools page states no parameter schema for this tool ("Parameters: None specified in the
documentation") and gives no example of a result shape the model sees — this is a **documentation
gap**, not a confirmed absence of parameters; treat the tool's actual call signature and return
shape as unknown from docs alone.

**Two index types**, set per-entry via `--index-type`:
- **Fast** — "Lightning-fast indexing," "Instant search," described as lexical/keyword-based
  (BM25-style, per the knowledge-management page's framing)
- **Best** — described as semantic, using embedding model **`all-minilm-l6-v2`**; "Intelligent
  search," "understands context and meaning," "Natural language queries"

This is a per-knowledge-base choice at creation time, not an automatic hybrid of both within one
entry as far as the docs state.

### 3. Indexing mechanics

- **Chunking:** "Large files split into searchable chunks." Configurable via `knowledge.chunkSize`
  ("Text chunk size for processing") and `knowledge.chunkOverlap` ("Overlap between text chunks") —
  **no default values are stated** for either key on the settings-reference page. The
  knowledge-management page separately cautions: "Very large files may be chunked, potentially
  splitting related content."
- **Embedding model:** `all-minilm-l6-v2`, used only for "Best" (semantic) index type. "Fast" entries
  use lexical/keyword indexing with no embedding step described.
- **Vector store / index persistence location:**
  - macOS: `~/Library/Application Support/kiro-cli/knowledge_bases/`
  - Linux: `~/.local/share/kiro-cli/knowledge_bases/`
  - Windows: `%LOCALAPPDATA%\kiro-cli\knowledge_bases\`
  No further detail on the storage format (no vector-store product/library named, e.g. no mention of
  SQLite, FAISS, LanceDB, etc. — documentation does not state).
- **Processing model:** "Asynchronous indexing" with background operations; indexing is cancellable
  via `/knowledge cancel [operation-id|all]`, which itself implies indexing runs as trackable
  background jobs with operation IDs, though the docs do not show an example ID or a progress-query
  mechanism beyond `/knowledge show`.
- **Index size on disk / indexing duration:** documentation does not state either.
- **File-type filtering:** via glob include/exclude patterns, both per-entry (`--include`/`--exclude`
  on `/knowledge add`) and as global defaults (`knowledge.defaultIncludePatterns`,
  `knowledge.defaultExcludePatterns` settings keys). Example patterns given: `*.rs`, `**/*.md`,
  `target/**`.
- **`.gitignore` respect:** documentation does not state that `.gitignore` is honored. No mention of
  it at all on any page consulted — this looks like a real gap rather than an omission from
  extraction, since the include/exclude pattern mechanism is described in some detail without ever
  referencing `.gitignore`.
- **Other limits:** `knowledge.maxFiles` caps files per knowledge base (docs state default 10,000 on
  the knowledge-management page). No stated max total size, max knowledge-base count, or max chunk
  count.

### 4. Update semantics — manual only, and the docs are silent on staleness

Refresh is **on-demand and manual**: `/knowledge update [path]` (single entry) or `/knowledge update`
(all entries), preserving the entry's original include/exclude patterns. There is **no watch mode**
and no mention of any automatic re-indexing trigger (no file-watcher, no git-hook, no periodic
re-scan) anywhere in the docs consulted.

**Staleness is not addressed** — the documentation does not state what happens to search results, or
to the index's internal consistency, when files change on disk after indexing and before the next
manual `/knowledge update`. There is no statement of whether stale results are flagged, silently
served, or excluded. This is the sharpest gap relative to Zikaron's own concerns (D11's repair-loop
design exists precisely because Zikaron treats staleness as a first-class failure mode) — kiro's
knowledge tool documentation simply does not engage with it at all.

One related caveat from the experimental limitations list: "No automatic cleanup of old or unused
contexts," and "Clear operations are irreversible with no backup" — both about lifecycle management
of entries, not about staleness of indexed content within a live entry.

### 5. Retrieval

- **Semantic** (Best/`all-minilm-l6-v2`): "Natural language queries," "Results ranked by relevance,"
  "Related concepts found even without exact word matches."
- **Lexical** (Fast): keyword/BM25-style, described only as fast and exact-match-oriented; no term
  "BM25" is quoted verbatim on the page, but the framing (lexical, keyword-based, instant) matches
  BM25-style search.
- The two are **not** described as fused into one hybrid result set — they are alternative modes
  selected per-entry at creation (`--index-type Fast|Best`), not simultaneous arms combined by e.g.
  reciprocal rank fusion. Documentation does not state whether a single query against a Fast-indexed
  entry vs. a Best-indexed entry ever combines results across multiple entries of different types.
- **No re-ranking step is documented.**
- **Result count / relevance threshold:** documentation does not state a fixed number of results
  returned, nor any relevance-score cutoff. (Contrast with Zikaron's explicit top-K=5 push and
  documented fusion depth — kiro's docs give no analogous numbers.)

### 6. Scoping

Knowledge bases are **agent-specific**, not user-global, project-global, or session-scoped in the
Zikaron sense:

> "Agent-specific knowledge bases": "Each agent maintains its own isolated knowledge base."
> "Automatic Scoping: /knowledge commands operate on current agent's knowledge base." No cross-agent
> access.

The context-management page's own decision framing says knowledge bases "operate ... within the
current session context" — worth flagging as a point needing verification against source, since
"per-agent isolated" and "within the current session" are stated on different pages and it isn't
clear from docs alone whether an agent's knowledge base persists across sessions (the "across chat
sessions" phrase in the tool's own description — "across chat sessions" — suggests persistence
beyond one session) or whether "session context" there just means the currently active agent
context. **Documentation does not fully resolve this**; flagging for source-tracing.

Working-directory interaction: a knowledge base is built from an explicit `--path` at `/knowledge
add` time, not implicitly from cwd. Documentation does not state whether relative paths resolve
against cwd at add-time or query-time.

### 7. Experimental status — quoted caveats

Global experimental-feature language (`docs/cli/experimental/`):

> "These features may change or be removed at any time. The experience might not be perfect. Use at
> your own discretion in production workflows."

Enabled via `/experiment` or a per-feature setting: `kiro-cli settings chat.enableKnowledge true`.
Knowledge management is one of seven listed experimental features (alongside Tangent Mode, TODO
Lists, Thinking Tool, Checkpointing, Context Usage Percentage, Delegate).

Knowledge-management-specific limitations quoted from that page: "No automatic cleanup of old or
unused contexts," and "Clear operations are irreversible with no backup." Also: "Very large files
may be chunked, potentially splitting related content" (a caveat about chunking correctness, not
about a hard size limit).

**What the docs explicitly say it is NOT for:** documentation does not state this directly — no
"do not use this for X" language was found. The closest thing is the context-management decision
flowchart's *positive* framing (see §8) implying it is unsuited to small, always-needed context,
which is the inverse of an explicit exclusion.

### 8. Relationship to other kiro context mechanisms

The `docs/cli/chat/context/` page draws an explicit contrast between **context files / agent
resources** (always-loaded, token-consuming) and **knowledge bases** (indexed, queried on demand):

> "Context files and agent resources consume tokens from your context window on every request,
> whether referenced or not."
>
> "Knowledge bases are searched on-demand by Kiro when relevant information is needed, making them
> ideal for large reference materials."

Its decision flowchart: "Is your content larger than 10MB or contains thousands of files? Yes → Use
Knowledge Bases." Context management is framed around three other approaches — Agent Resources,
Skills, and Session Context — with knowledge bases as "a fourth, indexed-search alternative designed
to preserve context window space for massive codebases or documentation" (my synthesis of the
page's framing, not a verbatim quote).

**No page found compares knowledge bases to steering files, hooks, or MCP directly** — those are
listed as separate sidebar topics but the knowledge-management and context-management pages do not
cross-reference them by name in the content extracted.

### An important adjacent finding: `knowledge` is not kiro's only code-facing tool

The built-in-tools reference lists a **separate** tool, `code`:

> **Description:** "Provides code intelligence capabilities including symbol search, LSP
> integration, and pattern-based code search and rewriting."

Example given: a natural-language query ("Find the UserRepository class") resolves to a symbol match
via LSP ("Class UserRepository at src/repositories/user.repository.ts:15:1"). Permissions: "Symbol
lookups and code edits within your workspace execute without prompting" (edits outside the workspace
need approval). "This tool has no configuration options." **The docs do not mention AST, symbol
graphs, call graphs, or repo maps** for this tool by name — it is described only as LSP-backed symbol
search plus pattern-based rewriting.

This matters for Zikaron's framing: D1's "a separate system handles code structure, symbols and repo
maps" is arguably describing **`code`** (LSP/symbol search), not **`knowledge`** (generic semantic
text indexing) — the two are documented as distinct built-in tools with non-overlapping
descriptions. `knowledge` is general-purpose text/document indexing (any file type in its list, not
specifically code-structure-aware), while `code` is the LSP-backed structural tool. Neither the
knowledge-management page nor the built-in-tools page states that `knowledge` performs any
AST-aware, symbol-aware, or structure-aware chunking — its chunking is described only in terms of
text size (`chunkSize`/`chunkOverlap`), with no code-aware boundary logic documented. If Zikaron's D1
scope line was written assuming `knowledge` was the "separate system," this note suggests the more
precise mapping is: **`code`** handles structure/symbols/repo maps, and **`knowledge`** is a generic
document/text semantic-search layer that happens to also accept source files as one of many indexed
formats. This distinction should be verified against source before revising D1's framing, since it
was inferred from two documentation pages describing sibling tools rather than from any page that
explicitly contrasts them.

### Noted but excluded as out of scope

WebSearch surfaced material about **Kiro Crew** (`docs/crew/features/knowledge/`), a distinct
product surface from kiro-cli, with its own `local_knowledge_search` MCP tool — not read in detail,
since the brief is specifically about kiro-cli. Also surfaced: third-party/community projects
(`Kiro-Ception`, `kirograph`) that build memory/knowledge-graph layers *for* Kiro — these are
third-party reconstructions, not vendor documentation, and are not cited as authoritative for any
claim above; noted here only so they are not mistaken for primary sources later.

## Evidence quality and gaps

Everything above is drawn from kiro.dev's live documentation as of 2026-09-14, via WebFetch
summaries of the rendered pages (not raw HTML/markdown source, so exact formatting — e.g. whether a
quoted phrase is a table cell, a bullet, or prose — is not always preserved; treat quoted text as
faithful to content but not necessarily to original layout). No source code was consulted. Several
load-bearing facts are explicitly marked "documentation does not state" above:
- the `knowledge` tool's call parameters and result shape as seen by the model
- default values for `chunkSize`, `chunkOverlap`, `maxFiles` on the settings-reference page itself
  (only the knowledge-management page states a 10,000-file default)
- `.gitignore` handling
- index size on disk and indexing duration
- staleness behavior when files change under a built index
- result count and relevance-threshold for retrieval
- whether Fast and Best results are ever combined/fused
- exact scope lifetime of "per-agent" knowledge bases (persists across sessions vs. session-bound)
- any explicit "not for X" statement

These are exactly the gaps to close with a source-tracing pass, per the brief's framing — this note
deliberately stops at "documentation does not state" rather than inferring behavior from kiro's
general architecture or from Zikaron's own design assumptions.

## Sources

1. [Knowledge management — Experimental — CLI — Kiro Docs](https://kiro.dev/docs/cli/experimental/knowledge-management/) — primary source
2. [Settings reference — Kiro Docs](https://kiro.dev/docs/reference/settings/) — `knowledge.*` config keys
3. [Context management — CLI Chat — Kiro Docs](https://kiro.dev/docs/cli/chat/context/) — contrast with context files/agent resources
4. [CLI commands reference — Kiro Docs](https://kiro.dev/docs/reference/cli-commands/) — checked, `/knowledge` not present here
5. [Built-in tools — Reference — Kiro Docs](https://kiro.dev/docs/reference/built-in-tools/) — the model-facing `knowledge` tool and the separate `code` tool
6. [Experimental features — CLI — Kiro Docs](https://kiro.dev/docs/cli/experimental/) — experimental-status definition and full feature list
7. [Kiro CLI: Augmenting Knowledge — AWS Builder Center](https://builder.aws.com/content/35E6MxLzBwBySJcVJhO9m4pPJl2/kiro-cli-augmenting-knowledge) — surfaced by search, not read in depth; third-party/community, not vendor doc
8. [Knowledge — Features — Crew — Kiro Docs](https://kiro.dev/docs/crew/features/knowledge/) — different product surface (Kiro Crew, not kiro-cli); noted, not analyzed
9. [Kiro-Ception (GitHub)](https://github.com/voidptr/Kiro-Ception) and [kirograph (GitHub)](https://github.com/davide-desio-eleva/kirograph) — third-party community projects building on/around Kiro; not vendor-confirmed, not used as evidence for any claim above
