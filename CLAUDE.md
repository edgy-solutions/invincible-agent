# invincible-agent — project memory

Survey date: 2026-09-20 (commit `319acec`, branch `master`).

## What this is

A content-level authorization layer for agentic systems: the gate sits between retrieval and
synthesis, so each engine filters retrieved rows / chunks / graph nodes / ontology classes
against the caller's grants **before** the model ever sees them (deny-by-default, explicit
per-asset grants). It ships as a fleet of ~20 FastAPI/Restate engines plus a Dagster
orchestration side and a Helm chart for the home-lab k3s sandbox.

## Repos and paths

| what | absolute path |
| --- | --- |
| this repo (master tree) | `C:\Users\cnogr\git\invincible-agent` |
| lane worktrees | `C:\Users\cnogr\git\ia-01` `ia-32` `ia-5f` `ia-74` `ia-91` `ia-eo` (branches `lane/NN`) |
| frontend (sibling repo) | `C:\Users\cnogr\git\cortex-ui` |
| handoff log (NOT in repo) | `C:\Users\cnogr\.claude\projects\c--Users-cnogr-git-invincible-agent\sessions\` — dated `YYYY-MM-DD-<slug>.md`, index + newest-first Log in its `README.md`. Read the newest 1–2 before starting; drop one when you finish substantive work. Deliberately outside git (carries home-lab IPs, kube contexts). |
| in-repo lane mail | `sessions/` — dated packets/dispatches *between lanes*, tracked and committed. Different channel from the handoff log above; don't confuse them. |
| auto-memory index | `C:\Users\cnogr\.claude\projects\c--Users-cnogr-git-invincible-agent\memory\MEMORY.md` |

## Map

- `agent_fleet/<engine>/` — one dir per engine (`ontology_service`, `cortex_bff`, `graph_host`,
  `cost_agent`, `finance_agent`, `safety_agent`, `presentation_agent`, `restate_analyst`,
  `neo4j_expert`, `weaviate_expert`, `data_analyst`, `planning_agent`, `docs_agent`,
  `swarms_scraper`, `langgraph_support`, `datahub_wrapper`, `mesh_registrar`, `core`, `utils`);
  each has its own `pyproject.toml` + `uv.lock` and usually a `main.py`.
- `src/iagent/` — orchestrator side: `gateway.py` (cortex-bff, 7.7k lines), `defs/` (Dagster),
  `authz/`, `projector/`.
- `tests/` — 484 tracked files; `routing/ cost/ finance/ safety/ graph_host/ identity/ security/
  eval/ docs/ planning/ sandbox_e2e/ fixtures/`.
- `docs/` — 380 files: `adr/ rulings/ plans/ measurements/ principles/ proposals/ runbooks/
  architecture/ reference/ corpus/`.
- `policy/` — ratified canvases/measures (the policy rail). `schemas/`, `sql/`, `helm/`, `setup/`.
- `scripts/` — operational scripts: `upgrade-sandbox.sh`, `roll-litany.sh`, census/probe/audit/
  generator scripts, `probes/`.
- `baml_shared/baml_client/` — **generated** BAML client. `package.json` exports the TS contracts.
- `AGENTS.md` — 2693-line fleet charter (lane conventions, rulings). Authoritative but huge.

## Run / test / build

```bash
uv sync                                    # root deps (orchestrator-side)
dg dev                                     # Dagster at http://localhost:3000
uvicorn agent_fleet.ontology_service.main:app --port 8084   # any engine, standalone
uv run pytest tests/                       # unit / contract, no cluster
uv run tests/sandbox_e2e/test_engine_w_knowledge.py         # e2e via cortex-bff + real JWT
scripts/upgrade-sandbox.sh                 # deploy the chart (bakes in every values file)
scripts/roll-litany.sh iagent-engine-w     # roll one service, six verification legs
```

Procfile: `web` = dagster webserver, `bff` = uvicorn on `src.iagent.gateway:app`.
Python is pinned `>=3.12,<3.13`; deps are uv-managed, never pip-installed ad hoc.

## Never read whole — context hazards

| never read | cheap inspection |
| --- | --- |
| `tests/fixtures/iads_40051_demo/40051E_5_0.fos` (1.2 MB) | `head -c 400`, `wc -l` |
| any `uv.lock` (18 of them, 200–430 KB each) | `grep -n 'name = "<pkg>"' -A2` |
| `src/iagent/gateway.py` (7772 lines) | `grep -n 'def \|@app\.' \| head`, then `sed -n` a range |
| `agent_fleet/ontology_service/main.py` (5139) | same |
| `agent_fleet/restate_analyst/main.py` (3701), `src/iagent/defs/dynamic_supervisor.py` (3610) | same |
| `AGENTS.md` (2693), `docs/rulings/README.md` (3459), `tests/routing/STATE_GATEWAY_V02.md` (2999) | `grep -n '^#\{1,3\} '` for the TOC, then `sed -n` |
| `baml_shared/baml_client/**` (generated, incl. `type_builder.py` 4363) | treat as build output; read the `.baml` sources instead |
| `dist/` (untracked: `*.duckdb`, generated validation `*.html`) | `ls -l dist`; never open the HTML |
| `assets/` (`*.jpg`, `*.svg`) | `ls`; never read |
| `cortex.db` (sqlite, untracked), `tmp/`, `agent_workspace/`, `**/__pycache__/`, `.venv*/` | `ls`, or sqlite metadata queries |
| the handoff log's session files | they are long-form narrative — read the newest 1–2 only, via the `README.md` Log lines first |

## Conventions and gotchas visible from the survey

- **Worktree ↔ branch, never a session name.** `ia-NN` ↔ `lane/NN`; lanes push to their branch,
  the architect merges. No lane's default view is `master`. A bare session name addresses nothing.
- **`master` is not currently green.** The measured failure census and its owner live in
  `docs/plans/suite-signal-session.md`. A green suite is not yet a valid gate.
- **Shared tree.** Other lanes land work in this same checkout; re-run any generator immediately
  before `git add`, and stage named paths only — a green belongs to a sha, not a directory.
- **Commit from a file**: `git commit -F <file>`, never `-m` with backticks (command substitution
  has silently deleted terms from messages here).
- **Never commit infra detail** (IPs, Pi-hole, kube contexts) — that is what the out-of-repo
  handoff log is for.
- `.gitignore` already covers `dist/`, `values-*.local.yaml`, `*.secret.yaml`, `list.md`,
  `docs/architecture/endpoint-gating-audit.md`, venvs and caches.
- MCP: none. `.mcp.json` (its only server was `forge_extension` at `localhost:50415`) was deleted
  by Chris on 2026-09-20; the deletion is unstaged in the working tree, for him to commit.
- Working-tree state at survey: 3 untracked `sessions/*.md` lane packets, plus that deletion.
