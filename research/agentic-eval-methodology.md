# Agentic A/B evaluation methodology for a memory system on coding tasks

## Brief

Zikaron plans an A/B: run a coding agent over a sequence of tasks from the same repository twice
— memory live vs. memory absent — and measure whether the memory arm resolves more tasks. This
project preregisters benchmarks and treats "it feels better" as a non-result (`CLAUDE.md`), so the
question is what is needed for the A/B to be *valid* before it is run: (1) run-to-run variance of
coding agents on SWE-bench-style evals, to size a detectable effect; (2) the right statistical test
and sample size; (3) contamination, in both directions — inflated baselines and *suppressed*
memory effect; (4) SWE-bench's construct-validity critiques; (5) leakage between tasks within a
memory A/B; (6) what counts as a fair no-memory control; (7) cost per instance, to size a budget.

## Method

Five search rounds (WebSearch), two WebFetch attempts (one blocked by a 403, one returned an
unparseable PDF and is flagged as unverified below). Prioritized arXiv preprints, vendor blog posts
(OpenAI), and benchmark repositories. No Zikaron-internal files were consulted or altered; this note
is written purely from external literature per the brief's method.

**A caution about the corpus itself.** Several sources returned by search carry very recent-looking
identifiers (e.g. "GPT 5.5", "Claude Opus 4.7", "DeepSeek-V4", arXiv ids in the 2602–2607 range,
dated in early-to-mid 2026) that are outside anything independently checkable by this agent. They
are reported below as found, with the identifier attached, so the researcher can judge their
plausibility; nothing here should be taken as confirmed beyond "a search engine returned it."

---

## 1. Run-to-run variance of coding agents

**Best source found:** "On Randomness in Agentic Evals" (arXiv:2602.07150). Collected ~60,000
agentic trajectories on SWE-bench-Verified across three models and two scaffolds and reports:

- Single-run pass@1 estimates vary by **2.2–6.0 percentage points** depending on which run is
  selected, with **standard deviations exceeding 1.5 points even at temperature 0**.
- Concrete per-config numbers quoted: DeepSWE-preview on a "nano-agent" scaffold at temperature 0,
  **20.4% ± 1.0%** (range 18.2–21.4%); Qwen3-32B on R2E-Gym, **22.3% ± 1.8%** (range 19.8–25.2%).
- The mechanism: even "deterministic" temperature-0 settings are not deterministic in practice —
  floating-point non-associativity, batching, and inference-engine scheduling all introduce
  variance. This generalizes a point made earlier by "Non-Determinism of 'Deterministic' LLM
  Settings" (arXiv:2408.04667), which is about single-model-call sampling rather than full agent
  trajectories but is the underlying mechanism.
- A companion data point from a different paper (SWE-Edit, arXiv:2604.26102) reports a 72.0 vs.
  69.9 resolve-rate gap between two configurations and argues this gap "is much larger than either
  configuration's per-run standard deviation" — i.e. a worked example of a comparison the authors
  judged real, given their own variance estimate.

**What this means for sizing Zikaron's A/B.** Take ±1.5–3 points of SD as the working floor for
run-to-run noise on this class of benchmark, and note it was measured on trajectory counts in the
thousands, not on a 50-instance slice — noise on a *small* slice (Zikaron's likely regime, since the
plan is same-repo task sequences rather than the full 500-instance Verified set) should be assumed
**larger**, not smaller, because per-instance variance does not average down until n is large. A
4-point apparent memory gain on a 50-instance run is not distinguishable from the noise floor these
papers measured on a much larger corpus; it is not distinguishable from noise on a small one either,
without either (a) many repeated runs per arm to estimate the local variance directly, or (b) a
paired design (§2) that removes between-instance variance rather than between-run variance.

**Open gap:** no source found reports run-to-run variance for a *paired, same-instance* design with
a stateful memory component in the loop (the exact case here). All the above is variance in
*independent* replications of the same static task; a memory arm changes state across the sequence,
which is a different variance source not covered by any paper found. This must be measured directly
(e.g. repeat the no-memory arm N times to get a same-instance noise floor before trusting a
single-run memory-vs-no-memory delta).

## 2. Statistical power and the right test

