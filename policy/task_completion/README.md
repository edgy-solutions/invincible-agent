# task_completion — the seed (structural species only)

One YAML per task kind, `kind:` as the key, composed by `iagent_mesh.declarations.compose_rows`
(ADR-0036). A row declares what a follow-on task must record before it can complete:
`by` (the payload key whose value selects the field list), `required_on` (verbs that complete the
task), `blank` (the text a blank is written as at review) and `fields` (per `by` value, a list of
`{name, label, type}`; types are `text`, `positive_integer`, `date`).

Domain rows never enter the seed. A deployment's rows live in its overlay's own
`task_completion/` directory, a sibling of its `task_kinds/`. See `src/iagent/task_completion.py`.
