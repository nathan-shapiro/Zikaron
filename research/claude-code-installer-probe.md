# Claude Code installer probe — measured, 2026-08-16

**Harness:** Claude Code **2.1.233**, Linux, headless `claude -p` in throwaway projects at
`/tmp/zk-m15*`. Companion to `research/claude-code-harness-probe.md`, which measured the *client*
side; this one measures the four things **M15's installer writes config against**.

Documentation reading of the same questions: `research/claude-code-install-artefact-contract.md`.
Where the two agree it is said so explicitly, because agreement between a doc and a measurement is
itself worth recording — this corpus's two prior probes both **refuted** the documentation reading,
and the absence of a refutation here is a fact about these particular claims, not a licence to stop
measuring.

---

## 1. The hooks shape fires, and `UserPromptSubmit` takes no matcher

Written into `.claude/settings.local.json` and confirmed to fire:

```json
{"hooks": {"UserPromptSubmit": [{"hooks": [
  {"type": "command", "command": "/abs/path/hook.sh", "timeout": 30}
]}]}}
```

The doubled `hooks` nesting is real: an event maps to a list of *groups*, each group carrying its own
`matcher` and its own inner `hooks` list. `UserPromptSubmit` groups carry **no** `matcher` — it always
fires. `SessionStart` accepted the identical shape and fired at session start.

**Hooks within one group run in parallel.** Three entries on one event started within **2 ms** of each
other (`START` timestamps `…951.336`, `…951.337`, `…951.338`) and each was timed independently. So the
harness waits for the *slowest* surviving hook, not the sum.

## 2. `timeout` is **seconds**, and the unit is proved rather than read

The decisive pairing, because a bisection that only ever kills cannot separate the two units:

| Entry | `timeout` | Slept | Outcome |
|---|---|---|---|
| `UNIT30` | `30` | 5 s | **survived** — `END` logged, marker reached the model |
| `KILL3` | `3` | 8 s | killed — no `END`, no marker |
| `KILL1` | `1` | 4 s | killed — no `END`, no marker |

If the field were milliseconds, `timeout: 30` would be 30 ms and `UNIT30` could not have survived a
5-second sleep. It did. **Seconds.**

**This is the one fact most likely to be got wrong by analogy**, and it is worth stating in the shape
of the mistake it prevents: kiro's field is `timeout_ms` and Zikaron ships **10000** in it. Writing
that integer into Claude Code's `timeout` installs a **10,000-second** hook budget — two hours and
forty-five minutes during which a wedged hook blocks every user message, with the harness behaving
exactly as configured and nothing anywhere reporting a problem. `design/architecture.md` already
records that the two *kiro* formats disagree about this same field's unit; this is the third unit in
the same family.

## 3. The `UserPromptSubmit` default is 30 s — not the 600 s that applies elsewhere

A ladder of no-`timeout` entries in a single run, each logging `END` only on survival:

| Slept | 15 | 20 | 25 | 28 | **30** | **32** | 35 | 45 | 55 |
|---|---|---|---|---|---|---|---|---|---|
| `END` logged | ✅ | ✅ | ✅ | ✅ | **✅** | ❌ | ❌ | ❌ | ❌ |

So the default lies in **[30, 32)**. The documentation states **30 s for `UserPromptSubmit`
specifically**, against 600 s for `command` hooks generally — consistent, and the 30-second sleep
winning its race against a 30-second deadline is the expected boundary behaviour rather than a
contradiction. The run's own `duration_ms` was **31,514** against a ~1.5 s model turn, which
independently confirms the harness sat waiting for the full default before proceeding.

**Consequence for the push path.** `push.py`'s ~2 s internal deadline is sized to fire *before* the
harness kills the hook. Against 30 s that property holds with a 15× margin — but it holds against the
**tightest** default in the table, and the margin is 20× smaller than the 600 s a reader who checked
only the general figure would have recorded. That is the reason the installer states the value
explicitly rather than inheriting it, which is the same reason `hook/limits.py` already gives for
kiro's `timeout_ms`.

## 4. A timed-out hook is silent — to the model and to the operator

The killed entries produced **no** notice on stdout, **nothing** on stderr, and no field in
`--output-format json`'s result object. The model saw only the surviving hooks' markers and reported
them as the complete set. Documentation agrees ("Claude Code discards the hook's output"), and adds
that the event is a non-blocking error for most other events.