**Test choice.** For a paired design (same task instances, two arms), the standard treatment for
paired binary outcomes (resolved/not resolved) is **McNemar's test on the discordant pairs** — cases
where the two arms disagree on that instance. [rcompanion's summary](https://rcompanion.org/handbook/H_05.html)
confirms this is the standard reference for paired nominal (2×2) data; the exact binomial form is
used when discordant-cell counts are small (<25 is the commonly cited threshold), the chi-square
approximation otherwise. A general-agent-evaluation paper found in search (arXiv:2602.22953,
"General Agent Evaluation") reports using "paired McNemar tests on binary success outcomes for
shared benchmark and task pairs," with Benjamini–Hochberg/Benjamini–Yekutieli or Holm–Bonferroni
correction for multiple comparisons — direct precedent for the design contemplated here. It also
notes that "at sample sizes typical in agent evaluation (n≈100 per benchmark), within-benchmark
comparisons can remain noisy" even when cross-model differences are large — i.e. the paired test
does not rescue an underpowered slice by itself.

**Do published agent evals report significance at all?** Rarely. Leaderboards (SWE-bench, HAL) and
most agent papers found in this search report a single pass@1 / pass@k number per configuration with
no confidence interval or paired test; "On Randomness in Agentic Evals" (§1) exists specifically
because this gap was noticed. Treat significance testing as **not the norm** in this literature —
which argues for Zikaron doing it anyway rather than following field convention, since the brief
already commits to a preregistered, defensible design.

**Rough sample-size arithmetic (worked here, not sourced — no paper gave sample-size tables for this
exact case).** A standard approximation for McNemar-test power (Connor 1987; used widely in applied
biostatistics) ties required total n to the *discordance rate* π_d (fraction of instances where the
two arms disagree) and the target difference δ between the two discordant-cell proportions:

```
n ≈ (z_{α/2} + z_β)^2 * π_d / δ^2      (two-sided α=0.05, power=0.80 → z sum ≈ 2.80, squared ≈ 7.84)
```

Because π_d is unknown until piloted, three illustrative scenarios (assuming π_d rises loosely with
the target δ, which is typical — bigger true effects tend to produce more disagreement):

| Target gap (δ) | Assumed discordance π_d | Approx. n needed |
|---|---|---|
| 5 pp | 0.20 | ~627 instances |
| 10 pp | 0.25 | ~196 instances |
| 15 pp | 0.30 | ~104 instances |

These are illustrative, not measured — the discordance-rate assumption is the load-bearing unknown
and should be replaced with a pilot estimate before trusting the resulting n. The qualitative
conclusion is robust to the exact assumption, though: **detecting a 5-point gain needs several
hundred paired instances**, well beyond what a same-repository task sequence is likely to supply
without many repeated task families; a 10–15 point gain is plausible to detect on a few hundred
instances, which is closer to SWE-bench-Verified's full 500-instance scale, not a 50-instance slice.
An unpaired two-proportion-test version of the same arithmetic (ignoring the pairing entirely) gives
n≈1,466 per arm for a 5-point gap at baseline 35–40% — confirming the paired design is not optional,
it is the only way this becomes remotely tractable at plausible sample sizes.

**Bootstrap alternative.** A nonparametric bootstrap over paired instances (resample instance pairs
with replacement, recompute the resolve-rate difference, repeat) is a reasonable complement or
alternative to McNemar — it does not require the exact-binomial small-sample correction and directly
yields a CI on the difference, which is arguably more useful to report than a p-value alone, and
several agent-eval papers use CIs framed this way in place of or alongside a formal test.

## 3. Contamination

**"The SWE-Bench Illusion" (arXiv:2506.12286, Liang et al.).** Diagnoses memorization via a file-path
identification probe: models identify the buggy file from the issue description alone with up to
**76% accuracy on SWE-bench instances**, dropping to at most **53% on structurally similar tasks from
repositories not in SWE-bench** — direct evidence that some fraction of apparent "reasoning"
performance is repository/instance familiarity from pretraining rather than issue comprehension.

**SWE-bench+ (Aleithan et al. 2024)**, per the search summary, manually screened issue text/comments
for solution leakage and found **32.67% of successful patches involved direct solution presence** in
the issue thread itself — a distinct and more mundane contamination channel (leakage in the *prompt*,
not the *weights*).

**Vendor-side corroboration.** Per search results: OpenAI has stopped reporting SWE-bench Verified
scores, and Anthropic's Opus 4.7 release notes reportedly describe screening SWE-bench
Verified/Pro/Multilingual for instances showing memorization signs before evaluating on them — both
are third-party-summarized claims from this search round and were not independently verified against
the primary release notes; treat as plausible but unconfirmed pending a direct read of Anthropic's
release notes.

**OpenAI's own stated reasons for retiring SWE-bench Verified** (from search of
`openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/` — the WebFetch to this page 403'd,
so this is search-snippet-only and should be re-verified by a direct read before being quoted
further): reported figures include **38.3% of samples flagged for underspecified problem
statements**, and a claim that **>60% of remaining problems are unsolvable** (49 tests judged too
narrow, rejecting functionally correct submissions; 26 judged too wide, requiring unstated features),
plus a claim that "all frontier models tested were able to reproduce the original human-written bug
fix," offered as contamination evidence. **These numbers are flagged as unverified** — the search
tool's synthesis may have blended OpenAI's post with a different critique paper found in the same
round; do not cite the specific percentages without a direct fetch of the primary source once network
access to openai.com is available.

