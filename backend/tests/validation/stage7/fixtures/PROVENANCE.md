# Stage-7 reference mRNA fixtures

Clinical mRNA sequences that the pipeline's stage-7 manufacturability checks
are replayed against. See `validation.md` → Stage 7 → "Reference replay".

## `bnt162b2_PP544446.gb`

Pfizer-BioNTech BNT162b2 COVID-19 vaccine plasmid, sequenced directly from a
commercial vial by Raoult (IHU Méditerranée Infection, Marseille) and
deposited to GenBank as **PP544446.1** (2024-04-21). 7692 bp linear DNA.

The BNT162b2 mRNA cassette within this plasmid:

- **T7 promoter**: 3507..3526
- **BNT162b2 CDS**: 3578..7399 (3822 nt → 1273 aa + stop; the "2P-stabilised"
  pre-fusion Spike with K986P / V987P substitutions — note that the native
  furin cleavage site `RRAR` is *preserved* at position 682–685 in this
  construct).

Fetch: <https://www.ncbi.nlm.nih.gov/nuccore/PP544446>

## `mrna1273_OK120841.gb`

Moderna mRNA-1273 COVID-19 vaccine mRNA, recovered from patient plasma 28
days post-vaccination and sequenced by Castruita et al. (Copenhagen
University Hospital) as accession **OK120841.1** (2021-09-28). 3828 bp
linear RNA — this is the mRNA itself, not a plasmid.

No CDS annotation on the record; the ORF is located at runtime by scanning
for the first in-frame Met → stop that reconstructs the 1273-aa Spike.

Fetch: <https://www.ncbi.nlm.nih.gov/nuccore/OK120841>

## Why these two

They are the two most-deployed clinical-grade mRNAs in history. If our
stage-7 manufacturability rules would have *rejected* them, our rules are
mis-calibrated relative to clinical practice. If a rule legitimately flags
something a clinical mRNA contains (e.g., the preserved furin site in
BNT162b2), the report should explain the biology rather than silently
lowering the threshold.
