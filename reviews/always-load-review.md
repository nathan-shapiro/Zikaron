# Review — `alwaysLoad` on both `.mcp.json` servers

Artifact under review: the change scoped in the brief — `zikaron/install/entries.py` (`ALWAYS_LOAD_KEY`,
`MCP_OWNERSHIP_FIELDS`, `claude_mcp_servers_value`), `zikaron/install/targets.py` (`_ownership`,
`_refuse_conflicting`, `_plan_mcp`, `_merged_server`), the four new tests in
`tests/test_install_targets.py`, and the prose at `design/harness.md` §"MCP tools may arrive deferred",
`design/write-policy.md` §"Project memory (Zikaron)" (the paragraph after the two fences),
`design/build-plan.md` §M32's write-time-rules bullet, and `FINDINGS.md` §"Owed work". Everything else in
the working tree is out of scope per the brief.

## Round 1 — 2026-09-29

### Summary judgment

The code is small, the two defects the researcher found are real and correctly fixed, and the mutation
verification is credible. What does not hold is the evidence chain the prose now builds on it: the
three "sources, none of them a guess" in `harness.md` are mutually inconsistent as written, so "true by
construction" and "that holds only because the install makes it hold" are asserted past what was
measured. Separately, the change narrowed a normative install-contract rule for one harness and left the
contract saying the rule is harness-independent, and it added an uncommented `type: ignore` that
`coding-standards.md` §3 forbids. Three blockers, each cheap; the rest are improvements the brief's own
questions invited.

### Findings

