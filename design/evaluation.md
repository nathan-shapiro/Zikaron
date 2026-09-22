# Evaluation — construct decomposition

> **STATUS: proposal, not normative.** Opened 2026-09-14 in response to the operator's question: which
> public benchmark can evaluate Zikaron, given that LoCoMo-style suites test general-purpose
> conversational memory rather than engineering tribal knowledge. **The three research briefs
> returned 2026-09-14 and are §4.** §1 is derived from this corpus alone and stands on its own.
> §2's arm definitions rest on `research/agentic-eval-methodology.md` and are defensible defaults
> rather than settled facts; §3's sizing is now in §5; and §4.1's headline experiment rests on a
> reading withdrawn 2026-09-22, so it needs restating before it is run.
> *This header said the briefs were "pending", that §1 and §2 both stand "regardless of what those
> return", and that §3 "waits" — three states this document had already left, in the paragraph a
> reader uses to decide which sections are safe to act on.*
>
> Governing decision: **D14**, as narrowed — component benchmarking was never stoved, and what waits
> for a running system is one measure: *does having memory make the agent finish the task better*.
> Tracked as open question 9.

## 1. The claim is a chain of six links, and only the product is visible end to end

The product claim — "an agent on a project Zikaron has been running on does better than one without"
— is not one mechanism. It is six, in series, each with its own failure mode and its own owner in
the design record:

| # | Link | Fails by | Owner |
|---|---|---|---|
| 1 | **Write** — the agent records the right thing | recording nothing, or recording trivia | D6, D30; open question 7 (question 13 was resolved and shipped 2026-08-16, a month before this table, and is named here no longer) |
| 2 | **Retrieve** — the right record comes back for a query | ranking failure | D5, D20–D25 — **already measured** |
| 3 | **Deliver** — it reaches the agent at a moment it can act on | push fires at task framing; the need arrives 20 tool calls later | D12; open question 1 |
| 4 | **Use** — the agent acts on a record that is in its context | the sufficiency illusion: present and ignored | write policy; **not tracked by any open question** |
| 5 | **Repair** — a wrong memory gets corrected | silently stale, confidently acted on | D11; open question 6 |
| 6 | **Consolidate** — merging improves rather than degrades | index-shaped gists lose triage value | D29; open question 12 — **measured, and it degrades** |

**The consequence for eval design is the whole point of this section.** A single end-to-end A/B
measures the *product* of links 1–4 and is confounded by 5–6. If it comes back null, it does not say
which link failed — and this corpus has already established that links 1, 3, 4 and 6 each have live
known defects. A null result would therefore be expensive and uninformative, which is the worst
combination an experiment can have.

So the design needs an instrument that **localises** a null, not only one that detects a win.

## 2. Three arms, and the cheap one runs first

| Arm | Store | What it isolates |
|---|---|---|
| **A — no memory** | tools present, **store empty** | baseline |
| **B — Zikaron live** | grown by the agent's own earlier work | the product of links 1–4: the real system |
| **C — oracle memory** | hand-filled with exactly the records the later tasks need | links 3–4 only, with link 1 held perfect |

**Arm A is "tools present, store empty", not "tools absent" — corrected 2026-09-14 from the
methodology research.** Tool *presence* alone shifts agent behaviour independently of what the tool
returns, so removing the tools changes two things at once and the comparison stops being about
memory. The evidence for this is practitioner-level rather than a controlled study
(`research/agentic-eval-methodology.md`), so it is a defensible default rather than a settled fact —
but it errs in the safe direction, since an empty store is the weaker claim.

C is the **ceiling**: the benefit available if the write policy were perfect. Two ratios fall out,
and each answers a different question:

- **C vs A** — *is the construct real on this substrate at all?* Does tribal knowledge help here?
- **B vs C** — *how much of the achievable benefit does the write policy plus retrieval capture?*

**Sequencing follows directly, and it inverts the obvious order: run C vs A first, on a small
slice.** It is the cheapest arm to build and the only one that validates the *instrument*. If the
ceiling is flat — if a perfect store does not help — then no memory system can win on that substrate
and no amount of tuning B will show anything. We would have learned that for the price of the
smallest run, instead of after a full A/B. This is the corpus's own "name the quantity before
quoting a number about it", applied one level up: **check that the substrate can express the effect
before measuring the effect.**

