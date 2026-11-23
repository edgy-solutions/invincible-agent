# engine-fin on a real dataset: the deployment checklist

**Who this is for:** the platform engineer who points engine-fin at a deployment's own earned-value
asset instead of the notional seed.

**What it is:** every key that must be set, and every grant that must exist, for engine-fin to read
that asset as the caller. It lists keys only. It holds no values, and the sandbox's values are not
a template.

**Unset means notional.** With `FIN_DATASET_URN` unset, engine-fin answers from its seed and none of
this applies. Once it is set, engine-fin refuses to start unless sections 1 and 2 hold. The error is
a lifespan `RuntimeError` beginning "FIN_DATASET_URN is set but the deployment cannot honour it:",
followed by each problem (`asset_inputs.check_config`).

Sections 3 and 4 are not checked at startup. They fail at the first read, as a 403 or a 503.

## 1. The dataset (engine-fin's env: `engineFinance.env`)

| key | needed | checked at startup |
|---|---|---|
| `FIN_DATASET_URN` | the switch | must start `urn:li:dataset:` and have more after it |
| `FIN_DATASET_BANNER` | yes, with the URN | must be non-empty. It is the line that stops a synthetic asset from reading as real |
| `FIN_DATASET_CONTRACT` | yes, with the URN | must name a contract that loads and passes section 2 |
| `FIN_ASSET_MAX_ROWS` | no (default 100000) | if set, a positive integer. A larger read is a 422 `asset_too_large` |
| `CENTRAL_GATEWAY_URL` | yes, with the URN | must be non-empty. It comes from the chart's shared configmap, not from `engineFinance.env` |

The base `values.yaml` sets none of the `FIN_` keys.

## 2. The contract

| item | needed |
|---|---|
| `DATASET_CONTRACT_DIR` | no. Default: `/app/contracts` in the image, `<repo>/contracts` in a checkout |
| `<dir>/<contract_id>.yaml` | yes. Its `contract_id` must equal the file's stem |
| `columns`: `program_id`, `program_name`, `control_account`, `work_package`, `period` | each declared, typed `string`, required, `nullable: false` |
| `columns`: `program_bac`, `bcws`, `bcwp`, `acwp` | each declared, typed as a number, required, `nullable: false` |
| `scope` | `program_id` |
| grain (key) | non-empty, and a subset of {`work_package`, `period`} |
| `dependencies` | `program_name` and `program_bac` determined by `program_id`; `control_account` determined by `work_package` |

**Every read enforces the whole contract**, not only these columns. A broken rule is a 502
`asset_contract_violation`, which names the rule and the column but never a value.

## 3. The grants (policy files and their syncs)

Two grants, both **per user**. Neither file resolves a group name.

| item | where | needed |
|---|---|---|
| a reader grant on the URN: `subject`, `asset`, `granted_by`, `reason` (`kind` defaults to `dataset`) | `policy/asset_grants.yaml` → `grant_sync` | one entry per person who will ask |
| the `dataset` object for the URN | `datahub_topaz_sync`, from DataHub | yes. The URN must be a DATASET entity in DataHub. Otherwise `grant_sync` refuses the grant as dangling |
| program membership: the program key, `grant_to`, `granted_by`, `reason` | `policy/program_members.yaml` → `program_member_sync` | yes. The program key must equal the asset's `program_id` value. A `svc:` principal is never a member |
| a declared row's `cells` | the row's `policy.cells`, resolved through `groups.yaml` | only for a declared measure that sets `cells` |

The rules behind this:
- **No group path to a dataset read.** In Topaz, `can_read = reader | owner`, and both relations
  take `user` only (`templates/topaz-configmap.yaml`, the `dataset` type).
- **A DataHub owner can read too.** `owner` comes from the DataHub owners that `datahub_topaz_sync`
  copies.
- **What each refusal looks like:**
  - missing program membership: 403 `program_not_visible`, before the asset is asked for;
  - missing reader grant: 403 `access_denied`, with the refusal naming `reader(<urn>)`.
- **Sync before you roll.** Both syncs must have run before the first request. A grant merged
  but not synced is a 403.

## 4. The route to the bytes (domain broker)

| item | needed |
|---|---|
| a domain broker advertising the URN: the gateway reads `mesh_route:<urn>` from Redis after the Topaz check | yes. Without it the gateway answers 404, which engine-fin reports as 503 `asset_unavailable` |
| the broker's own storage credentials, to mint short-lived read credentials | yes. These are broker settings, not engine-fin settings |
| the producing asset's `datahub/urn` tag (Dagster) | no. If set, it replaces the derived URN, and that URN is then the one sections 1 and 3 must name |
| the IO manager's `source_type`, from the broker's known set | yes, at publication |

## 5. Tags

**None are required.** Nothing reads a DataHub tag, domain, classification or platform on the
asset. `datahub_topaz_sync` fetches tags and does not use them, and the gateway checks none of them.
The contract's `tags.required` is empty for the sample asset.

## 6. The as-of source

There is **no deployment key** for this. What engine-fin cites is whatever the routing ticket carries:
- **As of dag-tools 0.17.0, no as-of reader is registered** (`AS_OF_READERS` is empty), so nothing
  reads an as-of when the read is authorized.
- **When the ticket carries one, it was advertised when the asset was published.** That is, the
  ticket has a top-level `as_of`, `snapshot_id` or `version`, put there by the IO manager's
  `mesh_extra()`. No shipped IO manager adds one.
- **Otherwise the ticket has no as-of,** with the reason `no_reader_for_source_type`. engine-fin
  then cites the ticket alone, as `(ticket: <id>)`, and the broker counts such tickets on
  `/health`.

A deployment that wants a dated citation today must publish through an IO manager that sets one of
those three keys. Neither a DataHub custom property nor a column is read for it.

## 7. Declared measures over the same asset

A dataset row (see [adding-a-measure-by-declaration.md](adding-a-measure-by-declaration.md))
names its own `inputs.dataset.urn`, `banner` and `contract`, and needs the section 3 grants on
*that* URN. The overlay directory is named in `MEASURE_VERB_OVERLAY_DIRS`. A misspelt path loads
nothing, and raises no error.

## 8. Declare your fiscal calendar

| item | needed |
|---|---|
| a `fin_calendar` file: `calendar_id` and the `periods` list, in `FIN_CALENDAR_OVERLAY_DIRS` | yes. With none declared, every period is refused (`period_outside_calendar`), whether or not `FIN_DATASET_URN` is set |

A private policy repo delivered by `policyOverlay` needs a `fin_calendar` directory before it rolls
a chart that carries this. The file shape and every rule are in
[finance-overlays.md](finance-overlays.md), section 8.
