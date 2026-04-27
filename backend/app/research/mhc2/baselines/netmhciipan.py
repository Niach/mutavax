"""NetMHCIIpan-4.3 baseline adapter.

NetMHCIIpan is the DTU predictor and the de-facto industry baseline for
MHC class II. The 4.3 release supports DR / DP / DQ / mouse. License is
free for academic use but requires registration:

    https://services.healthtech.dtu.dk/services/NetMHCIIpan-4.3/

Install on the host, then set ``NETMHCIIPAN_BIN`` to the absolute path of
the wrapper script (typically ``netMHCIIpan-4.3/netMHCIIpan``). The
adapter shells out for each allele and parses the table NetMHCIIpan
writes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from app.research.mhc2.baselines.base import BaselineModel, BaselinePrediction


class NetMHCIIpanAdapter(BaselineModel):
    name = "NetMHCIIpan-4.3"

    def __init__(self, binary: str | None = None, *, length_default: int = 15) -> None:
        # The user-facing wrapper is a tcsh script that may not run on
        # hosts without tcsh; we resolve down to the actual ELF binary
        # under ``$NMHOME/Linux_x86_64/bin/NetMHCIIpan-4.3`` and call it
        # directly with NETMHCIIpan + NMHOME set in the env.
        candidate = (
            binary
            or os.environ.get("NETMHCIIPAN_BIN")
            or shutil.which("netMHCIIpan")
        )
        self._wrapper_path = candidate
        self._inner_binary, self._netmhciipan_root = _resolve_inner_binary(candidate)
        self._length_default = length_default

    def is_available(self) -> tuple[bool, str]:
        if not self._wrapper_path:
            return (False, "NetMHCIIpan binary not found (set $NETMHCIIPAN_BIN or add to PATH)")
        if self._inner_binary is None:
            return (False, f"could not resolve ELF binary from {self._wrapper_path}; "
                           "expected $NMHOME/Linux_x86_64/bin/NetMHCIIpan-4.3 sibling")
        if not Path(self._inner_binary).is_file():
            return (False, f"inner binary {self._inner_binary} not found")
        return (True, f"using {self._inner_binary}")

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[BaselinePrediction]:
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(msg)
        grouped: dict[str, list[int]] = defaultdict(list)
        for idx, (peptide, allele) in enumerate(pairs):
            grouped[_to_netmhciipan_allele(allele)].append(idx)

        out: list[BaselinePrediction | None] = [None] * len(pairs)
        with tempfile.TemporaryDirectory() as workdir:
            workpath = Path(workdir)
            for nm_allele, indices in grouped.items():
                pep_file = workpath / "peptides.pep"
                pep_file.write_text(
                    "\n".join(pairs[i][0] for i in indices) + "\n",
                    encoding="utf-8",
                )
                cmd = [
                    self._inner_binary,
                    "-a", nm_allele,
                    "-f", str(pep_file),
                    "-inptype", "1",  # peptide list mode (no -length filter needed)
                ]
                env = {
                    **os.environ,
                    "NMHOME": str(Path(self._netmhciipan_root).parent),
                    "NETMHCIIpan": self._netmhciipan_root,
                    "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                }
                proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
                if proc.returncode != 0:
                    combined = (proc.stdout + "\n" + proc.stderr).lower()
                    if "cannot be found in hla_pseudo" in combined or "unknown allele" in combined:
                        # Allele isn't in NetMHCIIpan's supported set -> emit
                        # NaN scores for all pairs in this allele group; the
                        # harness sample-level max will still be valid as
                        # long as at least one allele in the sample is
                        # supported.
                        for idx in indices:
                            peptide, allele = pairs[idx]
                            out[idx] = BaselinePrediction(
                                peptide=peptide, allele=allele,
                                score=float("nan"), rank_percent=float("nan"),
                            )
                        continue
                    raise RuntimeError(
                        f"NetMHCIIpan failed for allele {nm_allele}: "
                        f"returncode={proc.returncode}\nstderr:\n{proc.stderr[-2000:]}\n"
                        f"stdout:\n{proc.stdout[-2000:]}"
                    )
                rows = _parse_netmhciipan_output(proc.stdout)
                if len(rows) != len(indices):
                    raise RuntimeError(
                        f"NetMHCIIpan returned {len(rows)} rows for {len(indices)} peptides"
                    )
                for idx, row in zip(indices, rows):
                    peptide, allele = pairs[idx]
                    out[idx] = BaselinePrediction(
                        peptide=peptide,
                        allele=allele,
                        score=row["score"],
                        rank_percent=row["rank"],
                        core=row.get("core"),
                        offset=row.get("offset"),
                    )
        return [item for item in out if item is not None]


def _resolve_inner_binary(wrapper: str | None) -> tuple[str | None, str | None]:
    """Find the ELF NetMHCIIpan-4.3 binary that the tcsh wrapper would
    exec. Returns (binary_path, $NETMHCIIpan_root) or (None, None) if it
    can't be located."""
    if not wrapper:
        return (None, None)
    wrapper_path = Path(wrapper).resolve()
    if not wrapper_path.exists():
        return (None, None)
    # If the user already pointed at the inner binary, keep it.
    if wrapper_path.name == "NetMHCIIpan-4.3" and wrapper_path.is_file():
        root = wrapper_path.parent.parent
        return (str(wrapper_path), str(root))
    # Otherwise look under $NMHOME/Linux_x86_64/bin/NetMHCIIpan-4.3.
    home = wrapper_path.parent
    for arch in ("Linux_x86_64", "Linux_x86", "Darwin_x86_64", "Darwin_arm64"):
        candidate = home / arch / "bin" / "NetMHCIIpan-4.3"
        if candidate.is_file():
            return (str(candidate), str(home / arch))
    return (None, None)


