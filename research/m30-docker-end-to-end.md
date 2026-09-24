# The published artefact, installed end to end on a machine that had never seen it

**2026-09-24.** The first exercise of the whole install path against PyPI, on a foreign OS, driven
the way a person would drive it. It reaches three things CI structurally cannot: a genuinely cold
model cache, a real Claude Code session receiving the write policy and writing through MCP, and a
real subagent.

**It does not cover push or pull.** No `UserPromptSubmit` gist block was captured and no
`zikaron_memory_search` call was made, so D12's injection and the search path were not exercised in
this run. The session wrote; it was never asked to recall.

It says nothing about **macOS arm64**. The container is amd64 Linux, so the platform where
`enable_load_extension` is reported off remains CI's alone.

## What was under test

| | |
|---|---|
| image | `ubuntu:26.04` → Ubuntu 26.04.1 LTS, x86_64, user `ubuntu` (uid 1000) |
| zikaron | `0.1.0` from PyPI |
| uv | 0.12.18 |
| Claude Code | 2.1.281, native installer, no Node |
| interpreter Zikaron runs on | uv-managed CPython **3.14.7**, linking SQLite **3.53.1** |
| host interpreter present but unused | `/usr/bin/python3` **3.14.4**, linking SQLite **3.46.1** |

## The cold baseline, and how it stopped being cold

A pristine `ubuntu:26.04` has **no `python3`, no `curl`, no `wget`, no `git`, no CA certificates**.
Two consequences, both worth stating because neither is Zikaron's doing and both shape the run:

- **`README.md` assumed `uv` had arrived from somewhere.** `uv`'s own installer is a `curl` pipe,
  and a stock image has neither `curl` nor CA certificates, so a real user installs both before
  reaching any documented Zikaron command.
- **Installing `sudo` installs CPython.** `sudo` Recommends `sudo-rs`, which Depends on `python3`.
  Verified by date-partitioning `/var/log/dpkg.log` — 86 packages from the image build, 21 from this
  session, `python3` among the latter. So "install sudo" is not a neutral preparation step on 26.04.

That accident produced a measurement worth keeping. **Ubuntu's system Python is not one of the
risky builds.** `README.md` warns that extension loading "is reported off in some widely used
builds"; this supports README's own hedge — *"a host Python may well work"*. It is the **second**
distribution build measured rather than cited: this host's Ubuntu 3.12.3 was probed with a real
`vec0` KNN query in `research/python-portability-probes.md` §4. **This probe is the weaker of the
two** — it reads the flag and the FTS5 compile option only, which places the build outside the
"reported off" class and proves nothing beyond that.

```
$ /usr/bin/python3 -c 'import sqlite3,sys; c=sqlite3.connect(":memory:")
print(sys.version.split()[0], sqlite3.sqlite_version)
c.enable_load_extension(True); print("enable_load_extension: ok")
print("fts5:", "ENABLE_FTS5" in [r[0] for r in c.execute("pragma compile_options")])'
3.14.4 3.46.1
enable_load_extension: ok
fts5: True
```

## `--managed-python` declines a host interpreter that exists

This is the claim README makes, and until now it rested on runs against *emptied uv directories* on
the development host. Here a host interpreter was genuinely present and was genuinely refused:

```
$ uv tool install --managed-python zikaron
Downloading cpython-3.14.7-linux-x86_64-gnu (download) (34.3MiB)
 + zikaron==0.1.0
Installed 3 executables: zikaron, zikaron-hook, zikaron-mcp

$ cat ~/.local/share/uv/tools/zikaron/pyvenv.cfg
home = /home/ubuntu/.local/share/uv/python/cpython-3.14.7-linux-x86_64-gnu/bin
version_info = 3.14.7
```

The independent confirmation is `doctor`'s own report of **SQLite 3.53.1 linked by Python 3.14.7**,
against the system Python's 3.46.1. Different interpreter, different SQLite.

## Cold `doctor`: absent, and exit 0

M30's most easily-wrong decision, and the one every previous run took the warm branch of.

```
ok   model cache (BAAI/bge-small-en-v1.5)  not yet fetched; fetched on first service start,
                                           into /home/ubuntu/.cache/zikaron/models
ok   socket path length                    /tmp/zikaron-1000/<hash>.sock fits 108 bytes
--   sqlite version                        3.53.1 linked by Python 3.14.7
DOCTOR EXIT=0
```

**The cache was still absent afterwards** — `doctor` reported the gap without closing it.