## 3. The dependent variable is probably not resolve rate

Zikaron's scope line is a claim about **time**: it stores "what cost someone time to discover". The
natural dependent variable is therefore cost-to-solution — tokens, wall-clock, failed tool calls,
actions before the first correct test invocation — with task success as a secondary outcome.

Two independent reasons this matters more than it looks:

1. **Construct.** If the benefit is "the agent does not re-derive how to run the test suite", that
   benefit is invisible in a pass/fail outcome whenever the agent would have re-derived it and
   passed anyway. Binary success censors exactly the effect being claimed.
2. **Power.** A binary outcome over a few dozen instances has poor power against a single-digit
   percentage-point difference. A continuous per-instance cost metric on the *same* instances has
   far more, and supports a paired analysis. Sizing is **§5**, from `research/agentic-eval-methodology.md` — which returned 2026-09-14; this line said "pending" past the header that redirects to it.

**Known objection to the substrate hypothesis, raised here rather than waited for.** The leading
candidate — the SWE-bench family — is a poor fit *at its stock settings*, and for a reason that comes
straight from D1. SWE-bench rewards knowing the code, which the **memory store** excludes by its
scope test — though since D1's amendment that knowledge is no longer *another system's* job, it is
the knowledge index's; the environment arrives pre-built and the test command is frequently handed to the
scaffold, which removes most of the in-scope surface. Whatever substrate is chosen has to leave the
tribal-knowledge surface **exposed**, or arm C will be flat for a reason that says nothing about
Zikaron.

## 4. What the literature returned (2026-09-14, three briefs)

Notes: `research/memory-benchmark-landscape.md`, `research/coding-agent-experience-benchmarks.md`,
`research/agentic-eval-methodology.md`.

**No public benchmark measures Zikaron's construct.** None of the ten memory benchmarks surveyed
scores an end-task coding outcome; all are conversational, personal-assistant or long-context QA.
This corroborates D14 rather than offering a way around it.

**But two published results define the experiment better than any benchmark would.**

### 4.1 The negative result is the important one

**CTIM-Rover** (arXiv:2505.23422) built approximately Zikaron's thing — a **repo-scoped episodic
memory** for a code-repair agent — on AutoCodeRover, and it **hurt**: SWE-bench Verified resolution
fell **42% → 31%** on a 45-issue subset. That is an 11-point drop, comfortably outside the 2.2–6.0
point single-run spread measured for agent scaffolds, so it is a real effect rather than noise.

**This must not be read as "memory does not work", and it must not be waved away either.** The
reported mechanism is retrieval noise polluting exploration-stage decisions — and the memory in
question was *episodic traces of past repairs*, which is **code-structure knowledge — the category
D1's memory scope test excludes**. ~~So CTIM-Rover is, read carefully, evidence *for* Zikaron's
scope line rather than against it: it is the measured cost of storing the thing D1 refuses to
store.~~
**— that inference rested on a delegation that no longer exists, and is withdrawn 2026-09-22.**
It read a published negative result as vindication on the strength of D1 sending code knowledge
to *another system*; since the amendment, Zikaron ships that capability itself. What CTIM-Rover
actually measured is the cost of putting code knowledge in an **agent-written, consolidated,
episodic** store. Zikaron's knowledge index is **agent-read, unconsolidated, and returns file
fragments with line ranges** — three differences on the axes the paper blames. So the live
question is sharper than the old one and is not yet answered: *does that difference flip the
sign?* The proposed headline experiment below rests on the withdrawn reading and needs restating
before it is run.

That reframes the whole evaluation. The sharpest available experiment is not "does memory help?"
but:

> **Replicate CTIM-Rover's negative result, then test whether D1's scope discipline flips its
> sign.**

This is stronger than a bare A/B on three counts: it has a published baseline to compare against,
it tests **D1 — this project's foundational and least-tested decision** — directly, and it is
falsifiable in a way that is interesting whichever way it lands.

