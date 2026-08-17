# M15 — The installer adapter: review

## Round 1 — 2026-08-16

**Summary judgment.** The shape of the milestone is right: `HarnessTarget` keeps flow/preflight/backup
single-sourced, the kiro golden guard is exactly the regression trap this milestone needed, the prose
renderer with `_guard_known_tools` is a real mechanism rather than a convention, and the probe-backed
timeout/wildcard/tool-name decisions are all traceable to measurements. But the Claude Code merge
planners do not yet hold themselves to the discipline the kiro planner documents and enforces two
functions away in the same file: they silently drop malformed user data on a write path, and they skip
the backup-path preflight whose absence the kiro planner's own docstring names as "the half-install the
plan/commit split exists to prevent." Both violate `_install`'s stated contract ("Nothing has been
written when one is raised") and the brief's intents 3–4, and both fixes are mechanical mirroring of
code that already exists.

### Findings

1. **[BLOCKER] The Claude Code merge planners silently destroy malformed-but-user-owned data — the
   exact "defensive filtering on a write path" `writer.py` refuses on the kiro side.**
   `zikaron/install/targets.py`, `_plan_settings` (lines 302–327) and `_plan_mcp` (lines 338–350).
   Three concrete cases, each verified by reading the merge construction:
   - `settings.local.json` with `"hooks"` that is not a dict (e.g. a list — someone pasting kiro's
     array format is not exotic): `by_trigger` becomes `{}` and `merged["hooks"]` is rebuilt from ours
     alone. The user's whole `hooks` value is replaced, silently, exit 0.
   - `"hooks": {"SessionStart": {...}}` (object where a list belongs), or any trigger whose value is
     not a list: the `isinstance(value, list)` filter drops it from `by_trigger`, and the rebuilt
     `merged["hooks"]` omits the key entirely. Silent deletion of a hand-edited entry in a file the
     class docstring itself says users edit by hand.
   - `.mcp.json` with `"mcpServers"` that is not a dict: `_refuse_conflicting` early-returns on
     `not isinstance(existing, dict)`, then `merged["mcpServers"] = {**{}, **servers}` replaces it.
     (Same shape for a non-list `enabledMcpjsonServers` via `_with_servers`.)
   Kiro's writer refuses every one of these shapes (`_detect_format`, `_guard_mergeable_shapes`,
   `_guard_existing_entries`'s non-object `mcpServers` check), with the stated rationale: "defensive
   filtering on a *write* path is data loss with a reassuring shape." **Fix:** add a
   `_guard_claude_mergeable_shapes(document, *, path)` called at the top of both planners, refusing:
   `hooks` present and not a dict; any `hooks.<trigger>` value not a list; `mcpServers` present and
   not a dict; `enabledMcpjsonServers` present and not a list. Mirror kiro's refusal wording. Add the
   counterpart tests beside `test_a_malformed_settings_file_is_refused_rather_than_overwritten`.

2. **[BLOCKER] No backup-path preflight for the Claude Code merges, so a blocked `.bak` produces a
   refusal *after* four writes — violating `_install`'s own "Nothing has been written when one is
   raised".** `zikaron/install/targets.py` `_plan_settings`/`_plan_mcp` never call
   `writer._guard_backup_path`; `plan_kiro_merge` (writer.py line 391) does, and its docstring states
   precisely why: the backup is the last thing a merge does and the shipped files are written before
   it. Reproduction: existing `.mcp.json`, a **directory** at `.mcp.json.bak`, run the installer —
   both shipped files are written, `settings.local.json` is merged, then `commit_merge` →
   `_back_up_once` → `_guard_backup_path` raises `InstallError`, and `main` prints "install refused"
   over a half-installed project. **Fix:** in each Claude planner, when the merge target exists
   (`path.exists() or path.is_symlink()`), call `_guard_backup_path(path)`. Add the test: blocked
   `.bak` beside an existing merge target ⇒ exit 1 and *nothing* written, for both merge targets.

3. **[IMPROVEMENT] The done-when's "a clean install … for each harness … driven through the real
   shipped commands" is covered for kiro only.** `tests/test_install_e2e.py` hard-codes the kiro
   `--agent` flow; every M15 test drives `main()` in-process with a monkeypatched
   `Commands.from_this_interpreter`, so nothing anywhere runs the *real* `zikaron-hook` /
   `zikaron-mcp` against artefacts a `--harness claude-code` install wrote. That glue (settings file →
   command string → subprocess → payload dispatch) is exactly where "config names a trigger the hook
   ignores ⇒ silent dead push path" lives, and it needs no live model: install with
   `--harness claude-code`, read the command out of `.claude/settings.local.json`, feed it
   `SessionStart` / `UserPromptSubmit` / `SubagentStart` payloads with `CLAUDE_CODE_SESSION_ID` set,
   assert the stdout vs `hookSpecificOutput.additionalContext` channels, and speak stdio MCP to both
   `.mcp.json` entries (including `--mode consolidator`). Either add that integration-tier arm, or
   annotate the brief's done-when to say explicitly that this clause's Claude half is deferred to
   M16's live checkpoint — right now the milestone does not meet its own bar as written.

