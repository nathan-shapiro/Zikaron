# What is "Jev", and could it judge tool calls in a behavioural-nudging hook?

> **Correction, 2026-09-24, to the brief this note was written against, not to its findings.** The
> brief supplied a "budgets already measured in tens of milliseconds" premise, which does not hold:
> no hook in this project has ever been budgeted or measured at that scale. `hook/connect.py` allows
> 300 ms to connect and 1.2 s to poll, `hook/push.py` 2.0 s, and M17 measured `surface` answering in
> 809–1348 ms. So the passages below reading Jev's ~400 ms p50 as "10–15x over budget" compare it to
> a figure with no source. The verdict is unchanged and the grounds are stronger: what rules out a
> per-tool-call judge is **frequency** — that cost is paid per tool call rather than once per user
> message — together with hosted-only deployment and the egress of `tool_input` on every call.
> Everything this note measured or cited stands as recorded.

## Brief (restated)

The operator named "Jev" (2026-09-24) as a public product that can cheaply and quickly classify
whether a rule was violated — the missing piece for a candidate M32 design: a `preToolUse` hook
(mechanism and teeth already verified on both harnesses) that has a cheap local judge decide
whether a tool call breaks a stated behavioural rule, then blocks (exit 2) or nudges (non-blocking
reminder). This sits **blocking on every tool call**, against latency budgets already measured in
tens of milliseconds. The brief asked for: identity, deployment shape, per-call latency, classifier
vs. generative, how rules are expressed, licence/distribution shape, and nudging support — plus a
survey of the guardrail-judge category more broadly, with safety/jailbreak guardrails flagged apart
from custom-policy engines.

## Bottom line

