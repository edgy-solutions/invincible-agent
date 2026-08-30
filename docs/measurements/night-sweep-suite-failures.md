---
id:         night-sweep-suite-failures
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  tests/test_endpoint_gating_manifest.py, tests/test_service_enumerations_agree.py, tests/planning/test_archetype_registries_agree.py, setup/ontologies/mesh_system.ttl
summary:    CURRENT ATTRIBUTED FAILURE LIST — 9 failed, 2241 passed, 180 skipped (uv run pytest tests, 2026-08-29 night, post-prime). Every one is attributed to a lane; none is a mystery. THREE ARE LANE 1's OWN and are undeclared inbound routes: /fill_slots, /resolve_instance, /enumerate_instances have no endpoint-gating manifest row, so their posture is undeclared rather than wrong. FOUR ARE ENGINE F's, and one of those is the sharper kind: finance_agent is absent from SERVICE_FILES, so its routes are not gate-checked AT ALL and the suite passes over them — the test's own words, "worse than failing". Filed, not fixed: the night sweep is measurement-only.
---

# Suite failures, attributed — 2026-08-29 night, post-prime

`uv run pytest tests -q` → **9 failed, 2241 passed, 180 skipped, 1 xfailed** in 5m54s.

Run the way CI runs it. A bare `py -m pytest` under-reports: a local `rdflib` skip once hid
eleven hard failures, which is why the invocation is part of the finding.

## Lane 1 — three, and all three are mine

| test | what |
|---|---|
| `test_endpoint_gating_manifest[ontology_service]` | `POST /fill_slots` has no manifest row |
| `test_endpoint_gating_manifest[planning_agent]` | `POST /resolve_instance`, `POST /enumerate_instances` have no manifest rows |
| `test_definitions_are_retrieval_input` | `mesh_system.ttl :: Dependency Neighborhood Set -> 'what does this wait on'` — a query-shaped example in a class definition (`959be6f`) |

**The first two are the ones to read carefully.** The routes are not *wrongly* gated; their
posture is **undeclared**. The manifest's vocabulary is
`gated | releasable_by_design | ungated_by_accident | delegates | internal`, and until a row
exists, nobody has said which. Three new inbound surfaces went in today and none was
classified — the same shape as an engine born without transport auth, which this repo already
has a rule about.

The third: a definition is retrieval input, and a quoted user question makes the class win on
FORMAT rather than subject. One line, in a definition Lane 1 authored.

## Engine F — four

| test | what |
|---|---|
| `test_service_enumerations_agree` | **`agent_fleet/finance_agent/main.py` is absent from `SERVICE_FILES`** |
| `test_archetype_registries_agree` | `fin:BurnRateSeries`, `fin:FundingStatusGrid`, `fin:PerformanceIndexSeries` have no `owl:Class` in `mesh_system.ttl` |
| `test_bindings_point_at_archetypes` | the same three: `rendersAs` SUBJECT end is undeclared, not `mesh:Response` |
| `test_chart_version_tracks_chart_content` | chart content changed after the last `Chart.yaml` edit |

**The first is the worst of the nine**, and the test says why in its own message: the gating
check is parametrised over `SERVICE_FILES`, so a service missing from that dict has its routes
**not checked for a declared posture at all — and the suite passes**, which is worse than
failing. engine-fin's entire inbound surface is currently unexamined by the gate check.

**The middle two are the Contract D gap**, exactly as ADR-0019 records it: Contract D checks
that both endpoint classes EXIST, not what they ARE. The three `fin:` response classes are
undeclared, so the bindings point at subjects that are not `mesh:Response` — and the failure
will present as `gateway-rejected-REFUSED`, which points at the registration rather than at
the missing declaration.

## Identity lane — one route inside a shared test

`test_endpoint_gating_manifest[gateway]` — `POST /internal/identity/redeem` has no manifest
row. Shares a test with nothing else; it is the identity-vault work's to declare.

## Unowned / pre-existing — one

`test_citation_paths` — two `docs/` paths cited but absent, a rename or move left dead links:

* `docs/cortex-data-client.md` — cited from `broker-advertises-unminted-credential.md` (×2) and
  `cortex-client-file-vs-table-reads.md`
* `docs/jupyter_guide.md` — cited from `sdk-blocking-sync-handlers.md` (×2) and
  `sdk-discards-caller-identity.md`

The test names the citing sites, so the fix needs no repo-wide grep.

## Not fixed, deliberately

The night dispatch is **measurement-only, file-don't-fix**. Every fix here is small — a
manifest row, a TTL class, a `SERVICE_FILES` entry — and every one is a *declaration* about
posture or classification, which is a judgment its owning lane should make rather than one a
sweep should guess at. Three of the nine are Lane 1's and will be taken in the morning; the
rest are routed above.
