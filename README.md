# Zikaron

**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") gives a coding agent the **tribal
knowledge** a project accumulates: how to build and test it, which step fails silently, which env
vars the integration tests need, which API is not safe to use yet and why, what was already tried and
how it failed.

The test for whether something belongs in Zikaron: *could you learn it by reading the code?* If yes,
it is out of scope — a separate system covers code structure and symbols. This store is for what cost
somebody time to discover, and would otherwise be discovered again by the next agent, at full price.

It runs entirely on your machine: a SQLite database under `.zikaron/`, a local embedding model, and a
small background service on a Unix socket. Nothing leaves the box, and there is no account to create.

---

## How it works

**Memories are short records** — a one-line *gist* and a longer *content* body. The gist exists to let
a future agent decide whether to read further; the content carries the detail. Records live in two
tiers: new ones land in a **journal**, and consolidation later folds the journal into **long-term**
records, merging what belongs together and retiring what does not.

**Reading happens two ways.** Before every message you send, a hook injects the few most relevant
gists into the agent's context, so recall costs no tool call and no decision. When the agent wants
more, it calls `zikaron_search` for a wider look or `zikaron_fetch` for a full record. Retrieval is
hybrid: a vector search over a local embedding model and a full-text search over the same corpus,
their rankings fused, so an exact identifier and a vague description both find their record.

**Writing is the agent's own judgment.** Nothing summarizes your session behind your back and no extra
model runs on the write path. A policy injected when the agent starts tells it what is worth recording;
it then calls `zikaron_remember`, `zikaron_amend` or `zikaron_retire` itself. Near-duplicates are
detected at write time and handed back to the agent to resolve rather than silently dropped, and
nothing is ever hard-deleted — a retired record stops surfacing but stays auditable.

**Consolidation is manual and runs as a separate agent.** You ask for it; a subagent with four tools
and no ability to search is handed groups of related entries that code selected for it, and decides
for each whether to merge, promote or discard. Keeping it separate means a fresh context and no
possibility of wandering outside the group it was given.

### The pieces

| | What it is |
|---|---|
| **core** | The library: the store, retrieval, chunking, consolidation. No processes, no transport. |
| **service** | A long-running process per project. Holds the embedding model in memory and the database open, and answers requests over a Unix socket. Starts itself when needed and stops itself when idle. |
| **MCP server** | Translates the agent's tool calls into requests to the service. One process per agent instance; loads no model. |
| **hook** | A single-shot executable your agent runs on start and before each message. Deliberately tiny; loads no model and never touches the database directly. |

The service exists for one measured reason: loading the embedding model costs about **780 ms**, and
retrieval sits on the path of every message you send. Keeping the model resident turns that into a
**~7 ms** embed and a **~9 ms** round trip. The hook stays thin for the same reason — it runs once per
message, and it costs about **50 ms** end to end.

If the service is not running, the hook starts it and moves on. If anything fails, the hook writes one
line to a log, tells the agent to mention it to you, and exits cleanly — it never blocks your message
and never fails your turn.

---

## Requirements

- **Linux.** The transport is a Unix domain socket and the paths assume a POSIX filesystem; nothing
  here has ever been run on macOS or Windows.
- **Python 3.12.**
- **`kiro-cli` on your `PATH`.** Zikaron installs hook and MCP entries that kiro itself reads, so the
  installer refuses to run without it.

## Install

From the Zikaron source directory:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

Then install into the project you want memory for:

```bash
cd /path/to/your/project
/path/to/zikaron/.venv/bin/python -m zikaron.install \
    --project . --agent .kiro/agents/<your-agent>.json
```

`--agent` is the config for the agent you actually work in. Omit it and the installer prints the JSON
for you to paste instead; nothing is merged into a file you did not name.

Finally, if the project is a git repository, tell git to ignore the store:

```bash
echo '.zikaron/' >> .gitignore
```

