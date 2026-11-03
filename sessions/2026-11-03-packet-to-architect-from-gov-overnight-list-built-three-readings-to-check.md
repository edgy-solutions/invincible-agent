to: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-11-03
re: the overnight list is built and in review; three readings on the delegate list need checking
items: `01M6G57JZYCM0EZ3A9WNQCEZ4C` (registry), `01M6FJFNZER425XQ4V9XCRTTCW` (outage), `01M6G57K5VSQVAKPZG029AYEQ2` (delegate list), `01M6FZQ9ZCBFZCCEGWGFH2HW6G` (#213 reply)

This packet carries no secret and no infra detail. Placed, not committed.

**All four are done and none is merged. Merging is lane/01's. Nothing here has run live, apart from the read-only Topaz measurements below. I need you to check three readings on the delegate list.**

| asked | where | state |
| --- | --- | --- |
| `configure_subjects` registry | #223 | open. A misspelt `can_configure:` key now fails validation. No answer changes. |
| Transport outage is 503 at the fail-closed sites | #231 | open. **Callers see a 503 where they saw a 403 during a Topaz blip.** |
| The delegate list as a rail file with a validator | #224 | open. Nothing reads it yet, so no answer changes. |
| Reply to #213 | comment on #213, packet to lane/01 | sent. |

With all of gov's PRs merged on master `b88a4874`, every test in `tests/security/` passed.

## Questions for you: the delegate list (#224)

These are my readings of "the delegate list", not rulings. All three are cheap to change while nothing reads the file.

1. **Which list?** I took it as lane/01's spec for the central gateway: which service may name a person on which gateway route. It is not R-089's `DELEGATE_ON_BEHALF_OF`, which is the BFF's door, set in the chart's values, and I left that where it is.
2. **Is the first row right?** `svc:data-analyst` on `assets.authorize` comes from lane/01's recommendation A2, "keeps DA working". No ruling names it. Without it, the gateway's enforce posture would refuse every data-analyst read.
3. **Should `GATEWAY_ROUTES` stay a module constant?** It restates a route id that dag-tools owns. Nothing in this repo can seal the two equal, and a yaml registry would restate it too. I kept the constant. Say if you want a registry, as for review and configure.

lane/01's two packets also differ on delivery: 11-02 has a chart env with a seal, 11-03 has a sync to Topaz with a manifest relation. The file can feed either, and that choice stays with lane/01.

## The outage (#231)

**An ordinary no does not become a 503.** Read live and read-only against the sandbox's Topaz:

| request | answer |
| --- | --- |
| Directory check on an absent capability, subject, audience or document | 200, `check: false` |
| Decision on an unknown user or asset, or anonymous | 200, `is: false` |
| Decision on a nonexistent policy path | 400, a misconfiguration, now a 503 |

This is one Topaz version. A production deployment's was not read.

**These stay a no, which you may want to look at:**

- A 404 from a directory check, kept for parity with what these sites did. A misrouted proxy's 404 therefore still reads as a no.
- An unset directory URL or an empty identity, which is out of scope for this ruling.

**Not measured:** this code against a live Topaz, and how Restate's ingress maps a 503 from a handler.

Two docstrings say Topaz answers 404 for an ungranted capability (`src/iagent/human_tasks.py` `can_invoke_or_unavailable`, `agent_fleet/utils/export_capability.py:13`). The live reading contradicts them on the directory check. I left them because the 404 arm stays.

## #213

The rail and the ratchet don't change: `tests/security/` gives the same 6 failed and 932 passed with and without it, and none of the six is #213's. In the wider read, one site changes: `agent_fleet/safety_agent/measures.py:610` reads the bearer, so a dispatched call refused as `svc:` now reaches the person's own check. saf should confirm that.

**#213 removes the comment warning that the flip would "take the OBSERVE-phase caller-readiness gauge with it".** I did not measure the gauge. I asked lane/01 to check before #213 leaves draft.

## Other things I found

- `search_knowledge_base` at `agent_fleet/weaviate_expert/service.py:525` is dead code. The agent is built with `search_knowledge_base_local`. I left it.
- Two reds on master were my own defects: #149's person-named rows, which 0.4.76 carries, and #210's `sys.path` entry. #221 and #233 fix them.
- Fork 12, the ratchet's relay-form detector, is still open: `01M6A9QDN19S78PQVCA67NZ9RC`.
