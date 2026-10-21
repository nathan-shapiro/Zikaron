# M40-3 — One model for every agent, and a flag for each — build review

Artifact: the M40-3 build in the working tree against `7abf443` — `zikaron/install/models.py`
(new), `main.py`, `targets.py`, `writer.py`, `code_knowledge.py`, `tests/test_install_models.py`
(new), `tests/install_snapshots.py`, `test_install_writer.py`, `test_install_targets.py`,
`test_install_components.py`, `design/harness.md`, `design/guards.md`, `design/code-knowledge.md`,
`design/kiro-gaps.md`, `README.md`. Brief: `design/build-plan.md` §"M40-3 — One model for every
agent, and a flag for each" (lines 6881–6996 at round 1).

## Round 1 — 2026-10-20

**Summary judgment.** The build does what the brief says on every item, invariant and done-when I
could check by reading. `models.py` owns the four options, the resolution, both refusals and the
check, and `main.py` keeps flow only (item 4); precedence is own flag → `--model` → default with
`is None` at both rungs (item 1); both refusals sit ahead of the `--print-only` branch and of every
write (item 2); the check deduplicates and includes the orchestrator's exactly where
`ships_orchestrator` holds (item 3); and `ships_orchestrator` is a shape on the target beside
`accepts_agent_flag`, with every value still read from `HarnessSpec` or the orchestrator's own
definition, so `design/harness.md` §"The installer's two targets" is respected. I traced each of the
brief's mutations against the test named for it and each would redden it for the reason the brief
gives; the done-when 2 sweep (below) finds no passage in `design/`, `README.md`, `zikaron/` or
`tests/` that still attributes an agent's model to `--model` alone or the guards refusal to
`--model` alone. Nothing here is a blocker or would change what ships; three optional nitpicks.

### Findings

1. **[NITPICK] `zikaron/install/writer.py:119–123` — the `Plan` docstring justifies one
   target-specific field on the shared value and is now silent about its twin.** The paragraph
   explains why `hook_format`, kiro's, stays on `Plan` rather than in a per-harness bag.
   `orchestrator_model` is the same case from the other side — `KiroTarget.shipped_files` never
   reads it and `refuse_unknown_models` skips it where `ships_orchestrator` is false — and a reader
   meeting a field one target has no use for gets the reasoning for the other field only. The
   brief retired the `#:` comment over `documenter_model` because its "kiro ignores the
   orchestrator's model" would read against the new refusal; this sentence can avoid that word.
   Suggested replacement for the paragraph's first sentence: *"`hook_format` is kiro's and
   `orchestrator_model` is Claude Code's; each target reads only its own, and both stay on the
   shared value rather than being pushed into a per-harness bag because the alternative — a
   per-harness options type — would make `main.py` build its arguments differently depending on a
   flag it has not resolved yet."* Optional.

2. **[NITPICK] `tests/test_install_code_knowledge.py:399` —
   `test_without_model_each_agent_takes_its_own_default` names the old single flag.** "Without
   model" meant "without `--model`" when that was the only flag; the property the body asserts is
   now "with no model flag at all", and the body is right. Suggested:
   `test_without_any_model_flag_each_agent_takes_its_own_default`. Optional.

3. **[NITPICK, outside the artifact] `tests/conftest.py:211` — `stub_harness_binaries`'s docstring
   says `install.main` "validates the consolidator's model on the way past".** Since this build it
   is `install.models.refuse_unknown_models` validating every shipped agent's model. Not in the
   changed files and not inside done-when 2's predicate (it says what *validates*, not what
   *sets*), so noted rather than asked for; if the file is touched: *"validates each shipped
   agent's model on the way past"*.

### Checked and found sound, so not raised

- **Each invariant's test against its mutation**, by reading the test and the code it drives:
  `test_under_claude_code[agent]` and `test_under_kiro[agent]` assert the whole model map with one
  agent replaced, so a flag landing in another agent's file or a flag ignored both fail the
  equality; `test_an_agents_own_flag_wins_over_model` asserts `every` everywhere but one;
  `test_an_empty_value_is_refused_rather_than_replaced` reaches the shape check only because
  `_chosen` tests `is None` at the first rung, and `test_no_malformed_model_reaches_the_artefact[""]`
  in `test_install_targets.py` already covers the second rung; the guards refusal is parametrized
  over all four flags × both modes and asserts the flag's own text and an empty tree, so a refusal
  reading `--model` alone passes three of four flags through to exit 0, and one moved past the first
  `commit_merge` leaves `settings.local.json` behind; the kiro refusal's empty-tree assertion fails
  the moment `write_shipped_files` runs first; `test_ships_orchestrator_agrees…` binds the property
  to `shipped_files` for a `memory` plan in both directions; the model-check tests count through a
  recorder on both classes, and each of the three mutations changes the count on the input the
  brief names (`--model every` → three records; Claude Code defaults → two; kiro defaults → two).
- **Refusal order.** `_refuse_unoffered_guards` takes kiro + `guards`/`both` before
  `refuse_unusable_model_flags`, so no command line meets two of the new refusals at once; under
  Claude Code the guards refusal precedes the shape check, so an invalid id with `guards` is
  reported as the flag being unusable rather than malformed, which is the right message.
- **The fixture interplay.** `_offer` overrides the same module attribute `stub_harness_binaries`
  sets, and `targets.py` reads it through the module at call time, so the later patch wins; the
  recorder is set on both concrete classes, which `TARGETS`'s instances resolve through.
- **Done-when 2, by meaning.** Passages that say what sets an agent's model: `harness.md` 337–343
  and 667–676, `code-knowledge.md` 444–447 and 671–676, `README.md` 547–559, `models.py`'s help
  strings and `code_knowledge.py:36` — each names the agent's own flag beside `--model` or says
  "no model flag". Passages that say which flags `guards` refuses: `guards.md` 601–604,
  `harness.md` 665–666, `README.md` 553 — each says every model flag. Passages found and judged
  not to make either claim: `harness.md` table rows 72–73 and line 91, `architecture.md` 2471–2527
  (the contract table and its harness delta name no flag), `overview.md` D34, `spec.py`'s field
  comments, `entries.py:377–378`, `test_install_main.py:253`, `test_install_components.py:338`,
  the two live tests that pass `--model` as an argument. `CLAUDE.md`, `.claude/`, `.kiro/` and
  `tests/fixtures/installed/` carry no model-flag text. `harness.md` §"The flags, and what each
  refuses" states the `--orchestrator-model` refusal, read from `ships_orchestrator`, as the brief
  requires.
- **Item 5's documents.** `kiro-gaps.md` row 23 carries `--orchestrator-model` in both columns and
  row 25 names `--documenter-model` before the default moves; `code-knowledge.md` §5.4's
  enumeration paragraph names `models.py`; `README.md`'s table has a row per flag and the
  two-installs sentence.
- **Scope fence.** No default moves (`spec.py` untouched, `ORCHESTRATOR_MODEL` unchanged, snapshots
  unmoved); no effort flag; no kiro orchestrator; no id translation; Claude Code's check stays the
  shape test.
- **The in-tree build.** `models.py` is imported by `main.py` alone; nothing outside
  `zikaron/install/` imports it; `doctor` still imports only `targets.claude_mcp_config`.
- **Coding standards.** `models.py` is one concept at 123 lines; full annotations; the one comment
  states a reason (`is None` over truthiness) rather than a repair; docstrings state contracts and
  `Raises:`; the new test module is named for its module and its docstring names the normative
  section; no provenance in `zikaron/` or `tests/`; `main.py` lands at 407 lines, down from where
  the brief found it.

VERDICT: APPROVED
