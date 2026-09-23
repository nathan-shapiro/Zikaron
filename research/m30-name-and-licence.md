# M30 — PyPI name availability, trademark friction, and `bge-small-en-v1.5` licence

## Brief

Three blocking questions for the M30 release milestone:

1. Is the PyPI project name `zikaron` available (genuinely unregistered vs. registered-but-abandoned
   vs. actively held), and what confusion risk exists in the close-neighbour namespace
   (`zikaron-*`, `zichron`, `zikhron`, `zikkaron`)?
2. Is there trademark/software-product friction on the name "Zikaron"?
3. What licence does `bge-small-en-v1.5` carry at the primary source (HF model card), and does the
   quantized ONNX redistribution we actually fetch (`qdrant/bge-small-en-v1.5-onnx-q`) carry the
   same licence — read verbatim, not reconciled if they differ?

## Method

Direct fetches of PyPI's simple index (a static, non-JS API — reliable for existence checks) and
the JSON API, for `zikaron` and the requested neighbours. `pypi.org/project/<name>` (the human page)
is JS-rendered and did not return usable content through WebFetch — the simple/JSON endpoints are
the ones actually load-bearing here. WebSearch for trademark/product collision, filtering out the
expected generic-word noise (memorial sites, Yom HaZikaron, the town Zichron Yaakov). Direct fetch
of both Hugging Face model cards' licence fields and the qdrant repo's file listing / head commit
via the HF model API.

## Q1 — PyPI name `zikaron`

- `https://pypi.org/simple/zikaron/` → **HTTP 404**. The simple index is PyPI's canonical,
  non-JS, per-project listing; a 404 there means no project currently exists under that exact name.
- `https://pypi.org/pypi/zikaron/json` → **HTTP 404** (same conclusion via the JSON API).
- `https://pypi.org/project/zikaron/` (the human-facing page) did not render usable content through
  WebFetch (JS-dependent) — not used as evidence either way; the two API-level 404s above are the
  authoritative signal.
