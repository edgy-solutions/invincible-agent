"""The door sets Content-Type from the kind it inferred and checks the magic.

pdf needs `%PDF-` in the first KiB; xml needs the XML declaration. A drop whose declared kind
and bytes disagree is 400 `kind_mismatch` BEFORE any write. cad has no magic check.
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("can_drop_open")

XML = b'<?xml version="1.0"?><a/>'
DECL = "<?xml version=\"1.0\"?>"


@pytest.mark.parametrize("head,want", [
    (b"%PDF-1.7\n...", "pdf"),
    (b"j" * 200 + b"%PDF-1.4", "pdf"),
    (b"j" * 1100 + b"%PDF-1.4", None),
    (XML, "xml"),
    (b"\xef\xbb\xbf \r\n\t" + XML, "xml"),
    (b"\xff\xfe" + DECL.encode("utf-16-le"), "xml"),
    (b"\xfe\xff" + DECL.encode("utf-16-be"), "xml"),
    (b"hello", None),
    (b"<root/>", None),
])
def test_the_sniff(head, want):
    assert gateway._sniff_file_kind(head) == want


class _S3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


@pytest.fixture
def rig(monkeypatch):
    s3, node, rows, looked = _S3(), [], [], []
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: s3)
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: node.append(kw))
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: looked.append(sha))
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: rows.append(kw) or {"id": kw["ingest_id"], "status": "received"})
    reg = type("Reg", (), {"domain": "sustainment", "branch": "document", "kind": "pcn"})()
    monkeypatch.setattr(ck, "by_kind", lambda k: reg if k == "pcn" else None)
    user = type("U", (), {"authz_id": "alice@example.com", "id": "alice@example.com",
                          "sub": "alice@example.com", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    yield type("Rig", (), {"s3": s3, "node": node, "rows": rows, "looked": looked})
    gateway.app.dependency_overrides.clear()


def _drop(kind, name, data):
    with TestClient(gateway.app) as c:
        return c.post("/ingest", files={"file": (name, data, "application/octet-stream")},
                      data={"kind": kind, "on_behalf_of": "alice@example.com",
                            "content_kind": "pcn"})


def _doc_put(rig):
    puts = [p for p in rig.s3.puts if not p["Key"].endswith("manifest.json")]
    assert len(puts) == 1, rig.s3.puts
    return puts[0]


def test_a_pdf_drop_of_xml_bytes_is_refused_and_nothing_is_written(rig):
    r = _drop("pdf", "notice.pdf", XML)
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["error"] == "kind_mismatch" and d["declared_kind"] == "pdf"
    assert d["sniffed_kind"] == "xml" and d["filename"] == "notice.pdf"
    assert rig.s3.puts == [] and rig.rows == [] and rig.node == [] and rig.looked == []


def test_an_xml_drop_of_hello_is_refused_with_no_sniffed_kind(rig):
    r = _drop("xml", "n.xml", b"hello")
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["error"] == "kind_mismatch" and d["sniffed_kind"] is None
    assert rig.s3.puts == [] and rig.rows == []


def test_a_good_pdf_is_accepted_with_its_content_type(rig):
    r = _drop("pdf", "n.pdf", b"%PDF-1.7\nbody")
    assert r.status_code == 200, r.text
    assert _doc_put(rig)["ContentType"] == "application/pdf"


def test_a_good_xml_is_accepted_with_its_content_type(rig):
    r = _drop("xml", "n.xml", XML)
    assert r.status_code == 200, r.text
    assert _doc_put(rig)["ContentType"] == "application/xml"


def test_a_cad_drop_of_arbitrary_bytes_is_accepted_as_octet_stream(rig):
    r = _drop("cad", "n.step", b"anything at all")
    assert r.status_code == 200, r.text
    assert _doc_put(rig)["ContentType"] == "application/octet-stream"
