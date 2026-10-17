# Kiro autonomous agent: what AWS's own material says (memory, verification, supervision, results)

Search date: 2026-10-14. Light, curiosity-level brief; not a full literature pass.

## Brief, restated

What do AWS/Kiro primary sources say about the Kiro autonomous agent (announced at re:Invent, 2025-12-02), narrowly on: (1) memory and context across tasks and sessions (what, scope, how it decides, user visibility/edit/delete); (2) how it verifies its own work (compare kiro-cli `/goal`); (3) invocation and supervision (background, multi-repo, parallel, duration, human checkpoints); (4) measured results, labelled as vendor self-report. Plus current status as of today.

## Source labels used below

- VD = vendor documentation (kiro.dev/docs)
- VB = vendor blog / changelog / press release (kiro.dev blog or changelog, aws.amazon.com blog, press.aboutamazon.com)
- 3P = third party

Quote caveat: WebFetch returns a small-model reading of each page, not raw text. Phrases in quotation marks are as relayed by that tool, kept under ~25 words, and were re-requested verbatim for the two load-bearing pages (the launch blog and the case study). Everything else is a faithful paraphrase; treat unquoted detail as "reported by the fetch, not byte-checked".

## 1. Status as of 2026-10-14 (the product has been folded into "Kiro Web")

- 2025-12-02: announced at re:Invent as one of three "frontier agents" (with AWS Security Agent and AWS DevOps Agent). Launch blog says preview, free during preview, "usage is subject to weekly limits"; Pro, Pro+, Power subscribers; teams on a waitlist. [1][2]
- 2026-05-07: "Kiro Web (Preview)" launched at app.kiro.dev; the autonomous agent is one of its modes. [3]
- 2026-05-29: the launch blog carries an update note that the autonomous agent "is now available on Kiro Web (Preview) as a new autonomous mode". [1]
- 2026-09-01: changelog "Kiro Web Is Now Generally Available". The entry is two sentences and does not mention the autonomous agent or the preview. [4]
- Current docs (VD): Kiro Web is available on Pro, Pro+, Pro Max and Power; requires AWS IAM Identity Center, Okta or Microsoft Entra ID; cloud sessions in us-east-1 only; three modes (default/collaborative, Spec, autonomous). The FAQ says "All three modes (autonomous, spec, and default) are available together in Kiro Web." [5][6]
- **My inference (flagged):** autonomous mode is therefore GA as part of GA Kiro Web. No source says "the autonomous agent is GA" in so many words. The original launch blog page still reads as preview/waitlist and has not been rewritten for GA. [1]
- Separate, adjacent product: **Kiro Crew**, described as open source, "persistent, self-learning", GA, runs locally or on your own hardware with Slack/Discord/etc. channels. The Crew landing page positions it as complementary to Kiro Web's autonomous capability, not the same thing. [7] Do not conflate its memory docs with the autonomous agent's (section 2.3).

## 2. Memory and context across tasks and sessions

### 2.1 What the launch material claims (VB)

- "it remembers and applies those patterns to future work automatically": the claim for PR feedback. [1]
- "the agent gets better at understanding your code, your products, and the standards you follow". [1]
- "The team agent weaves together specs, discussions, and pull requests into a unified memory": the only team-scope statement, and it is a sentence of positioning, not a mechanism. [1]
- Kiro Web (Preview) announcement: users can "teach the agent through PR comments", and feedback "carries forward to future work across all your repositories". That is user-level scope across repos, not per-repo. [3]
- Autonomous-mode doc: comments such as "always use our standard error handling" help the agent "learn and apply those patterns to future work". [8] The same doc was reported by the fetch as not covering memory mechanisms.
- AWS News Blog weekly roundup (2025-12-08): "maintains awareness across sessions and learns from pull requests and feedback"; it defers to the kiro.dev blog for detail. [9] The press release says only "maintains context and learns over time". [10]

### 2.2 What the memory documentation says (VD)

Current `/docs/memory/` covers Kiro memory across IDE, CLI and Web as one feature. [11] As relayed:

