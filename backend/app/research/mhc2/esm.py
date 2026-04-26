"""ESM-2 protein-language-model wrapper for the MHC-II Phase B model.

Loads ``facebook/esm2_t12_35M_UR50D`` (35M params, 480-dim per-residue
output) lazily, embeds amino-acid sequences, and persists per-residue
feature tensors to disk so training can read pre-computed features through
a `dict[str, Tensor]` lookup instead of running ESM at every step.

The cache is keyed by the *exact* upper-cased input sequence — case and
non-standard residues are stripped/replaced consistently, but the key the
training loop uses must match what the cache builder saw.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.research.mhc2.constants import MODEL_AMINO_ACIDS

ESM_MODEL_ID = "facebook/esm2_t12_35M_UR50D"
ESM_FEATURE_DIM = 480

# ESM-2 tokenizer accepts the 20 standard amino acids; X (unknown/gap) is
# mapped to <unk>. Pseudosequences contain X by design — that's fine, ESM
# treats it as a no-info residue and the adapter learns to cope.
_VALID_INPUT_RE = re.compile(rf"^[{MODEL_AMINO_ACIDS}]+$")


@dataclass(frozen=True)
class ESMCacheManifest:
    """Provenance the cache builder records alongside the .pt file."""

    model_id: str
    feature_dim: int
    n_sequences: int
    max_length: int
    source_files: tuple[str, ...]

    def to_json(self) -> dict:
        return {
            "model_id": self.model_id,
            "feature_dim": self.feature_dim,
            "n_sequences": self.n_sequences,
            "max_length": self.max_length,
            "source_files": list(self.source_files),
        }


def normalize_for_esm(sequence: str) -> str:
    """Uppercase + strip whitespace; raise on empty or invalid characters."""
    cleaned = sequence.strip().upper()
    if not cleaned or not _VALID_INPUT_RE.match(cleaned):
        raise ValueError(f"sequence is not a valid amino-acid string: {sequence!r}")
    return cleaned


def normalize_proteome_sequence(sequence: str) -> str:
    """Coerce a protein sequence into the ESM input alphabet by mapping any
    non-standard residue (e.g. ``U`` selenocysteine, ``B/Z/J`` ambiguous
    codes, ``O`` pyrrolysine, gaps, stop codons) to ``X``.

    The decoy generator accepts windows that contain only the 20 canonical
    amino acids, so it never produces a 9-mer at a position whose feature
    is the X-substituted one. The substitution exists to keep the *protein
    itself* embeddable end-to-end so that decoys sampled from non-X regions
    can be sliced out at training time.
    """
    cleaned = sequence.strip().upper()
    if not cleaned:
        raise ValueError("empty protein sequence")
    return "".join(c if c in MODEL_AMINO_ACIDS else "X" for c in cleaned)


def load_esm2_35m(device: str = "cuda"):
    """Load the frozen ESM-2 35M model + tokenizer.

    Returned model is in eval() with requires_grad=False on every parameter.
    Caller still needs to move it to the desired device themselves if they
    want a non-default placement; the ``device`` arg is only used for the
    initial ``.to()`` call.
    """
    try:
        import torch  # noqa: F401
        from transformers import AutoModel, AutoTokenizer
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "ESM-2 features require torch + transformers. "
            "Install via `pip install transformers` in the research env."
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(ESM_MODEL_ID)
    model = AutoModel.from_pretrained(ESM_MODEL_ID)
    model.eval()
    for param in model.parameters():
        param.requires_grad = False
    model.to(device)
    return model, tokenizer


def embed_sequences(
    model,
    tokenizer,
    sequences: Sequence[str],
    *,
    device: str = "cuda",
    batch_size: int = 64,
    use_bf16: bool = True,
) -> list:
    """Run ESM on a list of sequences. Returns a list of per-residue
    ``Tensor(L, feature_dim)`` aligned to ``sequences`` order. Trims the
    leading <cls> and trailing <eos> tokens so output length == input
    sequence length."""
    import torch

    out: list = []
    autocast_enabled = use_bf16 and torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    for start in range(0, len(sequences), batch_size):
        batch = list(sequences[start : start + batch_size])
        encoded = tokenizer(
            batch,
            padding=True,
            return_tensors="pt",
            add_special_tokens=True,
        ).to(device)
        with torch.no_grad():
            if autocast_enabled:
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    output = model(**encoded)
            else:
                output = model(**encoded)
        hidden = output.last_hidden_state.float().cpu()
        attention = encoded["attention_mask"].cpu().bool()
        for i, seq in enumerate(batch):
            mask = attention[i]
            seq_len = len(seq)
            # tokenizer adds <cls> at 0 and <eos> at seq_len+1 ; per-residue
            # features for the input sequence live at indices 1..seq_len.
            features = hidden[i, 1 : 1 + seq_len, :].clone()
            assert features.shape == (seq_len, hidden.shape[-1]), (
                f"unexpected ESM output shape for {seq!r}: got {features.shape}"
            )
            out.append(features)
    return out


def cache_embeddings_to_disk(
    sequences: Iterable[str],
    cache_path: Path,
    *,
    device: str = "cuda",
    batch_size: int = 64,
    use_bf16: bool = True,
    source_files: Sequence[str] = (),
) -> ESMCacheManifest:
    """Embed unique sequences and persist them as ``{seq: Tensor(L, 480)}``.

    The output file is a single ``.pt`` with two keys: ``embeddings``
    (the lookup dict) and ``manifest`` (an ``ESMCacheManifest.to_json()``
    payload). Lightweight ``cache_path.with_suffix('.json')`` manifest is
    written separately for human inspection.
    """
    import torch

    unique = sorted({normalize_for_esm(seq) for seq in sequences})
    if not unique:
        raise ValueError("no sequences to embed")

    model, tokenizer = load_esm2_35m(device=device)
    print(f"[esm] embedding {len(unique)} unique sequences on {device}", flush=True)
    embeddings: dict = {}
    log_every = max(1, len(unique) // 20)
    storage_dtype = torch.bfloat16 if use_bf16 else torch.float32
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        batch_features = embed_sequences(
            model,
            tokenizer,
            batch,
            device=device,
            batch_size=batch_size,
            use_bf16=use_bf16,
        )
        for seq, feat in zip(batch, batch_features):
            embeddings[seq] = feat.to(storage_dtype)
        if (start // batch_size) % max(1, log_every // batch_size) == 0:
            print(
                f"[esm] {min(start + batch_size, len(unique))}/{len(unique)}",
                flush=True,
            )

    manifest = ESMCacheManifest(
        model_id=ESM_MODEL_ID,
        feature_dim=ESM_FEATURE_DIM,
        n_sequences=len(unique),
        max_length=max(len(s) for s in unique),
        source_files=tuple(source_files),
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"embeddings": embeddings, "manifest": manifest.to_json()},
        cache_path,
    )
    cache_path.with_suffix(".json").write_text(
        json.dumps(manifest.to_json(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[esm] wrote {cache_path} ({len(embeddings)} entries)", flush=True)
    return manifest


def load_embedding_cache(cache_path: Path) -> dict:
    """Load a cache built by ``cache_embeddings_to_disk``. Returns the
    embeddings dict; raises on missing or malformed file."""
    import torch

    if not cache_path.exists():
        raise FileNotFoundError(f"ESM cache not found: {cache_path}")
    payload = torch.load(cache_path, map_location="cpu", weights_only=False)
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, dict) or not embeddings:
        raise ValueError(f"ESM cache at {cache_path} is empty or malformed")
    return embeddings
