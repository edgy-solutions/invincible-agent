# Proposal from ca — an `Initiator` kind for non-human worktrees (lane sessions), and the docs/explain tool as its first consumer

to: invincible-agent/seat/architect
from: iagent-mesh-sdk / `lane/ca`, 2026-09-26
re: third OVERNIGHT order, item 2 — "the identity ruling I owe for non-human worktrees ... Proposal only"
cites: `iagent_mesh/interfaces.py` (`Initiator`, `require_person`), `iagent_mesh/transport_auth.py` (`CallerIdentity`),
`agent_fleet/ontology_service/mesh_graph.py:165`, `mesh_vectors.py:96`, `main.py:4566`, `agent_fleet/utils/service_identity.py`,
this lane's 2026-09-25 handoff §3 (the MCP report: "the identity decision is the hard part")

**PROPOSAL ONLY. Nothing is built, tagged or changed.** Where this says "the SDK does X" it was read from source today;
where it says "not verified" it was not.

## 0. The recommendation in six lines

1. **Add `kind: "delegate"`** — a non-human session acting under a *named person's* delegation. Not `service`.
2. **A delegate MUST name the person** in a separate field, `on_behalf_of` (provenance only — never a gate input).
3. **Flip every "service" guard from a denylist to an allowlist** in the same change: `require_person` refuses any
   kind that is not `"person"`. Today it would ADMIT a delegate (§2 — this is the load-bearing finding).
4. **Admission is a Topaz grant, not a kind**: a delegate reads only what a `can_invoke` grant to its subject names.
   First grant: `mesh:explain`. Nothing else.
5. **Kind is declared at the mint, never sniffed.** No code builds an `Initiator` from a token today; that edge is
   unbuilt and needs a named claim knob (§3).
6. **The seal is derived from the type**, so a fifth kind cannot slip past the guards unproven (§5).

## 1. Why not `service`, and why not the operator's own token

The 2026-09-25 handoff offered two ways for a lane tool to identify itself: *the operator's per-user token*, or *a service
identity a ruling admits*. Both are wrong for a lane session, for different reasons:

* **As `service`:** the rule that refuses a service is *"a read attributed to a service records provenance no person can be
  asked about."* A lane session is not that — a named person launched it and can be asked. Reusing `service` would either
  make the docs tool unusable (every guard refuses it) or force the admission of `service` broadly to make it work, which
  is the wrong direction.
* **As the operator (kind `person`, their token):** attributable, and simple, but a non-human loop then reads with the
  operator's *entire* entitlement, and the record says a person did it. That is the authz-subject/provenance-actor collapse
  in its plainest form: attribution changed, the gate did not notice.

`svc:review-starter` (the first non-human subject) is a *deployed workload with its own Keycloak client*. A lane session is
the second class: **ephemeral, attached to a person, on a workstation.** It deserves its own kind for that reason and no
domain word in it (generic-at-birth) — `delegate` names the relationship, not "lane" or "docs".

## 2. The finding that makes item 3 non-optional: the guard is a denylist, in THREE places

`Initiator.kind` is `Literal["person", "service"]` and the guard is `if self.kind == "service": raise`. It is copied,
not imported:

| where | line |
|---|---|
| SDK `Initiator.require_person` | `iagent_mesh/interfaces.py:137` |
| fleet `MeshGraph` impl `_require_person` | `agent_fleet/ontology_service/mesh_graph.py:165` |
| fleet `MeshVectors` impl | `agent_fleet/ontology_service/mesh_vectors.py:96` |

Widening the Literal without touching the guards **admits `delegate` to every operation those three guard** — the
"broken-closed hides brokenness" shape in reverse: nothing fails, the new caller simply passes. (Consumers still on an
old SDK pin would instead reject the new kind at `Initiator` construction — which fails closed, by accident.) So:

* `require_person` becomes `if self.kind != "person"`, naming the kind in the refusal. The name already says this; the
  body never did.
* The two fleet copies flip in the **same change** as the SDK (coupled interim mechanisms retire together). If they
  cannot ship together, the fleet flip goes first — an allowlist over today's two kinds is behaviour-identical.
* `ServiceIdentityRefused` is currently the only refusal type. Either widen its docstring or add a sibling; my
  preference is a sibling (`DelegateIdentityRefused`) so the raise names the ONE condition, as that class's docstring
  demands. Your call; it is spelling.

## 3. Declaring the kind: the edge is unbuilt

`kind` is "declared, not sniffed" — from the token's claims at the edge that minted it. **I found no code that does
this.** The only `Initiator(...)` constructed in the fleet is a fixed `kind="service"` literal
(`main.py:4566`, `_POOL_READ_INITIATOR`); `CallerIdentity` (transport) has `authz_id`/`verified`/`reason`/`raw` and **no
kind**; and `authz_id` carries `svc:<name>` by the *mint contract* — a spelling convention, which is exactly the thing
the opaque-identity rule says nothing may parse. So today "is this caller a person?" has no implementation anywhere; a
delegate exposes that, it does not create it.