Two side effects of the container, both first-time exercises: `sqlite-vec` **loads and registers
`vec0` on a uv-managed interpreter on a foreign OS**; and with no `$XDG_RUNTIME_DIR`, the socket took
the per-uid `/tmp` fallback, which the development host has never used.

After the first service start the same command reports the warm branch —
`present at 52398278842ec682c6f32300af41344b1c0b0bb2 … 5 files verified` — so both branches were
observed in one container.

## Acquisition

The cache is keyed by the pinned revision and holds exactly the five blobs the digest set covers:

```
~/.cache/zikaron/models/models--qdrant--bge-small-en-v1.5-onnx-q/
  snapshots/52398278842ec682c6f32300af41344b1c0b0bb2
  blobs/  (5 files)
```

**The fetch happens inside the cold start, and the timestamps bound it rather than measuring it.**
The service's first log line is at `02:54:14.257`; the five blobs land between `02:54:15.879` and
`02:54:17.547`, the snapshot directory at `02:54:17.556`, and `service_warm` at `02:54:17.998`. A
blob's mtime is when it *finished*, so the first blob's own download lies before `15.879`: the 64 MB
fetch took **at least the 1.67 s** between first and last blob completing, and **at most the 3.30 s**
from the service's first log line to the snapshot directory, inside a **3.74 s** cold start on this
container's network.

**What was observed about verification is narrower than "verified".** Acquisition emitted no
refusal, which is the quiet path — a digest mismatch discards the snapshot and says so. The
five-files-match statement comes from `doctor`'s own hash pass afterwards, not from acquisition's.

## Installation

**`zikaron install --project .` — README's literal command as published with `0.1.0` — refuses for
the user that README addresses.** A freshly trusted Claude Code project has no `.claude/` directory,
and `CLAUDECODE` is exported into the processes a session spawns, not into a terminal outside one —
which is where this install was run from. So detection has nothing to read:

```
install refused: could not tell which harness . is for — it has neither .kiro/ nor .claude/,
and CLAUDECODE is not set. Pass --harness kiro or --harness claude-code. Guessing here would
install artefacts the harness never reads, which exits 0 and leaves no Zikaron tools at all.
```

The refusal is right; the documentation was not. README *then* called `--harness` an **override** of
detection, where for that install it was **required**.

**`--print-only` noted correctly that a harness was genuinely absent.** Before Claude Code was
installed, the preview volunteered that a real install would refuse because `claude` is not on
`PATH` — a guard that had only ever run against a stubbed binary — while still printing the preview,
which is its job. It wrote nothing.

**With `--harness claude-code` the create path wrote four artefacts** — `.claude/agents/`,
`.claude/skills/zikaron-consolidate/SKILL.md`, `.claude/settings.local.json`, `.mcp.json` — with
absolute paths into the uv tool bin, both servers in `enabledMcpjsonServers`, both in
`permissions.allow`, hooks on `SessionStart`, `UserPromptSubmit` and `SubagentStart`.

**Re-running is safe, as README claims.** Second run: exit 0, both config files byte-identical,
agent and skill files reported `kept (already exactly what this version ships)`, and a pre-existing
`.bak` left as it was rather than overwritten.

### The create path is the common case, not the merge path

The plan had the merge path first, on the grounds that it is the realistic user. That is wrong for a
*first* install: a freshly trusted project has no `.claude/settings.local.json` at all. Accepting the
trust dialog does not create one, and neither does granting an ordinary tool use —
`~/.claude.json`'s `projects[…].allowedTools` stayed `[]`. Presumably Claude Code writes that file
when a permission rule or setting is explicitly changed — not observed here. Merge is the
*second*-install case and the already-configured-project case.

## The session, the hook, and the subagent

The `SessionStart` hook fired and the write policy reached the model, carrying D1's operational test
verbatim: *"could you learn it by reading the code? If yes, leave it out."*

**The consolidator ran with the tool surface D32 specifies, under a real Claude Code subagent for the
first time:**

```
tools the consolidator called:
    mcp__zikaron-consolidator__zikaron_memory_next_group  x2
    mcp__zikaron-consolidator__zikaron_memory_promote     x1
    SubagentHandback                                      x1
any memory push/policy injected into the subagent: False
```

No `search`, no `fetch` — the withheld verbs stayed withheld. And **the push hook stayed silent in
the subagent**, which is the back door D32's suppression exists to close; previously verified only
by reading the code. Protocol as specified: claim → `promote` → `version: 2`, `remaining_uuids: []`,
`group_complete: true` → `next_group` → `{"done": true}`. A one-entry journal promoted unchanged
rather than merged, which is correct for the degenerate case.