- What is kept: repository commands and conventions, corrections, debugging insights, "approaches already ruled out". Each memory is a title, description and content, "not a copy of a past conversation".
- Scope: user-wide, workspace, and repository (`repo:github/<owner>/<repository>`).
- Access modes: `read & write`, `read only`, `off`. An "Automatic memory updates" setting (CLI V3) lets Kiro create and refine memories itself; it needs `read & write` and a trusted workspace.
- Visibility: `/memories` then `list` shows titles, descriptions and update times; Ctrl+P previews type, scope, description. Edit and delete are done by asking Kiro in chat (not by direct edit of the list).
- Size/eviction limits: none stated.

**Gap that matters:** the fetch of this page found its concrete mechanics (commands, trust, access modes) demonstrated for the CLI, and no Kiro Web specifics. Where memory lives in Kiro Web, and whether the web UI can delete, is not in the current page.

A search snippet from the older `/docs/web/memory/` page (now a redirect to `/docs/memory/`; I could not fetch the old text, the Wayback Machine is blocked) read: memory "is maintained automatically, so there's nothing to turn on and nothing to add manually", it is visible in "the Memory section of your Kiro Web Settings", and "You can delete any memory you don't want the agent to keep"; it also said guidance left on a PR is applied "across all your repositories". Treat as snippet-level evidence of a since-moved page. [12]

### 2.3 Kiro Crew's memory docs (VD, different product, noted because they are the only published mechanism detail)

Crew documents six layers (preferences, projects, recent history with decay, semantic facts in SQLite with optional embeddings, episodic snippets, user-taught "lessons"). It states a write gate ("≥0.8 confidence" for model-proposed facts; explicit user corrections always persist), exponential decay of episodic entries (about 23-day half-life as relayed), and a 10,000-entry cap pruning oldest lowest-importance first. Users manage it through `kirocrew learn add/list/remove` and a dashboard. [13] **None of this is documented for the autonomous agent / Kiro Web.** Whether the same engine sits behind both is unstated.

### 2.4 Plain reading

- Public material says **what** is remembered (conventions, corrections, ruled-out approaches, PR feedback) and gives **user control** (list, ask-to-delete; a Settings section on Web per the older snippet; read/write/off modes).
- It says **nothing** about how the agent decides what is worth keeping on Web: no write criteria, no dedup, no contradiction handling, no staleness or expiry, no team/organisation tier mechanics, no treatment of poisoning (a PR comment is attacker-reachable input to a memory the agent later obeys). The one published gate (0.8 confidence) is Crew's.
- The case study (section 5) reports zero memory/learning content, so the "learns from review" claim has no measured evidence in AWS's own results. [14]

## 3. Verifying its own work

- Launch blog: the agent "Breaks down the work and defines requirements and acceptance criteria"; sub-agents split into research/planning, coding, and "a verification agent checks output before moving forward". [1]
- Autonomous-mode doc: sub-agents handle each step "analyzing the codebase, writing code, and verifying changes before moving forward"; the end state is one or more PRs/MRs with descriptions. The doc gives **no completion criterion beyond PR creation** and no iteration limit for the autonomous mode itself. [8]
- Hard external check: "Kiro never merges changes automatically"; every result is reviewed before the default branch. [5]
- Case study: the agent "runs the full test suite, and opens a pull request"; CI and code-owner review are required. [14]
- **Closest analogue to `/goal`: Workflows** (changelog 2026-09-30, docs `/docs/workflows/`). A workflow is a background, multi-agent plan; a loop "repeats until evidence matches a condition or a safety cap is reached", with `maxIterations` and `onMaxIterations` of abort / continue / pause; each step runs in its own session with fresh context so a reviewer does not inherit the coder's reasoning; a 2026-10-12 update lets a user "Run N more" (1 to 1,000) or stop at the cap. Bundled recipes: `investigate`, `feature-pipeline`, `publish-pr`. [15][16][17]
- kiro-cli `/goal` (for comparison): derives acceptance criteria from the goal text, loops plan/implement/self-verify, default max 5 iterations, `--max` to change, state persists across sessions. [18] No source says autonomous mode shares this loop; I could not confirm either way.
- The only external characterisation of limits is the vendor's own case study: "What did not work" lists incorrect fixes that pass CI, architecturally wrong fixes, platform-specific failures and formatting violations, and the authors call CI "necessary but not sufficient" (paraphrase). [14]

## 4. Invocation and supervision

