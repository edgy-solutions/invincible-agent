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

`--expect` DEFAULTS TO THE TAG THE RELEASE WAS ROLLED WITH (`global.imageTag`, read from
helm), because the default question has to be the right one. `--expect HEAD` is the WRONG
question and was asked twice in one day: you roll, commit something else, and HEAD has moved
past the fleet — the census then reports 17 STALE services against a perfectly uniform fleet
and the reader spends minutes disproving their own instrument. Pass `--expect` to override.

FOUR EXIT CODES, BECAUSE A RUN-LEVEL CODE CANNOT CARRY A PER-CLAIM VERDICT. This census makes
TWO claims — every service is at the expected sha, and no service predates the last prime —
so one code would always be speaking for one of them:

    0  every claim checked, every claim passed
    1  a claim was checked and FAILED
    2  could not look at all (no deployments, unresolvable ref)
    3  checked what it could; at least one claim is UNCHECKED

UNCHECKED is not a failure and not a pass. Failing on a missing prime mark would fail a claim
that succeeded, so the unknown lives in the exit code's VOCABULARY rather than on the
pass/fail axis — the same distinction as returning None for "could not look" instead of False
for "the answer is no".

IT SHELLS OUT TO kubectl ON PURPOSE — no in-cluster client, no kubeconfig parsing, no new
dependency. It runs from a laptop against whatever context is current, which is where the
question actually gets asked.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import datetime as _dt
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


def _divergence(deployed: str, expected: str) -> str:
    """AHEAD or STALE — a sha that differs from the record is not automatically behind.

    ADDED 2026-09-11, after the census called the three NEWEST pods in the fleet STALE.
    Three engines had been rolled to master while the Helm release still recorded the
    previous tag, so they diverged from the record by being *in front of it*, and the label
    said the opposite of what was true.

    **A LABEL THAT CAN ONLY SAY "BEHIND" WILL SAY IT ABOUT EVERYTHING THAT DIFFERS**, and a
    reader acting on it would have rolled the fix backwards. The exit code is unchanged in
    either direction — divergence from the record is what this census exists to report, and
    being ahead of the record is still a lie in the record — but the OPERATOR needs to know
    which way, because the remedies are opposite.

    Ancestry from git, not string comparison: if the expected sha is an ancestor of what is
    deployed, the deployment is ahead. Unknown shas (a build from a branch nobody has, a
    shallow clone) report neither rather than guessing.
    """
    import subprocess
    if not deployed or not expected or deployed.startswith(expected[:12]):
        return ""
    def _known(sha: str) -> bool:
        return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                              capture_output=True).returncode == 0
    if not (_known(deployed) and _known(expected)):
        return "DIVERGED"          # both real, ancestry unknowable here
    anc = subprocess.run(["git", "merge-base", "--is-ancestor", expected, deployed],
                         capture_output=True).returncode == 0
    if anc:
        return "AHEAD"
    rev = subprocess.run(["git", "merge-base", "--is-ancestor", deployed, expected],
                         capture_output=True).returncode == 0
    return "STALE" if rev else "DIVERGED"


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


def _rolled_image_tag(namespace: str, release: str = "iagent") -> Optional[str]:
    """The sha this helm release was actually rolled with, from `global.imageTag`.

    The authoritative answer to "what is the fleet supposed to be running", and it lives in
    the cluster rather than in anyone's working tree — so it stays correct when HEAD moves
    after a roll, which is the case that produced a 17-service false STALE report.
    """
    rc, out = _kubectl_raw(["helm", "get", "values", release, "-n", namespace, "-o", "json"])
    if rc != 0 or not out.strip().startswith("{"):
        return None
    try:
        tag = (json.loads(out[out.index("{"):]).get("global") or {}).get("imageTag") or ""
    except Exception:  # noqa: BLE001
        return None
    tag = tag.strip()
    # A 40-hex sha is a pin; ':latest' or empty is not something to hold a fleet to.
    return tag if len(tag) == 40 and all(c in "0123456789abcdef" for c in tag) else None