4. **[IMPROVEMENT] Under Claude Code, `--trust-tools` (the default) does not deliver the property the
   flag's help text and the design argue for — writes that do not prompt.**
   `zikaron/install/main.py` lines 97–104 ("do not pre-approve Zikaron's own tools, so every memory
   write asks permission. The default trusts them: per-write prompts push against the write policy")
   and `targets.py` `_plan_settings`: the trust branch writes only `enabledMcpjsonServers`, which
   governs whether the *servers load*, not whether each tool *call* is approved. Claude Code prompts
   per MCP tool use unless the tool is in `permissions.allow` — and probe §6's `permissions.deny`
   result proves the permissions system parses `mcp__<server>__<tool>` names. So the default Claude
   Code install likely leaves every `zikaron_remember` behind an approval prompt: precisely the
   per-write friction `writer._selecting`'s rationale calls "worse than not asking at all", now
   installed silently on the harness the project is migrating to. **Fix:** under `trust_tools`, also
   merge `permissions.allow` entries for the five primary tools into `settings.local.json`, marked
   documented-unmeasured with M16 verifying (the same standing `enabledMcpjsonServers` already
   ships on); or, minimally, correct the `--no-trust-tools` help text for this harness and add an
   install note stating that per-call approval is not pre-granted and how to grant it. Do not leave
   the current text, which promises a behaviour the install does not attempt.

5. **[IMPROVEMENT] Harness *values* are re-spelled as literals outside the seam, with no drift guard
   tying them back.** Intent 1's own defect class: `zikaron/install/entries.py` lines 46–47
   (`_AGENT_SPAWN`, `_USER_PROMPT_SUBMIT`) and line 61 (`_CLAUDE_TRIGGERS =
   ("SessionStart", "UserPromptSubmit", "SubagentStart")`) duplicate `KIRO`/`CLAUDE_CODE`'s
   `spawn_trigger`/`prompt_trigger`/`subagent_start_trigger` fields; `zikaron/install/main.py` line 47
   (`_CLAUDE_MARKER = "CLAUDECODE"`) duplicates `CLAUDE_CODE.marker_variable`. The harness-table
   drift guard covers spec↔design; nothing covers spec↔entries. If a trigger name ever moved in the
   spec, the *hook* would follow (M14's tests read the spec) while the *installer* kept writing the
   old name — an installed config naming a trigger the hook does not recognize, which fails as
   no-output-exit-0. The hook tests already model the right pattern (they import `CLAUDE_CODE.…`).
   **Fix:** derive — `_CLAUDE_TRIGGERS` from the three `CLAUDE_CODE` fields, kiro's two constants from
   `KIRO`, `_CLAUDE_MARKER` from `CLAUDE_CODE.marker_variable` (keep the comment about why
   `detect.current_harness` is *not* used; that argument is about the function, not the constant).
   `entries.py` already imports through `hook.limits` → `spec`, so no new dependency weight.

6. **[IMPROVEMENT] `--print-only` neither previews everything nor runs everywhere (brief question
   (e)).** Two halves. (i) `main.py` `_install` runs `_refuse_missing_commands` (line 153) and
   `target.refuse_unknown_model` (line 176) before the `print_only` branch, so a kiro preview
   requires an installed package *and* an authenticated `kiro-cli` — on this very machine, where
   kiro auth is expired, `--print-only --harness kiro` fails — to validate a model that the printed
   fragment neither contains nor mentions. (ii) The preview under-delivers its own help text ("see
   exactly what an install would add"): `fragment()` shows the merge entries only, and never names the
   two shipped files per harness (consolidator + skill) a real install would also write. **Fix:** in
   the `print_only` branch, convert both preflight refusals into printed notes ("the consolidator
   model X could not be validated here: …; a real install will refuse"), and append "an install would
   also write: <shipped paths>" from the already-computed `shipped` tuple. Keep the hard refusals for
   real installs.

7. **[IMPROVEMENT] `--force` replaces a shipped file with *no* backup, contradicting the safety
   argument the content-comparison trade rests on.** `zikaron/install/writer.py` `_write_shipped`
   (lines 232–260): the backup-then-replace path is inside `if exists and not plan.force`; with
   `--force`, a differing (possibly hand-edited) shipped file falls straight through to `_replace`
   with no `_back_up_once`. The docstring's own defence — "safe because nothing is replaced without
   `<name>.bak` existing first" — and `architecture.md`'s "a clobbered edit is loud, backed up before
   it is touched" are both false on this path. And `--force` is the flag the merge-conflict refusals
   *instruct* users to pass, so it arrives in combination with unrelated conflicts, not only when the
   user means "clobber my edits". **Fix:** on the force path, when content differs and something
   exists, still attempt `_back_up_once` (first-wins semantics unchanged; degrade to a note on
   failure as the stale path already does). Alternatively document the exception in both the
   docstring and the README, but backing up is cheaper than the caveat.

8. **[IMPROVEMENT] The "byte-for-byte" kiro regression guard actually asserts *parsed-dict* equality
   for every JSON artefact, so serialization drift is unguarded.** `tests/test_install_targets.py`
   `TestKiroArtefactsAreUnchangedFromM12` compares `consolidator_agent_config(...)`, `hooks_object`,
   `hooks_array` and `mcp_servers_value` as dicts (the fixture was even captured with
   `sort_keys=True`, so key order is provably not what is being pinned), while the bytes on disk come
   from `KiroTarget.shipped_files`' `json.dumps(config, indent=_JSON_INDENT) + "\n"`. A change to the
   indent, the trailing newline, or a move to sorted keys would ship different bytes to every
   existing install — each re-run then reporting "differed … rewritten" — without failing this guard.
   Intent 2 says byte-for-byte. **Fix:** extend the fixture with the exact `ShippedFile.content`
   string for the consolidator config (the skill is already asserted as a string) and assert string
   equality on what `shipped_files` returns, not on the pre-serialization dict.

9. **[IMPROVEMENT] `--harness auto` silently sides with a stale `.kiro/` against a live `CLAUDECODE`
   marker (brief question (b)).** `main.py` `_resolve_harness` and the test that enshrines it
   (`test_the_environment_marker_decides_only_when_the_project_does_not`): marker set + lone `.kiro/`
   ⇒ kiro install, exit 0. For a user sitting in a Claude Code session on a project with a leftover
   `.kiro/` (this repository's own docs recommend *keeping* `.kiro/` through a migration), that is
   the working-looking-inert install for the session they are actually in. The both-dirs refusal is
   right, and project-before-environment is right as a default — but when the two *contradict*, the
   installer currently says nothing. **Fix (cheap, report-not-enforce):** when `auto` resolves kiro
   from project evidence while the marker is set, append a note: "CLAUDECODE is set but this project
   has only .kiro/ — installed for kiro; pass --harness claude-code if that is wrong." No behaviour
   change, one line, and it closes the one silent wrong-harness path `auto` still has.

10. **[IMPROVEMENT] `.mcp.json` carries machine-local venv paths in the one file Claude Code designs
    to be committed, and nothing warns about it.** The design forbids `settings.json` precisely
    because "writing machine-local paths into a file the user commits breaks every other clone"
    (`harness.md` line 327–330) — but `.mcp.json` is *project-scoped by definition*, sits at the
    repository root, and is picked up by a routine `git add -A`; a clone-mate then gets a broken
    server plus an approval prompt for it (their `settings.local.json` pre-approval is absent by
    construction). The README's gitignore advice (lines 104–114) covers `.zikaron/` only, and the
    "Installing into a clone" paragraph covers only kiro's consolidator config. The refusal on a
    differing committed `.mcp.json` is loud, so this is recoverable — but the same argument the
    design makes against `settings.json` deserves either an answer or a warning here. **Fix:** extend
    the README's gitignore section to name `.mcp.json` (or explicitly say why committing it is
    tolerable), and add one sentence to `harness.md` §"What a Claude Code install writes"
    acknowledging the tension and the accepted residual (no per-project, declaratively-writable
    machine-local MCP scope exists).

11. **[IMPROVEMENT] An arbitrary `--model` string is interpolated into YAML frontmatter unvalidated,
    so a malformed value corrupts the agent artefact silently.**
    `entries.py` `consolidator_agent_markdown` writes `f"model: {model}"`;
    `ClaudeCodeTarget.refuse_unknown_model` checks nothing. `--model "sonnet\nfoo: bar"` injects a
    frontmatter key; `--model "a: b"` changes the document's meaning; both parse *as YAML* and so
    pass nothing loudly — the frontmatter test runs only with the default. The harness will
    eventually refuse the mangled model at spawn, but the artefact meanwhile claims things the user
    never asked for, and "silent wrong outcome is worse than loud refusal" is this milestone's own
    rule. **Fix:** in `ClaudeCodeTarget.refuse_unknown_model`, refuse any value that is not a plain
    single-line token (e.g. `re.fullmatch(r"[A-Za-z0-9._-]+", model)` — every real id satisfies it),
    with a message saying the id cannot be written into YAML frontmatter as given.

12. **[NITPICK] The shipped frontmatter `tools:` uses YAML block-list form; the probe measured the
    inline form.** `entries.py` lines 300–301 ship `tools:\n  - mcp__zikaron-consolidator`;
    `installer-probe` §7 measured `tools: [mcp__zikaron-consolidator]`. Semantically identical YAML,
    but the harness's frontmatter parser is not warranted to be a full YAML parser, and this project's
    own discipline is to ship the measured spelling. Either match the probe's inline form or add the
    block form to M16's checklist.

13. **[NITPICK] The Claude `--print-only` fragment shows `enabledMcpjsonServers` unconditionally,
    ignoring `--no-trust-tools`.** `targets.py` `fragment` (lines 352–367) prints
    `sorted(_ZIKARON_SERVERS)` under that key even when a real install with the same flags would
    withhold it. Thread `plan.trust_tools` through and omit the key (or annotate it) when unset.

14. **[NITPICK] (Brief question (c).) The two conflict mechanisms are justified — the shapes
    genuinely differ, and kiro's writer already has the same split — but their refusal prose is
    near-duplicated and their diagnostics are unequal.** `_refuse_differing_hook_groups` and
    `_refuse_conflicting` end in two hand-maintained copies of the same three-sentence explanation
    ("another Zikaron install owns them… Re-run with --force"), which will drift; and the hook
    refusal names only the *trigger*, where kiro's `_describe_difference` names the differing
    *fields* — the very thing its docstring says lets a user tell their own edit from a version
    change. Share the explanation as one constant, and consider reusing `_describe_difference` for
    the settings groups.

### Answers to the brief's remaining questions

- **(a) Content-comparison trade.** The trade is right *for this transition* — with no record of what
  past versions shipped, content is genuinely the only evidence, and the losing side is documented in
  `architecture.md` with the override-file escape hatch. But the framing "'an older Zikaron wrote
  this' and 'a human edited this' are indistinguishable by content" is only true *without a record*:
  a manifest of shipped-content hashes (per artefact, written by the installer alongside its
  artefacts) distinguishes them from the next version onward — matches-a-shipped-hash refreshes
  silently, matches-nothing is a hand edit and could refuse-without-`--force` instead of clobbering.
  Optional, forward-looking; not re-litigating the decision. The `.bak` first-wins residual has a
  cheaper fix than it looks: first-wins is the *right* semantics for merge targets (pristine
  pre-Zikaron state) and the *wrong* one for shipped-file refreshes, where Zikaron's own prior
  version is recoverable from the package and the only thing worth saving is the user's most recent
  divergent content — unique-suffixed backups for the shipped-file path (only) would remove the
  residual without touching the merge rule.
- **(b)** See finding 9. Both-dirs refusal: right, including on this repository — a dual-harness
  project genuinely is ambiguous per install, and the refusal names both flags.
- **(c)** See finding 14: justified split, shareable prose.
- **(d) Wildcard grant: right call.** The measured exclusion (§7), the loud unknown-name spawn
  refusal, and the delegation to `--mode consolidator` (where D32 lives anyway) together beat four
  names whose drift mode is a consolidator that will not start. The residual — a tool later added to
  the consolidator server is granted automatically — is owned by `mcp/consolidator.py`, which is the
  right owner. Only finding 12's serialization nit attaches.
- **(e)** See finding 6: over-strict for a preview, and the preview is also incomplete.
- **(f) `_guard_known_tools` is load-bearing for the diagnostic, not for loudness** — without it,
  `_TOOL_TOKEN.sub`'s `vocabulary[match.group()]` lambda raises `KeyError` on any unknown token, so
  the failure would be loud either way; the guard converts an opaque `KeyError` into a named error,
  which is worth having and worth one docstring sentence saying so. Can a name still reach a Claude
  artefact unqualified? Not through render (both artefact bodies pass through it; the spawn
  instruction is substituted *before* rendering); the unrendered surfaces (skill frontmatter
  description, agent description) currently contain no `zikaron_` tokens, and
  `test_no_bare_tool_name_survives_into_a_claude_artefact` reads the whole file including
  frontmatter, so a future lapse there is caught. Adequately covered.
- **(g)** The uncovered done-when clause is finding 3. Everything else in the done-when list traces
  to a test I could locate: artefact formats (`TestACleanClaudeCodeInstall` +
  `_frontmatter`/PyYAML), kiro regression (finding 8 notes it is weaker than claimed but present),
  content-change re-run without `--force` (`TestSameInstallOlderVersion`, parametrized both),
  collision/backup/refuse parity (parametrized where shared; kiro's own suite covers its side),
  approval + exposure reporting (`test_it_reports_the_approval_step_and_the_exposure`).

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-16

**Summary judgment.** Thirteen of the fifteen round-1 items are genuinely resolved, and several are
resolved better than asked — `_refuse_unmergeable_shape` covers more shapes than the round-1 list,
the golden guard now pins the exact serialized string, `TestTheInstalledConfigDrivesTheRealHook` is
a well-chosen and verified-non-vacuous integration arm, and both rejections I was asked to judge are
correct (finding 6's kept-hard command check, finding 12's block-form fixture — confirmed from
`spikes/claude-code-installer/zk-gated.md` itself). But finding 11's fix is **claimed and not
implemented**: the regex constant exists, the docstring now asserts the refusal, and the method body
is still `del model` — a green gate over a guard that is documentation only, which is precisely the
shape M14's retrospective warns about. That, plus four round-1 fixes that landed without the tests
round 1 asked for, keeps this at NEEDS_CHANGES — everything remaining is small and mechanical.

### Findings

1. **[BLOCKER] The finding-11 fix is a docstring, not a behaviour — `ClaudeCodeTarget.refuse_unknown_model`
   still checks nothing, and now claims it does.** `zikaron/install/targets.py`: `_MODEL_ID` (line 66)
   is compiled and **never referenced anywhere** (`grep -rn _MODEL_ID zikaron/` returns only the
   definition), while the method (lines 400–411) opens *"Refuse a model id that cannot be written into
   YAML frontmatter as given"* and its body is `del model`. So `--model "a: b"` still silently changes
   what the agent file means and `--model` with an embedded newline still injects a frontmatter key —
   round 1's defect intact — and the artifact now affirmatively documents a guard that does not exist,
   which is worse than the round-1 state. Neither ruff nor `mypy --strict` flags a dead module-level
   `Final`, which is why the gate stayed green. **Fix:** three lines at the top of the method —
   `if _MODEL_ID.fullmatch(model) is None: raise InstallError(f"{model!r} cannot be written into YAML
   frontmatter as given — pass a plain model id or alias (letters, digits, dots, hyphens,
   underscores).")` — plus a test: `--harness claude-code --model "a: b"` ⇒ exit 1, nothing written.

2. **[IMPROVEMENT] Four round-1 fixes landed without the tests round 1 requested, and each could be
   reverted today with the suite green.** This corpus's own M14 lesson is to trust a guard only after
   watching it fail; none of these has been watched.
   - `_guard_backup_path_if_present` (round 1 blocker 2): no test puts a **directory** at
     `.mcp.json.bak` or `settings.local.json.bak` beside an existing merge target and asserts exit 1
     with *nothing* written. Deleting both call sites fails zero tests — the commit-time re-check
     silently restores the after-four-writes failure the fix exists to prevent.
   - `_write_shipped`'s force-path backup (round 1 finding 7): `test_force_replaces_an_existing_file`
     predates the fix and asserts only replacement; nothing asserts `<name>.bak` exists after a forced
     replace of a differing file, nor the degrade-to-note path.
   - The two new refusal shapes: `TestAWrongShapedKeyIsRefusedRatherThanReplaced`'s parametrize has no
     case for `permissions` as a non-dict or `permissions.allow` as a non-list (the error path through
     `_merged_permissions` is currently unexercised).
   - `_resolve_harness`'s contradiction note (round 1 finding 9): no test sets `CLAUDECODE` beside a
     lone `.kiro/` and asserts the note is printed — the adjacent
     `test_the_environment_marker_decides_only_when_the_project_does_not` asserts behaviour only.

3. **[IMPROVEMENT] A `--no-trust-tools` re-run over a previously-trusting install prints two false
   statements.** `targets.py` `_plan_settings` (the else-branch note: "`enabledMcpjsonServers` was
   **not** written … so you will be asked to approve both Zikaron servers") and `_merged_permissions`
   ("`mcp__zikaron` was **not** added … so every memory write will ask your approval") are
   unconditional — but the merge never *removes* entries, so after a default install both grants
   remain in the file and the install output asserts the opposite of what the file now says. Kiro
   already guards its equivalent note on presence (`plan_kiro_merge`:
   `TOOL_SELECTOR not in _string_list(document.get("allowedTools"))`). **Fix:** condition both notes
   the same way — the servers absent from the existing `enabledMcpjsonServers` list, and
   `f"mcp__{MCP_SERVER_NAME}" not in present`.

4. **[IMPROVEMENT] `permissions.allow` is absent from the doc that is normative for it.**
   `design/harness.md` §"The installer's two targets" — the artefact table and §"What the install
   reports rather than enforces" (first bullet) still describe `enabledMcpjsonServers` as the only
   settings key the install writes, while CLAUDE.md/FINDINGS direct every session to `harness.md` for
   "every harness-coupled fact". The finding-4 fix added a second key, a genuine design asymmetry
   (the consolidator's server allowed **unconditionally**, even under `--no-trust-tools`), and a
   documented-unmeasured M16 dependency — all currently recorded in code comments and the README but
   not in the normative section. The README's own artefact table (the `.claude/settings.local.json`
   row, ~line 142) likewise says "plus `enabledMcpjsonServers`" while its §"Two things to know"
   says both keys are written. **Fix:** one sentence in the harness.md bullet naming both keys and the
   unconditional-consolidator rule, and two words in the README table row.

5. **[NITPICK] `_APPROVAL_NOTE` claims "this install answers both" even when it deliberately did
   not.** Under `--no-trust-tools` it prints beside the very notes saying the primary grants were
   withheld. Thread `plan.trust_tools` into `notes()` (drop the `del plan`) or soften the constant to
   "a default install answers both".

6. **[NITPICK] The integration-test docstring misattributes the real-session evidence.**
   `TestTheInstalledConfigDrivesTheRealHook`: "those belong to M16's checkpoint, which has
   additionally observed this same path end to end" — probe §9 is **M15's own** measurement, it
   observed *this* path (`SubagentStart`), not the other two triggers, and M16 has not run. Reword:
   "…belong to M16's checkpoint. This same path was additionally observed end to end in a real
   session (`research/claude-code-installer-probe.md` §9)."

### The judgments the return brief asked for

- **Finding 3 (real-command coverage): adequate.** The `SubagentStart` choice is right for the three
  reasons the docstring gives; the non-vacuity check (mutating `CHANNELS[SUBAGENT_START]`) is the
  correct discipline; and the two live-service triggers are legitimately M16's, with the deferral now
  stated in the test, the brief, and backed by probe §9's real-session observation. The kiro half
  remains `test_install_e2e.py` behind expired auth, which is environmental as stated.
- **Finding 6 pushback (`_refuse_missing_commands` stays hard under `--print-only`): agreed.** The
  printed fragment embeds those absolute command paths; a preview naming nonexistent commands would be
  actively wrong, and the refusal names the remedy. The model check's downgrade-to-note is correctly
  implemented and tested (`test_an_unvalidatable_model_becomes_a_note_rather_than_a_refusal`).
- **Finding 12 rejection: correct, confirmed from the fixture.** `spikes/claude-code-installer/zk-gated.md`
  lines 4–5 carry the block form the installer ships; the probe note now quotes it and names the
  inline form as the unmeasured one; `harness.md` records the same. My round-1 nitpick was induced by
  the paraphrase, exactly as the corrected note says.

### Verified without a new finding

Blocker 1's fix is real and broader than requested (`hooks`, `hooks.<trigger>`, `mcpServers`,
`enabledMcpjsonServers`, `permissions`, `permissions.allow` all refused; five of six tested — the
sixth is finding 2c above). Blocker 2's fix is correctly placed at the top of both planners, ahead of
every write, and kiro's path is untouched (`plan_kiro_merge` and `_back_up_once` still call the
now-public `guard_backup_path`). Finding 4's two-key model is mechanically correct, uses the
documented `mcp__<server>` server-level form, preserves user-curated `permissions.allow` order, and
the consolidator-unconditional asymmetry is well argued and tested. Finding 5's derivations are real
(`KIRO.spawn_trigger`/`prompt_trigger`, the three `CLAUDE_CODE` trigger fields with the `is not None`
narrowing, `CLAUDE_CODE.marker_variable`) and typed against the spec. Findings 7, 8, 9, 10, 13 and 14
are implemented as described; 8's fixture carries the exact `consolidator_config_bytes` string and
the test asserts what `shipped_files` returns; 14's shared `_ANOTHER_INSTALL` constant and
`_describe_group_difference` both exist, the latter with its own refusal-names-what-differs test.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-16

**Summary judgment.** All six round-2 findings are genuinely resolved, this time in behaviour and
not only in prose, and each is guarded by a test that fails on revert — I traced every one of the
claimed revert-detections through the code rather than taking the return brief's word for it. The
blocker's fix is real: `ClaudeCodeTarget.refuse_unknown_model` (`zikaron/install/targets.py`
lines 425–432) raises on `_MODEL_ID.fullmatch(model) is None`, and the collateral defect the new
test surfaced (`--model ""` silently becoming the harness default through `or`-selection) is fixed
with `is None` at `main.py` line 180 and covered by the `""` parametrize case. A fresh adversarial
pass over the whole surface — merge idempotence on re-runs, the plan-time guard ordering ahead of
every write, the force-path and symlink branches of `_write_shipped`, note conditioning on partial
grant presence, and the print-only asymmetries — found no remaining material defect. What is left
is two nitpicks, both genuinely optional.

### Verified, so the next round (if any) need not re-check

- **Round-2 blocker.** The method body raises; the docstring now describes code that exists. The
  four watched-failing paths check out by trace: a bare-`return` revert makes
  `test_a_model_id_that_would_change_the_frontmatters_meaning_is_refused` and all four
  `test_no_malformed_model_reaches_the_artefact` cases exit 0 with artefacts written. The check
  runs *before* `shipped_files` in `_install` (line 209 vs 210), so no malformed model is ever even
  serialized.
- **Round-2 finding 2, all four.** Removing both `_guard_backup_path_if_present` call sites makes
  the parametrized blocked-`.bak` test fail on its written-artefact assertions (the commit-time
  re-check fires after `write_shipped_files`); reverting `_write_shipped`'s force backup
  (writer.py lines 234–247, confirmed present with the degrade-to-note branch) makes the `.bak`
  read raise `FileNotFoundError`; the two `permissions` shape cases exit 0 on a
  treat-as-absent revert; and the marker-note test asserts the printed text itself.
- **Round-2 finding 3.** Both notes are absence-conditioned (`_ZIKARON_SERVERS.issubset(_strings_in(listed))`
  at line 353; `f"mcp__{MCP_SERVER_NAME}" not in present` at line 542), the re-run test asserts
  both the file state and the absence of both false sentences, and both merges are idempotent
  (`wanted - present` / `_ZIKARON_SERVERS - _strings_in(existing)` go empty on a second default
  run, which the parametrized unchanged-re-run test pins).
- **Round-2 findings 4–6.** `harness.md` carries the Tool approval table row (line 323) and the
  rewritten two-key bullet with the unconditional-consolidator asymmetry, the wildcard form, the
  documented-unmeasured M16 dependency, *and* the absence-conditioning sentence; the README table
  row (line 142) names both keys; `_APPROVAL_NOTE` says "a default install answers both"; the
  integration-test docstring now attributes probe §9 to M15's own measurement of this trigger.

### Findings

1. **[NITPICK] `_MODEL_ID`'s comment makes an unmeasured universal claim.** `targets.py` line 64:
   "Every id and alias either harness serves satisfies it" — Claude Code also accepts the bracketed
   long-context alias form (`sonnet[1m]`, via `/model` and `ANTHROPIC_MODEL`), which `[A-Za-z0-9._-]+`
   refuses; whether agent-frontmatter `model:` serves that form is unprobed either way. The
   *behaviour* is the safe one — a loud refusal, zero writes, and a hand edit as the escape hatch —
   so nothing needs to change in code. Suggested: soften the comment to "every plain id and alias
   the probes exercised satisfies it" (or add `[]` to the class if M16 ever measures the bracketed
   form in frontmatter), so the comment does not claim a universal this corpus's own rule says to
   measure first.
2. **[NITPICK] The print-only downgrade note misdescribes the deterministic refusal.** `main.py`
   lines 196–199: for Claude Code, `--print-only --model "a: b"` prints "the model could not be
   validated here (…)" — but the shape check is local and deterministic; the model *was* validated
   and failed, unlike kiro's genuinely unreachable-harness case the wording was written for. The
   embedded exception text and the "A real install would refuse" sentence keep it actionable, so
   this is cosmetic. Suggested: "the model was refused (…)" or branch the phrasing on the exception,
   if the file is ever touched again.

Both findings are stylistic; neither changes what any install writes or refuses. The milestone
meets its brief as amended, the round-1 and round-2 intentional lists are respected, and the
watched-failing discipline the corpus asked for is now actually in the suite rather than in the
narrative.

VERDICT: APPROVED

## Round 4 — 2026-08-16 (targeted: absent-harness refusal, `_MODEL_ID` widening, test tiering)

**Summary judgment.** The behaviour changes are right and are placed correctly: `refuse_absent_harness`
is one shared, seam-parameterized rule that fires before any write on both harnesses, the `--print-only`
downgrade is real and tested, the `_MODEL_ID` widening is probe-backed with the load-bearing anchor
correctly identified, and the tier split with `stub_harness_binaries` genuinely makes the default suite
hermetic without weakening a single e2e/takeover assertion. One thing blocks: the flagship test of the
new `integration_claude` tier — the one the normative coding-standards text now cites as the coverage
for "the name the seam carries" — is vacuous under this file's own autouse stub and converts the one
failure it exists to catch into a silent skip. That is the exact test-shape M14's retrospective warns
about, and the fix is a few lines.

### Answers to the seven pressure-test questions

- **(a) Placement and write-freedom: verified by trace.** In `_install`, `refuse_absent_harness()`
  (main.py line 214) runs after only pure checks (`_resolve_harness`, `_refuse_missing_commands`,
  `_refuse_unusable_agent_flag`, path-shape refusals) and before `shipped_files`, `guard_shipped_targets`,
  `plan_merges` and every write, on both targets — the target classes add no writes of their own before
  it. Under `--print-only` both refusals sit inside the try at lines 193–204, the branch returns before
  `guard_shipped_targets`, and the new test asserts zero files for both harnesses. One inherent narrowing,
  acceptable: the shared try means an absent binary masks a simultaneously-malformed `--model` in the
  preview note (first refusal wins); the fragment contains neither, so nothing printed is wrong.
- **(b) Presence, not health: right.** The refusal's rationale is "nothing on this machine would *read*
  these files", and an installed-but-broken `claude` still reads them once fixed — health is a different
  problem with a different remedy, exactly as the docstring says. The kiro double-coverage asymmetry is
  inherent to kiro's model check needing a working binary, not something this change introduced or could
  remove. A `--version` health probe would add latency and a new way to refuse for reasons irrelevant to
  the install. No change wanted.
- **(c) "Nothing may live only in those tiers": holds for our code.** Every installer/parser behaviour
  in `integration_kiro` (`available_model_ids` parsing, `validate_agent_config` handling) is covered
  hermetically by the `subprocess.run` fakes in the same file, and `integration_claude`'s
  not-refused-when-present path is covered by the stub-True positive installs. The legitimate residents
  are harness-behaviour claims — but the coding-standards enumeration under-counts them (finding 4), and
  the claude tier's name-claim test cannot currently fail (finding 1).
- **(d) e2e/takeover not weakened: confirmed, with one real loss at the margin.** `main()` runs inside
  test functions (via `_install`), so the function-scoped `usefixtures` stub is active where it matters;
  every assertion in both files is about the hook subprocess, the service, the socket, the MCP surface
  and the store — none touches the binary, and `complaints_about` output was never asserted. The one
  thing that disappeared is incidental-but-real: before the stub, every e2e run drove the *real*
  `kiro-cli agent validate` over the *real shipped consolidator config*; now no tier anywhere validates
  the shipped artefact against the real validator (finding 3).
- **(e) `pytestmark` merge: confirmed in both files.** `test_install_e2e.py` lines 43–46 and
  `test_install_takeover.py` lines 45–48 each carry one list assignment with both
  `pytest.mark.integration` and `pytest.mark.usefixtures("stub_harness_binaries")`, plus the comment
  recording the replacement trap.
- **(f) YAML-special bare words: your judgement is right.** `--model no` is a type change inside a
  scalar position — the document's structure and every other key are untouched — and whichever way the
  harness's parser reads it (js-yaml-family parsers do not even treat `no`/`y` as booleans under the
  1.2 core schema), the outcome is a loud spawn-time refusal of a model nobody has, which probe §7d
  measured. An ad-hoc keyword denylist would defend against an unmeasured parser with an unmeasured
  list — worse on this corpus's own rules. No change. (Checked the widened pattern against the edge
  cases: `sonnet[1m]` admitted, `[1m]` refused by the anchor, embedded newline/colon/space still refused
  under `fullmatch`, unbalanced `sonnet[1m` admitted but is a plain YAML scalar and fails loudly at
  spawn like any typo.)
