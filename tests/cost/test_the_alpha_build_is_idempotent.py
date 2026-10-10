"""The alpha document is rebuilt from ONE duckdb file by a scripted build, and a rebuild is the same bytes.

`scripts/build_cost_package.py` could not produce the same bytes twice: it rebuilt the .duckdb
each run (whose bytes differ over identical rows, and whose sha256 is in the page), took
today's date as `as_of`, wrote in text mode (CRLF on Windows), and had no canvas input.
`--duckdb`, `--as-of`, `--canvas` and a bytes write close those, and
`scripts/build_alpha_document.py` pins the alpha inputs. Here the duckdb is built ONCE per
module, and everything that follows is measured against that one file.

"SAME" IS TWO CLAIMS: byte-identical to ITSELF (the build is deterministic given its inputs)
and identity-identical to the 09-06 document (`cost_package_identities.py`). It is not
byte-identical to 09-06, because `algorithm_sha` and the duckdb container are inputs.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("duckdb")
if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
    pytest.skip("the pinned Pyodide runtime is not fetched here", allow_module_level=True)

import build_alpha_document as A  # noqa: E402
import build_cost_package as B  # noqa: E402
import cost_package_identities as I  # noqa: E402

FIXTURE = json.loads(A.FIXTURE.read_text("utf-8"))
ALPHA = A.RECIPIENT
NAME = f"cost-validation-{ALPHA}.html"


@pytest.fixture(scope="module")
def duckdb_file(tmp_path_factory):
    """The ONE dataset every build in this module reuses."""
    import build_cost_dataset as D

    return D.build(ALPHA, tmp_path_factory.mktemp("db") / f"cost-{ALPHA}.duckdb")


def _build(duckdb_file, out_dir, *extra):
    argv = ["--recipient", ALPHA, "--duckdb", str(duckdb_file), "--canvas", str(A.CANVAS),
            "--as-of", FIXTURE["provenance"]["as_of"], "--out-dir", str(out_dir),
            "--runtime-dir", str(ROOT / ".pyodide-cache"), *extra]
    assert B.main(argv) == 0
    return out_dir / NAME


@pytest.fixture(scope="module")
def two_builds(duckdb_file, tmp_path_factory):
    return (_build(duckdb_file, tmp_path_factory.mktemp("one")),
            _build(duckdb_file, tmp_path_factory.mktemp("two")))


def test_two_builds_from_one_duckdb_are_byte_identical(two_builds):
    one, two = two_builds
    assert one.read_bytes() == two.read_bytes()


def _narrowed():
    from agent_fleet.cost_agent import canvas as canvas_reader
    from agent_fleet.cost_agent.seed import lots_for_recipient

    composed = canvas_reader.resolve(
        json.loads(A.CANVAS.read_text("utf-8")), recipient_scope=ALPHA,
        entitled_lots=lots_for_recipient(ALPHA))
    return dict(lots=composed["lots"], sections=composed["sections"],
                canvas_answers=composed["answers"])


def test_the_file_on_disk_is_the_encoded_string_so_no_CRLF_was_added(duckdb_file, two_builds):
    on_disk = two_builds[0].read_bytes()
    assert b"\r\n" not in on_disk
    # The same page built in memory: the bytes written must be exactly its UTF-8 encoding.
    html = B.build_html(
        ALPHA, ROOT / ".pyodide-cache", duckdb_file, as_of=FIXTURE["provenance"]["as_of"],
        sha=I.package_from_html(on_disk.decode("utf-8"))["algorithm_sha"], **_narrowed())
    assert on_disk == html.encode("utf-8")


def test_the_built_document_has_the_09_06_identities_and_sections(two_builds):
    built = I.extract(two_builds[0])
    assert A.differing_keys(built, FIXTURE) == []
    assert built["identities"] == FIXTURE["identities"]
    assert built["sections"] == FIXTURE["sections"]


def test_the_embedded_as_of_is_the_fixtures_not_todays(two_builds):
    pkg = I.package_from_html(two_builds[0].read_text("utf-8"))
    assert pkg["as_of"] == FIXTURE["provenance"]["as_of"]
    assert pkg["as_of"] != date.today().isoformat()


def test_the_default_as_of_is_still_today(duckdb_file, tmp_path):
    """Existing callers do not move: no --as-of means the build date, as before."""
    argv = ["--recipient", ALPHA, "--duckdb", str(duckdb_file), "--out-dir", str(tmp_path),
            "--runtime-dir", str(ROOT / ".pyodide-cache")]
    assert B.main(argv) == 0
    pkg = I.package_from_html((tmp_path / NAME).read_text("utf-8"))
    assert pkg["as_of"] == date.today().isoformat()


def _refusal(argv):
    with pytest.raises(SystemExit) as exc:
        B.main(["--recipient", ALPHA, "--runtime-dir", str(ROOT / ".pyodide-cache"), *argv])
    return str(exc.value)


def test_duckdb_with_with_dataset_is_refused_by_name(duckdb_file, tmp_path):
    msg = _refusal(["--duckdb", str(duckdb_file), "--with-dataset", "--out-dir", str(tmp_path)])
    assert "--duckdb and --with-dataset are exclusive" in msg
    assert list(tmp_path.iterdir()) == []


def test_a_canvas_without_a_dataset_is_refused_by_name(tmp_path):
    msg = _refusal(["--canvas", str(A.CANVAS), "--out-dir", str(tmp_path)])
    assert "--canvas needs a dataset" in msg


def test_a_missing_duckdb_is_refused_naming_the_path(tmp_path):
    gone = tmp_path / "not-there.duckdb"
    msg = _refusal(["--duckdb", str(gone), "--out-dir", str(tmp_path)])
    assert str(gone) in msg and "no such file" in msg


def test_a_malformed_as_of_is_refused(duckdb_file, tmp_path):
    msg = _refusal(["--duckdb", str(duckdb_file), "--as-of", "09/06/2026",
                    "--out-dir", str(tmp_path)])
    assert "--as-of must be YYYY-MM-DD" in msg


def test_a_second_scripted_run_is_unchanged_and_leaves_the_mtime(duckdb_file, tmp_path, capsys):
    argv = ["--duckdb", str(duckdb_file), "--out-dir", str(tmp_path)]
    assert A.main(argv) == 0
    first = capsys.readouterr().out
    dest = tmp_path / NAME
    assert "wrote " in first and "unchanged" not in first
    before = dest.stat().st_mtime_ns
    assert A.main(argv) == 0
    second = capsys.readouterr().out
    assert "unchanged " in second and "wrote " not in second
    assert dest.stat().st_mtime_ns == before


def test_the_scripted_build_names_each_differing_key():
    other = json.loads(json.dumps(FIXTURE))
    other["identities"]["rows_sha256"] = "sha256:other"
    other["sections"] = other["sections"][:-1]
    assert A.differing_keys(other, FIXTURE) == ["rows_sha256", "sections"]


def test_the_scripted_build_embeds_the_fixtures_as_of_and_all_eight_canvas_answers(
        duckdb_file, tmp_path):
    """Two things the identities cannot see: `as_of` is not an identity, and five of the eight
    answers select nothing the other three do not (measured: dropping any of them leaves the
    lots and sections unchanged). Only the embedded answer list, pinned here, shows one gone."""
    assert A.main(["--duckdb", str(duckdb_file), "--out-dir", str(tmp_path)]) == 0
    pkg = I.package_from_html((tmp_path / NAME).read_text("utf-8"))
    assert pkg["as_of"] == FIXTURE["provenance"]["as_of"]
    assert pkg["canvas_answers"] == [
        "ans-labor-1", "ans-trend", "ans-price-2", "ans-breakdown-3", "ans-category-4",
        "ans-rates-5", "ans-suppliers-3", "ans-assumptions"]
