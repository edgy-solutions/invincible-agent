---
id:         fin-inputs-resolver
status:     open
owner:      lane/fin
blocked-on: nothing for the code. A live read needs #213, the asset and its grant.
closed-by:
code-site:  agent_fleet/finance_agent/asset_inputs.py, agent_fleet/finance_agent/main.py (`_declared_envelope`, `mesh_ticketed_read`)
repo:       invincible-agent
summary:    Behind `FIN_DATASET_URN`, a declared finance measure computes over rows read as the caller from one catalogued asset. Unset, the seed answers exactly as today.
---

# The finance inputs resolver

"Inputs resolver" had no earlier written definition, so this design is lane/fin's. Nothing here has run on a cluster.

**Flag.** `FIN_DATASET_URN` via `engineFinance.env`; no chart change. Unset: no read, no import, byte-identical envelope. Set: boot also requires `FIN_DATASET_BANNER`, `CENTRAL_GATEWAY_URL`, a `urn:li:dataset:` form and an importable client. `FIN_ASSET_MAX_ROWS` defaults to 100000.

**Unchanged.**
- `run_declared` stays pure and the URN isn't in the row, so one board can't read two sources and a deployment edits no row.
- Built-in verbs, `/resolve_instance`, `/enumerate_instances` and `/verbs` stay on the seed.
- With the flag set, a package or CDRL naming a declared measure gets 409 `asset_export_unsupported` before anything is measured: `state_sha256` can't describe a mixed package. So no export holds asset rows, and `/artifact` needs no asset check.

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

`program_bac` is a column because a window filter can drop a work package, and a sum of package budgets would then quietly shrink TCPI's and VAC's input. Entity fields `run_declared` never reads hold placeholders, and `check_consistency` doesn't run on this state.

## Outcomes, never a seed fallback

| outcome | status | detail |
| --- | --- | --- |
| `NotEntitled` | 403 | `status: "access_denied"`, `denied_assets`, `subject`, `message`, `refusal` (`policy_id: "asset_grants"`, `missing_binding: "reader(<urn>)"`, `candidates: []`) |
| `MeshUnavailable`, scan failure | 503 | `asset_unavailable`; the log gets the exception's type only, as its text can hold a credential |
| a column, null, duplicate or calendar rule broken | 502 | `asset_contract_violation`, naming the rule, never a row's money |
| over `FIN_ASSET_MAX_ROWS` | 422 | `asset_too_large` |
| no rows for the program or window | 422 | `not_in_model` (the seed answers an empty 200 for a window) |

**Provenance.** When the asset answers, `data_provenance` is the URN plus `FIN_DATASET_BANNER`, never the notional banner, and `data_source: {kind: "asset", urn}` is added. The banner is required so a synthetic asset can't read as real.

**Dependency.** `polars` and `edgy-dag-tools@v0.10.0` in engine-fin's lock, as their own commit: +30 packages, about 242 MB of wheels, imported only when the flag is set. Memory under the 512Mi limit is unmeasured.

## Before anyone sets the flag

#213 rolled (otherwise a chat verb arrives as `svc:` and gets the 401); the asset and its synced grant; egress from the pod to the object store measured; `broker-advertises-unminted-credential.md` read, since the engine could receive a write-capable key.

## Forks for the architect

- **Built-ins on the seed.** Off the sandbox, a board shows invented built-ins beside real declared figures, under separate banners. Moving them needs fields the contract doesn't carry.
- **Exports from an asset.** Allowing them needs a ruling on what a recipient without an asset grant may read.
- **Calendar and pickers.** `FISCAL_PERIODS` is FY26 only, in code. A program only in the asset can't be named in chat, because `/enumerate_instances` reads the seed.
