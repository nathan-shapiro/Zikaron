# Review — design/build-plan.md §M17 (cold start loses the race; the encoder is why)

## Round 1 — 2026-08-19

### Recommendation: build (d), amended — ranking (d) > (c) > (b) > (a)

**Build (d)**, with two amendments the brief must make before it is implementable (findings 2 and 3):
it must say how `IndexingContext.__post_init__` is satisfied without blocking, and it must make the
post-load validation failure end the process rather than leave it resident. As written, (d) walks
straight back into the reverted trap the brief exists to prevent.

**Why (d) over the others.** The decisive fact — which the brief omits, and which reshapes every
option's trade (finding 1) — is that **option (b) already exists in the codebase**: `Store.open`
compares the config's `embed_model` *and* `embed_dim` against `meta` on every open, encoder-free,
before `IndexingContext` is ever constructed (`zikaron/core/store/store.py:472–475`, invariant 11,
named in `open`'s own docstring). So the operator-error case — someone editing `embed_model` against
an existing store — fails at startup, before bind, under **every** option, unchanged. The only thing
actually at stake in the (a)–(d) choice is the fate of the **artifact-vs-store** check: the one that
catches an encoder *object* whose measured facts disagree with the store. (d) is the only option
that keeps that check at full strength (artifact-derived `dim`, same `BAD_CONFIG` payload, no window
in which a mismatched encoder can write) while taking it off the critical path. Its extra machinery
over (c) is small — (c) needs the same wrapper and the same latch anyway, since a per-first-use check
must remember its verdict — and what (d) buys for it is validation at the earliest possible moment
plus a proactive surfacing channel. (b) is a deletion wearing an addition's clothes (finding 1), and
it reopens the exact silent channel `__post_init__`'s docstring names: a wrong-model, same-width
encoder writing vectors labelled with a model that did not produce them — the width check at
`vectors.py:65` passes, nothing downstream is loud, and that is precisely the D20 corruption the
rubric asks about. (a) does not reliably fix the defect at all (finding 4): its critical path is
~360 + ~640 + ~245 ≈ 1.25 s, at or over the 1.2 s deadline, and its "keeps the guard exactly as
strong" claim is wrong — `list_supported_models()` reports the registry's *claimed* dim, a
transcribed constant one shelf over from the model→dim table the brief itself rejects on D20 grounds.

**What would change my mind.** (i) If implementing (d)'s identity handoff turns out to require
changing the `Encoder` protocol itself or materially churning `FakeEncoder` across the hermetic tier,
drop to (c) — same wrapper, same latch, validation at first blocking access instead of at
load-completion. (ii) If even (c) is judged too much machinery, (b)-as-deletion is *acceptable*, but
only with the guard-weakening recorded in the guard's own comment (as the brief already requires)
and the equal-width silent channel named as an accepted risk in so many words. (iii) If the deciding
A/B on an idle machine shows the end-to-end margin under 2.0 s is thin (say < 300 ms), pull the
shelved split-deadline lever alongside — the brief already positions it as exactly that fallback.
No fifth option is needed: the strongest "fifth" candidate — answer `dim` from a previously measured
cache — is already what (d)-amended does, because `store.meta.embed_dim` *is* an artifact-derived
measurement cached at create time, not a transcribed constant.

### Summary judgment

The diagnosis is correct, verified against the code at every point I checked, and the negative
result is recorded well enough that no fresh session will repeat it. But the option analysis rests
on an omitted fact — `Store.open` already performs (b)'s comparison on every open — which distorts
the stated trades of (b), (c), and (d); and the leading candidate (d), as written, still blocks
assembly on the load through `__post_init__`, the exact reverted failure. Both must be fixed before
a fresh session can implement this brief without re-deriving what this review just re-derived.

### Findings

1. **[BLOCKER] The brief never says that `Store.open` already performs option (b)'s check, and the
   omission distorts three of the four options.** `zikaron/core/store/store.py:472–475` compares
   `config.get_str("embed_model")` and `config.get_int("embed_dim")` against `meta` on every open,
   with no encoder in hand, raising `BAD_CONFIG` (`source='meta'`, key `embed_model/embed_dim`) —
   invariant 11, stated in `open`'s docstring. Consequences the brief must carry:
   - **(b)** is not something to build; it is a *deletion* of the `IndexingContext` check, relying
     on a comparison that already ships. Its stated benefit — "catches the error that actually
     happens — someone changing `embed_model` against an existing store" — is already true today,
     under every option, at startup, before bind. A fresh session implementing (b) as written would
     author a duplicate of store.py:472–475.
   - **(b)'s trade sentence has both halves mischaracterized.** "Weaker on dim specifically, and no
     weaker at all on the name" is backwards. The **dim** half stays *loud* under (b): a wrong-width
     vector is refused at first embed by `_normalize` (`vectors.py:65`, `INDEX_FAILED`) and a
     wrong-width query fails against `vec0` — later and worse-labelled than `BAD_CONFIG` at
     startup, but never silent. The **name** half at *equal width* is where silence lives: a
     programming error routing a different-model, same-dim encoder into `IndexingContext` writes
     vectors labelled with `identity.embed_model` that a different model produced, and nothing
     anywhere downstream fires — the precise `vec0` mislabelling `__post_init__`'s own docstring
     names and D20 exists to prevent. And "per fact 1, no weaker at all on the name" contradicts
     the same paragraph's own programming-error sentence: fact 1 holds only while `assemble` passes
     the config string to `load`, i.e. exactly when no programming error has happened.
   - **(c)'s trade is much smaller than stated.** "A mismatched store now answers `health()`
     successfully and fails on its first real call instead of failing at startup" is wrong for the
     common case: the config-vs-store mismatch still fails inside `Store.open`, encoder-free,
     before bind, under (c) and (d) alike. The only class that moves to first-use is the narrow
     artifact-disagreement class (a registry serving different weights under an unchanged name, or
     call-site drift). Restate the trade at its real size.
   Suggested edit: add one paragraph before the option list — "`Store.open` already compares the
   config's `embed_model`/`embed_dim` against `meta` on every open (store.py, invariant 11),
   encoder-free and before the socket exists, so the operator-error case fails at startup under
   every option below. What the options decide is solely the fate of the *artifact-vs-store* check
   in `IndexingContext.__post_init__`" — then correct (b) and (c) as above.

2. **[BLOCKER] Option (d) as written re-enters the reverted trap.** It keeps "every accessor
   blocking on a `threading.Event`" while `IndexingContext.__post_init__` (writes.py:83–97) still
   reads `encoder.model_name` and `encoder.dim` during assembly — so assembly blocks on the load
   again, which is the measured 1224-vs-1216 ms failure the brief's own trap section warns about.
   The brief must state how `__post_init__` is satisfied without blocking. Concrete shape: the
   wrapper is constructed with the *expected* identity — `model_name` from config, which per fact 1
   is byte-identical to what the loaded artifact will report, and `dim` from `store.meta.embed_dim`,
   which is itself an artifact-derived measurement cached at create time, not a transcribed
   constant — and answers those two properties immediately; the loader thread performs the
   authoritative artifact-vs-identity comparison the moment `load` returns and latches either the
   encoder or the `ZikaronError`, which the five genuinely blocking members (`embed`,
   `count_tokens`, `token_char_spans`, `n_special_tokens`, `max_sequence_tokens`) raise. State
   plainly that this makes `__post_init__` vacuous *for the wrapper, by construction*, and that its
   strength is preserved by the pair: `Store.open`'s invariant-11 (config-vs-meta, eager, already
   shipped) plus the loader's artifact-vs-meta (deferred, latched); the check stays fully eager on
   the create path and for every direct construction (`FakeEncoder`, tests). Note the ordering
   consequence: the wrapper needs `store.meta` (or a set-once identity handoff), so on the open
   path either the load thread starts after `Store.open` (~140 ms of lost overlap) or it starts at
   assemble's top and waits on an identity-set event that is satisfied ~140 ms in — say which, or
   say the choice is the implementer's with the ~140 ms trade named.

