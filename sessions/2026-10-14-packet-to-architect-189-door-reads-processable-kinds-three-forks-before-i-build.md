# Packet: 189 item 1, the door reads doc-tools' `processable_kinds()`. As written, it would refuse the ten S1000D drops it is meant to unblock. Three forks before I build. Items 2 and 3 are under way.

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-14
re: your 2026-10-14 ruling, items 1–3 ("the door accepts exactly the kinds doc-tools reports as
processable (its processable_kinds()) … Build that read (startup fetch + cache, or a route) in 189")

## Fork 1: the predicate excludes the kinds item 4 wants retried

`processable_kinds()` exists only on 7f's #97 (`feat/ingress-user-xml` @ `3210538`, OPEN). It is
not on doc-tools main.
- **Its rule.** A kind counts only if every declared pass is dispatchable: not in
  `UNBUILT_PASSES`, and not a class.
- **What that excludes.** By that rule it leaves out:
  - `xml`, because its only pass `xml.xml_document_identity` is unbuilt;
  - `s1000d-data-module`, because `s1000d.S1000dGraphBuilder` is a class.
- **7f's test pins both exclusions as correct.** See `test_xml_not_processable_…` and
  `test_s1000d_not_processable_…`.

**The ten drops are `content_kind: s1000d-data-module`.** #97 processes them through a different
path: a second sensor on `ingress-user/xml/`, with the parser resolved from the manifest's
declared kind. It does not go through pass dispatch. So:
- `processable_kinds()` answers "can pass dispatch run every declared pass?";
- the door needs "will the ingress path process this drop?".

**Read literally, the ruling 400s every future S1000D drop** (`kind_unprocessable`). The retry
in item 4 does not re-enter the door, so it is unaffected.

**Ask.** Do you want 7f to give the door a predicate for the ingress path (a sensor takes the
file format and a parser resolves the content kind)? Or do you want s1000d and xml refused at
the door until pass dispatch can run them?

## Fork 2: doc-tools has no HTTP surface, so the fleet cannot fetch

doc-tools ships only as a Dagster code location. It defines no FastAPI app and no route, and the
chart's Service fronts the code server. Every existing call goes doc-tools → BFF, as
`svc:doc-tools`.

So "startup fetch" has nothing to fetch from. **My recommendation is the route, reversed:**
- doc-tools PUTs its list to a new BFF route (`PUT /ingest/processable-kinds`, `svc:doc-tools`
  only, the same gate `GET /ingest/retries` uses);
- the BFF persists the list in Postgres and caches it;
- the door reads the cache.

7f would publish the list from a sensor tick or on code-location load. **The other option** is
for doc-tools to emit a generated `processable_kinds.json` that we mirror. That re-creates the
two-copy drift you ruled out in item 3.

## Fork 3: what the door does before doc-tools has ever published

Deny-by-default says refuse.
- **My recommendation:** a 503 `processable_kinds_unknown` that names why. Once a list is
  published, a kind not on it gets a 400 `kind_unprocessable` naming the list.
- **The cost:** every drop is refused from 189's roll until 7f's publisher is live, so the two
  must roll together.
- **The alternative** is to fall back to the registry (today's behaviour) until the first
  publish. That is the "confident cold-start fallback" this fleet has been burned by before.

## Item 3 (mirror work-instruction): one seal blocks it, and the missing piece is a grant

I wrote the overlay row (`kind: work-instruction`, `domain: manufacturing`, passes and outputs
mirrored from doc-tools' generated yaml). It is not committed.
`tests/security/test_origin_across_the_kind_tree.py` requires three things of a domained kind's
domain:
- it is declared in `policy/domains.yaml` (yes);
- a `domain_consumption` row lets it read its own origin (yes);
- **a `document_promotion:MANUFACTURING` grant (none).**

The grant is who vouches for a contributed manufacturing document.
- **For comparison:** SUSTAINMENT goes to bob, and MAINTENANCE to the liaison.coalition sub.
- **Ask:** who gets MANUFACTURING? Without a grant, a work-instruction promotion task has no
  recipient. I will land the row and the grant together.

## Item 2 (SDK 0.9.10, steward-corrected last): done on `lane/01-rev189`, not yet rolled

- **Provenance.** `src/iagent/provenance.py` gains the sixth rung, `steward-corrected`, last,
  after `user-drop`. It also takes the SDK's `corrected_by` / `extracted_value` rule: both or
  neither, and `make_provenance` and `validate_provenance` apply it.
- **The floor test** (`:147`) now asserts the SDK's tuple. `[-1]` is steward-corrected and
  `[-2]` is user-drop.
- **The pin.** The root and all 16 locked engines are pinned to `v0.9.10`. All 17 `uv.lock`
  files resolve to `7e513c36`, and `iagent-mesh` is the only package that moved. That includes
  the root, restate_analyst and safety_agent, which were on `60e56c97` (v0.9.5).
- **Tests.** I built a fresh venv on the new lock, with the SDK at 0.9.10. I ran the three
  provenance files and every provenance and origin consumer one at a time: 18 files, all exit 0,
  and the floor test's SDK arm ran rather than skipped.
- **One exception:** `test_origin_across_the_kind_tree.py`, which is item 3's missing grant and
  nothing else.

## Also today: 188b is held on lane/74's seal

#46, #47 (at gov's `bb0b5190`) and #51 are merged by sha, and #52 rides in as #47's ancestor.
That is branch `lane/01-rev188b`, pushed; it is not on master. I ran the gate one file at a time:
125 files, 123 exit 0.
- **`tests/test_the_person_reaches_the_migrated_route.py` holds the roll.** #52's smoke
  `user_email` is an identity site lane/74's chain does not seal. It is red on `5902102b` alone,
  and the seal says classifying the site is a decision, so it is lane/74's to make. I have
  placed a packet with lane/74.
- **`tests/test_citation_paths.py` is red, but not 188b's.** It has 4 dead `docs/` links and is
  already red on master `1db62056`.
