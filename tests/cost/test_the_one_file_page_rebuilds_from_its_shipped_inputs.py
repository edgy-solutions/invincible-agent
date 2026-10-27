"""The one-file (slice-1) page rebuilds from the two inputs it ships with.

The slice-1 branch of `build_html` once dropped `as_of`, so `--as-of D` with no dataset embedded
today's date and the page could not be rebuilt. `--sha` and `--like PAGE` close the other half:
the sha the page claims, and a rebuild that takes both pins from a page already shipped.

No duckdb here: slice 1 reads none, so these run wherever the Pyodide runtime is fetched.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
    pytest.skip("the pinned Pyodide runtime is not fetched here", allow_module_level=True)

import build_cost_package as B  # noqa: E402
import cost_package_identities as I  # noqa: E402

RECIPIENT = "notional-customer-alpha"
NAME = f"cost-validation-{RECIPIENT}.html"
SHA = "0" * 40
AS_OF = "2026-01-02"


def _build(out_dir, *extra):
    argv = ["--recipient", RECIPIENT, "--out-dir", str(out_dir),
            "--runtime-dir", str(ROOT / ".pyodide-cache"), *extra]
    assert B.main(argv) == 0
    return out_dir / NAME


def _pinned(out_dir, sha=SHA, as_of=AS_OF):
    return _build(out_dir, "--sha", sha, "--as-of", as_of)


def _embedded(page):
    pkg = I.package_from_html(page.read_text("utf-8"))
    return pkg["algorithm_sha"], pkg["as_of"]


def test_the_one_file_page_embeds_the_as_of_it_was_given(tmp_path):
    page = _build(tmp_path, "--sha", SHA, "--as-of", AS_OF)
    assert I.package_from_html(page.read_text("utf-8"))["as_of"] == AS_OF


def test_two_one_file_builds_with_pinned_sha_and_date_are_byte_identical(tmp_path):
    one = _pinned(tmp_path / "one")
    two = _pinned(tmp_path / "two")
    assert one.read_bytes() == two.read_bytes()


def test_like_reproduces_a_built_page_byte_for_byte(tmp_path):
    a = _pinned(tmp_path / "dir1")
    b = _build(tmp_path / "dir2", "--like", str(a))
    assert a.read_bytes() == b.read_bytes()
    assert _embedded(b)[0] == SHA


def test_like_takes_its_inputs_from_the_page_not_the_clock_or_HEAD(tmp_path):
    a = _pinned(tmp_path / "a", sha="1" * 40, as_of="2026-01-03")
    b = _build(tmp_path / "b", "--like", str(a))
    assert _embedded(b) == ("1" * 40, "2026-01-03")


def _refused(tmp_path, fragment, *extra):
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        B.main(["--recipient", RECIPIENT, "--out-dir", str(out),
                "--runtime-dir", str(ROOT / ".pyodide-cache"), *extra])
    assert fragment in str(e.value)
    assert not out.exists() or not any(out.iterdir())


def test_like_with_sha_is_refused_by_name(tmp_path):
    a = _pinned(tmp_path / "a")
    _refused(tmp_path, "--like supplies --sha and --as-of; pass one or the other",
             "--like", str(a), "--sha", SHA)


def test_like_with_as_of_is_refused_by_name(tmp_path):
    a = _pinned(tmp_path / "a")
    _refused(tmp_path, "--like supplies --sha and --as-of; pass one or the other",
             "--like", str(a), "--as-of", AS_OF)


def test_like_a_missing_file_names_the_path(tmp_path):
    missing = tmp_path / "nowhere.html"
    _refused(tmp_path, f"{missing}: no such file", "--like", str(missing))


def test_like_a_page_without_a_package_block_is_refused(tmp_path):
    junk = tmp_path / "junk.html"
    junk.write_text("<html></html>", "utf-8")
    _refused(tmp_path, "no package-data block", "--like", str(junk))


def test_a_sha_that_is_not_40_hex_is_refused(tmp_path):
    _refused(tmp_path, "--sha must be a 40-hex commit, got 'nothex'", "--sha", "nothex")
