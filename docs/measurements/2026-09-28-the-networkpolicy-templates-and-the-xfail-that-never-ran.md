# The NetworkPolicy templates — and the strict xfail that never reached its subject

Date: 2026-09-28. Lane: `ia-np/chart/networkpolicy`, branched from `master` at `17bb2064`.
Dispatch item 5. Unmerged by design: this is a chart PR on a lane.

## What was asked, and what this branch does

| asked | done |
| --- | --- |
| one NetworkPolicy template per engine | ✅ `templates/networkpolicy-engines.yaml`, egress-only |
| allow gateway, registrar, `Mesh*` services, embed gateway | ⚠ three of four; `Mesh*` **does not exist** — see below |
| default-deny egress | ✅ egress-only policies, so everything unnamed is denied |
| one template for the store services | ✅ `templates/networkpolicy-stores.yaml`, ingress-only, 6 stores |
| chart PR on a lane, unmerged | ✅ this branch, not merged |
| "the `interfaces.py` xfail flips to xpass when it renders" | ⛔ **false as stated, and the reason matters** — §4 |

Renders measured, not predicted:

```
helm template iagent helm/invincible-agent                                  → exit 0, 6600 lines,  0 NetworkPolicy
helm template iagent helm/invincible-agent --set networkPolicy.enabled=true → exit 0, 16 NetworkPolicy
                                                                               (10 egress + 6 ingress)
```

No values file is passed in either render. That is deliberate: the question is what the **chart**
does, and a sandbox values file would make the answer a property of one deployment.

## 1. The gate key had to be declared, and its absence broke the whole chart

`networkPolicy` was not in `values.yaml`. `{{- if .Values.networkPolicy.enabled }}` against an
absent parent is not a quiet skip:

```
Error: template: invincible-agent/templates/networkpolicy-stores.yaml:37:14: executing
"...networkpolicy-stores.yaml" at <.Values.networkPolicy.enabled>:
nil pointer evaluating interface {}.enabled
```

`helm template` exited 1 and emitted **nothing** — every template in the chart, not just these two.
Found by rendering, not by review: both templates read as correct, and the seal's text arms were
green. The declaration is now in `values.yaml` with that measurement recorded beside it, so the key
is understood as load-bearing rather than as documentation of a default.

## 2. Two name registries, and a transcription would have silently denied four of six pods

`SUBSTRATE_CLIENTS` is keyed on agent/image names. A `podSelector` can only match the chart's
`app.kubernetes.io/component` label. Four of the six admitted pods are named differently:

| allowlist name | chart component |
| --- | --- |
| `engine-o` | `engine-o` |
| `mesh-registrar` | `mesh-registrar` |
| `restate-analyst` | **`engine-a`** |
| `weaviate-expert` | **`engine-w`** |
| `neo4j-expert` | **`engine-e`** |
| `presentation-agent` (the exception) | **`engine-f`** |

A policy written in the allowlist's own vocabulary would be valid YAML, would deploy without a
warning or an event, and would deny four of the six pods it was written to admit. There is no
error state for a selector that matches nothing. The reconciliation lives in exactly one place,
`AGENT_TO_COMPONENT` in the seal, and an allowlist entry with no mapping fails an arm rather than
being dropped.

## 3. Presence is not enforcement — and satisfying a guard can demote it

Both templates are gated on `networkPolicy.enabled`, which defaults to **false**, and nothing in
the repo sets it. So landing them changes what the chart *can* do and nothing about what it does.

That matters because three documents asserted the gap as an absence of manifests. Landing default-off
templates makes those sentences false while the perimeter stays exactly as open as before, and a
reader who greps for the manifest finds it and stops. All three were rewritten to the narrower,
weaker claim — the chart can apply a policy, and does not unless an operator turns the gate on:

- `tests/test_substrate_address_lint.py` — the provenance row (ZERO → TWO, both default-off) plus an
  inserted note that a rendered-nothing template is inert in exactly the way a values file nobody
  passes is inert: its content is verifiable and its wiring is absent, and only the wiring fires.
- `tests/test_substrate_allowlist_exceptions_expire.py` — header and exclusion paragraph.
- `iagent-mesh-sdk/iagent_mesh/interfaces.py:20-37` — **NOT fixed here; it is a different repo** and
  cannot be part of a chart PR. Routed to `lane/ca` as the third home of the now-false claim.

