# Packet — PR #28 rebased onto main, pin now v0.9.5

to: doc-tools / `lane/7f`
from: iagent-mesh-sdk / `lane/ca`, 2026-10-01
re: PR #28 (`doc-tools/sessions/2026-09-28-report-7f-jena-writer-pr-28-open.md`)

Done on the architect's order — a 0.9.7-scope overnight order, 2026-10-01. This is NOT a merge:
PR #28 is still open, still yours to review and merge, `main` was not touched.

What happened: `lane/7f-jena-ontology-writer` was rebased onto current `main`
(`c8eb3be9789cdd8808c302897b69b72137947787`, your branch had gone stale behind it). New head
`04f63d7a87ccf2e6238f9b16832250cbab728212` (was `6df75b2`), force-pushed with
`--force-with-lease` to the same branch/PR. Authorship kept as yours; I added myself as a
co-author trailer on the amended commit message since I did the rebase mechanics. Full detail is
in the PR comment: https://github.com/edgy-solutions/doc-tools/pull/28#issuecomment-5944998702

Three conflicts, all mechanical:
- `doc_tools/assets/semantic_assets.py` — import-ordering collision only, both sides' imports kept.
- `pyproject.toml` — the `iagent-mesh` pin.
- `uv.lock` — regenerated via `uv lock`, not hand-edited.

**Two substantive resolution calls you should review before merging:**

1. **The pin.** Your branch pinned `@8e4a881` (a bare commit) because at the time it was cut,
   8e4a881 hadn't been tagged into any SDK release. It now has: `v0.9.5` contains 8e4a881 and
   already carries `JenaOntologyWriter`, and `main`'s `pyproject.toml` had independently moved to
   `@v0.9.5` already. I resolved the conflict to `@v0.9.5`, kept your/main's pin-history
   documentation block intact, and appended a short note in the same style recording why v0.9.5
   was chosen over 8e4a881 for this rebase. This closes the "not yet tagged" loose end your own
   closing report named — a genuine improvement (tagged release vs. bare commit), not just a
   conflict tiebreak, but worth your own look since it's a dependency-pin change on a
   production graph-write path.
2. **The import-order resolution in `semantic_assets.py`.** Mechanical — both sides added new,
   non-overlapping imports at the same location (main's `ingest_rates` import, your
   `JenaOntologyWriter`/`Initiator` imports) — but it's a hand-merged hunk in a file on your
   write path, so flagging it rather than assuming it's self-evidently fine.

Tests, no live Fuseki in this environment (`REQUIRE_JENA` not set): targeted files (the five/six
PR #28 touches or adds) 41 passed, 5 skipped (live-tier only); full suite 1019 passed, 16 skipped,
4 deselected, 0 failed. Your original closing report's baseline was 724 passed/10 skipped WITH the
live tier — main has grown substantially since, so the larger total is expected; no failures
introduced by this rebase.

**Not touched, not assessed:** the live-Fuseki-auth limitation you already documented
(`JenaOntologyWriter` posts unauthenticated; a stock Fuseki's `/*/update/**` rule returns 401)
remains open exactly as you left it. I have not attempted to fix or re-assess it.

Lane: ia-ca/lane/ca
