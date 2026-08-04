# Zikaron

**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") gives a coding agent the **tribal
knowledge** a project accumulates: how to build and test it, which step fails silently, which env
vars the integration tests need, what was already tried and how it failed.

The test for whether something belongs in Zikaron: *could you learn it by reading the code?* If yes,
it is out of scope — a separate system covers code structure and symbols. This store is for what
cost somebody time to discover.

It runs entirely on your machine: a SQLite store under `.zikaron/`, a local embedding model, and a
small service on a Unix socket. Nothing leaves the box.

---

## Requirements

- Linux. The transport is a Unix domain socket and the paths assume a POSIX filesystem; nothing here
  has ever been run on macOS or Windows.
- Python 3.12.
- `kiro-cli` on your `PATH`. Zikaron installs hook and MCP entries that kiro itself reads, so the
  installer refuses to run without it.

## Install

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .            # or: .venv/bin/pip install zikaron
.venv/bin/python -m zikaron.install --agent .kiro/agents/<your-agent>.json
```

`--agent` is the config for the agent you actually work in. Omit it and the installer prints the JSON
for you to paste instead; nothing is merged into a file you did not name.

What it writes:

| Path | What |
|---|---|
| `.kiro/agents/zikaron-consolidator.json` | the consolidation subagent: its model, its four tools, its prompt |
| `.kiro/skills/zikaron-consolidate/SKILL.md` | how to run a consolidation, and how to recover a stuck one |
| the agent config you named | `hooks` for `agentSpawn` and `userPromptSubmit`, an `mcpServers` entry, and `@zikaron` in `tools` and `allowedTools` |

It backs your config up to `<config>.bak` before touching it, refuses to overwrite an existing
`zikaron-consolidator.json` or skill file (pass `--force` if you mean it), and validates the model id
against `kiro-cli chat --list-models` — an unknown model would otherwise be silently replaced by the
harness's default.

`@zikaron` has to be in `tools` or the memory tools are simply absent — `mcpServers` configures the
server and `tools` is what selects from it. Measured: an agent with the server entry and a `tools` list
that did not name it reported no `zikaron_*` tools at all, with no warning anywhere.

`@zikaron` also goes into `allowedTools`, so the agent can record without interrupting you. That is
deliberate rather than lax: the whole design leans on the agent writing freely, and a permission prompt
per write both suppresses that and trains you to click through prompts. What it trusts is five tools
reading and writing rows in a local SQLite file, with every write reversible by `zikaron_retire`. Pass
`--no-trust-tools` if you would rather approve each one.

**One thing it deliberately does not do:** add the `subagent` tool, which the consolidation skill needs
to spawn the consolidator. Its reach is much wider than memory, so that grant stays yours. The installer
says so if it is missing.

**Installing into a clone of this repository** finds `.kiro/agents/zikaron-consolidator.json` already
tracked, carrying whichever venv path the last committer had. The installer notices that the file names
a different install, backs it up, and rewrites it for yours.

### Options

| Flag | Effect |
|---|---|
| `--project <dir>` | install into another directory (default: the current one, which is also where the store lives) |
| `--agent <path>` | merge the hook and MCP entries into that config, after backing it up |
| `--model <id>` | the consolidator's model (default: `claude-sonnet-5`), validated against your harness |
| `--format {object,array}` | which hook format to write when the target config has none yet |
| `--no-trust-tools` | leave `@zikaron` out of `allowedTools`, so every memory write asks permission |
| `--force` | replace files that would otherwise be kept |

Both hook formats kiro accepts are supported, and a config that already uses one keeps it: kiro
rewrites a config in whichever format it read, so mixing them in one file has no defined meaning.

## Verify

Start a session with the agent you installed into. On spawn you should see nothing unusual — the
write policy is injected into the model's context, not printed to you. Then:

```bash
# a service should be running for this project after your first message
pgrep -af zikaron.service.main

# what the hooks recorded, if anything went wrong
cat .zikaron/hook.log
```

Ask the agent to remember something, then start a new session and ask about it. If the memory comes
back, the whole loop works: write through MCP, push through the hook, retrieval in between.

## Using it

**Writing** is the agent's own judgment. The `agentSpawn` hook injects a policy telling it what is
worth recording; you can also just say "remember that."

**Reading** happens two ways. The `userPromptSubmit` hook injects the top few relevant gists before
every message you send, and the agent can call `zikaron_search`/`zikaron_fetch` when it wants more.

**Consolidating** is manual, and it is how a journal of raw observations becomes durable records. Ask
the agent to consolidate project memory; it loads the shipped skill and spawns the consolidator
subagent. If a run ever seems stuck, ask again — a second invocation takes the abandoned run over.

## Configuration

Optional, and there is a working default for everything. Two TOML layers, later wins per key:

```
~/.config/zikaron/config.toml     system-wide
<project>/.zikaron/config.toml    this project only
```

```toml
[retrieval]
fusion_depth = 50        # how deep each arm fuses
rrf_k = 60               # the RRF constant

