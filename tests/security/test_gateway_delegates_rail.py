"""The `policy/gateway_delegates.yaml` rail and its validator.

WHAT EACH GROUP DEFENDS
  seed        the shipped rail validates clean against the shipped users, and the validate_policy
              CLI is green and prints the rail's line.
  when present  an absent file is valid (no delegate); a present one is validated and its errors
              reach `validate()`.
  no read     a row is not a grant: the rail file holds no grantee key, and the delegate holds no
              group through it.
  red arms    one per error class, each differing from the valid baseline in exactly one thing,
              each asserting a FRAGMENT of the message.

  read at    GATEWAY_ROUTES is a copy of dag-tools' route ids, read at one gateway image. The chart
              pinning another image is red until the list is re-read.

Nothing reads this rail yet: the gateway's `is_delegate` seam is in dag-tools and answers no until it
is wired. So nothing here measures a delegate being honoured.

Run:  uv run pytest tests/security/test_gateway_delegates_rail.py -q
"""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SYNC = _REPO / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

import validate_policy as vp  # noqa: E402

_POLICY = _REPO / "policy"
_RAIL = _POLICY / "gateway_delegates.yaml"
_SEED = yaml.safe_load(_RAIL.read_text(encoding="utf-8"))
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]

_B_USERS = [{"id": "svc:a"}, {"id": "svc:b"}, {"id": "alice"}]
_ROUTE = vp.GATEWAY_ROUTES[0]


def _row(**over):
    row = {"service": "svc:a", "routes": [_ROUTE], "granted_by": "seed", "reason": "because",
           "ratified_by": "owner"}
    row.update(over)
    return row


def _b(raw, users=None):
    return vp.gateway_delegates_errors(raw, _B_USERS if users is None else users)


def _red(raw, fragment):
    errs = _b(raw)
    assert any(fragment in e for e in errs), errs
    assert all(e.startswith("gateway_delegates.yaml: ") for e in errs), errs


def _rows(*rows):
    return {"gateway_delegates": list(rows)}


# ---- the positive control and the seed ---------------------------------------------------------

def test_the_valid_baseline_is_clean():
    assert _b(_rows(_row(), _row(service="svc:b"))) == []


def test_an_empty_list_names_no_delegate_and_is_valid():
    assert _b(_rows()) == []


def test_the_seed_parses_clean():
    assert _SEED["gateway_delegates"]                   # control: the rows are read
    assert vp.gateway_delegates_errors(_SEED, _USERS) == []


