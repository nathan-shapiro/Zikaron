---
name: self-review
description: Pressure-test a high-stakes artifact (design doc, plan, spec, schema, research note, or agent config) by delegating an independent critique to the memory-reviewer subagent and iterating on its feedback to convergence. Use before finalizing consequential work, not for routine single steps.
---

# Self-review loop

Delegate a tough, independent review of your own work to the **memory-reviewer** subagent, then iterate until it converges on approval. You stay the author and editor; only the critique is delegated.

## When to use
- Finalizing a significant **design document**, **architecture proposal**, **data schema**, **research plan**, **spec**, or **agent/config** change.
- Any artifact where being wrong is expensive or hard to walk back — in Zikaron, that especially includes storage schemas and context-assembly designs, since both are costly to migrate once sessions depend on them.

Skip it for routine, low-stakes steps — each loop spends extra model cycles.

## Protocol
1. **Externalize the artifact.** The reviewer is a subagent and cannot see your in-context reasoning, so write the artifact to a file first (e.g., `design/<topic>.md`, a research note, or the config under review). Reviews are always file-based.
2. **Run the re-read loop to a clean pass before you delegate**, and state each pass's defect count, so "it is clean" is a claim rather than a feeling. Do not spawn the reviewer until a pass finds nothing. A pass is not one reading: it covers the text around what you changed, what the change falsified elsewhere, and every fact you asserted.

   **Read around the change, not the change.** For every file touched since your last pass: the whole file if you wrote it from scratch or edited it more than twice, otherwise the changed passage **plus the paragraph before and after it, and the section heading it sits under**. The edit is coherent with itself by construction — you just made it — so the incoherence is never *in* it. It is in what now sits either side: a sentence the topic has moved past, a transition to a point you removed, a paragraph now saying twice what one sentence says, wrapping ravelled by a phrase swap, a `Raises:` block pushed into the middle of a docstring, a docstring contradicting the code below it. **Read it as words on disk, not as the intent you are still holding** — that is why this resists being done properly, and why skimming feels identical to checking.

   **Then find what the change falsified in files you did not touch.** Grep the *claim* you changed across the whole corpus, in all of its phrasings rather than the one you happened to replace. Then go further, because a string search only finds sentences that resemble yours while the ones that go stale are those that **followed from** it and share none of its words: write the change as a before/after pair of propositions, write down what the old proposition licensed a reader to conclude, and decide for each conclusion whether it still holds. Read those passages by meaning, not by match. This is where the expensive defects are — the ones that otherwise surface as a reviewer's blocker ten rounds in.

   **Then re-check every number, name, path and source you wrote**, against the thing that determines it: a count against the constant, a path by opening it, a figure by re-deriving it, a cited document by reading it. One asserted from memory reads exactly like one that was checked.

   **One pass is evidence about that pass, not about the artifact.** A single change typically needs several passes to reach zero. Every edit is a chance to create the next defect and a repair is still an edit, so a fix made during a pass is an input to the next one, never a closed item.

   It is a step here because re-reading is never itself one of the findings being applied, so it is never on the list being executed — which leaves this protocol as the only place the trigger reliably fires.
3. **Delegate the review.** Use the `subagent` tool with `role: memory-reviewer` and a brief containing:
   - the **file path(s)** to review,
   - a **review file path** under `reviews/` (e.g., `reviews/<slug>-review.md`) — use the same path for all rounds; the reviewer appends each round under a new header and reads prior rounds before writing,
   - the **intent / goals** the artifact must satisfy,
   - any **rubric or constraints**, and explicitly note anything that is **intentional** so it is not re-flagged.
   The reviewer appends its findings to that file and returns only the path + verdict in its summary.
4. **Read the review file.** After the subagent returns, read the review file at the path it reported to get the full findings. Do not rely solely on the summary.
5. **Apply feedback with judgment.** On `NEEDS_CHANGES`, address each finding: accept and apply the good ones, and reject any you disagree with — but record *why*. Edit the artifact file. If the artifact is an agent config, re-run `kiro-cli agent validate` after editing.
6. **Iterate to convergence, and let convergence decide when that is.** Run the re-read loop again before each re-spawn — the findings you just applied are edits like any other, and the round that introduced a defect while fixing an earlier one is the expensive kind. **After applying a round's findings, the re-read is still the whole file for anything edited more than twice — and it almost always is by then.** Checking the passages you just changed, or grepping for the phrases you replaced, is not a pass: the defects a round's edits create sit in the sections that *followed from* what changed, which neither check reaches. Re-spawn the reviewer with the same review file path. It will read prior rounds automatically and avoid re-raising resolved issues. Stop on `VERDICT: APPROVED` with no material improvements left. **Five rounds is a soft cap, not a limit**: reaching it means report what is still open — disagreements, and the findings each round keeps producing — to the operator and ask how to proceed, not close the loop yourself. **Never offer to proceed past an open blocker as one of the options**: continuing the loop is the default, and the question is only whether the operator wants something other than that. A small change that will not converge is evidence about the change or about the author, and both are worth surfacing.

   **Never put round pressure in a brief.** No round numbers, no "final round", no "the protocol allows N", no note of how close you think this is to done — **and no mirror of it**: not "there is no schedule", not "raise everything, however small". Either tells the reviewer which verdict is wanted; its own definition already sets the bar for what it raises, including "do not invent churn". A reviewer told that closure is expected is being asked for an approval rather than a judgement, and one told that findings are expected is being asked for findings — neither is worth anything. If you catch yourself having done either, discount that verdict and re-run with clean framing. Tell the reviewer what the artifact is, what changed since it last looked, and what you have already verified yourself. Nothing about your schedule, in either direction.

   **The brief carries facts, not framing.** Fill the template below and nothing else. Do not write guidance of your own about what to look for, how hard to look, which kind of finding is wanted, or what the operator wants. When the operator has given direction for the review, put it in the template's `On the operator's authority:` line in their exact words, with nothing added around it. A paraphrase is your framing with the operator's name on it, and it is the defect this rule exists to stop.
7. **Record the outcome.** Record any consequential *decision* in FINDINGS.md with a pointer to where its rationale lives; the verdict and the round count stay in `reviews/`, per `CLAUDE.md` §"Project memory". Keep the `reviews/<slug>-review.md` file — it is the audit trail for the artifact's review history. Add a one-line reference to it in `FINDINGS-archive.md`'s References section so it can be found later.

## Notes
- Subagents cannot spawn their own subagents, so the reviewer cannot delegate — it reviews only. That is fine.
- The reviewer writes only to `reviews/`; all edits to the artifact itself stay with you so changes remain coherent and validated.

## Reviewer brief template
```
Review the artifact at <path>. Append your findings to <reviews/slug-review.md> (same file each round).
Intent: <what it must achieve>.
Rubric: <correctness / alignment / cost realism / freshness / safety / completeness / measurability / risks / clarity>.
Intentional (do not re-flag): <list>.
Changed since the last round: <facts, or "first round">.
Verified myself: <facts>.
On the operator's authority: <the operator's words, verbatim — omit this line when there are none>.
Read the actual artifact file and any prior rounds in the review file. Return tagged findings ([BLOCKER]/[IMPROVEMENT]/[NITPICK]) with concrete edits, and end with exactly one line: VERDICT: APPROVED or VERDICT: NEEDS_CHANGES.
```
