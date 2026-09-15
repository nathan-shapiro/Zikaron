# Amazon Q Developer CLI — the `knowledge` indexing/retrieval engine

> Teardown of `crates/semantic-search-client/` in `~/amazon-q-developer-cli` (read-only clone, single
> shallow commit `15cc8f3`, dated 2026-04-23). Scope: the **engine**. The `chat-cli` integration is
> covered separately; it is touched here only where a call had to be followed to answer a question.
> Every claim below carries a file path and line number. Where the code did not settle a question the
> text says **not determined** and names what was read.

## What this is, in one paragraph

`semantic-search-client` is a ~7,100-line Rust crate that indexes a directory into a named "context"
and answers natural-language queries against it. Per context it picks **one** of two disjoint
retrieval modes — `Best` (dense: all-MiniLM-L6-v2 under Candle on CPU, HNSW over cosine) or `Fast`
(lexical: the `bm25` crate) — chosen at *index* time and recorded in the context's metadata. It is
**not hybrid**: no fusion, no reranking, no threshold. Indexing runs in a single background tokio
task fed by an unbounded channel, with progress and cancellation surfaced through a shared
`HashMap<Uuid, OperationHandle>`. Persistence is one `serde_json` array per context holding the chunk
text, its metadata and, for dense contexts, the raw 384-float vector as JSON numbers; the HNSW graph
itself is never persisted and is rebuilt in memory at every startup. There is **no staleness
mechanism of any kind** — no mtime, no hash, no watcher, no incremental update — and refresh is a
user-typed `/knowledge update <path>` that deletes the context and re-indexes it from scratch.
Everything is local; the only network call is a one-time model download from an AWS CDN, SHA256-pinned.

## Load-bearing constants

| Thing | Value | Unit | Where |
|---|---|---|---|
| Embedding model | `all-MiniLM-L6-v2` (repo `sentence-transformers/all-MiniLM-L6-v2`) | — | `src/embedding/candle_models.rs:46-47` |
| Alternate model (defined, unreachable) | `all-MiniLM-L12-v2` | — | `candle_models.rs:72-73` |
| Inference backend | Candle 0.9.1 (`candle-transformers` BERT), **CPU only** | — | `src/embedding/candle.rs:292-296` |
| Embedding dim | **384** (`hidden_size`) | floats | `candle_models.rs:53` |
| Max positions | 512 | tokens | `candle_models.rs:59` |
| Tokenizer truncation | **none configured anywhere** | — | see §1 |
| Pooling | unmasked `mean(1)` then L2 normalise | — | `candle.rs:224`, `candle.rs:236-240` |
| Model batch size | 32 (**never exercised on the index path**, see §8) | texts | `candle_models.rs:70` |
| `chunk_size` | **512** | **whitespace-separated words** | `src/config.rs:87` |
| `chunk_overlap` | **128** | **words** | `src/config.rs:88` |
| `default_results` | **5** | results **per context** | `src/config.rs:89` |
| `max_files` | **10000** (README and user docs say 5,000) | files | `src/config.rs:93` |
| Relevance threshold | **none** | — | §4 |
| Vector index | HNSW, `hnsw_rs` 0.3.1, `DistCosine` | — | `src/index/vector_index.rs:31-37` |
| HNSW `M` (max conns/layer) | 16 | — | `vector_index.rs:32` |
| HNSW max layer | 16 | — | `vector_index.rs:34` |
| HNSW `ef_construction` | 100 | — | `vector_index.rs:35` |
| HNSW `ef_search` | 100, hardcoded at the call site | — | `src/client/context/semantic_context.rs:132` |
| Lexical index | `bm25` 2.3.2, `Language::English` | — | `src/index/bm25_index.rs:50-52` |
| BM25 `avgdl` at **build** | **5.0** | tokens | `src/client/context/context_creator.rs:93` |
| BM25 `avgdl` at **load** | **100.0** | tokens | `src/client/context/context_manager.rs:35` |
| `MAX_CONCURRENT_OPERATIONS` | 3 (vacuous — see §7) | — | `src/client/background/background_worker.rs:26` |
| Model CDN | `https://desktop-release.q.us-east-1.amazonaws.com/models` | — | `src/config.rs:94` |
| Model cache dir | `~/.semantic_search/models/all-MiniLM-L6-v2/` | — | `config.rs:108-112`, `candle_models.rs:103-113` |
| Store dir (crate default) | `~/.semantic_search/` | — | `config.rs:108-112` |
| Store dir (as shipped) | `~/.aws/amazonq/knowledge_bases/<agent>/` | — | `docs/knowledge-management.md:188` |
| Dead config fields | `timeout` (30000), `model_name` | — | §1, §9 |

---

## 1. Embedding model, backend, dimension, provenance

**Model.** Exactly one model is reachable: `all-MiniLM-L6-v2`, 384-dim, 6 layers, 12 heads,
`max_position_embeddings: 512`, `normalize_embeddings: true` (`candle_models.rs:45-71`). A
`MiniLML12V2` variant is defined (`candle_models.rs:72-98`) but nothing constructs it —
`embedder_factory.rs:26` hardcodes `ModelType::MiniLML6V2`, and `EmbeddingType::to_model_type`
(`trait_def.rs:43-50`) maps `Best` to `MiniLML6V2` unconditionally.

**Backend: Candle, and only Candle.** `Cargo.toml:44-48` pulls `candle-core`/`candle-nn`/
`candle-transformers` 0.9.1 and `tokenizers` 0.21. There is **no ONNX Runtime dependency anywhere in
the workspace** — `grep 'ort ='` over the workspace `Cargo.toml` returns nothing.

> **`src/embedding/onnx.rs` (369 lines) and `src/embedding/tf.rs` (168 lines) are orphaned files.**
> `src/embedding/mod.rs:1-9` declares only `benchmark_test`, `benchmark_utils`, `candle`,
> `candle_models`, `mock`, `trait_def`. Neither `onnx` nor `tf` is ever declared as a module, so
> neither compiles. Their presence is the single biggest trap for a reader: the crate README still
> advertises ONNX as the macOS/Windows default (`README.md:139`, `:569-570`).

**Backend selection** is by **target triple at compile time**, not by feature flag or runtime probe.
The one axis is Linux-on-aarch64:

```rust
// src/embedding/trait_def.rs:10-19
pub enum EmbeddingType {
    /// Fast embedding using BM25 (available on all platforms)
    Fast,
    /// Best embedding using all-MiniLM-L6-v2 (not available on Linux ARM)
    #[cfg(not(all(target_os = "linux", target_arch = "aarch64")))]
    Best,
```

Default is `Best` everywhere except Linux/aarch64, which defaults to `Fast` (`trait_def.rs:23-38`).
The user can override per-context via `--index-type` or globally via `knowledge.indexType`
(`docs/knowledge-management.md:85`, wired at `crates/chat-cli/src/util/knowledge_store.rs:256-261`).

**Device.** The `Cargo.toml` carries elaborate `cfg`-gated `candle-core` entries whose comments
promise Metal on macOS and CUDA on Linux/Windows (`Cargo.toml:51-57`) — but every one of them
specifies `features = []`, and the code refuses acceleration outright:

```rust
// src/embedding/candle.rs:291-296
/// Get the best available device for inference
fn get_best_available_device() -> Device {
    // Always use CPU for embedding to avoid hardware acceleration issues
    info!("Using CPU for text embedding (hardware acceleration disabled)");
    Device::Cpu
}
```

**Weights and cache.** Not Hugging Face. A zip per model is fetched from the AWS CDN and extracted:

