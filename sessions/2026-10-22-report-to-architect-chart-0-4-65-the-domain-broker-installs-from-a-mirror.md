to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-22
re: Chris, after the 0.4.64 upgrade at work: the domain broker cannot reach github.com ("we can't go to internet - this is a close deployment"; "we do have an internal pypi"). Chris approved the merge and release
relay: Chris

Committed on lane/01-202. This report carries no secret and no infra detail.

# Master is `360fbeb6`, chart 0.4.65. The domain broker can now install from an internal PyPI. Work takes 0.4.65

**This supersedes the chart version in `9e6ca820` and `b8fd2a60`: work upgrades to 0.4.65.** The BFF image stays `67d6e9f6`. Since then, only `helm/`, `tests/` and `sessions/` have changed.

## What failed at work

- The domain broker runs on stock `python:3.12-slim` and pip-installs its dependencies every time it starts.
- The SDK's tarball URL was hard-coded to `github.com`, and the index was always PyPI. With no internet route, the pod retried github.com until its startup probe gave up.
- No values setting could change this, because the URL was a literal in the template. The lab has a route out, so the lab never sees it.

## The change (`360fbeb6`)

New `domainBroker` keys, modelled on `topazSeed.policySource.git`:

| key | effect |
| --- | --- |
| `meshSdkSource` | `url` (the default, the GitHub tag tarball as before) or `index`, which installs `iagent-mesh==<meshSdkVersion without the v>`. Any other value fails the render. |
| `meshSdkBaseUrl` | replaces the GitHub tags URL. The file name stays `<meshSdkVersion>.tar.gz`. |
| `pip.indexUrl` | becomes `PIP_INDEX_URL` |
| `pip.caSecretName` | a Secret with key `ca.crt`, mounted read-only and passed as `PIP_CERT` |

- **The version still has one source in both modes:** `meshSdkVersion`, which `test_lock_coherence` ties to the engines' pin.
- **There is no option to skip TLS verification**, because this install delivers the broker's transport-auth code.
- **The defaults render as before.** Against 0.4.64, the only differences are the version string and the `dagster-instance` checksum that follows it.
- **The test:** `tests/test_domain_broker_installs_from_a_mirror.py`.
  - Against the unfixed template, 4 of 7 arms failed. The 3 that passed are the controls: the default URL, the default env, and the no-skip-verify check.
  - With the index-mode arms added, 9 of 9 pass on the fix.
  - Neighbouring tests, run one file at a time, are green: `test_lock_coherence` (22), `test_chart_version_tracks_chart_content` (9) and `test_chart_renders_on_bare_defaults` (6).
- **The changelog** gains entries for 0.4.65, 0.4.64, and 0.4.62–0.4.63, which had none.

## For work, which Chris carries

- I built `iagent_mesh-0.9.10` (sdist and wheel) from tag `v0.9.10` of the SDK repo, for Chris to upload to the internal PyPI. The wheel contains `transport_auth`. Its hard dependencies must also be on that index:
  - `acryl-datahub`, `mcp`, `pyjwt`, `pyyaml`, `pydantic-settings`, `nest-asyncio`, `httpx`, `pydantic`;
  - plus the broker's own `fastapi` and `hypercorn`.
- Work's values: `domainBroker.meshSdkSource: index`, `domainBroker.pip.indexUrl: <work's index>`, and `pip.caSecretName` if the index has an internal CA.
- **Open:** if the index needs credentials, they would sit in `indexUrl` in plain text. I have asked Chris to say so first; the fix would be a Secret-backed key.

## Merge and release

- **Fast-forward** `d6fd6edf..360fbeb6` (2 commits: `b8fd2a60` and `360fbeb6`). I checked `is-ancestor` first, pushed the full sha, and did not force.
- **Build & Push Container Images on `360fbeb6`** (run 39864132902): success.
- **Release Helm Charts** (run 39864132825): succeeded. Release `invincible-agent-0.4.65` exists. Its push-time retag ran before the build finished and tagged 0 of 19, the same race as 0.4.63 and 0.4.64.
- **The retag re-run** (`workflow_dispatch`, chart 0.4.65, sha `360fbeb6`; run 39864944625): 19 of 19 tagged.
- **GHCR `cortex-bff`, read anonymously:** `0.4.65` and `360fbeb6…` both return 200 with `sha256:ce11932d…`. The negative control, `0.4.99`, returns 404.
- **The released chart itself:** the `.tgz` reads `version: 0.4.65`. Rendered with `meshSdkSource=index`, it installs `iagent-mesh==0.9.10`, sets `PIP_INDEX_URL`, and names no `github.com`.

## A pattern worth a ruling

This is the third release today whose push-time retag tagged nothing, because it ran while the build was still going. Each needed a hand dispatch. The release workflow could wait for the build of its sha. That is a workflow change, and I have not made it; whether to is yours.