[consolidation]
group_max = 12           # members per group before it shards
run_lease = 1800         # seconds a consolidation run holds the store

[service]
idle_timeout = 900       # seconds before the service stops itself
```

An unknown key or a wrong type is fatal rather than ignored, so a typo cannot silently leave you on a
default. A few keys are coupled to the store's contents (`embed_model`, `embed_dim`) and cannot be
changed without reindexing; the service refuses to start rather than serve a store its config
disagrees with.

**The write policy can be overridden per project.** Drop your own text at
`.zikaron/write-policy.md` and the `agentSpawn` hook prints that instead of the shipped policy. If it
is unreadable, empty, or a symlink, the shipped text is used instead and one line lands in
`.zikaron/hook.log` saying which.

## What lives where

```
.zikaron/
  memory.db          the store — never commit this
  config.toml        your overrides, if any
  service.log        the service's own log
  hook.log           one line per hook failure
  warmup.log         the detached warm helper's log
  write-policy.md    your policy override, if you wrote one
```

**Add `.zikaron/` to `.gitignore`.** The store is local state: memories, embeddings and a downloaded
model, none of it useful to anyone else and none of it reproducible from your repository.

## When something is wrong

Zikaron is built to fail quietly rather than get in your way. A hook that cannot reach the service
prints a short note asking the agent to tell you, writes one line to `.zikaron/hook.log`, and exits
0 — it never blocks your message, and it never reads the store directly.

| Symptom | Where to look |
|---|---|
| no memories are being injected | `.zikaron/hook.log`, then `pgrep -af zikaron.service.main` |
| the agent has no `zikaron_*` tools | `/tools` in kiro; check the `mcpServers` entry in your agent config |
| "consolidation seems stuck" | ask to consolidate again — that takes the run over |
| the service will not start | `.zikaron/service.log`; a config change to a store-coupled key is the usual cause |
| a hook command "not found" | you installed from a different venv than the one in the config; re-run the installer with `--force` |
| a memory seems to be injected half-written | a gist long enough to overflow the hook's output cap; see the note below |

**One known limit worth knowing about.** kiro truncates a hook's output past a byte cap (65536 for the
entries this installs, 10240 if your config uses the array hook format) and says nothing when it does.
Gist length is bounded in *tokens*, and tokens do not bound bytes — a single unbroken 4000-character
string counts as one token — so a pathologically long gist can push the injected block past that cap and
lose the tail of it silently. Ordinary prose gists are nowhere near it. If you see a truncated-looking
block, look for an over-long gist with `zikaron_search` and amend it.

The store is **plaintext on disk**, and retiring a memory does not erase it. The policy tells agents
never to record secrets, but nothing enforces that — treat `.zikaron/memory.db` as readable by
anything that can read your home directory.

**If a secret does get recorded, do not just delete the row.** The full-text index is an
external-content FTS5 table, so deleting a content row on its own leaves that row's terms behind: the
index then returns hits for a row that no longer exists, and the next write against it can corrupt the
database outright. Two safe options, in order of preference:

1. Stop the service and delete the whole store: `pkill -f zikaron.service.main && rm -rf .zikaron`.
   You lose every memory and keep nothing dangerous; the store rebuilds itself empty on the next
   session.
2. Follow the ordered procedure in `design/write-policy.md` §"The emergency erasure procedure,
   exactly", which deletes the FTS terms and vector rows before the content row and says what else
   has to be cleaned up.

Either way, remember the secret may also be in the value's own original home — rotate it rather than
only deleting the copy.

## Uninstall

```bash
rm -rf .zikaron                                        # the store and its logs
rm -rf .kiro/skills/zikaron-consolidate
rm .kiro/agents/zikaron-consolidator.json
mv .kiro/agents/<your-agent>.json.bak .kiro/agents/<your-agent>.json   # or edit the entries out
```

Stop any running service first with `pkill -f zikaron.service.main`, or just let it idle out.

## Design and development

The design record is in [`design/`](design/README.md) — start with `design/overview.md`.
`design/coding-standards.md` is binding for contributions, and `./check.sh` is the definition of
done: formatter, linter, `mypy --strict`, and the whole test suite under a coverage floor.