```rust
// src/client/hosted_model_client.rs:110-113
let zip_filename = format!("{}.zip", model_config.name);
let zip_url = format!("{}/{}", self.base_url, zip_filename);
```

Cache location is `~/.semantic_search/models/<model name>/{model.safetensors,tokenizer.json}`
(`candle_models.rs:103-113` → `config.rs:137-139` → `config.rs:108-112`). Weights are mmap'd:
`VarBuilder::from_mmaped_safetensors` (`candle.rs:302`).

**Integrity is SHA256-pinned, one hash per file, and a mismatch deletes the file:**

```rust
// src/model_validator.rs:28-34
allowlisted_shas.insert("model.safetensors", vec![
    "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
]);
allowlisted_shas.insert("tokenizer.json", vec![
    "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
]);
```
```rust
// src/model_validator.rs:64-67
if !valid_shas.contains(&actual_sha.as_str()) {
    let _ = std::fs::remove_file(file_path); // Remove invalid file
    return false;
}
```

This is the crate's best single idea and the one I would copy verbatim. Note it also **pins
`tokenizer.json` byte-for-byte**, which is what lets the next paragraph be a definite statement.

**Is anything remote?** No. Inference is entirely local. The only network call in the crate is the
model zip download (`hosted_model_client.rs:155`). No query, chunk, or embedding leaves the machine.

**Two dead config fields.** `SemanticSearchConfig::timeout` (`config.rs:37`, default 30000) is
**never read** — grep for `.timeout` across `src/` returns only declarations and test literals.
`SemanticSearchConfig::model_name` (`config.rs:34`) is **also never read** by the embedder path;
model choice comes from `ModelType::default()` and the on-disk directory name from
`ModelConfig.name`. Editing `model_name` in `semantic_search_config.json` does nothing.

**A cache-directory inconsistency worth knowing.** `AsyncSemanticSearchClient::with_config` calls
`config::ensure_models_dir(&base_dir)` (`async_implementation.rs:83`), creating
`<base_dir>/models/` — but `ModelType::get_local_paths()` ignores the configured base dir and always
resolves against `get_default_base_dir()` (`candle_models.rs:105`). As shipped this means chat-cli
creates an empty `~/.aws/amazonq/knowledge_bases/<agent>/models/` for every agent while the real
weights sit once in `~/.semantic_search/models/`. The sharing is correct behaviour arrived at by
accident.

### The truncation gap — flagged as the most consequential single finding in §1

There is **no truncation configured anywhere in the crate.** `prepare_tokenizer` sets padding only:

```rust
// src/embedding/candle.rs:327-340
fn prepare_tokenizer(tokenizer: &Tokenizer) -> Result<Tokenizer> {
    let mut tokenizer = tokenizer.clone();
    if let Some(pp) = tokenizer.get_padding_mut() {
        pp.strategy = tokenizers::PaddingStrategy::BatchLongest;
    } else {
        let pp = tokenizers::PaddingParams {
            strategy: tokenizers::PaddingStrategy::BatchLongest,
            ..Default::default()
        };
        tokenizer.with_padding(Some(pp));
    }
    Ok(tokenizer)
}
```

`grep -rn "truncation\|with_truncation\|max_length"` over `src/` (excluding the two orphaned files)
returns **zero** hits. Meanwhile `chunk_size` is 512 **words**, and BERT's position table is 512
**tokens**. English prose runs well above 1 token/word and code far above that, so a default-sized
chunk routinely tokenizes past 512 positions.

What happens then is **not determined from this checkout**: the pinned `tokenizer.json` may or may
not carry its own `truncation` stanza, and I could not read it (it is downloaded at runtime and the
CDN was not contacted). The two branches are:
- tokenizer.json has truncation → chunks are **silently truncated** to 512 tokens, i.e. roughly the
  first 60-70% of each chunk is embedded and the remainder is indexed-but-invisible;
- tokenizer.json does not → the position-embedding lookup errors, `process_batch` swallows it and
  returns `Vec::new()` (`candle.rs:176-182`, `:187`, `:201`), the length check at `candle.rs:164-168`
  then fires and the **whole indexing run fails** with `"Failed to generate embeddings for all texts"`.

Either way it is a real defect, and the second branch would be loud enough that the first is the
likelier reality in production.

### A second embedding-quality defect: unmasked mean pooling

```rust
// src/embedding/candle.rs:212-240 (abridged)
let embeddings = self.model.forward(token_ids, token_type_ids, Some(attention_mask))?;
// Apply mean pooling
let mean_embeddings = embeddings.mean(1)?;
...
let final_embeddings = if self.config.normalize_embeddings { normalize_l2(&mean_embeddings)? } else { ... };
```

The attention mask is passed into `forward` but **not** into the pooling. `mean(1)` averages across
the full padded sequence length, so padding positions contribute to the sentence vector. Reference
sentence-transformers computes `sum(h * mask) / sum(mask)`. Because padding is `BatchLongest`, the
amount of contamination depends on what else happened to be in the batch — which makes a document's
embedding **non-deterministic with respect to batch composition**. In this codebase the effect is
accidentally suppressed on the index path (every batch is size 1 — see §8) but *not* on any path that
batches, and it is wrong regardless.

---

## 2. Chunking

**Strategy: fixed-count sliding window over whitespace tokens. Nothing else.** The entire
implementation is 27 lines:

```rust
// src/processing/text_chunker.rs:14-41
pub fn chunk_text(text: &str, chunk_size: Option<usize>, overlap: Option<usize>) -> Vec<String> {
    let config = config::get_config();
    let chunk_size = chunk_size.unwrap_or(config.chunk_size);
    let overlap = overlap.unwrap_or(config.chunk_overlap);

    let mut chunks = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    if words.is_empty() {
        return chunks;
    }

    let mut i = 0;
    while i < words.len() {
        let end = (i + chunk_size).min(words.len());
        let chunk = words[i..end].join(" ");
        chunks.push(chunk);

        // Move forward by chunk_size - overlap
        i += chunk_size - overlap;
        if i >= words.len() || i == 0 {
            break;
        }
    }

    chunks
}
```

**Unit is words**, not bytes, chars or tokens — `split_whitespace()`. Defaults 512/128
(`config.rs:87-88`), overridable via `knowledge.chunkSize` / `knowledge.chunkOverlap`
(`crates/chat-cli/src/util/knowledge_store.rs:242-249`). Stride is 384 words, 25% overlap.

**No AST, no syntax awareness, no boundary logic at all.** Not paragraph-aware, not line-aware, not
sentence-aware. File type affects only *metadata*: `FileType::Code` adds a `language` key equal to
the file extension (`src/processing/file_processor.rs:160-170`). The chunker itself is never told the
file type.

**`join(" ")` destroys the original whitespace.** Every run of spaces, every newline, every level of
indentation collapses to a single space. For source code this means the indexed text of a Python
file has no indentation and the indexed text of any file has no line structure — so a retrieved chunk
cannot be shown back to a user as the code that is actually on disk, and no line number can be
recovered. The stored payload carries only `path`, `chunk_index`, `total_chunks`
(`file_processor.rs:152-158`) — **no byte or line offsets**, so a result cannot be located in the file
it came from.

**Two silent-truncation edges, neither validated against.** Nothing anywhere checks
`chunk_overlap < chunk_size`; `knowledge_store.rs:242-253` passes both settings through untouched.
- `overlap == chunk_size`: `i += 0`, the `i == 0` guard fires, loop breaks after one chunk.
- `overlap > chunk_size`: `chunk_size - overlap` underflows `usize`. The workspace release profile
  (`Cargo.toml:212-215`) does not set `overflow-checks`, so it wraps rather than panicking; `i`
  becomes enormous, `i >= words.len()` fires, loop breaks after one chunk.

