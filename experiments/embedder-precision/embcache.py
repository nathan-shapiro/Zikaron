#!/usr/bin/env python
"""Disk cache for embeddings, keyed by (model, exact text). Makes round-2 iteration affordable.

Round 1 spent ~4 min per sweep re-embedding 187 documents with bge-large. Round 2 runs the sweep
many more times (factorial ablation x 2 depths x 2 query sets), so the embeddings are cached.

Cache identity is `sha256(model_name + "\\x00" + text)`. Model name is part of the key, so a
same-dimension model swap CANNOT silently reuse another model's vectors - the FINDINGS
open-question-5 hazard, avoided here by construction rather than by remembering.
"""
import hashlib
import pathlib

import numpy as np

CACHE = pathlib.Path(__file__).parent / "embcache"
CACHE.mkdir(exist_ok=True)


def _key(model: str, text: str) -> str:
    return hashlib.sha256((model + "\x00" + text).encode()).hexdigest()


class EmbedCache:
    def __init__(self, model: str, embedder):
        self.model = model
        self.embedder = embedder
        self.path = CACHE / (model.replace("/", "__") + ".npz")
        self.store = {}
        if self.path.exists():
            with np.load(self.path) as z:
                self.store = {k: z[k] for k in z.files}
        self.hits = 0
        self.misses = 0

    def embed(self, texts: list, normalize=True) -> np.ndarray:
        keys = [_key(self.model, t) for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts) if k not in self.store]
        uniq = dict(missing)
        if uniq:
            mk = list(uniq)
            vs = np.array(list(self.embedder.embed([uniq[k] for k in mk])), dtype=np.float32)
            for k, v in zip(mk, vs):
                self.store[k] = v
            self.misses += len(mk)
        self.hits += len(texts) - len(uniq)
        out = np.array([self.store[k] for k in keys], dtype=np.float32)
        if normalize:
            out = out / np.linalg.norm(out, axis=1, keepdims=True)
        return out

    def flush(self):
        np.savez_compressed(self.path, **self.store)
