# The sync stream: a census of every table it can expose

Date: 2026-11-14. Lane: `invincible-agent/lane/saf`. Base: `origin/master` 2d27e27d, plus PR #395 at
5a25573e for path (a). Report only: nothing in this file changes behaviour.

Method: chart templates, values, `sql/` DDL and the Python that creates tables, read as files. No
cluster, no `kubectl`, no port-forward, no Secret, no `helm template` render. The table list is
derived from the database the chart provisions, not from the allow-list.

## Verdict

**The census PASSES with an empty UNDECIDED bucket, over 38 tables** (12 provisioned by this repo, 22 Dagster,
4 LangGraph), under one stated premise: path (c) counts every table the role can read as reachable, an
upper bound; whether the role owns a given Dagster table at runtime is a cluster fact this file-only
census cannot check (the evidence that would decide it: the table owner column of `pg_tables`). A first
version of this report left the Dagster and LangGraph classes UNDECIDED; they are now read from the
installed packages (section 3) and bucketed.

The finding that matters: **path (c) is open for every table.** The BFF allow-list at #395 closes
the browser path, but Electric itself runs unauthenticated, as a role that can read the whole
database, and nothing in the chart restricts who can open a connection to it.

## 1. The three paths

| path | what it is | check, file:line |
| --- | --- | --- |
| (a) `GET /electric/shape` at #395 | JWT-verified BFF proxy; refuses any table without an allow-list row; injects a per-table WHERE; client `where` dropped | allow-list: `src/iagent/gateway.py:18048` (`electric_shape(<table>)` policy refusal) and `:18078` (`electric_shape_filter(<table>)` final-else refusal), rows in `policy/electric_shapes.yaml`, loader `src/iagent/electric_shapes.py:55` (`allowed_row`), all on the #395 branch |
| (b) master's proxy | same proxy without the allow-list: a per-table WHERE for three tables, `produced_for_user_id = <sub>` for every other name | `src/iagent/gateway.py:18029` (table read, defaults to answers), `:18046` (tasks), `:18054` (ingest), `:18064` (everything else), `:18069` (server WHERE overrides client) |
| (c) in-cluster, no proxy | a pod opens the Electric Service directly | none, see section 3 |

Path (b) detail worth knowing. The `else` at `:18064` does not refuse an unknown table; it builds a
WHERE on `produced_for_user_id`. Only `answer_artifact_projection` has that column (added at
`sql/create_answer_artifact_projection.sql:94`), so for any other table Electric rejects the
WHERE as naming a missing column. That is a refusal by accident of the schema, not a seal: a
future table that gains a `produced_for_user_id` column would be streamed. Also, the branch
compares the table name by exact string, so a schema-qualified spelling of the answers table skips
the `archived_at IS NULL` clause at `:18066` (the caller still sees only their own rows).

## 2. Path (c): the reachability trace

- `helm/invincible-agent/values.yaml:1999` `electric.insecure: true`; the sandbox values do not
  override it. `templates/electric.yaml:119-120` passes it as `ELECTRIC_INSECURE`, which turns off
  Electric's API secret: any request that reaches the port is served, with any `table` and any
  `where`.
- `templates/electric.yaml` builds `DATABASE_URL` from the `BPMN_POSTGRES_*` values: the iagent
  application role, the whole main database. A `grant-replication` init container gives that role
  REPLICATION. `templates/jobs.yaml` (post-install hook) runs
  `GRANT SELECT ... ON ALL TABLES IN SCHEMA public` and `ALTER DEFAULT PRIVILEGES ... GRANT SELECT`
  to the same role, and transfers ownership of the four hook-created tables to it. Tables the
  application creates at startup are created by that role, so it owns them too. Electric can
  therefore publish and stream **any table in the public schema**, not only the two the UI uses.
- Exposure of the Service: `templates/electric.yaml:166` a ClusterIP Service on `electric.port`.
  `templates/ingress.yaml:130-167` renders an Electric Ingress only when `electric.ingress.enabled`;
  it is false in `values.yaml` and in `values-sandbox.yaml`. So nothing outside the cluster reaches
  it by chart configuration. Reachable from: every pod that can route to the Service.
