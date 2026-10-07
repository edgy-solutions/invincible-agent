# Probes — the small tools that settled design questions

Recovered from a session scratchpad 2026-08-10. They were written, used to decide something,
and left in session temp — which meant they were **lost by construction**.

> **A tool that lives only in a scratchpad is lost by construction.** Session temp is ephemeral
> and invisible to git, so *"I couldn't find it in any repo"* and *"it doesn't exist"* are
> different claims. Anything worth re-running belongs in the repo the first time it works.

That rule was earned twice over: `scripts/env_audit.py` was declared lost after a search of four
git repos — by an agent that had been writing files into the scratchpad it never thought to
look in. Absence from git proves *never committed*, never *doesn't exist*.

## Recovery discipline — allowlist, never directory

These were recovered **by name**, and each was **read for content** before being committed —
not scanned for it.

The distinction is the point. A grep for `SECRET|PASSWORD|TOKEN` matches on **key names**, and a
guard that matches on names validates naming, not content: a credential inside a
`DATABASE_URL`, a bearer hardcoded in a probe "just to test with", or an inline connection
string all pass such a scan cleanly. Every file here was checked for credential **shapes**
(`sk-`/`pk-` prefixes, `Bearer <token>`, long opaque literals, `scheme://user:pass@host`) and
confirmed to obtain credentials only via `os.environ[...]`.

Three scratchpad files were **verified to carry real credential values and deliberately left
behind**: `rendered_with_secrets.yaml`, `pod_env_raw.txt`, and the bulky live captures. A
`git add <dir>` would have committed them, and the standing rule is that recent leaks are
**history-rewritten, not forward-scrubbed** — expensive, and worse across a shared branch.
`rendered_with_secrets.yaml` announces itself in its filename; `pod_env_raw.txt` does not,
which makes it the more dangerous of the two. **Recover by allowlist; never by directory.**

## What each one is

| tool | question it settled |
|---|---|
| `probe_sameid.py` | Does Langfuse treat same-id ingestion as an upsert? Settled the boundary-emission design fork (ADR-0038). |
| `probe_ambient.py` | Does a **non-recording** ambient parent adopt children? The fact the replay-safe boundary rests on. |
| `probe_sdkingest.py` | Is `create_trace_id(seed=…)` deterministic across processes? The cross-service join. |
| `probe_readback.py` | Read a known trace back and count observations — the witness half of the above. |
| `count_spans.py` / `find_trace.py` | Count boundary spans / locate a trace. The replay-double instruments: **2 spans before the fix, 1 after.** |
| `fire_invocation.py` | Drive one Restate invocation, for manufacturing a replay on purpose. |
| `require_matrix.py` | The REQUIRE-posture matrix, run inside a throwaway pod: exempt `/health` → 200, gated route → 401 absent / 403 invalid, minted token admitted. |
| `cost_canvas_pages_open.py` | Does a canvas-composed cost page still verify and render in a real browser when sections are cut? Opens the full page and one page per section in headless Edge. 7/7 green on 2026-09-30, and it caught all five pages broken when one `HAS` guard was removed. |
| `engine_w_identity_census.py` | Does Engine W's per-chunk gate keep the same sources for the same identity whether `KNOWLEDGE_SEARCH_VIA_MESH` is off or on? Two halves: `run` inside the Engine W container once per flag value (piped on stdin to the image's python, flag set through `env`), then `diff off.json on.json` anywhere. Adds its own deny-identity and empty-caller controls, and reds on a census that shared no source or kept nothing. Written 2026-10-06 for after roll #20; sealed in `tests/test_engine_w_identity_census.py`. |

## Running them

All read credentials from the environment (`LANGFUSE_*`, `KEYCLOAK_REALM_URL`,
`SUPERVISOR_CLIENT_*`) and are intended to run **inside a pod** that already has them:

```bash
kubectl -n sandbox exec -i <pod> -- python - < scripts/probes/require_matrix.py
```

They are deliberately small and single-purpose. A probe that answers one question and prints
one discriminating result is the shape worth keeping; a probe whose output you have to
interpret is one that will be re-argued instead of re-run.