**Contamination-controlled alternatives found:**
- **SWE-bench-Live** ([microsoft/SWE-bench-Live](https://github.com/microsoft/SWE-bench-Live),
  paper "SWE-bench Goes Live!", arXiv:2505.23419) — continuously updated monthly from fresh
  post-2024 GitHub issues, 1,319 tasks across 93 repos at initial release, explicitly built to resist
  contamination by construction (instances postdate any fixed training cutoff at time of use).
- **SWE-smith** — referenced as a related toolkit for *generating* training/eval data rather than a
  fixed contamination-resistant set itself; treat as a data-construction pipeline, not a benchmark
  to point at directly.

**The subtler direction that matters most to Zikaron — contamination *suppressing* the memory
effect — is not addressed by any source found.** Every contamination paper located argues in one
direction only: that memorized solutions **inflate** baseline scores. None discusses the converse
that matters here — if a model's pretraining already encodes a repository's conventions (because
that repository, or repos like it, are well-represented in training data), an external memory
record of "this project's convention is X" is *redundant* with what the model already knows, and a
memory A/B on a well-known/public repository will *understate* the value memory would add on a
private or novel one. **This is a genuine literature gap** — plainly stated as such rather than
inferred from silence — and is a first-order design implication for Zikaron: the A/B should
deliberately be run on a repository (or task family) the base model is unlikely to have strong
memorized priors about, since a famous open-source SWE-bench-style repo is close to worst-case for
demonstrating memory's marginal value, for reasons orthogonal to whether memory works.

## 4. Construct validity of SWE-bench generally

Beyond the contamination critique in §3, the "SWE-bench Verified" construction rationale itself
(OpenAI, per [swebench.com/verified.html](https://www.swebench.com/verified.html) and the original
[Introducing SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/) post) was
a response to an earlier round of construct-validity concerns: human annotators screened the
original SWE-bench test set for improperly scoped `FAIL_TO_PASS` unit tests and underspecified issue
text, filtering to instances judged solvable and well-specified. That Verified itself later drew the
same class of criticism (§3, OpenAI's own walk-back) is the relevant lesson for Zikaron: **"Verified"
is not a settled ground truth, it is one round of human filtering that a later, more adversarial
round found still wanting.** A separate related paper, "SWE-ABS: Adversarial Benchmark Strengthening
Exposes Inflated Success Rates on Test-based Benchmark" (arXiv:2603.00520), was surfaced by search
under a cost-related query and appears to bear directly on this (test-based pass/fail as an
unreliable correctness proxy) but was not fetched and read in this pass — worth a follow-up read
before relying heavily on pass/fail as the sole outcome metric.

## 5. Cross-task leakage within a memory A/B

**No source found that directly and rigorously controls for this in a coding-agent memory
evaluation.** The closest hits:

- "Learning on the Job: Continual Learning from Deployment Feedback for Frozen-Weights Agents"
  (arXiv:2607.22157) — title and search summary suggest exactly the relevant setup (memory persists
  across a task sequence), but the WebFetch of the PDF returned unparseable binary content, so its
  actual leakage-control methodology is **unread and unverified**. This is a concrete lead the
  researcher should re-fetch directly rather than trust this note's characterization.
- "SWE-Exp: Experience-Driven Software Issue Resolution" (arXiv:2507.23361) — also directly on
  point by title (an experience/memory store used across SWE-bench-style issues) but not fetched in
  this pass; a leading candidate for a close read on exactly this question.
- The general framing found via search — "a trigger-probe protocol evaluates a fixed probe set
  against read-only memory snapshots at varying prefix lengths, together with a NullMemory
  counterfactual baseline" and "temporal memory contamination" as a named failure mode in a memory-
  security survey (arXiv:2604.16548, arXiv:2605.17830) — establishes that the *concept* of
  cross-task memory contamination is named in the security literature (there, framed as an attack
  surface: an earlier task's memory poisoning a later, unrelated task's behavior), but these papers
  are about adversarial safety, not about controlling for it as a benign confound in a resolve-rate
  A/B.

**What follows for Zikaron's design, stated as a gap this literature does not fill:** if Zikaron's
task sequence is drawn from one repository's real issue history, adjacent tasks are likely to share
files, subsystems, or even be sequential fixes to the same bug class — exactly the condition under
which a memory record written for task N would trivially help task N+1 for reasons that have nothing
to do with the memory system doing anything clever. No published methodology was found for
neutralizing this. Candidate controls, not sourced from literature (i.e., these are this note's own
suggestions, to be labeled as such rather than as established practice): (a) randomize or otherwise
decorrelate task order across repeated runs so file/subsystem overlap between consecutive tasks is
not systematically exploitable; (b) report overlap statistics (shared files, shared issue vocabulary)
between task pairs and check whether the memory arm's wins concentrate on high-overlap pairs, which
would be diagnostic of leakage rather than of memory quality; (c) a held-out task family with zero
file overlap with any earlier task, as a leakage-free subset of the result.

## 6. Fair baselines

**No source found does a controlled comparison of "tools absent" vs. "tools present but empty" vs.
"tools present with irrelevant content"** for a coding-agent memory system specifically. The nearest
evidence is generic, not memory-specific:

- Context-engineering literature (search round on "tool presence" confounds) documents that **merely
  having many tools available** degrades agent behavior independent of whether they are used —
  described under names like "context confusion" or "tool overload" in vendor/practitioner writeups
  (LangChain's context-engineering docs, Anthropic-adjacent context-engineering blog posts found via
  search). This is folklore-adjacent — practitioner-reported, not a controlled study with numbers —
  but it is a real and directly relevant confound: **adding a search/write tool to the memory arm
  that has no equivalent in the no-memory arm changes the tool-choice distribution and possibly the
  model's behavior even before any memory content is read.** "Memory-Induced Tool-Drift in LLM
  Agents" (arXiv:2605.24941) was surfaced by search under this exact framing and appears to name this
  phenomenon directly by title; **not fetched in this pass** — a strong candidate for a close read,
  since it may already quantify the effect Zikaron needs to rule out.
- No source addresses prompt-position confounds (Zikaron's own push mechanism places memory content
  early in context — see `design/retrieval.md` and FINDINGS open question 4's note that push
  placement contradicts a "surface memories late" lesson from a sibling project) as a factor
  independent of memory content, in the SWE-bench-agent literature specifically. The broader
  "lost in the middle" / context-position literature exists (not searched in this pass, out of
  scope for this brief but a known adjacent literature) and should be treated as informative context
  once this A/B design gets to specifying where memory is injected.

**Recommendation, not sourced from a paper but derivable from the above:** the honest no-memory
control is **tools present, store empty** (or a store seeded with topic-irrelevant records of
matched volume/length), not **tools absent entirely** — because "tools absent" confounds "no memory
content" with "no memory-shaped tool-affordance at all," and the tool-drift/tool-overload literature
above says that affordance alone can move behavior. An "irrelevant-content" arm (matched token
volume, wrong topic) is the more rigorous control if the tool-affordance and content-value effects
need to be separated; a "tools absent" arm is a weaker, cheaper control that answers a coarser
question ("does the system as shipped help") rather than the mechanism question.

## 7. Cost per instance

Figures found (search only, not independently fetched — treat as indicative, and note the model
names are recent/unfamiliar to this agent and unverifiable):

- A 350-instance run: **GPT-5.5 at $1,399.10 total** (~$4/instance); **Claude Opus 4.7 at
  $1,082.00 total** (~$3.09/instance); **DeepSeek-V4 Pro at $81.30 total** (~$0.23/instance,
  71.7% pass@1 claimed); **DeepSeek-V4 Flash at $8.20 total** (~$0.02/instance, 70.3% pass@1
  claimed) — source: search summary of an unnamed benchmarking paper, exact citation not captured
  cleanly by the search tool; needs a direct source check before being quoted in a budget document.
- **GPT-5, per-instance cost ≈ $2.50**; DeepSeek-V3 API cost ≈ **$0.13/instance** — again
  search-summary only.
- Wall-clock: **~18.5 minutes/instance** in one study, **~15m49s/instance** in another.
- A general caution surfaced directly and worth keeping: "output tokens, wall-clock duration, and
  dollar cost per trial all vary by an order of magnitude across agents... but none correlates
  strongly with pass rate" — i.e. cost is not a reliable proxy for capability, and a cheap scaffold
  is not necessarily a worse one for this purpose.

**A more citable, independently-known source not fully explored in this pass:** the **Holistic
Agent Leaderboard (HAL)** (arXiv:2510.11977, surfaced by search) is explicitly built to report
cost/latency alongside accuracy for agent benchmarks including SWE-bench-style tasks and is a
better primary source for budget figures than the scattered numbers above; it was not fetched in
this pass and is the strongest lead for a follow-up read before finalizing a token/dollar budget.

**Rough usable rule of thumb for budgeting, stated with the caveat above:** on the order of
**$1–5 and 15–20 minutes per instance** for a competent frontier-model scaffold on SWE-bench-style
tasks, an order of magnitude less for smaller/cheaper models. At the n≈100–600 range implied by
§2's power arithmetic, a two-arm, single-run design costs on the order of **$200–$6,000 and
50–400 agent-hours** depending on instance count and model choice — wide enough that the actual
model/scaffold choice matters more to feasibility than anything else in this note, and should be
fixed before committing to an instance count.

---

## Synthesis of what is known vs. folklore vs. unmeasured

**Measured, with numbers:** run-to-run variance at temperature 0 (§1, arXiv:2602.07150); the
file-path-identification contamination probe (§3, arXiv:2506.12286); SWE-bench+ solution-leakage
rate (§3, "32.67%," provenance not independently re-verified); McNemar as the standard paired test
(§2, general statistics reference plus one agent-eval paper using it in practice).

**Folklore / practitioner-reported, not a controlled study:** tool-presence/tool-overload effects on
agent behavior independent of content (§6); most cost figures (§7, search-summary only, several
unverifiable model names).

**Genuine literature gaps, stated plainly:**
- Contamination *suppressing* a memory-system's measurable effect (the direction that matters most
  to Zikaron) — not addressed anywhere found (§3).
- Cross-task leakage control specific to a memory A/B on sequential real-world issues — named as a
  concept in adjacent safety literature (temporal memory contamination) but not solved for a benign
  resolve-rate evaluation (§5).
- Sample-size guidance specific to a paired memory-vs-no-memory coding-agent design — none found;
  §2's table is this note's own arithmetic from a general McNemar power formula, not a sourced
  result, and rests on an unmeasured discordance-rate assumption.
- A controlled separation of "tool affordance present" from "tool content useful" for a memory
  system specifically (§6) — the closest candidate, "Memory-Induced Tool-Drift in LLM Agents"
  (arXiv:2605.24941), was found but not read in this pass.

## Leads for a follow-up pass (not yet read, ranked by relevance)

1. **arXiv:2605.24941**, "Memory-Induced Tool-Drift in LLM Agents" — likely the single best next
   read for §6.
2. **arXiv:2607.22157**, "Learning on the Job: Continual Learning from Deployment Feedback for
   Frozen-Weights Agents" — re-fetch as HTML/abstract rather than PDF; likely bears on §5 directly.
3. **arXiv:2507.23361**, "SWE-Exp: Experience-Driven Software Issue Resolution" — likely bears on
   §5 and possibly §6.
4. **arXiv:2510.11977**, Holistic Agent Leaderboard — best source to firm up §7's cost figures.
5. Direct fetch of `openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/` once network
   access permits (the 403 in this pass may be transient or environment-specific) — needed to
   confirm or correct the 38.3%/60% figures in §3/§4, which are currently search-snippet-only.
6. **arXiv:2603.00520**, "SWE-ABS: Adversarial Benchmark Strengthening" — bears on §4's pass/fail
   reliability point.

## Search queries used

1. `SWE-bench run-to-run variance nondeterminism resolved rate temperature 0`
2. `SWE-bench illusion contamination memorization arxiv`
3. `McNemar test agent evaluation paired significance testing benchmark sample size`
4. `SWE-bench Verified construction methodology unsolvable underspecified OpenAI`
5. `cost per SWE-bench instance tokens dollars agent scaffold wall clock`
6. `SWE-bench-Live SWE-smith contamination-free continuously updated instances`
7. `agent memory experiential learning coding tasks evaluation leakage cross-task contamination "memory" ablation empty store baseline`
8. `extra tool in context changes LLM agent behavior regardless of content prompt position confound`
9. WebFetch: `https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/` (403, failed)
10. WebFetch: `https://arxiv.org/pdf/2607.22157` (returned unparseable binary, failed)

## Sources

1. [On Randomness in Agentic Evals](https://arxiv.org/html/2602.07150) — arXiv:2602.07150
2. [Non-Determinism of "Deterministic" LLM Settings](https://arxiv.org/html/2408.04667v5) — arXiv:2408.04667
3. [SWE-bench Goes Live!](https://arxiv.org/pdf/2505.23419) — arXiv:2505.23419 (SWE-bench-Live)
4. [SWE-Edit: Rethinking Code Editing for Efficient SWE-Agent](https://arxiv.org/pdf/2604.26102) — arXiv:2604.26102
5. [The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason](https://arxiv.org/abs/2506.12286) — arXiv:2506.12286, Liang et al.
6. [SWE Atlas: Benchmarking Coding Agents Beyond Issue Resolution](https://arxiv.org/pdf/2605.08366) — arXiv:2605.08366
7. [McNemar Test and Tests for Paired Nominal Data — rcompanion handbook](https://rcompanion.org/handbook/H_05.html)
8. [General Agent Evaluation](https://arxiv.org/pdf/2602.22953) — arXiv:2602.22953
9. [Why SWE-bench Verified no longer measures frontier coding capabilities — OpenAI](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/) (fetch blocked, search-snippet only)
10. [Introducing SWE-bench Verified — OpenAI](https://openai.com/index/introducing-swe-bench-verified/)
11. [SWE-bench Verified — swebench.com](https://www.swebench.com/verified.html)
12. [SWE-bench-Live — microsoft/SWE-bench-Live (GitHub)](https://github.com/microsoft/SWE-bench-Live)
13. [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers](https://arxiv.org/html/2603.07670v1) — arXiv:2603.07670
14. [A Survey on the Security of Long-Term Memory in LLM Agents: Toward Mnemonic Sovereignty](https://arxiv.org/html/2604.16548v1) — arXiv:2604.16548
15. [Remembering More, Risking More: Longitudinal Safety Risks in Memory-Equipped LLM Agents](https://arxiv.org/html/2605.17830v1) — arXiv:2605.17830
16. [Learning on the Job: Continual Learning from Deployment Feedback for Frozen-Weights Agents](https://arxiv.org/pdf/2607.22157) — arXiv:2607.22157 (PDF unreadable in this pass)
17. [SWE-Exp: Experience-Driven Software Issue Resolution](https://arxiv.org/pdf/2507.23361) — arXiv:2507.23361 (not read this pass)
18. [Memory-Induced Tool-Drift in LLM Agents](https://arxiv.org/pdf/2605.24941) — arXiv:2605.24941 (not read this pass)
19. [Holistic Agent Leaderboard: The Missing Infrastructure for AI Agent Evaluation](https://arxiv.org/pdf/2510.11977) — arXiv:2510.11977 (not read this pass)
20. [SWE-ABS: Adversarial Benchmark Strengthening Exposes Inflated Success Rates on Test-based Benchmark](https://arxiv.org/pdf/2603.00520) — arXiv:2603.00520 (not read this pass)
21. [Context engineering in agents — Docs by LangChain](https://docs.langchain.com/oss/python/langchain/context-engineering)
