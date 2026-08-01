"""
M0 spike 4 — fastembed cold vs warm, in this venv.

build-plan.md: "Confirm the 783 ms / 5.5 ms figures the architecture rests
on, and the on-disk footprint."

Which figures those are, precisely (there are several in design/, and the
briefer is compressing them, so this spike measures all of them rather
than guessing which one "5.5 ms" means):
  - D22 (overview.md): cold whole-process bge-small load+embed = 783 ms,
    contrasted against 0.26 ms warm BM25-only (no embedding at all) —
    the number behind "the hook must never load an embedding model".
  - D31 (overview.md): warm, UNPREFIXED = 5.45 ms embed / 7.97 ms full
    path. Warm, PREFIXED (the config D20 actually adopts) = 6.64 ms
    embed / 9.14 ms full path.
  - "5.5 ms" in FINDINGS.md open question 4 is closest to the unprefixed
    warm-embed figure (5.45 ms), so this spike measures both prefixed
    and unprefixed to settle which the shorthand refers to and confirm
    neither is stale.

"Cold" here means the FIRST embed call in a fresh process — model load +
ONNX session init + first inference — since that is what a hook process
would pay if it ever loaded a model (which D22 forbids; this spike exists
to confirm the number that forbids it). "Warm" means every call after
that, in the same process.

On-disk footprint: not stated anywhere in design/ — genuinely new ground,
not a figure to cross-check.

Throwaway per build-plan.md's M0 fence.
"""

import os
import statistics
import time

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
N_WARM = 50

SAMPLE_DOC = (
    "the protobuf codegen step fails silently on the staging cluster when the "
    "proto compiler version drifts from the one pinned in requirements.txt"
)
SAMPLE_QUERY = "why does protobuf codegen fail on staging"


def measure_cold_and_warm() -> None:
    t0 = time.perf_counter()
    from fastembed import TextEmbedding  # import cost is part of "cold" for a hook process

    t_import = time.perf_counter() - t0
    print(f"import fastembed: {t_import * 1000:.2f} ms")

    t0 = time.perf_counter()
    model = TextEmbedding(model_name=MODEL_NAME)
    t_construct = time.perf_counter() - t0
    print(f"TextEmbedding(model_name=...) construction (downloads/loads ONNX session): {t_construct * 1000:.2f} ms")

    # First embed call — this is the true "cold" cost a hook process would
    # pay if it ever embedded anything: import + construct + first inference.
    t0 = time.perf_counter()
    list(model.embed([SAMPLE_DOC]))
    t_first_embed = time.perf_counter() - t0
    t_cold_total = t_import + t_construct + t_first_embed
    print(f"\nFirst embed() call (unprefixed doc text): {t_first_embed * 1000:.2f} ms")
    print(f"COLD TOTAL (import + construct + first embed): {t_cold_total * 1000:.2f} ms  <- compare to design's 783 ms")

    # Discard several more calls beyond the first to let the ONNX runtime
    # fully settle (thread pool, memory arena) before measuring either
    # condition.
    for _ in range(5):
        list(model.embed([SAMPLE_DOC]))

    # Controlled comparison: the SAME base text, prefixed vs. unprefixed,
    # interleaved call-by-call. An earlier version of this measurement
    # compared a long document against a short query+prefix — different
    # base text on each side — which is confounded: the "prefixed"
    # condition embedded FEWER total characters despite the added prefix
    # (98 vs 142), so it looked faster for a reason that had nothing to
    # do with the prefix. Holding the base text constant isolates the
    # prefix's actual cost, which is what D20's figure is about.
    warm_unprefixed_ms = []
    warm_prefixed_ms = []
    prefixed_query = QUERY_PREFIX + SAMPLE_QUERY
    for _ in range(N_WARM):
        t0 = time.perf_counter()
        list(model.embed([SAMPLE_QUERY]))
        warm_unprefixed_ms.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        list(model.embed([prefixed_query]))
        warm_prefixed_ms.append((time.perf_counter() - t0) * 1000)

    def summarize(label: str, values: list[float]) -> None:
        values = sorted(values)
        n = len(values)
        print(
            f"{label}: mean={statistics.mean(values):.3f}ms "
            f"p50={statistics.median(values):.3f}ms "
            f"p95={values[int(n * 0.95)]:.3f}ms "
            f"min={values[0]:.3f}ms max={values[-1]:.3f}ms  (n={n})"
        )

    print(f"\nWarm embed() over {N_WARM} calls, controlled comparison (SAME query text, prefix isolated):")
    summarize("  unprefixed query text", warm_unprefixed_ms)
    summarize("  prefixed query text  ", warm_prefixed_ms)
    prefix_cost_ms = statistics.mean(warm_prefixed_ms) - statistics.mean(warm_unprefixed_ms)
    print(f"  prefix cost (mean prefixed − mean unprefixed): {prefix_cost_ms:+.3f} ms")
    print("  <- compare to design's measured prefix cost, +1.19 ms (retrieval.md)")

    # Separate measurement: embedding DOCUMENT-length text (D31's warm-embed
    # figures are about write-side content, which runs longer than a query
    # and receives no prefix under BGE's asymmetric convention — so this is
    # a different, also real, data point, not a repeat of the controlled
    # comparison above.
    warm_doc_ms = []
    for _ in range(N_WARM):
        t0 = time.perf_counter()
        list(model.embed([SAMPLE_DOC]))
        warm_doc_ms.append((time.perf_counter() - t0) * 1000)
    print(f"\nWarm embed() over {N_WARM} calls, document-length text (no prefix, per BGE's asymmetric convention):")
    summarize("  document text", warm_doc_ms)
    print("  <- compare to design's D31 warm-embed figures, 5.45 ms (unprefixed) / 6.64 ms (prefixed)")

    # Sanity: confirm the vector actually has the expected width and looks
    # like a real embedding (non-degenerate, finite).
    vec = list(model.embed([SAMPLE_DOC]))[0]
    print(f"\nEmbedding dim: {len(vec)}  (expect 384 for bge-small-en-v1.5)")
    print(f"Sample values: {vec[:5].tolist() if hasattr(vec, 'tolist') else vec[:5]}")