So the timeout is **not** a loud failure the way an over-budget *injection* is (§5 of the harness
probe: a notice, a 2 KB preview and a path). It is kiro's silent truncation in a different costume,
and it is the reason `hook.log` remains the only place a hook failure is recoverable from.

## 5. Injected hook output is framed `UserPromptSubmit hook success: <stdout>`

Reported by the model itself, unprompted, when asked to quote the lines it could see: each hook's
stdout arrived "rendered as `UserPromptSubmit hook success: ZKM15-…`". Two things follow.

- It is a **neutral** frame. Kiro wrapped injected text in *"I have gathered this context from
  valuable programmatic script hooks"* — an instruction to follow requests found in the injected
  text, which `retrieval.md`'s untrusted-reference-data preamble exists to contradict. Claude Code's
  frame asserts nothing about how to treat the content. Open question 4's stated tension resolves in
  our favour on this harness for a second, independent reason beyond block *placement*.
- It is **per-hook**, so three registered entries produce three separately-framed blocks rather than
  one concatenation. Nothing in Zikaron depends on that, but it is the reason a reader should not
  expect the injected text to arrive as a single contiguous region.

## 6. The model-visible MCP tool name is byte-identical to the config form

Asked to name every tool containing `zikaron`, the model answered exactly
**`mcp__zikaron__zikaron_search`** — the same string `.mcp.json`'s server key and the tool's own name
compose to. The documentation note flagged this as unevidenced; it is now measured.

**This is what makes M15's fourth decision necessary rather than cosmetic.** Every bare
`zikaron_next_group` / `zikaron_search` in the shipped consolidator prompt and skill body names a
tool that does not exist under this harness. A model told to call a tool it cannot find does not
fail loudly — it improvises.

## 7. A whole-server wildcard in subagent frontmatter works, and **excludes** other servers

Two servers registered (`zikaron` with a search tool, `zikaron-consolidator` with a group tool), one
subagent whose frontmatter granted the consolidator server. **The exact spelling matters and is
therefore quoted rather than paraphrased** — an earlier revision of this note wrote it inline for
readability, and a review reasonably read that as the measured form and flagged the shipped artefact
for not matching it. What ran was the **block** form, which is what the installer ships:

```yaml
tools:
  - mcp__zikaron-consolidator
```

Full fixture: `spikes/claude-code-installer/zk-gated.md`. The *inline* form is the one nothing here
measured. Result:

- It reported **exactly one** tool, from the consolidator server.
- It reported **zero** tools whose name contains "search" — `mcp__zikaron__zikaron_search`, live in
  the parent session, **did not reach it**.
- The fully qualified form — a block list whose single entry is `mcp__zikaron__zikaron_search` —
  works identically.

**So D7's enforcement half survives mechanically, and the wildcard is the better spelling of it.**
Not merely equivalent: probe §6 measured that an *unrecognised* tool name in frontmatter refuses the
spawn outright with "would be spawned with zero tools", so an explicit four-name list is a second
declaration of a fact `mcp/consolidator.py` already owns, whose drift mode is a consolidator that
will not start. The wildcard delegates the question to `--mode consolidator`, which is where D32
actually implements it.

## 8. `enabledMcpjsonServers` is accepted, and headless cannot test what it is for

`{"enabledMcpjsonServers": ["zikaron", "zikaron-consolidator"]}` in `.claude/settings.local.json` was
accepted without complaint at 2.1.233, and the session ran normally — so the key is at least not
harmful to write.

**What is *not* measured is the thing that matters.** Both arms — with the key and with an empty
settings file — reached the tool under headless `claude -p`. So this run cannot discriminate: the
approval gate either does not apply headlessly or was already satisfied. The property the installer
would be relying on — *a project-scoped server loads without an interactive approval step* — remains
**documented, unmeasured**, and M16's interactive checkpoint is where it gets settled. The
documentation additionally warns the key is ignored when committed to a *tracked* `settings.json` in
an untrusted folder, and honoured from an untracked `settings.local.json` — which is the file M15
writes, for an unrelated reason (machine-local absolute paths).

