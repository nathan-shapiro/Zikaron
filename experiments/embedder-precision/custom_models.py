#!/usr/bin/env python
"""Round 4: register the artifacts fastembed 0.8.0 does not carry, under names nothing else uses.

Each gets its own name, so `EmbedCache`'s model-keyed cache cannot hand one artifact's vectors to
another. `bge-small-fp32` is BAAI's own unquantized export of the model fastembed ships quantized:
the control that separates *model* from *artifact* (round 2's threat 5).

Pooling and normalization are read off each repository's `1_Pooling/config.json` (checked
2026-09-29): granite and bge pool the CLS token, e5 pools the mean. Every one is L2-normalized.
Revisions are what `HfApi.model_info` reported at registration; `revisions()` reports what was
actually loaded, from the snapshot fastembed downloaded.
"""
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

CUSTOM = {
    # name: (repo, pooling, dim, model_file, expected revision)
    "zk/granite-embedding-30m-english": (
        "ibm-granite/granite-embedding-30m-english", PoolingType.CLS, 384, "model.onnx",
        "9b5b096411652ec1189c68fcfb90d0a82c5b45af"),
    "zk/granite-embedding-125m-english": (
        "ibm-granite/granite-embedding-125m-english", PoolingType.CLS, 768, "model.onnx",
        "4ab61ffd423be45cd932b21a7c696063d82bf45f"),
    "zk/e5-small-v2": (
        "intfloat/e5-small-v2", PoolingType.MEAN, 384, "model.onnx",
        "ffb93f3bd4047442299a41ebb6fa998a38507c52"),
    "zk/bge-small-en-v1.5-fp32": (
        "BAAI/bge-small-en-v1.5", PoolingType.CLS, 384, "onnx/model.onnx",
        "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"),
}

_done = False


def register() -> None:
    global _done
    if _done:
        return
    known = {m["model"] for m in TextEmbedding.list_supported_models()}
    for name, (repo, pooling, dim, model_file, _rev) in CUSTOM.items():
        if name in known:
            continue
        TextEmbedding.add_custom_model(
            model=name, pooling=pooling, normalization=True,
            sources=ModelSource(hf=repo), dim=dim, model_file=model_file)
    _done = True


register()
