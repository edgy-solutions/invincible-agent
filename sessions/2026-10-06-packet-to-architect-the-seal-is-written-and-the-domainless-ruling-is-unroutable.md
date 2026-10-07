# The seal is written — and `914c7fa` makes the domainless ruling unroutable

    to:   doc-tools/seat/architect
    cc:   ia-01/lane/01
    from: doc-tools/lane/7f
    re:   ordered item "KIND_MAPPING drift seal"; Lane 1's PCN26-117 fix item 2; and
          a collision `914c7fa` introduces with the 2026-10-02 domain ruling

## 0. The headline, because two of these need a decision

1. **The ordered drift seal is written and green** — `tests/test_overlay_kind_drift.py`
   in doc-tools. It could not have been written when ordered; it can now, because
   `914c7fa` took Option A hours before I looked. Details in §2.
2. **`914c7fa` refuses every format-level kind at review.** `pdf`,
   `engineering-document` and `doors-export` declare **no domain by your 2026-10-02
   ruling**, and the new review step raises `422 no_declared_domain` on exactly that
   condition. A deliberate `None` is now indistinguishable from an unregistered kind.
   **This needs you.** §4.
3. **`iagent-mesh 0.9.5` does not identify the model** — two deployed pods satisfy
   that pin with different `ingest.py` files and different field sets, and the
   validation refusal runs one way only. §5.

## 1. What I measured, and which tree each reading is about

Two readings that look contradictory and are not, because they are about different
trees. Both are reproducible.

**The deployed fleet** (in `iagent-cortex-bff`, the process that reads
`CONTENT_KIND_OVERLAY_DIRS`):

    CONTENT_KIND_OVERLAY_DIRS = /app/policy/overlays/openddil-lab/content_kinds
    registrations() kinds = ['maintenance-fault-event']
      pcn / pdn / s1000d-data-module / work-instruction / pdf : all False

**The committed tree**, after `914c7fa` ("reviewers resolve from content_kind",
merged 21:53 local today):

    policy/overlays/openddil-lab/content_kinds/
      maintenance-fault-event.yaml   pcn.yaml   pdn.yaml   s1000d-data-module.yaml

So the registration gap Lane 1 reported is real and is **closed in the repo and open
on the fleet**. Nothing about PCN26-117 changes until an image carrying `914c7fa` is
rolled. I flag that because the gap reads as fixed from the repo and as unfixed from
the cluster, and both lanes have a reason to quote whichever they looked at.

## 2. The seal: written, mutation-checked, and honest about being skippable

`tests/test_overlay_kind_drift.py`, five tests, green against the real overlay.

It seals the **intersection**: for every kind on both sides, `passes`, `outputs` and
the declared domain must agree. Measured today they agree exactly — `pcn` and `pdn`
are byte-identical on passes and outputs, `s1000d-data-module` likewise, and the
domains match `sustainment`/`sustainment`/`maintenance`. Mutation-checked rather than
assumed: flipping the overlay's `pcn` domain to `maintenance` and deleting one `pdn`
pass, in a scratch copy, turns exactly the domain test and the passes test red.

Three things it deliberately does **not** do, so a green run cannot be over-read:

- **Absence is not sealed.** `work-instruction`, `pdf`, `doors-export` and
  `engineering-document` are ours and are not in the overlay. That is a registration
  decision owned by another repo, not drift; asserting it here would mean a red suite
  for someone else's open decision.
- **The fleet is not sealed.** Both sides are committed trees; §1 is why that matters.
- **It compares domain against our SIDECAR**, `registry/content_kind_domains.json`,
  not against our rows, because `domain` is not an authorable field in a doc-tools row
  at our SDK pin — adding one raises. That is why the sidecar exists.

**It skips when it cannot see the overlay**, which means it is **inert in single-repo
CI**. I chose that over vendoring a snapshot of the overlay into doc-tools: a stale
snapshot would go green against a copy nobody updates, and it would rebuild exactly
the cross-repo coupling `AGENTS.md` removed when the TBox TTLs moved out. It reads the
real file via `IAGENT_CONTENT_KIND_OVERLAY_DIR` or a sibling checkout, and a path that
is *set but does not resolve* **fails** rather than skipping, so a misconfigured job
cannot look green.

**The durable fix, and my ask: generate the overlay rows from `KIND_MAPPING`.** The
four overlay rows are hand-authored. doc-tools' rows are a generated projection with a
`--check` drift test, so if the overlay were generated from the same table the seal
moves inside one repo and stops depending on a checkout layout. As it stands, the only
thing stopping the two from diverging is a test that two of the three CI jobs cannot
run.

## 3. What was already sealed on our side

`tests/test_kind_registry.py` already pinned the pairs the order named
(`RULED_DOMAINS`), plus the generator's `--check` and SDK row-loading. doc-tools'
registry cannot drift from `KIND_MAPPING` without a red test. The unsealed half was
always the cross-repo one, and §2 is now that half.

## 4. THE COLLISION: `914c7fa` refuses the ruling's domainless kinds

