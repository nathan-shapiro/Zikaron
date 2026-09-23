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
2. **Delegate the review.** Use the `subagent` tool with `role: memory-reviewer` and a brief containing:
   - the **file path(s)** to review,
   - a **review file path** under `reviews/` (e.g., `reviews/<slug>-review.md`) — use the same path for all rounds; the reviewer appends each round under a new header and reads prior rounds before writing,
   - the **intent / goals** the artifact must satisfy,
   - any **rubric or constraints**, and explicitly note anything that is **intentional** so it is not re-flagged.
   The reviewer appends its findings to that file and returns only the path + verdict in its summary.
3. **Read the review file.** After the subagent returns, read the review file at the path it reported to get the full findings. Do not rely solely on the summary.
4. **Apply feedback with judgment.** On `NEEDS_CHANGES`, address each finding: accept and apply the good ones, and reject any you disagree with — but record *why*. Edit the artifact file. If the artifact is an agent config, re-run `kiro-cli agent validate` after editing.
5. **Iterate to convergence, and let convergence decide when that is.** Re-spawn the reviewer with the same review file path. It will read prior rounds automatically and avoid re-raising resolved issues. Stop on `VERDICT: APPROVED` with no material improvements left. **Five rounds is a soft cap, not a limit**: reaching it means report what is still open — disagreements, and the findings each round keeps producing — to the operator and ask how to proceed, not close the loop yourself. A small change that will not converge is evidence about the change or about the author, and both are worth surfacing.

   **Never put round pressure in a brief.** No round numbers, no "final round", no "the protocol allows N", no note of how close you think this is to done — **and no mirror of it**: not "there is no schedule", not "raise everything, however small". Either tells the reviewer which verdict is wanted; its own definition already sets the bar for what it raises, including "do not invent churn". A reviewer told that closure is expected is being asked for an approval rather than a judgement, and one told that findings are expected is being asked for findings — neither is worth anything. If you catch yourself having done either, discount that verdict and re-run with clean framing. Tell the reviewer what the artifact is, what changed since it last looked, and what you have already verified yourself. Nothing about your schedule, in either direction.
6. **Record the outcome.** Record any consequential *decision* in FINDINGS.md with a pointer to where its rationale lives; the verdict and the round count stay in `reviews/`, per `CLAUDE.md` §"Project memory". Keep the `reviews/<slug>-review.md` file — it is the audit trail for the artifact's review history. Add a one-line reference to it in `FINDINGS-archive.md`'s References section so it can be found later.

## Notes
- Subagents cannot spawn their own subagents, so the reviewer cannot delegate — it reviews only. That is fine.
- The reviewer writes only to `reviews/`; all edits to the artifact itself stay with you so changes remain coherent and validated.

## Reviewer brief template
```
Review the artifact at <path>. Append your findings to <reviews/slug-review.md> (same file each round).
Intent: <what it must achieve>.
Rubric: <correctness / alignment / cost realism / freshness / safety / completeness / measurability / risks / clarity>.
Intentional (do not re-flag): <list>.
Read the actual artifact file and any prior rounds in the review file. Return tagged findings ([BLOCKER]/[IMPROVEMENT]/[NITPICK]) with concrete edits, and end with exactly one line: VERDICT: APPROVED or VERDICT: NEEDS_CHANGES.
```