def _kubectl_raw(argv: List[str]) -> Tuple[int, str]:
    """Run a command verbatim (helm, not kubectl) and return (rc, stdout)."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout
    except Exception:  # noqa: BLE001
        return 1, ""


def _prime_run_from_graph(namespace: str, bff_deploy: str = "iagent-cortex-bff"):
    """The newest `:PrimeRun` row — epoch seconds, or None.

    THE RECORD IS WRITTEN BY THE ACT. `setup/prime_databases.py` writes this row when it
    finishes, so it is evidence rather than a claim — the same principle as reading the rolled
    tag from `helm get values` instead of from a file somebody maintains.

    It replaces reading the hook Job's completionTime, which could not work: the Job is deleted
    by its hook-delete-policy and the Pod is reaped with it, so within the hour nothing in the
    cluster remembered that a prime had happened at all.

    Returns None — never 0, never "now" — when it cannot look. A wrong timestamp here marks
    every engine as fresh, which is the one answer that must not be guessed.
    """
    pod = _pod_for(namespace, bff_deploy)
    if not pod:
        return None
    snippet = (
        "import os,json,base64,urllib.request as u;"
        "usr=os.environ.get('NEO4J_USER') or os.environ.get('NEO4J_USERNAME') or 'neo4j';"
        "tok=base64.b64encode((usr+':'+os.environ.get('NEO4J_PASSWORD','')).encode()).decode();"
        "q={'statements':[{'statement':"
        "'MATCH (p:PrimeRun) RETURN max(p.completed_at_epoch) AS t'}]};"
        "r=u.Request('http://iagent-neo4j:7474/db/neo4j/tx/commit',"
        "data=json.dumps(q).encode(),"
        "headers={'Content-Type':'application/json','Authorization':'Basic '+tok});"
        "d=json.load(u.urlopen(r,timeout=20));"
        "print(json.dumps(d['results'][0]['data'][0]['row'][0] if d.get('results') "
        "and d['results'][0]['data'] else None))"
    )
    rc, out = _kubectl(["-n", namespace, "exec", pod, "--", "python", "-c", snippet], timeout=90)
    if rc != 0:
        return None
    try:
        val = json.loads(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return None
    return float(val) if isinstance(val, (int, float)) else None


def _last_prime_completion(namespace: str) -> Optional[float]:
    """Epoch seconds at which the most recent prime-substrate hook COMPLETED, or None.

    RULED 2026-09-11 — registration-forces-restart is an INVARIANT, not a side-effect of the
    weight-20 hook. An invariant that exists only because a hook happens to restart deployments
    is one hook edit away from not existing, and its absence has no symptom: every engine keeps
    reporting healthy while the router answers from the ontology it loaded before the prime.

    MEASURED 2026-09-10. engine-o did not restart across a prime and /resolve answered
    MaintenanceWorkOrderRecord at 0.78 with no planning class in the candidate pool, CONFIDENTLY,
    while the census reported every service current. After the restart: idp#Portfolio at 0.95.
    The census could not see the difference, because a sha is not a statement about WHEN the
    process started reading the substrate.
    """
    rc, out = _kubectl([
        "-n", namespace, "get", "job", "-l", "app.kubernetes.io/component=prime-substrate",
        "-o", "jsonpath={range .items[*]}{.status.completionTime}{\"\n\"}{end}",
    ], timeout=60)
    if rc != 0:
        return None
    best = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = _dt.datetime.strptime(line, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_dt.timezone.utc).timestamp()
        except ValueError:
            continue
        best = t if best is None else max(best, t)
    return best


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

    # ── THE DEFAULT QUESTION IS THE RIGHT ONE. RULED 2026-09-11 ────────────
    #
    # `--expect HEAD` is the wrong question and it was asked twice in one day. You roll, then
    # commit something else, and HEAD has moved past the sha the fleet is running — the census
    # correctly reports 17 STALE services against a fleet that is perfectly uniform, and the
    # reader spends minutes proving their own instrument wrong.
    #
    # THE CLUSTER ALREADY KNOWS WHAT WAS ROLLED. `helm get values` carries `global.imageTag`,
    # which is the sha helm actually deployed — authoritative, needs no state file to go stale,
    # and correct from any checkout at any commit. So that is the DEFAULT, and `--expect` is
    # the override for "hold the fleet to this instead".
    #
    # The alternative considered and rejected: the roll script writing its sha to a file. That
    # is a second source of truth about the same fact, which is the shape that drifts.
    expected = None
    if args.expect:
        expected = _git_sha(args.expect)
        if not expected:
            print(f"cannot resolve git ref {args.expect!r}", file=sys.stderr)
            return 2
    else:
        rolled = _rolled_image_tag(args.namespace)
        if rolled:
            expected = rolled
            args.expect = rolled
            print(f"(expecting {_short(rolled)} — the tag this release was rolled with; "
                  f"pass --expect to override)")

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
                     (report or {}).get("repo") or "invincible-agent",
                     (report or {}).get("uptime_s")))

    if not rows:
        print(f"no {OUR_PREFIX} deployments in namespace {args.namespace!r}")
        return 2

    w = max(len(r[0]) for r in rows)
    print(f"{'DEPLOYMENT':<{w}}  {'SPEC TAG':<14}  {'PROCESS SHA':<14}  {'SINCE PRIME':<12}  VERDICT")
    print("-" * (w + 64))

    # REGISTRATION RECENCY, BESIDE THE SHA. A sha says WHAT is running and nothing about
    # WHEN that process last read the substrate — different facts. An engine whose process
    # predates the last prime runs the right code against an ontology it has not re-read,
    # which is the engine-o defect: /resolve answered from the maintenance ontology at 0.78,
    # CONFIDENTLY, while a sha-only census reported every service current.
    # THE GRAPH FIRST, THE REAPED JOB AS A FALLBACK. The PrimeRun row is written BY the
    # prime when it finishes, so it survives the hook-delete-policy that removes the Job
    # and the Pod. The Job read stays only for clusters primed before that row existed —
    # it answers for about an hour and then cannot.
    _primed_at = _prime_run_from_graph(args.namespace)
    _prime_src = "PrimeRun row"
    if _primed_at is None:
        _primed_at = _last_prime_completion(args.namespace)
        _prime_src = "hook Job (legacy; reaped within the hour)"
    _now = _dt.datetime.now(_dt.timezone.utc).timestamp()
    if _primed_at is None:
        print("  (no prime-substrate completion found — registration recency NOT checked)")
    stale_reg: List[str] = []
    bad: List[str] = []
    for name, spec_tag, proc, repo, uptime in sorted(rows):
        # "-" IS HONEST ABSENCE, NOT A PASS. A service that reports no uptime cannot be
        # placed against the prime, and calling that fresh is the vacuous green this
        # column exists to prevent.
        # TWO DIFFERENT UNKNOWNS, TWO DIFFERENT MARKS. Collapsing them into one glyph
        # loses which instrument failed: `no-prime` means WE cannot place anything (no
        # prime timestamp exists), `no-uptime` means THIS service did not answer with one.
        # invincible-agent-91's rule, from a seal that returns None for "could not look"
        # and False for "the graph says no" — collapsing those is how a probe reports a
        # finding when it simply could not look.
        if _primed_at is None:
            reg = "no-prime"
        elif uptime is None:
            reg = "no-uptime"
        else:
            started = _now - float(uptime)
            reg = "restarted" if started >= _primed_at else "BEFORE PRIME"
            if reg == "BEFORE PRIME":
                stale_reg.append(name)
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
                verdict = "current" if ok else (
                    f"{_divergence(proc, expected) or 'STALE'} of record "
                    f"({_short(expected)})")
                if not ok:
                    bad.append(name)
            elif spec_tag not in ("latest", "?"):
                ok = expected.startswith(spec_tag[:12]) or spec_tag.startswith(expected[:12])
                verdict = "current (by tag)" if ok else (
                    f"{_divergence(spec_tag, expected) or 'STALE'} of record "
                    f"({_short(expected)}, by tag)")
                if not ok:
                    bad.append(name)
            else:
                # UNKNOWABLE IS NOT CURRENT. `:latest` with no stamp cannot be placed, and
                # reporting it as passing is how a census becomes decoration.
                verdict = "UNKNOWN (no stamp, unpinned tag)"
                bad.append(name)
        print(f"{name:<{w}}  {spec_tag:<14}  {_short(proc):<14}  {reg:<12}  {verdict}")

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

    # THREE OUTCOMES, BECAUSE THERE ARE THREE. invincible-agent-91's resolution, and the
    # reasoning is that a run-level exit code cannot carry a PER-CLAIM verdict. This census
    # makes TWO claims — every service is at the expected sha, and no service predates the last
    # prime — so one exit code means one of them is always being spoken for.
    #
    # FAILING ON A MISSING PRIME MARK WOULD FAIL A CLAIM THAT SUCCEEDED. The unknown belongs in
    # the exit code's VOCABULARY, not on the pass/fail axis — the same distinction as returning
    # None for "could not look" rather than False for "the answer is no", one level up.
    #
    #   0  every claim checked, every claim passed
    #   1  a claim was checked and FAILED
    #   2  could not look at all (no deployments, unresolvable ref)
    #   3  checked what it could; at least one claim is UNCHECKED
    if _primed_at is None:
        print("NOTE: exit 3 — sha checked; registration recency UNCHECKED (no prime-substrate "
              "completion found). The table is PARTIAL, and a reader taking 0 from it would be "
              "taking a pass on a claim nobody made.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
