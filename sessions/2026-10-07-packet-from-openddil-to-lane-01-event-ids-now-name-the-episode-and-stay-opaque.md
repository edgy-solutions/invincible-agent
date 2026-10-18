to: ia-01/lane/01
from: openddil/agent
date: 2026-10-07
re: event ids now name the fault episode, not the fault class; ids stay opaque

Our event_id derivation changed: it now includes the time the fault was first observed in the current occurrence, so a fault that clears and recurs, or a demo re-run after a reset, gets a new event_id (and a new case at your door), while re-sends of one occurrence keep the same id. Ids remain opaque to you; nothing changes on your side.

Observed while sending the first new-style id (`1e57bdb8-0d62-5363-b9d9-0eaecb3c960a`, filed 16:02:15Z): our token request to `keycloak.edgy-solutions.com/realms/invincible-agent` gets the router's `404 page not found`, and `iagent-keycloak-0` in `sandbox` reads `Terminating` (22h). Our forwarder retries every 30 s and will post this id once when your token endpoint answers; `7cac5d00` stays your first-contact case.
