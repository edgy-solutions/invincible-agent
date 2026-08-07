# `ENABLE_AGENTIC_AUTH` — the flip packet (ADR-0025's terminus)

**What this is.** Turning `ENABLE_AGENTIC_AUTH` on is **not a configuration change**. It is the
final step of ADR-0025's enforcement arc — `authorization.md:262`, *"flips LAST, after all
enforcement points migrate"* — and executing a migration's last step as a hygiene commit would be
the looks-like-the-fix trap at architecture scale. This packet exists so the flip happens as the
named terminus of an arc with its preconditions enumerated, not as a one-line values edit.

**Ruling that produced it (2026-08-07).** The target posture is settled: *enforcing by default;
auth-off must be explicit.* Deny-by-default applied to configuration — forgot-and-locked is a loud
403 someone investigates, forgot-and-open is silent and indistinguishable from working. The read
then established that the target already has a name, an ADR and a stated precondition, so the
ruling is the DESTINATION and the ADR owns the PATH.

## Established by reading the code (2026-08-07)

| fact | evidence |
|---|---|
| default is **OFF** | `os.getenv("ENABLE_AGENTIC_AUTH", "false")` — `core/authz.py`, `datahub_wrapper/main.py`, `weaviate_expert/service.py` |
| unset ⇒ gates **disabled** | `auth_dependency` returns token-or-None unverified; decorator passes `user_jwt = None` |
| sandbox sets `false` | equal to the default — **not** a posture downgrade |

**The sandbox value is the ruling already half-obeyed.** Setting a value equal to the default is
exactly what "never ride an implicit default" prescribes: someone made the dark-launch posture
visible on the deployment. It was missing only the comment and the chart's authority — both now
landed.

## ONE FLAG, THREE ENFORCEMENT POINTS — the design, not a defect

| site | gate |
|---|---|
| `core/authz.py` | JWT verification (auth dependency + decorator) |
| `datahub_wrapper/main.py` | `query_metadata` → Topaz `can_view` ask |
| `weaviate_expert/service.py` | per-chunk `can_read` filter before synthesis |

The three-jobs rule fires but its verdict **inverts** here. One flag over three points means the
system can never occupy a **partial enforcement state** — door verified but chunks unfiltered,
catalog asked but JWTs unverified. Each half-on state is a configuration whose security properties
nobody has reasoned about: the multiple-heads syndrome ADR-0025 exists to kill. All-at-once is the
deliberate answer.

**Road not taken, recorded:** staging the migration per-enforcement-point requires **splitting the
flag first**. Anyone who wants a partial rollout must do that as its own change, with the partial
states enumerated and reasoned about — not by adding a second flag beside this one.

## ITEM 0 — adjudicate the gating manifest against the code

`endpoint_gating_manifest.yaml:17` counts dark-launched gates as **"gate present", not none** — so
the manifest is the claim and the code is the authority. Read-only, first, before any flip:

1. Every enforcement point the manifest lists → **verified live in code** behind this flag.
2. Every endpoint the migration expects gated → **checked for a gate at all** (present-but-dark is
   fine; absent is a finding).
3. Stop-and-report on any divergence rather than flipping over it.

## THE CONVERGENCE — the DA read path is NOT behind this flag

Stated loudly because it is the packet's real precondition and it is easy to miss:

DA's engine-side authz was **deliberately removed** (`endpoint_gating_manifest.yaml:318-323`, "the
DA-read seal") in favour of a single gateway gate — correct under single-PDP discipline. What that
removal silently assumed is that the identity reaching the gateway is trustworthy. It is not:
`data_analyst/main.py:218` takes the acting identity from an **unauthenticated body field**
(`request["user_email"]`) and mints `X-Originator-Email` from it, and `main.py:203` shows the
endpoint requires no token at all. **The removal wasn't the bug; the unverified subject was.**

**Flipping `ENABLE_AGENTIC_AUTH` does nothing for that path.** So "all enforcement points migrated"
is FALSE until the DA read path has a verified subject — which is the two-lock `on_behalf_of` work
(lock 1: `/analyze_data` requires a verified caller; lock 2: the entitlement subject is derived
supervisor-side from the front-door identity and honored only from a delegation-granted asserter).

