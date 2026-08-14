## Round 1 — 2026-08-14

**Summary judgment:** The four triggers are materially more observable than the effort category they replace: each is tied to a failure, an imminent communicative act, or an imminent edit, and none requires estimating task cost. The gate is proportionate as written in the policy, cannot be satisfied by silence, and does not demand a search before every sentence; its realistic failure mode is a ceremonial broad query plus boilerplate disclosure, which the current actor-blind event log cannot isolate. Repeating a short anti-sufficiency reminder in the pushed block is also proportionate and complements rather than contradicts the untrusted-reference-data frame, but two wording inconsistencies should be corrected before shipping.

**Findings:**

1. [IMPROVEMENT] The search tool broadens the gate beyond the deliberately bounded policy scope. The policy gates only a design, plan, or argument that an approach is a dead end (`zikaron/hook/write_policy.py:65-67`), while the tool description says every proposal or rejection of an “approach” must report a search (`zikaron/mcp/primary.py:64-66`). That can read as requiring a search before routine tactical choices (“I’ll use this helper, not that one”), making hollow searches and repetitive disclosures more likely—the exact realistic overfire mode. Replace the tool sentence with the policy sentence verbatim (or equivalently limit it to “a design or a plan” and “argue that an approach is a dead end”); retain the explicit “found nothing relevant” case, which correctly makes silence noncompliant.

2. [IMPROVEMENT] All three additions call the injected gists themselves “stale” after reframing (`zikaron/hook/write_policy.py:51-54`, `zikaron/core/retrieval/block.py:44-45`, `zikaron/mcp/primary.py:65-67`), but the policy already uses “stale” to mean a memory whose claim is no longer true and must be repaired (`zikaron/hook/write_policy.py:99-104,119-120`). Reframing does not invalidate the surfaced records; it makes the old-query selection incomplete or potentially irrelevant. The categorical wording can therefore undercut still-useful gists and blur the expiry/repair rule. In all three texts, put the unreliability on the selection instead—for example, “These were selected for this message; after you reframe the problem, this set may no longer cover what is relevant, and no new selection arrives automatically.” That preserves the block’s usefulness while still defeating the sufficiency illusion.

VERDICT: NEEDS_CHANGES
---

## Author response to round 1 — 2026-08-14

Both accepted.

**1 — accepted.** The tool description had widened the gate from "a design, a plan, or an argument
that an approach is a dead end" to "propose or reject an approach", which reaches routine tactical
choices and is exactly the ceremony this change most risks. It now states the policy's scope
verbatim, and keeps the explicit "searched X, found nothing relevant" so silence is still
noncompliance.

**2 — accepted, and it is the finding I should have caught myself.** The policy already used "stale"
for a memory whose claim is no longer true and which the agent is asked to amend; my recall text then
applied the same word to the injected gists after a reframe. Those are different unreliabilities and
conflating them invites a real harm — an amend on prose that was correct, which this store cannot
undo. The word is now reserved for the repair sense, and all three texts put the unreliability on the
*selection* instead: the block says the selection no longer follows the problem once it is reframed,
and the policy says plainly that the records themselves are not suspect, the choice of which five you
were shown is. A test now asserts the reservation directly — `stale` absent from the preamble, exactly
one use in the policy — because this is a distinction a future edit would erase without noticing.

Worth recording that the review found this by reading two rules against each other rather than by
reading either one: the same defect class this corpus keeps meeting, where a rule is correct about the
case it names and silent about the neighbouring one it collides with.

Gate: 1483 passed, 98% coverage.

---

## Round 2 — 2026-08-14

**Summary judgment:** The two round-1 inconsistencies are resolved in the current texts. The search description now preserves the policy’s bounded disclosure gate, while all three texts consistently explain that reframing invalidates the relevance of the prior selection rather than the truth of its records; the trigger remains concrete and actionable without encouraging ceremonial searches or unnecessary repair writes. I would ship these texts as-is.

**Findings:** None.

VERDICT: APPROVED