## 9. The installed artefacts were driven end to end, once

Not a design question, but the cheapest possible check that the four files this installer writes are
files the harness actually reads — and it exercises the one entry with **no kiro counterpart**, which
is therefore the one no existing test could have caught being wrong.

`python -m zikaron.install --project /tmp/zk-e2e` into a throwaway project, then a headless
`claude -p` asking a canary subagent to report any memory-related instructions it had been given
beyond its own prompt. It came back with the shipped write policy **verbatim** — *"This directory has
a memory store holding **tribal knowledge**…"* — and correctly summarised the rest of the block: the
four search occasions, the gist bound, the secrets prohibition.

So, from the *installed* config rather than a hand-written one: the `SubagentStart` entry is
registered where Claude Code looks for it, fires for an ordinary subagent, and its
`additionalContext` reaches that subagent. This closes one of M16's done-when clauses early — *"a
subagent is observed to have actually **received** the write policy, rather than only our side being
observed to emit it"* — and it is worth having closed here, because M15 is the milestone that could
have got it silently wrong: register only kiro's two triggers and nothing anywhere fails.

**A second run, after the review added `permissions.allow`, took the whole installed config into a
real session** — `claude -p` in a freshly-installed throwaway project, asking only for a marker and a
tool list. Three things came back, and the third was not expected:

- **The config loads.** No settings error, and the harness named both `.mcp.json` servers, so nothing
  was blocked pending approval and the new `permissions` key did not upset the file.
- **A store appeared** at `.zikaron/memory.db`. Nothing called a memory tool, so that is the
  `SessionStart` hook's warm helper reaching the service and the service creating the store on first
  run — `architecture.md` §"First run" behaving as specified, through the installed entry.
- **The tools were not available yet.** The model reported both servers as *"still connecting at
  session start"* and could not name their tools. n=1, headless, one short turn — but if it
  generalises it is a real product property rather than a probe artefact: `zikaron-mcp` imports
  `fastmcp`, which `architecture.md` §Components already prices as the reason that client is
  deliberately not stdlib-only, and a session whose first turns arrive before the server is ready has
  **pull unavailable while push works**. That asymmetry is invisible to the agent, which simply sees
  no memory tools.
  **Not chased here, deliberately** — it is a latency question about a live session, which is
  exactly M16's instrument-reading conditions, and the honest thing to record now is the observation
  and its sample size. What it does *not* indicate is a defect in what M15 writes: the entry is
  correct and the harness acted on it.

**Still M16's, and deliberately not attempted here:** the push and pull paths, which need a live
service and store; the consolidation run; link coverage; and the recall instrument's fresh baseline.

## 11. A bracketed long-context alias is a legitimate frontmatter `model:`

Prompted by a review nitpick rather than by a plan, and it **refuted the claim it was checking**. The
installer's model-shape guard was written as `[A-Za-z0-9._-]+` with a comment asserting that "every
id and alias either harness serves satisfies it" — an unmeasured universal in a corpus whose own rule
is to measure first.

A subagent whose frontmatter read `model: sonnet[1m]` **spawned normally** and answered. So the
bracketed long-context form is a real value the guard was rejecting, and the pattern now admits
brackets.

**What the guard still refuses, and why the anchor rather than the character class does the work:** in
YAML a `[` opens a flow sequence only at the *start* of a scalar. `sonnet[1m]` is therefore a plain
string, while `[1m]` is a one-element list — the same silent meaning-change as an embedded colon. The
pattern requires the first character to be alphanumeric, which is what separates the two.

**Not evidence of which model ran.** The spawned agent volunteered a model id, and that is exactly the
self-report `harness.md` §"The consolidator's model" rejects as a provenance source. The measurement
here is only that the spawn **succeeded** — that the harness accepted the frontmatter value — which is
the whole question the guard turns on.

## 12. Not measured here

Whether the approval gate binds interactively (§8) — M16. `SubagentStart` matcher semantics against a
real `agent_type` (the harness probe measured the payload carries `agent_type`; matching on it is
untested). `SessionStart`'s own default timeout, which was not laddered — the installer states the
value explicitly, so the default is not load-bearing there. Fractional or zero `timeout` values.
Whether a hook killed by timeout leaves anything in the harness's own debug output at higher
verbosity.