def measure_disk_footprint() -> None:
    # fastembed's cache path is NOT ~/.cache/huggingface's hub layout —
    # that directory only holds a small config/tokenizer blob. The actual
    # ONNX weights live under fastembed's own default cache directory,
    # confirmed here by asking a live TextEmbedding instance rather than
    # guessing a path, since guessing HF-hub-style paths first pointed at
    # the wrong (much smaller) directory.
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL_NAME)
    cache_dir = getattr(model.model, "cache_dir", None)
    print("\n=== On-disk footprint ===")
    print(f"fastembed's actual cache_dir (asked the live model instance): {cache_dir}")

    candidates = [
        cache_dir,
        os.path.expanduser("~/.cache/huggingface"),
        os.environ.get("HF_HOME", ""),
        os.environ.get("FASTEMBED_CACHE_PATH", ""),
    ]
    seen_paths = set()
    for path in candidates:
        if not path or path in seen_paths or not os.path.isdir(path):
            continue
        seen_paths.add(path)
        seen_inodes: set[tuple[int, int]] = set()
        total_bytes = 0
        file_count = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    st = os.stat(fpath)
                    key = (st.st_dev, st.st_ino)
                    if key in seen_inodes:
                        continue
                    seen_inodes.add(key)
                    total_bytes += st.st_size
                    file_count += 1
                except OSError:
                    pass
        if file_count > 0:
            print(f"{path}: {total_bytes / (1024 * 1024):.2f} MiB across {file_count} unique files (deduped by inode; whole cache dir, may hold other models)")

    # Narrow to just this model's own subdirectory, which is the number
    # that actually answers "what does deploying this model cost on disk".
    #
    # Dedupe by inode: HF hub's cache layout stores each file once under
    # blobs/<hash> and SYMLINKS it into snapshots/<rev>/<name> — walking
    # both and summing os.path.getsize() on each double-counts the large
    # weight file (it appeared once as the blob, once as the symlink
    # target's resolved size), inflating 64 MiB to a bogus 128 MiB. `du`
    # gets this right by default; matching that here by tracking
    # (st_dev, st_ino) and counting each real file once.
    if cache_dir and os.path.isdir(cache_dir):
        for entry in os.listdir(cache_dir):
            if "bge-small" in entry.lower():
                model_dir = os.path.join(cache_dir, entry)
                seen_inodes: set[tuple[int, int]] = set()
                file_list: list[tuple[str, int]] = []
                for root, _dirs, files in os.walk(model_dir):
                    for f in files:
                        fpath = os.path.join(root, f)
                        st = os.stat(fpath)  # follows symlinks, resolves to the real blob
                        key = (st.st_dev, st.st_ino)
                        if key in seen_inodes:
                            continue
                        seen_inodes.add(key)
                        file_list.append((os.path.relpath(fpath, model_dir), st.st_size))
                total_bytes = sum(size for _, size in file_list)
                print(f"\nModel-specific directory: {model_dir}")
                print(f"Total (deduped by inode, matches `du`): {total_bytes / (1024 * 1024):.2f} MiB")
                print("Largest unique files:")
                for fname, fsize in sorted(file_list, key=lambda x: -x[1])[:5]:
                    print(f"  {fsize / (1024 * 1024):.2f} MiB  {fname}")


if __name__ == "__main__":
    measure_cold_and_warm()
    measure_disk_footprint()
