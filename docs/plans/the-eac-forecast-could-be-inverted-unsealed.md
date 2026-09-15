---
id:         the-eac-forecast-could-be-inverted-unsealed
status:     closed
owner:      lane/91 (invincible-agent-81)
blocked-on:
closed-by:  3863a86
repo:       invincible-agent
code-site:  agent_fleet/finance_agent/measures.py (fin_eac_calculation), tests/finance/test_the_eac_formulas_are_the_formulas.py
summary:    Five of six mutations against fin_eac_calculation survived the full suite, and the CPI one REVERSES THE SIGN of the forecast — "2.15M over budget" reading as "1.8M under". THE VERB WAS CORRECT; nothing asserted that it was. Found by R-029's check before an ADR-0053 §7 extraction, sealed in 3863a86. Test-only. The one mutation that did red exposed a second law: a relative check is not an absolute one.
---

# The EAC forecast could be inverted, and 151 green tests could not tell

## What this record is

**Not a wrong answer that shipped.** Every formula matched the public EVM methodology the module
docstring names. What shipped was a **green that could not tell** — and this is the verb that
produces the number a program office argues about.

## The five survivors, each measured before being called a finding

| mutation | correct | mutant |
|---|---|---|
| **CPI: `bac * cpi`** | **14,152,381** | **10,174,966** |
| `REMAINING_AT_BUDGET` drops the spend | 13,130,000 | 5,700,000 |
| `vac` sign flipped | −2,152,380 | +2,152,380 |
| `etc` measured from `bcwp` | 6,722,380 | 7,852,380 |
| `percent_complete` over `acwp` | 0.5250 | 0.8479 |

**The first does not make the forecast wrong by an amount — it reverses its sign.** With CPI
below 1, dividing raises the forecast and multiplying lowers it: *"we will overrun by 2.15M"*
becomes *"we will land 1.8M under"*. A reader acts on exactly that difference.

`vac` flipped is the same reversal one field along; `percent_complete` over ACWP turns a program
52% complete into one reading 85%. **Each points the same reassuring way.**

## The one that DID red, and why it is not reassuring

`CPI_SPI` dividing by `cpi` alone reds — through `fin_eac_comparison`'s seals, which compare the
three methods' **spread**.

> **A relative check is not an absolute one.**

A spread check notices when one method moves *relative to the others*. It cannot notice all three
being wrong in the same direction, nor one being wrong in a way that **preserves the ordering** —
and `bac * cpi` keeps CPI below CPI_SPI, so the comparison stays happy.

**Same shape as two fields agreeing because they come from one upstream: a check between derived
things is blind to what they share.** It is easy to mistake for coverage precisely because the
relative check is the more sophisticated-looking of the two.

## What closed it — `3863a86`, test-only

Sixteen seals, each recomputing from the **row's own published quantities** (`bac`, `bcwp`,
`acwp`, `cpi`, `spi` all ride on the row), so a response whose EAC disagrees with the numbers
printed beside it contradicts itself. **No second implementation of the verb.**

**Five controls, one per assertion that needs one:**

1. **`cpi` must be below 1** — at exactly 1.0 multiply and divide agree and the inversion seal
   proves nothing; above 1.0 it tests the opposite sign of the finding.
2. **`spi` must not be 1.0** — otherwise dividing by one index is an equivalent mutant.
3. **`vac` must actually be negative** — on a program forecast at budget the flip is invisible.
4. **`acwp` must differ from `bcwp`** — or ETC's origin cannot be told.
5. **The three methods must not collapse to one figure** — which would let the wrong formula
   satisfy most of the file, and would also zero the spread `fin_eac_comparison` depends on.

All six mutations now red: the inversion 2, dropping the spend 1, `CPI_SPI` by `cpi` only 3,
`vac` flipped 4, `etc` from `bcwp` 3, `percent` over `acwp` 3.

## The consequence for the method registry, recorded where it will be needed

ADR-0053 §2 makes EAC methods **pluggable rows**, and a customer may supply one. **A row whose
formula cannot be checked against a stated standard is a row that ships a sign flip with a name
on it** — this defect record is what that looks like before anyone could write such a row.

The requirement is added to §2: each method row carries `prov:wasDerivedFrom` pointing at the
clause it implements, and an **absolute transcription seal** against it — the same discipline the
risk matrix was transcribed under, cell by cell from its source table.
