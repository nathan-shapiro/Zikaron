# Zikaron

**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") gives a coding agent the two kinds of
knowledge a project holds that are not in its source code.

**Tribal knowledge — memory.** What nobody wrote down, because it was learned by living through the
work: how to build and test it, which step fails silently, which env vars the integration tests need,
which API is not safe to use yet and why, what was already tried and how it failed. Agents write
this as they go and read it back in later sessions.

**Institutional knowledge — knowledge bases.** What the project *did* write down, indexed and made
searchable: a docs tree, a directory of run books, design records, a vendored dependency's manual.
The agent searches a named corpus and gets fragments back with real line ranges, quoted verbatim.

The two differ in where they come from and therefore in who maintains them. Memory accumulates
without anybody curating it, and goes stale when the code moves under it — so the agent that a memory
misleads is the one expected to correct it. A knowledge base is a view onto files somebody else owns,
and it goes stale when those files change — so you refresh it, and a result from a file that has
changed since it was indexed comes back marked as such.

The test for whether something belongs in **memory**: *could you learn it by reading the code?* If
yes, it is out of scope. That store is for what cost somebody time to discover, and would otherwise
be discovered again by the next agent, at full price. A knowledge base has no such test — it is
whatever corpus you point it at.

It runs entirely on your machine: SQLite databases under `.zikaron/`, a local embedding model, and a
small background service on a Unix socket. **Zikaron reaches the network for exactly one thing** —
the embedding-model download described under [Install](#install), which it repeats if the cache it
lands in is cleared — and there is no account to create.
What it retrieves still reaches your model, since that is the point: the gists a hook injects and
the groups a consolidator is handed travel to it the way the rest of your session does.

---

## How it works

The two halves share a substrate — the same store directory, the same embedding model, the same
service, the same hybrid retrieval — and differ in everything above it. Memory is described first
and at greater length because it is the half with a write path, a policy and a consolidation step;
knowledge bases are the simpler half and are covered under
[Knowledge bases](#knowledge-bases-searching-what-the-project-wrote-down) below.

**Memories are short records** — a one-line *gist* and a longer *content* body. The gist exists to let
a future agent decide whether to read further; the content carries the detail. Records live in two
tiers: new ones land in a **journal**, and consolidation later folds the journal into **long-term**
records, merging what belongs together and retiring what does not.

**Reading happens two ways.** Before every message you send, a hook injects the few most relevant
gists into the agent's context, so recall costs no tool call and no decision. When the agent wants
more, it calls `zikaron_memory_search` for a wider look or `zikaron_memory_fetch` for a full record. Retrieval is
hybrid: a vector search over a local embedding model and a full-text search over the same corpus,
their rankings fused, so an exact identifier and a vague description both find their record.

**Writing is the agent's own judgment.** Nothing summarizes your session behind your back and no extra
model runs on the write path. A policy injected when the agent starts tells it what is worth recording;
it then calls `zikaron_memory_remember`, `zikaron_memory_amend` or `zikaron_memory_retire` itself. Near-duplicates are
detected at write time and handed back to the agent to resolve rather than silently dropped, and
nothing is ever hard-deleted — a retired record stops surfacing but stays auditable.

**Consolidation is manual and runs as a separate agent.** You ask for it; a subagent with the four
consolidation verbs and no way to search or fetch is handed groups of related entries that code
selected for it, and decides for each whether to merge, promote or discard. Keeping it separate
means a fresh context, and it cannot write outside the group it was handed — every verb refuses a
uuid that was not served to it. Under kiro those four verbs are its whole surface. Under Claude Code
it is also granted a file-reading tool, because a group too large to return is handed to it as a
file instead; that grant cannot be restricted to one path there, so what keeps it off everything
else is its prompt.

**No agent can put its own words into the text a knowledge base searches.** The searchable content
comes only from the files on disk: an indexer walks the tree you pointed it at, chunks them, and
stores the text with its line ranges. What an agent *does* write is the corpus's **definition** —
the name, description, root and filters it passes to `zikaron_knowledge_add`, of which
`zikaron_knowledge_rename` changes the name alone, and the name and description come back on every
search as the label on each group — plus a build's own metadata and the four search counters
described under [Files and logs](#files-and-logs). The agent reaches them through
`zikaron_knowledge_search` and a handful of management verbs — every tool name carries its
subsystem, `zikaron_memory_*` or `zikaron_knowledge_*`, so a model choosing between the two stores
reads which one it is addressing before it reads a description. Consolidation never touches them.

### The pieces

| | What it is |
|---|---|
| **core** | The library: the store, retrieval, chunking, consolidation, and the knowledge index. No process concerns, no transport. |
| **service** | A long-running process per project. Holds the embedding model in memory and the databases open, and answers requests over a Unix socket. Starts itself when needed and stops itself when idle. |
| **MCP server** | Translates the agent's tool calls into requests to the service. One process per agent instance; loads no model. |
| **hook** | A single-shot executable your agent runs on start, before each message, and — under Claude Code — when it spawns a subagent. Deliberately tiny; loads no model and never touches the databases directly. |
| **indexer** | A detached process started per knowledge-base build — by the service when an agent asks, or by the `zikaron.knowledge` command when you do. It outlives the call that started it, loads a model, saturates a core for a minute or more, and exits when the build finishes. If you see one in `ps`, that is a corpus building, not a runaway. |

The service exists for one measured reason: loading the embedding model costs about **780 ms**, and
retrieval sits on the path of every message you send. Keeping the model resident turns that into a
**~7 ms** embed and a **~9 ms** round trip. (The indexer pays that same load cost once per build, in
its own process, which is why it is detached rather than run inside the service.) The hook stays
thin for the same reason — it runs once per message, and it costs about **50 ms** end to end.

If the service is not running, the hook starts it and moves on. If anything fails, the hook writes one
line to a log, tells the agent to mention it to you, and exits cleanly — it never blocks your message
and never fails your turn.

---

## Requirements

- **Linux, or macOS on Apple Silicon.** The transport is a Unix domain socket and the paths assume a
  POSIX filesystem.
  **Linux x86_64 is verified; Linux arm64 and macOS are supported but not yet verified** — nothing
  has run on Linux arm64, and the *advisory* macOS CI job is configured but has not yet had a run,
  so treat macOS as "expected to work, untested". **Intel Macs and Windows are not supported**:
  Intel Macs would mean pinning a year-stale `onnxruntime` on two of the three interpreters and a
  hard install failure on the third, and Windows needs a second RPC transport rather than a flag.
  `design/distribution.md` §1 has the detail.
- **Python 3.12 or newer.** Tested versions: 3.12, 3.13, 3.14.
- **A supported harness installed: `kiro-cli` or Claude Code.** Zikaron installs hook and MCP
  entries whose only reader is that harness's own binary, so the installer checks it is on your
  `PATH` and **refuses if it is not** — writing those files where nothing reads them would exit 0
  and leave you with no Zikaron tools and no error to search for. Pass `--print-only` to see exactly
  what would be written without writing it, which is how to provision a machine before its harness.

  **The installer itself is an ordinary program and does not need a harness *running* in order to
  execute.** Run it from any shell — a terminal, an ssh session, a container build. It works out
  which harness a project is for from the project itself (a `.claude/` or a `.kiro/` directory),
  falls back to the `CLAUDECODE` marker when the project says nothing, and **refuses — telling you
  to name the harness — when the project names both, or when neither the project nor the marker
  says**. Under kiro it additionally validates the consolidator's model id against the binary,
  because kiro substitutes an unknown model silently; Claude Code refuses one itself, at
  spawn, so no such check is needed there.

## Install

**Two supported paths, and the first is recommended for a reason worth reading.**

```bash
# Recommended. `--managed-python` is not optional; the paragraph below says why.
uv tool install --managed-python git+https://github.com/nathan-shapiro/Zikaron.git
```

```bash
# Alternative — a source checkout on a Python you already have.
git clone https://github.com/nathan-shapiro/Zikaron.git
cd Zikaron
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Why `uv` is recommended.** Zikaron's vector search is a loadable SQLite extension, and whether an
interpreter can load one at all is decided when *that interpreter* was compiled — and it is reported
off in some widely used builds, python.org's macOS installer and conda-forge among them. The
interpreters `uv` fetches were **measured** here and have it; those two were not, so treat them as a
reported risk rather than a verified failure. A host Python may well work; it is simply the path
where "it installed fine and then retrieval does not work" is possible.

**And that is why `--managed-python` is in the command.** Without it, uv falls back to a host
interpreter whenever it has not already downloaded one of its own — which is the case right after you
install uv. Measured, running both forms against empty uv directories: **with** the flag, uv
downloaded its own CPython and built the tool environment on it; **without** it, uv used
`/usr/bin/python3.12` and downloaded nothing. So the plain command hands you the host build on a
fresh machine, which is the outcome the recommendation exists to avoid.

**`uv` is used at install time only.** Zikaron never invokes `uv run` or `uvx` when it runs: the hook
executes once per message you type, and a resolver in that path costs about 20 ms every time. What
gets installed is ordinary console scripts with a fixed interpreter.

**First use downloads a 64 MB embedding model** from Hugging Face, so the very first search is slow
and needs the network. Everything after it is local. **Known limitation**: the model is cached under
the system temporary directory rather than a durable per-user one, so a reboot can cost you the
download again. It is outside your project either way, so no `.gitignore` entry helps. A durable
cache is planned.

Then install into the project you want Zikaron in. The installer is invoked as `python -m
zikaron.install` and has no command of its own yet, so you need the path to the interpreter Zikaron
was installed into. That differs by which path you took above:

```bash
# If you used `uv tool install`:
ZK="$(uv tool dir)/zikaron/bin/python"

# If you used a source checkout:
ZK=/path/to/zikaron/.venv/bin/python
```

A single `zikaron install` command is planned.

Under **Claude Code**:

```bash
cd /path/to/your/project
"$ZK" -m zikaron.install --project .
```

Under **kiro**, name the config for the agent you actually work in:

```bash
"$ZK" -m zikaron.install --project . --agent .kiro/agents/<your-agent>.json
```

Pass `--harness claude-code` or `--harness kiro` to override the detection described under
[Requirements](#requirements). `--agent` is kiro-only, and passing it under Claude Code is refused
rather than ignored — there its entries go into fixed project files instead. To see exactly what
would be written without writing anything, pass `--print-only` on either harness.

Finally, if the project is a git repository, tell git to ignore the store — and, under Claude Code,
the MCP config too:

```bash
echo '.zikaron/' >> .gitignore
echo '.mcp.json' >> .gitignore     # Claude Code only; see below
```

**`.mcp.json` is the awkward one.** Claude Code intends that file to be committed and shared — that
is what "project-scoped" means — but the entries Zikaron writes into it name absolute paths inside
*your* virtualenv, so a clone-mate gets a server that cannot start, plus an approval prompt for it.
This is the same objection that keeps the hook entries out of the checked-in `settings.json`; the
difference is that `settings.local.json` exists as an untracked sibling and `.mcp.json` has no
equivalent. With no per-project, machine-local MCP scope to move it to, the choice is yours: ignore
the file, or accept that each clone re-runs the installer. Re-running is safe — a differing Zikaron
entry is refused loudly rather than merged over.

The installer does not edit `.gitignore` for you; appending to it is not a decision an installer
should make silently. But it matters and is easy to forget: without it the memory database and its
write-ahead log, every knowledge base's index and the service logs all show up as untracked, and a
routine `git add -A` commits the lot. None of it is useful to anyone else, and none of it is
reproducible from your repository.

What it writes under **kiro**, relative to the project:

| Path | What |
|---|---|
| `.kiro/agents/zikaron-consolidator.json` | the consolidation subagent: its model, its four tools, its prompt |
| `.kiro/skills/zikaron-consolidate/SKILL.md` | how to run a consolidation, and how to recover a stuck one |
| the agent config you named | `hooks` for start and per-message, an `mcpServers` entry, `@zikaron` in `tools` and `allowedTools`, the consolidator in `toolsSettings.crew`, and the skill in `resources` |

and under **Claude Code**:

| Path | What |
|---|---|
| `.claude/agents/zikaron-consolidator.md` | the consolidation subagent, as frontmatter plus its prompt |
| `.claude/skills/zikaron-consolidate/SKILL.md` | how to run a consolidation, and how to recover a stuck one |
| `.claude/settings.local.json` | three hooks — session start, per-message, and per-subagent — plus both approval keys, `enabledMcpjsonServers` and `permissions.allow` |
| `.mcp.json` | both servers: `zikaron` for your own tools, `zikaron-consolidator` for the consolidation verbs |

**`settings.local.json`, not `settings.json`**, and it matters if you commit your settings: the hook
entries name absolute paths inside *your* virtualenv, so they are meaningless in anyone else's clone.
The third hook is the one with no kiro counterpart — it hands the write policy to each subagent you
spawn, which kiro achieves by firing its ordinary hooks for subagent sessions instead.

It backs up any file it merges into (`<file>.bak`, and the first backup wins), and **refreshes a
shipped file whose contents are not what this version ships** — after backing it up, and saying so.
That is what makes upgrading work, and the cost is that a hand-edit to a shipped file is reverted on
the next install rather than kept. Under kiro it also validates the consolidator's model id, because
an unknown model would otherwise be silently replaced by the harness's default.

`@zikaron` has to be in `tools` or Zikaron's tools are simply absent: the `mcpServers` entry
*configures* the server and `tools` is what *selects* from it. It goes into `allowedTools` too, so the
agent can record without interrupting you. That is deliberate rather than lax — the whole design leans
on the agent writing freely, and a permission prompt per write both suppresses that and trains you to
click through prompts. What it trusts is still narrow, but it is not only rows. The memory tools read
and write rows in a local database. The knowledge tools additionally **read a directory tree you
name, which may sit outside the project** — a docs tree or a vendored dependency is a legitimate
corpus, so only degenerate roots (the filesystem root, your home directory itself) are refused — and
copy its text into an index, in a detached process that works a core for minutes. No network either
way **once the model is cached** — the only fetch Zikaron makes is the embedder download described
above, which a cleared temporary directory can make the indexer pay again — and nothing is written
into your project outside `.zikaron/`. A mistaken memory write is *recoverable* rather than
undoable: `zikaron_memory_retire` withdraws a record from ordinary retrieval and leaves it
auditable, while an amend overwrites prose that nothing restores. A mistaken
`zikaron_knowledge_remove` destroys that corpus's index, which is rebuildable from the files it was
built from but not instantly. Pass `--no-trust-tools` if you would rather approve each one.

**That trust stops at the primary agent's tools.** Spawning the consolidator is a separate grant — a
subagent with its own model invocation, four mutation verbs and, under Claude Code, a file read —
and the installer does not make it for you. **Under kiro** that grant is
`toolsSettings.crew.trustedAgents`, which the installer only ever reads: starting a consolidation
therefore asks your permission once, and adding `zikaron-consolidator` there yourself is what stops
it. Claude Code has no such key, so there is nothing to add and nothing withheld.

**Three keys under kiro only, and Claude Code has none of them.** The consolidator also has to be
reachable by the `subagent` tool, so if your config already restricts which agents may be spawned
(`toolsSettings.crew.availableAgents`), the installer adds `zikaron-consolidator` to that list. If
you have no such restriction it leaves it alone — an empty list means *every* agent is available,
and writing one entry into it would restrict you to just this one. The skill is also declared in the
agent's `resources` unless something there already covers it. Skills normally arrive by inheritance,
so that entry is usually redundant — but it is the only thing that makes the skill loadable if you
have set `chat.disableInheritingDefaultResources`, and declaring a resource does not disable
inheritance, so it can only help.

**One thing the kiro install deliberately does not do:** add the `subagent` tool itself, which the
consolidation skill needs in order to spawn the consolidator. Its reach is much wider than Zikaron's
own tools, so that grant stays yours. The installer says so if it is missing. Under Claude Code none
of this arises — the shipped skill is an ordinary project file, and the consolidator is spawned
through whatever subagent tool the harness already gives your agent.

**Installing into a clone of the Zikaron repository itself, under kiro,** finds
`.kiro/agents/zikaron-consolidator.json` already tracked, carrying whichever virtualenv path the last
committer had. The installer notices that the file names a different install, backs it up, and
rewrites it for yours. Under Claude Code there is nothing tracked to collide with — the consolidator
config is not in this repository — so the installer simply writes it.

### What to know under Claude Code

**There are three approval gates and the install answers two of them.** `enabledMcpjsonServers`
decides whether a project-scoped `.mcp.json` server **loads** at all; `permissions.allow` decides
whether each tool **call** goes through without a prompt. Both are written into
`settings.local.json`. The one it does not answer comes first: Claude Code's own folder-trust
dialog, on first entry to a directory, which is yours to answer — and it reads the
`permissions.allow` entries back at you as a warning that this folder pre-approves tool permissions.
If Zikaron's tools are missing after a fresh install, check `/mcp` for a server pending approval
before looking anywhere else — an unapproved server is simply absent, with nothing saying why. If
they are present but every write interrupts you, it is `permissions.allow` that did not take.

**A fourth prompt is deliberately left live.** The first time a consolidation meets a group too
large for the harness to deliver, the group is written to a file and Claude Code asks whether the
consolidator may read from the runtime directory. Allow it for the session — and expect it again in
the next one, because session scope is the only scope that grant has. It is not pre-answered on
purpose: a file-reading tool cannot be restricted to one path in subagent config, so this prompt is
the only point at which that grant is put to you as a question.

`--no-trust-tools` withholds both written keys for *your* tools. It does not withhold them for the
consolidator's: a subagent has nobody to answer a permission prompt, so an unapproved **MCP** tool
there does not ask, it fails at the moment consolidation needs it. The file read above is the
exception — that one prompts.

**Your own agent can see the four consolidation verbs**, and that is not a misconfiguration. A server
has to be registered for the whole session before any subagent can reach it, so registering the
consolidator's server exposes it to you too. Under kiro the two tool sets are separated mechanically;
here it is the prompt that keeps them apart. Nothing in the store is at risk from it — the never-lose
guard, the receipts and the lease are untouched — but an unauthorized consolidation would spend
tokens and could write a poorly-judged long-term record. `permissions.deny` is **not** the fix: it is
global and unregisters the tool, after which the consolidator itself refuses to start.

### Options

| Flag | Effect |
|---|---|
| `--project <dir>` | the project to install into. Also where the store lives (default: the current directory) |
| `--harness {auto,kiro,claude-code}` | which harness to install for. `auto` reads the project, then the `CLAUDECODE` marker; it refuses when the project has **both** dotdirs, and when neither source says |
| `--agent <path>` | **kiro only.** Merge the hook and MCP entries into that config, after backing it up |
| `--print-only` | print what would be written and write nothing at all |
| `--model <id>` | the consolidator's model (default: `claude-sonnet-5` under kiro, `sonnet` under Claude Code) |
| `--format {object,array}` | **kiro only.** Which hook format to write when the target config has none yet |
| `--no-trust-tools` | do not pre-approve Zikaron's own tools, so every Zikaron tool call asks permission |
| `--force` | replace a symlink at a shipped path, and overwrite entries wired to a different Zikaron install that would otherwise be refused |

Both hook formats kiro accepts are supported, and a config that already uses one keeps it: kiro
rewrites a config in whichever format it read, so mixing them in one file has no defined meaning.

## Verify

Start a session with the agent you installed into. On start you should see nothing unusual — the write
policy goes into the model's context, not to your terminal. Then, from the project directory:

```bash
# a service should be running for this project after your first message
pgrep -af zikaron.service.main

# one line per hook failure, write-policy-override note, or session/environment mismatch; absent means none happened
cat .zikaron/hook.log
```

Ask the agent to remember something, then start a fresh session and ask about it. If the memory comes
back, the whole loop works: write through MCP, injection through the hook, retrieval in between.

## Using it

**Writing.** Say "remember that" when you want something kept, or leave it to the agent — the injected
policy tells it what is worth recording. Its bias is toward recording, because the common failure is an
agent that records nothing.

**Reading.** The relevant gists arrive before every message you send. The agent fetches full records
when it wants the detail, and can search when the injected few are not enough.

**Consolidating.** Ask the agent to consolidate project memory once the journal has built up — after a
stretch of real work, or at the end of a task. It loads the shipped skill and spawns the consolidator.
If a run ever seems stuck, ask again: a second invocation takes the abandoned run over and replans.

### Knowledge bases: searching what the project wrote down

Memory holds the **tribal** knowledge agents learned by working here. A **knowledge base** is the
**institutional** half: a named, indexed corpus of text files the project already has — a docs tree,
a directory of run books, a vendored dependency's documentation. The agent searches it and gets back
fragments with line ranges, quoted verbatim, so it can read further or quote them as they stand.

Ask the agent to create one and it will, without leaving the session: *"index the docs directory as
a knowledge base called design docs"*. It has tools to list, create, rename, refresh, inspect and
remove them. The same verbs are available at a shell, for when no agent is running — using the same
`$ZK` interpreter path the install section works out, since this command has no front door of its
own yet either:

```bash
"$ZK" -m zikaron.knowledge list
"$ZK" -m zikaron.knowledge add "design docs" --path ./design \
    --description "Architecture and design records"
"$ZK" -m zikaron.knowledge refresh            # every corpus; name one to narrow it
"$ZK" -m zikaron.knowledge status "design docs"
```

Three things are worth knowing before you point one at a directory.

**Building takes minutes and runs in the background.** `add` and `refresh` start a build and return.
A **first** build answers nothing at all while it runs: the corpus reports `reindex_required` for
its whole duration, and only becomes searchable when the build completes. A later `refresh` keeps
answering from what is already indexed while it works — as does a `--full` one — with the exception
of a rebuild forced by a changed embedding model, which empties the corpus before it starts and so
answers nothing until it finishes. `status` says how far it has got.

**Nothing updates an index on its own.** There is no watcher and no schedule: a corpus drifts from
its files until somebody refreshes it. A search says so when it can — a result whose file has
changed since it was indexed comes back marked `stale`.

**An index holds the text of every file in it.** Do not point one at a directory holding
credentials. The databases are `0600`, the same as `memory.db`, and they are under `.zikaron/`, so
the `.gitignore` line above already covers them — but what is *in* one is searchable by every agent
working in this project.

---

## Configuration

Entirely optional — every key has a working default. Two TOML files, later wins per key:

```
~/.config/zikaron/config.toml     applies to every project
<project>/.zikaron/config.toml    this project only
```

An unknown key or a value of the wrong type is **fatal rather than ignored**, so a typo cannot silently
leave you on a default. Values are range-checked when the service starts.

```toml
[retrieval]
fusion_depth = 50          # how many candidates each arm contributes before fusion
rrf_k = 60                 # the rank-fusion constant; larger flattens the ranking

[consolidation]
group_max = 12             # members per group before it is split
run_lease = 1800           # seconds a consolidation run holds the store

[service]
idle_timeout = 1800        # seconds of inactivity before the service stops itself
```

### Everything that is tweakable

| Section | Key | Default | Range | What it does |
|---|---|---|---|---|
| `embedding` | `embed_model` | `BAAI/bge-small-en-v1.5` | any model your embedder can load | which embedding model to use. **Store-coupled (hard)** |
| `embedding` | `embed_dim` | `384` | ≥ 1 | that model's vector width. **Store-coupled (hard)** |
| `embedding` | `embed_prefix_query` | a retrieval instruction | free text | the prefix prepended to a query before embedding |
| `indexing` | `chunk_max_tokens` | `450` | 64–8192 | how large a chunk may get before a record is split. **Store-coupled (soft)** |
| `indexing` | `gist_max_tokens` | `64` | 8–256 | the longest gist a write may carry |
| `indexing` | `knowledge_max_file_bytes` | `1048576` | 1–67108864 | **knowledge bases:** the largest file an indexer will read; bigger ones are skipped |
| `indexing` | `knowledge_embed_batch` | `32` | 1–256 | **knowledge bases:** how many chunks an indexer embeds per batch |
| `retrieval` | `chunk_overfetch` | `8` | 1–64 | how many extra chunks the vector arm reads to cover its candidates |
| `retrieval` | `fusion_depth` | `50` | 1–500 | how deep each arm goes before the two are fused |
| `retrieval` | `rrf_k` | `60` | ≥ 1 | the rank-fusion constant |
| `retrieval` | `supersession_penalty` | `0.5` | >0.0–1.0 | how far a replaced record is demoted rather than hidden — the score is multiplied by it, so zero is refused because it would hide the record rather than demote it |
| `retrieval` | `retired_penalty` | `0.5` | >0.0–1.0 | the same, for a retired record when one is asked for |
| `retrieval` | `supersession_max_depth` | `32` | 1–1024 | how far a chain of replacements is followed |
| `retrieval` | `fts_query_max_terms` | `64` | 1–512 | the largest full-text query built from one prompt |
| `retrieval` | `knowledge_max_chunks_per_file` | `2` | 1–20 | **knowledge bases:** how many fragments one file may contribute to a result set |
| `retrieval` | `knowledge_snippet_max_chars` | `1200` | 80–24000 | **knowledge bases:** how much text a single returned fragment carries, counted in code points |
| `dedup` | `dedup_threshold` | `0.8` | 0.0–1.0 | how similar a new record must be to be offered back as a near-duplicate |
| `dedup` | `dedup_max` | `3` | 0–20 | how many near-duplicates are handed back at once |
| `consolidation` | `mutual_k` | `5` | 2–50 | how many neighbours each entry considers when grouping |
| `consolidation` | `orphan_edge_cutoff` | `0.65` | 0.0–1.0 | how close two entries must be to group without a shared anchor |
| `consolidation` | `anchor_cutoff` | `0.65` | 0.0–1.0 | how close an entry must be to a long-term record to be anchored to it |
| `consolidation` | `group_max` | `12` | 2–64 | members per group before it is split into shards |
| `consolidation` | `max_group_serves` | `3` | 1–16 | how many times one group may be re-served before it is abandoned |
| `consolidation` | `run_lease` | `1800` | 60–86400 | seconds a consolidation run holds the store |
| `consolidation` | `spill_threshold` | `27000` | 4096–1048576 | **Claude Code only:** bytes past which a consolidator tool result is written beside the socket instead of returned inline. Nothing spills under kiro, where the key has no effect |
| `service` | `idle_timeout` | `1800` | 60–86400 | seconds of inactivity before the service stops itself |
| `signals` | `signal_horizon_days` | `30` | 1–3650 | the window the write-policy instrumentation reports over |

**Three keys are coupled to what is already stored, at two severities.** The file says what you
want; the store records what was actually done, and a file that disagrees is *requesting* a change
rather than making one.

- **Hard — `embed_model`, `embed_dim`.** They describe the vectors already on disk, so changing
  either means reindexing. The two stores say so differently. The **memory store** refuses: the
  service will not start rather than serve a store whose configuration disagrees with its contents.
  **Every knowledge base** seeds the same two keys into its own metadata when it is created and
  **degrades instead of refusing** — a corpus whose recorded encoder no longer matches reports
  `reindex_required`, answers searches with no results, and is rebuilt whole by the next `refresh`.
  A corpus's own database is opened per call and never at startup, so one in this state does not
  keep the service down.
- **Soft — `chunk_max_tokens`, and only in the memory store.** There the file governs **new** writes:
  nothing refuses, nothing needs rebuilding, and the store simply ends up holding chunks cut at more
  than one size. A **knowledge base** seeds this key at creation like the other two and then ignores
  later changes to it, so changing it affects only corpora you add afterwards — an existing corpus is
  re-chunked at the value it was created with, even by a full `refresh`.

**Three further keys are frozen into a knowledge base alone**, by the same mechanism and with no
equivalent in the memory store: `rrf_k`, `fusion_depth` and `knowledge_max_file_bytes` are recorded
in a corpus when it is created and read from there afterwards — the first two on every search, the
third on every build — so changing them in the file affects only corpora you add afterwards.
`knowledge_max_file_bytes` can also be set per corpus when you add it. They carry no marker in the
table above because the severities are a property of the *memory* store, which these do not touch.

**The write policy can be overridden per project.** Put your own text at `.zikaron/write-policy.md`
and the session-start hook prints that instead of the shipped policy. An absent override is the
ordinary case and is silent. If one is there but is unreadable, empty, a symlink, not a regular
file, or sits in a store directory that is not yours alone — owned by another user, or carrying any
group or other permission at all — the shipped text is used and one line lands in `hook.log` saying
which. An override **too large for the harness's injection budget is
printed anyway**, with a line in `hook.log` — the harness truncates in silence, and a policy the
model received part of is worse than one you were told about. The policy print is the one path that
is never allowed to fail.

---

## Files and logs

Almost everything Zikaron writes for a project *while it runs* lives in one directory, and all of
it is `0600` or `0700`. The **installer** also writes harness config — the files tabled under
[Install](#install), plus a `.bak` beside anything it replaces.

```
<project>/.zikaron/
  memory.db          the store itself — never commit this
  memory.db-wal      SQLite's write-ahead log; part of the store
  memory.db-shm      SQLite's shared-memory index; part of the store
  knowledge/         one database per knowledge base, named by a generated id.
                     Absent until you create one
  config.toml        your per-project overrides, if you wrote any
  service.log        the background service: startup, resolved config, errors
  hook.log           one line per hook failure, write-policy-override note, or session/environment
                     mismatch. Absent means none happened. Not every line is a failure: an override
                     that is used but exceeds the injection budget is printed anyway and logged
  warmup.log         the small helper that warms the service when a session starts
  write-policy.md    your policy override, if you wrote one
```

**One thing the running system writes lives elsewhere, and it has to.** The service's Unix socket
and its lock file sit in `$XDG_RUNTIME_DIR/zikaron/` — or `/tmp/zikaron-<uid>/` where that variable
is unset, which is every Mac — named by a hash of the store's path, `0600` inside a `0700`
directory. A socket belongs on a runtime filesystem rather than in your project. **Under Claude
Code**, an over-large consolidator result also spills to a file beside them, carrying that group's
record prose verbatim and named by the same store hash; it is deleted when the consolidator asks for
its next group — or, if that process is killed first, by the next one that starts. It is the one
copy of memory text that lives outside `.zikaron/`, which is why the erasure procedure under
[Secrets](#secrets) removes it by hand. Nothing spills under kiro.

Two notes on reading the rest. `memory.db` can look implausibly small while `memory.db-wal` is large —
that is normal for a database held open by the service, since recent writes live in the log until a
checkpoint; the files together are the store. And `hook.log` records only a fixed failure label and an
error code, never your prompt or a memory's text, so it cannot hold a leaked secret.

There is one more log that is not a file: an event table inside `memory.db`. It records what happened
on every **memory** read and write — used to measure whether the write policy is working, and kept in
the database because those rows must commit alongside the change they describe. A knowledge base has
no event log: it keeps four **search** counters in its own metadata — searches, empty searches,
results returned, results stale — which `zikaron_knowledge_status` reports beside the last build's
own file, byte and skip-reason counts.

---

## When something is wrong

Zikaron is built to fail quietly rather than get in your way. A hook that cannot reach the service
prints a short note asking the agent to tell you, writes one line to `hook.log`, and exits cleanly. It
never blocks your message, and it never reads the store directly.

| Symptom | Where to look |
|---|---|
| no memories are being injected | `.zikaron/hook.log`, then `pgrep -af zikaron.service.main` |
| the agent has no `zikaron_*` tools | kiro: `/tools`, and check `@zikaron` is in the agent's `tools`. Claude Code: `/mcp`, and check neither server is pending approval |
| every Zikaron tool call asks permission | kiro: add `@zikaron` to the agent's `allowedTools`. Claude Code: it is `permissions.allow` in `settings.local.json` that did not take |
| a knowledge search returns nothing, or too little | `zikaron_knowledge_status` (or `... -m zikaron.knowledge status <name>`) — a corpus **refreshing** answers from what is already indexed, but one building for the first time answers nothing until it finishes. `reindex_required` means it has no usable index **right now**: never built, or a rebuild emptied it and was interrupted before it finished, or its database is gone, or the configured embedding model changed since it was built. `refresh` rebuilds it |
| knowledge results look wrong for the file on disk | the index has drifted; nothing refreshes it on a schedule. A result whose file changed since indexing is marked `stale` — run `refresh` |
| "Agents not available for crew stages: zikaron-consolidator" | add it to `toolsSettings.crew.availableAgents`, or re-run the installer |
| consolidation seems stuck | ask to consolidate again — that takes the run over |
| the service will not start | `.zikaron/service.log`; a change to a **hard** store-coupled key (`embed_model`, `embed_dim`) is the usual cause. A soft one never refuses **over what is already stored** — but any key set outside its range refuses at startup, whatever its coupling |
| a hook command "not found" | the config names a different virtualenv than the one you installed from; re-run the installer with `--force` |
| a memory looks half-written when injected | an over-long gist; see the note below |

**One known limit, now narrow.** kiro truncates a hook's output past a byte cap and says nothing
when it does. Gist length is bounded in *tokens*, and tokens bound neither characters nor bytes — a
single unbroken 4000-character string counts as one token — so a pathologically long gist could
once push the injected block past that cap and lose the tail of it silently. **New writes can no
longer do this:** a gist over 1,024 characters is rejected outright, which keeps a five-row block
comfortably inside every supported harness's budget. (Emoji and other characters outside the common
range count as two each, so a gist made mostly of them is capped nearer 512 — the matching count
rather than a conservative one, because the injection budget was measured to count them the same
way.) Only records written before that bound existed can still be over-long. If you see a
truncated-looking block, find that gist with `zikaron_memory_search` and amend it; the amend is
rejected until the gist is shortened.

### Secrets

**Both stores are plaintext on disk**, and retiring a memory does not erase it. The policy tells
agents never to record secrets, but nothing enforces that — treat the store as readable by anything
that can read your home directory.

**A knowledge base is the larger plaintext surface, and it works differently.** A corpus holds the
verbatim text of every file indexed into it. A secret that reaches Zikaron inside an indexed *file*
was never recorded by an agent and is not in the memory store, so neither remedy below applies:
`zikaron_knowledge_remove` destroys that corpus's index, and the file itself is yours to fix.

**If a secret does get recorded in a memory, do not just delete the row.** The full-text index does
not hold its own copy of the text, so deleting a content row on its own leaves that row's terms
behind: the index then returns hits for a row that no longer exists, and the next write against it
can corrupt the database. Two safe options, in order of preference:

1. Stop the service, delete the whole store, **and delete the spill files, which are not in it**:
   `pkill -f zikaron.service.main; rm -rf .zikaron; rm -f "${XDG_RUNTIME_DIR:-/tmp}"/zikaron*/*.json`.
   You lose every memory **and every knowledge base**; the store rebuilds itself empty on the next
   session.
   **The separator is `;` rather than `&&` deliberately**: the service stops itself after
   `service.idle_timeout`, so it is usually *not* running, and `pkill` exits 1 when nothing
   matched — which with `&&` skips the deletion silently, leaving the store you believe you
   just erased.
   **The third command is the one that is easy to miss.** A consolidator group too large to return
   is written to the runtime directory rather than into your project, with the record prose in it
   verbatim, so `rm -rf .zikaron` does not reach it and a record erased from the store can survive
   there until the next reboot. That glob takes every store's spill files rather than only this
   one's, which is recoverable rather than free: a consolidation still in flight fails its next
   read loudly and is re-served the group with a fresh copy. It is a Claude Code path — nothing
   spills under kiro.
2. Follow the ordered procedure in `design/write-policy.md` §"The emergency erasure procedure,
   exactly", which removes the index terms and vectors before the content row.

Either way the secret is probably still live in its own original home — rotate it rather than only
deleting the copy.

## Uninstall

From the project directory, first the part that is the same on both harnesses:

```bash
pkill -f zikaron.service.main    # or just let it idle out
rm -rf .zikaron                  # the memory store, every knowledge base, and the logs
rm -f "${XDG_RUNTIME_DIR:-/tmp}"/zikaron*/*.json   # Claude Code only: spilled consolidator groups
```

The third line is there for the reason [Secrets](#secrets) gives: spill files sit outside the
project, so `rm -rf .zikaron` does not reach them.

Then the harness's own artefacts. Under **kiro**:

```bash
rm -rf .kiro/skills/zikaron-consolidate
rm .kiro/agents/zikaron-consolidator.json
mv .kiro/agents/<your-agent>.json.bak .kiro/agents/<your-agent>.json
```

The last line restores the backup the installer made. If you would rather keep later edits to that
config, remove the `hooks`, `mcpServers` and `@zikaron` entries by hand instead.

Under **Claude Code** the artefacts are project files rather than one merged config:

```bash
rm .claude/agents/zikaron-consolidator.md
rm -rf .claude/skills/zikaron-consolidate
```

and then remove Zikaron's `hooks`, `enabledMcpjsonServers` and `permissions` entries from
`.claude/settings.local.json`, and its two servers from `.mcp.json`. Both files are edited rather
than deleted, because both hold settings that are not Zikaron's. **All three settings keys, because
the install writes three** — leaving `enabledMcpjsonServers` behind names two servers that no longer
exist, which loads nothing and breaks nothing but is not an uninstall.

Note that `rm -rf .zikaron` takes the knowledge bases with it. They are rebuildable — an index is a
view onto files you still have — but rebuilding one takes minutes per corpus.

## Design and development

The full design record is in [`design/`](design/README.md) — start with `design/overview.md`, which
carries the decision table and the reasoning behind every choice above.
`design/coding-standards.md` is binding for contributions. `./check.sh` is the per-edit gate and the
definition of done for a change — formatter, linter, `mypy --strict`, and the hermetic test suite
under a coverage floor, with three marker tiers (`manual`, `integration_kiro`, `integration_claude`)
deselected by default and run by name. `./check-matrix.sh`, which runs all of that once per tested
Python version, is additionally required before a milestone lands.

**CI is not a third thing to run.** The workflow in `.github/workflows/` asserts the matrix's claim —
every tested version green on one tree — against a commit, by running `check.sh` once per version. So a
pull request needs nothing you would not already run locally. It also runs an **advisory** macOS job,
which gates nothing: macOS support is committed to but unverified, and a red result there is the
instrument working rather than a broken build. `design/distribution.md` explains what that job can and
cannot prove.