Enabling the gate is a **traffic change**, not a hardening no-op: the engines that still read the
stores directly are what the policy exists to stop, so they break the moment it is on. That
decision is what the address lint has been standing in for, and the manifest landing does not make
it.

## 4. ⛔ The strict xfail was satisfied by a crash, not by the gap

The dispatch said the xfail "flips to xpass when it renders". The marker was on
`test_THE_NETWORKPOLICY_MANIFEST_EXISTS`. Removing it and running the arm gave:

```
NameError: name '_REPO' is not defined
```

Neither `_REPO` nor `pathlib` was ever imported into that module. **The arm never read a single
file.** A strict xfail is satisfied by *any* failure, and a crash is a failure — so it reported the
expected red on an exception raised two lines before the question, and would have gone on reporting
it after the manifests landed. Forever, and silently.

It was not carrying the gap; it was carrying a typo. The one thing it existed to make impossible —
the surrounding prose quietly going stale — is precisely what it permitted. My first draft of the
replacement docstring credited the marker with "turning the suite red the moment the gap closed";
that was a justification invented downstream that fit by construction, and it is kept in the file
as the finding rather than deleted.

**A nonzero result is not a measurement.** An arm that cannot reach its subject is
indistinguishable, from outside, from an arm that reached it and found the expected answer — and
`strict=True` converts that into a guarantee of attention nobody was paying. The same reasoning
applies to a mutant that crashes.

Fixed, then positive-controlled, because a green here would otherwise be worth no more than the
xfail was:

| state | result |
| --- | --- |
| manifests present | PASS |
| both templates moved aside | **FAIL on its own assertion text** (not `NameError`) |
| templates restored | PASS |

### The class, censused rather than left as one instance

This repo already records the family at `tests/test_task_verbs_by_kind.py:236-244` — "a strict
xfail is only as good as the test under it: it guarantees a signal only if the failure mode cannot
CHANGE." This instance is the sharper sub-case: the failure mode was never the subject at all.

Every remaining live `xfail` decorator, checked with `--runxfail`:

| arm | verdict |
| --- | --- |
| `planning/test_leadership_questions_map.py:201` | legitimate — fails on a real `AssertionError` ("a human must read the 17 questions") |
| `routing/test_b2_format_ingest_guards.py:133` | ⚠ non-strict **and skipped** — needs a live `driver` fixture |
| `routing/test_b2_format_ingest_guards.py:172` | ⚠ same |

The last two are doubly inert: a skip beats an xfail, so offline they never evaluate at all, and
their skip is keyed on a **substrate read** rather than a declared condition. That is exactly the
concern dispatch item 4 raises about skips; it is recorded here and left to that item.

## 5. What the text arms structurally could not see, and the mutants that proved it

`test_EVERY_ENGINE_IN_THE_CHART_HAS_AN_EGRESS_POLICY` compares two *files* and passes 16-to-16. The
render is 10, because both files gate each entry on that engine's `.enabled` and six engines ship
disabled. A text arm compares **populations**; the hazard lives in the **conditions** attached to
them. So three arms were added against the render, and each was mutated:

| mutant | killed | survived |
| --- | --- | --- |
| engine-o's policy suppressed while its Deployment still renders | `test_EVERY_RENDERED_ENGINE_WORKLOAD_HAS_AN_EGRESS_POLICY` | ⚠ the **text** arm stayed green — the proof the render arm is not redundant |
| rule 4's target typo'd to `lite-llm` | `..._TARGETS_THAT_SELECT_NO_POD...` | ⛔ `..._NAMES_A_COMPONENT_THE_CHART_CANNOT_DEPLOY` — see below |
| a fourth target added naming a real-but-disabled component (`engine-b`) | `..._TARGETS_THAT_SELECT_NO_POD...` | — |

Each mutation was reverted by its own inverse and the suite re-run to 12 passed / 1 skipped between
mutants, not restored to `HEAD` — the templates are new files, so `HEAD` is not a valid baseline.

### ⛔ One of my own new arms could not fire, and mutation is what found it