The installer does not do this for you — `.gitignore` is yours, and appending to it is not a decision an
installer should make silently. But it matters, and it is easy to forget: without it the memory
database, its write-ahead log, the service logs and a downloaded embedding model all show up as
untracked, and a routine `git add -A` commits the lot. None of it is useful to anyone else and none of
it is reproducible from your repository.

What it writes, relative to the project:

| Path | What |
|---|---|
| `.kiro/agents/zikaron-consolidator.json` | the consolidation subagent: its model, its four tools, its prompt |
| `.kiro/skills/zikaron-consolidate/SKILL.md` | how to run a consolidation, and how to recover a stuck one |
| the agent config you named | `hooks` for start and per-message, an `mcpServers` entry, `@zikaron` in `tools` and `allowedTools`, and the consolidator in `toolsSettings.crew` |

It backs your config up to `<config>.bak` before touching it, keeps an existing consolidator config or
skill rather than overwriting your edits (pass `--force` if you mean it), and validates the
consolidator's model id against your harness — an unknown model would otherwise be silently replaced
by the harness's default.

`@zikaron` has to be in `tools` or the memory tools are simply absent: the `mcpServers` entry
*configures* the server and `tools` is what *selects* from it. It goes into `allowedTools` too, so the
agent can record without interrupting you. That is deliberate rather than lax — the whole design leans
on the agent writing freely, and a permission prompt per write both suppresses that and trains you to
click through prompts. What it trusts is narrow: five tools reading and writing rows in a local
database, with no network and no effect outside the project. A mistaken write is *recoverable* rather
than undoable — `zikaron_retire` withdraws a record from ordinary retrieval and leaves it auditable,
while an amend overwrites prose that nothing restores. Pass `--no-trust-tools` if you would rather
approve each one.

**That trust stops at the memory tools.** Spawning the consolidator is a separate grant — a subagent
with its own model invocation and four mutation verbs — so the installer never adds it to
`trustedAgents`, and starting a consolidation asks your permission once. Add
`zikaron-consolidator` there yourself if you would rather it did not.

The consolidator also has to be reachable by the `subagent` tool, so if your config already restricts
which agents may be spawned (`toolsSettings.crew.availableAgents`), the installer adds
`zikaron-consolidator` to that list. If you have no such restriction it leaves it alone — an empty list
means *every* agent is available, and writing one entry into it would restrict you to just this one.
The skill is also declared in the agent's `resources` unless something there already covers it. Skills
normally arrive by inheritance, so that entry is usually redundant — but it is the only thing that
makes the skill loadable if you have set `chat.disableInheritingDefaultResources`, and declaring a
resource does not disable inheritance, so it can only help.

**One thing it deliberately does not do:** add the `subagent` tool itself, which the consolidation
skill needs in order to spawn the consolidator. Its reach is much wider than memory, so that grant
stays yours. The installer says so if it is missing.

**Installing into a clone of the Zikaron repository itself** finds a consolidator config already
tracked, carrying whichever virtualenv path the last committer had. The installer notices that the file
names a different install, backs it up, and rewrites it for yours.

### Options

| Flag | Effect |
|---|---|
| `--project <dir>` | the project to install into. Also where the store lives (default: the current directory) |
| `--agent <path>` | merge the hook and MCP entries into that config, after backing it up |
| `--model <id>` | the consolidator's model (default: `claude-sonnet-5`), validated against your harness |
| `--format {object,array}` | which hook format to write when the target config has none yet |
| `--no-trust-tools` | leave `@zikaron` out of `allowedTools`, so every memory write asks permission |
| `--force` | replace files that would otherwise be kept |

Both hook formats kiro accepts are supported, and a config that already uses one keeps it: kiro
rewrites a config in whichever format it read, so mixing them in one file has no defined meaning.

## Verify

Start a session with the agent you installed into. On start you should see nothing unusual — the write
policy goes into the model's context, not to your terminal. Then, from the project directory:

```bash
# a service should be running for this project after your first message
pgrep -af zikaron.service.main

# one line per hook failure, and absent when nothing has failed
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
| `embedding` | `embed_model` | `BAAI/bge-small-en-v1.5` | any model your embedder can load | which embedding model to use. **Store-coupled** |
| `embedding` | `embed_dim` | `384` | ≥ 1 | that model's vector width. **Store-coupled** |
| `embedding` | `embed_prefix_query` | a retrieval instruction | free text | the prefix prepended to a query before embedding |
| `indexing` | `chunk_max_tokens` | `450` | 64–8192 | how large a chunk may get before a record is split |
| `indexing` | `gist_max_tokens` | `64` | 8–256 | the longest gist a write may carry |
| `retrieval` | `chunk_overfetch` | `8` | 1–64 | how many extra chunks the vector arm reads to cover its candidates |
| `retrieval` | `fusion_depth` | `50` | 1–500 | how deep each arm goes before the two are fused |
| `retrieval` | `rrf_k` | `60` | ≥ 1 | the rank-fusion constant |
| `retrieval` | `supersession_penalty` | `0.5` | 0.0–1.0 | how far a replaced record is demoted rather than hidden |
| `retrieval` | `retired_penalty` | `0.5` | 0.0–1.0 | the same, for a retired record when one is asked for |
| `retrieval` | `supersession_max_depth` | `32` | 1–1024 | how far a chain of replacements is followed |
| `retrieval` | `fts_query_max_terms` | `64` | 1–512 | the largest full-text query built from one prompt |
| `dedup` | `dedup_threshold` | `0.8` | 0.0–1.0 | how similar a new record must be to be offered back as a near-duplicate |
| `dedup` | `dedup_max` | `3` | 0–20 | how many near-duplicates are handed back at once |
| `consolidation` | `mutual_k` | `5` | 2–50 | how many neighbours each entry considers when grouping |
| `consolidation` | `orphan_edge_cutoff` | `0.65` | 0.0–1.0 | how close two entries must be to group without a shared anchor |
| `consolidation` | `anchor_cutoff` | `0.65` | 0.0–1.0 | how close an entry must be to a long-term record to be anchored to it |
| `consolidation` | `group_max` | `12` | 2–64 | members per group before it is split into shards |
| `consolidation` | `max_group_serves` | `3` | 1–16 | how many times one group may be re-served before it is abandoned |
| `consolidation` | `run_lease` | `1800` | 60–86400 | seconds a consolidation run holds the store |
| `service` | `idle_timeout` | `1800` | 60–86400 | seconds of inactivity before the service stops itself |
| `signals` | `signal_horizon_days` | `30` | 1–3650 | the window the write-policy instrumentation reports over |

**Two keys are store-coupled** and cannot be changed once memories exist: `embed_model` and
`embed_dim` describe the vectors already on disk. The service refuses to start rather than serve a
store whose configuration disagrees with its contents — changing either means reindexing.

**The write policy can be overridden per project.** Put your own text at `.zikaron/write-policy.md`
and the start hook prints that instead of the shipped policy. If it is missing, unreadable, empty, a
symlink, or in a store directory other users could write to, the shipped text is used and one line
lands in `hook.log` saying which — the policy print is the one path that is never allowed to fail.

---

## Files and logs

Everything Zikaron writes for a project lives in one directory, and all of it is `0600` or `0700`:

```
<project>/.zikaron/
  memory.db          the store itself — never commit this
  memory.db-wal      SQLite's write-ahead log; part of the store
  memory.db-shm      SQLite's shared-memory index; part of the store
  config.toml        your per-project overrides, if you wrote any
  service.log        the background service: startup, resolved config, errors
  hook.log           one line per hook failure. Absent means nothing has failed
  warmup.log         the small helper that warms the service when a session starts
  write-policy.md    your policy override, if you wrote one
