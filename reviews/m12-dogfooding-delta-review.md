## Round 1 — 2026-08-05

**Summary judgment:** The installer’s list asymmetry is implemented correctly for absent, empty, populated, and aliased crew blocks, and the recall/write additions are generally concise rather than contradictory. I would not ship this delta unchanged, however: consolidation can erase the new expiry protection, and the installer silently couples tool trust to a separate subagent-spawn trust grant that its CLI and user-facing rationale do not disclose. The recall guard and tests also need small but material hardening around the exact dogfooding failures this delta is meant to close.

**Findings:**

1. **[BLOCKER] The consolidator can remove the expiry condition that the primary write policy now makes mandatory.** `zikaron/hook/write_policy.py::WRITE_POLICY_PROMPT`, “If a claim expires,” correctly requires the condition in the gist because future agents may see only that field; `zikaron/install/assets.py::CONSOLIDATOR_PROMPT`, “Authoring gists and content,” never repeats that rule even though the consolidator does not receive the write policy and rewrites gists during `merge` and non-byte-identical `promote`. “Never invent” and “preserve the specifics” do not protect the gist/content boundary: a consolidator can preserve “until 2.0” in content while replacing the gist with an unconditional prohibition, recreating the measured failure. Add a consolidator-specific rule requiring any time/version/migration condition to remain in the authored gist (or requiring the entry not be merged into an unconditional record), and add a shared semantic test in `tests/test_install_assets.py` covering expiry as a fourth independently required property.

2. **[BLOCKER] `--no-trust-tools` controls an undisclosed, distinct trust boundary: permission to spawn the consolidator.** `zikaron/install/main.py::_parser` and the README describe the option only as controlling whether `@zikaron` enters `allowedTools`, while `zikaron/install/writer.py::_merged_tools_settings` also uses `trust_tools` to create/extend `toolsSettings.<crew>.trustedAgents`. Thus the default trusts not only five local MCP tools but also a separate model invocation with four consolidation mutation verbs; conversely, opting into per-write prompts unexpectedly turns on a spawn prompt. This also makes `writer.py::_selecting` and the README’s “What it trusts is five tools … every write reversible by retire” rationale incomplete and factually too strong: `retire` withdraws a record from default retrieval but is neither rollback nor erasure, and it cannot restore prose overwritten by an amend. Split these controls (for example, `trust_tools` and `trust_consolidator`, with independently named flags), or explicitly rename/document one broader trust option and justify both grants; in either case replace “reversible” with the precise soft-retirement guarantee.

3. **[IMPROVEMENT] The planning-recall safeguard is correctly placed but too abstract at the point most likely to anchor the agent.** `WRITE_POLICY_PROMPT` ends the recall paragraph with “check that its conditions still hold,” which is visible and non-contradictory, but `zikaron/mcp/primary.py::zikaron_search` repeats the strong “planning and weighing options” trigger without its qualification. A prior-failure gist often does not state all conditions needed to perform that check, so an agent can still use “we tried this” as a veto rather than as a hypothesis to verify. Keep the trigger duplication—it earns its context by appearing at tool choice—but append a short guard to the tool description such as: “Hits are historical evidence, not vetoes; fetch the relevant record and verify current code, versions, and environment before ruling an option out.” Sharpen the policy similarly to say prior failures should choose what to re-check, not by themselves eliminate an approach.

4. **[IMPROVEMENT] A known inheritance-disabled configuration is left with an installed but unreachable skill even though an explicit resource entry would be additive.** `zikaron/install/writer.py::_merged_resources` leaves `resources` absent and only prints a note telling the user to add the skill manually if `chat.disableInheritingDefaultResources` is set. That is a deterministic non-working install for precisely the documented exception; the command already knows the exact `skill://` URI, and adding it does not narrow inherited resources. Always add the explicit skill entry when no covering entry exists (including when `resources` is absent), or reliably inspect the effective inheritance setting and add it when disabled. Add the corresponding inheritance-disabled test rather than treating a warning as delivery of the installed skill.

5. **[IMPROVEMENT] Several new tests can pass while the property in their name is broken.** In `tests/test_install_assets.py::TestTheThreeSharedProhibitions`, the observations-not-orders test asserts only that `--force` occurs and the gist-purpose test only that `PGHOST` occurs; either example token can survive after its governing instruction is deleted or inverted. Assert the operative clauses or parse the relevant prompt sections, and add direct checks for the new expiry, one-write-at-a-time, split-cue, length, and recall requirements. In `tests/test_install_writer.py`, the alias test proves only `availableAgents` is updated, not that an alias with no `availableAgents` receives `trustedAgents`; add that exact fixture. Finally, the new malformed `allowedTools`/`toolsSettings`/crew-list/`resources` refusal tests invoke the plan-and-commit helper and prove only that the agent file and backup are unchanged, while `tests/test_install_main.py::TestNothingIsWrittenWhenTheMergeIsRefused` does not include any of those new guards. Add them to the whole-project snapshot parametrization so a future ordering regression cannot write the shipped files while all newly named refusal tests remain green.

6. **[NITPICK] The split heuristic narrows “symptom or situation” back to “symptom” and can misclassify valid non-failure findings.** `CONSOLIDATOR_PROMPT` first correctly asks for an observable “symptom or situation,” then says “If you cannot lead with one observable symptom, the entries are probably not one finding.” A build procedure, environment constraint, or settled convention may have one sharp situation but no symptom. Change the latter phrase to “one observable symptom or situation”; this preserves the deliberate split-over-table-of-contents policy without biasing it toward failure records only.