- **(g) `harness_is_available()`: keep it.** Not dead — `available_model_ids` guards on it and five
  tests in `test_install_harness.py` patch or call it by name. It is the kiro-specific presence
  question with the binary baked in; inlining `binary_is_available(KIRO_BINARY)` would churn six call
  sites to delete four lines. What *is* worth touching next to it is finding 2.

### Findings

1. **[BLOCKER] The `integration_claude` tier's name test is vacuous and cannot fail — a wrong
   `harness_binary` produces a green tier.** `tests/test_install_targets.py` lines 1293–1296: the
   module's autouse `_harness_answers` fixture (line 92) pins `harness.binary_is_available` to
   `lambda _name: True` for **every** test in the file, including `TestAgainstTheRealClaudeBinary`, so
   `assert harness.binary_is_available(CLAUDE_CODE.harness_binary)` asserts the stub back to itself.
   The only name-sensitive line is the `shutil.which` skip guard — so mutate the seam
   (`harness_binary="clod"` in spec.py) and run `-m integration_claude` on this machine: **both tests
   skip, exit 0, nothing fails.** The class docstring ("nothing anywhere would notice if the name were
   wrong" — implying this tier notices) and `design/coding-standards.md` §4's normative claim that the
   name-claim is covered by this test are both false as written; this is the pass-vacuously shape M14's
   retrospective names, in the round that cites that retrospective. **Fix:** in
   `test_the_name_the_seam_carries_is_a_binary_that_exists`, restore the real function
   (`monkeypatch.setattr(harness, "binary_is_available", _REAL_BINARY_IS_AVAILABLE)`) and **fail rather
   than skip on absence** — the tier is only ever run by explicit request, so absence is a legitimate
   failure: `assert shutil.which(CLAUDE_CODE.harness_binary) is not None, "<binary> is not on PATH:
   either this machine lacks Claude Code (do not run -m integration_claude here) or the seam's
   harness_binary name is wrong"`. Keep the second test's skip if you like — once the first fails on
   absence, the tier can no longer go silently green on a wrong name. Then verify by the mutation
   above, per the project's own watched-failing rule.

2. **[IMPROVEMENT] `KIRO_BINARY` re-spells `KIRO.harness_binary` — round 1 finding 5's exact defect
   class, reintroduced beside the field that was created to prevent it.**
   `zikaron/install/harness.py` line 24 (`KIRO_BINARY: Final = "kiro-cli"`) and
   `zikaron/harness/spec.py` line 145 (`harness_binary="kiro-cli"`) are two hand-maintained copies of
   one seam value with no drift guard between them: `refuse_absent_harness` checks the spec's spelling
   while `available_model_ids`/`validate_agent_config` spawn the constant's. If they ever diverge, the
   install refuses (or passes) on one name and then execs another. **Fix:** derive it, exactly as
   `main.py` line 52 already does for the marker —
   `from zikaron.harness.spec import KIRO` then `KIRO_BINARY: Final = KIRO.harness_binary` (no cycle:
   spec imports nothing from install; keep the comment about PATH resolution, which is about the
   lookup, not the name).

3. **[IMPROVEMENT] No tier now validates the shipped consolidator config against the real
   `kiro-cli agent validate`.** Before this round, every e2e run incidentally drove the real validator
   over the real written artefact via `complaints_about`; the stub removed that, and the tier test that
   should replace it — `test_install_harness.py::test_the_real_validator_accepts_a_config_we_write`
   (line 183) — validates a hand-written toy (`{"name": "probe", "description": "d", ...}`), which
   asserts a belief about a document nothing ships. **Fix:** in that test, serialize the real artefact
   — `consolidator_agent_config(Commands(...), model=...)` dumped exactly as `KiroTarget.shipped_files`
   does — to `tmp_path` and validate that (if the validator objects to nonexistent command paths,
   point `Commands` at two touch-created files, as the unit fixtures already do). That restores the
   one real check the stubbing removed, in the tier built to hold it.

4. **[NITPICK] `design/coding-standards.md` §4's enumeration of binary-only residents does not match
   the suite.** Lines 90–93: "What legitimately remains binary-only … Both are single tests." The
   kiro tier holds **three** tests (real-format parsing, schema acceptance of a config we write,
   model-non-checking — all three are harness-behaviour claims a stub cannot make), and the claude
   tier holds **two**. The rule itself holds; the normative sentence enumerating it will be read as
   exhaustive and is not. Reword to name the claims per tier or drop "Both are single tests".

5. **[NITPICK] A stale assert message and a stale module docstring, both made false by this round's
   own changes.** (i) `tests/test_install_e2e.py` line 86: `"the install refused on a machine where
   the real harness is present"` — under `stub_harness_binaries` no real harness is consulted; say
   "…where the harness checks are answered for". (ii) `zikaron/install/harness.py` lines 1–11:
   "Everything install asks the installed **kiro** harness… **Two** questions" — the module now also
   answers a generic presence question for Claude Code through `binary_is_available`. One sentence
   fixes it.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-08-16 (verification of round 4)

**Summary judgment.** All five round-4 findings are genuinely resolved, and finding 3's resolution is
the round's real contribution: rather than accepting a passing rewrite, the researcher asked whether
the validator could ever say no, measured that it signals complaints by stderr-at-exit-0, and thereby
exposed and fixed a check that had been a no-op since M12 — with the fix, the measured table, the
hermetic tests, the vacuity-breaking integration test, and the design/archive record all in place and
mutually consistent. One material item remains, introduced by the round's own finding-4 fix: the
binding coding-standards text now states a fail-rather-than-skip rule that five of the six tests it
governs violate, and under it the kiro tier retains exactly the green-by-skip shape the rule was
written to forbid. That one improvement, plus two optional nitpicks, is everything.

### Answers to the four questions, in the brief's order

- **(a) The validator fix is correct, and the wide reading of "complaint" is the right one.**
  Traced end to end: `complaint = stderr.strip() or stdout.strip()` then `return complaint or None`
  on a zero exit (`zikaron/install/harness.py` lines 170–175); `KiroTarget.complaints_about` wraps it
  with the path and command name (`targets.py` lines 304–311); it lands in `report.notes` and
  `_print_report` prints it after the file lines (`main.py` lines 233, 360–361) — so a complaint that
  can now actually appear is printed, the exit stays 0, and the report-not-gate contract survives
  intact. Multi-line diagnostics survive (`strip` trims ends only) and print legibly under the
  `\n{note}` form. The warning-on-valid-config worry is real but correctly resolved as-is: today the
  measured shape is empty streams on a valid config, and that assumption has a live guard —
  `test_the_real_validator_accepts_the_config_we_actually_ship` asserts `is None` against the real
  binary, so if a future kiro starts chattering on success, the tier goes red and the question gets
  re-asked with evidence. Narrowing now (e.g. matching an `Error:` prefix) would re-encode a belief
  about the format — the exact defect class that produced the three-milestone no-op. Keeping the
  non-zero branch is right, and its no-output fallback names the exit code. Whitespace-only stderr
  correctly falls through to `None`. ANSI relay is intentional per the brief; not re-flagged.
- **(b) The new `integration_kiro` test is non-vacuous and correctly tiered.** Revert
  `validate_agent_config` to the old exit-code logic and the real binary's exit-0-with-stderr answer
  becomes `None`, so `test_it_reports_a_broken_config_on_stderr_while_still_exiting_zero`'s
  `assert complaint is not None` fails — it pins the precise defect it commemorates. It belongs in
  that tier: "the harness can say no at all" is a claim about the harness's own behaviour that a stub
  would only assert back to us, and the hermetic counterpart
  (`TestAComplaintIsOutputNotAnExitCode`, whose fixtures now encode the *measured* shapes) satisfies
  the nothing-lives-only-in-those-tiers rule. Two residuals: its skip guard (finding 1) and its name
  (nitpick 3).
- **(c) The enumeration is current; what went stale instead is the adjacent rule.** Counted against
  the suite: `integration_kiro` holds four tests (`TestAgainstTheRealBinary` three,
  `TestTheRealValidatorComplainsAtAll` one), `integration_claude` holds two — matching "currently
  four … and two" at `design/coding-standards.md` lines 91–92, and the doc now sensibly delegates the
  listing to `--collect-only` rather than a paragraph that has gone stale twice. But the paragraph
  right below it (lines 97–101) makes a universal behavioural claim the suite contradicts —
  finding 1.
- **(d) Nothing broken found.** Finding 1's fix: `test_the_name_the_seam_carries_is_a_binary_that_exists`
  restores `_REAL_BINARY_IS_AVAILABLE` (captured at line 63, before the autouse stub) and fails with
  a message naming both causes; the test-body `setattr` correctly overrides the autouse
  `_harness_answers` fixture; the mutation trace agrees with the researcher's (`"clod"` ⇒ real
  `which` ⇒ assert fires). The second test cannot mask it: its skip fires only on genuine absence,
  and on a wrong name the first test has already failed the tier. Finding 2's fix: `KIRO_BINARY`
  derives from `KIRO.harness_binary` with an identical value, no cycle (`spec.py` imports `enum` and
  `typing` only), the PATH comment correctly re-scoped to the lookup, and `zikaron/install/harness.py`
  sits outside the stdlib-only guard's discovered packages so nothing new is enforced or violated.
  The e2e/takeover tiers are unaffected by the now-capable validator because
  `conftest.stub_harness_binaries` (line 87) already stubs `validate_agent_config` to `None`.
  `architecture.md` §"The install contract" (lines 1899–1907) and the FINDINGS-archive dogfooding
  entry both record the measured table accurately, including the transferable lesson that the unit
  fixtures encoded the belief the binary contradicts. Finding 5's two strings are fixed as asked.