## Coexistence with Claude Code's own memory (n=1)

The session was asked to remember two things: the user's name, and that the directory is for an
Unreal Engine game. The agent wrote to **both** stores and split them.

**It kept personal data out of the shared store, and that was policy compliance rather than
invention.** `WRITE_POLICY_PROMPT` says *"Never record a secret … and no personal data. Names and
procedures, never values."* The name went only to Claude Code's `memory/`. Zikaron's record
anonymises to *"the project owner said"*.

**It argued past the scope test rather than ignoring it.** The gist reads *"the project direction was
set before any game code existed"* — the model justifying why a fact about project direction survives
*could you learn it by reading the code?*

**The same fact was written in two genres, and this bears on open question 14.**

| store | what it got |
|---|---|
| Zikaron | *"As of 2026-09-24, the project owner said … At that point the directory held only tooling config and a `docs/` folder. There was no `.uproject` and no engine version chosen yet."* |
| Claude Code | *"**How to apply:** Assume Unreal Engine conventions (C++/Blueprints, `.uproject` layout) when working here."* |

Zikaron's copy is **evidentiary**: dated, scoped to what was observed, degrading gracefully if the
project pivots. Claude Code's is **directive** and carries no expiry. Q14 asks what to do about
preferences collected into a store designed not to bind; here the model resolved it unaided by
routing the *binding* form to the store that binds and the *evidence* to the store that does not.
That is a fourth option beyond the three Q14 lists.

**The defect is the duplication.** One fact, two records, two staleness clocks, and no link across
the boundary — Claude Code cross-links its own records with `[[wiki-links]]`, but nothing points at
Zikaron and nothing points back. A pivot corrects one of them.

**This is one session, one model, one phrasing.** It is the first observation of coexistence at all,
not a result to generalise from.

## Defects found

1. **`zikaron knowledge add` names a defect without a remedy.** On a project with no store:
   `refused: … expected=an existing, openable memory.db — this store has not been created`. Accurate,
   and it stops there. M30 made `doctor`'s checks remedy-named deliberately; three messages on the
   install path name the failure, the remedy *and* the consequence of guessing. This one, which a
   new user hits first, names only the failure.
   **The remedy is not `zikaron install`**, and the first attempt at this fix said it was. Verified
   in this container: installing into the project exits 0, creates no `.zikaron`, and the retried
   command prints the identical refusal. `architecture.md` §"First run" is an operator decision that
   *nothing* upstream of the service creates `memory.db` — `Store.create` has one production caller,
   `service/context.py`. The true remedy is a first service start, which a session triggers.
2. **`README.md` presents `--harness` as an override when it is required**, for a person installing
   from a terminal outside a session into a project that is not yet set up. A *Claude Code* agent
   running the installer is detected, because `CLAUDECODE` reaches the processes a session spawns;
   kiro exports no marker, so there it is a `.kiro/` in the project or nothing.
3. **`zikaron --version` does not exist** — falls through to `unknown command '--version'`, exit 2,
   on a tool whose version is the first thing a bug report needs.
4. **`README.md` never says where `uv` comes from.** Its installer is a `curl` pipe, and a stock
   image has neither `curl` nor CA certificates — so a reader cannot reach README's own first
   command without two packages README does not mention.

## Re-deriving this

```bash
docker run -d --name zikaron-e2e -u ubuntu -w /home/ubuntu ubuntu:26.04 sleep infinity
docker exec -u 0 zikaron-e2e apt-get update -qq
# `sudo` is not neutral here: it Recommends `sudo-rs`, which Depends on `python3`. Keep it —
# the host interpreter it installs is the condition that makes the `--managed-python` result
# below mean anything, since refusing an absent interpreter would prove nothing.
docker exec -u 0 zikaron-e2e apt-get install -y -qq sudo curl ca-certificates
docker exec zikaron-e2e sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
docker exec zikaron-e2e sh -c 'export PATH=$HOME/.local/bin:$PATH; uv tool install --managed-python zikaron && zikaron doctor'
```

Claude Code is installed with `curl -fsSL https://claude.ai/install.sh | bash`; its login is
completed by the operator in an attached `tmux` pane (`docker exec -it zikaron-e2e tmux attach`),
because the browser shows a code to paste rather than redirecting — documented behaviour in
containers, not a failure. No credential passes through the agent. Set `TERM=xterm-256color` on the
exec; the image has no useful terminfo and the TUI renders poorly without it.
