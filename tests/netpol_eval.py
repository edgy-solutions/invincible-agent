"""A dry-run NetworkPolicy evaluator over `helm template` output (helper module, no tests).

It implements the Kubernetes NetworkPolicy semantics that matter for flows between the pods of
ONE release namespace plus kube-system, so a rendered gate can be EVALUATED rather than read:

  * a pod's egress is restricted iff some policy whose podSelector selects it lists Egress in
    policyTypes; it is then allowed iff some egress rule of some such policy matches the
    destination (peer AND ports; an absent/empty `to` or `ports` means all). Ingress likewise
    on the destination pod. A flow is allowed iff BOTH sides allow it.
  * policy ports are matched against the DESTINATION POD's port: the Service's targetPort,
    resolved (numeric, or named -> the containerPort of that name), never the Service port.
  * a host that is not a Service in the render is OFF-CLUSTER: it is allowed only by an egress
    ipBlock that contains the IP the caller assigned to that host (`external_hosts`).
  * a pod may always reach itself.

NOT modelled: CNI enforcement quirks, port-forward / hostNetwork / node-local paths, hook-Job
pods (the Jobs are not workloads here), policies in other namespaces, SCTP, `endPort` ranges on
named ports. See docs/measurements/2026-10-10-the-gate-keeps-cortex-bff-and-engine-o.md.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

NS_LABEL = "kubernetes.io/metadata.name"
_WORKLOADS = ("Deployment", "StatefulSet")
# default port by URL scheme (a driver suffix such as postgresql+asyncpg is stripped first)
SCHEME_PORTS = {
    "http": 80, "https": 443, "bolt": 7687, "neo4j": 7687, "bolt+s": 7687, "neo4j+s": 7687,
    "redis": 6379, "rediss": 6379, "postgres": 5432, "postgresql": 5432, "grpc": 443,
}
_HOSTPORT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9.-]*):(\d{1,5})$")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_VARREF = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")


@dataclass
class Pod:
    """A pod template as the policies see it (one per Deployment/StatefulSet, or synthetic)."""
    name: str
    namespace: str
    labels: dict
    ports: list = field(default_factory=list)  # [(name|None, number, protocol)]


@dataclass
class Flow:
    src: str
    host: str
    port: int
    key: str = ""        # the env key the flow was derived from ("" for implicit flows)
    proto: str = "TCP"


@dataclass
class Verdict:
    allowed: bool
    reason: str


def _match_selector(sel: dict | None, labels: dict) -> bool:
    if sel is None:
        return False
    for k, v in (sel.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for e in sel.get("matchExpressions") or []:
        key, op, vals = e["key"], e["operator"], e.get("values") or []
        if op == "In" and labels.get(key) not in vals:
            return False
        if op == "NotIn" and key in labels and labels[key] in vals:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True


class Cluster:
    def __init__(self, docs: list[dict], namespace: str = "default",
                 external_hosts: dict[str, str] | None = None):
        self.ns = namespace
        self.external_hosts = dict(external_hosts or {})
        self.docs = docs
        self.policies = [d for d in docs if d.get("kind") == "NetworkPolicy"]
        self.services = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "Service"}
        self.config = {(d["kind"], d["metadata"]["name"]): d for d in docs
                       if d.get("kind") in ("ConfigMap", "Secret")}
        self.pods: list[Pod] = []
        self.workload_docs: dict[str, dict] = {}
        for d in docs:
            if d.get("kind") in _WORKLOADS:
                tpl = d["spec"]["template"]
                ports = []
                for c in tpl["spec"].get("containers", []):
                    for p in c.get("ports") or []:
                        ports.append((p.get("name"), int(p["containerPort"]), p.get("protocol", "TCP")))
                pod = Pod(d["metadata"]["name"], namespace, dict(tpl["metadata"].get("labels") or {}), ports)
                self.pods.append(pod)
                self.workload_docs[pod.name] = d
        # kube-dns lives in kube-system and is not part of the render
        self.dns = Pod("kube-dns", "kube-system", {"k8s-app": "kube-dns"}, [(None, 53, "UDP"), (None, 53, "TCP")])
        self.ns_labels = {namespace: {NS_LABEL: namespace}, "kube-system": {NS_LABEL: "kube-system"}}

    # ---- lookup -------------------------------------------------------------------------
    def pod(self, name: str) -> Pod:
        return next(p for p in self.pods if p.name == name)

    def pod_by_component(self, component: str) -> Pod:
        return next(p for p in self.pods if p.labels.get("app.kubernetes.io/component") == component)

    def service_for_host(self, host: str) -> dict | None:
        """Short name, `name.ns`, `name.ns.svc` or the FQDN; a different namespace is not ours."""
        parts = host.split(".")
        if len(parts) == 1:
            return self.services.get(parts[0])
        if parts[1] != self.ns:
            return None
        rest = ".".join(parts[2:])
        if rest in ("", "svc", "svc.cluster.local"):
            return self.services.get(parts[0])
        return None

    def backends(self, svc: dict) -> list[Pod]:
        sel = svc["spec"].get("selector") or {}
        return [p for p in self.pods if sel and all(p.labels.get(k) == v for k, v in sel.items())]

    def resolve_target_port(self, svc: dict, port: int, backends: list[Pod]) -> int | None:
        """Service port -> the destination pod's port (the number a policy is matched on)."""
        for sp in svc["spec"]["ports"]:
            if int(sp["port"]) != port:
                continue
            tp = sp.get("targetPort", sp["port"])
            if isinstance(tp, int) or str(tp).isdigit():
                return int(tp)
            for b in backends:
                for name, num, _ in b.ports:
                    if name == tp:
                        return num
            return None
        return None

    # ---- policy semantics ---------------------------------------------------------------
    def _selecting(self, pod: Pod, direction: str) -> list[dict]:
        out = []
        for pol in self.policies:
            ns = pol["metadata"].get("namespace", self.ns)
            if ns != pod.namespace or direction not in (pol["spec"].get("policyTypes") or []):
                continue
            if _match_selector(pol["spec"].get("podSelector") or {}, pod.labels):
                out.append(pol)
        return out

    def _peer_matches(self, peer: dict, pol_ns: str, other: Pod | None, other_ip: str | None) -> bool:
        if "ipBlock" in peer:
            if other_ip is None:
                return False  # ipBlock never matches a pod here (pod IPs are not modelled)
            blk = peer["ipBlock"]
            ip = ipaddress.ip_address(other_ip)
            if ip not in ipaddress.ip_network(blk["cidr"]):
                return False
            return not any(ip in ipaddress.ip_network(x) for x in blk.get("except") or [])
        if other is None:
            return False
        ns_sel, pod_sel = peer.get("namespaceSelector"), peer.get("podSelector")
        if ns_sel is not None:
            if not _match_selector(ns_sel, self.ns_labels.get(other.namespace, {})):
                return False
        elif other.namespace != pol_ns:
            return False
        if pod_sel is not None and not _match_selector(pod_sel, other.labels):
            return False
        return True

    @staticmethod
    def _ports_match(ports: list | None, number: int, proto: str, dest: Pod | None) -> bool:
        if not ports:
            return True
        for p in ports:
            if p.get("protocol", "TCP") != proto:
                continue
            want = p.get("port")
            if want is None:
                return True
            if isinstance(want, str) and not want.isdigit():
                if dest is not None and any(n == want and num == number and pr == proto for n, num, pr in dest.ports):
                    return True
                continue
            lo, hi = int(want), int(p.get("endPort", want))
            if lo <= number <= hi:
                return True
        return False

    def _allows(self, direction: str, pod: Pod, other: Pod | None, other_ip: str | None,
                number: int, proto: str, dest: Pod | None) -> tuple[bool, str]:
        pols = self._selecting(pod, direction)
        if not pols:
            return True, f"{pod.name} has no {direction.lower()} policy"
        key = "egress" if direction == "Egress" else "ingress"
        peerkey = "to" if direction == "Egress" else "from"
        for pol in pols:
            pol_ns = pol["metadata"].get("namespace", self.ns)
            for rule in pol["spec"].get(key) or []:
                peers = rule.get(peerkey)
                if peers and not any(self._peer_matches(p, pol_ns, other, other_ip) for p in peers):
                    continue
                if not self._ports_match(rule.get("ports"), number, proto, dest):
                    continue
                return True, f"{pol['metadata']['name']} admits"
        return False, f"{direction.lower()} of {pod.name} denies ({', '.join(p['metadata']['name'] for p in pols)})"

    # ---- flows --------------------------------------------------------------------------
    def evaluate(self, flow: Flow) -> Verdict:
        src = self.pod(flow.src)
        if flow.host in ("kube-dns", "__dns__"):
            dst, number, ip = self.dns, flow.port, None
            backends = [dst]
        else:
            svc = self.service_for_host(flow.host)
            if svc is None:
                ip = self.external_hosts.get(flow.host)
                if ip is None:
                    try:
                        ip = str(ipaddress.ip_address(flow.host))  # an IP literal is its own address
                    except ValueError:
                        if self._selecting(src, "Egress"):
                            return Verdict(False, f"{flow.host} is off-cluster and has no test IP")
                ok, why = self._allows("Egress", src, None, ip, flow.port, flow.proto, None)
                return Verdict(ok, f"off-cluster {flow.host}: {why}")
            backends = self.backends(svc)
            if not backends:
                return Verdict(False, f"service {svc['metadata']['name']} selects no workload")
            number = self.resolve_target_port(svc, flow.port, backends)
            if number is None:
                return Verdict(False, f"service {svc['metadata']['name']} has no port {flow.port}")
        for dst in backends:
            if dst is src:
                continue  # a pod may always reach itself
            ok, why = self._allows("Egress", src, dst, None, number, flow.proto, dst)
            if not ok:
                return Verdict(False, why)
            ok, why = self._allows("Ingress", dst, src, None, number, flow.proto, dst)
            if not ok:
                return Verdict(False, why)
        return Verdict(True, "both sides allow")

    # ---- flow derivation ----------------------------------------------------------------
    def env_of(self, workload: str) -> dict[str, str]:
        """Every env value a container of the workload carries: envFrom + env (+ valueFrom refs)."""
        d = self.workload_docs[workload]
        env: dict[str, str] = {}
        for c in d["spec"]["template"]["spec"].get("containers", []):
            for ef in c.get("envFrom") or []:
                ref = ef.get("configMapRef") or ef.get("secretRef")
                kind = "ConfigMap" if "configMapRef" in ef else "Secret"
                obj = self.config.get((kind, ref["name"]))
                if obj:
                    env.update({k: str(v) for k, v in (obj.get("data") or obj.get("stringData") or {}).items()})
            for e in c.get("env") or []:
                if "value" in e:
                    env[e["name"]] = str(e["value"])
                    continue
                vf = e.get("valueFrom") or {}
                for kind, kk in (("ConfigMap", "configMapKeyRef"), ("Secret", "secretKeyRef")):
                    if kk in vf:
                        obj = self.config.get((kind, vf[kk]["name"]))
                        val = ((obj or {}).get("data") or (obj or {}).get("stringData") or {}).get(vf[kk]["key"])
                        if val is not None:
                            env[e["name"]] = str(val)
        for _ in range(3):  # expand $(VAR) references
            for k, v in list(env.items()):
                env[k] = _VARREF.sub(lambda m: env.get(m.group(1), m.group(0)), v)
        return env