3. **[IMPROVEMENT] Under (c)/(d), specify what the service *does* after a latched validation
   failure — and under (d), make the self-stop mandatory, not "one line if you want".** The config
   is read once at startup; `health()` never touches the encoder, so a mismatched-but-latched
   service answers `ready=true` indefinitely while rejecting every real call — and start-if-absent
   never replaces a live socket, so an operator's config fix does not take effect until idle-stop
   fires, up to 30 minutes later. Worse: each rejected message refreshes `ActivityTracker`, so a
   user retrying keeps the broken service alive indefinitely. A mandatory self-stop on latched
   failure (drain in-flight requests through the existing shutdown path, `log_self_stop` with a new
   `reason`, unlink, exit) restores today's recovery loop exactly: the next message spawns a fresh
   process that reads the corrected config. Also worth one sentence in the brief because it is a
   genuine improvement over today: the in-flight caller's hook receives `-32023` and relays
   "bad_config (-32023)" to the model (`push.py` `_REJECTION_KINDS`), where today's
   startup-failure path gives the client only a poll-deadline "transport". And extend the first
   invariant to name where the refusal now *surfaces* — which RPC, which wire code — so the
   mismatch test asserts client-observable behavior rather than an internal latch.

4. **[IMPROVEMENT] Finish (a)'s arithmetic, because finished it removes (a) from the candidate
   list.** Critical path under (a): ~360 ms service imports + ~640 ms fastembed import (required by
   `list_supported_models()`, and running the background load concurrently does not help — both
   threads serialize on the same module import lock) + ~245 ms deferred assembly ≈ **1.25 s**
   against the 1.2 s deadline: it fails the brief's own done-when ("below the hook's deadline with
   margin") on the brief's own numbers. Separately, "(a) keeps the guard exactly as strong" is
   false: `list_supported_models()` reports the registry's *claimed* dimension for a name, not the
   artifact's measured width, so (a) validates registry-vs-store — a transcribed constant
   outsourced to fastembed, the same character of thing as the model→dim table the brief rejects
   under D20. Suggested edit: move (a) to the rejected list with both sentences, or carry both
   corrections in place.

5. **[IMPROVEMENT] Fact 2's "~400 ms" understates the surface-side wait by roughly 2×; replace it
   with the end-to-end sum.** If the load thread starts at assemble (~360 ms after spawn) and costs
   ~1059 ms, it completes ~1.42–1.56 s after spawn; a `surface` arriving at ~700 ms on the hook's
   clock therefore blocks ~700–900 ms *inside* the call and answers ~1.5–1.6 s into the 2.0 s
   budget — margin ~400–500 ms, thinner than "spend ~400 ms and still answer" reads. The
   conclusion (it fits) survives; the number a fresh session would size the margin from does not.
   The done-when's whole-sequence measurement will catch this empirically, but the brief's stated
   arithmetic should not need catching.

6. **[IMPROVEMENT] State once, above the option list, that (a)–(c) are guard-side *enablers* that
   each presuppose re-landing the reverted `BackgroundLoadedEncoder` deferral.** As written, (b)'s
   "free, needs no encoder at all" invites a literal implementation that changes the guard and
   keeps the eager `FastEmbedEncoder.load` at `context.py:150` — which changes socket-ready latency
   by zero. The done-when would eventually fail such a build, but a sentence is cheaper than a
   discovered dead end.

7. **[IMPROVEMENT] Add the outcome-level observable to the done-when.** The defect is "push
   silently lost", so assert its absence directly: on the first message to a genuinely cold
   service, the hook's stdout is the surface block, not a degrade relay, and `hook.log` gains no
   `transport` line — three of three runs, idle machine, load recorded. Socket-ready-with-margin
   and the whole-sequence timing are the right instruments, but neither *is* the defect.

8. **[NITPICK] `zikaron/hook/connect.py` `_poll_until_reachable`'s docstring is truncated
   mid-sentence** ("...well before `ServiceContext.assemble()`'s model load" — the sentence never
   ends, connect.py:264–266), and under any deferral its premise inverts (assemble no longer
   contains the model load; `health()` becomes true before the encoder is ready). Not M17's
   artifact, but M17's implementer edits this exact behavior story; fix in passing.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-19

### The three questions, attacked

**Q1 — the common-cost claim is true, and it is understated in your favor.** I looked hard for a
(b)-shape cheaper than "wrapper + something blocking until ready", and there is one — but it does
not change the conclusion. The cheapest honest (b) is: re-land the reverted
`BackgroundLoadedEncoder` **verbatim** (the stack-trace experiment proved `__post_init__` was the
*only* assembly-time toucher, so with the check deleted, the all-members-blocking wrapper from git
history suffices — no immediate-identity properties needed at all) plus delete the check. That is
genuinely smaller than (d) by the identity handoff. **But (b) cannot shed the latch or the
self-stop, and your 40-line marginal estimate wrongly charges both to (d).**
`FastEmbedEncoder.load` fails for reasons that have nothing to do with identity — its own `Raises`
section names two `BAD_CONFIG` artifact failures (no tokenizer, no `max_length`,
encoder.py:151–155), and a cold fastembed cache adds download and disk failures. Under *any*
deferral that failure now happens after bind, inside a thread; the wrapper must latch it, the
blocking members must raise it, and the resident-zombie problem — `health()` true forever,
retries refreshing `ActivityTracker` — exists under (b) exactly as under (d). So wrapper, latch,
*and* self-stop are all common cost. (d)'s true marginal cost over the cheapest (b) is: two
constructor arguments carrying the expected identity, two immediate properties, and one `dim`
comparison in the loader — closer to 15 lines than 40. Against that, (b) carries costs (d) does
not: deleting the shipped invariant test, rewriting `IndexingContext`'s now-false "Self-validating"
docstring (writes.py:67–71), and recording an accepted silent-corruption channel. Your reasoning
survives; correct its bookkeeping (finding 3).

**Q2 — I tried to make (b)+test win, and it loses on three counts; round 1's recommendation
stands.** The strongest case for (b)+test: the guard defends only against our own future call-site
drift; a test is the normal defence against our own programming errors; runtime machinery that
exists for a case that cannot currently fire is standing liability. It fails: (i) **a test pins
enumerated call sites, and the drift class is by definition an unenumerated future call site** — a
second store in one process (D8 says no global tier "in v0", and this machine already runs two
stores), a cached encoder, a consolidator sharing one. A constructor invariant travels with the
object into call sites the test's author never saw; a test written today asserts that *today's one
call site* passes the config string to `load`, which is precisely the case where nothing is wrong.
And the failure being defended against is the equal-width silent class, where the first loud
symptom is *never*. (ii) The vacuity analysis under Q3 below: (d)'s `__post_init__` still fires,
eagerly, on exactly the most likely drift shape — a wrapper seeded from one store/config wired
into another's `IndexingContext` — which (b)+test catches never. (iii) The premium is ~15 lines
over what (b) must build anyway (Q1). Separately, (b) cannot satisfy the milestone's own invariant
1 as written (finding 1). One honest concession: if the identity handoff turned out to require
touching the `Encoder` protocol or materially churning `FakeEncoder` — round 1's condition (i) —
the calculus changes. It will not: see Q3.

**Q3 — the vacuity objection dissolves under precision, because the check is not vacuous; the
brief merely says it is, and the brief is wrong in its own disfavor.** Take the two halves of
`__post_init__` separately. **The name half retains exactly today's strength.** Per the brief's
own fact 1, today's eager check *already* compares a declared string — `load`'s echoed argument,
sourced from config — against `meta`; it has never compared an artifact fact. The wrapper's
expected `model_name`, sourced from the same config key, is the identical comparison with
identical provenance. Nothing weakens. **The dim half is the only part that becomes vacuous for
the wrapper** — `store.meta.embed_dim` compared to `identity.embed_dim`, meta against meta — and
its real content, the *measured* width, moves into the loader's latched comparison rather than
disappearing. **And the check as a whole still fires for the wrapper** whenever a wrapper seeded
from store/config A is wired into store B's `IndexingContext` with a different model name — the
cross-wiring case, which is the concrete shape of the "future code drift" the brief's §stake
section says the guard exists for. So: no new shape is needed, no protocol change is needed, and
the shape proposed already avoids the defect — what must change is the brief's *description* of
it (finding 2). A mandated comment reading "this check structurally cannot fail" above a check
that in fact fires on miswiring would itself be this project's misleading-comment defect, in the
opposite direction. On the protocol question specifically: `Embedder`'s own docstring already
licenses declared identity — *"this protocol says nothing about how `dim` is produced; only that
it is available without embedding anything"* (embedder.py:21) — and `FakeEmbedder` is shipped
precedent. The wrapper conforms by the protocol's charter, not by loophole.