- I could **not** independently confirm whether PyPI's name-reuse policy would still block a fresh
  registration if the operator's memory of "another project once used the name and renamed" is
  accurate — PyPI does allow name reclaim in some circumstances (abandonment claims, typosquat
  takedowns) but a project that was renamed rather than deleted **does not reserve the old name** in
  the way a deleted-but-still-indexed project might. I found **no trace of `zikaron`** in web search
  results, PyPI's own simple/JSON endpoints, or in user-profile search results — i.e., no evidence
  of a prior registration at all, renamed or otherwise. **Verdict: (a) genuinely unregistered and
  claimable, on the evidence available.** I cannot rule out a name that was registered and then
  fully deleted (PyPI does permanently retire *some* deleted names to prevent typosquatting of
  security-sensitive packages, per PyPI's own documented policy, but a deleted name only becomes
  permanently blocked if it exceeded a download/dependency threshold **or** if it was reserved via
  PyPI's malware/typosquat process) — the 404 on both API endpoints is consistent with either "never
  registered" or "deleted and not specially blocked," and I have no way to distinguish those two from
  outside. **Recommend the operator or a maintainer attempt an actual `twine upload` dry run (or
  reach PyPI support) if higher certainty than "404 on both APIs" is required before the name is
  spent on a real release.**

### Close-neighbour namespace

| Name | Result |
|---|---|
| `zikaron-*` prefix (e.g. `zikaron-mcp`, `zikaron-cli`, `zikaron-agent`) | No hits in PyPI search or web search — no evidence of registration |
| `zichron` | `https://pypi.org/simple/zichron/` → **404**, unregistered |
| `zikhron` | `https://pypi.org/simple/zikhron/` → **404**, unregistered |
| `zikkaron` (double-k) | **REGISTERED — actively held.** See below. |

**`zikkaron` is the important finding.** `https://pypi.org/simple/zikkaron/` lists real release
artefacts for versions 0.1.0 through **1.6.0**. The project JSON
(`https://pypi.org/pypi/zikkaron/json`) reports:
- Author: `amanhij`
- Summary: *"A biologically-inspired persistent memory engine for Claude Code built on
  computational neuroscience. The system consolidates, forgets intelligently, and reconstructs
  context through 26 subsystems running locally on SQLite."*
- Latest release: **1.6.0, uploaded 2026-04-01**
- Homepage/repo: `https://github.com/amanhij/Zikkaron`

This is **not merely a spelling neighbour** — it is a persistent-memory system for Claude Code
built on SQLite, i.e. the same problem space and harness as this project, actively maintained (a
release four months before this brief). One character (`k` vs `kk`) separates it from our proposed
name. This substantially raises the confusion-risk stakes beyond ordinary trademark search — a user
searching "zikaron memory claude" is likely to encounter both, and installer/typing confusion
(`pip install zikaron` vs `zikkaron`) is a real and immediate risk, not a hypothetical one.

## Q2 — Trademark / product friction on "Zikaron"

Filtered for genuine software/tech collision, excluding generic-word hits (memorial sites, Yom
HaZikaron, Zichron Yaakov):

- **`zikaron.app`** — a real, active product: a Jewish-cemetery records platform ("brings together
  records from Jewish cemeteries across Europe and the Middle East... North America, Asia and
  Australia. The app allows users to add burial records, order care services, and search graves").
  This is software, under the plain name "Zikaron," but in genealogy/memorial services — a
  different market from developer tooling / AI agent memory. Low confusion risk for a PyPI package
  aimed at coding agents, but worth knowing it exists if a written mark search or domain purchase
  is contemplated later.
- **Crunchbase lists an organization "Zikaron"** described (per search snippet, page itself returned
  403 to direct fetch) as an e-platform for cemetery management with multilingual tools — likely the
  same entity as `zikaron.app` rather than a second collision.
- **No hits** for a software/AI company, registered trademark, or dev-tool product named "Zikaron"
  in the computing/AI space. I did not query the USPTO TESS database directly (out of scope for a
  light web search); this is a gap if a formal trademark clearance is later required.
- **The `zikkaron` PyPI package (Q1) is the real friction**, not a trademark issue in the legal
  sense (no evidence of a registered mark) but a direct naming/discoverability collision in the
  identical product category.

**Confidence: moderate.** The cemetery-platform hit is confirmed and clearly out of category. No
registered-mark collision found in computing, but only a light search was performed and no USPTO
lookup was done, per brief scope.

## Q3 — Licence of `bge-small-en-v1.5` and the qdrant ONNX redistribution

### Primary source: `BAAI/bge-small-en-v1.5` (Hugging Face)

Fetched `https://huggingface.co/BAAI/bge-small-en-v1.5` and its README directly.

- **YAML frontmatter licence field, verbatim: `license: mit`**
- Model-card prose: *"FlagEmbedding is licensed under the [MIT License]... The released models can
  be used for commercial purposes free of charge."*

This **confirms** the corpus's existing MIT claim from a primary reading of the model card, not
just the earlier research note.

### The redistribution actually fetched: `qdrant/bge-small-en-v1.5-onnx-q`

Fetched `https://huggingface.co/qdrant/bge-small-en-v1.5-onnx-q` and its HF model API
(`https://huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q`).

- **Licence field, verbatim: `apache-2.0`**
- **This differs from the upstream `BAAI/bge-small-en-v1.5` MIT licence — stated explicitly, not
  reconciled.** The qdrant repo re-tags the model as Apache-2.0 rather than carrying forward MIT.
  Both are permissive licences (attribution/notice requirements differ slightly: Apache-2.0 adds a
  patent grant and a NOTICE-file mechanism that MIT does not have), but they are **not the same
  licence text**, and a package that (per our design) fetches the qdrant artefact at runtime is
  bound by whatever qdrant actually attached, not by what BAAI attached upstream. I could not find,
  on the qdrant model card, any explicit note reconciling the discrepancy with the upstream MIT
  license (e.g. "originally MIT, relicensed as..." language) — the card simply carries an
  `apache-2.0` tag with no discussion of provenance-of-licence. This is worth flagging as an
  unexplained inconsistency rather than treating Apache-2.0 as clearly correct.
- **Redistribution terms bearing on "fetch at runtime, never redistribute weights":** neither card,
  as fetched, states redistribution terms specific to a fetch-only (non-redistributing) consumer.
  Apache-2.0 and MIT are both permissive enough that a runtime-fetch-only design (no weights ever
  committed to or shipped from our own repository/package) is uncontroversially fine under either
  licence — the licence terms that matter (attribution, notice preservation) attach to whoever
  *redistributes* the weights, which on our design is Hugging Face / qdrant, not us. **Not
  established**: I found no explicit "you may fetch this without redistributing and incur no
  obligations" statement on either card — that's an inference from the licences' ordinary terms, not
  a quoted assurance, and should be labelled as such internally.

### File list, head commit, history (for pinning)

From `https://huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q` and its `/refs` endpoint:

- **Head commit SHA on `main`: `52398278842ec682c6f32300af41344b1c0b0bb2`** (reported by the HF
  API's branch reference; note this string is 41 hex characters as transcribed through the fetch
  tool rather than the standard 40 — **flagging this as possibly a transcription artefact of the
  fetch/summarization step, not a value I read from raw bytes**. Before pinning, re-fetch
  `https://huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q/refs` yourself, or run
  `huggingface-cli` / `huggingface_hub.HfApi().model_info(...)` locally, to get the exact SHA
  without an intermediate paraphrase step.)
- **File list** (from the model API's file listing):
  - `.gitattributes`
  - `README.md`
  - `config.json`
  - `model_optimized.onnx`
  - `ort_config.json`
  - `special_tokens_map.json`
  - `tokenizer.json` — **present**, confirming it is available to pin as planned
  - `tokenizer_config.json`
  - `vocab.txt`
- **Commit history**: the `/refs` endpoint shows exactly **one branch (`main`)**, no tags, pointing
  at the single commit SHA above; no evidence of multiple historical commits was surfaced by this
  endpoint (it reports current refs, not full commit log). Model metadata: created
  2024-01-15T06:19:25Z, last modified 2024-07-15T12:50:23Z — i.e. **the repo has had at least one
  update after creation** (creation and last-modified timestamps differ by six months), so there is
  commit history beyond the initial one even though `/refs` only surfaces the current tip. To get
  the actual commit count/log, fetch `https://huggingface.co/qdrant/bge-small-en-v1.5-onnx-q/commits/main`
  directly (not done here — out of scope for this pass but cheap to do before pinning).
  Downloads reported: 1,236,714 (high-traffic, actively-used artefact, consistent with "not
  abandoned").

## Evidence quality and gaps

- PyPI simple/JSON 404s are reliable (static API), but do **not** by themselves prove a name was
  *never* registered — only that no project currently exists under it. No stronger signal (e.g. a
  PyPI support ticket, or an actual upload attempt) was available within this brief's scope.
- The qdrant repo's exact head SHA should be re-verified directly (not through a paraphrasing fetch)
  before it is written into a pin file — the 41-vs-40-character discrepancy noted above is a red
  flag worth 30 seconds of direct verification.
- No formal USPTO trademark search was performed; the brief asked for a "light search only," which
  this satisfies, but it is not a legal clearance.
- The `zikkaron` collision is the single most load-bearing finding in this note and is the one most
  likely to change the operator's decision — it is a live, actively-maintained, same-category
  PyPI package one keystroke away from the proposed name.

## Sources

1. [pypi.org/simple/zikaron/](https://pypi.org/simple/zikaron/) — 404, checked directly
2. [pypi.org/pypi/zikaron/json](https://pypi.org/pypi/zikaron/json) — 404, checked directly
3. [pypi.org/simple/zichron/](https://pypi.org/simple/zichron/) — 404, checked directly
4. [pypi.org/simple/zikhron/](https://pypi.org/simple/zikhron/) — 404, checked directly
5. [pypi.org/simple/zikkaron/](https://pypi.org/simple/zikkaron/) — lists releases 0.1.0–1.6.0, checked directly
6. [pypi.org/pypi/zikkaron/json](https://pypi.org/pypi/zikkaron/json) — package metadata, checked directly
7. [github.com/amanhij/Zikkaron](https://github.com/amanhij/Zikkaron) — homepage of the colliding package (referenced via PyPI metadata, not independently fetched)
8. [zikaron.app](https://zikaron.app/) — Jewish cemetery records platform, found via WebSearch
9. [crunchbase.com/organization/zikaron](https://www.crunchbase.com/organization/zikaron) — company profile, fetch returned 403; description via search snippet only
10. [huggingface.co/BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) — model card, `license: mit`, checked directly
11. [huggingface.co/BAAI/bge-small-en-v1.5/blob/main/README.md](https://huggingface.co/BAAI/bge-small-en-v1.5/blob/main/README.md) — frontmatter and licence prose, checked directly
12. [huggingface.co/qdrant/bge-small-en-v1.5-onnx-q](https://huggingface.co/qdrant/bge-small-en-v1.5-onnx-q) — model card, `license: apache-2.0`, checked directly
13. [huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q](https://huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q) — raw metadata (license, files, timestamps, downloads), checked directly
14. [huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q/refs](https://huggingface.co/api/models/qdrant/bge-small-en-v1.5-onnx-q/refs) — branch/commit refs, checked directly (SHA transcription should be re-verified before pinning)