## LOCK 1 IS NOT A SEPARATE ITEM — it is this flip (established 2026-08-07)

The packet originally sequenced "two-lock work → item 0 → flip". Enumerating the caller graph
dissolved that distinction and corrected two errors in the sketch:

**Error 1 — the wrong token.** The packet said `/analyze_data` should require "the
`iagent-data-analyst` token". That is DA's **outbound** credential to the data broker; it cannot
be what DA verifies **inbound**. The inbound caller is the supervisor.

**Error 2 — lock 1 was never separable.** ZERO engines verify inbound auth
(`Depends`/`verify_jwt`/`auth_dependency` = 0 across all six) because that verification IS
`core/authz.py`'s `auth_dependency`, dark-launched behind this flag. So lock 1 cannot be turned on
"just for DA" without SPLITTING the flag — the road already recorded as not taken. Lock 1 is this
flip wearing a different name.

### NEW PRECONDITION — `svc:supervisor` must exist before the flip

Flipping the flag makes `core/authz.py` verify JWTs fleet-wide, which requires **every legitimate
caller to have a verifiable identity**. The supervisor's specialist dispatch sends **no
Authorization header at all**, and `policy/users.yaml` holds exactly two service identities —
`svc:review-starter` and `svc:data-analyst`. **There is no supervisor identity.**

So flipping today would **deny the supervisor's own calls** — the same empty-caller/no-identity
failure the ceremony work hit, predicted this time rather than witnessed. Required first:
1. `svc:supervisor` / `iagent-supervisor` per the mint contract;
2. into `keycloak.serviceClients` (the reconcile job then creates it in every environment — the
   mechanism the 2026-08-07 recovery proved);
3. a mint-at-use at the supervisor's dispatch, and the token presented on the specialist POST.

Item 0's enumeration inherits this: "all enforcement points migrated" is false while any
legitimate caller lacks a verifiable identity.

### What lock 2 already delivered (`0555620`)
The subject's VALUE is trustworthy on the legitimate path — derived from `current_user.authz_id`,
un-nameable by a caller, guarded by break-on-purpose-verified assertions. It does NOT close
transport auth. Both halves are needed; only one is done.

## Sequence — these are ordered, not parallel

1. ~~**Two-lock `on_behalf_of` + endpoint auth**~~ — RE-SEQUENCED 2026-08-07. Lock 2 is DONE
   (`0555620`). Lock 1 is not a separate item: it IS this flip (see above).
2. **`svc:supervisor` identity** — mint contract + `keycloak.serviceClients` + mint-at-use on the
   dispatch. Without it the flip denies the supervisor's own calls.
3. **Item 0 enumeration** — only after (2) can it honestly conclude all points are ready.
4. **The flip** — `enforcement.agenticAuth: true`, one change, three gates, witnessed.
5. **Fresh-deploy posture test** becomes the standing guard: assert ENFORCING on a render with
   **no overrides**. Per the sentinel-per-input rule, that test is what catches this class at the
   chart instead of at an audit. It only makes sense once enforcing is the intent — before the
   flip it would assert the wrong posture.

## Already landed (2026-08-07) — the interim, loud

Neither changes behaviour; both make the interim posture legible, which is pure gain in any posture.

* **Chart**: `enforcement.agenticAuth` in values + `ENABLE_AGENTIC_AUTH` in the ConfigMap,
  hasKey-guarded, with the direction and the not-hygiene warning commented.
* **Startup announcement** at all three sites, naming the **source** as well as the state:
  `agentic auth: DISABLED (explicit config | DEFAULT, dark-launch ADR-0025) [<site>]`.
  Source matters per the `admitted_by` pattern: after the flip, `DISABLED (DEFAULT)` must be
  **impossible**, and a line that cannot distinguish "nobody configured this" from "someone chose
  this" cannot show that. It also makes the posture assertion readable in a log, not only a suite.