**Jev is real** — confirmed against the vendor's own site and independent third-party coverage —
but it is **hosted-API-only, with no self-host or open-weights option, and independently measured
latency of ~380–540 ms per call (p50–p95) over the network.** That is roughly one to two orders of
magnitude above the "tens of milliseconds" budget this hook has to live inside, and it cannot be
brought in-process the way `bge-small-en-v1.5-onnx-q` is. On the specific question asked — can Jev
itself sit in this hook — the answer is **no**, on latency and deployment shape alone, independent
of accuracy or cost. It is a **classifier with tunable, per-question confidence thresholds**
(useful shape for graded nudge/block), and rules are expressed as ad hoc natural-language yes/no or
choice "questions" per call rather than a persistent rule set (relevant to "how much work to add a
rule" — trivial per call, but there is no standing rule registry to point at).

## Identity and maturity

- **Jev is TypeSafe AI's flagship model**, described by the vendor as the first "System One model"
  — evaluates typed yes/no or choice "questions" against a state and returns structured
  answers with calibrated confidence, rather than generating text. Trained with a method the vendor
  calls "Reinforcement Learning for Calibrated Decisions (RLCD)." [TypeSafe AI blog, "Introducing
  System One Models & Jev"](https://typesafe.ai/blog/introducing-system-one-models-and-jev);
  [TypeSafe AI docs, Introduction](https://docs.typesafe.ai/introduction); [TypeSafe AI
  home](https://typesafe.ai/).
- **Maturity: very early access**, launched within days of when the operator named it — the
  vendor's own blog post and third-party coverage (MarkTechPost, Towards Data Science) are dated
  2026-09-23, one day before the operator's mention. [MarkTechPost, "A Coding Guide to TypeSafe AI
  Jev"](https://www.marktechpost.com/2026/09/23/a-coding-guide-to-typesafe-ai-jev/); [Towards Data
  Science, "A New Kind of Model for AI
  Decision-Making?"](https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/).
  The docs site explicitly says Jev is "available today in early access" (per TypeSafe AI blog,
  above). This is not a mature, multi-year product — treat every figure here as a snapshot of a
  week-old launch, not a settled baseline.
- It has picked up fast third-party adoption/coverage in days: a LangChain integration
  (`TypeSafeClassifier`) and blog post
  ([langchain.com/blog/building-a-harness-with-jev](https://www.langchain.com/blog/building-a-harness-with-jev)),
  an OpenRouter cookbook exposing it as `typesafe/jev-1.13` via OpenRouter's alpha "Decisions API"
  ([openrouter.ai/docs/cookbook/building-agents/gate-tool-calls-with-jev](https://openrouter.ai/docs/cookbook/building-agents/gate-tool-calls-with-jev)),
  and independent benchmarking write-ups (below). **Caveat**: at the time of this search, Jev did
  not appear in OpenRouter's public model list search (`openrouter.ai/models?q=jev` returned no
  hits), so the OpenRouter integration may be gated/alpha rather than generally available — treat
  the cookbook's "official documentation" status as real but the product as not yet broadly listed.

## Deployment shape — hosted only, no self-host

**This is the load-bearing fact for the brief.** TypeSafe AI's own blog says the "service is
currently based" on the US West Coast, references early-access sign-up and API keys
(`console.typesafe.ai`), and gives no mention anywhere of local, on-premises, or open-weight
deployment. [TypeSafe AI blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev).
The docs introduction likewise gives no self-host path. [TypeSafe AI
docs](https://docs.typesafe.ai/introduction). Every third-party integration found (LangChain, the
OpenRouter cookbook, the independent dev.to benchmark) calls it as a hosted API with an API key —
none run it locally. No GGUF/ONNX/safetensors artifact, no model size, and no licence terms are
published anywhere found. This rules Jev out for the specific "second pinned artifact alongside
`bge-small`" machinery the brief asks about — there is nothing to pin; it is a network call every
time.

## Per-classification latency

- **Vendor claim** (not independently verified by the vendor's own page): "end-to-end response time
  is 70ms–500ms," described as "40x–200x faster" than frontier LLM calls (vendor cites 3–329s for
  those). [TypeSafe AI blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev). No
  p50/p99 breakdown given at the source.
- **Independent measurement** (dev.to, "I Benchmarked Jev on Agent Tool-Call Risk. Calibration
  Held.", dated 2026-09-17, publishes a labeled 60-case dataset and states its methodology —
  client-side HTTP timing, residential Portland-OR network, same code path for every backend):
  **p50 421.6 ms / p95 542.0 ms for `jev-latest`; p50 378.5 ms / p95 484.3 ms for `jev-preview`.**
  The author is explicit that "network conditions are part of the measurement," flags run-to-run
  variance (93.3% vs 91.7% accuracy across runs) and the small n=60 sample size, and discloses no
  frontier-LLM baseline was run for comparison. This reads as a genuinely independent, methodologically
  honest benchmark rather than vendor-adjacent content. [dev.to /
  webofmike](https://dev.to/webofmike/i-benchmarked-jev-on-agent-tool-call-risk-calibration-held-49i3).
- A second write-up (LangChain's tutorial-style coverage) shows a **single call at 7 ms** claimed
  for one question with 57 input tokens versus **738 ms for ten calls run sequentially** (implying
  ~74 ms/call amortized when batched) — but this figure's provenance and measurement conditions are
  unclear from the fetched content, and it conflicts by an order of magnitude with the independent
  dev.to figures for what appears to be the same hosted endpoint, so it should be treated with
  suspicion rather than taken as a second confirmed data point.
  [langchain.com/blog/building-a-harness-with-jev](https://www.langchain.com/blog/building-a-harness-with-jev).
- **Reading for the brief**: taking the more rigorous independent figure (p50 ~380–420 ms, p95
  ~480–540 ms, network-dependent, hosted-only), a call on every tool call is **not viable** against
  a "tens of milliseconds" budget — it is roughly 10–15x over budget at p50 even before accounting
  for jitter, cold starts, or contention, and every call leaves the local machine, which this
  project's cost-measurement rule ("measure under the condition the budget was set for") explicitly
  warns against ignoring.

## Classifier vs. generative

Jev is **not** a free-text generative model — it answers a fixed, pre-declared set of typed
"questions" (three primitives per TypeSafe's docs: **Choice** — pick from a list, with
probabilities and confidence; **Score** — rate against a rubric; **Noul** — a boolean/0–1
probability) and returns structured probabilities rather than prose. [TypeSafe AI
docs](https://docs.typesafe.ai/introduction). This is the right *shape* for the brief's threshold-tunable
design (approve/review/block by probability cutoff — the OpenRouter cookbook shows exactly this
pattern: approve ≥0.9, block ≤0.1, review in between). The shape is good; the deployment and
latency are what disqualify it here.

## How rules are expressed

Rules are **per-call natural-language questions**, not a persisted rule registry: the caller sends
the current state plus a set of yes/no or choice questions phrased in plain language (e.g. "the
order ID matches the customer's message," "the situation qualifies under policy" —
OpenRouter cookbook example) in every request; there is no evidence of a standing rule set, DSL, or
training step to add a rule. Adding a "rule" is free (just phrase a new question) but there is no
persistence layer — the caller's own code owns the rule catalogue and re-sends it every call, which
is also consistent with the deployment being stateless and hosted.

## Licence and distribution shape

**Unresolved / not published anywhere found.** No open-weights release, no model size, no
architecture disclosure, no artifact format, no licence text. Pricing is metered
(`$0.042/M input tokens`, output described as "free, too cheap to meter" — TypeSafe AI blog), which
confirms it is a paid hosted service, not a redistributable artifact. This alone rules it out of
`design/distribution.md`'s pin-and-digest machinery, which requires an artifact to pin.

## The nudging half

Jev's confidence-scored output (probability per question) is naturally suited to a graded
approve/review/block scheme — this is the pattern shown in both the OpenRouter cookbook and the
vendor's own "confidence-gated action" framing (act when sure, escalate when not). It does not, on
current evidence, emit a free-text explanation or suggested correction alongside the score — the
outputs are typed values (choice, score, boolean-probability), not natural-language rationale, so
a "nudge" built on it would have to be templated from the question text and threshold band, not an
explanation string from the model itself.

## Category survey — guardrail/policy judges over agent tool streams

The brief's real question is whether *any* fast, cheap, local judge exists for this shape of
problem, independent of whether Jev specifically is it.

| Option | Local or hosted | Latency (published) | Rule expression | Safety/jailbreak vs custom policy |
|---|---|---|---|---|
| **Jev / TypeSafe AI** | Hosted only, no self-host | p50 ~380–420 ms, p95 ~480–540 ms (independent, network-bound); vendor claims 70–500 ms | Ad hoc NL questions per call, no persisted rule set | Neither — general decision/classification substrate, not safety-specific; but wrong deployment shape for a blocking hook regardless |
| **Llama Guard 3 (8B)** | Local (weights on Hugging Face) | CPU ~2–5 s/request — too slow for sub-100 ms budgets without GPU investment | Fixed taxonomy of harm categories (prompt-classifier), not free-form custom rules | Safety/jailbreak — wrong shape (judges harm categories, not project-specific working rules) |
| **Llama Guard 3-1B** (incl. INT4 variant) | Local | Markedly faster than 8B; no p50/p99 figure found, but described as the "latency" variant | Same fixed harm taxonomy | Safety/jailbreak |
| **ShieldGemma (2B / 9B)** | Local (open weights) | 2B is Google's stated "latency play" vs 9B; no independent p50/p99 found | Fixed policy templates for content-safety categories | Safety/jailbreak |
| **IBM Granite Guardian (38M HAP model up to 8B)** | Local (open weights, Hugging Face) | No independent latency figure found; the 38M `granite-guardian-hap-38m` variant is small enough to plausibly hit a tens-of-ms local budget but this is inference, not measurement, and needs benchmarking before it can be relied on. 5B is IBM's "balanced default"; "thinking" mode should be disabled in production for latency | Fixed risk taxonomy (harm, bias, jailbreak, groundedness) via prompts; not an arbitrary custom-policy DSL | Safety/jailbreak, though the family also covers hallucination/groundedness which is closer to custom-policy territory |
| **Invariant Labs / Invariant Guardrails** | **Can run fully locally** via the `invariant-ai` package and `LocalPolicy.from_string()`, or hosted via `INVARIANT_API_KEY` | No published latency figure found for the local path | **Custom policy DSL** — Python-inspired rules over agent traces, e.g. `(call: ToolCall) -> (call2: ToolCall)`, with allow/deny, argument constraints, cross-tool invariants, budgets, approval gates | **Custom policy** — closest fit in category to this brief's shape, since it is explicitly a rule-based (not model-judgement) layer over tool calls, and runs local |
| **NeMo Guardrails (NVIDIA)** | Local library, orchestrates rails (can call local or hosted models/rules) | Not benchmarked here; depends entirely on which rail model is plugged in | Colang DSL plus pluggable rails (can be rule-based or LLM-judged) | Framework, not itself safety- or policy-specific — the judgement is whatever model you plug in |
| **Lakera Guard** | Hosted SaaS (`api.lakera.ai/v2/guard`); Kong/gateway plugin form | Vendor claims **sub-50 ms** at "98%+ detection," but this is a vendor claim on the search snippet level, not independently verified here | Toggle-based defense categories, plus regex-based custom detectors for content moderation / data-leakage | Safety/jailbreak-leaning (prompt injection, content moderation), with limited custom-rule support via regex only |
| **llm-guard** | **Local, self-hosted library** (open source), cited as "the free self-hosted alternative to Lakera" | Not benchmarked here | Config-driven scanners (input/output), mostly fixed detector types rather than an open custom-policy DSL | Safety/jailbreak-leaning |

**Reading for the brief**: the only category entry with evidence of both (a) genuinely local
execution and (b) an explicit custom-policy rule language over *tool calls specifically* is
**Invariant Guardrails' local path** — worth a closer, dedicated look if this design direction is
pursued, since it is architecturally closer to "rule engine" than "model judge" (i.e., it may not
need an LLM/classifier in the loop at all for many rule shapes, which sidesteps the latency question
entirely). Everything named safety/jailbreak (Llama Guard, ShieldGemma, Granite Guardian's harm
categories, Lakera, llm-guard) judges a fixed taxonomy of harm/injection, not arbitrary
project-authored working rules — wrong shape for "did this tool call violate *our* stated rule,"
confirming the brief's suspicion that this distinction is blurred by marketing copy. None of the
locally-runnable small classifiers here has a *measured* tens-of-milliseconds figure in hand; that
would need to be benchmarked directly (e.g., `granite-guardian-hap-38m` via ONNX/llama.cpp on the
target machine) before it could be trusted for this design.

## Evidence quality notes

- Jev's existence and core facts (hosted-only, no self-host, RLCD training, three-primitive output
  shape, early-access status) are corroborated across the vendor's own site/docs and at least three
  independent third parties (dev.to benchmark, MarkTechPost, LangChain), which is reasonably strong
  triangulation for a week-old product.
- The initial web search returned a large number of low-quality, SEO-farm-style pages about Jev
  (jev.pro, ayautomate.com, cloudraft.io, refix.ai, penligent.ai, archestra.ai, superpowerdaily.com,
  various MCP-server listing sites) with garbled or inconsistent terminology ("Noul", "T_VIOLATION")
  in their auto-summarized snippets. These were **not used as sources** in this note; only the
  vendor's own site/docs, LangChain's blog, the OpenRouter cookbook, and the dev.to independent
  benchmark were fetched and quoted. The volume and low quality of that surrounding content-farm
  activity is itself worth flagging: it suggests the topic attracted rapid programmatic-SEO
  coverage within days of launch, which inflates apparent "buzz" without adding evidence.
- No independently-run latency benchmark exists for the local guardrail models in the table beyond
  qualitative "1B/2B/38M is the latency variant" statements from the vendors — those numbers are
  inferred/reported secondhand from search snippets (Turing Post, VentureBeat, Medium) rather than
  fetched and verified against primary sources; treat the category table's latency column as
  directional, not decisive, except for Jev (independently measured) and Llama Guard 8B (CPU
  latency figure sourced from a benchmark review page, not independently re-verified here either).

## Open questions / leads not pursued

- Whether Invariant Guardrails' local path has any published latency figures — worth a follow-up
  fetch of `invariantlabs-ai.github.io/docs/mcp-scan/guardrails-reference/` or the `invariant-ai`
  PyPI package docs directly.
- Whether `granite-guardian-hap-38m` or a similarly small encoder-only classifier can be benchmarked
  directly on this project's target hardware to get a real tens-of-milliseconds figure — this is
  the most promising unexplored lead for a genuinely local, fast judge, but nothing found here
  measures it.
- Whether OpenRouter's alpha "Decisions API" / `typesafe/jev-1.13` listing is generally available or
  still gated — the model didn't appear in OpenRouter's public model search at time of writing,
  which is inconsistent with the cookbook page being live; not resolved.

## Search queries used

1. `Jev AI classify rule violation guardrail`
2. `"Jev" AI policy classifier tool calls agent`
3. `"TypeSafe AI" jev model site:typesafe.ai OR "typesafe.ai"`
4. (WebFetch) `openrouter.ai/models?q=jev`
5. (WebFetch) `typesafe.ai/blog/introducing-system-one-models-and-jev`
6. (WebFetch) `docs.typesafe.ai/introduction`
7. (WebFetch) `marktechpost.com/2026/09/23/a-coding-guide-to-typesafe-ai-jev/`
8. (WebFetch) `dev.to/webofmike/i-benchmarked-jev-on-agent-tool-call-risk-calibration-held-49i3`
9. `Llama Guard 3 latency ms local inference classifier`
10. `Invariant Labs guardrails agent tool call policy DSL local`
11. `ShieldGemma Granite Guardian IBM latency local model size`
12. `Lakera Guard latency ms API llm-guard local library custom policy rules`

## Sources

1. [TypeSafe AI — Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) (vendor blog, 2026-09-23)
2. [TypeSafe AI — Docs Introduction](https://docs.typesafe.ai/introduction) (vendor docs)
3. [TypeSafe AI — Home](https://typesafe.ai/) (vendor site)
4. [MarkTechPost — A Coding Guide to TypeSafe AI Jev: Typed Decisions, Calibrated Confidence, and Speculative Fan-Out with a System One Model](https://www.marktechpost.com/2026/09/23/a-coding-guide-to-typesafe-ai-jev/) (2026-09-23)
5. [Towards Data Science — A New Kind of Model for AI Decision-Making?](https://towardsdatascience.com/a-new-kind-of-model-for-ai-decision-making/)
6. [LangChain — What Is Jev? A Guide to TypeSafe AI's System One Model](https://www.langchain.com/blog/building-a-harness-with-jev)
7. [OpenRouter Cookbook — Gate Agent Tool Calls with Jev](https://openrouter.ai/docs/cookbook/building-agents/gate-tool-calls-with-jev)
8. [dev.to (webofmike) — I Benchmarked Jev on Agent Tool-Call Risk. Calibration Held.](https://dev.to/webofmike/i-benchmarked-jev-on-agent-tool-call-risk-calibration-held-49i3) (2026-09-17, independent)
9. [OpenRouter — Models search for "jev"](https://openrouter.ai/models?q=jev) (no results at time of check)
10. [GitHub — invariantlabs-ai/invariant: Guardrails for secure and robust agent development](https://github.com/invariantlabs-ai/invariant)
11. [Invariant Labs — Introducing Guardrails: The contextual security layer for the agentic era](https://invariantlabs.ai/blog/guardrails)
12. [Invariant Labs — Advanced Guardrails / MCP-Scan Documentation](https://invariantlabs-ai.github.io/docs/mcp-scan/guardrails-reference/)
13. [ibm-granite/granite-guardian-hap-38m — Hugging Face](https://huggingface.co/ibm-granite/granite-guardian-hap-38m)
14. [IBM — Granite Guardian docs](https://www.ibm.com/granite/docs/models/guardian)
15. [Turing Post — Guardian Models: Llama Guard, ShieldGemma & DynaGuard](https://www.turingpost.com/p/guardianmodels)
16. [Llama Guard Benchmark Review: Real Performance vs. Vendor Claims — AI Moderation Tools](https://aimoderationtools.com/posts/llama-guard-benchmark-review/)
17. [arXiv — Llama Guard 3-1B-INT4: Compact and Efficient](https://arxiv.org/pdf/2411.17713)
18. [Kong Docs — AI Lakera Guard Policy](https://developer.konghq.com/ai-gateway/policies/ai-lakera-guard/)
19. [Lakera API docs — Guard API Endpoint](https://docs.lakera.ai/docs/api/guard)

Not used as sources (low-quality/inconsistent content-farm pages found in initial search, excluded
per the brief's instruction not to speculate): jev.pro, ayautomate.com, cloudraft.io, refix.ai,
penligent.ai, agent.nexus, archestra.ai (used only for category framing awareness, not quoted),
superpowerdaily.com, various MCP-listing aggregator sites (Glama, LobeHub).
