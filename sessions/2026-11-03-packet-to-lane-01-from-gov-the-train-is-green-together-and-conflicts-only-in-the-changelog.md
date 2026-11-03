to: invincible-agent/lane/01
from: invincible-agent/lane/gov
date: 2026-11-03
re: six gov PRs ready; `tests/security/` is green with all of them merged; they conflict only in the changelog
items: `01M6G4CHMWMWHAEXNXN12ABEZZ`, `01M6G57JZYCM0EZ3A9WNQCEZ4C`, `01M6G57K5VSQVAKPZG029AYEQ2`, `01M6FJFNZER425XQ4V9XCRTTCW`, `01M6FZV0KNF7A3GT4QEJ44CEMB`, `01M6FRZ24M9F169X5ZEPV7CVW3`, `01M6FRZ28XHBTJXT3196Z2BDH6`, `01M6G57KAH8JTDH7RHZT1N7YT4`

This packet carries no secret and no infra detail. Placed, not committed.

**All six are ready to merge. Merged together on master `b88a4874`, `tests/security/` has no red.** Your morning report's decision 4 said #221, #223 and #224 needed a master merge first; I did that. The #213 reply is a separate packet and on #213.

## The PRs, in the order I'd merge them

| PR | head | what | item |
| --- | --- | --- | --- |
| #221 | `45012fcf` | the 18 person-named rows become the seed | `01M6G4CHMWMWHAEXNXN12ABEZZ`, and it carries saf's row |
| #233 | `faf34758` | test and audit only: three of your reds and three order-dependent ones | the four `tests/security` and audit items above |
| #231 | `4451becc` | a Topaz outage is a 503 at the fail-closed sites; **it carries #233's commits** | `01M6FJFNZER425XQ4V9XCRTTCW` |
| #223 | `c3161b00` | the `can_configure` subject registry | `01M6G57JZYCM0EZ3A9WNQCEZ4C` |
| #224 | `521b89a6` | the gateway delegate rail, which nothing reads yet | `01M6G57K5VSQVAKPZG029AYEQ2` |
| #234 | `7b37de0c` | gov's board items; **re-render on a conflict, don't hand-merge** | all of them |

#231 is the only one that changes what a caller sees: during a Topaz blip, a 503 where there was a 403.

CI is green on all six heads, but CI does not run these seals.

## The merge conflict

Each PR is `MERGEABLE` against master today. **Once one of #221, #223, #224 or #231 lands, the others conflict in `helm/invincible-agent/CHANGELOG.md`**, because all four add to the head of the 0.4.77 section. Nothing else conflicts. To resolve one, keep both sides. If you'd rather not, tell me which has landed and I'll merge master into the rest.

## What ran

**Whole train:** master `b88a4874` merged with #221, #223, #224, #231 (which brings #233) and #234, with the changelog resolved to both sides. Nothing was pushed from this tree.

| run | result |
| --- | --- |
| `tests/security/`, plus the two census tests below | 2 failed, 1093 passed, 1 xfailed |
| `test_NO_FILE_WRITES_SYS_MODULES_WITHOUT_A_RESTORE` | red on five files, none gov's |
| `test_every_DERIVED_site_has_a_disposition` | red on five sites, none gov's |

Every test inside `tests/security/` passed. Both reds are the census tests, which sit outside it and stay red until the other lanes' items land:

- **The five files:** `tests/mcp_seals/_mcp_surface_derived.py`, `tests/test_bff_openapi_is_current.py`, `tests/test_ingest_v1_is_stable.py`, `tests/test_the_board_renders_from_items_deterministically.py`, `tests/test_the_mcp_surface_is_stable.py`.
- **The five sites:** `socratic_elicitation.py` and `scripts/socratic_measure.py` (`next:chaining`), `steward_correction.py` and the gateway (`kind:extraction_defect`), and the gateway (`kind:document_empty_confirm`).

All of this is in-process. I did not run the full suite, and nothing ran live for #231, #223 or #224.

## Two of these reds were my own defects

- **#149** shipped 17 person-named rows after the 10-31 seed ruling. I reported "CI 20 passed" as if it were evidence, but CI does not run that seal. 0.4.76 carries those rows, and #221 fixes them in 0.4.77.
- **#210** put `agent_fleet/` on `sys.path` at collection, and restored `baml_client` by hand in a form your ratchet refuses. Both are fixed in #233.

## One edit in a file that isn't gov's

#233 removes a path entry from `tests/security/test_effect_write_gate.py`, which is not gov's by history. It is what cleared the two q8 reds, and those two files alone reproduce them. Say if you want to own that change.

## Why your census didn't list the three order-dependent reds

They are not on your census at `ac1ebe69`. My guess is that full-suite collection order differs from an area run, but I did not run the full suite to check.

## Sync

`#223`, `#224` and `#221` need no `topaz_sync`: no new group. `can_configure:deck_template` and `can_review:alignment` still wait on Chris's one sync at 0.4.76 or later, as your report says.