```

Two notes on reading them. `memory.db` can look implausibly small while `memory.db-wal` is large —
that is normal for a database held open by the service, since recent writes live in the log until a
checkpoint; the files together are the store. And `hook.log` records only a fixed failure label and an
error code, never your prompt or a memory's text, so it cannot hold a leaked secret.

There is one more log that is not a file: an event table inside the database. It records what happened
on every read and write — used to measure whether the write policy is working, and kept in the database
because those rows must commit alongside the change they describe.

---

## When something is wrong

Zikaron is built to fail quietly rather than get in your way. A hook that cannot reach the service
prints a short note asking the agent to tell you, writes one line to `hook.log`, and exits cleanly. It
never blocks your message, and it never reads the store directly.

| Symptom | Where to look |
|---|---|
| no memories are being injected | `.zikaron/hook.log`, then `pgrep -af zikaron.service.main` |
| the agent has no `zikaron_*` tools | `/tools` in kiro; check `@zikaron` is in the agent's `tools` |
| every memory write asks permission | add `@zikaron` to the agent's `allowedTools` |
| "Agents not available for crew stages: zikaron-consolidator" | add it to `toolsSettings.crew.availableAgents`, or re-run the installer |
| consolidation seems stuck | ask to consolidate again — that takes the run over |
| the service will not start | `.zikaron/service.log`; a change to a store-coupled key is the usual cause |
| a hook command "not found" | the config names a different virtualenv than the one you installed from; re-run the installer with `--force` |
| a memory looks half-written when injected | an over-long gist; see the note below |

**One known limit, now narrow.** kiro truncates a hook's output past a byte cap and says nothing when
it does. Gist length is bounded in *tokens*, and tokens bound neither characters nor bytes — a single
unbroken 4000-character string counts as one token — so a pathologically long gist could once push the
injected block past that cap and lose the tail of it silently. **New writes can no longer do this:** a
gist over 1,024 characters is rejected outright, which keeps a five-row block comfortably inside every
supported harness's budget. (Emoji and other characters outside the common range count as two each, so
a gist made mostly of them is capped nearer 512 — the stricter count is deliberate, because the
harness's own budget may count them that way too.) What remains is history — a record written before that bound existed can
still be over-long. If you see a truncated-looking block, look for such a gist with `zikaron_search`
and amend it; the amend will be rejected until the gist is shortened, which is the intended nudge.

### Secrets

The store is **plaintext on disk**, and retiring a memory does not erase it. The policy tells agents
never to record secrets, but nothing enforces that — treat the store as readable by anything that can
read your home directory.

**If a secret does get recorded, do not just delete the row.** The full-text index does not hold its
own copy of the text, so deleting a content row on its own leaves that row's terms behind: the index
then returns hits for a row that no longer exists, and the next write against it can corrupt the
database. Two safe options, in order of preference:

1. Stop the service and delete the whole store:
   `pkill -f zikaron.service.main && rm -rf .zikaron`. You lose every memory and keep nothing
   dangerous; the store rebuilds itself empty on the next session.
2. Follow the ordered procedure in `design/write-policy.md` §"The emergency erasure procedure,
   exactly", which removes the index terms and vectors before the content row.

Either way the secret is probably still live in its own original home — rotate it rather than only
deleting the copy.

## Uninstall

From the project directory:

```bash
pkill -f zikaron.service.main                          # or just let it idle out
rm -rf .zikaron                                        # the store and its logs
rm -rf .kiro/skills/zikaron-consolidate
rm .kiro/agents/zikaron-consolidator.json
mv .kiro/agents/<your-agent>.json.bak .kiro/agents/<your-agent>.json
```

The last line restores the backup the installer made. If you would rather keep later edits to that
config, remove the `hooks`, `mcpServers` and `@zikaron` entries by hand instead.

## Design and development

The full design record is in [`design/`](design/README.md) — start with `design/overview.md`, which
carries the decision table and the reasoning behind every choice above.
`design/coding-standards.md` is binding for contributions, and `./check.sh` is the definition of done:
formatter, linter, `mypy --strict`, and the whole test suite under a coverage floor.