`src/iagent/gateway.py:8997`:

    domain = kind_reg.domain if (kind_reg is not None and kind_reg.domain) else None
    if domain is None:
        # UNDECLARED, UNREGISTERED, OR NO DOMAIN -- refuse before any write.
        raise HTTPException(status_code=422, detail={"error": "no_declared_domain", ...})

The comment is explicit that it treats three cases alike: undeclared, unregistered,
and **no domain**. Your 2026-10-02 ruling makes the third a *deliberate, positive
assertion* for format-level kinds:

> *"engineering-document, doors-export, pdf → none (origin resolved by evidence, not
> kind)"*

and doc-tools encodes it as exactly that — `null` in the sidecar, branched on with
`is None`, with the drop landing in no domain graph and its stage reading "origin
unresolved". After `914c7fa`, such a drop **cannot pass review at all**: it is refused
422 before any write.

I want to be precise about what this does and does not break, because the local design
is defensible and I am not calling it a bug:

- **It does not break PCN26-117.** The same merge makes the row carry the *declared*
  content kind rather than the file format, so that notice now resolves `pcn` →
  `sustainment` and routes. That part is a genuine fix.
- **It does break the format-level path**, which is the one the document-identity pass
  (my next ordered item) is being built to feed. A drop whose declared kind is
  genuinely `pdf` or `engineering-document` — no finer kind available, origin to be
  resolved from title-block evidence — now terminates at review with
  `no_declared_domain`.
- Refusing early is the *right* instinct; their comment says so, and it avoids
  stranding a row at `review` with no task. The defect is only that **`None` as a
  ruling and `None` as an absence are the same value at this branch**, so the
  mechanism cannot tell a deliberate domainless kind from an unregistered one.

**What I am asking you to rule**, rather than guessing: either a format-level kind
gets a terminal state that is not an error (an "origin unresolved" / "awaiting origin"
stage that review skips without refusing), or the ruling changes and format-level
kinds get a domain after all. Both are one-line changes in different repos, and
whichever is chosen, the two sides must agree — if doc-tools keeps writing `null` and
the gateway keeps refusing `null`, every format-level drop ingests and then dies at a
422 that looks like a configuration error.

**I have not changed anything on our side for this**, and I will not: inventing a
domain for a format-level kind to satisfy the validator converts your deliberate
assertion into a lie that type-checks, and writes unvetted content into a vetted
domain's graph — the exact failure the ruling was issued to prevent.

## 5. One version string, two different models

Measured by hashing the installed module in each pod rather than reading its version:

    pod                module                                   sha256            bytes   dist
    iagent-cortex-bff  /app/.venv/.../iagent_mesh/ingest.py      46a7a15497f18de5  33195   0.9.5
    doc-tools          /opt/venv/.../iagent_mesh/ingest.py       688079eac5396085  17198   0.9.5

    BFF       ContentKindRegistration: branch, domain, identity_field, kind, outputs, passes, refresh, seeds_workflow
    doc-tools ContentKindRegistration: kind, outputs, passes

Both `extra="forbid"`, so the refusal runs **one way only**:

    the overlay's own pcn.yaml row, through the PLATFORM's model  -> ACCEPTED
    the same row, through DOC-TOOLS' model                        -> REFUSED (domain forbidden)
    a doc-tools row, through the PLATFORM's model                 -> ACCEPTED (domain -> None)

Two consequences.

**A version string is not a statement about the bytes installed.** Two pods satisfy
`iagent-mesh==0.9.5` with different code, so "we are on 0.9.5, therefore field X
exists" is unsound in both directions. I nearly shipped that error myself: seeing the
8-field model I concluded the BFF was on 0.9.7, and its metadata says 0.9.5. Hash the
module and print `model_fields`; do not read the version.

**It is why the new seal parses the overlay with plain PyYAML rather than through the
SDK.** doc-tools physically cannot validate the overlay rows it is sealing against —
`domain:` raises at our pin. Please rule whether doc-tools' pin moves to the build the
BFF runs, or whether the two sides formally do not share this model. Until then no
in-repo check can round-trip an overlay row.

**This also corrects a note of mine** that said 0.9.7 requires a non-empty `domain`
and therefore cannot express your ruled `none`. In the model the platform actually
deploys, `domain` is **optional, default `None`** — so the ruling is representable in
the model. The place it is *not* representable is §4's branch, which is a different
layer and the one that needs you.

## 6. The delivery decision is spent, with one standing hazard

Lane 1's fix item 2 offered: register our kinds in the overlay, **or** rule that the
platform reads doc-tools' registry. `914c7fa` took the first. For the record, so
nobody revisits it as an improvement:

**Do not additionally point `CONTENT_KIND_OVERLAY_DIRS` at doc-tools' registry.** Per
the overlay README, *"A kind declared twice, anywhere on the path, is refused,"* and an
unreadable registry **fails closed**. With `pcn`/`pdn`/`s1000d-data-module` now in the
overlay, adding our registry to the path double-declares all three — which does not
merely fail to help, it takes `maintenance-fault-event` down with it. The one kind that
works on the fleet today is the casualty. The new seal encodes this: it refuses a kind
declared twice within a directory, naming the fail-closed consequence.

— doc-tools/lane/7f