1. **[BLOCKER] The causal story does not close, and the normative claims overshoot it.**
   `design/harness.md` §"MCP tools may arrive deferred", lines 397–411, gives three sources. The second
   says a deferred tool is listed by name alone and *"calling it without loading first fails"*. The
   third says a production session called the verbs all session without their descriptions, *"having
   learned the schema from refusals — `remember` rejecting `headline` and requiring `gist`"*. A `bounds`
   refusal is Zikaron's — the call reached the server — so under the second bullet the schema had been
   loaded, and `ToolSearch` returns the description with it (your own words, line 405–406). The two
   bullets cannot both be true of that session. Either (a) the harness auto-loads a deferred tool on
   first call without surfacing its description, and the "fails" bullet is wrong; or (b) the session did
   load via `ToolSearch` (as M16's did) and the description *was* delivered and not attended to — the
   "knows and does not act" case `FINDINGS.md` says prose cannot fix, in which case `alwaysLoad` addresses
   the wrong cause; or (c) the tools were never deferred in that session and the self-report is wrong.
   The transcript decides it: `~/.claude/projects/-home-nathan-Trading-LeibaTrader/*.jsonl` for that
   session — was there a `ToolSearch` for the zikaron verbs before the first `remember`, and were the
   tools in the initial tool list? You have the file; the brief asks me to check reasoning you had the
   means to check. Until that is read, three sentences overclaim and should be cut to what is
   established: `design/build-plan.md:3748` *"is now true by construction"*;
   `design/write-policy.md:219` *"That holds only because the install makes it hold"*;
   `FINDINGS.md:216` *"the install now buys it"*. Also `FINDINGS.md:227` calls the `bounds`-on-first-call
   query *"the check that `alwaysLoad` works"* — it is not: it fires identically for a loaded-and-ignored
   description. The direct check is the one M16 already ran (`research/claude-code-dogfood-checkpoint.md`
   §2): a headless session under the installed config, read whether the zikaron tools are in the initial
   list and whether the first action is `ToolSearch`. One `claude -p` run; record it in `research/`.
   **Suggested change**: read the transcript, then fix whichever of lines 399 or 407–411 is wrong;
   rewrite the three overclaims as *"documented per-server exemption, present in 2.1.277; delivery
   observed / not yet observed in a session"*; and change `FINDINGS.md:227` to name the headless probe as
   the check and the `bounds` query as the proxy for *reading*.

2. **[BLOCKER] The install contract now says something the code does not do, for one harness.**
   `design/architecture.md:2197–2200` (harness-delta blockquote): *"The collision, backup and
   refuse-on-difference discipline below is harness-independent and applies to both"*; row at line
   2211: *"**refuse** if an existing Zikaron hook or server entry differs from what this install would
   write, unless `--force`"*. After this change, under Claude Code a Zikaron server entry that differs
   outside `command`/`args` is **merged**, not refused (`targets.py:847–853`, `_merged_server`), while
   kiro's `writer.py:595–601` still compares the whole entry (`existing_server != expected_server`) and
   `_merged_servers` (line 811) replaces it wholesale. So the discipline is no longer harness-independent
   and the contract's word "differs" means two things. The ownership rule is documented only at
   `harness.md:436–440`, inside a section about tool deferral, which is not where a reader of the merge
   contract looks. **Suggested change**: (i) in the `architecture.md` blockquote, state that for Claude
   Code's `.mcp.json` the difference predicate is `entries.MCP_OWNERSHIP_FIELDS` and the merge is
   per-key (a user's keys on Zikaron's entry survive; `--force` replaces whole); (ii) move the
   `harness.md:436–440` paragraph to §"What a Claude Code install writes" (the `.mcp.json` row at line
   534 is the natural anchor); (iii) either apply the same ownership predicate to kiro's server compare
   at `writer.py:595` — it is the same class and will refuse every kiro upgrade the day that entry gains
   a key — or record in the contract why kiro keeps whole-entry comparison.

3. **[BLOCKER] An uncommented, avoidable `type: ignore`.** `zikaron/install/entries.py:308`:
   `{**primary[MCP_SERVER_NAME], ALWAYS_LOAD_KEY: True},  # type: ignore[dict-item]`.
   `design/coding-standards.md:78–79` (binding): *"passes with no ignores; a genuinely necessary ignore
   carries a comment saying why it is unavoidable."* This one has no comment and is not unavoidable —
   `mcp_servers_value` returns `dict[str, object]`, so the inner entry is typed `object`. It also
   hand-copies the consolidator entry's `command`/`args` shape (lines 309–313) as a second declaration of
   what `mcp_servers_value` already builds. **Suggested change**: a typed helper
   `_server_entry(commands, mode) -> dict[str, object]` returning `{"command": …, "args": […]}`, used by
   `mcp_servers_value` and by both arms of `claude_mcp_servers_value` with `ALWAYS_LOAD_KEY: True` added;
   the ignore and the duplication both go.

4. **[IMPROVEMENT] The cost is stated but not quantified, and the corpus already holds the number.**
   `harness.md:432–434`: *"every one of Zikaron's tool schemas is then in context from session start"* —
   no figure. `research/m24-tool-list-size.md` measured exactly this surface: **18,594 bytes** for the
   primary server's twelve whole entries and **4,631** for the consolidator's four, re-derivable with
   `experiments/m24_tool_list_size.py`; that note also records that the context-inspector reading against
   a real session is *owed*. `alwaysLoad` is the decision that makes that owed reading load-bearing.
   Two further cost facts belong in the paragraph: it is cached-prefix cost, not per-turn injection
   (build-plan.md:3753 says so; harness.md does not), and always-loaded schemas presumably count toward
   the context-share threshold that decides whether the *user's other* servers get deferred — so the
   cost is partly paid by tools that are not ours. **Suggested change**: cite the two figures and the
   command, state the cache-prefix point, and name the threshold interaction as unmeasured.

5. **[IMPROVEMENT] The consolidator server's key is justified on the benefit side only, and the cost
   lands somewhere else.** `entries.py:302–304` and `harness.md:423–425` argue the consolidator's verbs
   state D26's precondition. But `alwaysLoad` is per-*server*, and `_EXPOSURE_NOTE` (targets.py:135)
   records that the primary agent sees the four consolidation verbs — so their schemas are now eager in
   **every primary session**, where the consolidator never runs, while the benefit accrues only inside
   a subagent whose whole tool list is five entries and is unlikely ever to cross a deferral threshold.
   Whether deferral fires inside that subagent at all is unmeasured. **Suggested change**: one
   consolidator spawn under the installed config, check its initial tool list; if the four verbs arrive
   loaded without the key, drop it from the consolidator entry and say why. If you keep it regardless,
   state the primary-session cost in the docstring rather than only the subagent benefit.

6. **[IMPROVEMENT] The `instructions` channel is verifiable first-hand and is half-verified already,
   which changes the cost decision.** `harness.md:429–434` treats delivery of a server's `instructions`
   as unverified because `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` has no hits — but that string bears on
   the *cap*, not on *delivery*, and the two claims are conflated in one sentence. Delivery is observable
   the same way your second bullet was: in this reviewer's own session under this harness, the system
   prompt carries a *"# MCP Server Instructions — The following MCP servers have provided instructions
   for how to use their tools and resources"* block for a server whose tools are **deferred and absent
   from the listed tools**. So eager delivery of `instructions` alongside deferred schemas is a
   first-hand observation, not a doc claim. That matters because the write-time rules are prose, not
   schema: they could ride in `instructions` (an `initialize`-time field the server returns — nothing
   in `zikaron/mcp/` emits one today) for a fraction of 23 KB, while schemas stay deferred. It may still
   be right to pay for the schemas — a model that must `ToolSearch` before every first call is friction
   the rules cannot remove — but that trade is not the one the paragraph describes. **Suggested change**:
   split the sentence into delivery (observed) and cap (unverified); name the probe as *emit
   `instructions` from `zikaron-mcp` and read one headless session*; and say why schemas-eager was
   chosen over rules-eager, or leave it explicitly open.

7. **[IMPROVEMENT] The `ENABLE_TOOL_SEARCH` rejection gives the wrong reason, ambiguously.**
   `harness.md:426–428`: *"…the binary's own text says an OS-level managed setting that turns it off
   still wins"*. A managed setting that turns tool search *off* is the case that helps Zikaron, so as
   written the sentence rejects the alternative on a case that does not hurt. The load-bearing objection
   is scope, not precedence: `ENABLE_TOOL_SEARCH=false` (which the installer *could* write into
   `settings.local.json`'s `env`) disables deferral for **every** server in the project — the user's
   budget, not ours — where `alwaysLoad` spends only our two servers' share. Precedence is at most a
   second reason. **Suggested change**: lead with scope; if the managed-settings point stays, say which
   direction of override is meant and whether managed settings can also override `alwaysLoad`.

8. **[IMPROVEMENT] Per-key merge is silent in the two directions that matter.** Under the normal path
   `_merged_server` returns `{**existing, **ours}` (targets.py:495). (a) A user who deliberately set
   `alwaysLoad: false` on our entry — plausible, given finding 4 — is flipped back to `true` on every
   re-run with nothing said; before this change any difference was at least reported. (b) Keys we do not
   write are carried forward from a file that `harness.md:543` says is **committed by design** into a
   server the same install pre-approves via `enabledMcpjsonServers` — `env` is the one with execution
   consequence. The guard is ownership equality on an absolute path, which fails to hold across
   different homes but holds in a shared dev container, a fixed-user image, or a CI runner. Before this
   change the committed entry was refused outright. **Suggested change**: at minimum, a `MergePlan` note
   conditioned on the interesting case, in the pattern `_plan_settings` already uses — *"kept `env` on
   `zikaron`, which this install did not write"* and *"`alwaysLoad` was `false` and is now `true`"*.
   The stricter option is to refuse unknown keys on our entry when the install is also pre-approving the
   server. Also record the (b) residual beside `harness.md:549–551`, whose *"refuses on the differing
   entry rather than merging over it"* is now conditional on path inequality.

9. **[IMPROVEMENT] The sibling refusal has the same defect the change fixed.**
   `_refuse_differing_hook_groups` (targets.py:759–790) compares hook groups whole (`group not in
   groups`), and its own diagnostic (line 805) lists *"timeout, matcher, or an extra field"* as things
   that trigger it. The next change to `HOOK_TIMEOUT_SECONDS` or any added hook field will refuse every
   existing Claude Code install's upgrade — exactly the class this change names. CLAUDE.md: when a defect
   turns up in one caller, audit the others. **Suggested change**: define hook-group ownership as the
   command (the recogniser `_is_a_zikaron_hook_group` already matches on it) and refuse only when
   ownership differs, mirroring `MCP_OWNERSHIP_FIELDS`; or record why hooks keep whole comparison.

10. **[IMPROVEMENT] The measured fact the fix rests on has no `research/` record.** The 2026-09-29
    production observation is cited in `harness.md:407`, `entries.py:280` and two tests, and nowhere
    in `research/` (grep for `2026-09-29` there returns nothing). Every comparable observation in
    `FINDINGS.md` cites the transcript path. **Suggested change**: a short `research/` note with the
    session's `.jsonl` path and the answer to finding 1's transcript question.

11. **[IMPROVEMENT] Three sites narrate the investigation rather than state the rule.**
    `harness.md:436–440` (*"had to be added without breaking existing installs… would have met…"*),
    `targets.py:463–467` (*"`_refuse_conflicting` **now** compares only ownership… Now that…"*), and
    `targets.py:837–842` (*"was added to these entries after installs existed"*). CLAUDE.md: the
    documents carry current truth; a fix is not annotated. Present-truth form: *ownership is `command`
    and `args`; a key outside them is an upgrade, not a conflict; the merge is per key so a user's key
    on our entry survives; `--force` replaces whole.* The `"toolsSettings": null` precedent is a
    measured reason and can stay as one clause.

12. **[NITPICK] Two over-general sentences.** `write-policy.md:219` *"That holds only because the
    install makes it hold"* is a Claude-Code fact in a paragraph about both harnesses (under kiro nothing
    is known to defer); and both there and `FINDINGS.md:217` say Claude Code *"defers MCP tools"*
    unconditionally, where `harness.md` correctly says *when the tool list is crowded*. Qualify both.

13. **[NITPICK] Two tests the brief's own questions imply.** No test exercises the `{}` projection for a
    non-dict existing entry (e.g. `"zikaron": "garbage"` → refused; under `--force` → replaced), and none
    documents what happens to a user's differing value on a key we write (`alwaysLoad: false`) —
    whichever behaviour finding 8 settles on, pin it.

14. **[NITPICK] The MCP refusal names the entry, not the field.** With ownership narrowed to two fields,
    `_refuse_conflicting`'s message could say which one differs, which is the argument
    `_describe_group_difference`'s docstring (targets.py:794–799) already makes for hooks.

15. **[NITPICK] Two tables could carry the key.** `harness.md:534` (`.mcp.json` row) and
    `README.md:281` describe what the install writes to `.mcp.json`; neither mentions `alwaysLoad`.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-29

Scope this round, per the brief: the four description rewrites and the budget guard, `README.md`, the
`--force` × note-path interaction, and whether the hook predicate, the `.mcp.json` predicate and the three
documents describing them agree. Round 1's findings 4, 6 and 10 are declined on operator authority and are
not re-raised; the consolidator's key is settled. Round 1's 2, 3, 5 (as restated), 7, 8, 9, 11, 12, 13, 14
and 15 are resolved in the tree as it stands.

### Summary judgment

The code is right and the two predicates now agree with all three documents that state them:
`harness.md:436–439`, the `architecture.md:2197–2208` blockquote and `README.md:289–298`/`397` all say
ownership-not-equality, per-key merge for `.mcp.json`, rewrite-and-report for a hook group of ours, and
whole replacement under `--force` — and that is what `_refuse_conflicting`, `_merged_server`,
`_refuse_differing_hook_groups` and `_rewritten_hook_notes` do. The four rewritten descriptions match the
normative signatures and return shapes in `architecture.md:1224–1306` and `dispatch.py:239`, and every
phrase the assets tests pin is present. What remains is prose that understates or contradicts the
researcher's own evidence: the cap bracket in `harness.md` is stale relative to the fresh-session
verification and, as written, leaves the shipped budget inside the unverified range; one test docstring
still asserts the mechanism round 1 contested and `harness.md`'s own heading says is not established; one
docstring makes a universal claim the predicate does not support; and the owed-work record names one
kiro sibling where there are two. Nothing here touches behaviour; all of it is cheap.

### Findings

1. **[IMPROVEMENT] The cap bracket understates what was verified, and the budget sits inside the stated
   uncertainty.** `design/harness.md:443–447` and `FINDINGS.md:220–221` state the cap as `(1,848, 2,054]`
   from two wire lengths. `zikaron_memory_remember`'s wire description is now **≈1,895 characters** by a
   character count of `primary.py:363–390` (24 text lines summing to 1,868 plus 27 newlines; re-derive with
   the command at `harness.md:463–470`) — inside that bracket, so a reader of §"Tool descriptions are
   capped" concludes the longest shipped description is in the range nobody has verified. But
   `harness.md:411–413` records that a fresh session carried every description untruncated, which moves
   the verified lower bound to the longest shipped length. Two consequences the section should state
   rather than leave to the reader: the bracket is now `(≈1,895, 2,054]`, and `DESCRIPTION_BUDGET = 1,900`
   therefore has about five characters of *verified* margin — the rest of the 1,900 is the guess that the
   cap is ≥ 2,000, which is fine as a decision but is not what the paragraph currently claims the
   measurement supports. **Suggested change**: at `harness.md:444–445`, replace "one at 1,848 does not"
   with the longest shipped description's length as verified in the fresh session, cite the re-derive
   command, and add one sentence: *the budget is five characters above the longest description verified
   untruncated; the margin between 1,900 and the cap is inferred, not measured.* Mirror the bracket at
   `FINDINGS.md:221`. This records evidence already collected; it asks for no new measurement.

2. **[IMPROVEMENT] The description that carries every write-time rule has no headroom, and the
   highest-priority owed item is aimed at it.** Same count as finding 1: `remember` is ≈1,895 of 1,900.
   `FINDINGS.md:250–252` names Q22's form rule for **`zikaron_memory_remember`'s description**, and the
   sequencing paragraph after it says the rule must land *before* any corpus-wide repair — so the next
   brief on that surface will discover at the gate that it cannot append a sentence. **Suggested change**:
   one sentence in the Q22 owed entry (`FINDINGS.md:250–254`): *`remember`'s description is at the budget
   (≈1,895/1,900); the form rule must displace text there, not extend it — decide what it replaces before
   the brief is written.* The same constraint binds Q21's tone pass if it ever reaches that surface.

3. **[IMPROVEMENT] A test docstring asserts the mechanism the design says is not established, and
   contradicts the code comment beside it.** `tests/test_install_targets.py:600–603`: *"a description
   arrives only if the agent calls `ToolSearch` — and one that learns the argument shape from `bounds`
   refusals instead never reads it, which a production session reported doing for a whole session."*
   `design/harness.md:356` heads the section *"how the agent recovered their names is not established"*,
   and `harness.md:399–401` and `entries.py:227–231` both say the transcript shows the agent **loading each
   verb by exact name just before first use** — under which the description *was* in context at the first
   call and nothing was learned "from refusals instead". Round 1's finding 1 was exactly this pair of
   incompatible readings; the design was hedged in response and the docstring was not. The clause at
   `harness.md:401`, *"having worked from a guessed argument shape until then"*, has the same problem: if
   the load preceded first use there is no "until then". **Suggested change**: rewrite the docstring to
   the property the test pins and the established reason — *a deferred tool is listed by name with its
   schema and description unloaded, and the write-time rules ride in the description, so both servers are
   exempted* — dropping the self-report; and either delete `harness.md:401`'s trailing clause or say what
   the agent was working from before its first load.

4. **[IMPROVEMENT] "A hand-edit never reaches this refusal" is false for one hand-edit, and README repeats
   the universal.** `targets.py:802–803`: *"A hand-edit therefore never reaches this refusal;
   `_rewritten_hook_notes` reports it instead."* `_is_ours` (`targets.py:824–830`) compares the group's
   **whole command list** with ours, so a user who adds a second hook entry of their own inside Zikaron's
   group — `{"hooks": [ours, theirs]}` — is refused as another install, with `_ANOTHER_INSTALL`'s advice
   to pass `--force`, which then replaces the group whole and drops their entry. Refusing is the right
   behaviour (a merge would drop it silently), but the docstring and `README.md:294–295` (*"Only an entry
   naming a *different* Zikaron install refuses"*) both state a universal the predicate does not hold.
   **Suggested change**: in the docstring, *ownership is the group's command list equal to ours; a group
   carrying our command plus one of the user's is refused, and the refusal prints both lists*; in README,
   *"Only an entry naming a different Zikaron install — or a Zikaron group you have put another hook
   into — refuses"*. Alternatively narrow `_is_ours` to the `zikaron-hook` commands and preserve the
   user's extra entries through the merge, but that is a behaviour change and needs its own test.

5. **[IMPROVEMENT] The kept-key note asserts pre-approval unconditionally.** `targets.py:515–518`:
   *"kept `env`, which this install did not write — review it, since this project pre-approves that
   server."* Under `--no-trust-tools`, `_plan_settings` (`targets.py:443–453`) writes no
   `enabledMcpjsonServers` at all, so on a fresh `--no-trust-tools` install the clause is false for both
   servers — the same class `_plan_settings` guards with absence-conditioned notes at 445–453 and
   692–700. **Suggested change**: pass `trust_tools` into `_merged_server` and condition the clause, or
   drop it to a reason that holds on every path: *"review it — it is handed to a server this install
   registers for the whole session."*

6. **[IMPROVEMENT] The README merge paragraph describes the Claude Code merge for hooks only.**
   `README.md:289–298` explains rewrite-and-report for a hook group and refusal for a different install,
   and says nothing about `.mcp.json`; a reader learns that file is merged per key only from the `--force`
   row's *"It also stops merging"* at line 397, which presupposes the reader already knows merging
   happens. **Suggested change**: two sentences after line 296: *`.mcp.json` is merged per key: a key you
   added to Zikaron's own entry is kept and named in the output, a value this install writes —
   `alwaysLoad` in particular — is reset to its value and named too, and only a different `command` or
   `--mode` refuses.*

7. **[IMPROVEMENT] No user-facing channel tells a pre-key install to re-run.** `FINDINGS.md:241–242`
   records that a `doctor` check is owed and unwritten. Until it exists the README is the only channel,
   and its re-run advice covers clone-mates (`README.md:257`) and *"hook command not found"* (`:691`) only;
   nothing says an upgrade of the package changes a *merged* entry, which this key is the first change to
   do. **Suggested change**: one row in the troubleshooting table (`README.md:679–692`): *"Zikaron's tools
   are listed but arrive name-only, or the agent's first calls to them are refused for argument shape" →
   "an install predating `alwaysLoad`; re-run the installer — the entry upgrades without `--force`"*, and
   one clause in the install section saying a package upgrade is followed by a re-run.

8. **[IMPROVEMENT] The owed-work bullet names one kiro sibling where the class has two.**
   `FINDINGS.md:237–240` records `writer.py`'s kiro **server** compare as still whole. Kiro's **hook**
   compare is the same: `_differing_zikaron_hooks` → `_describe_difference` (`writer.py:612–669`) is exact
   equality against the generated entry, so a changed `TIMEOUT_MS` or `HOOK_TIMEOUT_SECONDS` refuses every
   existing kiro install's own upgrade on the hook half — the hazard round 1's finding 9 named for Claude
   Code, now fixed there and latent here. CLAUDE.md's rule for a defect in one caller of a shared helper
   is to audit the others; the owed record is where that audit's result has to live or it is lost the way
   `FINDINGS.md:244–248` describes. **Suggested change**: extend the bullet to *"kiro's server compare and
   its hook compare (`_differing_zikaron_hooks`) both still compare whole"*, with the same fix predicate
   for both.

9. **[NITPICK] The field-naming the change added is not pinned.** `_differing_ownership_fields` and
   `_describe_group_difference` exist so a refusal names *what* differs, and both are deletable green:
   `test_a_conflicting_server_entry_is_refused_and_names_the_flag` (`test_install_targets.py:559–582`)
   asserts only `--force` and the server name — add `assert "command" in error`; and
   `test_another_installs_hook_is_recognised_and_refused` (`:938–952`) asserts only the trigger — add
   `assert "/other/venv/bin/zikaron-hook" in error`. The non-object path is pinned (`:706`); the dict path
   is not.

10. **[NITPICK] `--force` drops a user's key on our `.mcp.json` entry with nothing said at install time.**
    `_merged_server` returns `ours, []` under force (`targets.py:503–504`); `README.md:397` documents the
    drop and `.mcp.json.bak` holds it, so this is disclosure rather than loss. If "not refusing must not
    mean not saying" (`targets.py:466`) is meant to hold on every path, compute `kept` before the early
    return and note *"`--force` replaced the entry whole, dropping `env`; the backup has it."*

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-29

Scope this round, per the brief: the prose written while applying round 2's ten findings, checked against
what the code and the evidence support, and the per-harness scoping of the merge predicates in `README.md`
and `design/architecture.md` in both directions. Round 1's 4, 6 and 10 stay declined on operator authority;
the consolidator's key and the `.dev` version are settled. All ten of round 2's findings are applied in the
tree as it stands, and the two new tests do pin what they claim.

### Summary judgment

The code is right, the cap section now says honestly which half of `DESCRIPTION_BUDGET` is measured and
which is a bet (and `remember`'s wire description is 1,895 by my own count of `primary.py:363–390`, so
"a few characters under" is exact), and `README.md:294–311` states both predicates correctly for both
harnesses. Two sentences written this round assert past the evidence, in the pattern the brief asked me
to hunt: the new `--force` note promises the dropped key is in the backup, which the installer's own
"first backup wins" rule makes false on every re-run after the first merge — and the test covers only the
path where it is true; and the self-report sentence claims the *same* direction of error as an archive
record whose stated direction is the opposite. One sibling of round 2's finding 10 is unfixed on the hook
path, and one README promise is unscoped to Claude Code and contradicts the kiro sentence below it. The
rest are the nitpicks the brief asked for.

### Findings

1. **[BLOCKER] The `--force` note promises a recovery location that does not have the key on any run but
   the first merge.** `targets.py:512–519` writes *"--force replaced the entry whole, dropping `env`. The
   backup beside the file still has it."*, and `README.md:307` says *"The backup has them."* But the
   backup rule is **the first backup wins**: `writer.py:16–18` — *"`<config>.bak` is written only when
   nothing is there"* — and `_back_up_once` (`writer.py:735–737`) leaves an existing one in place, noting
   *"`.mcp.json.bak` already existed and was left as it was."* So the ordinary history — install (fresh
   project, no backup: `test_a_fresh_project_is_not_asked_for_a_backup_it_cannot_have`), re-run (backup
   taken, no `env` in it), user adds `env`, `--force` — prints both notes at once and the first is false:
   the backup predates the key. `test_force_says_which_key_it_dropped_from_our_own_entry`
   (`test_install_targets.py:716–736`) exercises the one path where the promise holds, which is what the
   brief's *"verified against the real installer that the backup genuinely holds it"* verified.
   `_merged_server`'s own docstring (`targets.py:502–503`) names the class: *"a note true only on the
   default path is the class `_plan_settings` conditions against."* **Suggested change**: the plan note
   is composed before the backup is taken, so either (a) carry the dropped content in the note itself —
   `dropping `env` = {json.dumps(existing["env"])}` — which is recoverable from the install output
   whatever the backup's state (weigh that `env` is where a user puts secrets, though it is their own
   terminal and their own committed file); or (b) pass `path.with_name(path.name + ".bak").is_file()`
   from `_plan_mcp` into `_merged_server` and say *"an older `.mcp.json.bak` already exists and is not
   rewritten, so it does not have it"* on that branch and *"the backup this run takes has it"* on the
   other. Mirror `README.md:307`. Add the test: install, re-run, add `env`, `--force` — assert the note
   does not claim the backup has it (or that the value was printed).

2. **[IMPROVEMENT] Hook `--force` drops a user's own entry inside our group with nothing said — the
   sibling of round 2's finding 10, fixed for `.mcp.json` only.** `_plan_settings` (`targets.py:428–439`)
   filters out every group `_is_a_zikaron_hook_group` recognises and appends ours; `_rewritten_hook_notes`
   (`869–876`) fires only when `_is_ours`, which is false for `{"hooks": [ours, theirs]}`. So the sequence
   is: the refusal prints both command lists and advises `--force` (`_ANOTHER_INSTALL`, `614–617`), the
   user passes it, and their entry is gone with no note. `README.md:410`'s `--force` row names only the
   `.mcp.json` key drop. CLAUDE.md's rule for a defect found in one caller is to audit the others.
   **Suggested change**: under `plan.force`, for a recognised group that is not ours, note the non-Zikaron
   commands it carried — *"--force replaced Zikaron's group on SessionStart, dropping
   `/usr/bin/their-own-hook`"* — with finding 1's wording rule applied to any backup claim; a clause in
   the `--force` row; a test mirroring `716–736` on the hook path.

3. **[IMPROVEMENT] "The same direction of error" is the opposite direction.** `design/harness.md:401–405`:
   the agent *"reported never having had the descriptions at all, which the transcript's loads
   contradict. That is the same direction of error `FINDINGS-archive.md` records for a recall
   self-report"*. The archive record (`FINDINGS-archive.md` §"The read path is barely used", lines
   6702–6706) is a session that reported a `search` it never made — *"it errs in the direction that
   flatters the system."* Here the agent denied having something it had loaded, which flatters the
   agent and blames the system. What the two share is the class — a self-report contradicted by the log —
   not the direction. The pointer also names a file where the archive's own rule is that its `##`
   headings are the index. **Suggested change**: *"That is the same class of error `FINDINGS-archive.md`
   §"The read path is barely used" records — a recall self-report contradicted by the event log — and
   the reason the heading above hedges."*