def parse_destination(value: str) -> tuple[str, int] | None:
    """(host, port) if the value is a URL or a bare host:port, else None. Raises on a URL it
    cannot place (unknown scheme with no port, unresolved $(VAR)), so nothing is skipped quietly."""
    value = value.strip()
    m = _SCHEME.match(value)
    if m:
        scheme = m.group(1).lower().split("+")[0]
        u = urlparse(re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "http://", value, count=1))
        host = u.hostname
        if host is None or "$(" in value:
            raise ValueError(f"unplaceable URL (unresolved reference or no host): {value[:40]}")
        if u.port is not None:
            return host, u.port
        if scheme not in SCHEME_PORTS:
            raise ValueError(f"URL with unknown scheme and no port: {scheme}")
        return host, SCHEME_PORTS[scheme]
    m = _HOSTPORT.match(value)
    if m and not re.fullmatch(r"\d+", m.group(1)):
        return m.group(1), int(m.group(2))
    return None


def derive_flows(cluster: Cluster, workload: str) -> list[Flow]:
    """Every (key, host, port) the workload's env points at, plus the implicit kube-dns flows.
    A bare `<X>_HOST` value with a sibling `<X>_PORT` is read as one destination."""
    env = cluster.env_of(workload)
    out: list[Flow] = []
    for k, v in sorted(env.items()):
        dest = parse_destination(v)
        if dest is None and k.endswith("_HOST") and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", v) \
                and re.fullmatch(r"\d{1,5}", env.get(k[:-5] + "_PORT", "")):
            dest = (v, int(env[k[:-5] + "_PORT"]))
        if dest is None:
            continue
        out.append(Flow(workload, dest[0], dest[1], key=k))
    out.append(Flow(workload, "kube-dns", 53, key="", proto="UDP"))
    out.append(Flow(workload, "kube-dns", 53, key="", proto="TCP"))
    return out