In **both** cases the result is one chunk containing the first `chunk_size` words and **the rest of
the file is discarded with no error, no warning and no log line.** A user who sets
`knowledge.chunkOverlap 1024` against the default 512 silently indexes the first 512 words of every
file in their project.

---

## 3. Vector store

**Storage is a JSON array of records, each carrying its own raw vector.** There is no database, no
binary format, no mmap.

```rust
// src/types.rs:143-153
pub struct DataPoint {
    pub id: usize,
    pub payload: HashMap<String, serde_json::Value>,
    pub vector: Vec<f32>,
}
```
```rust
// src/client/context/semantic_context.rs:59-66
pub fn save(&self) -> Result<()> {
    let file = File::create(&self.data_path)?;
    let writer = BufWriter::new(file);
    serde_json::to_writer(writer, &self.data_points)?;
    Ok(())
}
```

One `data.json` per context (`context_manager.rs:33`), one `data.bm25.json` for lexical contexts
(`context_manager.rs:34` — note the user docs say `bm25_data.json` at
`docs/knowledge-management.md:193`; the docs are wrong). Metadata for all contexts lives in one
`contexts.json` at the store root (`context_manager.rs:49`).

384 `f32` serialised as JSON decimal numbers costs on the order of 4-5 KB per chunk before the chunk
text itself — roughly an order of magnitude worse than the 1,536 bytes the floats actually occupy.

**Index type: HNSW, flat parameters, cosine.**

```rust
// src/index/vector_index.rs:31-37
let index = Hnsw::new(
    16,                    // Max number of connections per layer
    max_elements.max(100), // Maximum elements
    16,                    // Max layer
    100,                   // ef_construction (size of the dynamic candidate list)
    DistCosine {},
);
```

`max_elements` is passed as `self.data_points.len().max(100)` (`semantic_context.rs:71`). Whether
`hnsw_rs` 0.3.1 enforces that as a hard cap when `update_index_by_range` appends past it is **not
determined** — the crate source was not in the local cargo cache and I did not fetch it.

**The HNSW graph is never persisted.** `VectorIndex` has no save, no load, no serde impl — read
`src/index/vector_index.rs` end to end; its only methods are `new`, `insert`, `search`, `len`,
`is_empty`. It is rebuilt from the JSON on every process start:

```rust
// src/client/context/semantic_context.rs:44-53
if data_path.exists() {
    let file = File::open(&data_path)?;
    let reader = BufReader::new(file);
    context.data_points = serde_json::from_reader(reader)?;
}
// If we have data points, rebuild the index
if !context.data_points.is_empty() {
    context.rebuild_index()?;
}
```

So startup cost is: parse the whole JSON (vectors included) into RAM, then perform one HNSW insert
per chunk. **Everything is resident in memory; nothing is memory-mapped.** `load_persistent_contexts`
does this for every context at client construction (`async_implementation.rs:112`), on the calling
task, before `with_config` returns.

**`VectorIndex` has no delete.** Neither does `SemanticContext` — `data_points` is append-only. The
only removal granularity is the whole context (`context_manager.rs:336-356`).

**The BM25 persistence path is a stub that writes an empty array**, and the authors say so:

```rust
// src/index/bm25_index.rs:94-108
pub fn save_to_disk<P: AsRef<Path>>(&self, path: P) -> crate::error::Result<()> {
    // Extract documents from the search engine
    let _engine = self.engine.read().unwrap();
    let documents: Vec<SerializableDocument> = Vec::new();

    // Note: The BM25 crate doesn't expose a way to iterate over documents
    // This is a limitation - we'd need to track documents separately
    // For now, this is a placeholder that would need the BM25 crate to expose document iteration

    let file = File::create(path)?;
    let writer = BufWriter::new(file);
    serde_json::to_writer(writer, &documents)?;

    Ok(())
}
```

It is harmless only because nothing calls it: `grep save_to_disk\|load_from_disk` over `src/` and
`tests/` finds the two definitions and no call site. Lexical persistence actually happens through
`BM25Context::save` (`bm25_context.rs:63-68`), which writes the `BM25DataPoint` list and rebuilds the
engine on load. Two parallel persistence designs, one live and one dead, in adjacent files.

---

## 4. Retrieval

**Dense-only or lexical-only, per context. Never both, never fused.** The mode is fixed at index
time and stored in `KnowledgeContext::embedding_type` (`types.rs:108-109`), and the dispatch is a
plain branch:

```rust
// src/client/context/context_manager.rs:85-96
for (context_id, context_meta) in contexts_metadata.iter() {
    if context_meta.embedding_type.is_bm25() {
        if let Some(results) = self.search_bm25_context(context_id, query_text, effective_limit).await {
            all_results.push((context_id.clone(), results));
        }
    } else if let Some(results) = self
        .search_semantic_context(context_id, query_text, effective_limit, embedder)
        .await?
    {
        all_results.push((context_id.clone(), results));
    }
}
```

**No reranker.** `grep -i rerank\|cross.encoder` over the crate: zero hits.

**Metric.** Dense: cosine distance via `DistCosine` (`vector_index.rs:36`), against L2-normalised
embeddings. Lexical: BM25 score from the `bm25` crate. Both are returned in the same `f32` field:

```rust
// src/types.rs:169-176
pub struct SearchResult {
    pub point: DataPoint,
    /// Distance/similarity score (lower is better)
    pub distance: f32,
}
```

**Top-K is 5 and it is per context, not global** (`config.rs:89`; `async_implementation.rs:416`
passes `effective_limit` down to each context individually). A user with eight contexts gets up to 40
rows back from one search.

**No relevance threshold or cutoff anywhere.** `grep -i threshold\|min_score\|cutoff` over the crate
and over `crates/chat-cli/src/util/knowledge_store.rs`: zero hits. A query against an unrelated
context still returns its five nearest chunks.

### The ordering defect

Because BM25 scores (**higher is better**, unbounded) and cosine distances (**lower is better**, in
[0,2]) are both written into `SearchResult::distance`, any ordering that spans both kinds of context
is meaningless. Both places that order across contexts sort **ascending**:

```rust
// src/client/context/context_manager.rs:98-105
all_results.sort_by(|(_, a), (_, b)| {
    if a.is_empty() || b.is_empty() { return std::cmp::Ordering::Equal; }
    a[0].distance.partial_cmp(&b[0].distance).unwrap_or(std::cmp::Ordering::Equal)
});
```
```rust
// crates/chat-cli/src/util/knowledge_store.rs:398 (the user-facing search)
flattened.sort_by(|a, b| a.distance.partial_cmp(&b.distance).unwrap_or(std::cmp::Ordering::Equal));
```

Ascending sort promotes the *worst* BM25 matches and demotes the best. A user who keeps one `Fast`
context and one `Best` context — precisely the arrangement the docs recommend at
`docs/knowledge-management.md:70-77` — gets a merged result list whose order is partly inverted. The
comparator's `if a.is_empty() || b.is_empty() { Equal }` is separately unsound as a `sort_by`
predicate (non-transitive), though in practice empty result sets are filtered out upstream
(`context_manager.rs:154`, `:172`).

Lexical results also fabricate a vector to fit the shared struct:

```rust
// src/client/context/context_manager.rs:143-149
let vector = vec![0.0; 384];
let point = DataPoint { id: data_point.id, vector, payload: data_point.payload.clone() };
SearchResult::new(point, score)
```

