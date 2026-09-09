"""VERSION CENSUS — what commit is each service actually running?

WHY THIS EXISTS. On 2026-09-08, twice, "is the fix on the pod?" was answered by a person
squinting at pod age and then importing a symbol by hand. Pod age tells you nothing under
`:latest`: a pod started an hour ago may be running an image built a week ago, and a pod
started a week ago may have been running the newest image the whole time. Two rolls that day
were verified by `kubectl exec ... python -c "import ..."`, which works and is not a check
anyone will run for twelve services.

THE THREE READINGS, AND THEY ARE NOT THE SAME QUESTION:

    spec      what the Deployment ASKED for            `.spec...containers[].image`
    resolved  what the kubelet actually PULLED         `.status...imageID` (a digest)
    process   what the RUNNING CODE says it is         `IAGENT_GIT_SHA`, baked at build

Only the third can be trusted, and only because it is baked into the image at build time
rather than injected by the chart. A chart-injected tag is a claim about what was requested;
under `:latest` it is not even that. See the `ARG GIT_SHA` block in
`.github/workflows/build-containers.yml`.

A DISAGREEMENT BETWEEN THEM IS THE FINDING, not noise. Spec says a sha and the process
reports another: the pod did not restart, or an init container is serving. Spec says
`latest`: nothing is pinned and the resolved digest is the only identity there is.

USAGE

    uv run --frozen python scripts/version_census.py --namespace sandbox
    uv run --frozen python scripts/version_census.py --namespace sandbox --expect HEAD
    uv run --frozen python scripts/version_census.py -n d4-sandbox --expect origin/master

Exit code is 1 when `--expect` is given and any service disagrees with it, so this is
usable as a post-roll gate rather than something to read and interpret.

IT SHELLS OUT TO kubectl ON PURPOSE — no in-cluster client, no kubeconfig parsing, no new
dependency. It runs from a laptop against whatever context is current, which is where the
question actually gets asked.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

#: The env var the images stamp. Read from the RUNNING process, never from the pod spec.
SHA_ENV = "IAGENT_GIT_SHA"

#: Images built from this repo. A deployment whose image is not one of ours is skipped
#: rather than reported unknown — postgres and restate have their own versioning and
#: reporting them as "not current" would be noise that trains people to ignore the census.
OUR_PREFIX = "invincible-agent/"


def _kubectl(args: List[str], timeout: int = 120) -> Tuple[int, str]:
    proc = subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, timeout=timeout
    )
    return proc.returncode, (proc.stdout or proc.returncode and proc.stderr or "")


def _git_sha(ref: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "rev-parse", ref], capture_output=True, text=True
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _short(sha: str) -> str:
    return sha[:12] if sha and len(sha) > 12 else (sha or "")


def _deployments(namespace: str) -> List[Dict[str, Any]]:
    rc, out = _kubectl(["-n", namespace, "get", "deploy", "-o", "json"])
    if rc != 0:
        print(f"kubectl failed: {out.strip()[:400]}", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(out).get("items", [])


def _pod_for(namespace: str, deploy: str) -> Optional[str]:
    """The pod actually SERVING, resolved through endpoints where a Service exists.

    Not `deploy/<name>`, and not the newest pod: during a rollout both answer, and the one
    that answers a request is the one behind the Service. This is the same resolution used
    to verify two rolls by hand on 2026-09-08.
    """
    rc, out = _kubectl(
        ["-n", namespace, "get", "endpoints", deploy, "-o",
         "jsonpath={.subsets[0].addresses[0].targetRef.name}"]
    )
    if rc == 0 and out.strip():
        return out.strip()
    rc, out = _kubectl(
        ["-n", namespace, "get", "pods", "-l", f"app={deploy}", "-o",
         "jsonpath={.items[0].metadata.name}"]
    )
    return out.strip() or None


def _fleet_report(namespace: str, bff_deploy: str = "iagent-cortex-bff") -> Dict[str, dict]:
    """`component -> /version payload`, via the gateway's aggregator — ONE exec, not N.

    The gateway asks every service directly and returns the lot, so the fleet is read the
    way a person would read it if they could curl inside the cluster. Falls back to nothing
    (not to a lie) when the aggregator is absent, which is what an old BFF image looks like;
    the caller then drops to per-pod `printenv`.

    UNREACHABLE SERVICES COME BACK NAMED rather than missing — the aggregator does that on
    purpose, and dropping them here would undo it.
    """
    pod = _pod_for(namespace, bff_deploy)
    if not pod:
        return {}
    rc, out = _kubectl(
        ["-n", namespace, "exec", pod, "--", "python", "-c",
         "import json,urllib.request as u;"
         "print(json.dumps(json.load(u.urlopen('http://localhost:8090/fleet/version',"
         "timeout=20))))"],
        timeout=120,
    )
    if rc != 0 or not out.strip().startswith("{"):
        return {}
    try:
        doc = json.loads(out[out.index("{"):])
    except Exception:  # noqa: BLE001
        return {}
    report: Dict[str, dict] = dict(doc.get("services") or {})
    if doc.get("self"):
        report["cortex-bff"] = doc["self"]
    return report


def _process_sha(namespace: str, pod: str) -> Optional[str]:
    """Ask the RUNNING process, via its own environment.

    `printenv` rather than `kubectl get pod -o jsonpath` on the env block: the pod spec
    reports what was CONFIGURED, and the whole point of this column is to read what the
    process actually has. An image built before the stamp existed reports nothing, which is
    honest and is exactly what a stale pod looks like.
    """
    rc, out = _kubectl(["-n", namespace, "exec", pod, "--", "printenv", SHA_ENV], timeout=60)
    val = (out or "").strip()
    return val if rc == 0 and val and val != "unknown" else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--namespace", default="sandbox")
    ap.add_argument(
        "--expect",
        help="git ref every service must match (e.g. HEAD, origin/master, a sha). "
             "Exit 1 on any disagreement.",
    )
    ap.add_argument(
        "--repo", action="append", metavar="NAME=PATH",
        help="another repository a service reports itself from, e.g. "
             "cortex-ui=../cortex-ui. Its services are compared to THAT repo's head. "
             "A repo with no path given is reported but never judged — holding a "
             "separately-rolled frontend to this repo's sha would call a correct deploy "
             "stale.",
    )
    ap.add_argument(
        "--skip-exec", action="store_true",
        help="spec and resolved digest only — no exec into pods. Faster, and the honest "
             "choice where exec is not permitted; the process column reads 'n/a' rather "
             "than being silently omitted.",
    )
    args = ap.parse_args()

    expected = None
    if args.expect:
        expected = _git_sha(args.expect)
        if not expected:
            print(f"cannot resolve git ref {args.expect!r}", file=sys.stderr)
            return 2

    # ── ONE CALL FIRST ─────────────────────────────────────────────────────
    # Thirteen execs is a command nobody runs. The aggregator turns it into one, and the
    # per-pod path below stays as the fallback for a fleet whose BFF predates it.
    fleet = {} if args.skip_exec else _fleet_report(args.namespace)
    if fleet:
        print(f"(read {len(fleet)} service report(s) via the gateway aggregator)")

    # EACH SERVICE AGAINST ITS OWN REPO'S HEAD. The frontend is a separate repository with
    # its own roll; holding it to this repo's sha would report a correct deploy as stale.
    # A repo we were given no path for is reported, never judged.
    repo_head: Dict[str, Optional[str]] = {"invincible-agent": expected}
    for spec in (args.repo or []):
        if "=" not in spec:
            print(f"--repo needs name=path, got {spec!r}", file=sys.stderr)
            return 2
        rname, rpath = spec.split("=", 1)
        proc = subprocess.run(
            ["git", "-C", rpath, "rev-parse", args.expect or "HEAD"],
            capture_output=True, text=True,
        )
        repo_head[rname] = proc.stdout.strip() or None

    rows: List[Tuple[str, str, str, str]] = []
    for item in _deployments(args.namespace):
        name = item["metadata"]["name"]
        containers = item["spec"]["template"]["spec"]["containers"]
        image = containers[0].get("image", "")
        if OUR_PREFIX not in image:
            continue
        spec_tag = image.rsplit(":", 1)[-1] if ":" in image else "?"
        # AN EXACT JOIN, NOT A SUFFIX GUESS. The first live census showed six services with
        # no sha while every one of them was reporting correctly: the heuristic matched
        # `iagent-engine-a` to the key "a" by luck and failed to match `iagent-engine-o` to
        # "ontology" at all. Worse than the misses, a suffix rule can MATCH THE WRONG
        # SERVICE and report one pod's sha under another's name, which reads as a
        # successful census.
        #
        # The aggregator now keys by the component each service reports for ITSELF
        # (`engine-o`), and a deployment is `iagent-` plus that. Exact, and a service whose
        # name does not follow the convention is MISSED VISIBLY rather than mismatched.
        _key = name[len("iagent-"):] if name.startswith("iagent-") else name
        report = fleet.get(_key)
        proc = (report or {}).get("git_sha")
        # THE STATE, NOT JUST THE SHA. `no_endpoint` (not rolled yet), `unstamped` (rolled,
        # built before the stamp), `unreachable` (down) and `error` all arrive with a null
        # sha and have DIFFERENT REPAIRS. Reporting one dash for all four is the collapse
        # cortex-ui-60's header made the same night, on the same data.
        state = (report or {}).get("state") or ""
        pod = None
        if proc is None and not args.skip_exec and not fleet:
            pod = _pod_for(args.namespace, name)
            proc = _process_sha(args.namespace, pod) if pod else None
        _shown = proc or {
            "no_endpoint": "not-rolled",
            "unstamped": "unstamped",
            "unreachable": "DOWN",
            "error": "error",
        }.get(state, "n/a" if args.skip_exec else "-")
        rows.append((name, spec_tag, _shown,
                     (report or {}).get("repo") or "invincible-agent"))

    if not rows:
        print(f"no {OUR_PREFIX} deployments in namespace {args.namespace!r}")
        return 2

    w = max(len(r[0]) for r in rows)
    print(f"{'DEPLOYMENT':<{w}}  {'SPEC TAG':<14}  {'PROCESS SHA':<14}  VERDICT")
    print("-" * (w + 50))

    bad: List[str] = []
    for name, spec_tag, proc, repo in sorted(rows):
        verdict = ""
        want = repo_head.get(repo)
        if want is None and repo != "invincible-agent":
            # REPORTED, NOT JUDGED. Pass `--repo <name>=<path>` to hold it to a head.
            print(f"{name:<{w}}  {spec_tag:<14}  {_short(proc):<14}  "
                  f"(repo {repo}, no head given)")
            continue
        expected = want or expected
        if expected:
            # THE PROCESS IS AUTHORITATIVE. A matching spec tag with a stale process is
            # still stale — that is the case this census exists to catch.
            if proc not in ("-", "n/a"):
                ok = proc.startswith(expected[:12]) or expected.startswith(proc[:12])
                verdict = "current" if ok else f"STALE (wants {_short(expected)})"
                if not ok:
                    bad.append(name)
            elif spec_tag not in ("latest", "?"):
                ok = expected.startswith(spec_tag[:12]) or spec_tag.startswith(expected[:12])
                verdict = "current (by tag)" if ok else f"STALE (wants {_short(expected)})"
                if not ok:
                    bad.append(name)
            else:
                # UNKNOWABLE IS NOT CURRENT. `:latest` with no stamp cannot be placed, and
                # reporting it as passing is how a census becomes decoration.
                verdict = "UNKNOWN (no stamp, unpinned tag)"
                bad.append(name)
        print(f"{name:<{w}}  {spec_tag:<14}  {_short(proc):<14}  {verdict}")

    unpinned = [r[0] for r in rows if r[1] == "latest"]
    if unpinned:
        print(
            f"\n{len(unpinned)} of {len(rows)} on ':latest' — the spec tag identifies "
            f"nothing. Pin with `--set global.imageTag=$(git rev-parse HEAD)`."
        )
    if expected and bad:
        print(f"\nFAILED: {len(bad)} service(s) not at {args.expect} ({_short(expected)}): "
              f"{', '.join(sorted(bad))}")
        return 1
    if expected:
        print(f"\nOK: all {len(rows)} service(s) at {args.expect} ({_short(expected)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
