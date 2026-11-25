"""Electric's own database role (electric.db.enabled): the census of what it may read, and what its pod holds.

Seals (step 3 of the sync-service exposure plan):

1. OFF by default: no Job, no Secret, and Electric's pod is exactly as before (envFrom kept).
2. ON: the pod has no `envFrom` and no init container, and its DATABASE_URL names the configured role and NOT the
   main user (the main user's name is read from values.yaml's postgresql.auth.username, with a control that it is
   non-empty and appears in the OFF render's pod env source).
3. CENSUS: the tables the Job grants SELECT on equal the tables policy/electric_shapes.yaml names, the YAML READ
   here, not restated; the chart's copy of that file is byte-equal to the policy file.
4. No `ALL TABLES`; no table name typed in a template; the password is a secretKeyRef, never a literal.
5. The role name comes from values; a second deployment with another allow-list gets its own grants (the chart is
   copied and its allow-list replaced).
6. An empty allow-list fails the render.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_POLICY = _REPO / "policy" / "electric_shapes.yaml"
_COPY = _CHART / "files" / "policy" / "electric_shapes.yaml"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _helm(chart: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "r", str(chart), *extra], capture_output=True, text=True,
                          cwd=str(_REPO), timeout=300)


def _render(*extra: str, chart: Path = _CHART) -> list[dict]:
    r = _helm(chart, *extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _on(*extra: str, chart: Path = _CHART) -> list[dict]:
    return _render("--set", "electric.db.enabled=true", *extra, chart=chart)


def _electric_pod(docs):
    dep = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "r-electric")
    return dep["spec"]["template"]["spec"]


def _job(docs):
    return [d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"] == "r-electric-role"]


def _script(job) -> str:
    return "\n".join(job["spec"]["template"]["spec"]["containers"][0]["command"])


def _policy_tables(path: Path = _POLICY) -> list[str]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))["electric_shapes"]
    return [r["table"] for r in rows]


def _granted(script: str) -> list[str]:
    return re.findall(r'GRANT SELECT ON TABLE "[^"]+"\."([^"]+)"', script)


def test_off_by_default_changes_nothing():
    docs = _render()
    assert _job(docs) == []
    assert not [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == "r-electric-db"]
    pod = _electric_pod(docs)
    assert pod["containers"][0].get("envFrom"), "control: the OFF render keeps its envFrom"
    assert pod.get("initContainers")


def test_the_pod_has_no_envfrom_and_its_url_does_not_name_the_main_user():
    main = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["postgresql"]["auth"]["username"]
    assert main, "control: a main user exists"
    off_env = {e["name"]: e.get("value", "") for e in _electric_pod(_render())["containers"][0]["env"]}
    assert "BPMN_POSTGRES_USER" in off_env["DATABASE_URL"], "control: the OFF url takes the main user by reference"
    pod = _electric_pod(_on())
    c = pod["containers"][0]
    assert "envFrom" not in c and not pod.get("initContainers")
    url = next(e["value"] for e in c["env"] if e["name"] == "DATABASE_URL")
    assert url.startswith("postgresql://electric_reader:"), url
    assert f"//{main}:" not in url and "BPMN_POSTGRES" not in url


def test_the_password_is_a_secret_key_ref_in_pod_and_job_and_the_secret_is_rendered():
    docs = _on()
    refs = []
    for d in (_electric_pod(docs)["containers"][0], _job(docs)[0]["spec"]["template"]["spec"]["containers"][0]):
        e = next(x for x in d["env"] if x["name"] == "ELECTRIC_DB_PASSWORD")
        assert "value" not in e
        refs.append((e["valueFrom"]["secretKeyRef"]["name"], e["valueFrom"]["secretKeyRef"]["key"]))
    assert refs[0] == refs[1] == ("r-electric-db", "password")
    assert [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == "r-electric-db"]


def test_census_the_granted_tables_equal_the_policy_file_read_here():
    want = _policy_tables()
    assert len(want) >= 2, "control: the ruled case is a multi-table row"
    script = _script(_job(_on())[0])
    assert sorted(_granted(script)) == sorted(want)
    pub = re.search(r'CREATE PUBLICATION "[^"]+" FOR TABLE ([^;]+);', script).group(1)
    assert sorted(re.findall(r'\."([^"]+)"', pub)) == sorted(want)


def test_the_charts_copy_is_byte_equal_to_the_policy_file():
    assert _COPY.read_bytes() == _POLICY.read_bytes()


def test_no_blanket_grant_and_no_table_typed_in_the_electric_templates():
    script = _script(_job(_on())[0])
    assert "ALL TABLES" not in script.upper()
    for t in _policy_tables():
        for f in (_CHART / "templates").glob("electric*.yaml"):
            if f.is_file():
                code = chr(10).join(l for l in f.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
                assert t not in code, f"{t} typed in {f.name}"


def test_the_role_name_comes_from_values():
    docs = _on("--set", "electric.db.role=zz_reader")
    assert 'TO "zz_reader"' in _script(_job(docs)[0])
    url = next(e["value"] for e in _electric_pod(docs)["containers"][0]["env"] if e["name"] == "DATABASE_URL")
    assert url.startswith("postgresql://zz_reader:")


def test_a_second_deployment_with_another_allow_list_gets_its_own_grants(tmp_path):
    chart = tmp_path / "chart"
    shutil.copytree(_CHART, chart)
    (chart / "files" / "policy" / "electric_shapes.yaml").write_text(
        "electric_shapes:\n  - table: only_one_table\n", encoding="utf-8")
    script = _script(_job(_on(chart=chart))[0])
    assert _granted(script) == ["only_one_table"]


def test_an_empty_allow_list_fails_the_render(tmp_path):
    chart = tmp_path / "chart"
    shutil.copytree(_CHART, chart)
    (chart / "files" / "policy" / "electric_shapes.yaml").write_text("electric_shapes: []\n", encoding="utf-8")
    r = _helm(chart, "--set", "electric.db.enabled=true")
    assert r.returncode != 0 and "names no table" in r.stderr


# ---------------------------------------------------------------------------------------------
# gov's review of #546 at 16537d2f: findings 1-4 and the seals E2/E3/E4/E6
# ---------------------------------------------------------------------------------------------
def _bad_table_chart(tmp_path: Path, table: str) -> Path:
    chart = tmp_path / "chart"
    shutil.copytree(_CHART, chart)
    (chart / "files" / "policy" / "electric_shapes.yaml").write_text(
        f"electric_shapes:\n  - table: {table!r}\n", encoding="utf-8")
    return chart


def test_1_the_job_revokes_what_the_role_holds_outside_the_list_before_any_grant_in_one_transaction():
    job = _job(_on())[0]
    script = _script(job)
    want = _policy_tables()
    rev = script.index("REVOKE ALL PRIVILEGES ON TABLE")
    assert rev < script.index("GRANT "), "the revoke must precede the first GRANT"
    block = script[script.rindex("DO $$", 0, rev):rev]
    assert "information_schema.role_table_grants" in block and "grantee = 'electric_reader'" in block
    keep = re.search(r"<> ALL \(ARRAY\[([^\]]*)\]\)", block).group(1)
    assert sorted(re.findall(r"'([^']+)'", keep)) == sorted(f"public.{t}" for t in want), "keep-set == the rendered list"
    line = next(l for l in script.splitlines() if l.lstrip().startswith("psql "))
    assert re.search(r"(^| )-1( |$)", line) and re.search(r"(-f -|--file=-)( |$)", line), (
        "psql -1 only wraps -f/-c actions: the script must come in as -f - for the transaction to exist")
    assert "ALL TABLES" not in script.upper()


def test_1_the_keep_set_follows_the_schema_value():
    script = _script(_job(_on("--set", "electric.db.schema=other"))[0])
    keep = re.search(r"<> ALL \(ARRAY\[([^\]]*)\]\)", script).group(1)
    assert all(k.startswith("other.") for k in re.findall(r"'([^']+)'", keep))


def test_2_the_job_fails_if_another_publication_exists_and_the_comments_state_the_reach():
    script = _script(_job(_on())[0])
    gate = script.index("pubname <> 'electric_publication_default'")
    assert gate < script.index("CREATE ROLE"), "the publication gate runs before anything is created"
    assert re.search(r"IF o IS NOT NULL THEN[^;]{0,20}RAISE EXCEPTION", script[gate:gate + 600]), "the gate raises when another publication exists"
    assert script.index("RAISE EXCEPTION") < script.index("GRANT ")
    tpl = (_CHART / "templates" / "electric.yaml").read_text(encoding="utf-8")
    vals = (_CHART / "values.yaml").read_text(encoding="utf-8")
    assert "read-only on the allow-listed tables" not in tpl
    assert "stream ANY" in tpl and "stream ANY" in vals


def test_3_the_password_stays_out_of_argv_and_out_of_the_server_log():
    job = _job(_on())[0]
    script = _script(job)
    assert "SET log_statement = 'none';" in script and "SET log_min_error_statement = 'panic';" in script
    assert "SET log_min_duration_statement = -1;" in script and script.index("SET log_min_duration_statement") < script.index("PASSWORD %L")
    assert script.index("SET log_min_error_statement") < script.index("PASSWORD %L")
    assert chr(92) + "getenv pw ELECTRIC_DB_PASSWORD" in script
    assert "-v pw=" not in script and "$ELECTRIC_DB_PASSWORD" not in script
    image = job["spec"]["template"]["spec"]["containers"][0]["image"]
    major = int(re.search(r":(\d+)", image).group(1))
    assert major >= 15, f"getenv needs psql 15+; the chart image is {image}"


def test_3_a_psql_older_than_15_fails_the_render_and_so_does_an_unreadable_tag():
    for tag in ("14-alpine", "latest"):
        r = _helm(_CHART, "--set", "electric.db.enabled=true", "--set", f"utilImages.postgresClient.tag={tag}")
        assert r.returncode != 0 and "needs psql 15 or newer" in r.stderr, tag
    assert _helm(_CHART, "--set", "electric.db.enabled=true", "--set",
                 "utilImages.postgresClient.tag=16.2-alpine").returncode == 0


def test_4_the_job_pod_names_its_component_and_adds_no_default_directcallers_row():
    docs = _on()
    job = _job(docs)[0]
    assert job["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/component"] == "electric-role"
    vals = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    assert "electric-role" not in (vals["networkPolicy"].get("directCallers") or {})


def test_E2_a_bad_table_name_fails_the_render_with_the_message(tmp_path):
    for bad in ("Bad-Name", 'x"; DROP TABLE y; --'):
        r = _helm(_bad_table_chart(tmp_path / ("c" + str(abs(hash(bad)))), bad), "--set", "electric.db.enabled=true")
        assert r.returncode != 0 and "is not a plain lower-case SQL identifier" in r.stderr, bad
        assert "electric_shapes.yaml: table" in r.stderr


@pytest.mark.parametrize("key", ["role", "publication", "schema"])
def test_E3_a_bad_role_publication_or_schema_fails_the_render(key):
    r = _helm(_CHART, "--set", "electric.db.enabled=true", "--set", f"electric.db.{key}=Bad-Name")
    assert r.returncode != 0 and "is not a plain lower-case SQL identifier" in r.stderr and "electric.db:" in r.stderr


def test_E4_the_publication_is_replaced_by_the_list():
    script = _script(_job(_on())[0])
    want = _policy_tables()
    m = re.search(r'ALTER PUBLICATION "[^"]+" SET TABLE ([^;]+);', script)
    assert m and sorted(re.findall(r'\."([^"]+)"', m.group(1))) == sorted(want)
    assert "ADD TABLE" not in script.upper()


def test_E6_bare_defaults_never_revoke_replication_from_the_main_user():
    assert "NOREPLICATION" not in _script(_job(_on())[0])
    assert "NOREPLICATION" in _script(_job(_on("--set", "electric.db.revokeReplicationFromMainUser=true"))[0]), \
        "control: the switch, when true, renders it"
