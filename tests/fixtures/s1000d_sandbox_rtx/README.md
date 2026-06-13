# B2 test fixture — synthetic RTX-themed S1000D corpus

**Boundary rule (non-negotiable):** every file in this directory is a
**sandbox/CI test fixture**. None of it is real RTX technical data. It
must NEVER reach the work cluster.

The Model Identification Code `SANDBOXRTX` (visible in every DMC and
every `<dmCode modelIdentCode="SANDBOXRTX" ...>` element) is a
deliberate, detectable marker. The B2 negative boundary guard asserts:

> `SANDBOXRTX` is present in the sandbox/CI graph AND absent from
> every deploy-path artifact (`CANONICAL_TTL_MANIFEST`,
> `prime_databases.py`, Helm values, every bootstrap fetch URL).

The fabrication is designed so leakage is catchable. If a single
synthetic DMC shows up in the work cluster's graph, the negative
guard fires loudly and names exactly which path leaked.

## What's here

8 module references (7 distinct XML files; row 8 is a re-ingest of
row 3 — idempotency probe) per the architect's coverage table:

| # | DMC | type | mil:* kind | Purpose |
|---|---|---|---|---|
| 1 | DMC-SANDBOXRTX-A-46-10-00-00A-**040A**-D | descript | mil:DescriptiveDataModule | core map (SPY-6 array face) |
| 2 | DMC-SANDBOXRTX-A-46-15-00-00A-**042A**-D | descript | mil:DescriptiveDataModule | family-robustness (04x → same kind, LTAMDS) |
| 3 | DMC-SANDBOXRTX-B-72-30-10-00A-**520A**-A | proced | mil:ProcedureDataModule | core map (NASAMS canister remove) |
| 4 | DMC-SANDBOXRTX-C-95-20-15-00A-**720A**-A | proced | mil:ProcedureDataModule | family-robustness (5xx/7xx pair, Patriot install) |
| 5 | DMC-SANDBOXRTX-A-46-20-05-00A-**420A**-A | fault | mil:FaultIsolationDataModule | core map (SPY-6 T/R diagnostic) |
| 6 | DMC-SANDBOXRTX-C-95-40-00-00A-**941A**-A | ipd | mil:IllustratedPartsDataModule | core map (Patriot launcher IPD) |
| 7 | DMC-SANDBOXRTX-A-46-30-00-00A-**520A**-A | proced | mil:ProcedureDataModule + requiresTool + hasPart | composition probe (LTAMDS PS, Q5 plumbing) |
| 8 | DMC-SANDBOXRTX-B-72-30-10-00A-**520A**-A | proced | mil:ProcedureDataModule | row 3 again — idempotency / G3 |

## Generation

The corpus was generated via `s1kd-newdm` from
[kibook/s1kd-tools](https://github.com/kibook/s1kd-tools)
(open source, GPL-3.0). All modules validate against the S1000D
Issue 4.2 schemas via `s1kd-validate --net`.

Reproduce by running `scripts/generate_sandboxrtx_corpus.sh` (TBD —
this fixture is committed permanently; the script exists for the
"re-generate from scratch" use case when the spec evolves).

## Theming vs. content

The RTX-themed naming (SPY-6, LTAMDS, NASAMS, Patriot) lives in the
S1000D **metadata** (tech name, system code, info name). The **body
text** is generic placeholder maintenance prose ("remove access
panel," "inspect connector for corrosion") — no real parameters, no
real procedures, nothing licensed. This is the correct test design
per B0 §1: classification keys on the info code, not the content.
The realism is in the metadata; the body is intentionally generic
so the fabrication is honest (and so nothing classifiable as real
data can ever escape this fixture).

## What proves the boundary

Run the B2 standing guards:

    pytest tests/routing/test_b2_format_ingest_guards.py

Particularly the negative-boundary guard (B2 implementation will
add it as part of Step 3 of the recipe). The marker `SANDBOXRTX`
appears here and in the test graph after a fixture ingest; it must
NOT appear in any `setup/`, `helm/`, or `scripts/` artifact a deploy
consumes.