### The BM25 `avgdl` inconsistency

BM25's length normalisation needs the corpus average document length. This crate supplies a constant,
and **a different constant at build time than at load time**:

```rust
// src/client/context/context_creator.rs:93  — when the context is first built
let mut bm25_context = BM25Context::new(context_dir.join("data.bm25.json"), 5.0)
```
```rust
// src/client/context/context_manager.rs:35  — when the context is reloaded next session
const DEFAULT_BM25_SCORE: f64 = 100.0;
// ...used at context_manager.rs:286
let bm25_context = BM25Context::new(data_file, DEFAULT_BM25_SCORE)?;
```

Two consequences. First, **the same query against the same corpus ranks differently before and after
a CLI restart** — the index is rebuilt from `data_points` with a 20× different `avgdl`. Second, both
numbers are wrong: documents here are ~512-word chunks, so true `avgdl` is in the hundreds. At
`avgdl = 5.0` every document is ~100× "longer than average" and BM25's length penalty saturates,
flattening the ranking toward pure IDF. The misleading name `DEFAULT_BM25_SCORE` for an average
document length is probably how this survived review.

---

## 5. File selection and filtering

**Discovery** is `walkdir` with `follow_links(true)` (`src/client/background/file_processor.rs:42`,
`:116`), filtered to regular files, with exactly two filters.

**(a) Hidden files — filename only, and directories are not pruned:**

```rust
// src/client/background/file_processor.rs:133-139
if path
    .file_name()
    .and_then(|n| n.to_str())
    .is_some_and(|s| s.starts_with('.'))
{
    continue;
}
```

This is a `.filter()` on the flattened iterator, **not** `WalkDir::filter_entry`. WalkDir therefore
**descends into `.git/`, `.venv/`, `.cache/`, `node_modules/`** and every other dotted or build
directory. `.git/objects/ab/cdef…` does not start with a dot, so it passes the filter and is counted
and processed. With no user patterns supplied (the default), indexing a normal repository walks the
entire `.git` object store.

**(b) Optional user glob patterns** — the only real control, and off by default:

```rust
// src/client/background/file_processor.rs:163-176
fn create_pattern_filter(
    include_patterns: &Option<Vec<String>>,
    exclude_patterns: &Option<Vec<String>>,
) -> std::result::Result<Option<crate::pattern_filter::PatternFilter>, String> {
    if include_patterns.is_some() || exclude_patterns.is_some() { ... } else { Ok(None) }
}
```

