# kiro-cli, installed and driven in a container that had never seen the project

**Run 2026-09-24**, `ubuntu:26.04`, kiro-cli authenticated by the operator, Zikaron installed from
the working tree (`pip install -e`) rather than PyPI — `0.1.0` has neither `init` nor the
thin-client CLI. This is the half of D34 the 2026-09-24 Claude Code run
(`research/m30-docker-end-to-end.md`) could not cover.

Kiro ran in `auto` mode throughout. **It does not name the model it routed to** — every assistant
record carries `"modelId": "auto"` — so nothing here is attributable to a particular model, and the
operator's reading is that it was a cheap open-source one. Total cost of the session was under a
dollar, which is itself a datum: `design/evaluation.md` scopes benefit around end-task success and
says nothing about whether the design works when the model is cheap.

## What ran for the first time

- **kiro installs on a machine that had never seen the project**, with the agent config in the
  *global* location (`~/.kiro/agents/nathan.json`) and the project elsewhere — the case
  `--agent`-pointing-outside-the-project had never met the real binary.
- **The store is created by the harness**, no `zikaron init` anywhere: the `agentSpawn` hook
  started the service, which fetched the 64 MB artifact and created `memory.db`, in ~13 s.
- **`agentSpawn` delivers hook output to the model.** D18 rests entirely on this and it had never
  been checked against the real binary. Verified by asking the agent to quote the policy: it
  returned *"Err toward writing. The common failure is recording nothing, not recording too much"*
  plus the following sentence, which had not been shown to it.
- **12 MCP tools** under kiro, matching D32 exactly — the twelve registered in `mcp/primary.py`,
  with `memory_surface` (the hook's push path) and `knowledge_unlock` (operator business, M31's
  decision) correctly absent from the agent's surface.
- **Consolidation end to end**: one group planned, served, promoted `in_place` v1→v2 into
  `long_term`, then a second run planning zero groups.
- **D15's write-time dedup fired in production**, twice across three writes in the first session.

## Two defects the real binary found

**`kiro-cli agent create` emits `"toolsSettings": null`, and the installer refused it.** Every shape
guard in `install/writer.py` read `key in document`, so a present-but-null key was a malformed
value. kiro writes `null` for unset in four fields of its own default config, and `kiro-cli chat
--agent <name>` runs that agent normally — so the installer was refusing the harness's own default
output, the modal input to `--agent`. Fixed by `_is_unset`, which treats absent and `null` alike; a
wrong *type* is still refused, because that is data a merge would destroy. This reverses
`TestExplicitNullsAreValuesRatherThanAbsences`, whose reasoning conflated *present* with *carries
data*.

**`kiro-cli agent validate` prints `Error:` and exits 0.** Measured without a pipe. Anything relaying
its complaints must read stderr; a status check relays nothing. The installer already does this
correctly, and the relay was observed working in the live install.

## The write policy, observed

Two sessions, the second with `read`/`write`/`shell` added to the agent's tools.

**Session 1 — three settled design decisions, zero writes.** Gradle over Brazil, Spring Boot in
place of Coral, a protocol-pluggable template proven by S3. The agent had *only* Zikaron tools, so
Zikaron was the sole persistence channel available and it still wrote nothing. Challenged, it
justified itself from our own text: the decisions were *"still proposals"*. **This is a scope
finding, not a model failure.** `design/write-policy.md` gates on *"what cost someone time to
discover"* and lists six retrospective bullets; a decision reached by argument is none of them. The
policy contradicts itself one bullet later — *"conventions and preferences that are settled but
written down nowhere"* did not cost anyone time to discover either.

**Session 2 — a hard-won bug, written unprompted.** Asked for a "top N recently changed files"
script and then told it must be portable, the agent hit two real failures it had to debug
(`find -exec ls -td {} +` sorting each `ARG_MAX` batch independently; GNU `stat -c '%Y %n'`
word-splitting so paths drop silently) and reached for `memory_remember` on its own, purpose
*"so they aren't rediscovered"*. Given something genuinely hard-won, it wrote without being asked.

**The 64-token gist bound cost two of three calls**: rejected at 71 tokens, again at 67, accepted at
58. The error payload names field, limit and actual, which is why it converged rather than guessed.

**It merged three findings into one record**, against a prompt that Q12 says leans toward splitting.
Both bugs *and* the standing convention — *"the user asked that ALL shell scripts written here be
portable (target includes NetBSD)"* — went into one memory whose gist is about mtime sorting. The
convention is therefore in the store but reachable only on portability-shaped queries: both
`surface` events came from prompts about portability, and a plain "write me a script" would not
retrieve it. The gist advertises a `find`/`stat` gotcha, so a future agent has no reason to fetch,
and under D11 the convention now carries a bug report's staleness clock.

## A measurement gap this exposed

**A `BOUNDS` rejection leaves no event.** `EventKind` instruments fifteen kinds, including
`VERSION_CONFLICT`, `NO_RECEIPT` and `DEDUP_OFFERED` — every other way a write is turned away. A
gist over the limit is refused before anything is written, so the store recorded `remember: 1` for a
session that made three calls. The two rejections exist only in a kiro transcript, and
`FINDINGS.md` already records that harness transcripts survive only as long as the harness keeps
them. So the cost of the gist bound — demonstrably real, two thirds of the calls in the one clean
observation — cannot be measured where every other write-path signal is.

## Re-deriving this

The container is `zikaron-kiro`; exec as `--user ubuntu`. Sessions are under
`~/.kiro/sessions/cli/*.jsonl`, one JSON object per line with `kind` in `Prompt`,
`AssistantMessage`, `ToolResults`. **Hook output is not in the transcript** — neither the
`agentSpawn` policy nor the `userPromptSubmit` block appears there, so injection can only be
confirmed by asking the agent, and a tool result is the only record of a rejected write.
