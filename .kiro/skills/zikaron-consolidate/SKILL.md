---
name: zikaron-consolidate
description: Consolidate this project's Zikaron memory journal into long-term records by spawning the zikaron-consolidator subagent. Use when journal entries have accumulated — after a stretch of real work, at the end of a task, or when asked to consolidate, tidy or clean up project memory. Also the recovery path when a previous consolidation run was interrupted.
---

# Consolidate project memory

Zikaron writes new memories into a **journal**. Consolidation turns that journal into **long-term
records**: entries about the same thing are merged into one durable record, entries with no home
become new records, and worthless ones are retired. It is deliberately manual — nothing runs it on a
schedule.

## You do not do this yourself

You have `zikaron_memory_search`, `zikaron_memory_fetch`, `zikaron_memory_remember`,
`zikaron_memory_amend` and `zikaron_memory_retire`.
The merge, promote and discard verbs are not yours and never will be: consolidation runs as a
separate agent with its own tool surface, on a fresh context, so that nothing from this session's
reasoning leaks into judgments that will outlive it.

## How to run it

Spawn the **zikaron-consolidator** subagent with the `subagent` tool:

```
role: zikaron-consolidator
prompt: Consolidate this project's memory journal. Work through every group until
        zikaron_memory_next_group answers {"done": true}, then report what you did.
```

That is the whole invocation. The consolidator's own tooling claims the store's consolidation lock
when it asks for its first group, works through the groups code has planned for it, and exits. You do
not need to tell it how to decide anything; its own instructions cover that.

Then relay its report to the user: groups handled, records merged and created, entries discarded, and
anything it could not finish.

## If a run reports `busy`

`busy` means some worker currently holds this store's consolidation run. **Whether to invoke again is
the user's call, and it is a real decision rather than a formality**, because nothing inside the store
can tell a stopped worker from a slow one — a lease is a timer, and the only evidence that a holder
has stopped is a human saying so.

- If a consolidation is genuinely running right now — someone else's session, or one you started
  moments ago — **let it finish.** Invoking again would displace it and throw away its in-flight
  reasoning.
- If the user says consolidation seems stuck, or the holder's session is gone (a crash, a cancelled
  turn, a killed terminal), **invoke again.** That takes the run over, closes the stranded one, and
  replans from the journal's current state.

Either way nothing is lost: an entry is marked done only when its disposition was actually written, so
a displaced run costs the work in flight and never a journal row. Report the holder's session and pid
to the user and ask, rather than deciding for them.

## What to expect

- On a project whose journal is empty, the consolidator gets `{"done": true}` immediately and reports
  nothing to do. That is a successful run, not a failure.
- A large journal may take several minutes and many tool calls. That is normal.
- If the consolidator reports `busy` with a holder session and pid, see the section above: the
  question is whether that holder is working or stranded, and the user is the one who knows.
