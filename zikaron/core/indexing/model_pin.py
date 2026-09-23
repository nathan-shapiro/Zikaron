"""The embedding artefact this package is pinned to: which repository, which commit, which bytes.

**A hash set without a revision is not a pin.** `fastembed`'s own acquisition resolves
`model_info(<repo>).sha` — the repository's *current head* — and snapshot-downloads that, forwarding
no `revision`. So an allowlist of digests alone has a second mismatch cause that is not local
corruption: the first time upstream pushes any commit, every install fetches bytes that cannot
match, and does it again on the next service start, forever, 64 MB at a time. Owning the revision is
what makes a mismatch mean either a corrupt local copy or a source serving something else, and
nothing third.

**Pinning `tokenizer.json` is also what makes the tokenizer-dependent bounds provable rather than
assumed.** `chunk_max_tokens`, the gist character bound and the 512-token window arithmetic all rest
on a tokenizer that nothing pinned. This is the second reason the revision has to be pinned too: a
digest without one proves that the fetch will eventually fail, not that the artefact the bounds were
computed against is the artefact in use.

**Five files, not the repository's nine.** Measured 2026-09-23 against a warm cache: fastembed
fetches the five named below and leaves `.gitattributes`, `README.md`, `ort_config.json` and
`vocab.txt` where they are. Pinning those four would make the product download more than it runs.

**Keyed by the configured model name, because D20 keeps `embedding.embed_model` a config key.** A
model this table does not name falls through to fastembed's own unpinned acquisition, which is what
every install did before this module existed — so the supply-chain guarantee covers the shipped
default and **nothing reports when a store has configured its way out of it**. Closing that would
mean `doctor` reading a project's resolved config rather than this table.

**Weights are fetched, never redistributed** — an operator constraint, stricter than the licence.
Only the revision and the digests travel with this package. The artefact's own licence is
`apache-2.0`, read from the `qdrant` model card; the `BAAI` weights it is derived from are `mit`,
and the card states no reason for the difference.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class PinnedArtifact:
    """One model's identity on the Hub, and the bytes its files must hash to."""

    #: The configured `embedding.embed_model` value — fastembed's friendly name, not the repo.
    model_name: str
    #: The Hugging Face repository fastembed maps that name to.
    repo_id: str
    #: The full 40-character commit sha. **Never a tag and never a short form**: only a revision
    #: matching `REGEX_COMMIT_HASH` lets `snapshot_download` skip `repo_info` entirely, and anything
    #: else costs an HTTPS round-trip on every service start — which with the network down stalls
    #: on the request timeout before falling back.
    revision: str
    #: Filename to expected SHA256, for every file the model actually loads.
    digests: Mapping[str, str]

    @property
    def filenames(self) -> tuple[str, ...]:
        """The files to fetch, in a fixed order, as `allow_patterns` takes them."""
        return tuple(sorted(self.digests))


_BGE_SMALL_EN_V1_5: Final = PinnedArtifact(
    model_name="BAAI/bge-small-en-v1.5",
    repo_id="qdrant/bge-small-en-v1.5-onnx-q",
    revision="52398278842ec682c6f32300af41344b1c0b0bb2",
    digests=MappingProxyType(
        {
            "config.json": "13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd",
            "model_optimized.onnx": (
                "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"
            ),
            "special_tokens_map.json": (
                "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a"
            ),
            "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
            "tokenizer_config.json": (
                "0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53"
            ),
        }
    ),
)

PINNED_ARTIFACTS: Final[Mapping[str, PinnedArtifact]] = MappingProxyType(
    {_BGE_SMALL_EN_V1_5.model_name: _BGE_SMALL_EN_V1_5}
)


def pin_for(model_name: str) -> PinnedArtifact | None:
    """The pin for a configured model, or nothing if this package does not pin that one."""
    return PINNED_ARTIFACTS.get(model_name)