Proposal, minimal: **one claim, named by a per-environment knob** (mirroring `USER_ENTITLEMENT_CLAIM`), e.g.
`IDENTITY_KIND_CLAIM`, with values `person | service | delegate`, set by a hardcoded-claim mapper on the Keycloak client
(the mechanism `svc:review-starter` already uses). Carried onto `CallerIdentity` as a declared field. **Absent or
unrecognised → unclassified**: logged under OBSERVE, refused under REQUIRE — never defaulted to `person`. That default
would be the silent-service-read failure `require_authz_id` was written to prevent, one field over.

## 4. `on_behalf_of`, and the authz-subject / provenance-actor split

* `Initiator.subject` (the delegate's own opaque subject) is what a gate checks. `on_behalf_of` (the person's opaque
  subject, same claim discipline) is what the audit trail archives. **Two fields, even though a human might read them
  as one.** A test must show that changing `on_behalf_of` cannot change any authorization decision.
* A validator ties them: `delegate` **requires** `on_behalf_of`; `person` and `service` **forbid** it. A delegate with no
  accountable person is a service under another name and should be refused as one.
* This is Model Y (the delegate has its own grants). **The alternative is Model X** — RFC 8693 token exchange, `sub` =
  the operator, `act` = the session — which gives *permissions ≤ the operator's* by construction (access-regulates:
  outer bound = the person) and is the right shape if a delegate ever needs an entitlement-bearing read. I recommend Y
  now because (a) it matches the ask, "refused by the service-caller guards", which presupposes a distinct kind, and
  (b) X needs token exchange enabled on the realm, **which I have not verified**. The price of Y: nothing in it
  *guarantees* a delegate's grants stay within its operator's. That ceiling is enforced by review of a very small grant
  set, not by construction. **Name that as an accepted limit or choose X.**

## 5. First consumer: `explain` — and what it does and does not need

The tool is an MCP `explain(subject)` calling engine-docs `POST /explain` (`docs_agent/main.py:307`). Facts that shape the ruling:

* `/explain` is an **HTTP route behind transport auth**, not a `MeshGraph`/`MeshOntology`/`MeshVectors` operation. So
  `require_person` never sees it: the delegate is admitted or refused *there*, by (i) the transport layer and (ii) a
  Topaz `can_invoke mesh:explain` check on the delegate's subject — one decider. **Nothing in the handler reads
  `current_caller()` today** (from the handoff §3; still unverified whether `/explain` filters per caller). If it does not
  filter, then any verified caller reads the same pages, and the grant is the *only* gate — worth knowing before
  deciding the docs are "not sensitive".
* Under **OBSERVE** an unauthenticated tool call already works, so a delegate identity changes nothing until the flip;
  it must be in place **before** the flip or every lane's `explain` stops on REQUIRE (the eleven-site class).
* Credential, for the ruling to choose: per-session mint by client-credentials (the `svc:review-starter` pattern — a
  client secret then lives in a workstation env; short TTL mitigates, does not remove) **or** token exchange from the
  operator's own login (no stored secret; needs the realm feature). **Not `MESH_DEV_TOKEN`; not the operator's raw token.**

Tool-side requirements regardless of the above (already in the handoff §3): four outcomes returned as structure not
prose, 409 (sha mismatch) and 503 kept distinct from `abstain`, an explicit timeout. **A denial (401/403) must be a
fourth thing and never an `abstain`** — "you may not read this" reading as "nothing explains it" is the same-observation-
opposite-reasons failure.

## 6. Acceptance — the negatives, written before any code (each proven RED by breaking it, then restored)

1. **Every non-person kind is refused by every guard**, and the test iterates the arguments of the `kind` Literal
   (`typing.get_args`) minus `"person"`, so a *fifth* kind is refused-or-loudly-red without anyone remembering to add it. Runs against the
   SDK guard and both fleet impls. **Break-on-purpose:** revert one fleet copy to `== "service"` → RED for `delegate`.
   Positive control in the same test: `person` is admitted (deny-by-default must prove its ALLOW path).
2. **A delegate with no `can_invoke mesh:explain` grant is refused on `/explain`** — as a denial, not an `abstain`.
3. **A delegate with the grant is admitted** — the positive control for (2).
4. **`on_behalf_of` is never a gate input:** vary it, hold `subject`, decision identical.
5. **An unclassified token is refused under REQUIRE** and logged under OBSERVE; a `delegate` claim on a *person's* client is
   not honoured (kind is bound to the client that mints it — otherwise anyone can declare their own kind).
6. **A delegate token cannot invoke anything but the granted verbs** — one representative ungranted `can_invoke` refused.

## 7. Rulings owed, in the order they block work

1. **Kind name and refusal type** (`delegate`, `DelegateIdentityRefused`) — spelling, cheap, blocks everything.
2. **Model Y (own grants) vs Model X (RFC 8693)** — the real decision; §4.
3. **The claim knob and who owns the mapper** — Keycloak/realm config is not this lane's, and not the SDK's.
4. **Credential lifecycle** — per-session mint vs token exchange; revocation when the session ends.
5. **Who lands the two fleet guard flips** — lane 74's tree, not mine, and they must precede or accompany the SDK widening.

## 8. Ship path

The `Literal` widening and guard flip are SDK code: **v0.9.4-or-later, unreleased until cut → pin → declare, on Chris's
word.** It is a public-contract change (the conformance arm's `initiator kinds` fixture and the docs' §4 text change with
it). No tag and no cut from this lane, and nothing above touches a shared store.

Lane: ia-ca/lane/ca