- NetworkPolicy: the chart renders two templates, `networkpolicy-engines.yaml` (egress policies,
  one per enabled engine, selected by component label) and `networkpolicy-stores.yaml` (ingress
  policies for the seven stores in the `networkPolicyStores` define: postgresql, keycloak, weaviate,
  neo4j, restate, fuseki, topaz). Neither selects `component: electric`, and **neither contains a
  namespace-wide default-deny** (no empty `podSelector`; every selector is a component label).
  Both templates are gated on `networkPolicy.enabled`, which is `false` by default and unset in the
  sandbox values. So no policy covers Electric by label or otherwise: any pod in the namespace
  (and, under a permissive CNI, any pod in the cluster) can open `iagent-electric:<port>` today.
- A second-order effect of turning the gate on, read from the templates and not rendered: the
  postgresql ingress policy admits only the six listed components plus `networkPolicy.directCallers`
  entries, and `values-sandbox.yaml` names no `electric` entry. So the gate-on roll would cut
  Electric's own connection to Postgres (failing closed by accident), not protect Electric's port.
  The gate does not address path (c) in either direction.
- The sandbox values still carry a `VITE_ELECTRIC_URL` pointing at an external Electric host while
  the Electric ingress is closed (`values-sandbox.yaml:767` and `:866-886`). It reaches nothing
  today, but it is the one line that would make a browser try the direct path; #395 removes it.

## 3. Per-table census

Tables are derived from `sql/*.sql`, `helm/invincible-agent/files/sql/` (a copy), and every
`CREATE TABLE` in `src/` and `agent_fleet/` (one ORM model, `agent_fleet/models.py:42`, is the same
`bpmn_catalog`). Person columns mean columns that name a user. Domain columns mean columns that
carry a domain or label.

