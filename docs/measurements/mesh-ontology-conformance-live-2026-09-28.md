# Measurement — `MeshOntology` conformance against the real Jena implementation, driven live

**Date:** 2026-09-28 · **Lane:** `ia-74/lane/74` · **Subject:**
`agent_fleet/ontology_service/mesh_ontology.py::JenaMeshOntology` against the SDK's
`check_ontology_contract`, talking to the sandbox RDF store.

**Ordered, verbatim:** "MeshOntology conformance against your real Jena implementation, if not yet
run; report."

## 0. The answer

**It had not been run, and it now has. The implementation CONFORMS.** Read-only throughout; nothing
was written to the store, which is why the fixture's typed terms were *discovered* in it rather than
seeded into it.

| leg | result |
| --- | --- |
| `ask` on a present IRI | `answered`, 1 row |
| `ask` on an absent IRI | **`empty`** — not `failed`, not `unreachable`, not `answered` |
| `construct` on a present subject | `answered`, one `str` row, 5032 characters of Turtle |
| term types in that Turtle | intact — `@en-US` language tags and `^^xsd:anyURI` |
| `check_ontology_contract` | **PASSED** |
| positive controls | **5 of 5 failed as required** |

## 1. Why "if not yet run" resolved to *not run*

The arm is **not in the pinned SDK**. Measured, not assumed: the interpreter in this worktree reports
`iagent-mesh 0.9.3`, imported from `site-packages` — a copy, not an editable install — and it has
`check_ontology_contract`: **False**, `check_ontology_writer_contract`: **False**,
`MeshOntologyWriter`: **False**. So the fleet cannot see the SDK's working tree at all.

The fleet's own arm, `test_the_SDKs_ontology_arm_runs_the_moment_the_pin_carries_it`, is correctly
written and behaved correctly: it **skipped**, against a measured version rather than a story, and it
reds instead of skipping if the pin ever advances while the arm is still absent. 28 passed, 1 skipped.

**That is a skip, not a conformance result.** A dormant arm excused against the right version is good
hygiene and it is still not evidence about the implementation. Hence this run.

## 2. How it was driven, and the control that makes it mean something

The SDK's working tree was placed first on `sys.path` and the loaded module's path **asserted** to be
under it — driving the pinned 0.9.3 copy would have measured the very absence that made this
necessary. The implementation was pointed at the store's declared SPARQL endpoint through a local
read-only forward (coordinates stay in the out-of-repo log).

**The typed terms were read out of a real `construct`, not typed by hand.** A term I invent that the
serializer never emits makes the contract's own fixture-discrimination arm pass on a fiction. Phase 1
dumped the Turtle and extracted what the serializer actually produced; phase 2 passed two of those
back in — one language tag and one datatype, so both branches of the discrimination check are
exercised.

Five controls, each differing from the subject in exactly the property its arm claims to decide on,
and each **failed**:

| control | the refusal it earned |
| --- | --- |
| `ask(absent)` raises | "'could not ask' read from a legitimate absence" |
| `ask(absent)` returns `answered` | "both cases present as 'answered', so this arm would pass against the defect it tests for" |
| `construct` strips term types | "Term types were DROPPED … types intact is the point of CONSTRUCT over SELECT" |
| `typed_terms` empty | "a suite over nothing passes everything" |
| `typed_terms` carries an untyped term | "fixture does not discriminate … would still emit it" |

## 3. What the store actually holds — and why that changes the offline fixture's standing

A literal-datatype census of the sandbox graph, five distinct kinds:

| count | datatype |
| --- | --- |
| 2048 | `xsd:string` |
| 598 | **language-tagged** |
| 191 | `xsd:anyURI` |
| 90 | `xsd:integer` |
| 75 | `xsd:boolean` |

**No `xsd:date`, and no bare `@en`.** The offline fixture's `TYPED_TERMS` are
`'"2026-09-26"^^xsd:date'` and `'"hello"@en'` — neither form occurs in production. This does **not**
weaken the offline arm: its property is discrimination between a typed form and its own stripped
twin, which holds for any type, and its control is built for exactly that. It does mean the offline
fixture is not evidence about the production serializer. The live run is, and the arm's docstring now
says so instead of leaving its own documented weak leg standing as a permanent caveat.

## 4. Two candidate findings raised and REFUTED, and the instrument defect behind both

Worth more than the conformance result, because both were nearly filed.

1. **"The sandbox write path is refusing by name."** `engine-o`'s `substrate_posture` refuses SPARQL
   UPDATE when `JENA_UPDATE_ENDPOINT` is undeclared, and two reads of the deployment said it was
   undeclared: it is absent from the container's `env[]`, and a listing of the mounted ConfigMap's
   keys returned nothing matching. **False.** The running process has it. A pod's own environment is
   the population; a deployment spec read is a sample of it.
2. **"The pod predates its spec."** The obvious explanation for (1). **False** — generation 224,
   observedGeneration 224, 1/1 updated. Fully rolled out.

**The defect was mine.** `kubectl get cm … -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'`
returned **empty** rather than erroring, and an empty result from an unsupported query is
indistinguishable from a real absence. Parsing the ConfigMap as JSON showed both `JENA_SPARQL_ENDPOINT`
and `JENA_UPDATE_ENDPOINT` present. A silent empty read is the same instrument failure as a matcher
that matches nothing — it needs a positive control, and here the positive control was the thing that
should have been the first read.

## 5. Not claimed

- Nothing about the **write** half. `MeshOntologyWriter` and `iagent_mesh.writers.jena` exist in the
  SDK's tree and are **not** in the pin, so they were not exercised, and exercising them would need a
  store write, which is not this seat's to make.
- Nothing about conformance **under the pin**. This run used the SDK's working tree. What it licenses
  is a prediction: when a release carrying the arm lands and the pin bumps, the fleet's dormant arm
  should go green without code changes. If it does not, the difference is between the working tree and
  the release, and this report is the baseline for that comparison.
- Nothing about **other datasets**. One dataset, one subject, one store.