### Findings

1. **[IMPROVEMENT] The finding-4 fix wrote a rule into the binding standards that five of the six
   governed tests violate, and under it the kiro tier still goes green-by-skip on a missing or
   wrongly-named binary.** `design/coding-standards.md` lines 97–101: "Tests in these tiers **fail
   rather than skip** on a missing binary" — but all four `integration_kiro` tests guard with
   `pytest.skip` (`tests/test_install_harness.py` lines 183–184, 199–200, 225–226, 281–282), as does
   the second claude test (sanctioned in round 4, fine once the first fails). Consequence:
   `pytest -m integration_kiro` on a kiro-less machine — or one where the name is wrong on *both*
   sides of the spec↔design drift guard (`test_harness_table.py` line 144 pins spec against
   `harness.md`, not against the machine; an upstream binary rename lands on both at once) — exits 0
   with four skips. That is the round-4 blocker's shape on the other harness, now directly
   contradicted by a sentence in a document CLAUDE.md calls binding, and finding 2's fix raised the
   stakes by making `KIRO.harness_binary` the single spelling everything kiro execs. **Fix (prefer
   the first):** hoist the guard into a failing assert mirroring the claude test — e.g. a
   module-level `_require_kiro()` used by both marked classes:
   `assert shutil.which(KIRO.harness_binary) is not None, "…either this machine lacks kiro-cli (do
   not run -m integration_kiro here) or the seam's harness_binary names the wrong binary…"` — about
   a dozen lines, then verify by the same `"clod"`-style mutation. Alternatively narrow the
   standards sentence to "each tier's presence test fails rather than skips on absence" and
   designate one per tier; do not leave a binding universal the suite falsifies, which is M14's
   always-loaded-file shape in the normative layer.