- Start: app.kiro.dev "New session", choose repos (optionally a branch), describe the work. [19] Or GitHub: add the `kiro` label to an issue, or mention `/kiro` in a comment. [1]
- Modes: default is collaborative ("You work with the agent interactively"); autonomous is opt-in. [19][5]
- Isolation: each task has its own sandbox mirroring the dev setup, configurable network access, env vars and secrets, DevFile/Dockerfile setup; headless Chrome with Playwright/DevTools MCP included. [1][20]
- Multi-repo: repos are cloned into the sandbox and changed together; the launch blog calls this "a unified task". [1][19]
- Parallelism: the launch blog says "execute up to 10 tasks concurrently" (preview-era; the current docs state no concurrency limit). Sub-agents coordinate inside a task. [1][20]
- Duration: "hours or days" appears in the press release and TechCrunch, not in any technical doc; the docs state no run-time limit. Sessions expire 90 days after last activity. [10][21][19]
- Human checkpoints: (a) a "Needs attention" state when the agent wants clarification, which waits for input; (b) chat steering during a run; (c) PR/MR comments, which the agent answers by pushing updates; (d) mandatory human review and merge. [8][1][19]
- Background / scheduled: Automations run a prompt on a schedule (hourly minimum, up to five schedules, 10,000-character prompt), open a PR when there is something to review, and appear in session history; no duration or concurrency limits stated. [22] Workflows add pause/resume/stop and loop-cap decisions. [15]

## 5. Measured results (all vendor self-report)

- Kiro blog, 2026-09-14, "Tackling technical debt at scale with Kiro Web's autonomous mode" (VB). The user is AWS's own Automated Reasoning Group, on Kani and CBMC (916 open issues). Quoted: of 94 PRs submitted in Nov/Dec 2025, "as of September 2026, 35 (37%) have been merged, 56 (60%) remain open and under review, and 3 (3%) were closed"; "183 Kiro-generated pull requests have been merged across the two repositories"; "The merged PRs continue to introduce zero regressions". Effort estimate: "At 2–3 hours of focused developer effort per task, the 94 PRs represent roughly 200–280 hours". [14]
- The authors' own bottleneck finding: Kiro can generate PRs faster than the team can review them (paraphrase; the fetch's wording). Median PR about 5 files and 110 lines. [14]
- The "400+ total PRs" figure and "under five minutes" human time for one fuzzer-crash issue came from the fetch's first summary only; I did not re-verify them verbatim.
- Evidence quality: a customer that is AWS itself, no control arm, no comparison with a human baseline, hours saved is an estimate of what developers would have spent, "zero regressions" is unaccompanied by a method, and 60% of PRs were still unreviewed after nine months, so the merge rate is censored.
- Marketing with no technical content: Garman's "orders of magnitude more efficient" claim (AWS roundup). [9] TechCrunch (3P) notes LLM hallucination and that developers prefer short tasks with fast verification. [21]

## 6. What this means for Zikaron (one paragraph, not a recommendation)

AWS publishes the existence and user-facing controls of agent memory (list, ask-to-delete, off/read/read-write, repo/workspace/user scopes) but not the write policy, dedup, staleness or poisoning handling for the autonomous agent. It names the same kinds of content Zikaron's tribal store targets (commands, conventions, ruled-out approaches, corrections). Its only published selection rule is Crew's confidence gate, for a different product. Verification is a role (a verification agent), a PR, and human review; the explicit loop-until-evidence construct lives in Workflows and in `/goal`, with caps and a human pause on cap.

## Methodology and queries

Searches (WebSearch, standard mode): "Kiro autonomous agent AWS frontier agent re:Invent"; "kiro.dev autonomous agent docs memory learns code review feedback"; "AWS News Blog 'Kiro autonomous agent' preview"; "Kiro Web autonomous mode docs ..."; "'Kiro Crew' memory recurring jobs schedules"; "AWS News Blog Kiro autonomous agent frontier agents ... December 2025" (aws.amazon.com only); "re:Invent 2025 session Kiro autonomous agent frontier agent"; "kiro-cli '/goal' command ..."; "Kiro Web workflows docs ..."; "Kiro autonomous agent customer results case study ...". Fetches: kiro.dev blog (twice), docs pages (memory, web index, autonomous-mode, using-the-agent, sandbox, automations, workflows, crew, crew memory, FAQ, cli goal), changelog index and two entries, press.aboutamazon.com, AWS roundup, TechCrunch.

