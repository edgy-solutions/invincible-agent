# Overnight findings — 2026-06-27 → 2026-06-28

Started: 2026-06-27 22:30 CDT (approx)
Dispatched by: architect (Chris) for unsupervised overnight work.

## Governing discipline

- Halt-at-premise-shift still applies. When I would normally stop and ask:
  write the decision up as a note (choice / options / evidence /
  recommendation), append to this doc, move on. A queued decision for
  the morning is the correct outcome. A 3am autonomous pick is not.
- Every item has a self-verifiable done-check (probe / diff / `helm
  template` / refresh-and-look). If done-check is not green, leave it
  red with explanation. Do not force green.

## Items
- [ ] **1.** Pin projector image tag — chart defaults to `""` →
      AppVersion `0.1.1` (no such GHCR tag). Currently running on
      `kubectl set image ... :latest`; restart re-breaks the projector.
      Done-check: `helm template` resolves to a tag that exists on GHCR.
      Do NOT `helm upgrade` against sandbox.
- [ ] **2.** Decision A — artifact displays its own `question_text` from
      the projection, not from `useInterviewStore` (ephemeral messages).
      Done-check: refresh; each artifact shows its generating question
      sourced from the durable field.
- [ ] **3.** Gate `force_poll` behind env flag (default off). Red-first
      probe: assert endpoint returns disabled/404 when flag unset; works
      when set.
- [ ] **4.** `apply_once`/interval-loop concurrency: lock or
      pause-interval-during-forced-batch. Red-first probe: concurrent
      `apply_once` against running interval loop; assert no double-advance,
      no skipped window. The probe is the reviewer here.
- [ ] **5.** Unambiguous UI bugs (single-correct-behavior only). Skip
      judgment calls (leave as notes).
- [ ] **6.** CI / flake stabilization. Drive CI green; harden flakes.
- [ ] **7.** During-query diagnostic — RUN AND REPORT ONLY. Routed query
      that should return real sources (not `prov#*` fallback). Record
      fill-timing of ontology map / routing card / sources card. Write
      finding here with diagnosis (inconsistent-path /
      real-Electric-bug / honest-empty-misread) + recommendation. Do
      NOT implement any lag fix.

## Fenced — do not touch

- Option 2 (during-query SSE optimism) — diagnostic only (item 7)
- Message substrate / Hop 4 — its own session
- Enforcement / ADR-0025 access-control — sealed
- Gate 6 browser-visual close — architect-awake-only
- Shared-cluster restart or `helm upgrade` against sandbox
- prov#* / `[[resolve-phrasing-sensitivity]]` chasing

---

## Progress log

(entries appended below as items complete; commit hashes inline)

---