2. **[NITPICK] The test module's docstring still says "the two questions install asks the installed
   kiro binary."** `tests/test_install_harness.py` line 1. Round 4 finding 5(ii) fixed the mirror
   sentence in `zikaron/install/harness.py` but not this one, and the module now covers three
   functions, one of them either-harness's. One sentence, same shape as the fix already made.
3. **[NITPICK] The "while still exiting zero" half of the new integration test's name is asserted by
   nothing.** `tests/test_install_harness.py` lines 278–287: `validate_agent_config` hides the exit
   code, so a future kiro that moves complaints to a non-zero exit leaves this test green (the
   non-zero branch also relays output) while the test's name and the measured table in
   `validate_agent_config`'s docstring go silently stale. Optional strengthening: run the argv
   directly via `subprocess.run` in this test and assert `returncode == 0` and non-empty stderr —
   pinning the measured shape itself — or drop the exit-zero claim from the name.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-08-16 (final verification of round 5)

**Summary judgment.** All three round-5 findings are genuinely resolved, and finding 1 is resolved
one level better than either option I offered: beyond every governed test now failing on its own
(the `_require_kiro()` assert, both Claude tests tightened), the rule is **mechanically enforced** —
`tests/conftest.py::pytest_runtest_makereport` (lines 72–102) converts any skip inside either
harness tier into a failure that preserves the original reason, and
`design/coding-standards.md` (lines 111–116) now describes that mechanism rather than restating an
intention the suite could falsify. That is precisely the structural fix the brief's question (b)
asked me to name if the paragraph were still capable of going stale; it is already in place, with
the mutation record extended to cover it ("a deliberately-skipping test added to a tier fails
through the wrapper"). Everything that remains is stylistic or forward-looking. Ship it.

### Answers to the brief's four questions

- **(a) The rule is now true of every test in both tiers.** Grepped the whole test tree for
  `pytest.skip`/`skipif`: zero occurrences under either marker. All four `integration_kiro` tests
  call `_require_kiro()` (`tests/test_install_harness.py` lines 215, 230, 255, 310), whose failing
  assert names both causes and whose docstring correctly explains why the spec↔design drift guard
  cannot see the second; both `integration_claude` tests restore `_REAL_BINARY_IS_AVAILABLE`
  (captured at `test_install_targets.py` line 63, before the autouse stub) and assert presence —
  the second via direct `shutil.which`, so neither can go green-by-skip. The three `pytest.skip`s
  that do remain (`tests/test_install_assets.py` lines 384, 394, 402) are default-tier, unmarked,
  and gated on *checkout state* (tracked dogfood artefacts present) rather than a binary — correctly
  outside the rule's scope, and the conftest wrapper's narrow `_HARNESS_TIERS` frozenset leaves them
  untouched. The mutation logic traces both ways: `kiro-clo` fails all four through
  `shutil.which(KIRO.harness_binary)`; `clod` fails the first Claude test through the real
  which-based `binary_is_available` and the second through its own `shutil.which` assert.
- **(b) The doc matches the suite, and the paragraph is no longer merely prose.** Verified line by
  line: the tier counts at lines 91–92 ("currently four … and two") match collection (4 = 3 in
  `TestAgainstTheRealBinary` + 1 in `TestTheRealValidatorComplainsAtAll`; 2 in
  `TestAgainstTheRealClaudeBinary`, consistent with the default run's 6 deselected); the history
  paragraph (97–101) now records both near-misses accurately, including that the kiro tier kept the
  shape "one review round longer, while this paragraph already claimed otherwise"; the universal at
  103–109 is true of the suite; and lines 111–116 name the conftest wrapper as the enforcement, with
  the correct diagnosis ("a normative sentence the suite can falsify is the always-loaded-file
  defect one layer up"). The structural question is therefore answered *by the artifact*: a future
  test that skips in either tier fails through the wrapper regardless of what any paragraph says.
  What can still go stale is only the inline counts — finding 1 below, nitpick-grade, and already
  hedged by "currently" plus the tiers-are-the-enumeration delegation.
- **(c) The direct-argv assertion is non-vacuous and does not duplicate the wrapper assertion.**
  The two blocks assert different subjects on one fixture. The direct block pins the *harness's*
  measured shape: `returncode == 0` fails loudly (with a message pointing at the docstring table)
  if a future kiro moves complaints onto a non-zero exit — the exact staleness round 5 named — and
  `stderr.strip()` non-empty fails if the validator stops objecting to unparseable JSON, which
  simultaneously guards `TestTheRealValidatorComplainsAtAll`'s reason to exist. The wrapper block
  then separately pins the *relay* (`complaint is not None`, content check). Neither subsumes the
  other: revert `validate_agent_config` to exit-code logic and only the wrapper block fails; move
  kiro to non-zero-exit signaling and only the direct block fails. The comment at lines 314–317
  states this division correctly. One optional refinement, folded into finding 3.
- **(d) Nothing broken found.** The wrapper fires only on `report.skipped` for the two named
  markers, so the default suite (where both tiers are deselected via `addopts`) and the unmarked
  `test_install_assets.py` skips are unaffected — consistent with the brief's verified runs (1697
  passed default and under a bare `PATH`, 4 + 2 in the tiers). `KIRO_BINARY` still derives from
  `KIRO.harness_binary`; `stub_harness_binaries` is still opt-in with its docstring intact;
  `check.sh`'s comment, CLAUDE.md's tier description, `pyproject.toml`'s `addopts`/markers, and the
  coding-standards table all tell the same story. The rewritten module docstring
  (`test_install_harness.py` lines 1–17) is accurate on all three counts the brief claims: three
  functions, `binary_is_available` named as the either-harness one, and the fakes-encoded-a-shape-
  the-binary-never-produces record.

### Findings

1. **[NITPICK] The one residual staleness vector in the governed paragraph is the inline tier
   counts.** `design/coding-standards.md` lines 91–92: "currently four under `integration_kiro` and
   two under `integration_claude`" sits in the same paragraph that says the count "has already gone
   stale twice" and delegates enumeration to `--collect-only`. The counts are correct today and the
   rule itself is now wrapper-enforced, so nothing can silently regress — but the next test added to
   either tier makes this clause false while everything real stays green. Suggested: drop the
   numbers ("…where a stub would only assert our belief back to us — each saying so in its
   docstring") and let the delegation sentence carry the enumeration entirely.
2. **[NITPICK] The enforcement wrapper itself has no standing test.** `tests/conftest.py` lines
   72–102 were verified by a one-off hand mutation (the deliberately-skipping test the standards doc
   records), which satisfies the watched-failing rule the same way the six-test mutation does — but
   nothing re-runs it, so a future refactor of the hook (e.g. `item.keywords` handling, or a pytest
   upgrade changing wrapper-hook semantics) could disarm the backstop silently. Low stakes: the
   wrapper is defense-in-depth over tests that already fail on their own, so a disarmed wrapper
   alone reopens nothing. Forward-looking: a `pytester`-based test (write a tier-marked
   `pytest.skip` test to a temp conftest'd dir, run in-process, assert it reports failed) would pin
   it if the conftest is ever touched again.
3. **[NITPICK] Two trivial polish items, both optional.** (i) `tests/test_install_harness.py`
   line 14: "The two classes at the end" — `TestAComplaintIsOutputNotAnExitCode` (hermetic) sits
   between the two marked classes, so "at the end" reads loosely; "the two `integration_kiro`
   classes below" would be exact. (ii) In
   `test_it_reports_a_broken_config_on_stderr_while_still_exiting_zero`, the final
   `"invalid" in complaint.lower()` pins a third-party wording; asserting
   `complaint == completed.stderr.strip()` instead would pin relay-exactness — a stronger claim
   about *our* code with no dependency on kiro's phrasing. Brittle-but-loud as-is, in an opt-in
   tier; fine either way.

All three findings are stylistic or forward-looking; none changes what any install writes, refuses,
or reports, and none weakens a guard. The round-5 fixes are real, watched failing in both
directions, and the standards document now describes mechanisms that exist.

VERDICT: APPROVED