### Summary judgment

All eight round-1 findings landed except one half of finding 3 (the invariant extension), and the
rewrite is accurate everywhere I re-derived it — the arithmetic in fact 2, the (a) rejection, the
stake section, and the `-32023`/`_REJECTION_KINDS` and `vectors.py:65` citations all check out
against the code. The provisional choice of (d) is right and the case for it is stronger than
either the brief or your cover reasoning states: the latch and self-stop are common cost (so (d)'s
premium is ~15 lines, not 40), and the "vacuous check" charge against (d) is substantially false.
One blocker remains — invariant 1 contradicts still-live candidate (b) and, under (d), tests an
internal latch rather than anything a client observes — plus the description-level corrections
above.

### Findings

1. **[BLOCKER] Invariant 1 is unsatisfiable under (b), which the brief keeps as a live candidate —
   and it never received round 1 finding 3's extension, so under (d) it asserts an internal latch
   rather than client-observable behavior.** As written ("still refused, with `BAD_CONFIG` and the
   same payload ... construct an encoder whose `dim` disagrees and watch the guard fire"): under
   (b) the construction-time guard is deleted, a disagreeing `dim` surfaces as `INDEX_FAILED` at
   first embed (vectors.py:48–49, 65 — different code, different payload), and a disagreeing name
   at equal width surfaces never — so the invariants section silently decides the option choice
   the candidates section presents as open. And under (d), "watch the guard fire" names no
   observable: the mismatch is latched in a thread. Suggested replacement: *"A model or dimension
   that disagrees with the store's recorded identity is still refused with `BAD_CONFIG` and the
   same payload — asserted where a client sees it: the blocking member raises the latched error,
   the in-flight RPC answers `-32023`, and the service self-stops with the new reason. Assert it
   by breaking it — hand the loader an artifact whose measured `dim` disagrees with the store's —
   not by unit-testing the comparison function alone. Under (b) this invariant cannot be met and
   its test is deleted; that is part of (b)'s price and choosing (b) means saying so here."*
   Recording (d) as the chosen design (which the brief currently nowhere does — it demands the
   ordering choice be recorded but not the option choice) resolves the contradiction in the same
   stroke and should happen regardless.

2. **[IMPROVEMENT] Correct the vacuity sentence in (d); as mandated, the comment would be false.**
   Replace "Say plainly in the code that this makes `__post_init__` vacuous for the wrapper by
   construction — a check that structurally cannot fail is worse than no check if a reader
   mistakes it for protection" with the accurate statement (argued under Q3): for the wrapper,
   the **dim** comparison is meta-vs-meta and cannot fail — the measured-width check lives in the
   loader's latched comparison — while the **name** comparison keeps exactly the strength it has
   always had (declared identity against the store's; per fact 1 it never compared an artifact
   fact), and the check as a whole still fires on a wrapper wired to the wrong store or seeded
   from the wrong config. That is the comment the code should carry. Worth one parenthetical in
   the same paragraph: since the wrapper calls `load(expected.model_name)`, the loader's *name*
   comparison is an echo check and vacuous by fact 1 — `dim` is that comparison's entire content —
   so an implementer does not write a name assertion there and believe it tests something.

3. **[IMPROVEMENT] Move the latch and the self-stop into the common-cost paragraph; they are not
   (d)'s marginal machinery.** The brief hangs "A latched failure must end the process" off the
   (d) subsection, and your marginal-cost arithmetic charges latch + self-stop to (d). Both are
   required under every option, including (b), because `load` itself fails post-bind under any
   deferral for non-identity reasons (encoder.py:151–155's two `BAD_CONFIG` artifact failures;
   download/disk on a cold cache) and the resident-zombie state follows identically. Suggested
   edit: state in §"What is actually at stake" that the wrapper, the latched-failure channel, and
   the self-stop are all common cost; what the options buy or decline is only the identity
   handoff and the loader's one comparison. This also makes (b)'s "cheapness" honest: it saves
   ~15 lines, not the self-stop machinery.

4. **[IMPROVEMENT] The ordering-consequence paragraph and fact 2's margin arithmetic contradict
   each other; "either is defensible" is wrong on the brief's own numbers.** Fact 2's ~400–500 ms
   margin assumes the load thread starts at assemble's top (~360 ms after spawn). The
   start-after-open choice starts it ~140 ms later, so the load completes ~1.56–1.70 s and a
   ~700 ms `surface` answers ~1.65–1.75 s — margin ~250–350 ms, straddling the brief's own
   ~300 ms threshold for pulling the shelved split-deadline lever. Meanwhile the start-early
   choice's event costs nothing at runtime: the identity event gates only *validation*, and by
   the time `load` returns (~1.4 s) the identity has been set for over a second, so the loader
   thread never actually waits. Suggested edit: name start-early as the default because
   start-after-open spends roughly a third of the fact-2 margin, and keep "the milestone must say
   which it chose" for the record.

5. **[NITPICK] (b)'s "record the weakening ... in the guard's own comment" names a location that
   no longer exists under (b).** The guard is deleted; the record belongs in `IndexingContext`'s
   docstring, whose "Self-validating, so every write inward may assume the encoder matches the
   index it is writing into" (writes.py:67–71) becomes false under (b) and must be rewritten
   regardless. Name the docstring.

6. **[NITPICK] Add one sentence of protocol ammunition to (d):** `Embedder`'s docstring already
   states "this protocol says nothing about *how* `dim` is produced; only that it is available
   without embedding anything" (embedder.py:21), and `FakeEmbedder` is shipped precedent for
   declared identity — so the wrapper needs no protocol change and `FakeEncoder` is untouched,
   which discharges round 1's condition (i) explicitly rather than leaving it to be re-checked.

7. **[NITPICK] Two prose wrinkles from the rewrite.** "three runs of three" in the done-when
   (round 1 said "three of three runs"); and the socket-ready figure **1177–1257 ms** disagrees
   with FINDINGS.md priority item 6's **1184–1235 ms** while the brief's evidence line claims
   FINDINGS "carries every number below" — if the wider range came from more runs, say so in one
   parenthetical, or soften the evidence line.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-19

Verification round. (d) is decided by the operator; per the brief's instruction I looked for
infeasibility only, and found none — every load-bearing premise re-checks against the code:
`-32023` is `BAD_CONFIG` (`errors.py:44`) and `push.py:120` relays it as `bad_config`;
`log_self_stop` takes a free-form `reason` (`log.py:51`), so "a new reason" is data, not a schema
change; `health()` reads `store.meta` only (`dispatch.py:91–99`), so the zombie analysis holds;
the eager load is at `context.py:150` as cited; the `embedder.py:21` quote is verbatim; and
`FakeEmbedder` (`embedder.py:36`) and `FakeEncoder` (`tests/fake_encoder.py:45`) both exist and
are distinct, so the protocol-precedent sentence names real things. **(d) is implementable as
specified.**

**All seven applied fixes landed, and landed accurately.** (1) Invariant 1 now asserts the
client-observable chain with the (b) clause in past tense. (2) The vacuity paragraph is the
precise version, parenthetical included. (3) The wrapper/latch/self-stop are common cost in
§"What is actually at stake", with `encoder.py:151–155` and the cold-cache failures named, and
the full self-stop paragraph relocated intact — no duplicate left behind in (d). (4) Start-early
is the default; I re-derived the arithmetic (~500 ms start + ~1059 ms load → completion
~1.56–1.70 s → answer ~1.65–1.75 s → margin ~250–350 ms) and it is consistent with fact 2's
~400–500 ms and with the shelf paragraph's ~300 ms threshold; "spends roughly a third of fact 2's
margin" checks out. (5) (b)'s record location is the `writes.py:67–71` docstring. (6) The
protocol question is discharged in place. (7) "three of three runs" is fixed and the unreconciled
range is stated as unreconciled with the A/B named as what supersedes it. The brief is now
sufficient for a fresh session: wrapper shape (which two members answer immediately and from
where), what blocks, the ordering and its default, the latch, the self-stop, four invariants, and
the measurement protocol including the idle-machine requirement are all stated without needing
this review file.

### Summary judgment

The rewrite is accurate everywhere I re-derived it and introduced no garbled prose, no duplicated
claims, and no orphaned references. One genuine inconsistency survives the rewrite, and it is the
residue of round 2's own findings 1 and 2 colliding: the vacuity parenthetical correctly rules the
loader's *name* comparison vacuous, but invariant 1 and (d)'s headline sentence both still route a
disagreeing **model name** through the latch chain, which fact 1 makes impossible — the invariant
is the milestone's test contract, so its letter should not name an unsatisfiable observable. That
one edit is the only thing between this and APPROVED; everything else below is trivial.

### Findings

1. **[IMPROVEMENT] The name half still travels the latch chain in two places the vacuity
   parenthetical contradicts — and in the invariant, that letter is unsatisfiable.** The
   parenthetical (build-plan.md:996–999) is right: the wrapper calls `load(expected.model_name)`,
   `load` echoes its argument (fact 1), and `expected.model_name` comes from config, which
   `Store.open` has already proved equal to meta — so **no disagreeing name can ever reach the
   latch**, with a real loader, on any path. Yet: (i) **Invariant 1** opens "A **model** or
   dimension that disagrees ... the blocking member raises the latched error, the in-flight RPC
   answers `-32023`, and the service self-stops" (build-plan.md:1055–1058). For "model" those
   observables cannot be produced except by a stub that fact 1 says misrepresents the real loader;
   a test author either chases an impossible assertion or writes the vacuous loader name-check the
   parenthetical forbids. Suggested edit: *"A **dimension** whose measured value disagrees with
   the store's recorded identity is still refused ... [rest unchanged]. A disagreeing model
   **name** cannot reach the latch at all — the artifact echoes `load`'s argument (fact 1) — and
   is still refused where it always was: config-vs-meta at `Store.open`, before bind, and
   `__post_init__` on a cross-wired wrapper; both startup-shaped, unchanged by this milestone."*
   (ii) **(d)'s headline** (build-plan.md:968–969), "The loader compares the freshly loaded
   artifact's `model_name`/`dim` against the store's recorded identity", instructs the comparison
   the parenthetical then half-retracts twenty lines later. Suggested edit: *"The loader compares
   the freshly loaded artifact's measured `dim` against the store's recorded identity (the
   artifact's `model_name` is an echo of `load`'s argument — fact 1 — so `dim` is the comparison's
   entire content) and stores either the encoder or the `ZikaronError` ..."* — after which the
   later parenthetical can stay as reinforcement or be trimmed.

2. **[NITPICK] Say who initiates the self-stop: the loader thread, the moment it latches — not
   the first raising access.** "On a latched failure the service drains ..."
   (build-plan.md:909–911) reads that way on the plain reading, but never says it, and the
   invariant-1 test cannot distinguish the two wirings (it must send a request to observe
   `-32023`, and either wiring passes then). The lazy wiring leaves a trafficless mismatched
   service resident as `ready=true` until idle-stop — bounded at 30 min and every real caller is
   still served correctly, which is why this is a nitpick and not more — but one clause forecloses
   it: *"initiated by the loader thread the moment it latches, so a mismatched service with no
   traffic does not sit resident until idle-stop."*

3. **[NITPICK] The evidence line's "carries every number below" is contradicted by the brief's
   own unreconciled-range note four paragraphs later** (build-plan.md:767–768 vs 839–844) — and
   loosely false twice more: the table's `import fastembed` **640 ms** is FINDINGS' **638 ms**,
   and the create-path **~847 ms** appears nowhere in FINDINGS. Not re-flagging the unreconciled
   range itself (intentional); the fix is to the claim about it: *"which carries the negative
   result and most of the numbers below — one range differs, see the note under the table."*

4. **[NITPICK] Three post-decision staleness residues.** (i) (b)'s "If this is chosen"
   (build-plan.md:953) → "If this is ever chosen", matching the head paragraph's
   kept-for-the-record framing. (ii) Invariant 4's "whatever the protocol becomes"
   (build-plan.md:1070) predates (d)'s settled "no protocol change is needed" — reword to *"the
   `Encoder` protocol does not change under (d); `FakeEncoder` stays untouched and the hermetic
   tier keeps running on it."* (iii) The scope fence's "without saying so in the guard itself"
   (build-plan.md:1096) is letter-impossible under (b), whose record location is now correctly
   the class docstring because the guard is gone — moot under (d), one parenthetical if anyone
   cares.

5. **[NITPICK] Add `dispatch.py:79` `health`'s docstring to the fix-in-passing list.** Its
   justification — "a service that can answer at all has, by construction, already opened its
   store (`ServiceContext.assemble` raises before the socket is ever opened otherwise)"
   (dispatch.py:85–89) — stays true of the store but stops covering the encoder under any
   deferral: encoder failures now latch post-bind, so `ready=true` no longer implies a working
   encoder. Same class as the `connect.py:264–266` item the brief already carries, and a reader
   of that docstring post-M17 would draw exactly the wrong conclusion the self-stop paragraph
   exists to prevent.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-08-19

Verification round. All five round-3 findings landed, each checked against the text rather than
the changelog, and none introduced a contradiction:

- **(1i) Invariant 1** (build-plan.md:1064–1078) opens on a dimension whose *measured value*
  disagrees; the name clause names both surviving refusal sites (config-vs-meta at `Store.open`
  before the bind; `__post_init__` on a cross-wired wrapper) as startup-shaped and unchanged; the
  (b) clause is fully counterfactual. I checked the rewrapped bullet word by word for the damage
  the author flagged: none — no joined or dropped words, wrapping consistent, tense coherent
  inside the counterfactual. Satisfiability re-verified: a store whose config *and* meta both
  carry a doctored `embed_dim` passes `Store.open` and the wrapper's vacuous `__post_init__`,
  then the real artifact's measured 384 disagrees at the loader — so the demanded test is
  writable against the real loader, with no stub that misrepresents it.
- **(1ii) (d)'s headline** (968–977) now compares measured `dim` only, echo parenthetical
  inline; consistent with the vacuity parenthetical at 1000–1003, which correctly survives as
  reinforcement. No third location still routes a disagreeing name through the latch.
- **(2)** The loader-thread initiation clause and the two-wirings note landed (910–913) — one
  prose casualty, finding 1 below.
- **(3)** The evidence line (767–768) is now honest; "most of the numbers" also covers the
  640/638 ms and ~847 ms gaps round 3 noted in passing.
- **(4)** "If this is ever chosen" (955); invariant 4 as suggested verbatim (1084–1086); the
  scope fence names both record locations (1109–1112).
- **(5)** `health`'s docstring is in the fix-in-passing paragraph (1055–1060) with the correct
  reason.

Implementability re-checked end to end: wrapper identity sources (config `model_name`,
`store.meta.embed_dim`), what blocks and where (facts 3–4, invariant 3), the ordering default
with its arithmetic, the latch, the loader-initiated self-stop, four invariants, and the
three-layer done-when (socket-ready A/B, end-to-end sequence, outcome-level observable, idle
machine) are all stated without needing this review file. Nothing is orphaned or duplicated —
the relocated self-stop paragraph left no residue in (d), and no candidate text still assumes
the choice is open. No infeasibility in (d) found.

### Summary judgment

Every round-3 fix landed accurately and the section is internally consistent: the name/dim split
now reads the same way in all three places it appears, and the invariant contract is satisfiable
by a real-loader test. What remains is three cosmetic residues of the round-3 edits themselves —
one genuinely garbled antecedent (in the self-stop paragraph, not the invariant bullet the author
asked about) and two line-wrap artifacts. None would cause a fresh session to misimplement,
because the semantics each sentence garbles are stated correctly in bold or in the invariant one
paragraph away. Ship it; fix the sentence when next touching the file.

### Findings

1. **[NITPICK] The inserted two-wirings note orphans "— which restores today's recovery loop
   exactly" from its antecedent** (build-plan.md:908–914). The sentence now runs: "drains …
   writes … unlinks and exits — **initiated by the loader thread …** — so a mismatched service …
   does not sit resident until idle-stop; note that invariant 1's test cannot tell the two
   wirings apart, since observing `-32023` requires sending a request either way — which restores
   today's recovery loop exactly, since the next message spawns a fresh process…". Grammatically,
   "which restores" now attaches to the note clause ("observing `-32023` requires sending a
   request"), which restores nothing; its true antecedent is the drain-log-unlink-exit sequence
   three clauses back. Suggested edit: end the sentence after "either way." and continue
   *"Exiting restores today's recovery loop exactly: the next message spawns a fresh process
   against the corrected config."* Line 913 is also ~108 columns against the section's ~100
   wrap — the same edit's residue; the rewording fixes both.

2. **[NITPICK] Line 974 is ~111 columns, another edit residue — and while rewrapping it,
   consider one word.** "**What it preserves:** the same comparison, the same artifact-derived
   `dim`, the same `BAD_CONFIG` payload" lists "the same comparison" and "the same
   artifact-derived `dim`" as two items, but after the headline fix the artifact-derived `dim`
   *is* the comparison's entire content — the em-dash clause immediately above says so.
   *"the same artifact-derived `dim` comparison, the same `BAD_CONFIG` payload"* says it in one
   item and cannot be read as claiming the loader still compares the name. Optional; the
   adjacent clause already disambiguates for a careful reader.

3. **[NITPICK] The scope-fence rewrap left a short orphan line mid-paragraph**
   (build-plan.md:1112): "claim lives once the guard itself is gone. The idle" wraps at ~50
   columns with "timeout is not the subject" starting the next line. Rewrap the paragraph to the
   section's width. Purely cosmetic.

VERDICT: APPROVED

## Round 5 — 2026-08-19 — the artifact changes: this round reviews the implementation, not the brief

Rounds 1–4 reviewed and approved `design/build-plan.md` §M17. This round checks the shipped code
and tests against that approved design. Files reviewed: `zikaron/core/indexing/encoder.py`
(`BackgroundLoadedEncoder`, `index_identity_disagrees`), `zikaron/core/indexing/writes.py`,
`zikaron/service/context.py`, `zikaron/service/lifecycle.py`, `zikaron/service/main.py`,
`zikaron/service/dispatch.py` and `zikaron/hook/connect.py` (docstrings), `design/architecture.md`
§"The model loads behind the socket" plus §"First run" and the clean-exit observable, and the four
named test files.

### Design conformance, checked point by point

Every structural clause of the approved design is implemented as specified. **Identity handoff:**
`model_name` from `config.get_str("embed_model")` at construction, `dim` via
`declare_dim(store.meta.embed_dim)` (`context.py:164–165, 228`) — exactly the two sources the
brief names. **Loader-thread check, measured width only:** `_load_or_reject` (encoder.py:435–445)
compares `artifact.dim` against the declared width and deliberately writes no name assertion,
matching the vacuity parenthetical; the module docstring of `test_background_encoder.py` even
states why, and `test_a_disagreeing_model_name_is_not_checked_here` pins it. **Latch:**
`_failure`/`_loaded` with the `finally`-set event, `BaseException` caught on the loader thread so
a waiter can never wait on an event that is never set (encoder.py:421–433) — sound. **Self-stop,
loader-initiated:** `stop_on_encoder_failure` wakes from `failure()` the moment the latch sets,
not from the first raising access, so a trafficless mismatched service does not sit resident
(lifecycle.py:121–163); wired into `run()` through `_self_stopping_tasks`, created only when
`encoder_load` is not `None`, and a completing watch is correctly treated as a self-stop by the
`done & set(self_stopping)` check (main.py:240). A watch that *raises* `ShutdownTimeoutError`
routes to the terminal path through `_raise_if_any_task_genuinely_failed` — checked. **Start
early:** the facade is constructed at the top of `assemble`, before `_open_or_create`, and the
identity event is released on every failure path (`except BaseException: loading.release()`),
including cancellation — no path leaves the loader waiting on a declaration that never comes.
**Create path:** blocks on `artifact()` through `to_thread`, hands `Store.create` and
`IndexingContext` the raw artifact (eager check preserved), returns `encoder_load=None` —
unchanged in every way the invariant demands. **Protocol and fakes:** `Encoder` unchanged,
`FakeEncoder` untouched (read in full — all fields pre-existing), the shipped `__post_init__`
invariant test (`test_indexing_writes.py:1009–1031`) survives with the shared factory and its
payload assertions still hold. **Scope fence:** `HEALTH_POLL_DEADLINE_SECONDS` still 1.2, socket-
before-store ordering untouched, guard not weakened. Both fix-in-passing docstrings landed
correctly, and `dispatch.py:91–94`'s new "`ready` speaks for the store, not for the encoder"
paragraph is exactly what round 3 finding 5 asked for.

**Concurrency, attacked as requested.** The memory-visibility story is earned, not assumed:
`_dim` is written before `_declared.set()` and read after `_declared.wait()`; `_artifact`/
`_failure` are written before `_loaded.set()` in a `finally` and read after `_loaded.wait()` —
`threading.Event` is a lock-backed condition, so every cross-thread read is ordered by an
acquire/release pair, GIL aside. Re-raising one exception instance from multiple threads mutates
only its `__traceback__`, which is `concurrent.futures.Future.result()`'s own shipped behaviour —
acceptable, and the tests assert instance identity, which holds. The one deadlock I found is
misuse-only and is finding 6; the one *production* non-termination is finding 8. Nothing on the
open path between `assemble`'s construction of the facade and its return reads an artifact member
— I checked every construction in the `try` block (`IndexingContext.for_store` reads only the two
declared properties; `RetrievalSettings`/`ConsolidationSettings` read config only) — so the
rewritten `assemble` docstring's central claim, the one whose earlier version killed the first
attempt, is true of this code.

### Summary judgment

The implementation is faithful to the approved design in every structural respect I could check,
and the concurrency core is sound. What falls short is the test layer: two of the new tests are
vacuous in exactly the class the author asked me to hunt — one of them the flagship unit test of
the milestone's core property, whose docstring claims it "cannot pass by accidentally waiting"
while a 5 s gate timeout makes it do precisely that — and invariant 1's middle observable, the
in-flight RPC answering `-32023`, is asserted nowhere. Fix those three and this ships; the
remaining findings are prose honesty and one cheap loudness improvement.

### Findings

1. **[BLOCKER] `test_declared_identity_answers_while_the_artifact_is_still_loading`
   (tests/test_background_encoder.py:51–65) is vacuous — it passes under the exact reverted-trap
   mutation it exists to prevent, and its docstring's "this cannot pass by accidentally waiting"
   is false.** Mutate `model_name`/`dim` to call `_resolved()` first: the property blocks,
   `_GatedLoad.__call__`'s `released.wait(timeout=5.0)` (line 37) expires, the loader finishes
   and latches, and every assertion then passes — `model_name` matches (the artifact echoes the
   default), `dim` matches (FakeEncoder's default 384 equals the declared 384), and
   `assert not load.released.is_set()` passes because `released` is an input the test never set;
   the timeout expiring is what satisfied it. This is the identical vacuity shape the author
   found and fixed in `test_assemble_returns_on_the_open_path_before_the_model_has_loaded`
   (whose comment at test_service_context_assemble.py:247–251 describes it word for word), fixed
   there and not here. The property does have non-vacuous *system-level* cover in that assemble
   test, which is why the suite is not blind — but a unit test that certifies the milestone's
   core property only when the code is right, and certifies it anyway when the code is wrong, is
   the M14 green-gate class this corpus records. Concrete fix, same pattern as the assemble
   test: add `self.finished = threading.Event()` to `_GatedLoad`, set it in a `finally` around
   `__call__`'s return, and assert `not load.finished.is_set()` after the two property reads
   (keep the `released` assert or drop it; it proves nothing either way). Mutation-verify by
   making `dim` call `_resolved()` first: the fixed test must fail in ~5 s.

2. **[BLOCKER] `test_the_watch_does_not_block_the_event_loop_while_the_model_loads`
   (tests/test_service_encoder_failure_stop.py:104–136) asserts a constant: `ticks == 5` cannot
   be false.** The loop increments `ticks` unconditionally five times with no timeout around it,
   so the assertion holds whether the five `sleep(0)` turns took microseconds or five seconds.
   Mutate `stop_on_encoder_failure` to call `loading.failure()` synchronously on the loop: the
   loop blocks inside `_loaded.wait()` until `_slow_load`'s `release.wait(timeout=5.0)` expires,
   the load completes, `failure()` returns `None`, the watch suspends on its forever-event, the
   tick loop then runs — and the test passes, five seconds slower, having measured nothing. And
   unlike finding 1, **no other test catches this mutation**: the failed-load test's loader
   raises instantly, so a synchronous `failure()` is invisible there too. Concrete fix: add
   `finished = threading.Event()`, set it in `_slow_load` immediately before returning, and
   after the tick loop assert `not finished.is_set()` — with the watch off-loop the five turns
   complete while the loader is still gated, and with it on-loop the turns can only run after
   the loader finished, failing the new assert deterministically. Mutation-verify with the
   synchronous-`failure()` mutation.

3. **[BLOCKER] Invariant 1's middle observable — "the in-flight RPC answers `-32023`" — is
   asserted nowhere.** The invariant (build-plan.md:1064–1069) names three client-observable
   links and demands they be asserted "where a client sees it, not at an internal latch". The
   first link (blocking member raises the latched `BAD_CONFIG`) is covered by
   `test_a_width_disagreeing_with_the_store_is_refused_by_every_artifact_member`; the third
   (self-stop with the new reason) by `test_a_failed_load_unlinks_the_socket_and_stops_the_
   server`. The second — a real request over the socket answered with wire code `-32023` — has
   no test: the only `-32023` assertions in the tree (`test_hook_push.py:283, 498`) run against
   a scripted fake service. The chain is plausible by composition (the latched `ZikaronError`
   propagates out of `to_thread`, `_compute_response_line` maps every `ZikaronError` to its
   code), but composition-of-tested-halves is precisely what this project's own M14 record says
   not to trust. Concrete test, deterministic because it needs no watch task: build a served
   context à la `service_fixtures.open_context` but with a gated `BackgroundLoadedEncoder`
   (loader returns `FakeEncoder(dim=768)`, `declare_dim` the store's 384) as both `ctx.encoder`
   and `ctx.index.encoder`; connect a raw client socket; send a `surface` request while the gate
   is still closed (use `surface`, not `remember` — the read path reaches the encoder through
   `asyncio.to_thread`, so the test's own loop stays live; `remember` would block the loop in
   `plan_chunks`, which is finding 5's subject); release the gate; assert the response line
   carries `"code": -32023` and the disagreement payload. Mutation-verify by removing the width
   check: the response must then be a success line.

4. **[IMPROVEMENT] "Its request fails with `bad_config`, which reaches the model" is stated as
   a guarantee in two places and is in fact a race the code usually wins.** The claim
   (architecture.md:680–681 "An in-flight caller is told... rather than with a connection that
   simply stops answering"; lifecycle.py:139–141 "In-flight callers are not left guessing")
   assumes the handler writes its error line before the loader-initiated stop tears the
   connection down. But the stop path is `shut_down()` → `close_all_connections`, which
   **cancels** every handler task (server.py:317–319) — it does not drain them — and the request
   racing the latch wakes from the same `_loaded.set()` that wakes the watch, so whether the
   handler's `writer.drain()` completes before its task is cancelled is a scheduling race
   (transport close flushes buffered data, which is why the write usually survives, but
   "usually" is not what either sentence says). Since the design deliberately reuses the
   existing shutdown path rather than adding a drain (right call — the racing request fails
   promptly anyway), fix the prose, not the code: in both places, state that the in-flight
   request is answered `bad_config` *when its response beats the teardown, which the shared
   wake-up makes the common case*, and that the residual race loses nothing today's behaviour
   ever delivered (today's equivalent is a poll-deadline `transport`). Finding 3's test, run
   without the watch task, deliberately does not assert on this race.

5. **[IMPROVEMENT] Fact 4's "it must be stated" is not satisfied: the one on-loop encoder access
   is stated nowhere in the shipped artifact.** The brief (build-plan.md, fact 4) and invariant 3
   both require that the single event-loop-blocking wait — `writes.prepare` calling
   `chunking.plan_chunks` directly in a coroutine (writes.py:163–169), whose `count_tokens`/
   `token_char_spans` block on a still-loading deferred encoder for whatever remains of the load
   — be *stated*, with `to_thread` as the remedy if judged too long. I searched `writes.py`,
   `chunking.py`, and architecture.md §"The model loads behind the socket": no statement exists.
   Concrete edit: one sentence in `prepare`'s docstring (writes.py:152–162), in the house style —
   e.g. "`plan_chunks` runs on the event loop, and its token counts block on a deferred encoder
   for whatever remains of the model load — once per process, bounded by the load, accepted
   rather than wrapped in `to_thread` because the write that pays it is already the slow path" —
   or wrap the call and say why. Either discharges the invariant; silence does not.

6. **[IMPROVEMENT] An undeclared facade hangs forever on any blocking member, where the same
   misuse on `dim` fails loudly.** If neither `declare_dim`/`release`/`artifact` is ever called
   and a caller reaches `count_tokens` (or any of the five), the caller waits on `_loaded` while
   the loader waits on `_declared` — two untimed waits, a silent deadlock (encoder.py:413–414,
   437). `dim` handles the identical misuse with a `BAD_CONFIG` raise (encoder.py:385–389); the
   five blocking members should not answer it with a hang. Unreachable in production (`assemble`
   declares or releases on every path, including cancellation — checked), so this is
   misuse-proofing, but the class docstring invites reuse. Concrete edit: first line of
   `_resolved`, `if not self._declared.is_set(): raise _artifact_failure(self._model_name, "a
   declared index width, set once the store has been opened")` — safe because every legitimate
   caller's declaration happens-before the encoder is published (`artifact()` sets `_declared`
   itself), so no legitimate concurrent path can see it unset.

7. **[IMPROVEMENT] `assemble`'s `Raises` section still reads eager-world: it lists
   `FastEmbedEncoder.load`'s failures unqualified, but on the open path they never propagate
   from `assemble` at all — they latch.** context.py:152–162 names "`BAD_CONFIG` naming
   `embedding.embed_model` if the configured model exposes no usable tokenizer" as something
   this function raises; after this milestone that is true only on the create path, and the
   companion sentence at context.py:149–150 ("`FastEmbedEncoder.load` failing... this function's
   own `Raises` section already names both") compounds it. A reader diagnosing an open-path
   startup would conclude a broken model fails `assemble`, which is exactly backwards — it
   binds, latches, and self-stops. This is the author's priority-4 class, in the very docstring
   whose earlier false claim killed the first attempt. Concrete edit: scope the load-failure
   clauses with "on the create path only —", and add one clause: "on the open path a load
   failure does not raise here at all; it latches and surfaces at the first artifact access and
   through `stop_on_encoder_failure`."

8. **[IMPROVEMENT] Nothing names the non-terminating-load state, and it is the one state where
   this design produces the permanent resident process the scope fence forbids.** Every
   teardown path assumes `FastEmbedEncoder.load` terminates: `failure()` returns only when
   `_loaded` sets, so on a hung cold-cache download (a network read with no deadline) the watch
   never fires, `health()` answers `ready=true` indefinitely, every model-touching request
   blocks in `to_thread` — which pins `in_flight` above zero, so **idle self-stop can never
   fire either** (`may_stop`, context.py:70) — and a `SIGTERM` exit blocks in
   `asyncio.run`'s `shutdown_default_executor` joining the executor thread stuck in
   `failure()`. The latched-failure machinery covers a load that *fails*; a load that *hangs*
   is covered by nothing and named nowhere. The eager world had the same non-termination but
   never bound a socket, so it degraded invisibly. Not asking for a load deadline (out of
   scope); asking for the assumption to be stated where the machinery is: one sentence in
   architecture.md §"The model loads behind the socket" and/or `stop_on_encoder_failure`'s
   docstring — "everything here assumes the load terminates; a load that hangs leaves the
   service resident and ready, with every model-touching request blocked and both self-stop
   conditions unreachable, until the operator intervenes."

9. **[NITPICK] The second assemble test's docstring gives the wrong reason for its own
   injection point.** test_service_context_assemble.py:91–93: "for the identical reason: a
   failing `FastEmbedEncoder.load` now raises before `assemble` ever opens a store" — that is
   the *create-path* reason, and this test runs the open path (its store pre-exists), where a
   failing load does not raise before the open; it never raises from `assemble` at all. The
   sibling test's docstring (lines 38–42) states the correct reason; point at it or restate it.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-08-19

Verification round on the nine round-5 fixes. Each checked against the current code, the three
rewritten tests re-attacked by asking what mutation each survives, and every piece of new prose
re-derived against the code rather than against the changelog.

### The three tests, re-attacked

- **Fix 1** (`test_declared_identity_answers_while_the_artifact_is_still_loading`): non-vacuous
  now. Under the reverted-trap mutation (`dim` calling `_resolved()` first), the gate's 5 s
  timeout expires, `_GatedLoad.__call__`'s `finally` sets `finished` **before** the wrapper
  latches and sets `_loaded`, so `dim` returns only after `finished` is set and
  `assert not load.finished.is_set()` fails deterministically — same-thread ordering, no race.
  The comment at test_background_encoder.py:38–42 explaining why `released` proved nothing is
  accurate. `_loading`'s `entered.wait` also closes the "never started the load" mutation.
- **Fix 2** (`test_the_watch_does_not_block_the_event_loop_while_the_model_loads`): non-vacuous.
  Under a synchronous `loading.failure()`, the loop blocks in `_loaded.wait()`; `_slow_load`'s
  `finally` sets `finished` before the wrapper sets `_loaded`, so by the time the tick loop can
  run, `finished` is set and the assert fails — deterministic for the same ordering reason. The
  replacement comment ("the load is the assertion, not the count") is true of the code.
- **Fix 3** (`test_a_request_needing_the_model_is_answered_with_the_wire_error`): sound, and the
  `_handle_line` deviation is **accepted** — `_handle_connection` (server.py:196–199) writes
  `_handle_line`'s return verbatim (`response.encode("utf-8")`, nothing added), framing is
  covered in `test_service_server.py`, and the one thing a raw socket would add is the
  response-vs-teardown race the round-5 finding-4 prose deliberately declines to assert. The
  `replace(base.index, encoder=disagreeing)` re-runs `__post_init__` against the declared
  identity, which passes without blocking — incidentally exercising exactly the design's
  declared-identity property. Asserting `ErrorCode.BAD_CONFIG.value` rather than the literal
  `-32023` is adequately anchored: `test_error_codes.py::test_codes_and_names_match_the_design_
  table` pins every enum value against the design table, so the enum cannot drift silently.
  Under the width-check-removal mutation the latched 768-wide artifact turns the response into a
  non-`BAD_CONFIG` line (a 768 query vector against a 384 `vec0` index fails downstream), so the
  code assertion fails. Deterministic: no gate, no watch task, `_handle_line` awaited directly.

### The prose fixes and the two direct questions

Fix 4 landed accurately in both places (architecture.md:680–684; lifecycle.py:140–144 — the
shared-wake mechanism, cancel-not-drain, and the losing-costs-nothing clause all check against
`shut_down()`/`close_all_connections`). Fix 5's paragraph (writes.py:16–21) is true of the code:
`prepare` calls `plan_chunks` on the loop, the once-per-process bound holds (the first blocked
write consumes the remaining load; nothing after it can block), and "the read path reaches the
encoder through a thread" verifies against `reads.py:152`'s `to_thread(query.external_query, …)`.
Fix 6's guard (`encoder.py:419–422`) is correctly placed, its publish-before-use safety argument
holds for every production path, `artifact()` sets `_declared` itself so the create path is
unaffected, and the rewritten test drives the call on a joined thread with a 2 s deadline — the
confessed hang shape is genuinely gone. **The repeated-shape hunt found no other instance**: the
remaining direct calls to blocking members in `test_background_encoder.py` all run after
`released.set()`, are bounded by the gate's own 5 s timeout in any regression that still latches,
and none carries a docstring claiming a bound it does not have. Fix 7 (context.py:153–169) is
accurate on both paths, and the companion sentence at 149–151 now agrees with it. Fix 9's
docstring gives the correct open-path reason. Nothing contradictory or duplicated turned up
across the touched files — architecture.md, lifecycle.py, writes.py, dispatch.py:91 and the test
docstrings all tell the same story — with the single exception below.

### Summary judgment

Eight of nine fixes landed correctly and completely; the three rewritten tests are genuinely
non-vacuous under exactly the mutations that defeated their predecessors. The one miss is in fix
8's new prose, in both places it was added: the claim that with no traffic "idle self-stop fires
normally and the ordinary lifecycle still applies" is false — the stop fires and the socket goes,
but the process never finishes exiting, for a mechanism round 5 itself named for the SIGTERM path
and which applies identically to the idle exit. The paragraph whose whole job is naming the
uncovered state truthfully ends on a false reassurance; fix the sentence and this ships.

### Findings

1. **[IMPROVEMENT] The hang paragraph's no-traffic clause is untrue of the code, in both places
   fix 8 added it** (architecture.md:689–690 "With no traffic, idle self-stop fires as usual and
   the ordinary lifecycle still applies"; lifecycle.py:149–150, same claim). The stop does fire
   and the socket is unlinked — but the process cannot complete its exit. The watch's
   `asyncio.to_thread(loading.failure)` worker is blocked in an untimed `_loaded.wait()`
   (cancelling the watch task abandons the worker, it does not unblock it); `run()` returns and
   closes the store cleanly, then `asyncio.run`'s teardown waits `THREAD_JOIN_TIMEOUT` (300 s on
   the pinned 3.12) for the executor and gives up with a warning, and interpreter shutdown then
   blocks **forever** in `concurrent.futures.thread._python_exit`'s untimed `t.join()` on that
   same non-daemon worker. This is the identical mechanism round 5 finding 8 named for a
   `SIGTERM` exit; the idle exit leaves through the same teardown. So the true dichotomy is not
   resident-vs-ordinary: a resident process remains in **both** cases, and traffic decides only
   whether it stays *reachable* (socket bound, `in_flight` pinned, start-if-absent unable to
   replace it) or becomes unreachable residue (socket gone, store closed, next message spawns a
   fresh service, one leaked process until the operator kills it). Suggested edit, both places:
   *"With no traffic, idle self-stop still fires and the socket goes, so the next message spawns
   a fresh service — but the process itself never finishes exiting: interpreter shutdown joins
   the executor thread blocked in `failure()`, leaving a resident, unreachable process (its store
   already closed) until the operator kills it. With traffic it is worse: the first request that
   needs the model blocks, `in_flight` never returns to zero, and the resident process stays
   reachable, with nothing able to replace it."*

2. **[NITPICK] "before this class is ever constructed" is false in the letter, twice**
   (test_background_encoder.py:11 module docstring; :157
   `test_a_disagreeing_model_name_is_not_checked_here`). The facade is constructed at the top of
   `assemble` (context.py:171) and `Store.open`'s name check runs after it (context.py:234). The
   check precedes any *use* of the class, not its construction — architecture.md:667–669 states
   it correctly ("before the socket exists"). Pre-existing prose round 5 passed over, raised now
   because it is exactly the confident ordering claim this round was asked to hunt. Suggested:
   "before anything ever consults this class — at `Store.open`, against the store's own
   metadata."

3. **[NITPICK] build-plan.md:915 still states the in-flight relay as a flat guarantee** ("the
   in-flight caller's hook receives `-32023` and relays…") which fix 4 correctly downgraded to a
   usually-won race everywhere in the shipped artifacts. The brief is the approved plan and was
   not touched this round, so this is optional alignment: "normally receives" is the two-word
   version.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-08-19

Verification round on the three round-6 fixes plus the unrequested coverage test, in the caller's
priority order. The hang paragraphs were re-derived link by link against the installed 3.12 stdlib
sources rather than against my own round-6 text, since that text is itself part of the chain of
custody for a paragraph that has been wrong three times. Both terminal states were then traced
through `main.run` and `server.py` end to end.

### Priority 1 — the rewritten hang paragraphs: true, complete, correctly assigned

Every load-bearing clause in `design/architecture.md:686–697` and `lifecycle.py:146–163` now checks
against the code and the interpreter:

- **The trap chain, verified in the stdlib itself.** `asyncio.to_thread` → `run_in_executor(None,
  …)` (threads.py:25), so `loading.failure` occupies a **default-executor** worker;
  `ThreadPoolExecutor` workers are non-daemon on 3.12 (no `daemon=` anywhere in
  concurrent/futures/thread.py); `_python_exit` (thread.py:23–31) does `q.put(None)` then an
  **untimed** `t.join()` per worker — a worker blocked in `_loaded.wait()` never consumes the
  sentinel, so the join never returns; and it is registered via `threading._register_atexit`
  (thread.py:37), whose callbacks `threading._shutdown` runs **before** joining non-daemon threads
  (threading.py:1589–1592) — so, exactly as coding-standards already records for the store variant,
  no `atexit` hook runs late enough to rescue it. The author's correction stands verified:
  `THREAD_JOIN_TIMEOUT = 300` lives in `asyncio/constants.py:34`, and `Runner.close`
  (runners.py:72–73) passes it to `shutdown_default_executor`, which on expiry warns and proceeds
  (base_events.py:600–606) — a bounded 300 s detour the prose rightly omits, since the terminal
  fact ("never finishes exiting") is `_python_exit`'s untimed join, and "interpreter shutdown joins
  it with no deadline" attributes it correctly.
- **The no-traffic case, traced through `main.run`.** `idle_self_stop` fires (`in_flight` is 0, the
  clock started at assemble), unlinks, `shut_down()` returns trivially with no connections;
  `run()`'s `finally` cancels the watch — CancelledError lands at the `await`, the executor future
  is left running, gather completes — the outer `finally` closes the store; `Runner.close` burns
  its 300 s; `_python_exit` blocks forever. Store closed, socket gone, process resident. As stated.
- **The with-traffic case, traced through `server.py`.** A model-needing request blocks inside
  `handler(...)` → `to_thread` → `_resolved()` → `_loaded.wait()`; `end_request` sits in
  `_dispatch_request`'s `finally` (server.py:92–96) and never runs, so `in_flight` stays pinned —
  and I checked the one escape hatch: a client that gives up and disconnects does **not** unpin it,
  because the handler task is suspended inside `_handle_line`, not `readline()`, and nothing cancels
  handler tasks outside `close_all_connections`, which only shutdown reaches. `may_stop` is false
  forever, the socket stays bound, start-if-absent finds a listener. As stated.
- **Split completeness.** The elaborations are conditioned precisely ("the first request *needing
  the model*"), so traffic that never touches the encoder — health polls, `fetch` — correctly
  reduces to the no-traffic terminal state once it stops, and a load that terminates *late* rather
  than never un-sticks everything (the worker's `failure()` returns, it consumes the sentinel, the
  join completes), which is outside the paragraph's stated hypothesis and rightly unmentioned. One
  internal-consistency point checked deliberately: the **loader** thread is daemon
  (encoder.py:321–326, "must never be the reason a process outlives its work") and that is *not*
  contradicted by the residue — the thread that outlives the work is the executor's, exactly as
  both paragraphs say. Also verified `kill <pid>` genuinely works on the residue: the signal
  handlers were removed in `_stop_on_sigterm_or_sigint`'s `finally` before the block, restoring
  `SIG_DFL`, so "until someone kills it" needs no qualification.

### Priority 2 — the coding-standards parallel: same failure mode, not a false parallel

`coding-standards.md:226–234` records: a non-daemon thread (aiosqlite's worker) blocked on an
untimed internal wait keeps the process alive after its work is done, silently, joined before
`atexit` so nothing can rescue it — and for `zikaron-service` specifically, idle self-stop unlinks
the socket while the process stays resident, so the next start-if-absent raises a second service.
The executor variant is that mechanism exactly, at every level that matters: non-daemon thread,
untimed internal wait (`_loaded.wait()` instead of the connection queue), survives the event loop,
blocks inside `threading._shutdown` before any `atexit` hook, silent, socket already unlinked,
second service spawned alongside. Two honest differences, neither of which the prose overclaims:
the join site differs (`_threading_atexits`/`_python_exit` versus the ordinary non-daemon join —
both inside `threading._shutdown`, so the "no hook late enough" property carries over unchanged),
and the consequence is strictly milder here — coding-standards' named hazard is a second server
against a store the first **still holds**, whereas this residue's store is closed before the block,
so the second service is safe and the residue is only a leak. "The same trap, reached through the
executor instead" is the right sentence, and "holding nothing" is the clause carrying that second
difference — see finding 1 for its one imprecision.

### Priority 3 — the new test: sound, and I could not make it pass for the wrong reason

`test_assemble_releases_the_loader_when_the_store_cannot_be_opened`
(tests/test_service_context_assemble.py:298–347), attacked on four vectors: (i) on this path
`release()` is the **only** thing that can set `_declared` — `declare_dim` sits after the
`Store.open` that raises (context.py:234–235), and `artifact()` is create-path only, unreachable
because the store pre-exists — so the thread dying proves the `except BaseException` clause ran,
not something adjacent; (ii) `assert loaders` closes the load-never-started vacuity, and the append
runs on the loader thread itself before its `_declared.wait()`, so the recorded thread is
necessarily the one that would leak; (iii) the loader is daemon, so nothing else in the suite can
reap it and make `is_alive()` false by accident; (iv) under the stated mutation (drop
`loading.release()`) the thread blocks in an untimed `_declared.wait()`, `join(2.0)` expires, and
the `is_alive()` assert fails deterministically — matching the author's mutation report. The one
mutation it tolerates — replacing `release()` with a spurious `declare_dim` — still releases the
thread and so still satisfies the property the test names, which is the property that matters; not
a vacuity. The docstring's "invisible in production, where the process is exiting anyway" is
consistent with the daemon-thread fact and with `release()`'s own docstring.

### Priority 4 — consistency sweep

Round-6 findings 2 and 3 landed as suggested and are accurate against the code
(test_background_encoder.py:8–12 and :154–158 — and the added "before the service has bound a
socket" is true, since `assemble` completes before `serve()` is reached; build-plan.md:915 now
"normally receives"). The old false no-traffic clause survives nowhere outside this review file's
own history. architecture.md's earlier paragraphs (656–684), context.py's `Raises` section,
writes.py's on-loop statement, dispatch.py:91 and both rewritten watch tests are unchanged since
round 6 and still agree with the new dichotomy. Two wording residues turned up, below.

### Summary judgment

The hang paragraphs are now true of the code and of the pinned interpreter, link by link, and the
two-case split is complete under its stated hypothesis and correctly assigned; the
coding-standards parallel is genuine; the new test is non-vacuous and covers the one branch round
5 had only read. What remains is two word-level imprecisions, neither of which touches a
load-bearing claim. This ships.

### Findings

1. **[NITPICK] "holding nothing" claims more than was verified, in both places**
   (architecture.md:693 "unreachable residue holding nothing"; lifecycle.py:155 "an unreachable
   process holding nothing"). What is verified is: no store connection, no socket. What is not:
   in the paragraph's own named scenario — a hung cold artifact download — the daemon loader
   thread is mid-download in the model cache, and downloader file-locking (huggingface_hub locks
   per file) could plausibly leave the residue holding exactly the lock the *replacement*
   service's own load then blocks on. I have not verified that cascade and do not ask the
   artifact to assert it either way — which is precisely the argument for the narrower phrase.
   Suggested, both places: "holding neither store nor socket" — same rhythm, only the verified
   content.

2. **[NITPICK] `tests/test_service_context_assemble.py`'s module docstring (lines 5–6) still
   describes the pre-M17 injection point**: "`FastEmbedEncoder.load` monkeypatched to fail — no
   real model load needed to prove the store-closing contract." No default-tier test in this file
   patches the load to fail anymore; both closing tests patch it to a fake and inject at
   `IndexingContext.for_store`, and their own docstrings (lines 38–42, 91–94) explain that a
   failing load would not raise from `assemble` on the open path at all — so the header asserts
   the exact eager-world reading its own tests refute two paragraphs later, the round-5 finding-7
   class in miniature. Suggested: "a real store on `tmp_path`, `FastEmbedEncoder.load`
   monkeypatched to a fake and the failure injected at a post-open construction step — on the
   open path a failing load never raises from `assemble` at all, which is why the injection point
   moved."

VERDICT: APPROVED
