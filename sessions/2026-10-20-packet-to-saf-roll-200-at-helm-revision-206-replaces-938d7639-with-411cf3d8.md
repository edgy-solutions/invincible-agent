to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-20
relay: Chris

Placed, not committed. This packet carries no secret.

# Roll 200 (helm revision 206) replaces 938d7639 with 411cf3d8 on every iagent image

This corrects one line of my earlier packet today, "938d7639 at helm revision 204 IS roll 199". It said every iagent image stays at `938d7639` through revision 205. That was true when I wrote it, and it is no longer true.

| what | value |
| --- | --- |
| helm revision 206 | deployed 2026-10-20 at 20:2xZ. This is **roll 200**. |
| the image on every iagent container | `411cf3d80effd505ce34696cf2b806d19811db34`. No `938d7639` is left. |
| what changed in the code | 10 commits, `938d7639..411cf3d8` on lane/01-197. The last of them, `411cf3d8`, is not yet on master. Code changes: `988e70c7`, a rejected row's evidence follows it into quarantine and the door's sniff binds; `46e54949`, lane 74's Q7(a) resolver half in engine-o (`input_declared.py`, `main.py`); `f07ac60d`, the Q9 menu no-op canonicalises both keys; `411cf3d8`, a `promoted` document_promotion act applies row_edits and reconciles the notice's SUBJECT_TO edges to the reviewed set. The other commits are sessions, docs, a test seal, a merge and the cortex pin. |
| cortex-ui | unchanged from 199b (`7a7666d`). |

If your arms were measured against 199, they ran on `938d7639`. Anything you measure from now on runs on `411cf3d8`.
