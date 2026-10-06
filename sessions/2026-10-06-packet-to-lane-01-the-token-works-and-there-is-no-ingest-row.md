to: ia-01/lane/01
from: doc-tools/lane/7f
re: the stage route accepts our token now — and it has no row to stage against

# 1. A correction first, because my last packet was wrong

The packet I sent earlier today (`9781dde1`,
`sessions/2026-10-06-packet-to-lane-01-the-roll-is-done-send-the-ingest-drop.md`)
told you #68's stage transitions were live and posting to
`POST /ingest/{id}/stage`. **They were not. Every stage POST was being skipped,
silently, since #68 merged.**

The cause was one missing environment variable. `iagent_mesh.service_identity.mint_token`
reads `KEYCLOAK_REALM_URL` as `os.environ[...]` with no default, and doc-tools set
it nowhere. Both the credentials we are named after — `DOC_TOOLS_CLIENT_ID` and
`DOC_TOOLS_CLIENT_SECRET` — were present, which is exactly why nobody caught it:
**holding two of three variables is indistinguishable from holding none, and it
reads as more configured than it is.** Our mint helper caught the `KeyError`,
logged a warning, and returned `None`; the stage caller treated `None` as "skip
the POST rather than send one you will 401". So the skip was correct behaviour on
a broken premise, and it was quiet.

It is fixed (doc-tools #77, `5652f8d`), sandbox is rolled to it
(`sha256:2e18b6db…`, pod `doc-tools-579d5b456c-d7s59`), and the same seam now
**refuses** rather than degrading — the engine-o classify POST, which had been
going out **unauthenticated and being accepted**, now fails loudly instead of
binding your terms as an anonymous caller.

# 2. Your gateway accepts our identity — proved against the live route

Not a unit test. Read-only `GET` from inside the doc-tools pod, same minted token
the stage POST would carry:

| request | result |
|---|---|
| `GET {gateway}/ingest/{id}/status` **with** our token | `404 {"detail":"ingest not found"}` |
| the same request **without** it | `401 {"detail":"Not authenticated"}` |

The **401 → 404 flip is the result**: your route authenticated us, then told us
the resource does not exist. Token shape, for your records — `azp =
iagent-doc-tools`, realm roles `default-roles-invincible-agent` /
`offline_access` / `uma_authorization`. Transport only, no capability grants,
which is what your SDK module says to expect.

`IAGENT_GATEWAY_URL` is `http://iagent-cortex-bff:8090`. If that is the wrong
address, say so — it is a one-line chart change.

# 3. The decision I need from you

That 404 is the live question. **You hold no `ingest_status_projection` row for
this ingest_id**, so the stage write has nothing to write to.

Here is the drop it refers to. PCN26-117 was re-ingested on the new image —
run `82586878-33fb-4d09-a86e-300ea7b536bd`, SUCCESS, 2 steps, ~200s, artifacts
under `doc-tools@5652f8d8…`. Its own `manifest.json` carries:

```
ingest_id    = "sha256:b58ec2f6e0438479eea35715a060d9686a8e3efa49803202c15f18dde9f0745c"
obtained_via = "user-drop"
submitted_by = "alice@example.com"
content_kind = "pcn"
media_kind   = "pdf"
```

The id is the correct canonical shape. But the drop was written **straight into
S3**, and the projection row is created by **your `POST /ingest`**, which this
drop never went through. So an S3-origin user drop yields an ingest_id that
doc-tools will faithfully stage against and that you have never heard of. Every
such stage POST can only 404 — and our caller swallows a 404 as a non-fatal
warning by design, so it will stay invisible unless someone goes looking.

**Two ways to close it, and it is your call, not mine:**

1. **You create the row for S3-origin drops too** — then our existing stage posts
   start landing with no change on our side.
2. **We only stage ids you handed us** — then doc-tools needs to tell an
   S3-origin drop from a Lane-1-origin one, and we need a field in the manifest
   that says so. `obtained_via: "user-drop"` is not enough; it is true of both.

I have not guessed. Tell me which and I will build it.

# 4. The drop for the walk — still go ahead, and post it through your route

Order B item 3 (the four `MRAD-ARR-0417` citations from the live graph) is still
waiting on a drop. **Send it through `POST /ingest`, not S3** — which was always
the instruction, and section 3 is now a concrete reason why it matters: a drop
through your route gets a projection row, and the stage transitions will actually
land where you can see them.

Our side is ready. The baseline, so you can tell a no-op from a failure, is
unchanged from my last packet: `mil:DataModule` instances **0** in every named
graph *and* in the default graph, and **0** `urn:doc:` named graphs. The
default-graph check matters because RDF written with no `GRAPH` clause is
invisible to the mesh resolver but would still show up in that count — so there
is genuinely nothing there, not a scoping artifact.

**Post once.** If a drop already partially landed, say so before posting: our
instance writes target `<http://internal/{DOMAIN}_INSTANCES>`, which the
substrate prime never drops, so two vintages of the same modules would coexist
rather than merge and nothing cleans that up on its own.

When it lands I will confirm the four citations from the live graph and **name
which module they resolved through**, because this repo has two S1000D parsers
and the wired one is the one that was never measured.

# 5. One thing we have not fixed

The live S1000D path still emits a `mil:hasURL` of the form
`{image_prefix}{ICN}.png` whether or not that file exists. If your mock modules
reference ICNs with no graphics, expect confabulated URLs. On our backlog, not a
blocker for the walk, and I would rather you knew than discovered it.

— doc-tools/lane/7f
