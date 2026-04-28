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


def cache_embeddings_packed(
    sequences: Iterable[str],
    cache_dir: Path,
    name: str,
    *,
    device: str = "cuda",
    batch_size: int = 64,
    use_bf16: bool = True,
    source_files: Sequence[str] = (),
) -> ESMCacheManifest:
    """Embed unique sequences and write them as a *packed* memmap-able
    binary file plus a small index, instead of a dict of tensors.

    Layout under ``cache_dir``:
      * ``{name}.bin``     -- contiguous raw bytes; one row per residue,
                              ``feature_dim`` entries each, in bf16
                              (or float32 if use_bf16=False).
      * ``{name}.idx.pt``  -- torch.save({'sequences': List[str],
                                          'starts': LongTensor(N),
                                          'lengths': LongTensor(N),
                                          'index': dict[str, int],
                                          'feature_dim': int,
                                          'dtype': str,
                                          'manifest': dict}).
    The lookup dict maps sequence -> row index; ``starts``/``lengths`` give
    the slice into the binary blob. Workers can mmap the .bin file and
    share its pages without copying the per-sequence Python dict.
    """
    import torch

    unique = sorted({normalize_for_esm(seq) for seq in sequences})
    if not unique:
        raise ValueError("no sequences to embed")
    cache_dir.mkdir(parents=True, exist_ok=True)
    bin_path = cache_dir / f"{name}.bin"
    idx_path = cache_dir / f"{name}.idx.pt"

    storage_dtype = torch.bfloat16 if use_bf16 else torch.float32
    bytes_per_residue = ESM_FEATURE_DIM * (2 if use_bf16 else 4)

    model, tokenizer = load_esm2_35m(device=device)
    print(
        f"[esm-packed] embedding {len(unique)} unique sequences -> {bin_path} "
        f"(storage_dtype={'bf16' if use_bf16 else 'fp32'}, "
        f"bytes_per_residue={bytes_per_residue})",
        flush=True,
    )

    starts: list[int] = []
    lengths: list[int] = []
    sequences_in_order: list[str] = []
    cursor = 0
    log_every = max(1, len(unique) // 20)
    sanity_checked = False

    with bin_path.open("wb") as bin_handle:
        for start in range(0, len(unique), batch_size):
            batch = unique[start : start + batch_size]
            features = embed_sequences(
                model,
                tokenizer,
                batch,
                device=device,
                batch_size=batch_size,
                use_bf16=use_bf16,
            )
            for seq, feat in zip(batch, features):
                feat_t = feat.to(storage_dtype).contiguous()
                feat_bytes = feat_t.numpy().view("uint8").tobytes() if not use_bf16 \
                    else feat_t.view(torch.uint8).numpy().tobytes()
                expected_bytes = feat_t.shape[0] * bytes_per_residue
                if len(feat_bytes) != expected_bytes:
                    raise RuntimeError(
                        f"[esm-packed] BYTE-WIDTH MISMATCH for {seq!r}: "
                        f"wrote {len(feat_bytes)} bytes for {feat_t.shape[0]} residues "
                        f"(expected {expected_bytes}, "
                        f"{len(feat_bytes) / max(1, feat_t.shape[0]):.1f} B/res actual vs "
                        f"{bytes_per_residue} B/res expected)."
                    )
                bin_handle.write(feat_bytes)
                length = feat_t.shape[0]
                starts.append(cursor)
                lengths.append(length)
                sequences_in_order.append(seq)
                cursor += length
            if not sanity_checked:
                bin_handle.flush()
                actual_size = bin_path.stat().st_size
                expected_size = cursor * bytes_per_residue
                if actual_size != expected_size:
                    raise RuntimeError(
                        f"[esm-packed] FILE-SIZE MISMATCH after first batch: "
                        f"file={actual_size} bytes, expected={expected_size} "
                        f"({cursor} residues x {bytes_per_residue} B/res)."
                    )
                print(
                    f"[esm-packed] first-batch sanity ok: "
                    f"{cursor} residues -> {actual_size} bytes "
                    f"({actual_size / cursor:.1f} B/res)",
                    flush=True,
                )
                sanity_checked = True
            if (start // batch_size) % max(1, log_every // batch_size) == 0:
                print(
                    f"[esm-packed] {min(start + batch_size, len(unique))}/{len(unique)} "
                    f"residues_written={cursor}",
                    flush=True,
                )

    total_bytes = cursor * bytes_per_residue
    print(
        f"[esm-packed] {bin_path} = {total_bytes / 1e9:.1f} GB "
        f"({cursor} residues, dim={ESM_FEATURE_DIM}, dtype="
        f"{'bf16' if use_bf16 else 'fp32'})",
        flush=True,
    )

    starts_t = torch.tensor(starts, dtype=torch.int64)
    lengths_t = torch.tensor(lengths, dtype=torch.int64)
    index = {seq: i for i, seq in enumerate(sequences_in_order)}
    manifest = ESMCacheManifest(
        model_id=ESM_MODEL_ID,
        feature_dim=ESM_FEATURE_DIM,
        n_sequences=len(unique),
        max_length=int(lengths_t.max().item()),
        source_files=tuple(source_files),
    )
    torch.save(
        {
            "sequences": sequences_in_order,
            "starts": starts_t,
            "lengths": lengths_t,
            "index": index,
            "feature_dim": ESM_FEATURE_DIM,
            "dtype": "bfloat16" if use_bf16 else "float32",
            "manifest": manifest.to_json(),
            "total_residues": cursor,
        },
        idx_path,
    )
    print(f"[esm-packed] wrote {idx_path} (index: {len(index)} entries)", flush=True)
    return manifest


class PackedPeptideCache:
    """Memmap-backed peptide-feature cache.

    A single binary file is opened with ``torch.from_file(..., shared=True)``
    so DataLoader workers (which fork / spawn from the parent) share the
    OS-level mapping. Per-peptide lookup is a small index dict + a tensor
    slice -- no per-worker dict copy.
    """

    def __init__(self, cache_dir: Path, name: str) -> None:
        import torch

        bin_path = cache_dir / f"{name}.bin"
        idx_path = cache_dir / f"{name}.idx.pt"
        if not bin_path.exists() or not idx_path.exists():
            raise FileNotFoundError(
                f"packed cache not found: expected {bin_path} + {idx_path}"
            )
        idx_payload = torch.load(idx_path, map_location="cpu", weights_only=False)
        self._cache_dir = cache_dir
        self._name = name
        self.feature_dim = int(idx_payload["feature_dim"])
        self.total_residues = int(idx_payload["total_residues"])
        self.dtype = (
            torch.bfloat16 if idx_payload["dtype"] == "bfloat16" else torch.float32
        )
        self.starts = idx_payload["starts"]
        self.lengths = idx_payload["lengths"]
        self.index: dict[str, int] = idx_payload["index"]
        # Map the raw binary as a 1-D tensor and view as (N, dim).
        # ``shared=True`` makes the mapping visible to forked workers without
        # duplicating physical memory.
        flat = torch.from_file(
            str(bin_path),
            shared=True,
            size=self.total_residues * self.feature_dim,
            dtype=self.dtype,
        )
        self._features = flat.view(self.total_residues, self.feature_dim)

    def __contains__(self, peptide: str) -> bool:
        return peptide in self.index

    def __getitem__(self, peptide: str):
        i = self.index[peptide]
        start = int(self.starts[i].item())
        length = int(self.lengths[i].item())
        return self._features[start : start + length]

    def __len__(self) -> int:
        return len(self.index)

    def get(self, peptide: str, default=None):
        if peptide in self.index:
            return self[peptide]
        return default

    def __getstate__(self) -> dict:
        # Re-mmap on unpickle in workers -- don't ship the (large) tensor.
        return {"cache_dir": self._cache_dir, "name": self._name}

    def __setstate__(self, state: dict) -> None:
        self.__init__(state["cache_dir"], state["name"])  # type: ignore[misc]


def load_packed_or_dict_cache(cache_dir: Path, name: str):
    """Prefer packed memmap cache; fall back to legacy ``{name}.pt`` dict."""
    bin_path = cache_dir / f"{name}.bin"
    if bin_path.exists():
        return PackedPeptideCache(cache_dir, name)
    legacy = cache_dir / f"{name}.pt"
    if legacy.exists():
        return load_embedding_cache(legacy)
    raise FileNotFoundError(
        f"neither {bin_path} nor {legacy} exists in {cache_dir}"
    )