`test_NO_EGRESS_RULE_NAMES_A_COMPONENT_THE_CHART_CANNOT_DEPLOY` built its "declarable components"
set by scanning **all** templates — including the two policy templates it was checking. Every
component a policy names is written as an `app.kubernetes.io/component:` line *inside* the policy
file, so the typo declared itself and the arm passed for the same reason it should have failed. The
total was derived from the same parse as the parts. Fixed by excluding the two policy files, with a
positive control asserting the remaining set still contains known components, so the exclusion
cannot quietly remove too much and red on correct templates. Re-running the same mutant now kills it.

## 6. ⛔ In sandbox, the embed-gateway rule selects nothing

A rule naming a real component is **not** evidence the dependency is reachable. At chart defaults,
two of the three named egress targets render no workload:

| target | default | sandbox |
| --- | --- | --- |
| `cortex-bff` | enabled | live |
| `mesh-registrar` | `enabled: false` | ✅ `values-sandbox.yaml` sets `meshRegistrar.enabled: true` |
| `litellm` | `enabled: false` | ⛔ **absent from `values-sandbox.yaml`, so it inherits false** |

Both mentions of the in-cluster proxy in `values-sandbox.yaml` are **comments**. The endpoint the
fleet actually uses is set by `LLM_BASE_URL` to an **off-cluster host**, which no `podSelector` can
ever match — a NetworkPolicy names pods. So enabling this gate against sandbox as shipped denies
every engine its model and embedding endpoint, and `extraEgress` — the only rule able to reach an
off-cluster host — defaults to `[]`.

That failure would present as **model timeouts, not as a policy error**, which is the same shape as
the missing-DNS hazard: a default-deny egress does not announce what it cut. Whoever enables the
gate must populate `extraEgress` with that endpoint first. The address itself is deployment detail
and is not in any tracked file.

Rule 4 is kept, not deleted — it is correct for any deployment running the in-cluster proxy — and is
sealed as a **known-inert target** by a ratchet: the arm asserts the set of targets selecting no pod
is exactly `{mesh-registrar, litellm}`. It cannot assert reachability; nothing renderable can. It
asserts that set does not **grow** unnoticed, so a third name means the perimeter has quietly
acquired a dependency it cannot reach. Both directions carry instructions in the failure message,
because a smaller set here is not automatically an improvement.

## 7. The perimeter this PR builds is not a perimeter, and that is scope, not a defect

With the gate on, 29 workloads render and **10** have an egress policy. The dispatch asked for one
template per *engine* plus the stores, so the other 19 — `dagster-*`, `projector`, `domain-broker`,
`cortex-ui`, `electric`, `topaz`, `pub-tools*`, `dag-tools*`, and the stores themselves — egress
freely. Stated here so nobody reads "NetworkPolicy shipped" as "egress is controlled".

Worth a follow-up rather than a claim: the substrate-address lint scans `agent_fleet/` only, so
`src/iagent/projector/` has never been checked for a direct store connection, and `projector`
renders a workload with no egress policy. Not measured here; named so it is not lost.

## 8. What I did not do

- **Did not enable the gate anywhere.** No values file sets it, and a live rollout is not this
  branch's business.
- **Did not merge.** Unmerged on a lane, per the dispatch.
- **Did not touch `iagent_mesh/interfaces.py`.** Different repo; routed to `lane/ca`.
- **Did not verify any policy on a live pod.** Every claim here is from `helm template` and from
  reading the chart. Whether a policy is *applied* anywhere is not observable from the repository,
  and the live half belongs to a roll's verification legs.
- **Did not add policies for the 19 non-engine workloads** (§7), nor an ingress policy for the
  engines themselves — these objects say who may open a connection *to* a store and nothing about
  any store's own egress.

## Reproduce

```bash
helm template iagent helm/invincible-agent | grep -c '^kind: NetworkPolicy'                # 0
helm template iagent helm/invincible-agent --set networkPolicy.enabled=true \
  | grep -c '^kind: NetworkPolicy'                                                         # 16
uv run --frozen pytest tests/test_networkpolicy_admits_the_allowlist_by_component.py \
  tests/test_substrate_allowlist_exceptions_expire.py tests/test_substrate_address_lint.py -q
# 23 passed, 1 skipped   (the skip is the exception backstop, 2026-12-14, not yet due)
```