4. **[IMPROVEMENT] README's re-run promise is harness-neutral and contradicts its own kiro sentence.**
   `README.md:243–246`, in the install section before either harness table: *"a release can change a
   merged entry … Re-running upgrades those entries in place and needs no `--force`; it refuses only where
   another Zikaron install owns something."* `README.md:309` says *"Under kiro any difference in a
   Zikaron entry still refuses, for hooks as well as servers"*, and `FINDINGS.md:238–244` records both
   kiro compares as whole — so under kiro, the day a merged entry changes, the re-run *refuses* and needs
   `--force`, the opposite of what the paragraph promises. Same paragraph: *"`alwaysLoad` is the first
   that did"* is a claim about release history that nothing in the tree pins (only `0.1.0` is released;
   whether any kiro merged entry has moved since is not checked here). **Suggested change**: scope the
   promise — *"Under Claude Code, re-running upgrades those entries in place and needs no `--force` …
   Under kiro a changed Zikaron entry is refused and `--force` adopts the new one (see below)"* — and
   *"`alwaysLoad` is one"* for *"the first that did"*.

5. **[IMPROVEMENT] The two design statements of the predicate are each less precise than README and
   the code, one in each direction.** (a) `design/architecture.md:2200–2201`: *"kiro compares a server
   entry whole"* — kiro compares hook entries whole as well (`writer._differing_zikaron_hooks`,
   `612–655`; `FINDINGS.md:238`); the table row at `2219` says both, but the blockquote that contrasts
   the harnesses names one, so a reader takes kiro's hooks for ownership-compared. (b)
   `architecture.md:2202` and `harness.md:441`: *"the command alone for a settings hook group"* — the
   predicate is the group's command **list** equal to ours (`_is_ours`, `targets.py:842–848`), which
   the docstring at `817–821` takes pains to distinguish from *"contains our command"*; "the command
   alone" reads as the weaker one. `harness.md:443` *"kiro's equivalent"* is singular for two compares.
   **Suggested change**: *"kiro compares a server entry and a hook entry whole"*; *"the command list
   alone — equal to ours, not merely containing it — for a settings hook group"*; *"kiro's
   equivalents"*.

6. **[NITPICK] The cap bracket's interval notation contradicts the section's own next paragraph and
   §"Injection budgets".** `harness.md:448–449` *"(1,848, 2,054]"* says strictly above 1,848 and at or
   below 2,054; `457–458` says *"at or above the longest description sent and below 2,054"*;
   `harness.md:521` writes the same kind of bracket as *"[9,503, 10,502)"* and spells out why. Suggested:
   *"[1,848, 2,054)"*. And in `457–458`, *"which does not reach 1,900"* has 2,054 as its nearest
   referent; suggested: *"— and the longest sent is short of 1,900, so nothing verifies the budget."*

