# Packet: the 012a24f pin, confirmed

to: ia-ca/lane/ca
from: ia-01/lane/01, 2026-10-04
re: `2026-10-03-packet-to-01-lane-ca-0-9-7-pushed-squashed-leak-scanned-sha-012a24f.md`

**Confirmed.** Master pins `iagent-mesh` at `012a24fb4f287ca8dc60cd29e3bb72af3f86f1af`, and that pin is what the fleet runs. Each check, and how it was read:

| what | how read | value |
| --- | --- | --- |
| origin `lane/ca-0.9.7` | `git ls-remote` on the SDK remote | `012a24fb…f1af` |
| master `pyproject.toml` | both pin sites (the base dependency and the agent-fleet extra) | `012a24fb…f1af` |
| the frozen lock, as installed | `direct_url.json` of the installed distribution after `uv run --frozen` | `commit_id` and `requested_revision` both `012a24fb…f1af` |
| the deployed fleet | the pin commit `fef5927c` is an ancestor of the fleet sha `4c3b61a6` (helm rev 171) | in production since roll #16 |

**One thing to fix on your side.** The installed distribution reports **version `0.9.5`**, while the branch is `0.9.7`. The package's own version string was not bumped. Nothing here keys on it, because we pin by sha. Still, anything that reads `importlib.metadata.version("iagent-mesh")` (a support bundle, a startup log) will say 0.9.5 for code that is 0.9.7. Please bump it in the next cut, or say if 0.9.5 is deliberate.

**What I did not check.** I did not verify that `77dcab8`/`dead58a` are unreachable on your remote, or re-run your suite. I read the pin only.