def test_the_validate_policy_cli_is_green_and_prints_the_rail():
    r = subprocess.run([sys.executable, str(_SYNC / "validate_policy.py")],
                       capture_output=True, text=True, cwd=_REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert f"gateway_delegates.yaml: {len(_SEED['gateway_delegates'])} row(s)" in r.stdout


def test_every_seed_row_says_why_and_who_ratified_it():
    """Architect 11-04: every row carries both. The validator enforces it; this names the ruling."""
    for row in _SEED["gateway_delegates"]:
        assert row.get("reason", "").strip() and row.get("ratified_by", "").strip(), row


def test_every_seed_service_is_a_seeded_service_identity():
    ids = {u["id"] for u in _USERS}
    for row in _SEED["gateway_delegates"]:
        assert row["service"].startswith(vp.SERVICE_SUBJECT_PREFIX) and row["service"] in ids, row


# ---- validated when present --------------------------------------------------------------------

def _policy_copy(tmp_path):
    pol = tmp_path / "policy"
    shutil.copytree(_POLICY, pol, ignore=shutil.ignore_patterns("__pycache__"))
    return pol


def _rail_errors(pol):
    return [e for e in vp.validate(pol, pol) if e.startswith("gateway_delegates.yaml")]


def test_validate_carries_a_rail_error(tmp_path):
    """Clean as copied (the control), refused once a row is broken. Without this arm the CLI test
    stays green with the rail's errors dropped on the floor."""
    pol = _policy_copy(tmp_path)
    assert _rail_errors(pol) == []
    raw = copy.deepcopy(_SEED)
    raw["gateway_delegates"][0]["routes"] = ["no.such.route"]
    (pol / "gateway_delegates.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    errs = _rail_errors(pol)
    assert any("unknown route 'no.such.route'" in e for e in errs), errs


def test_validate_passes_the_real_users_to_the_rail(tmp_path):
    """A seeded service passes only if `validate()` handed the validator users.yaml: drop the row's
    service from a copy of users.yaml and the same rail goes red."""
    pol = _policy_copy(tmp_path)
    service = _SEED["gateway_delegates"][0]["service"]
    users = yaml.safe_load((pol / "users.yaml").read_text(encoding="utf-8"))
    users["users"] = [u for u in users["users"] if u["id"] != service]
    (pol / "users.yaml").write_text(yaml.safe_dump(users, sort_keys=False), encoding="utf-8")
    errs = _rail_errors(pol)
    assert any(service in e and "not a seeded identity" in e for e in errs), errs


def test_an_absent_file_is_valid_and_not_required(tmp_path):
    pol = _policy_copy(tmp_path)
    (pol / "gateway_delegates.yaml").unlink()
    assert _rail_errors(pol) == []
    assert "gateway_delegates.yaml" not in vp.DATA_FILES


# ---- a row is not a grant ----------------------------------------------------------------------

def test_a_row_holds_no_grantee_key():
    for row in _SEED["gateway_delegates"]:
        assert set(row) <= set(vp._GD_ROW_FIELDS), row
    assert not {"grant_to", "grant_to_groups"} & set(vp._GD_ROW_FIELDS)


def test_a_seeded_delegate_holds_no_group():
    """The row's first service keeps the users.yaml caution: naming a person on a route does not
    entitle the service to read anything itself."""
    delegates = {r["service"] for r in _SEED["gateway_delegates"]}
    held = {u["id"]: u.get("groups") or [] for u in _USERS if u["id"] in delegates}
    assert set(held) == delegates                       # control: every delegate was found
    assert not any(held.values()), held


# ---- red arms ----------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, fragment", [
    ([], "exactly one key"),
    ({}, "exactly one key"),
    ({"gateway_delegates": [], "extra": 1}, "unknown key(s): extra"),
    ({"gateway_delegates": None}, "must be a list"),
    ({"gateway_delegates": {"svc:a": _row()}}, "must be a list"),
    ({"gateway_delegates": ["svc:a"]}, "row 0: must be a mapping"),
])
def test_a_malformed_file_is_refused(raw, fragment):
    _red(raw, fragment)


@pytest.mark.parametrize("over, fragment", [
    ({"route": [_ROUTE]}, "unknown key 'route'"),
    ({"service": None}, "`service` must be a non-empty string"),
    ({"service": "  "}, "`service` must be a non-empty string"),
    ({"service": 7}, "`service` must be a non-empty string"),
    ({"service": "alice"}, "a person holds their own token"),
    ({"service": "svc:nobody"}, "not a seeded identity"),
    ({"service": "svc:*"}, "not a seeded identity"),
    ({"routes": None}, "`routes` must be a non-empty list"),
    ({"routes": []}, "`routes` must be a non-empty list"),
    ({"routes": _ROUTE}, "`routes` must be a non-empty list"),
    ({"routes": ["no.such.route"]}, "unknown route 'no.such.route'"),
    ({"routes": ["*"]}, "unknown route '*'"),
    ({"routes": [_ROUTE, _ROUTE]}, "is listed more than once"),
    ({"granted_by": None}, "`granted_by` must be a non-empty string"),
    ({"granted_by": " "}, "`granted_by` must be a non-empty string"),
    ({"reason": None}, "`reason` must be a non-empty string"),
    ({"reason": ""}, "`reason` must be a non-empty string"),
    ({"ratified_by": None}, "`ratified_by` must be a non-empty string"),
    ({"ratified_by": "  "}, "`ratified_by` must be a non-empty string"),
    ({"ratified_by": 3}, "`ratified_by` must be a non-empty string"),
    ({"ratified_by": "alice"}, "names a seat"),
    ({"ratified_by": "svc:b"}, "names a seat"),
    ({"service": "pipeline:nightly"}, "never a delegate row"),
])
def test_a_bad_row_is_refused(over, fragment):
    _red(_rows(_row(**over)), fragment)