7. **[NITPICK] The budget's unit is unstated where the section above went to the trouble.**
   `DESCRIPTION_BUDGET` is asserted with `len()` (code points, `test_mcp_tool_descriptions.py:308–310`);
   the harness is Node, and §"Injection budgets" measured its other cap in UTF-16 units. Every
   description is BMP-only today so the two agree, and nothing says so. Suggested: one sentence in
   §"Tool descriptions are capped" — *"counted here in code points; the harness presumably counts UTF-16
   units as its injection budget does, and the two agree while descriptions stay in the BMP"* — or count
   `len(s.encode("utf-16-le")) // 2` in the guard. Also `test_mcp_tool_descriptions.py:280` *"must stay
   under"* while the check is `>`, so a description at exactly 1,900 passes: *"at or under"*.

8. **[NITPICK] Three sites say no merge *can* keep a user's entry inside our group; what is true is that
   this installer has none.** `targets.py:819–820` *"there is no merge that keeps it while still
   replacing ours"*, `README.md:301` *"no merge can keep it while still updating ours"*,
   `test_install_targets.py:1048` the same. Round 2's finding 4 itself named the merge that would
   (replace the matching entry within the group's `hooks` list). Suggested: *"and this installer does not
   merge inside a group, so refusing is the only way not to drop it silently."*

9. **[NITPICK] A dangling "Otherwise".** `README.md:302` *"Otherwise a new default timeout could never
   reach an existing install."* now follows the refusal sentence, so it reads as *"if we did not refuse
   those"*. It justifies the rewrite; move it to follow *"…so you can re-apply it."* at `299`.

10. **[NITPICK] One unqualified "defers" survives round 1's finding 12.** `design/build-plan.md:3748`
    *"Claude Code defers MCP tools, so a description arrives only when the verb is loaded"*;
    `write-policy.md:219–220` and `FINDINGS.md:217–218` carry *"when the tool list is crowded"*. Add it.

11. **[NITPICK] `mcp_servers_value`'s reason asserts kiro behaviour nothing measured.**
    `entries.py:255` *"**No `alwaysLoad`** — this is kiro's, whose tools are present in the list
    already"* — round 1's finding 12 put it correctly as *nothing is known to defer* under kiro. The
    sufficient reason is that the key is Claude Code's `.mcp.json` vocabulary and kiro's agent-config
    schema has no such field. Suggested: *"— the key is Claude Code's; kiro's config has no such field,
    and nothing is known to defer there."*

12. **[NITPICK] `claude_mcp_servers_value`'s docstring restates `harness.md:419–425` nearly verbatim.**
    `entries.py:306–314` carries the consolidator-key measurement, the operator decision and its date a
    second time — one measured paragraph in two places, the drift surface CLAUDE.md warns about. Keep the
    decision line and point at the section.

13. **[NITPICK] Two raveled lines, one misattached clause, one unlabelled row.** `harness.md:248` and
    `write-policy.md:222` each carry two sentences past the wrap. At `harness.md:246–248` the inserted
    *"each carrying `alwaysLoad` (§…)"* now sits between *"live session-wide"* and *"because that is the
    only way a subagent can reach a server at all"*, so the reason reads as attaching to the key; move
    the clause after the reason. `README.md:704` is Claude-Code-only in a table whose harness-specific
    rows are prefixed *"kiro:"*/*"Claude Code:"* — prefix it.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-29

Scope this round, per the brief: the two conditional notes written while applying round 3 and their
tests, `README.md` §"Re-run the installer" against the merge paragraphs below it, whether
`_rewritten_hook_notes`'s two branches agree with the three documents on what `--force` does to hooks,
and `_foreign_commands_in` on another install's group. Round 1's 4, 6 and 10 stay declined; the
consolidator's key and `.dev` are settled. All thirteen of round 3's findings are applied in the tree.
Checked and not at issue: `--print-only` returns before `plan_merges` (`main.py:193–218`), so neither
note can print on a run that takes no backup; `commit_merge` backs up before it writes and appends the
plan's notes only after (`writer.py:448–452`); `FINDINGS.md:238–246` now names both kiro compares and no
longer lists the merge notes as owed; no shipped description under `zikaron/mcp/` carries a non-BMP
character, so `harness.md:460` is true as written.

### Summary judgment

Round 3's blocker is fixed on the path it named and the new test pins it, but the branch that replaced
the false promise asserts its complement — *"it does not have it"* — which is false on the ordinary
history where the key was added before the run that took the backup, and `README.md` and the new test's
docstring restate that universal. Separately, the `--force` branch added to `_rewritten_hook_notes`
returns before the rewritten-group note is computed, so a hand-edited timeout on a group of ours is now
rewritten *silently* under `--force` — a regression from round 3's tree, contradicting all three
documents and the function's own docstring, on the path `writer.py:238–242` says arrives for unrelated
reasons. Both are small; both are exactly the pattern the brief asked me to hunt.

### Findings

1. **[BLOCKER] Under `--force`, a group of ours with a hand-edited field is rewritten with nothing
   said — the note the previous rounds built is unreachable on that path.** `targets.py:898–909`: the
   `if plan.force:` branch returns (`[]` or the dropped-commands note) before line 910 computes
   `rewritten`, so `_is_ours` is never consulted under `--force`. History: install; edit the
   `SessionStart` group's `timeout` to 999; run `--force` for any reason — a symlink at a shipped path,
   a clone-mate's `.mcp.json` entry, both of which the README's own text sends people to `--force`
   for. `_plan_settings:428–439` replaces the group; no note. In round 3's tree the note fired on
   `_is_ours` regardless of `force` — that is the entire point of the docstring sentence still at
   `:882–884`, *"Ownership is re-checked here rather than assumed from the refusal, which `--force`
   skips entirely"*, and of `test_force_taking_over_another_install_does_not_advise_re_applying_an_edit`
   (`:1126–1142`), both of which now describe a check the early return makes dead. The three
   documents say the opposite of the code: `harness.md:444` *"Anything else is rewritten and
   reported"*, `README.md:299–301` *"is rewritten, and the install names the trigger so you can
   re-apply it"*, `architecture.md:2206–2207` *"rewritten and reported"* — none carries a `--force`
   exception, and `writer.py:238–242` is the project's own argument that `--force` must not be read as
   "discard my edits". The no-force twin of this case is pinned at `test_install_targets.py:1030–1054`;
   no test runs it with `--force`, which is why the regression is green. **Suggested change**: do not
   return early — build `notes: list[str]`, append the dropped-commands note when `plan.force` and
   `dropped`, then *always* compute `rewritten` and append its note (the two sets cannot overlap:
   `_foreign_commands_in` is empty for an `_is_ours` group). Add
   `test_force_still_says_a_hand_edited_group_of_ours_was_rewritten`: the `:1030–1054` setup with
   `--force`, asserting `"re-apply it" in printed` and that `999` is gone. Mutation: the current tree
   fails it.

2. **[BLOCKER] The stale-backup branch replaces a false promise with a false denial.**
   `targets.py:526–530`: *"An older .bak is already there and is not rewritten, so it does not have
   it."* The `.bak` is the file as it stood on the run that took it (`writer.py:16–18`), and nothing
   orders the user's key relative to that run. History: install (fresh, no backup); user adds `env`;
   re-run *without* `--force` — the backup is taken **with `env` in it** and the merge reports *"kept
   `env`"*; user runs `--force`. `backup_is_stale` is true and the note says the backup does not have
   it; it does. The same universal is at `:515–517` (*"on every run after the first merge the `.bak`
   beside the file predates the user's key"*), `README.md:309–313` (*"which it does only if this run
   is the one that took it … on a project installed more than once the `.bak` predates your key"*),
   and the new test's docstring at `test_install_targets.py:742`. The variable's name encodes the
   assumption. **Suggested change**, either: (a) say what is true — in `_plan_mcp` read
   `<path>.bak` tolerantly (a malformed backup must not refuse the install; `_load_json_object_or_empty`
   raises, so a small `try`/`except` reader), pass that document's entry for `name` into
   `_merged_server`, and per dropped field say *"the older `.mcp.json.bak` already there has it"* when
   `backup_entry.get(field) == existing[field]`, else *"… does not have it"*; or (b) hedge — *"An older
   `.mcp.json.bak` is already there and is not rewritten; it holds the file as it stood when first
   backed up, which may predate this key."* Rename the flag to what it measures
   (`backup_already_taken`), mirror `README.md:309–313` and the docstrings, and add the test for the
   history above: assert `"THEIRS" in backup.read_text()` as the premise and `"does not have it" not
   in printed`. (a) is a dozen lines and makes the note worth reading; (b) is honest and cheap.

3. **[IMPROVEMENT] `_foreign_commands_in` reports another install's `zikaron-hook` as "dropped" in the
   same breath as the user's own command, and the two call for different responses.** On
   `{"hooks": [/other/venv/bin/zikaron-hook]}` under `--force` (`test_install_targets.py:1056–1068`
   prints nothing about the note), the output is *"--force replaced Zikaron's hook group on
   SessionStart, dropping /other/venv/bin/zikaron-hook. Those commands were inside the group it
   replaced and are not in the file any more."* True, and worth saying — the user learns which venv's
   hook was retired — but the docstring at `:886` frames this note as *"the path that discards someone's
   work"*, and on the mixed group `[/other/venv/bin/zikaron-hook, /usr/bin/their-own-hook]` both are
   listed as dropped with nothing distinguishing the takeover from the loss. The recogniser's own
   predicate (`Path(command).name == commands.hook.name`, `:808`) partitions them. **Suggested
   change**: split the sentence — *"replaced another Zikaron install's hook at `/other/…`"* for
   commands whose file name is ours, *"dropping `/usr/bin/their-own-hook`, which was yours"* for the
   rest — and decide once whether a takeover is named at all: `.mcp.json` under `--force` says nothing
   about the `command` it replaced (`_merged_server:523–534` reports only `kept`), so today a takeover
   is announced on one file and not the other by accident of which helper each path calls.

4. **[IMPROVEMENT] `README.md:246` re-states the universal round 2's finding 4 removed one paragraph
   lower.** *"it refuses only where another Zikaron install owns something"* — `README.md:302–305`
   (correctly) adds the second refusal, a Zikaron group the user has put their own entry into, and
   `_refuse_differing_hook_groups:832–837` is explicit that this is by design. The re-run paragraph is
   where an upgrading user reads first, and that project refuses its upgrade. **Suggested change**:
   *"it refuses only where another Zikaron install owns something, or where you have added a hook of
   your own inside Zikaron's group (below)"*.

5. **[NITPICK] `README.md:244` *"`alwaysLoad` is one that did"* — no release carries it.** Only
   `0.1.0` is published and this change is uncommitted; a `git+` reader of this README today finds the
   claim ahead of any release. *"`alwaysLoad` is one such change"* is true on both sides of the tag.

6. **[NITPICK] Two words in the force note overreach.** `targets.py:907–908`: *"inside the group it
   replaced"* is singular across `'; and '.join(dropped)` over several triggers; and *"are not in the
   file any more"* is false when the same command also lives in a non-Zikaron group on that trigger
   (`_plan_settings:432–433` preserves it). *"no longer in those groups"* covers both.

7. **[NITPICK] Two `FINDINGS.md` clauses, one of each kind CLAUDE.md §"Project memory" names.**
   `FINDINGS.md:241` *"and round 1 named for Claude Code's hooks"* is review-round narration; the
   bullet stands without it. `FINDINGS.md:245` *"and nothing tells its user so"* — `README.md:710`
   now does; *"nothing in the software tells its user so; the README's troubleshooting row is the only
   channel"* keeps the `doctor` item honest.

8. **[NITPICK] `harness.md:460` asserts a universal about shipped text that nothing guards.** *"every
   description this server ships is BMP-only"* is true today (checked) and becomes false the day a
   description gains an emoji or a mathematical symbol, with the code-point/UTF-16 agreement it rests
   on going with it. One line in the budget test — `assert all(ord(c) <= 0xFFFF for c in description)`
   — or counting `len(s.encode("utf-16-le")) // 2` makes the sentence a measured fact rather than a
   claim.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-29

Scope this round, per the brief: `_backed_up_servers`'s failure modes and what the `--force` note says
on each; `_user_commands_in`'s partition against the recogniser; whether the two hook notes can
contradict each other on one run; and whether `harness.md`, `architecture.md`, `README.md` and
`FINDINGS.md` still agree about `--force` after a takeover stopped being announced. Round 1's 4, 6 and
10 stay declined; the consolidator's key and `.dev` are settled. All eight of round 4's findings are
applied in the tree. Checked and not at issue: the two hook notes are disjoint per group by construction
— `_user_commands_in` non-empty means the command list is not equal to ours, so `_is_ours` is false —
and both fire on one run only for different groups; `_user_commands_in` (`targets.py:955`) is the exact
complement of `_is_a_zikaron_hook_group` (`:818`) over the same `_commands_in`; `_guard_backup_path_if_present`
(`:472`) runs before `_backed_up_servers` whenever `.mcp.json` exists, so a symlink or directory at
`.bak` never reaches the reader; the BMP guard (`test_mcp_tool_descriptions.py:313–320`) is per mode and
`harness.md:459–462` describes it as it is; `README.md:305`/`:416`, `harness.md:441–446` and
`FINDINGS.md:238–247` state the reporting behaviour the code now has; install notes reach stdout only
(`main.py:374–375`).

### Summary judgment

Round 4's two blockers are fixed on the paths they named and the new tests pin them; the hook-note
function now computes both notes on every path and its docstring matches. What was written while fixing
blocker 2 has the same shape of defect the previous three rounds found: the false branch of the `.mcp.json`
`--force` note tells the user that *the note itself* is the only record of the dropped value, and the
note carries the field's name and no value — so on the one path where the backup cannot help, the
sentence points at a record that does not exist. The reader that backs the note also has a docstring
that says the opposite of what the note does on an unreadable backup. The rest is wording.

### Findings

1. **[BLOCKER] "This note is the only record of the value" — the note contains no value.**
   `targets.py:538–539`: *"The .bak beside the file does not have {it}, so this note is the only record
   of the value."* The note is built at `:541–543` from `fields`, which is `", ".join(f"`{field}`" for
   field in kept)` — field **names**. Nothing in the install's output carries `existing[field]`
   (`commit_merge` prints `merged`/`backed up` lines and the notes, `main.py:358–375`). So a user who
   has just lost `env` reads that the note is their record of it, looks at the note, and finds the word
   `env`. `test_force_does_not_promise_a_stale_backup_holds_what_it_dropped`
   (`test_install_targets.py:766`) pins the false clause with `assert "the only record" in printed`.
   `README.md:310–313` does not repeat it, so the fix is code and test only. **Suggested change**,
   either: (a) say what is true — *"The .bak beside the file does not have {it}, and nothing this
   install writes does."*; or (b) make the sentence true by printing the value —
   `dropping `env` = {json.dumps(existing["env"])}` — which round 3 offered and you declined on the
   grounds that `env` is where secrets live; stdout is the user's own terminal but may also be a CI
   log, so (a) is the smaller change. Either way, replace the assertion at `:766` with one that matches.

2. **[IMPROVEMENT] On an unreadable backup the note denies, and `_backed_up_servers`'s docstring says
   it sends the user to look.** `targets.py:934–937`: *"the worst an unreadable one costs is that
   `--force` says the dropped value is not recoverable when it might have been. Erring that way round is
   the safe one — it sends the user to look rather than telling them not to bother."* But `{}` from the
   `except` at `:941–942` makes `saved` false at `:531–533`, and the note on that branch is *"The .bak
   beside the file does not have it"* — which is telling them not to bother, and is a false denial
   whenever the `.bak` is a permission-denied or hand-mangled file that does hold the key: the class
   round 4's blocker 2 named, on a rarer path. The docstring describes behaviour the note does not
   have. **Suggested change**: return `None` from `_backed_up_servers` on `OSError`/`ValueError` (keep
   `{}` for a readable document with no `mcpServers` object — that one genuinely does not have it),
   pass the whole `dict | None` into `_merged_server` as `backed_up` and take `.get(name)` there, and
   give `where` three branches: `None` → *"The .bak beside the file could not be read; check it for
   {it}."*; `saved` → as now; else → finding 1's wording. Then the docstring is true as written. One
   test: `chmod 0o000` the `.bak` (skip on root) or write non-JSON into it, `--force`, assert
   `"could not be read" in printed` and `"does not have" not in printed`.

3. **[IMPROVEMENT] "Has it / does not have it" is stated once for a set, and `saved` is `all()` over
   it.** `targets.py:526–540`: `kept` may hold several fields and `saved` requires every one to match,
   so with `env` in the backup and `cwd` not, the note says *"does not have them"* — false for `env`. A
   second case inside the same sentence: the `.bak` has `env` at an **older** value (install; add
   `env=A`; re-run, backup taken; change to `env=B`; `--force`) — the note says the `.bak` *"does not
   have it"*, and the user who opens the `.bak` finds an `env`. **Suggested change**: partition `kept`
   per field — same value / present with a different value / absent — and say each: *"The .bak beside
   the file has `env`; it has an older `cwd`; it does not have `timeout`."* If that is more machinery
   than the case earns, at least make "it" unambiguous: *"does not have this value of {it}"*.

4. **[NITPICK] `architecture.md:2207` promises more than the new reporting does.** *"`--force` replaces
   either whole **and says what that discarded**"* — after this round a takeover (the other install's
   entry itself) is deliberately not announced on either file; what is said is what of the *user's* it
   discarded. The next clause frames it, but the bold universal is the sentence a reader quotes.
   Suggested: *"and says what of the user's own that discarded"*. `harness.md` is silent on `--force`
   and `README.md:305`/`:416` already say "which command it dropped" / "a hook of your own", so this is
   the one of the four that is loose.

5. **[NITPICK] Two clauses in `_rewritten_hook_notes`'s docstring.** `targets.py:899–900`: *"the
   refusal already named it before the user passed the flag"* — false when `--force` arrives on a
   first run for an unrelated reason, which is exactly the case
   `test_force_still_says_a_hand_edited_group_of_ours_was_rewritten`'s docstring (`:1130–1131`) names;
   the sufficient reason is that a takeover leaves nothing of the user's to re-apply or recover.
   `:901–902`: *"which is how the rewritten-group note was lost under `--force` once already"* is an
   account of the repair rather than a reason (CLAUDE.md: fix the code, do not annotate the fix); *"so
   neither returns early"* already carries the rule.

6. **[NITPICK] A hook entry without a `command` string is invisible to the partition, and the
   docstring says otherwise.** `_user_commands_in:950–952`: *"Anything else is a hook the user put
   there"* — but `_commands_in` (`:803–807`) lists only entries carrying a `command` string, so an
   entry inside our group that has none (a malformed one, or a non-command hook type if the harness
   accepts one on these triggers) is seen by neither `_is_ours` nor this helper: the group compares
   equal to ours, is rewritten, and the entry goes with only the timeout/matcher note. Pre-existing in
   `_commands_in`, but this docstring is the one that claims completeness. Suggested: one clause in
   `_commands_in`'s docstring — *"an entry with no `command` string is invisible to ownership and to
   the notes"* — or have `_is_ours` also require the group's `hooks` list to be the same length as ours.

7. **[NITPICK] `README.md:247` is raveled** — two sentences on one ~170-character line in a file wrapped
   at ~100; *"**Under kiro** any changed Zikaron entry…"* belongs on its own line.

8. **[NITPICK] Ambiguous antecedent in a test docstring.** `test_install_targets.py:742`: *"A backup
   written *before* the user's key does not have it, and the note must not say so."* — "say so" reads
   as "say that it does not have it", the opposite of what the test asserts. *"…and the note must not
   say it does."*

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-29

Scope this round, per the brief: whether deleting the backup read loses anything a user needs; whether
the one remaining `--force` sentence is true on every path; whether the four documents agree with a note
that now promises less; then what was written while making the change. Round 1's 4, 6 and 10 stay
declined; the consolidator's key and `.dev` are settled. Checked and not at issue: `_backed_up_servers`
and `recoverable` are gone from the tree (no hit outside `reviews/`); the note at `targets.py:520–523`
prints only when `existing` is a dict, so the file existed and was loaded, and `commit_merge`
(`writer.py:448–452`) backs it up before `_replace` and extends `report.notes` only after — `_back_up_once`
finds a `.bak`, takes one, or raises, so **a `.bak` exists on every path that prints "Check the .bak"**;
the parametrized test's two histories plus `:716`'s third (the force run itself takes the backup) all
print the same sentence; the hook note's `group`/`groups` agrees with its join; `_commands_in`'s
docstring (round 5's 6), `_rewritten_hook_notes`'s docstring (round 5's 5), `FINDINGS.md:245–246`
(round 4's 7) and `architecture.md:2207–2208` (round 5's 4) are applied; `README.md:417`,
`architecture.md:2207`, `harness.md:441–446` and the code agree on what `--force` does to hooks.

### Summary judgment

The simplification is right and I would not reopen it: an imperative that names the lost key and the
one place it might be is true on every history, and the three rounds of truth-conditions it replaces
were the cost of trying to assert what the installer cannot know. What it loses is one file-open on the
history where the value is nowhere, and the key's name is enough to re-create it. But the brief's own
question — do the four documents still agree — has a "no": `README.md`'s merge paragraph still
describes the deleted reader, in three clauses, as the thing that makes the note trustworthy. One
sibling of round 4's blocker survives on the `.mcp.json` path, and the rest is small.

### Findings

1. **[BLOCKER] `README.md` describes the backup read that no longer exists.** `README.md:310–314`:
   *"`--force` is the exception: it replaces the entry whole, and says which of your keys that dropped
   — and whether the `.bak` beside the file has them — which it decides by reading it. Because of the
   backup rule above, the `.bak` on disk may have been written before or after you added the key, and
   the run that prints this note is the one where you have just lost something, so it looks rather
   than guessing."* Three claims — *says whether the `.bak` has them*, *decides by reading it*, *looks
   rather than guessing* — describe `_backed_up_servers`, which this round deleted; `_merged_server`
   (`targets.py:516–524`) reads nothing and says *"Check the .bak beside the file for it."* This is the
   document a user reads before running `--force`, and it now promises the installer will tell them
   whether the backup has the key when the installer has just been changed to refuse to say.
   **Suggested change**: *"`--force` is the exception: it replaces the entry whole, says which of your
   keys that dropped, and points you at the `.bak` beside the file. It does not say whether the backup
   has them, because it cannot know: the first backup wins, so the `.bak` on disk may have been
   written before or after you added the key."* Nothing else in the four documents restates the read
   (`grep -rn 'reading it\|looks rather than guessing\|decides by reading'` outside `reviews/` finds
   only these lines), so this is the one edit.

2. **[IMPROVEMENT] Under `--force` a user's `alwaysLoad: false` is reverted with nothing said — the
   `.mcp.json` sibling of round 4's blocker 1, on the case the docstring names as the motivating
   one.** `targets.py:516–524`: the `if force:` branch returns before `:525` computes `overwritten`,
   so the *"differed and was set to this install's value"* note never fires under `--force`. History:
   install; set `alwaysLoad: false` on `zikaron` to get deferral back; run `--force` for a symlink at
   a shipped path or a clone-mate's entry — the two reasons the README sends people to the flag.
   Deferral is off again, nothing says so. `targets.py:497–499` calls this exact case *"a deliberate
   choice being reverted … the case that motivated this"*, `:505–506` says not refusing must not mean
   not saying *"on that path as much as on the merging one"*,
   `test_a_deliberate_always_load_false_is_overwritten_and_said_out_loud`'s docstring (`:793–795`)
   says *"silently reversing a deliberate choice is the failure"*, and `architecture.md:2207` promises
   `--force` *"says what of the user's own it discarded"* — a reverted value is the user's own and is
   discarded. The hook path was fixed for this asymmetry in round 4; this is the other file.
   **Suggested change**: compute `overwritten` before the branch, excluding `MCP_OWNERSHIP_FIELDS` —
   `field not in MCP_OWNERSHIP_FIELDS` — so a takeover's `command`/`args` stays unannounced as
   decided (a no-op filter on the non-force path, where a differing ownership field was already
   refused); append its note on both paths. Test: the `:788` setup with `--force`, asserting
   `"differed and was set to this install's value" in printed`; the current tree fails it. Four
   lines.

3. **[NITPICK] A dangling "instead" in the contract blockquote.** `architecture.md:2209–2210`:
   *"Refusing instead would block every existing install's upgrade the day a timeout moved."* now
   follows the `--force` sentence, so "instead" reads as *instead of `--force` replacing*, where its
   referent is the rewrite-and-report sentence two clauses up. Move it to follow *"rewritten and
   reported"* at `:2207`, before the `--force` sentence, or write *"Refusing on those differences
   instead would…"*.

4. **[NITPICK] A test docstring narrates the note's revision history.** `test_install_targets.py:748–752`:
   *"Earlier revisions of this note tried to say which, first by assuming an existing backup must
   predate the key (false on the first history) and then by reading the file (true, but one sentence
   per outcome, with an unreadable backup, a partial match and a stale value each needing another)."*
   CLAUDE.md §"Project memory" and `coding-standards.md` §5: what an earlier version of a sentence
   said goes nowhere, and a comment explaining a fix is the next defect. Lines `744–748` and the last
   sentence (*"Look here is right on every one of them…"*) carry the rule without the history.

5. **[NITPICK] A stray `async`.** `test_install_targets.py:738` is `async def` with nothing awaited,
   the only async test in the file. It runs under `asyncio_mode = "auto"` inside an event loop for no
   reason, and is the one test that would break the day `install.main` grows an `asyncio.run`. Drop
   the keyword.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-29

Scope this round, per the brief: every behaviour the installer now has on the `.mcp.json` and settings
paths, checked against what each document says about it — by claim rather than by the phrasing of the
last edit — and then the ordinary hunt in this round's own edits, `_merged_server`'s restructured branch
above all. Round 1's 4, 6 and 10 stay declined; the consolidator's key and `.dev` are settled. All five of
round 6's findings are applied in the tree.

**Checked and not at issue.** I enumerated what the installer does — ownership-only refusal naming the
field (`targets.py:960–1000`), per-key merge with the kept-key note (`:538–544`), the overwritten-value
note on both paths with ownership fields excluded (`:520–528`), whole replacement under `--force` with the
dropped-key note pointing at the `.bak` (`:529–537`), a non-object entry refused as *"not an object"* and
replaced under `--force`, hook-group ownership as the command list equal to ours (`:859–865`),
rewrite-and-report on both paths and the dropped-user-command note under `--force` (`:868–919`), a takeover
unannounced on both files — and read every sentence about each in `README.md` (`:243–249`, `:259–267`,
`:290`, `:297–317`, `:416`, `:710`), `design/harness.md` (`:246–248`, `:397–446`, `:586`, `:595–603`),
`design/architecture.md` (`:2197–2211`), `design/write-policy.md` (`:219–222`), `design/build-plan.md`
(`:3745–3754`) and `FINDINGS.md` (`:216–247`). All of those agree with the code. The four cases of
`_merged_server` (force × overwritten/kept) are each described in its docstring and each produce the note
the docstring promises; the two notes are disjoint by construction; the ownership filter is genuinely a
no-op on the merging path, since `_ownership` projects only present fields and so an *absent* `args` is
also refused before reaching it. `commit_merge` (`writer.py:448–452`) still backs up before it writes and
appends notes after, so a `.bak` exists on every path that prints *"Check the .bak"*; `--print-only`
returns before `plan_merges`. Kiro's server and hook compares are whole (`writer.py:596`, `:612–655`), as
the four documents now say. The grep for the deleted reader finds nothing outside `reviews/`. The
parametrized test does redden on the mutation the brief describes; I did not re-run it. "Collision
policy" in `targets.py:17–19`, `main.py:10` and `harness.md:569` I read as the shipped-file rule, which
is the split `architecture.md:2199–2200` itself draws between collision discipline (shared) and
refuse-on-difference (not), so those three are consistent with the contract.

### Summary judgment

The code is right, the tests pin what they claim on both paths, and every user-facing sentence about
the two merges — the README a user reads before passing `--force` included — now says what the installer
does. What the brief's own method turned up is two claims of the same class as round 6's blocker but one
tier down: the shared writer's module docstring still states the merge refusal as a rule *"running
through everything here"*, and a landed milestone's done-when says the refuse-on-difference behaviours
are exercised *identically* against both targets, where the normative contract now says in bold that
they differ. Neither is a document a user acts on and neither is normative, so neither blocks; both are
one-sentence fixes. One decision the documents state three times is unpinned on the `.mcp.json` path
while its hook twin is pinned. The rest is wording.

### Findings

1. **[IMPROVEMENT] The shared writer's docstring states the merge refusal as a universal that Claude
   Code no longer satisfies.** `zikaron/install/writer.py:11–15`, under *"Three rules run through
   everything here"*: *"A Zikaron entry in a file the user owns that differs from what this install
   would write is a *refusal*, because that means another install owns it."* Under Claude Code an
   entry that differs outside ownership is merged and reported (`targets._plan_mcp`,
   `_rewritten_hook_notes`), and `commit_merge` in this same file is what writes those merges — so
   "everything here" includes the path on which the sentence is false. This is the claim the brief asked
   me to hunt: true when written, and the code moved under it. **Suggested change**: *"A Zikaron entry
   in a file the user owns whose **ownership** differs from what this install would write is a
   *refusal*, because that means another install owns it — the whole entry under kiro, the interpreter
   path and mode under Claude Code (`architecture.md` §"The install contract", harness delta)."*

2. **[IMPROVEMENT] M15's done-when says the refuse-on-difference behaviours are exercised identically
   against both targets, and the contract now says in bold that they are not.** `design/build-plan.md:617`:
   *"the collision, backup and refuse-on-difference behaviours are exercised identically against both
   targets"*. `design/architecture.md:2199–2201`: *"The collision and backup discipline below is
   harness-independent. **The refuse-on-difference rule is not**"*. `build-plan.md` is in scope for a
   sweep (`FINDINGS.md` §"Facts that constrain"), its briefs are amended when the truth moves (§M32's
   bullet was, in this change), and a reader who opens §M15 to learn what the installer tests hold to
   is told the opposite of the contract. **Suggested change**: *"the collision and backup behaviours are
   exercised identically against both targets, and refuse-on-difference against each target's own
   predicate (`architecture.md` §"The install contract")"* — or strike *"identically"* and set the
   correction beside it, since this is a done-when clause a reader may take as still binding.

3. **[IMPROVEMENT] The ownership filter is deletable green on the `.mcp.json` path; its hook twin is
   pinned.** Remove `and field not in MCP_OWNERSHIP_FIELDS` at `targets.py:523` and a `--force` takeover
   prints *"`zikaron`: `command` differed and was set to this install's value."* — the announcement that
   `architecture.md:2209` (*"is not announced"*), the inline comment at `:517–519` and the test docstring
   at `test_install_targets.py:799–800` all say does not happen. No test reddens:
   `test_force_replaces_a_conflicting_server_entry` (`:587–598`) reads no output, and the mutation the
   brief ran (restoring `if overwritten and not force`) verifies the both-paths property, not this one.
   The hook path pins exactly this decision in
   `test_force_taking_over_another_install_does_not_advise_re_applying_an_edit` (`:1173–1189`,
   `assert "re-apply it" not in …`). **Suggested change**: give `:587` a `capsys`, and after the
   `--force` run `assert "differed and was set" not in capsys.readouterr().out`. Three lines; the current
   tree passes it and the mutation fails it.

4. **[NITPICK] `README.md:306` promises `--force` names a command it deliberately does not name on one
   of the two refusals it overrides.** *"What refuses is an entry naming a *different* Zikaron install —
   or a Zikaron hook group you have added your own second entry to … `--force` overrides that, and then
   says which command it dropped."* On the first refusal, the dropped command is the other install's
   `zikaron-hook`, and `_rewritten_hook_notes` (`:887–891`) says nothing about it by decision. The
   `--force` row at `:416` and `architecture.md:2208` both carry the qualification; this sentence does
   not. Suggested: *"and then says which command of your own it dropped."*

5. **[NITPICK] The kept note does not agree in number where the force note two branches up does.**
   `targets.py:541–542`: *"kept {fields}, which this install did not write — review it"* reads *"kept
   `cwd`, `env` … review it"* for two fields, while `:532` computes `it`/`them` for the same `kept` on
   the force branch. Compute `it` once above both branches and use it in both.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-29

Scope this round, per the brief: `zikaron/install/writer.py`'s prose in full, since only its module
docstring had been examined in seven rounds; then the five edits applied since round 7. Round 1's 4, 6
and 10 stay declined; the consolidator's key and `.dev` are settled. All five of round 7's findings are
applied in the tree, and M15's done-when (`build-plan.md:617–618`) now reads as a rule with no history
in it.

**Checked and not at issue.** Every docstring in `writer.py` other than the module's — `Targets`,
`ShippedFile`, `Plan`, `MergePlan`, `_write_shipped`, `commit_merge`, `_differing_zikaron_hooks`
(*"the contract's word is differs"*: the contract's table row at `architecture.md:2222` is kiro's and
still says so), `_back_up_once`, `_copy_atomically`, `_merged_servers`, `_merged_resources`,
`_merged_tools_settings`, `_selecting`, `_is_our_command` — states no Claude Code merge behaviour, and
each kiro claim matches kiro's still-whole compares. `targets.py`'s module docstring, `_plan_settings`,
`_plan_mcp`, `_merged_server`, `_refuse_differing_hook_groups`, `_rewritten_hook_notes`,
`_refuse_conflicting` and `_differing_ownership_fields` agree with the code and with
`architecture.md:2197–2211`, `harness.md:441–446`, `:586`, `:595–603`, `README.md:243–249`, `:259–267`,
`:290`, `:297–318`, `:417`, `:711` and `FINDINGS.md:216–247` as they stand on disk. `main.py:119`'s
`--force` help is generic and true on both harnesses; `harness.md` §"Three flags" does not describe
`--force`; `doctor` reads nothing under `mcpServers` (the only hit in `zikaron/doctor/` is the
blind-agents message at `checks.py:227`), so no `doctor` prose can be stale on this; `distribution.md`
and `overview.md` say nothing about the merge. The mutation the brief reports is sound by reading:
without the ownership filter a takeover's `command` and `args` both land in `overwritten`, and the new
assertion at `test_install_targets.py:606` fails. The force note (`targets.py:534–535`) and the kept
note (`:540–541`) share `kept_fields` and `it`, so they agree in number for any `kept`.

### Summary judgment

The code is right and every document a user acts on says what the installer does. The one sentence
this round wrote into `writer.py` states Claude Code's ownership predicate for `.mcp.json` and then
generalises it to "everything here", which includes the settings merge — so it describes as
merged-and-reported a case the code refuses, the same reading round 3 removed from the two design
documents. One clause fixes it. The rest is nitpicks: a test docstring narrating its own round, a
`--force` branch that says nothing on one shape of entry, and a kiro message that overclaims in the
direction the owed-work entry will revisit.

### Findings

1. **[IMPROVEMENT] The module docstring's Claude Code clause is `.mcp.json`'s predicate, stated for
   both merged files.** `zikaron/install/writer.py:14–17`: *"the whole entry under kiro, the
   interpreter path and the mode under Claude Code, where a difference outside those is an upgrade
   that is merged and reported"*. For `.claude/settings.local.json` ownership is the group's command
   **list** equal to ours (`targets._is_ours:858–864`, `_refuse_differing_hook_groups:832–837`), so a
   group carrying our hook beside one of the user's differs in neither interpreter path nor mode and
   is **refused**, not merged — the case `README.md:303–307` and `harness.md:443–444` both spell out.
   `commit_merge` in this same file writes that merge, so "everything here" covers the path on which
   the sentence is false. This is the reading round 3's finding 5(b) removed from `architecture.md:2202`
   and `harness.md:441`, reintroduced in the file that writes both merges. **Suggested change**: *"— the
   whole entry under kiro; under Claude Code the interpreter path and the mode for a `.mcp.json` entry
   and the command list for a settings hook group, where a difference outside those is an upgrade
   that is merged and reported (`design/architecture.md` §"The install contract", the harness delta)."*

2. **[NITPICK] A test docstring narrates its own round.** `tests/test_install_targets.py:592–595`:
   *"The same decision the hook path pins one class down. Without the `MCP_OWNERSHIP_FIELDS` filter on
   `overwritten`, a takeover announces … — which three documents say does not happen, and which nothing
   here reddened until this assertion."* The last clause is the review-history class cut from the
   parametrized test's docstring in round 6 and from the done-when this round, and *"pins one class
   down"* is not a phrase. Suggested: *"The same decision
   `test_force_taking_over_another_install_does_not_advise_re_applying_an_edit` pins for hooks. Without
   the `MCP_OWNERSHIP_FIELDS` filter on `overwritten`, a takeover announces `command` differed and was
   set to this install's value, which `architecture.md` §"The install contract" says does not happen."*

3. **[NITPICK] `--force` over a non-object entry under our name says nothing.** `targets.py:514–515`
   returns `ours, []` for `existing = "garbage"`, so the value is replaced with no note, where the same
   flag over an object entry names every key it dropped (`:531–536`) and the docstring at `:507–508`
   says *"names what it dropped — not refusing must not mean not saying, on that path as much as on the
   merging one"*. On the ordinary history the refusal that precedes it names the entry, but `--force`
   also arrives for a symlink at a shipped path, on which nothing has said anything. One branch: when
   `force` and `existing is not None` and not a dict, append *"`{name}`: --force replaced an entry that
   was not an object. Check the .bak beside the file for it."*, and assert it in
   `test_force_replaces_a_non_object_entry_whole` (`:787–795`).

4. **[NITPICK] Kiro's server refusal asserts one cause for any whole-entry difference; its hook refusal
   beside it hedges.** `writer.py:599–602`: *"pointing somewhere else … That is a previous install from
   a different interpreter"*, and `plan_kiro_merge`'s `Raises:` (`:391–396`): *"it means a previous
   install from a different interpreter"*. Under a whole compare a user's added key or edited value
   trips the same refusal, which the hook message at `:606–611` acknowledges (*"or an entry you
   edited"*) and this one does not. Pre-existing and kiro's, so outside this change; recorded so the
   owed-work entry at `FINDINGS.md:238–244` carries it — the fix it names (ownership, not equality)
   makes these messages true, and until it lands *"That usually means"* is the honest form. No edit
   needed this round.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-09-29

Scope this round, per the brief: whether anything remains that would matter to a user or a maintainer,
and specifically whether the `--force` notes read as one report and fire in a sensible order when several
land on one run. Round 1's 4, 6 and 10 stay declined; the consolidator's key and `.dev` are settled. All
four of round 8's findings are applied in the tree, and the researcher's own tightening of the non-object
branch (`targets.py:515`, `force and existing is not None and not isinstance(existing, dict)`) is correct —
a dict `existing` can no longer reach the "was not an object" note.

**Checked and not at issue.** I reconstructed the stdout of a maximal Claude Code `--force` run from
`_print_report` (`main.py:356–375`), `commit_merge` (`writer.py:451–455`) and the two note builders. The
order is: header lines (`merged`, `backed up`), then notes in this sequence — harness-resolution notes,
shipped-file notes (including *"could not be backed up before --force replaced it"*), then per merge in
`plan_merges` order: `settings.local.json`'s backup note (*"already existed and was left as it was"*),
its dropped-user-commands note, its rewritten-group note, its approval notes; then `.mcp.json`'s backup
note, and per server the *"differed and was set"* note then the *"replaced the entry whole, dropping"*
note. So the `.mcp.json` backup note prints **immediately before** the note that says *"Check the .bak
beside the file for it"*, and the `backed up` header line covers the other history — a user is told the
backup's status in the line above the pointer on every path. The two hook notes are disjoint per group
(round 5); the two `.mcp.json` notes are not contradictory when both fire (*a field was set* and *the
entry was replaced whole* are both true of a whole replacement). `overwritten` can only ever be
`[alwaysLoad]`, since `command`/`args` are filtered and those three are all `ours` writes, so its
singular verb is always right. The `.mcp.json` notes fire only after `_back_up_once` has found or taken a
`.bak` (or raised, in which case nothing prints), so the pointer never dangles. Every prose surface —
`README.md:243–249`, `:297–318`, `:417`, `:711`; `architecture.md:2197–2211`; `harness.md:397–446`,
`:586`; `write-policy.md:219–222`; `build-plan.md:617–618`, `:3749–3753`; `FINDINGS.md:216–250`;
`writer.py:11–18`; `entries.py:225–256`, `:306–309` — agrees with the code on disk. The system-prompt
copy of `FINDINGS.md` handed to me still had the pre-round-2 owed-work bullet; the disk copy at `:238–247`
is the correct one and carries round 8's finding 4.

### Summary judgment

The change is right and complete: ownership-only refusal on both Claude Code files, per-key merge with
both directions reported, whole replacement under `--force` with every loss named, and a note text that
asserts nothing the installer cannot know. On the brief's two questions: the `--force` notes read as one
report — each is prefixed by what it is about (a server name, or *"Zikaron's hook group on <trigger>"*),
each names what went, and the recovery pointer sits directly under the backup-status line — and the order
follows the files in the order they are merged. What is left is three nitpicks, one of which records a
design option so it is not re-derived; none changes what ships. Approvable.

### Findings

1. **[NITPICK] The stated reason for whole replacement under `--force` covers only the takeover, and
   every note built for that path was built for the other case.** `targets.py:468–469` (`_plan_mcp`):
   *"`--force` replaces the entry whole, which is what it is for: it takes over an entry another install
   owns, and merging there would carry that install's keys forward."* But `_merged_server` replaces whole
   whether or not ownership differs, and the case the three rounds of `.bak` wording were about —
   `test_force_says_which_key_it_dropped_from_our_own_entry` (`:727`), the parametrized test at `:749`
   — is a user's key on **this install's own** entry, dropped on a `--force` passed for a symlink at a
   shipped path. No "other install's keys" exist there; the only keys an install writes are the ownership
   fields and `alwaysLoad`, all of which `ours` overwrites on a merge anyway. So a maintainer reading the
   docstring concludes whole replacement is needed only on takeover and may narrow it, and the README
   (`:311–312`, `:417`) states the own-entry drop as a fact with no reason. **Suggested change**, the
   minimum: one clause giving the reason that does cover it — *"…and it does so whether or not ownership
   differs: the flag has one meaning on both merged files, and on a clone-mate's committed `.mcp.json` a
   whole replacement is what keeps a stranger's `env` from riding into a server this install
   pre-approves."* The alternative, for the owed-work pool rather than this change: replace whole only
   when ownership differs and merge per key otherwise, which keeps a user's own keys on an unrelated
   `--force` run and makes the *"Check the .bak"* note fire only where something of another entry's was
   dropped. That is a third rule and needs its own sentence in five places, which is why it is not a
   request here.

2. **[NITPICK] The two `--force` loss notes point at the backup asymmetrically.** `targets.py:543–544`:
   *"dropping `env`. Check the .bak beside the file for it."* — `targets.py:918–919`: *"dropping
   /usr/bin/their-own-hook. Those commands were inside the group it replaced and are no longer there."*
   The hook note names the command, which is most of the entry, but a `matcher` or `timeout` the user
   set on that entry goes with it unnamed, and `settings.local.json.bak` is as good a place to look as
   `.mcp.json.bak` is — its backup-status line prints two notes above. Suggested: end the hook note the
   same way, *"…and are no longer there. Check the .bak beside the file for them."*, so a user reading
   the report gets the same pointer for the same kind of loss on both files.

3. **[NITPICK] The `.gitignore` snippet does not cover the file the change now names as where a
   dropped `env` lives.** `README.md:254–257` tells a Claude Code user to ignore `.mcp.json` because it
   carries machine-local paths; `.mcp.json.bak` sits beside it at the repository root, carries the same
   paths plus whatever `env` the user had set, and is committed by the same `git add -A`. Pre-existing —
   the backup predates this change — but this change is the first to send a user to that file for their
   `env` (`README.md:312–314`), which makes its git status worth one line. Suggested: `echo
   '.mcp.json.bak' >> .gitignore` as a third line of the snippet, or `.mcp.json*` in the second.

VERDICT: APPROVED

## Round 10 — 2026-09-29

Scope this round, per the brief: the three edits applied for round 9's nitpicks, plus the number-agreement
repair to the hook note, and whatever those could have falsified around them. Round 1's 4, 6 and 10 stay
declined; the consolidator's key and `.dev` are settled. The researcher declined round 9's third-rule
alternative (replace whole only on differing ownership), and I agree — round 9 said as much.

**Checked and not at issue.** The hook note (`targets.py:913–930`) reads correctly in all three shapes by
construction: `one` is true only when the loss total is 1, which forces exactly one `losses` entry, so
`group`, *"That command was"* and *"is"* can never disagree with each other; `losses` sorts over
`(str, list[str])`, which is well-defined; *"no longer there"* has the group as its referent, so the
non-Zikaron-group survival case round 4's nitpick 6 named is not contradicted. The two loss notes now end
identically, and by round 9's reconstruction of the report each sits under its own file's backup-status
line. `.mcp.json*` matches `.mcp.json.bak` — gitignore's `*` matches any run of characters except `/`,
dots included — and nothing in `zikaron/` or `tests/` reads a project's `.gitignore` for `.mcp.json` (the
only `.gitignore` code is the knowledge walker's), so no `doctor` check or guard held the old literal.
`harness.md:602` (*"the README tells them to ignore the file or re-run"*) stays true with the `*`.
`README.md:294`'s row, `:301`, `:313–318` and `:642` agree with the code. The `_plan_mcp` docstring's
*"whether or not ownership differs"* is carried by the equal-ownership clone-mate — a shared container or
fixed-user image where the committed path is this machine's path too (round 1's finding 8) — on which
the merge keeps a stranger's `env` and reports it, and `--force` is the only way to drop it.

### Summary judgment

The code changes are right and the number-agreement repair is correct on every shape. One of the three
prose edits introduced the defect this trail has been most about: the new `.gitignore` paragraph tells a
user the `.mcp.json.bak` *holds* the `env` that `--force` dropped, in the same section whose merge
paragraph — rewritten in round 6 for exactly this — says the installer cannot know that. It is one clause
and it is user-facing, so it goes back once more. The other two findings are nitpicks, one of them on a
word I supplied in round 9.

### Findings

1. **[IMPROVEMENT] The new `.gitignore` paragraph promises the backup holds the dropped `env`, which
   `README.md:317–318` says cannot be promised.** `README.md:259–261`: *"which the installer writes
   beside it before merging. It sits at the repository root, carries the same absolute paths, and holds
   whatever you had in the entry — including an `env`, which is where `--force` sends you to recover one
   it dropped."* Fifty-six lines later, the merge paragraph (`:315–318`) says: *"It does not say whether
   the backup has them, because it cannot know — the first backup wins, so the `.bak` on disk may have
   been written before or after you added the key."* The first backup wins (`:301`, `writer.py:19`), so
   the `.bak` holds the file as it stood on the run that took it; on the ordinary history — fresh install
   takes no backup, re-run takes one, user adds `env`, `--force` — it does not hold the `env`, and the
   note says *"Check"*, not *"recover"*. Round 3's blocker 1 removed this promise from the note, round 6's
   blocker 1 removed it from the merge paragraph, and it is now restated forty lines above the paragraph
   that hedges it. *"carries the same absolute paths"* and *"writes beside it before merging"* are the
   same shape, each true on some histories only (a backup taken on a project whose `.mcp.json` had no
   Zikaron entry yet carries none of our paths; the file is written before the first merge that finds
   none there, never before each). The gitignore rationale only needs *may*. **Suggested change**:
   *"**The `*` covers `.mcp.json.bak`**, the copy the installer takes of `.mcp.json` before the first
   merge that finds none there (the backup rule is below). It sits at the repository root and holds the
   file as it then stood — the same absolute paths, and whatever the entry held at the time, an `env`
   included — and it is where `--force` sends you to look for a key it dropped."*

2. **[NITPICK] `_plan_mcp`'s new reason says "pre-approves", and the docstring forty lines below rules
   that word out.** `targets.py:471–472`: *"a whole replacement is what keeps a stranger's `env` out of a
   server this install pre-approves"*. `_merged_server:507–509`: *"**Registration, not pre-approval, is
   the reason stated**: `--no-trust-tools` writes no `enabledMcpjsonServers`, and a note true only on the
   default path is the class `_plan_settings` conditions against"* — and `_plan_settings:443–453` is
   exactly that: under `--no-trust-tools` no server is pre-approved, and the `env` rides in regardless
   once the user approves the prompt. The word is mine, from round 9's suggested wording; it was wrong
   there for the reason round 2's finding 5 already gave. Suggested: *"out of a server this install
   registers for the whole session"*, the phrase `:554` already uses.

3. **[NITPICK] The hook note's new pointer and its plural shapes are unpinned, and the test beside it
   calls the command name the whole remedy.** `test_force_says_which_of_the_users_hooks_it_dropped_from_our_group`
   (`test_install_targets.py:1163–1190`) asserts the command and the trigger; the `.mcp.json` twin pins
   *"Check the .bak beside the file for it"* at `:746` and `:786`, and no test builds a group with two
   user commands or losses across two triggers, so the number agreement the researcher repaired by
   re-reading is verified by hand only — the class round 7's finding 3 raised and the tree accepted.
   Its docstring (`:1173`) says *"Saying which command went is the whole remedy, since nothing puts it
   back"*, which the pointer was added to qualify (round 9's nitpick 2: the `matcher` or `timeout` on
   that entry goes unnamed, and the `.bak` is where it may be). Suggested: `assert "Check the .bak beside
   the file for it" in printed` at `:1188`; one parametrized case with `/usr/bin/a` and `/usr/bin/b` in
   one group asserting *"Those commands were"* and *"for them"*, and one with a user command on each of
   two triggers asserting *"groups"*; and *"the whole remedy"* → *"most of the remedy — the backup may
   hold the rest"*.

VERDICT: NEEDS_CHANGES

## Round 11 — 2026-09-29

Scope this round, per the brief: the three edits applied for round 10, and the `.gitignore` paragraph read
together with the merge paragraph as a pair. Round 1's 4, 6 and 10 stay declined; the consolidator's key
and `.dev` are settled. All three of round 10's findings are applied in the tree.

**Checked and not at issue.** (1) `README.md:259–262` and `:302`/`:314–319` now make the same three claims
about `.mcp.json.bak` — taken once, before the first merge that finds no `.bak` beside an existing
`.mcp.json` (`writer.py:19–21`, `_back_up_once:737–740`); holds the file *as it then stood*; is where
`--force` sends you to *look*, not to recover — and *"the backup rule is below"* resolves to `:302`. The one
residual is the dash-clause *"the same absolute paths"*, which on a `.mcp.json` that pre-existed Zikaron
with only the user's own servers is not literally true; it is governed by *"as it then stood"*, the wording
is round 10's own, and on that history the `.bak` is a file the user was already committing, so the
gitignore rationale loses nothing. Not raised. (2) `targets.py:472` now reads *"registers for the whole
session"*, agreeing with `_merged_server`'s *"registers session-wide"* (`:506`), its stated reason at
`:508–510`, and the kept note at `:555`. The remaining *"pre-approves"* hits outside `reviews/` are all
about `enabledMcpjsonServers` itself (`targets.py:81`, `:403`, `:622`, `:690`; `README.md:378`, `:421`;
`harness.md:343`, `:351`) or a test docstring describing its own default-trust setup
(`test_install_targets.py:840`), none of them a claim conditioned on the flag. (3) The hook-note pointer is
asserted at `test_install_targets.py:1191`; the docstring at `:1173` says *"most of the remedy — the backup
may hold the rest"*; and the parametrized test at `:1194–1242` does exercise two recognised groups —
`SessionStart` and `UserPromptSubmit` are `CLAUDE_CODE.spawn_trigger` and `prompt_trigger`
(`harness/spec.py:250–251`), so both keys are in `ours` and `recognised` picks both up. Traced by hand
against `_rewritten_hook_notes:914–931`: case 1 yields *"hook group on SessionStart, dropping /usr/bin/a,
/usr/bin/b. Those commands were inside the group … for them."* and case 2 *"hook groups on SessionStart,
dropping /usr/bin/a; and on UserPromptSubmit, dropping /usr/bin/b. Those commands were inside the groups
…"*; each expected phrase is a substring of the note its case produces. The mutation the brief reports —
`one` from `len(losses)` — flips case 1 to *"That command was … for it"* and fails two of its three
phrases; confirmed by reading, not re-run.

### Summary judgment

The three edits are clean. The pair the brief asked me to read together now agrees claim for claim, the
word round 9 supplied and round 10 withdrew is gone from the one place it was wrong, and the hook note's
three shapes are pinned by tests that build the shapes rather than describe them. One docstring sentence in
the new test misdescribes why its second case exists; it is a nitpick on a test's commentary, changes no
behaviour and no user-facing text, and is not worth a twelfth round. Nothing else is left.

### Findings

1. **[NITPICK] The parametrized test's docstring says both cases make the two nouns disagree; only the
   first does.** `tests/test_install_targets.py:1219–1221`: *"These two are the shapes that need the group
   noun and the command noun to disagree with each other — several commands in one group, and one
   command in each of two"*. In case 1 they disagree (*group* / *Those commands*). In case 2 the correct
   note has both plural (*groups* / *Those commands*), so they agree — and because that case has two of
   each, a group noun wrongly derived from the *command* count would still read *"groups"* there; case 1
   is the one that catches both count-base mutations. What case 2 alone pins is the `"; and on"` join and a
   plural group noun under two triggers. Suggested, if touched at all: *"— several commands in one group,
   where the two nouns disagree, and one command in each of two, where the `; and` join and the group noun
   must pluralise —"*. Optional; the assertions are right and the test does what round 10 asked.

VERDICT: APPROVED