## Gaps and leads

- No dedicated AWS News Blog post and no re:Invent session page specific to the autonomous agent turned up; the AWS roundup defers to kiro.dev. Not exhaustively searched (session catalogue not fetched).
- Kiro Web memory specifics (UI location, deletion in the web UI, how a PR comment becomes a memory, whether it is per-user or per-team) are unconfirmed in current docs. Only a hands-on session or a docs page that the fetch missed would close it.
- Whether autonomous mode runs an iterate-until-criteria loop like `/goal` is unstated.
- Search results also surfaced an `alpha.us-east-2.kiro.adc.aws.dev` mirror of the docs; not used (pre-release host, unclear provenance).
- Fetch-tool summaries can drop or invent detail; if any phrase here becomes load-bearing for a design claim, re-read the page directly.

## Sources

1. Introducing Kiro autonomous agent (Kiro blog, 2025-12-02; update note 2026-05-29) https://kiro.dev/blog/introducing-kiro-autonomous-agent/ (VB)
2. Kiro changelog entry, same title https://kiro.dev/changelog/web/introducing-kiro-autonomous-agent/ (VB; surfaced in search, not separately read)
3. Introducing Kiro Web (Preview) (changelog, 2026-05-07) https://kiro.dev/changelog/web/introducing-kiro-web-preview/ (VB)
4. Kiro Web Is Now Generally Available (changelog, 2026-09-01) https://kiro.dev/changelog/web/kiro-web-is-now-generally-available/ (VB); index https://kiro.dev/changelog/web/
5. Kiro Web docs landing https://kiro.dev/docs/web/ and https://kiro.dev/docs/autonomous-agent/ (VD)
6. Kiro FAQ https://kiro.dev/faq/ (VD)
7. Kiro Crew overview https://kiro.dev/docs/crew/ (VD)
8. Autonomous mode docs https://kiro.dev/docs/web/autonomous-mode/ (VD)
9. AWS Weekly Roundup, 2025-12-08 https://aws.amazon.com/blogs/aws/aws-weekly-roundup-aws-reinvent-keynote-recap-on-demand-videos-and-more-december-8-2025/ (VB)
10. AWS Unveils Frontier Agents (press release, 2025-12-02) https://press.aboutamazon.com/2025/12/aws-unveils-frontier-agents-a-new-class-of-ai-agents-that-work-as-an-extension-of-your-software-development-team (VB)
11. Memory docs https://kiro.dev/docs/memory/ (VD)
12. Older Kiro Web memory page, moved; snippet only, via search https://kiro.dev/docs/web/memory/ (VD, unverified beyond snippet)
13. Kiro Crew memory https://kiro.dev/docs/crew/features/memory/ (VD, different product)
14. Tackling technical debt at scale with Kiro Web's autonomous mode (Kiro blog, 2026-09-14) https://kiro.dev/blog/tackling-technical-debt-at-scale-with-autonomous-mode/ (VB, self-report)
15. Workflows docs https://kiro.dev/docs/workflows/ (VD); loop/cap detail from search result for https://kiro.dev/docs/workflows/patterns/ and https://kiro.dev/docs/workflows/manage/
16. Model Fallback, Workflow Step Models, and Session Reopen Previews (changelog, 2026-10-12) https://kiro.dev/changelog/web/model-fallback-and-workflow-updates/ (VB; read via changelog index)
17. Introducing Workflows in Kiro Web (changelog, 2026-09-30), read only via the changelog index
18. kiro-cli /goal https://kiro.dev/docs/cli/chat/goal (VD)
19. Working with the agent (Web) https://kiro.dev/docs/web/using-the-agent/ and https://kiro.dev/docs/autonomous-agent/using-the-agent/ (VD)
20. Sandbox https://kiro.dev/docs/web/sandbox/ (VD)
21. TechCrunch, Amazon previews 3 AI agents ... (2025-12-02) https://www.techcrunch.com/2025/12/02/amazon-previews-3-ai-agents-including-kiro-that-can-code-on-its-own-for-days/ (3P)
22. Automations https://kiro.dev/docs/web/automations/ (VD)
