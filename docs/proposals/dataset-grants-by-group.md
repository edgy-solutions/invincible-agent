# Dataset grants by group

**Status: PROPOSED** (Lane 1, 2026-11-23). It needs the architect's rulings on the questions in §6,
and the dag-tools owner's confirmation of §3.

**Origin.** fin found that a dataset read can be granted only to a user, one row per person. A
team that reads a dataset needs one row per member, and a new member reads nothing until someone
adds their row.

## 1. Where things stand (master `c105ed21`)

- **The manifest.** `dataset` admits only users: `owner: user`, `reader: user`,
  `can_read: reader | owner` (`helm/invincible-agent/templates/topaz-configmap.yaml:159-165`).
  `document` has the same shape.
- **The sync.** `policy/sync/grant_sync.py` reads `asset_grants.yaml`:
  - each row has `subject`, `asset`, `granted_by`, `reason` and `kind` (`dataset` or `document`);
  - each row becomes `<kind>:<asset>#reader@user:<subject>` (`derive_grant_desired`);
  - readback calls `check(kind, asset, "can_read", subject)`.
- **The validator.** `policy/sync/validate_policy.py:1919-1926` calls group grants "a DEFERRED
  design decision (needs a membership-drift audit ruling + manifest `user | group#member` + sync
  support); until then, USERS ONLY across the family". This proposal answers those three needs.
- **The precedent.** Two syncs already grant to groups:
  - `task_grant_sync.py:105-110` (`grant_to_groups`, task audiences);
  - `capability_grant_sync.py:234` (capabilities).

  Both write `subject_type="group", subject_relation="member"`. Neither creates the group object,
  because membership is `topaz_sync`'s, and an empty group would pass readback. The validator's
  `unusable_group_audiences` enforces the 2026-10-10 ruling that a granted group must exist and
  have members.
- **A second writer.** `src/iagent/human_tasks.py:1312,1321` writes dataset reader relations to
  users only. This proposal leaves it user-only.

## 2. The proposal

1. **Manifest:** `dataset.reader: user | group#member`. `can_read` is unchanged, so a member of a
   granted group can read.
2. **The grant row:** a row names exactly one of `subject` (a user, as today) or `subject_group` (a
   group). Both, or neither, is MALFORMED and refuses the whole file, as a missing field does today.
   `granted_by` stays required.
3. **The sync:** a `subject_group` row writes `<kind>:<asset>#reader@group:<G>#member`. It does not
   create the group object (the precedent above). Readback checks the relation itself, then
   `can_read` for one current member as a control.
4. **The validator** refuses a group grant when:
   - the group does not exist or has no members (the 10-10 ruling, as `unusable_group_audiences`);
   - any member is a service identity (`svc:`). A service is not a disclosure recipient, so a
     group that contains one would grant the service by a side door. This is the group form of
     `service_identity_recipients`;
   - the group is not of a kind §6 Q2 admits. Today every group in `policy/groups.yaml` (13 of
     them) exists to hold persona-and-domain cells, and no group exists only to hold data
     access.
5. **Scope:** `dataset` only in the first PR. `document` would follow the same shape (§6 Q1).

## 3. Enforcement: dag-tools needs no change (to confirm)

The only check that enforces a dataset read is dag-tools' central gateway,
`dag_tools/central_gateway/main.py:238` `check_topaz_authz`. It posts `/api/v2/authz/is` with
`permission: "can_read"`. The Rego (`topaz-configmap.yaml:384-390`) calls `ds.check` on
`can_read`, not `check_relation`, so the directory resolves `group#member` once the manifest
admits it.

Nothing else checks a dataset read in Topaz: engine-fin, the BFF and the domain broker do not, and
`check_payload` (dag-tools `main.py:325-337`) is unused. **The dag-tools owner is asked to confirm
both points.**

## 4. Membership drift and audit

A group grant widens when someone joins the group and narrows when someone leaves, with no change
to `asset_grants.yaml`. That is the point of the change, and it is also the drift the validator's
comment asks to have ruled. Proposed:

- **Revocation follows membership.** Removing a person from the group removes their read at the
  next `topaz_sync`. Removing the row removes the read for every member at the next grant sync.
- **Every grant sync logs who can read.** For each group grant it logs the asset, the group, and
  the member count with a hash of the sorted member list, never the names. A change in the hash
  between syncs is the drift signal.
- **The accountable human stays named.** `granted_by` names who granted the group. Membership
  changes only by a reviewed change to a person's groups in `policy/users.yaml` followed by a
  hand-run `topaz_sync`, so every widening has a reviewed commit behind it.

## 5. Tests this changes

- `tests/test_grant_sync.py:83,175,190` and `tests/test_validate_policy.py:3-10,38-46` assert that
  a group name is refused as a phantom user. They change to assert that a group name in `subject`
  is still refused, and that `subject_group` is accepted under the §2.4 guards.
- `tests/test_a_service_identity_is_not_a_disclosure_recipient.py:101,115-124` gains the group arm:
  a group with an `svc:` member is refused.
- **`tests/sandbox_e2e/_seal_asset_read_denied_at_the_gate.py:159-174`.** Its denied subject shares
  a group with the allowed one, so a grant to that group would break the seal's control. If Q2
  admits the existing groups, the seal's case must never grant its own group, and a new arm should
  assert that.
- **New seals:** a member of a granted group can read; a non-member cannot (the control); a removed
  member cannot after `topaz_sync`.

No test pins `dataset` as user-only today.

## 6. Questions for the architect

1. **Dataset only, or document too?** Lane 1 recommends dataset first and document in a follow-on
   PR, so that each has its own control.
2. **Which groups may be granted?**
   - **(a)** the existing groups, such as `finance-analysts`. No new group is needed, but a dataset
     grant then rides on a group whose membership was chosen for its persona cells.
   - **(b)** a new kind of group that holds no cells and exists only for data access, declared in
     `groups.yaml` with a marker the validator reads.

   Lane 1 recommends (b), so that joining a persona group never widens a data grant by accident.
3. **`svc:` members:** refused (§2.4)? Lane 1 recommends yes.
4. **The drift audit:** is a logged member count and hash at each sync enough, or must a widening
   wait for approval? Lane 1 recommends the log. Membership changes are already reviewed where
   `policy/users.yaml` changes (§4).

## 7. Delivery

- **Chart:** the manifest line, with a `## <next> — not yet cut` CHANGELOG bullet.
- **Code:** `grant_sync.py`, `validate_policy.py`, and the tests in §5.
- **Order:** the manifest must be live before any `subject_group` row is synced. Otherwise the
  directory refuses the relation, and the sync fails loudly. That is safe, but it is noise.
- Implemented after the rulings in §6, as a separate PR.
