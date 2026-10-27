to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-21
re: your item 1 ("the node is the story: which node, why NotReady, is it healthy now")
relay: Chris

This report carries no secret.

# The substrate node was hard-reset at about 19:44:50Z, mid-hook, and nobody reset it by hand. It is healthy now. Its disk did not die, and what reset it is still open

## Which node
It is worker6, the node with the Weaviate, Keycloak, MinIO and Restate volumes. Those four are pinned to its local disk, so nothing reschedules around it. It has failed four times before. Each time its host's NVMe dropped off the PCIe bus under I/O load, and the root filesystem went read-only.

## Why NotReady: a hard reset, not pressure, not kubelet, not disk
All of this was read from the cluster: node events, the node summary, the node's own `/var/log` through the API proxy, and a vectorizer access log that its pods call every 10 s.

| time (Z) | what |
| --- | --- |
| 19:27 | rev 210 upgrade begins. The node's pods go on serving at 6 requests a minute, every minute. |
| 19:42:48 | The node's syslog is still being written (a systemd timer). The disk is alive. |
| 19:44:39 | Helm reaches the post-upgrade hook and creates the seed pod. |
| 19:44:4x–5x | The node's last request. The 19:44 minute has 5 requests, and 19:45 has none. |
| 19:45:03, 19:45:21 | The two seed attempts start, after the node has already gone. Both time out connecting to Weaviate. |
| 19:45:29 | The node controller marks it NotReady. |
| 19:45:31 | The hook's backoff limit is reached, and rev 210 is marked failed. |
| 19:46:25 | The kernel boots, with a new boot id. |
| 19:46:34 | Kubelet starts, the node reports Ready, and the pods restart. |
| 19:47 onward | Steady at 6 requests a minute again. |

**What this rules out:**
- **Pressure:** there is no OOM, hung-task or lockup line in the kernel or system logs. The kubelet never reported memory, disk or PID pressure before it went.
- **The previous disk death:** the disk was being written until at least 19:42:48. The node served normally until about 19:44:50. Last time the signature was a read-only root and logs that stopped well before the network went.
- **A clean reboot:** syslog has no shutdown sequence before the new boot. The last lines are routine timers, and then the kernel's boot banner.
- **The seed hook as the cause:** its pods started after the node's last request.

**What the cluster cannot tell me: what reset it.**
- **It was not Chris.** He found it had gone down only when he checked its uptime at 20:38:50Z: up 52 minutes, so booted about 19:46:50Z, which agrees with the cluster.
- That leaves the hypervisor itself, or a host-level fault (power, the PCIe link, a watchdog) that the guest could not log.
- Three logs would answer it, and only Chris can read them: the guest's previous-boot journal, the host's kernel log, and the hypervisor's task log for that VM. I have asked him.
- Until then, **the cause is open.** It is not the earlier read-only-root signature, and it is not benign.

## Healthy now
Read at 20:30–20:40Z:
- Ready since 19:46:34Z, with all four pressure conditions False.
- 4.8 GB of about 33 GB memory in use.
- Root filesystem 65% used, 63 GB free.
- Serving at its normal rate since 19:47.
- Rev 211 rolled cleanly onto it: the seed hook passed and 33/33 deploys are green.
- Chris confirms the VM is up in the hypervisor and has a shell on it.

## Can it fall over Thursday
**Yes. Nothing that happened today makes that less likely.** The node is a single point holding four stateful services. Its host has a recorded hardware fault (a marginal M.2 seat), and the standing remedy, a reseat, has not been done. Today's reset is not yet explained.

What I propose for Thursday. Each item is yours or Chris's to accept:
1. **No roll during the dry run.** Freeze the chart at rev 211 from the evening before. A roll's hooks are what a node loss breaks first.
2. **A pre-run gate:** this node Ready, its pods' request rate normal for the last 10 minutes, and no rev newer than 211.
3. **If the host is to be touched (the M.2 reseat), do it before Wednesday night,** not on the day. A cold cycle costs three hosts that share a power rail.
4. **A dry-run abort rule:** if this node goes NotReady mid-run, the run stops. Keycloak and Weaviate go with it, so the run's evidence would read as a refusal, not an outage.

## The registrar restart, for the record
After the node came back, the mesh registrar answered health in about 30 s against a 5 s probe. Its Weaviate search hit a gRPC deadline, most likely over a channel opened before Weaviate restarted (unverified). One deployment restart recovered it. That restart was inside the roll window, as you ruled.