### 4.2 The protocol already exists

**ChainSWE** (arXiv:2607.02606) mines **304 issues across 54 Python repos** into chronological,
dependent chains *within one repository*, and compares a no-memory baseline against a
memory-carrying condition — the protocol hypothesised in §2, already built. Its chain-construction
methodology is reusable; its dependency definition needs a full-text read before it is trusted.

### 4.3 The purest scope match has no sequencing

Environment-setup benchmarks are what Zikaron's scope line literally describes — "get this
repository's test suite running" *is* tribal knowledge. **SetupBench** (93 tasks, 7 ecosystems),
**Installamatic** (40 Python repos), **ExecutionAgent** (CI-log ground truth), **EnvBench** (329
Python + 665 JVM). None runs repeated memory-connected attempts against the same repo; that
sequencing is ours to build. **EnvBench's best-known success is 6.69% / 29.47%**, which risks a
floor effect drowning any delta.

## 5. What the arithmetic permits — and the tension it exposes

From `research/agentic-eval-methodology.md`, for a **paired binary** resolve-rate design:

| Effect to detect | Paired instances needed | Three arms, at $1–5 and ~17.5 min each |
|---|---|---|
| 5 pp | ~600 | 1,800 runs, $1.8k–9k, 525 h serial |
| 10 pp | ~200 | 600 runs, $0.6k–3k, 175 h serial |
| 15 pp | ~100 | 300 runs, $0.3k–1.5k, 88 h serial |

(The instance counts are the assistant's own arithmetic, flagged unsourced; re-derive before
preregistering.)

**Two consequences, and the second is the awkward one.**

1. **A binary resolve-rate A/B can detect a CTIM-Rover-sized effect and cannot detect an
   AgentKB-sized one.** AgentKB (arXiv:2507.06229) reports the cleanest on-topic positive —
   OpenHands on SWE-bench, pass@1 **24.3% → 28.3%**. That is **+4.0 pp, which sits inside the
   2.2–6.0 pp single-run spread** that the randomness study measured over ~60k trajectories. Unless
   AgentKB averaged over seeds — not established by this pass, and worth checking before citing it
   — its headline number is not clearly distinguishable from run-to-run noise. **This inference is
   mine, by cross-referencing two briefs, and neither paper makes it.** It should be verified, not
   repeated as settled.
2. **The repo with enough instances is the repo where the effect is least likely to exist.**
   SWE-bench Verified's distribution is **django/django = 231 of 500 (46%)**, then sympy 75, sphinx
   44, matplotlib 34, scikit-learn 32, astropy 22, flask 1. So django is the *only* repo that
   supplies a within-repo sequence long enough for a ~10 pp binary detection — and django is also
   the most thoroughly pretrained-on repository in the set. `agentic-eval-methodology.md` records
   that **contamination suppressing a memory effect has no published treatment at all**: if a
   model already knows django's conventions from its weights, an external store of those
   conventions adds nothing. **Statistical power and construct sensitivity are in direct opposition
   here, and django maximises exactly the wrong one.**

This is the strongest argument in the whole pass for **not leading with SWE-bench**, and for
preferring a contamination-controlled substrate (SWE-bench-Live, post-cutoff instances) or a
corpus with no pretrained prior at all.

## 6. Proposed shape — three instruments, mapped onto §1's chain

Not one benchmark. One per class of claim, because §1 established that a single end-to-end number
cannot localise a null.

| Instrument | Links tested | Substrate | Status |
|---|---|---|---|
| **Sequential setup harness** | 1–4, end-task | SetupBench / Installamatic / ExecutionAgent, sequencing built by us | construct-valid core; **cheapest, run first** |
| **Scope ablation vs. CTIM-Rover** | 1–4, comparability | django/231 ordered, or SWE-bench-Live | external comparability; powered only for ≥10 pp |
| **Component instruments** | 5 (repair), 1 (write) | MemoryAgentBench `FactConsolidation`; HaluMem | isolates what no end-task benchmark can |

The ordering is deliberate and follows §2: the cheap construct-validity check runs before the
expensive comparability run, so a flat ceiling is discovered for the price of the small experiment.