| table | defined at | person columns | domain/label columns |
| --- | --- | --- | --- |
| `answer_artifact_projection` | `sql/create_answer_artifact_projection.sql:16` | `produced_for`, `produced_for_user_id`, `produced_by`; the question and rendered answer are the caller's content | `resolved_intent`, `routing`, `sources` (retrieval provenance) |
| `projector_cursor` | same file `:138` | none | none |
| `projector_skip_log` | same file `:160` | none (`artifact_id`, `exception_message` may echo content) | none |
| `bpmn_catalog` | `sql/create_bpmn_catalog.sql:8` | none | none (`bpmn_payload` is the workflow definition) |
| `human_task_projection` | `sql/create_human_task_projection.sql:31`, columns added at `src/iagent/human_tasks.py:98-110` | `recipient_id`, `requested_by`, `acted_by`, `on_behalf_of`, `audience`, `excludes` | `subject_ref`, `payload` (carry the task's object, whose labels the viewer may not hold, ADR-0068 s6), `case_id` |
| `routing_fault` | `sql/create_human_task_projection.sql:115` | `addressee`, `on_behalf_of` | `dimension`, `label` |
| `ingest_status_projection` | `sql/create_ingest_status_projection.sql:26`, columns added at `src/iagent/ingest_status.py:193-258` | `submitted_by`, `on_behalf_of`, `leaf_set_by` | `source`, `object_prefix`, `content_kind`, `leaf_candidates`, `case_id`, `detail`, `failure` |
| `ingest_processable_kinds` | `src/iagent/processable_kinds.py:20` | `published_by` | `kinds` |
| `case_summary` | `sql/create_case_summary.sql:13` | `seeded_by` | `transitions`, `artifact_ids` |
| `document_decision_record` | `sql/create_document_decision_record.sql:13` | `acted_by` | `record` (free text, content) |
| `frontend_menu` | `sql/create_frontend_menu.sql:10` | `registered_by` | `menu` |
| `user_canvas` | `src/iagent/user_canvas.py:22` | `user_id` (the key) | `canvases` (the user's own layout) |

That is 12 tables, one row each above.

Two further classes are defined by dependencies, not by this repo. Their DDL was read from this
worktree's own synced venv (`dagster-postgres` 0.28.20 / `dagster` 1.12.20 table definitions in
`dagster/_core/storage/{runs,event_log,schedules}/schema.py`; `langgraph-checkpoint-postgres` 3.0.5
`langgraph/checkpoint/postgres/base.py:38-74`). Both share the database and role Electric uses:
`templates/dagster.yaml:50-53` sets `DAGSTER_POSTGRES_DB`/`USER` from the same `pgDatabase`/`pgUser`
defines as everything else, and `GRAPH_HOST_POSTGRES_DSN` (`values.yaml:803`) is composed from the
same `BPMN_POSTGRES_*` parts Electric's `DATABASE_URL` uses. Both create their tables as that role
(`AsyncPostgresSaver.setup()` at `agent_fleet/graph_host/main.py:197`; Dagster's alembic storage init).
Neither has a `produced_for_user_id` column.

LangGraph (4 tables):

| table | person columns | payload columns |
| --- | --- | --- |
| `checkpoints` | `thread_id` (a run id, not a user), `metadata` | `checkpoint` (JSONB graph state: conversation and intermediate content) |
| `checkpoint_blobs` | none | `blob` (BYTEA channel values: content). The caller's bearer token is redacted before write by `agent_fleet/graph_host/identity_scrub.py`, so a credential should not be here; a JWT-shape predicate, not a seal on this path |
| `checkpoint_writes` | none | `blob` (BYTEA pending writes: content) |
| `checkpoint_migrations` | none | none |

Dagster (22 tables). The caller identity reaches Dagster as run config: `gateway.py:9026-9037`
launches `supervisor_query_job` with `user_query`, `user_id`, `user_email` and `user_persona`, so
`runs.run_body` and the event log carry the question and the person.

| table | person or payload columns |
| --- | --- |
| `runs` | `run_body` (run config: question, user id, email, persona), `pipeline_name`, `partition` |
| `run_tags` | `key`, `value` (tags) |
| `event_logs` | `event` (serialized event payloads and log messages), `run_id`, `asset_key` |
| `snapshots` | `snapshot_body` (job structure) |
| `bulk_actions` | `body` (backfill definition) |
| `backfill_tags` | `key`, `value` |
| `asset_keys` | `last_materialization`, `asset_details`, `tags`, `cached_status_data` (materialization metadata) |
| `asset_event_tags` | `key`, `value` |
| `asset_check_executions` | `evaluation_event` |
| `asset_daemon_asset_evaluations` | `asset_evaluation_body` |
| `job_ticks` | `tick_body` |
| `jobs`, `instigators` | `job_body`, `instigator_body` (schedule and sensor definitions and cursors) |
| `kvs` | `key`, `value` |
| `daemon_heartbeats` | `body` (host and process info) |
| `dynamic_partitions`, `concurrency_limits`, `concurrency_slots`, `pending_steps`, `secondary_indexes`, `instance_info`, `alembic_version` | no person column; keys and counters only (`run_id`, `step_key`) |

### Partition, path by path

Rule for "checked": a check that scopes rows to the caller **and** the table carries no content the
caller could be barred from by a label. A row-owner filter on a table whose content is gated at
write time counts as checked; an owner filter on a table whose content has labels the owner may lack
does not.

| bucket | (a) #395 allow-list | (b) master proxy | (c) in-cluster, no proxy |
| --- | --- | --- | --- |
| exposed and checked | `answer_artifact_projection`, `ingest_status_projection` (2) | `answer_artifact_projection`, `ingest_status_projection` (2) | none (0) |
| exposed, unchecked | none (0) | `human_task_projection` (1): row-keyed on `recipient_id` but no label match on `payload` / `subject_ref`; the gap #395 closes by removing it | all 38 tables (38) |
| not exposed | the other 36, by allow-list (36) | the other 35, by the missing `produced_for_user_id` column only (35) | none (0) |
| UNDECIDED | none (0) | none (0) | none (0) |

Per table:

| table | (a) | (b) | (c) |
| --- | --- | --- | --- |
| `answer_artifact_projection` | checked: allow-list row, WHERE `produced_for_user_id = <sub>` and `archived_at IS NULL` (`gateway.py` #395 branch, step 2b and `:18078` arm) | checked: `:18064-18066` (schema-qualified name skips the archive clause) | unchecked: any pod, any row, no WHERE |
| `ingest_status_projection` | checked: allow-list row, WHERE submitter or on-behalf-of = authz id | checked: `:18054-18058` | unchecked |
| `human_task_projection` | not exposed: refused, no row | exposed-unchecked for content: `:18046-18052` filters on recipient only | unchecked |
| `projector_cursor`, `projector_skip_log`, `bpmn_catalog`, `routing_fault`, `ingest_processable_kinds`, `case_summary`, `document_decision_record`, `frontend_menu`, `user_canvas` | not exposed: refused | not exposed by accident: WHERE names a column they lack | unchecked (`routing_fault`, `user_canvas`, `document_decision_record`, `case_summary` name people; `projector_skip_log.exception_message` can echo content) |
| 22 Dagster tables | not exposed: refused (by name) | not exposed by accident: no `produced_for_user_id` column in any of them | unchecked: `runs.run_body`, `run_tags`, `event_logs` carry the question, user id and email |
| 4 LangGraph tables | not exposed: refused (by name) | not exposed by accident: no `produced_for_user_id` column | unchecked: `checkpoints.checkpoint`, `checkpoint_blobs.blob`, `checkpoint_writes.blob` hold graph state, i.e. content |

Totals across all 38 tables (12 provisioned, 22 Dagster, 4 LangGraph):

- path (a): 2 exposed-and-checked, 0 exposed-unchecked, 36 not exposed.
- path (b): 2 exposed-and-checked, 1 exposed-unchecked, 35 not exposed (accidental).
- path (c): 0 exposed-and-checked, 38 exposed-unchecked, 0 not exposed.
- UNDECIDED: 0 on every path.

Premise on (c): the count is an upper bound. Electric needs to own or be able to publish a table;
the role created the Dagster and LangGraph tables, so the census assumes it can. Evidence that would
shrink (c): `pg_tables.tableowner` for each table on a live database (not read here).

## 4. Who can reach what

| actor | route | tables reached |
| --- | --- | --- |
| browser user | BFF proxy, after #395 | the 2 allow-listed tables, filtered to the caller |
| browser user | BFF proxy, on master | answers and ingest (filtered), tasks (recipient-filtered, no label match) |
| any pod in the namespace | direct to the Electric Service | every table the role can read, any WHERE, no authentication |
| outside the cluster | none by chart configuration (ingress closed, ClusterIP only) | none; one values line (`VITE_ELECTRIC_URL`) still names an external host |
| anyone who flips `electric.ingress.enabled` | direct | everything, unauthenticated |

## 5. Ranked recommendations (recommendations, not changes)

1. **Put Electric behind a NetworkPolicy that admits only cortex-bff.** One ingress policy selecting
   `component: electric`, allowing only the `cortex-bff` component on `electric.port`. This is the
   only fix that closes path (c); the allow-list does not. It needs a seal in the style of
   `tests/test_networkpolicy_direct_callers_join.py` that every Service the chart renders for
   a data-bearing component has an ingress policy, and a decision on how it relates to the
   `networkPolicy.enabled` gate (an Electric-only policy should not wait for the whole gate roll).
2. **Turn `electric.insecure` off, give Electric an API secret, and hold it in cortex-bff only.**
   Independent of (1): authentication at Electric means a pod that reaches the port still cannot
   read. The proxy adds the secret on the upstream call (`gateway.py:18071` is the call site). The
   secret goes in a `*.secret.yaml`, never in the values file, and is read by length and hash prefix
   only.
3. **Give Electric its own database role with SELECT on the two allow-listed tables only.** Today
   the role is the application role with `GRANT ... ON ALL TABLES` and default privileges, so every
   future table is streamable by construction. A dedicated role, owner of nothing and granted per
   table by the same rows as `policy/electric_shapes.yaml`, makes the database refuse what the
   proxy refuses, and shrinks path (c) to two tables even if (1) and (2) slip. This needs a design
   note first (Electric creates its own publication and wants ownership; the manual-publication
   mode is the likely route).
4. **Seal the allow-list against the database.** A test that derives the table list from the DDL
   (as this census did) and asserts every table is either an allow-list row or listed as
   not-streamable with a reason, so a new table is classified in the PR that adds it (the rule the
   refusal ratchet already applies to refusal sites).
5. **Close path (b)'s accidental refusal.** Move #395 to master (it removes the `else` that builds a
   WHERE on a column most tables lack), and treat the schema-qualified-name bypass of the archive
   clause as fixed by the exact-match refusal at `:18048`.
6. **Move Dagster, and the LangGraph checkpoints, out of the sync role's reach.** They add 26 of the 38
   tables, including `runs.run_body` with each question, user id and email. A separate database or role
   for Dagster removes 22 tables from path (c) at no cost to the sync stream; recommendation 3 would
   remove all 26 as a side effect.
7. **Remove or correct the sandbox `VITE_ELECTRIC_URL` line and its comments** (`values-sandbox.yaml`
   `:762-767`, `:866-886`) so the values file stops describing a direct browser path the chart does
   not provide. #395 already removes the variable; the comment at `:866` needs the same.
8. **Note for the gate-on roll:** the postgresql ingress policy would cut Electric's own connection
   (no `electric` `directCallers` entry). Decide deliberately whether Electric is a direct caller
   of Postgres before the gate goes on; a render of the gate-on values will confirm what this read
   of the templates suggests.