def test_a_service_named_twice_is_refused():
    _red(_rows(_row(), _row()), "more than one row names this service")


def test_a_person_is_refused_even_when_seeded():
    """`alice` IS in users.yaml, so the seeded check alone would pass her; the prefix is what refuses."""
    assert "alice" in {u["id"] for u in _B_USERS}
    assert any("own token" in e for e in _b(_rows(_row(service="alice"))))


def test_an_unhashable_route_is_refused_not_a_crash():
    _red(_rows(_row(routes=[["nested"]])), "unknown route")
    _red(_rows(_row(routes=[["nested"], ["nested"]])), "unknown route")


def test_a_pipeline_gets_its_own_refusal_and_only_that():
    """`pipeline:` also fails the `svc:` prefix; the reader should see why, once, not two reasons."""
    errs = _b(_rows(_row(service="pipeline:nightly")))
    assert len(errs) == 1 and "never a delegate row" in errs[0], errs


def test_a_row_without_ratified_by_is_refused_by_name():
    row = _row()
    del row["ratified_by"]
    _red(_rows(row), "`ratified_by` must be a non-empty string")


# ---- the route list is a copy, read at a pinned gateway image ----------------------------------

_VALUES = _REPO / "helm" / "invincible-agent"
#: The chart's own values files. `values-roll-frontend-digest.yaml` is a per-roll overlay (09-26),
#: passed only by the roll that wrote it; the chart's pin of record is the sandbox file's.
_PIN_FILES = ("values.yaml", "values-sandbox.yaml")


def _unread_gateway_pins(paths):
    """Each file whose central-gateway image is pinned to anything but the image the list was read at."""
    want = vp.GATEWAY_ROUTES_READ_AT["central_gateway_digest"]
    out = {}
    for p in paths:
        image = ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("centralGateway") or {}).get(
            "image") or {}
        pin = image.get("digest") or (f"tag:{image['tag']}" if image.get("tag") else None)
        if pin and pin != want:
            out[p.name] = pin
    return out


def test_the_route_list_was_read_at_the_pinned_gateway_image():
    paths = [_VALUES / f for f in _PIN_FILES]
    assert any("digest:" in p.read_text(encoding="utf-8") for p in paths)   # control: a pin exists
    moved = _unread_gateway_pins(paths)
    assert not moved, (
        f"the chart pins a central-gateway image the route list was not read at: {moved}. Read the "
        "route ids the delegate table is keyed on at that image's dag-tools commit, then update "
        "GATEWAY_ROUTES and GATEWAY_ROUTES_READ_AT in policy/sync/validate_policy.py together.")


@pytest.mark.parametrize("image", [
    {"digest": "sha256:" + "0" * 64},
    {"tag": "sha-0000000"},
], ids=["another digest", "a tag"])
def test_CONTROL_a_moved_pin_is_caught(tmp_path, image):
    p = tmp_path / "values-sandbox.yaml"
    p.write_text(yaml.safe_dump({"centralGateway": {"image": image}}), encoding="utf-8")
    assert _unread_gateway_pins([p]) == {"values-sandbox.yaml": image.get("digest") or f"tag:{image['tag']}"}


def test_the_read_at_record_is_a_full_commit_and_digest():
    rec = vp.GATEWAY_ROUTES_READ_AT
    assert len(rec["dag_tools"]) == 40 and int(rec["dag_tools"], 16) >= 0
    assert rec["central_gateway_digest"].startswith("sha256:") and len(rec["central_gateway_digest"]) == 71
