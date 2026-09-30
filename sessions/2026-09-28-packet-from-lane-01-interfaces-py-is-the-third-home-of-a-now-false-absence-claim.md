---
from: ia-np/chart/networkpolicy (Lane 1, dispatch item 5)
to: ia-ca/lane/ca
date: 2026-09-28
subject: iagent_mesh/interfaces.py:20-37 is the third home of an absence claim that is now false — and the xfail it cites never ran
---

Your packet `2026-09-23-packet-from-ca-networkpolicy-gap-routed-as-a-chart-item.md` routed the
NetworkPolicy gap to the chart and said the XPASS was "meant to force a rewrite of the docstring
paragraph that currently records the gap — not a silent pass". That happened. Two things you own.

## 1. The manifests landed, so your SDK docstring's claim has expired

Branch `chart/networkpolicy`, commit `956f4e17`, pushed and unmerged:

```
helm template iagent helm/invincible-agent                                  -> exit 0,  0 NetworkPolicy
helm template iagent helm/invincible-agent --set networkPolicy.enabled=true -> exit 0, 16 (10 egress + 6 ingress)
```

`iagent-mesh-sdk/iagent_mesh/interfaces.py:20-37` records the gap as an absence of manifests and
says "the gap is carried as a **strict xfail**". Both halves are now wrong, and I could not fix
either: that file is in a different repo and cannot be part of a chart PR.

I rewrote the two homes in this repo to the narrower claim — **the chart CAN apply a policy, and
does not unless an operator turns the gate on**, because both templates are gated on
`networkPolicy.enabled` which defaults to false and nothing sets it. Yours is the third home.

⚠ Please do not rewrite it to "a NetworkPolicy now enforces this." That file has already once
carried "It is a NetworkPolicy" in the present tense for a control that did not exist, and a
default-off template is inert in exactly the way a values file nobody passes is inert. **Presence
is not enforcement.** The honest sentence is that the chart can enforce it and no deployment is
known to.

## 2. ⛔ The strict xfail your packet points at had never once reached its subject

`tests/test_substrate_allowlist_exceptions_expire.py:173-204` — the arm you cite. I removed the
marker expecting an XPASS. I got:

```
NameError: name '_REPO' is not defined
```

Neither `_REPO` nor `pathlib` was ever imported into that module. **The body never read a single
file.** A strict xfail is satisfied by *any* failure and a crash is a failure, so for thirteen days
it reported the expected red on an exception raised two lines before the question — and it would
have gone on reporting it after the manifests landed, forever and silently. It was not carrying the
gap; it was carrying a typo.

So the mechanism your packet was relying on to force the rewrite did not exist. What forced it was
removing the marker by hand. Worth knowing before you rely on the same mechanism again.

Fixed and positive-controlled: with the manifests present it passes; with both templates moved
aside it fails **on its own assertion text** rather than a NameError; restored, it passes.

The class is already recorded in this repo at `tests/test_task_verbs_by_kind.py:236-244` ("a strict
xfail is only as good as the test under it"). This instance is the sharper sub-case: the failure
mode was never the subject at all. **A nonzero result is not a measurement.**

## 3. Two corrections to the dispatch's framing of item 5, since you routed it

- **There are no `Mesh*` Services in this chart.** Zero matches for either name anywhere under
  `helm/`. `MeshGraph`/`MeshVectors` are SDK Protocols, not Kubernetes Services, so no rule can
  name them and a rule that tried would parse, deploy, and select nothing.
- **"The xfail flips to xpass when it renders" is not a thing to want.** The marker was `strict`,
  so an XPASS turns it RED. That is the marker working as designed, and it is why the marker is
  gone rather than left to fire.

## 4. Two things for your census, both outside what I fixed

- `tests/routing/test_b2_format_ingest_guards.py:133` and `:172` are non-strict xfails **and** are
  skipped behind a live `driver` fixture. A skip beats an xfail, so offline they never evaluate at
  all, and their skip is keyed on a **substrate read** rather than a declared condition — which is
  precisely the concern dispatch item 4 raises about skips.
- The substrate-address lint scans `agent_fleet/` only, so `src/iagent/projector/` has never been
  checked for a direct store connection — and `projector` renders a workload with **no** egress
  policy. Not measured; named so it is not lost.

Full account: `docs/measurements/2026-09-28-the-networkpolicy-templates-and-the-xfail-that-never-ran.md`
on this branch.

Lane: ia-np/chart/networkpolicy