def _to_netmhciipan_allele(allele: str) -> str:
    """Convert IPD-style ``HLA-DRB1*15:01`` etc. to the names NetMHCIIpan
    expects:

      * DR/DRB1/DRB3/DRB4/DRB5 monomers -> ``DRB1_1501``
      * DP / DQ heterodimers            -> ``HLA-DPA10103-DPB10101``

    The dimer formatting is what the DTU pseudoseq file ships, so it
    matches NetMHCIIpan-4.3 expectations.
    """
    body = allele.removeprefix("HLA-")
    parts = body.split("-")
    converted_parts: list[str] = []
    for part in parts:
        if "*" in part:
            gene, digits = part.split("*", 1)
            digits = digits.replace(":", "")
            converted_parts.append((gene, digits))
        else:
            converted_parts.append((part, ""))
    if len(converted_parts) == 1:
        gene, digits = converted_parts[0]
        if digits:
            return f"{gene}_{digits}"
        return f"HLA-{gene}"
    # Dimer: concatenate as HLA-<gene1><digits1>-<gene2><digits2>.
    flattened = "-".join(f"{gene}{digits}" for gene, digits in converted_parts)
    return f"HLA-{flattened}"


_HEADER_LINE_RE = re.compile(r"^\s*Pos\s+MHC\s+Peptide", re.IGNORECASE)


def _parse_netmhciipan_output(stdout: str) -> list[dict]:
    """Parse the table NetMHCIIpan writes to stdout. The format has been
    stable across 4.0-4.3: a banner, a header line beginning with ``Pos``,
    then one row per peptide ending with ``Score_EL`` and ``%Rank_EL``."""
    lines = stdout.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if _HEADER_LINE_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return []
    header = re.split(r"\s+", lines[header_idx].strip())
    rows: list[dict] = []
    for line in lines[header_idx + 1 :]:
        if not line.strip() or line.startswith("---") or line.startswith("Number of"):
            continue
        cells = re.split(r"\s+", line.strip())
        # The trailing BindLevel column is ``NA`` for non-binders and is
        # often dropped when whitespace-splitting; tolerate one missing
        # field. Anything shorter than that is a header artefact / blank.
        if len(cells) < len(header) - 1:
            continue
        row = dict(zip(header, cells))
        try:
            score = float(row.get("Score_EL", row.get("Score", "nan")))
            rank = float(row.get("%Rank_EL", row.get("%Rank", "nan")))
        except ValueError:
            continue
        rows.append({
            "score": score,
            "rank": rank,
            "core": row.get("Core") or row.get("Of"),
            "offset": int(row["Pos"]) if row.get("Pos", "").isdigit() else None,
        })
    return rows
