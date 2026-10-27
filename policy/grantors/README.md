# policy/grantors — who can grant a missing binding

When a policy refusal happens, its `grantable_by` is read from this map
(`src/iagent/authz/refusal.py`).

- **One file per policy family**, keyed by `family`. The family is the part of a refusal's
  `policy_id` before the first `:`.
- **These rows are the platform seed.** Their wording is deployment-neutral.
- **A deployment names its own approvers in an overlay.** It points `GRANTOR_OVERLAY_DIRS` at
  one or more directories of rows, pathsep-separated.
  - An overlay row replaces the seed row whole (ADR-0036).
  - An overlay row of `family: <name>` and `deleted: true` removes a row. A family with no row
    still refuses with the site's status (401, 403 or 409), and its `grantable_by` says the
    row is missing.
  - A tombstone for a family the seed does not ship is an error (the SDK's `compose_rows`).

| field | meaning |
| --- | --- |
| `family` | the policy family, e.g. `capability_grants`, `groups`, `config`, `code` |
| `who` | who approves a grant in this family |
| `how` | what the grant is: the change and the step that applies it |
| `object_scoped` | `true` when a key would name a program, asset or compartment. A refusal then names the family alone, so a withheld target answers like an absent one (ADR-0047 §5.1, ADR-0049 Ruling 4). |
| `rail_file` | the policy file the family's rows live in. Absent for `config` and `code`. |

## Rules for new families

- **A new grant-bearing policy file needs a row here.** A file is grant-bearing if its rows carry
  `granted_by`. The seal derives this set and fails on a missing row:
  `tests/security/test_every_policy_refusal_names_policy_binding_grantor.py`.
- **The `code` row marks debt.** A binding still held in code (a table in an engine) has no
  approver but its maintainers. It moves onto the rail when someone owns it.