VERDICT: NEEDS_CHANGES

---

## Author response to round 1 — 2026-08-05

All six accepted. One is fixed with a simpler remedy than proposed, and the reasoning is below.

**1 — accepted, and it is the most consequential finding here.** The consolidator rewrites gists on
every merge and every non-byte-identical promote, never sees the write policy, and had no expiry rule —
so a consolidation could strip a condition the policy had required, recreating the exact failure this
whole thread started from. Concretely reachable today: `~/Memory` has a long-term record whose gist was
*amended by hand yesterday* to add "was under claude-opus-4.8, not the current gpt-5.6-sol", and a
future merge could have dropped it. The prompt now requires any time, version or migration condition to
survive into the authored gist, and says that an entry whose condition will not fit should be promoted
alone rather than folded into a record that cannot carry it. Expiry is now the fourth property asserted
of both texts in `tests/test_install_assets.py`.

**2 — accepted, with a simpler fix than splitting the flag.** The finding is exactly right that
`trust_tools` silently governed two different grants, and that the README's "every write reversible"
overstated it. Rather than add a second flag, the installer now **never** grants `trustedAgents`: a
consolidation is manual and rare, so one approval prompt per run costs almost nothing, while the grant
itself is a subagent with its own model invocation and four mutation verbs. That removes the conflation
instead of documenting it, keeps `--no-trust-tools` meaning precisely what its name says, and adds no
surface. The install now reports that starting a consolidation will ask once, and says how to opt in.
"Reversible" is replaced with the precise guarantee — `retire` withdraws a row from ordinary retrieval
and leaves it auditable; an `amend` overwrites prose that nothing restores — in the README, the design
and the code.

**3 — accepted.** The trigger was duplicated into the tool description and the guard was not, which is
the worse half to leave behind, since the description is what is read at the moment of anchoring. It now
carries "a hit is historical evidence rather than a veto: it tells you what to re-check, so fetch the
record and confirm the conditions still hold before ruling an option out." The policy's own sentence is
sharpened the same way: a recorded failure chooses what to re-check, not which option to drop.

**4 — accepted.** The note-only path was a deterministically broken install for the one documented
configuration it was written for, and a warning is not a delivered skill. The explicit `skill://` entry
is now added whenever nothing already covers it, including when `resources` is absent — which is safe
because declaring resources does not disable inheritance, so the entry is purely additive. Cost is one
redundant declaration in the common case.

**5 — accepted, all of it, and one of the weak assertions broke while I was fixing the others**, which
is the finding demonstrating itself: the subagent-note test asserted on the bare word "subagent", and
the new crew note mentions a subagent spawn, so it started failing for a reason unrelated to what it
checks. Every prose assertion now names the operative clause rather than a worked example's token, and
all of them run through a whitespace-normalizing helper — the texts are hard-wrapped, so a clause
spanning a line break was invisible to a substring test, and rewrapping a paragraph while editing it
would silently disarm the guard defending it. That is not hypothetical: `probably not one finding`
failed on exactly that when first written. Added: direct checks for expiry, one-write-at-a-time, the
split cue, gist length and recall; a fixture for the alias with no `availableAgents`; and all seven new
refusal shapes in the `main()`-level whole-project snapshot parametrization.

**6 — accepted.** "Symptom" narrowed what the sentence above it had correctly called "symptom or
situation", and would have biased the store toward failure records over build procedures and settled
conventions. Fixed, with a test.

Gate after the fixes: 1475 passed, 98% coverage.


## Round 2 — 2026-08-05

**Summary judgment:** All ship-impacting Round 1 findings are resolved. The consolidator now preserves expiry conditions at the gist boundary, recall presents prior failures as evidence to re-check rather than vetoes, and the installer delivers the skill without silently granting subagent trust. I found no remaining path in this delta that would harm an installed user or newly turn a stale or fabricated memory into an unconditional model instruction.

**Findings:**

1. **[NITPICK] One internal docstring retains the superseded “reversible” claim.** `zikaron/install/writer.py::_selecting`, in the paragraph beginning “What is being trusted,” still says “every write reversible by `retire`,” although the implementation and user-facing documentation now correctly distinguish soft retirement from an amend that overwrites prose nothing restores. This does not affect runtime behavior or installed users, but replace it with the same precise soft-retirement guarantee used in `README.md` so the code does not preserve the rationale Round 1 rejected.

VERDICT: APPROVED
---

## Author response to round 2 — 2026-08-05

**Accepted, and the nitpick was real: the stale claim was still there and I had believed I removed it.**
Two `str.replace` calls in this session reported success and changed nothing, and the cause turned out to
be my own tooling — the line-reflow helper I use to hold the 100-column limit had rewrapped the paragraph
between reading it and editing it, leaving `reviewed` alone on its own line, so an anchor copied from an
earlier read no longer matched. The fix replaces the paragraph by line range and asserts the old wording
is gone afterwards. The general practice this leaves: an unconditional `replace` on wrapped prose is a
silent no-op waiting to happen, so assert the substitution took, and prefer line ranges over text anchors
in any file the formatter may have touched since it was read.

Gate: 1475 passed, 98% coverage. No further findings outstanding.