`PatternFilter` (`src/pattern_filter.rs:33-85`) is include-then-exclude over the `glob` crate, and
`matches_pattern` retries the pattern against every path suffix so that `node_modules/**` matches an
absolute path (`pattern_filter.rs:71-82`). Defaults come from
`knowledge.defaultIncludePatterns`/`defaultExcludePatterns`, which ship **empty**
(`docs/knowledge-management.md:95`: "If no patterns are specified and no defaults are configured, all
supported files are indexed").

**`.gitignore` is not read.** `grep -ri gitignore` over `src/` returns one hit — `".gitignore"` as an
*extension-less filename that should be indexed as text* (`file_processor.rs:71`). The `ignore` crate
is not a dependency. The README's claim that "the client automatically skips common build artifacts
and hidden files" (`README.md:535`) is false for the first half.

**Symlinks are followed** (`follow_links(true)`), with no loop detection beyond whatever walkdir
provides and no containment check that the target stays inside the indexed root.

**No size cap of any kind, on a file or on the corpus.** `grep` for `metadata()`, `file_size`,
`max_size` over `src/` returns nothing relevant. The only guard is a **file count**:

```rust
// src/client/background/background_worker.rs:204-218
if file_count > self.config.max_files {
    ... cancel_token.cancel();
    return Err(format!("Failed: Directory contains {} files, which exceeds the maximum limit of {} files", ...));
}
```

So one 800 MB `.log` file passes the gate, gets `fs::read_to_string`'d whole, gets split into a
`Vec<&str>` of every word, gets chunked, and every chunk plus every 384-float vector is accumulated
in RAM before anything is written.

**Type selection is an extension allowlist — there is no binary content sniffing.**
`get_file_type` (`src/processing/file_processor.rs:14-80`) enumerates: `.txt`; `.md/.markdown/.mdx`;
`.json`; `.ini/.conf/.cfg/.properties/.env`; `.csv/.tsv`; `.log`; `.rtf/.tex/.rst`; `.svg`; `.pdf`;
and as `Code`: `.rs .py .js .jsx .ts .tsx .java .c .cpp .h .hpp .go .rb .php .swift .kt .kts .cs .sh
.bash .zsh .html .htm .xml .css .scss .sass .less .sql .yaml .yml .toml`. Extension-less files are
matched by name against `Dockerfile | Makefile | LICENSE | CHANGELOG | README`, plus
`.gitignore | .env | .dockerignore`.

**Everything else is indexed as a bare path with no content**, which is the subtlest problem in the
file:

```rust
// src/processing/file_processor.rs:189-196
FileType::Unknown => {
    // For unknown file types, just store the path
    let mut metadata = serde_json::Map::new();
    metadata.insert("path".to_string(), Value::String(path.to_string_lossy().to_string()));
    metadata.insert("file_type".to_string(), Value::String("Unknown".to_string()));
    Ok(vec![Value::Object(metadata)])
},
```

That map has **no `text` key**. Downstream:

```rust
// src/client/context/context_creator.rs:249-250
let text = item.get("text").and_then(|v| v.as_str()).unwrap_or("");
let vector = embedder.embed(text)?;
```

So every unknown file — every `.png`, every `.git` object, every `.so` — contributes **one data point
whose embedding is the embedding of the empty string**. All of them are byte-identical vectors. On a
real repository that is potentially thousands of identical points crowding the HNSW graph, degrading
its neighbour lists, and competing for the top-5 on any query whose embedding happens to sit near the
empty-string vector. The user docs note the behaviour (`docs/knowledge-management.md:136`) but not
the consequence, and the same docs contradict themselves 160 lines later with "Binary files are
ignored during indexing" (`:298`).

**Non-UTF-8 content in an allowlisted extension is dropped silently.** `fs::read_to_string`
(`file_processor.rs:132`) fails on invalid UTF-8, and the caller discards the error without logging:

```rust
// src/client/background/file_processor.rs:141-144
match process_file_with_config(path, Some(self.config.chunk_size), Some(self.config.chunk_overlap)) {
    Ok(mut file_items) => items.append(&mut file_items),
    Err(_) => continue,
}
```

A latin-1 `.txt`, or a `.log` with one stray byte, vanishes from the index with no diagnostic. That
`continue` also swallows PDF extraction failures and permission errors.

**Prose vs code:** the only difference is the `language` metadata key on `Code` files
(`file_processor.rs:160-170`). It is written into the payload and **never read** — no retrieval path
filters or boosts on it. `Markdown` gets no special handling at all; heading structure is discarded
by the whitespace chunker like everything else.

---

## 6. Update and staleness — **the answer is: there is none**

This was the question of most interest, so the negative result is stated precisely.

**Searches performed over `crates/semantic-search-client/src/`:**
`mtime`, `modified`, `SystemTime` on file metadata, `notify`, `watch`, `stale`, `refresh`, `reindex`,
`re-index`, `incremental`, `update_context`, `sync_`, `hash` (outside the model validator),
`sha` (outside the model validator), `dirty`, `version`, `etag`.

**Result: the crate contains no mechanism for detecting, recording, or reacting to a file changing
underneath a built index.** There is no file watcher (`notify` is not a dependency — see
`Cargo.toml:13-41`), no mtime capture, no content hash, no per-file record of any kind. The stored
payload per chunk is `text`, `path`, `file_type`, `chunk_index`, `total_chunks`, and optionally
`language` (`file_processor.rs:152-169`) — nothing that could witness a change.

**There is no notion of a stale entry.** `KnowledgeContext` carries an `updated_at` field
(`types.rs:88`), and grepping the whole crate for it returns exactly two hits: the declaration, and
`updated_at: now` in the constructor (`types.rs:131`). **It is written once at creation and never
touched again** — including by the delete-and-rebuild refresh path, which creates a *new* context
with a *new* UUID, so even the creation timestamp does not survive a refresh as a refresh timestamp.
Nothing reads it.

**The client exposes no update method.** The public surface of `AsyncSemanticSearchClient` is:
`with_config`, `new`, `new_with_default_dir`, `get_default_base_dir`, `add_context`, `get_contexts`,
`search_all`, `search_context`, `cancel_*` (4), `find_operation_by_short_id`, `list_operation_ids`,
`get_status_data`, `clear_all`, `clear_all_immediate`, `remove_context_by_id`, `get_context_by_path`,
`get_context_by_name`, `list_context_paths`. No update, no refresh, no partial add.

**Refresh is therefore destroy-and-rebuild, driven by a human typing a command.** Following the call
one level into `chat-cli`:

```rust
// crates/chat-cli/src/util/knowledge_store.rs:502-519 (abridged)
pub async fn update_by_path(&mut self, path_str: &str) -> Result<String, String> {
    if let Some(context) = self.agent_client.get_context_by_path(path_str).await {
        // Remove the existing context first
        self.agent_client.remove_context_by_id(&context.id).await.map_err(|e| e.to_string())?;
        // Then add it back with the same name and original patterns (agent scope)
        let options = AddOptions {
            description: None,
            include_patterns: context.include_patterns.clone(),
            exclude_patterns: context.exclude_patterns.clone(),
            embedding_type: None,
        };
        self.add(&context.name, path_str, options).await
```

`remove_context_by_id` deletes the on-disk directory outright (`context_manager.rs:347-352`). The
three variants (`update_by_path`, `update_context_by_id`, `update_context_by_name`) are the same
shape. The user docs confirm this is the whole story — `/knowledge update <path>` is the only refresh
verb (`docs/knowledge-management.md:145-149`), and the guidance is simply "Regularly review and
update outdated contexts" (`:271`) with the Limitations section conceding "No automatic cleanup of
old or unused contexts" (`:312`).

**The rebuild is not atomic.** Remove happens first and takes effect immediately; the re-index is
queued to the background worker. Between the two, the context does not exist and searches silently
return nothing for it. If the re-index then fails — path gone, over `max_files`, an embedding error —
**the old index is already destroyed and there is no rollback.** A refresh is a strictly destructive
operation with a window of total unavailability proportional to corpus size.

**Consequence for a consumer.** Between refreshes, retrieved chunks are the text as it was at index
time, with no timestamp, no file hash, and no line anchors. A consumer cannot tell whether a returned
chunk still exists on disk, has moved, or has been rewritten — it cannot even check cheaply, because
the payload records no offsets to check against. The failure is exactly the shape Zikaron's D11
worries about: nothing fails loudly, the answer is just quietly wrong, and the only repair mechanism
is a human noticing and re-running a destructive rebuild.

---

## 7. Concurrency and lifecycle

**Topology.** One `tokio::spawn`'d `BackgroundWorker::run` per client, fed by an **unbounded** mpsc
channel (`async_implementation.rs:90`, `:101`). `add_context` validates, registers an
`OperationHandle`, and returns `(Uuid, CancellationToken)` immediately (`async_implementation.rs:267-319`).

**The worker is strictly serial, and `MAX_CONCURRENT_OPERATIONS` is therefore vacuous.**

```rust
// src/client/background/background_worker.rs:71-100 (abridged)
while let Some(job) = self.job_rx.recv().await {
    match job {
        IndexingJob::AddDirectory { .. } => { self.process_add_directory(id, params, cancel).await; },
        IndexingJob::Clear { id, cancel } => { self.process_clear(id, cancel).await; },
    }
}
```

The loop `await`s each job to completion before receiving the next, so at most one job is ever in
flight. `process_add_directory` nevertheless acquires a permit from a `Semaphore::new(3)`
(`background_worker.rs:26`, `:61`, `:120-148`) that cannot be contended; the entire try-acquire /
fall-back-to-blocking-acquire ladder and the "Waiting for available slot (max 3 concurrent)…" message
are unreachable. `SystemStatus::max_concurrent` reports 3 to the UI
(`operation_manager.rs:236`) — a number the system does not implement.

**Blocking work is inconsistently offloaded.** File *counting* is correctly wrapped:

```rust
// src/client/background/file_processor.rs:38
let count_result = tokio::task::spawn_blocking(move || { ... }).await;
```

File *processing* is not: `process_directory_files` (`file_processor.rs:95-161`) runs
`fs::read_to_string`, PDF extraction and chunking **directly on the async task**, with `.await`
points for progress interleaved. Embedding is worse — `ContextCreator::create_semantic_context`
(`context_creator.rs:176-195`) runs the BERT forward pass inline on the runtime thread. A large
indexing job starves whatever else that worker thread was going to run.

**Progress reporting is a shared map mutated best-effort.** Every update is `try_write` +
`try_lock`, and a failure is silently dropped:

```rust
// src/client/background/background_worker.rs:372-380
async fn update_operation_progress(&self, operation_id: Uuid, current: u64, total: u64, message: String) {
    if let Ok(mut operations) = self.operation_manager.get_active_operations_ref().try_write() {
        if let Some(operation) = operations.get_mut(&operation_id) {
            if let Ok(mut progress) = operation.progress.try_lock() {
                progress.update(current, total, message);
            }
        }
    }
}
```

Updates fire every 10 files (`file_processor.rs:148`) and every 10 items during embedding
(`context_creator.rs:181`). A contended moment loses the update entirely, so displayed progress can
sit still while work proceeds.

**Operation state is encoded in a human-readable string and recovered by substring matching.** There
is no state enum. Three separate places parse the progress *message*:

```rust
// src/client/context/context_manager.rs:200-205
let is_cancelled = progress.message.contains("cancelled");
let is_failed = progress.message.contains("failed") || progress.message.contains("error");
let is_completed = progress.message.contains("complete");
if !is_cancelled && !is_failed && !is_completed { return Err(...("Already indexing this path: ...")) }
```
```rust
// src/client/operation/operation_manager.rs:240-248
fn is_operation_waiting(progress: &ProgressInfo) -> bool {
    progress.message.contains("Waiting") || progress.message.contains("queue")
        || progress.message.contains("slot") || progress.message.contains("write access")
        || progress.message.contains("Initializing") || progress.message.contains("Starting")
        || (progress.current == 0 && progress.total == 0 && !progress.message.contains("complete"))
}
```

Indexing a directory whose *name* contains "complete" or "error" changes control flow, because the
path is interpolated into some of these messages.

**Cancellation** is `tokio_util::CancellationToken`, checked at eight points on the indexing path
(`background_worker.rs:112,174,189,220,237`; `context_creator.rs:89,100,120,166,177,197`;
`file_processor.rs:65,127`) plus a poll every 100 counted files inside the blocking count task
(`file_processor.rs:62-75`). Granularity is per file during walking and per chunk during embedding,
so cancellation latency is bounded by one file read or one forward pass. `cancel_operation` also
calls `task_handle.abort()` (`operation_manager.rs:75-77`) — but `OperationHandle.task_handle` is
**always constructed as `None`** (`operation_manager.rs:61`) and nothing ever sets it, so the abort
branch is dead. Cancellation is cooperative only.

**Cancellation leaks.** On a cancelled or failed run the partially-created context directory
(`background_worker.rs:185`) is never removed — `perform_indexing` returns `Err` and no cleanup runs.

**If the process dies mid-index: the work is lost, and a directory is orphaned.** The order is
(1) create `<base>/<uuid>/`, (2) walk and chunk everything into memory, (3) embed everything into
memory, (4) `semantic_context.save()` writes `data.json`, (5) `store_context_metadata` inserts into
the in-memory map and writes `contexts.json` (`background_worker.rs:185`, `:224`, `:243`, `:256`;
`context_creator.rs:209`). A crash before step 4 loses everything and leaves an empty directory. A
crash *between* 4 and 5 leaves a fully-written `data.json` that `contexts.json` never references —
and since `load_persistent_contexts` iterates the **keys of `contexts.json`**
(`context_manager.rs:238-251`), that directory is invisible forever. **There is no orphan scan, no
recovery pass and no GC.**

**No file locking, and the metadata write is non-atomic.**

```rust
// src/client/utils.rs:101-105
pub fn save_json_to_file<T: serde::Serialize>(path: &Path, data: &T) -> Result<()> {
    let json = serde_json::to_string_pretty(data)?;
    fs::write(path, json)?;
    Ok(())
}
```

`grep flock\|fs2\|advisory\|LockFile` over `src/`: zero hits. `fs::write` truncates then writes, with
no temp-file-and-rename. And the read side turns any parse failure into an empty knowledge base
**silently**:

```rust
// src/client/utils.rs:116-122
pub fn load_json_from_file<T: serde::de::DeserializeOwned + Default>(path: &Path) -> Result<T> {
    if path.exists() {
        let json_str = fs::read_to_string(path)?;
        Ok(serde_json::from_str(&json_str).unwrap_or_default())
    } else {
        Ok(T::default())
    }
}
```

Composing those: two `q chat` processes running the same agent share
`~/.aws/amazonq/knowledge_bases/<agent>/contexts.json` with no lock. Interleaved writes, or a crash
mid-`fs::write`, produce a truncated file; the next start parses it, hits `unwrap_or_default()`, and
reports **zero contexts with no error** while every context directory still sits on disk, now
unreachable. That is the same silent-truncation failure class Zikaron already recorded against
`cp memory.db` — the copy opens cleanly and answers every query, and nothing announces the loss.

**Search-time locking is try-lock with short timeouts, so heavy indexing makes search lie.**
`search_semantic_context` takes a 100 ms timeout on the contexts map and then `try_lock` on the
context; a failed `try_lock` returns `Ok(None)` (`context_manager.rs:165-183`), which is
indistinguishable from "no results". `get_contexts` degrades to an empty vector after 2 s with a
`warn!` (`context_manager.rs:62-72`). Because the worker holds the context mutex for the whole
`add_data_points` call, **a search issued during indexing can silently return nothing.**

---

## 8. Scale and performance

**There are no measured numbers in this repository.** The benchmark harness exists
(`src/embedding/benchmark_utils.rs`, `src/embedding/benchmark_test.rs`) but it `println!`s and
asserts nothing, and it is skipped unless `MEMORY_BANK_USE_REAL_EMBEDDERS` is set and skipped again
if `CI` is set (`benchmark_test.rs:16-30`). Its fixture is five hardcoded sentences
(`benchmark_utils.rs:14-22`). No results are committed anywhere.

**Asserted (not measured) numbers** all live in prose, and several are wrong:
- `README.md:23,481,556` and `docs/knowledge-management.md` imply a 5,000-file default; the code says
  **10,000** (`config.rs:93`). The doc comment *inside* `config.rs` also says 5,000 (`config.rs:42`),
  directly above the field whose default is 10,000 — the mismatch is three lines apart in one file.
- `README.md:556-559` gives RAM guidance (8 GB → 5-10k files, 16 GB → 10-20k, 32 GB+ → 20k+) with no
  cited measurement.
- `README.md:565`: "Indexing Time: Larger file counts increase indexing time exponentially" — the
  implementation is linear in chunks with HNSW's `O(n log n)` build; the claim is not derived from
  anything.
- `README.md:16,563,569`: Metal hardware acceleration — contradicted by `candle.rs:292-296`.
- `README.md:21`: "Memory Efficient: Stream large files and directories without excessive memory
  usage" — nothing streams; see the accumulation chain below.

**Caps and limits that actually exist:** `max_files` = 10,000, checked *before* indexing on the
counted total (`background_worker.rs:204`). That is all. No byte cap, no chunk cap, no index-size cap,
no per-file cap.

**Structural cost, derived from the code rather than measured:**

*Peak memory during an index* is the sum of, held simultaneously: the full `Vec<serde_json::Value>`
of every chunk of every file (`file_processor.rs:114`, `:142`), plus the full `Vec<DataPoint>` with
every 384-float vector (`context_creator.rs:173`, `:194`), plus the `SemanticContext.data_points`
copy after `extend` (`semantic_context.rs:95`), plus the HNSW graph. Nothing is flushed incrementally;
`save()` happens once at the end (`context_creator.rs:209`).

*On-disk size* is dominated by JSON-encoded floats. 384 `f32` printed as decimal is roughly 4-5 KB per
chunk against 1,536 bytes of actual float data, plus a second full copy of the chunk text in the
`text` payload.

*Startup cost* is a full JSON parse plus a complete HNSW rebuild for **every** persistent context, on
the calling task, before the client is usable (`async_implementation.rs:112` →
`context_manager.rs:238-251` → `semantic_context.rs:44-53`).

**The most avoidable performance defect: embedding is one text per forward pass.** `embed_batch`
exists, is rayon-parallel over `par_chunks(batch_size)` with `batch_size = 32`
(`candle.rs:158-161`, `candle_models.rs:70`) — and the indexing path never calls it. It calls
`embed` per item, in a serial `for` loop:

```rust
// src/client/context/context_creator.rs:176-195 (abridged)
for (i, item) in items.iter().enumerate() {
    ...
    let data_point = Self::create_data_point_from_item(item, i, embedder)
        .map_err(|e| format!("Failed to create data point: {}", e))?;
    data_points.push(data_point);
}
```
```rust
// src/client/context/context_creator.rs:249-250
let text = item.get("text").and_then(|v| v.as_str()).unwrap_or("");
let vector = embedder.embed(text)?;
```

and `embed` wraps the single text in a one-element `Vec` before delegating (`candle.rs:130-139`). So
every chunk is a batch of one: no batching, no rayon parallelism, and `prepare_tokenizer` is cloned
and reconfigured **once per chunk** (`candle.rs:152`). On a corpus of N chunks that is N sequential
forward passes on one CPU thread where 32-wide batches were available. It is also, incidentally, the
only reason the unmasked-mean-pooling bug of §1 does not corrupt the stored vectors.

---

## 9. Known limitations — what the authors say, and what the tests actually pin

**Self-declared.** Searching `TODO|FIXME|HACK|XXX|unimplemented|todo!` across `src/` and `tests/`
(excluding the two orphaned files) yields **one** genuine admission, quoted in full in §3:
`bm25_index.rs:99-101`, "This is a limitation - we'd need to track documents separately". That is the
crate's entire self-critique.

**Undeclared but visible in the code** — collected from the sections above:
- `src/embedding/onnx.rs` and `src/embedding/tf.rs` are never compiled (`embedding/mod.rs:1-9`).
- The sync `SemanticSearchClient` (1,056 lines, `src/client/implementation.rs`) is **dead in
  production**: `grep -rn SemanticSearchClient crates/ --include=*.rs` outside this crate finds only
  `AsyncSemanticSearchClient` (`crates/chat-cli/src/util/knowledge_store.rs:9,138,277`).
- `SemanticSearchConfig::timeout` and `::model_name` are never read (§1).
- `OperationHandle::task_handle` is always `None`, making the abort path dead (`operation_manager.rs:61`).
- `MAX_CONCURRENT_OPERATIONS` is unreachable (§7).
- The `language` payload key is written and never read (§5).
- `update_config` can only take effect before first use — `CONFIG` is a `OnceLock` and the code says
  so: "Otherwise, we need to restart the application to apply changes" (`config.rs:269-271`).

**Documentation that contradicts the code** (relevant because these are the statements a reader would
otherwise trust): ONNX/Metal (`README.md:139,569`), 5,000-file default (`README.md:23` etc.),
`set_chunk_size`/`set_chunk_overlap`/`with_embedding_type`/`EmbeddingType::Onnx`/`::Candle`/`::BM25`
(`README.md:156-158`, `:382-401`) — **none of these APIs exist**; `AddContextRequest` examples omit
its `embedding_type` field; per-platform default base dirs (`async_implementation.rs:196-200` claims
`~/Library/Application Support/semantic-search` etc. while `config.rs:108-112` says
`~/.semantic_search` on every platform); `bm25_data.json` vs the real `data.bm25.json`
(`docs/knowledge-management.md:193` vs `context_manager.rs:34`); "Binary files are ignored during
indexing" (`docs/knowledge-management.md:298`) versus the same document's own line 136; and
"Context persistence is determined automatically based on usage patterns"
(`docs/knowledge-management.md:261`) — **there is no such mechanism**; `persistent` is a boolean the
caller supplies (`types.rs:30`).

### What the tests pin

Seven integration files (`tests/`, ~900 lines) plus inline `#[cfg(test)]` modules. Read end to end,
they pin **plumbing and nothing else**.

**Every default test run uses a hash, not an embedder.** `MockTextEmbedder` seeds all 384 dimensions
from one `u32`:

```rust
// src/embedding/mock.rs:29-37
// Use a simple hash of the text to seed the embedding values
let hash = text.chars().fold(0u32, |acc, c| acc.wrapping_add(c as u32));

for i in 0..self.dimension {
    // Generate a deterministic but varied value for each dimension
    let value = ((hash.wrapping_add(i as u32)).wrapping_mul(16807) % 65536) as f32 / 65536.0;
    embedding.push(value);
}
```

A sum of char codes is **anagram-invariant**, and since every dimension is a fixed function of that
one scalar, the whole vector space collapses to a 1-D curve — "nearest neighbour" means "closest
character sum". The real embedder runs only under `MEMORY_BANK_USE_REAL_EMBEDDERS`, and even then
only in the benchmark, which asserts nothing. **No test in the crate asserts that a semantically
relevant document outranks an irrelevant one.**

**Three tests are vacuous.** The clearest:

```rust
// tests/test_vector_index.rs:3-10
#[test]
fn test_vector_index_creation() {
    let index = VectorIndex::new(384); // 384-dimensional vectors
    // Verify the index was created successfully
    assert!(!index.is_empty() || index.is_empty());
}
```

`p || !p` — a tautology that cannot fail. (The comment is also wrong: `VectorIndex::new` takes
`max_elements`, not a dimension; `VectorIndex` has no dimension parameter.) Next:

```rust
// tests/test_vector_index.rs:44-54
let results = index.search(&query, 2, 100);
assert!(results.len() <= 2); // May return fewer results than requested
if !results.is_empty() {
    assert!(results[0].0 <= 2);
}
```

An upper bound only, guarded by `if !is_empty()` — a `search` that returns nothing passes. And:

```rust
// tests/test_file_processor.rs:103-117 (abridged)
let test_file = temp_dir.join("test.bin");
fs::write(&test_file, [0xff, 0xfe, 0x00, 0x01, 0x02]).unwrap();
let result = process_file(&test_file);
if let Ok(items) = result {
    if !items.is_empty() {
        let text = items[0].get("text").and_then(|v| v.as_str()).unwrap_or("");
        assert!(text.is_empty() || text.contains("\u{fffd}"));
    }
}
```

Doubly guarded — an `Err`, or an empty vector, both pass. Worse, it never reaches the code it names:
`.bin` is not in the allowlist, so `get_file_type` returns `Unknown` and the file is **never read**.
The "binary file" test does not exercise binary handling.

`tests/test_semantic_search_client.rs:66-67` has the one assertion that would have measured
retrieval, **commented out**: `// assert!(!results.is_empty());` with the note "Don't assert on
results being non-empty as it depends on the embedder implementation".

**What is genuinely pinned:** file-type classification (`file_processor.rs:251-296`, a good table
test), chunk count and overlap arithmetic (`text_chunker.rs:88-107`), config round-tripping
(`config.rs:284-390`), pattern include/exclude semantics (`pattern_filter.rs:94-140`), mock-embedder
determinism and normalisation (`mock.rs:69-112`), save/load round-trip of a `SemanticContext`
(`test_semantic_context.rs`), and the async add-then-search happy path (`test_async_client.rs`).

**What is pinned nowhere:** ranking quality; the BM25 arm end-to-end; the cross-context ordering
of §4; the `avgdl` mismatch; cancellation; crash recovery; concurrent access; the chunk-overlap
underflow; the >512-token chunk; any behaviour of the real embedder.

---

## The `knowledge_beta_improvements_agents` directory

**It is not a directory and it is empty.**

```
$ file knowledge_beta_improvements_agents
knowledge_beta_improvements_agents: empty
$ ls -la knowledge_beta_improvements_agents
-rw-rw-r-- 1 nathan nathan 0 Sep 14 16:32 knowledge_beta_improvements_agents
```

A **0-byte regular file** at the repository root, committed as part of the single commit this clone
carries (`git log --diff-filter=A` → `15cc8f3cd18c4272925ce1c7053268eedff1ea0a 2026-04-23 Zoe Lin
"Update README to include issue reporting link (#3775)"`). It is not in `.gitignore`. It contains
nothing, so it states no intent, no known problems and no roadmap. The name suggests a working
directory that was `git add`ed while empty, or a stray `touch`; **the clone is shallow
(`git rev-list --count HEAD` = 1, `.git/shallow` present)**, so the commit that actually introduced it
is not available here and its history is **not determined**. A full clone would settle it.

**The design/intent material the brief was probably after is `docs/knowledge-management.md`
(354 lines)** — the user-facing feature documentation, and the only place the feature's intent is
written down. What it contributes beyond the code:

- **The feature is beta and off by default**: `q settings chat.enableKnowledge true` (`:12-14`).
- **Positioning of the two modes** (`:53-77`): `Fast`/BM25 is recommended for *"Large codebases"*
  ("Fast symbol and function searches") and logs/configs; `Best`/semantic for documentation and
  research. So AWS's own guidance for the code-indexing case is **lexical, not dense** — which,
  given §1's truncation gap and §2's whitespace chunker, reads as a quiet acknowledgement that the
  dense arm is not good at code.
- **Per-agent isolation** (`:177-235`): one store per agent under
  `~/.aws/amazonq/knowledge_bases/<agent>/`, no cross-agent access, legacy stores auto-migrated.
- **Settings surface** (`:166-175`): `knowledge.maxFiles`, `.chunkSize`, `.chunkOverlap`,
  `.indexType`, `.defaultIncludePatterns`, `.defaultExcludePatterns`.
- **A Limitations section** (`:294-313`), which is the closest thing to a roadmap in the repository:
  *"Very large files may be chunked, potentially splitting related content"*; *"No explicit storage
  size limits, but practical limits apply"*; **"No automatic cleanup of old or unused contexts"**;
  *"Clear operations are irreversible with no backup functionality"*.
- **Staleness is explicitly the user's job** (`:271`): "Regularly review and update outdated
  contexts", with `/knowledge update <path>` (`:145-149`) the only verb.

Its errors are catalogued in §9. There is no ADR, no design doc, and no roadmap file anywhere in the
repository for this feature — `find . -iname "*knowledge*"` returns the empty file, this doc, and
three `chat-cli` source files.

---

## Reusable for Zikaron / deliberately not

### Copy

**1. The SHA256 model allowlist that deletes on mismatch.** `src/model_validator.rs:28-70`. One pinned
hash per file, verified before use, invalid file removed so the next run re-downloads. Zikaron pulls
`bge-small-en-v1.5` through fastembed and currently trusts whatever lands in the cache. The Python
equivalent is ~20 lines and it closes a supply-chain hole that D19/D20 leave open. It also pins
`tokenizer.json`, which makes tokenizer-dependent bounds provable rather than assumed — directly
relevant to the `GIST_MAX_CHARACTERS` argument, where the deployed WordPiece vocabulary's behaviour
is load-bearing.

**2. Model download separated from model use, with the artefact identity checked at the boundary.**
`ensure_model` validates first and downloads only on failure (`hosted_model_client.rs:87-101`).
Zikaron's M17 landed a background-loading encoder that validates the artefact against the store's
recorded identity *inside the loader thread*; this crate's split is the same instinct applied one
level up, at acquisition rather than at load, and the two compose.

**3. `CancellationToken` checked at named points, with the check density stated.** Eight checks on
the indexing path at file and chunk granularity (§7). If Zikaron ever adds a long-running index, this
is the right shape: a cooperative token, checks at documented granularities, and a bounded
cancellation latency you can state in a design doc. **Do not** copy the `task_handle.abort()`
half — it is dead here because nothing ever populates the field, which is itself the lesson: an
abort path that is never constructed looks like a safety net and is not one.

**4. Recording include/exclude patterns *in the context metadata* so a refresh reuses them**
(`types.rs:96-102`, consumed at `knowledge_store.rs:544-548`). Cheap, and it makes "rebuild this the
way it was built" a real operation rather than a thing the user must remember.

**5. As a negative control: the failure modes are worth the read even though the code is not.** Six
of them are exactly Zikaron's own recorded hazards, arrived at independently — silent truncation on a
non-atomic write, vacuous tests that cannot fail, documentation asserting what the adjacent code
contradicts, a config field that is read by nothing, a constant whose name lies about its meaning
(`DEFAULT_BM25_SCORE` for an average document length), and a "safety" limit that cannot be reached.
That convergence is itself evidence that FINDINGS' "read the changed passage end to end after
editing" rule is catching a real and common class rather than a local quirk.

### Deliberately not

**1. Word-count chunking.** 512 whitespace words against a 512-token model is a unit mismatch that
either truncates silently or fails the whole run (§1, §2), and `join(" ")` destroys indentation and
line structure. Zikaron already chunks on **tokens** (`chunk_max_tokens` 450, D28) and already has
the measurement this crate lacks — 162-879 tokens, median 273 over 93 authored writes. Keep the token
unit; treat this as a worked example of why.

**2. Serialising float vectors as JSON.** 4-5 KB per 384-dim vector, plus a full re-parse and a full
HNSW rebuild at every startup (§3). sqlite-vec already gives Zikaron binary storage and a persisted
index; this is the alternative measured in the negative.

**3. Rebuilding the ANN graph at every process start.** Startup is `O(chunks)` HNSW inserts before
the client is usable (`async_implementation.rs:112`). Zikaron's cold-start budget is 1.2 s against a
hook deadline, and M17 spent a whole milestone moving a 1,059 ms encoder load off that path. Adopting
a rebuild-on-open index would put the cost straight back, scaled by corpus size.

**4. One retrieval mode per store, chosen at index time.** D5 and the RRF work assume both arms over
one corpus; this crate makes them mutually exclusive per context, then orders across contexts with a
single ascending sort over two incomparable scales (§4). Zikaron's known fusion defect —
unweighted RRF discarding the dense arm's advantage (open question 2) — is a *tuning* problem inside
a sound structure. This is the structure being wrong.

**5. Extension allowlists as the only binary detection, and path-only entries for the rest.** Every
unsupported file contributes one data point embedding the **empty string** (§5), so a repository's
`.git` object store injects thousands of identical vectors into the graph. If Zikaron ever indexes
documents: sniff content, and **skip** what you cannot read rather than inserting a degenerate row.
A null entry is worse than no entry because it competes in the ranking.

**6. Encoding operation state in a display string and recovering it by substring match**
(`context_manager.rs:200-205`, `operation_manager.rs:240-248`). Zikaron's consolidation lease already
uses an explicit state machine with named transitions (`_PlanBridge`'s
`unplanned | ready | failed`); that is the right answer and this is the counterexample.

**7. Best-effort `try_lock` for both progress and search.** A failed `try_lock` here returns
`Ok(None)` from search — indistinguishable from "no results" (`context_manager.rs:165-183`). A memory
system that silently returns nothing under load is worse than one that says it is busy; Zikaron's
degrade-and-relay behaviour on the hook path (log to `hook.log`, relay on stdout) is the better
pattern and should not be traded for this.

**8. `fs::write` for the metadata index, with `unwrap_or_default()` on read.** Together these turn a
crash mid-write into a silent, total loss of the knowledge base with every context directory still on
disk (§7). Write temp-and-rename; make a parse failure **loud**. Zikaron has been burned by exactly
this class once already, and the entry in FINDINGS notes that what caught it was a human who did not
trust the snapshot — not any check the agent controlled.

### The staleness verdict, stated plainly

A shipped production code-indexing feature from AWS handles code changing under its index by **not
handling it**: no mtime, no hash, no watcher, no stale marker, no `updated_at` that is ever updated,
and a refresh that is a human-typed command performing an unguarded delete-then-rebuild with a
window of total unavailability and no rollback (§6). The stored chunk carries no timestamp and no
line offsets, so a consumer cannot even cheaply check whether what it was handed still exists.

Two things follow for Zikaron. First, D11 — repair in-band by the agent the memory misled — is not
the weak option it might look like next to a "real" invalidation scheme; it is **strictly more than
the state of the art in a shipped competitor**, which has no mechanism at all. Second, the specific
gap D11 already knows about (open question 6: it only fires when a memory surfaces, is acted on, and
fails *loudly*) is precisely the gap this crate leaves totally unaddressed — and this crate's version
is worse, because a stale code chunk fails *quietly* by construction. If Zikaron ever indexes code,
the minimum viable improvement over this baseline is cheap and worth pricing: **store a content hash
and the line span with each chunk**, so a consumer can verify at read time rather than trusting the
index. Neither is in this crate, and neither is expensive.
