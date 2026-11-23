---
id:         fin-inputs-resolver
status:     open
owner:      lane/fin
blocked-on: nothing. The sandbox sets the flag from 0.4.81 (#277); measured live 3 of 3 on 0.4.80.
closed-by:
code-site:  agent_fleet/finance_agent/asset_inputs.py, agent_fleet/finance_agent/main.py (`_declared_envelope`, `mesh_ticketed_read`)
repo:       invincible-agent
summary:    Behind `FIN_DATASET_URN`, a declared finance measure computes over rows read as the caller from one catalogued asset. Unset, the seed answers exactly as today.
---

# The finance inputs resolver

"Inputs resolver" had no earlier written definition, so this design is lane/fin's. It ran on the sandbox on 2026-11-05: chart 0.4.80, with the flag set by hand and reverted after, `tests/sandbox_e2e/test_variance_set_reads_the_ev_fixture.py` passed 3 of 3.

**Flag.** `FIN_DATASET_URN` via `engineFinance.env`; no chart change. Unset: no read, no import, byte-identical envelope. Set: boot also requires `FIN_DATASET_BANNER`, `CENTRAL_GATEWAY_URL`, a `urn:li:dataset:` form and an importable client. `FIN_ASSET_MAX_ROWS` defaults to 100000.

**Unchanged.**
- `run_declared` stays pure and the URN isn't in the row, so one board can't read two sources and a deployment edits no row.
- `/resolve_instance`, `/enumerate_instances` and `/verbs` stay on the seed.
- A package reads the asset as the caller, grant-checked before anything is measured, like a CDRL (see the forks below).
- A CDRL is not refused (ruled 2026-11-05). Its sources run through `_measure_envelope`, as the caller. The caller's grant is checked before anything is measured, and the program's facts come from the asset. `/artifact` checks the fetcher's grant before serving the file.

## The read, in `_declared_envelope`

```python
periods_in(window)                                 # an unknown period refuses with no read
client = CortexDataClient(broker_url=os.environ["CENTRAL_GATEWAY_URL"],
                          originator_email=caller.require_authz_id(), jwt_token=bearer)
lf = client.get_dataframe(urn)                     # ticket_ms
df = (lf.filter(program_id == p, period in window) # period filter only if a window was asked for
        .select(COLUMNS).head(max_rows + 1).collect())   # scan_ms
rows = measure_verbs.run_declared(asset_inputs.state_from_rows(df, program_id=p), row, **params)
```

- **Identity.** `mesh_ticketed_read` stays in `main.py` and is now called. No service identity. The bearer comes from an app dependency that sets a ContextVar (the SDK's technique). No bearer, `PermissionError` or a `svc:` caller is a 401 with the existing message prefix, and no read.
- **One read per `/measure`; no cache,** because a cache across callers bypasses the grant. Program and cell checks run first.
- **Timing, one line per read:** `ticket_ms scan_ms sql_ms=0 rows bytes` and the URN, never the caller. The logger gets its own INFO handler, since engine-fin configures none.

## The columns

Fixed names, no column map. File-backed only: a table-backed asset runs `SELECT *` before the frame exists.

| column | type | rule |
| --- | --- | --- |
| `program_id`, `program_name` | string | one name per program |
| `program_bac` | numeric | one value per program, on every row |
| `control_account`, `work_package` | string | one account per work package |
| `period` (the key) | string | in `FISCAL_PERIODS`; one row per (`work_package`, `period`) |
| `bcws`, `bcwp`, `acwp` | numeric | period amounts, never cumulative |

Integer or float both compute the same figures. A float budget only prints differently in the audit strings (`12000000.0`, `vac_exact` `-60000.0`), and the sandbox fixture keeps the seed's split so its envelope matches the seed's exactly.

`program_bac` is a column because a window filter can drop a work package, and a sum of package budgets would then quietly shrink TCPI's and VAC's input. Entity fields the contract does not carry are `None`, and `check_consistency` doesn't run on this state.

## Outcomes, never a seed fallback

| outcome | status | detail |
| --- | --- | --- |
| `NotEntitled` | 403 | `status: "access_denied"`, `denied_assets`, `subject`, `message`, `refusal` (`policy_id: "asset_grants"`, `missing_binding: "reader(<urn>)"`, `candidates: []`) |
| `MeshUnavailable`, scan failure | 503 | `asset_unavailable`; the log gets the exception's type only, as its text can hold a credential |
| a column, null, duplicate or calendar rule broken | 502 | `asset_contract_violation`, naming the rule, never a row's money |
| over `FIN_ASSET_MAX_ROWS` | 422 | `asset_too_large` |
| no rows for the program or window | 422 | `not_in_model` (the seed answers an empty 200 for a window) |

A denial stays a 403 because the board's relay keeps it whole. On the chat path the supervisor's relay carries `status`, `denied_assets`, `subject` and `message` past its refusal dict, since those open the request-access flow.

**Provenance.** When the asset answers, `data_provenance` is the URN plus `FIN_DATASET_BANNER`, never the notional banner, and `data_source: {kind: "asset", urn}` is added. The banner is required so a synthetic asset can't read as real.

**Dependency.** `polars` and `edgy-dag-tools@v0.10.0` (0.14.0 since `26817b82`) in engine-fin's lock, as their own commit: +30 packages, about 242 MB of wheels, imported only when the flag is set. Memory under the 512Mi limit is unmeasured.

## Before anyone sets the flag: all four hold (2026-11-05)

- **#213** (a person's subtask carries that person's token) is merged as `bd351cce`, first in chart 0.4.78. Without it a chat verb arrives as `svc:` and gets the 401.
- **The asset and its grant.** `ev_fixture` is materialized, and the grant held live: on the leg the allowed subject read it and the denied subject got 403 `access_denied` naming it.
- **Egress** from the pod to the object store, measured on the live leg: `ticket_ms` 0.3 to 1.1 s, `scan_ms` 0.1 to 0.2 s.
- **The broker mints the ticket's credential per request** (`broker-advertises-unminted-credential.md`, steps 1 and 3): dag-tools `c651fac`, first released in v0.3.0, and the minting identity in v0.3.1. Engine-fin pinned v0.10.0 then (0.14.0 since `26817b82`).

## Forks for the architect

- **Built-ins on the seed.** Ruled 2026-11-08: with the flag set the built-ins read the asset, because that is what the flag means. Funding stays on the seed by its row (`policy/measure_verbs/fin_funding_status.yaml`, `source: seed`, ruled 2026-11-09: the source is declared per row, not per flag) until the EV contract carries funding lines; with that row replaced by `source: asset` it is a 422 over the asset, never zero rows. The fields the contract does not carry (a CA's BAC, WBS and OBS, a package's BAC and technique) are absent. Still on the seed: `/enumerate_instances` and the instance listing, and the registration's and `/verbs`' reported periods.
- **Exports from an asset.** Ruled for CDRL (architect, 2026-11-05): a CDRL reads the same resolver the canvas does and is grant-checked the same way, at export and at fetch. A package is the same: it runs as the caller, grant-checked at the asset, and `state_sha256` hashes the asset state it computed from. `recipient_readers` governs who may receive the file, not who reads the asset, so its fetch asks no asset grant. `program_finance`'s funding panel is seed-sourced, so the package computes over the asset's facts with the seed's funding lines for that program, and its manifest and page name the seeded panel and its reason. A declared or dataset-kind panel stays a 503 from the builder: the page recomputes with its embedded `measures.py`, which does not hold them.
- **Calendar and pickers.** `FISCAL_PERIODS` is FY26 only, in code. A program only in the asset can't be named in chat, because `/enumerate_instances` reads the seed.
