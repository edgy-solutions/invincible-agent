"""git's ssh-signature format (OpenSSH PROTOCOL.sshsig), ed25519 only.

No shell-out: ``cryptography`` does the key work, and the blobs are packed here.

    signed blob    = "SSHSIG" string(namespace) string(reserved) string(hash_alg) string(H(data))
    signature blob = "SSHSIG" uint32(1) string(pubkey) string(namespace) string(reserved)
                     string(hash_alg) string(string("ssh-ed25519") string(sig))

A *string* is a big-endian uint32 length followed by the bytes. ``ssh-keygen -Y verify`` and
``git verify-commit`` (``gpg.format=ssh``) read exactly this.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_MAGIC = b"SSHSIG"
_KEYTYPE = b"ssh-ed25519"
_HASH = b"sha512"
_BEGIN = "-----BEGIN SSH SIGNATURE-----"
_END = "-----END SSH SIGNATURE-----"


def _string(b: bytes) -> bytes:
    return struct.pack(">I", len(b)) + b


def _read_string(buf: bytes, off: int) -> tuple[bytes, int]:
    if off + 4 > len(buf):
        raise ValueError("truncated sshsig blob")
    (n,) = struct.unpack_from(">I", buf, off)
    off += 4
    if off + n > len(buf):
        raise ValueError("truncated sshsig blob")
    return buf[off : off + n], off + n


def _pubkey_blob(raw_public: bytes) -> bytes:
    return _string(_KEYTYPE) + _string(raw_public)


def _signed_blob(data: bytes, namespace: str) -> bytes:
    return (
        _MAGIC
        + _string(namespace.encode())
        + _string(b"")
        + _string(_HASH)
        + _string(hashlib.sha512(data).digest())
    )


def _public_blob_from_openssh(public_openssh: str) -> bytes:
    parts = public_openssh.split()
    if len(parts) < 2 or parts[0] != _KEYTYPE.decode():
        raise ValueError("not an ssh-ed25519 public key")
    return base64.b64decode(parts[1])


@dataclass(frozen=True)
class Signer:
    _key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> "Signer":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_openssh_private(cls, data: bytes) -> "Signer":
        key = serialization.load_ssh_private_key(data, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("only ed25519 keys are supported")
        return cls(key)

    def private_openssh(self) -> bytes:
        return self._key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )

    def _raw_public(self) -> bytes:
        return self._key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    def public_openssh(self) -> str:
        blob = _pubkey_blob(self._raw_public())
        return f"{_KEYTYPE.decode()} {base64.b64encode(blob).decode()}"

    def sign(self, data: bytes, namespace: str = "git") -> str:
        sig = self._key.sign(_signed_blob(data, namespace))
        blob = (
            _MAGIC
            + struct.pack(">I", 1)
            + _string(_pubkey_blob(self._raw_public()))
            + _string(namespace.encode())
            + _string(b"")
            + _string(_HASH)
            + _string(_string(_KEYTYPE) + _string(sig))
        )
        b64 = base64.b64encode(blob).decode()
        lines = [b64[i : i + 76] for i in range(0, len(b64), 76)]
        return "\n".join([_BEGIN, *lines, _END]) + "\n"


def verify(data: bytes, armored: str, public_openssh: str, namespace: str = "git") -> bool:
    """True only if ``armored`` is a valid signature of ``data`` by exactly this key and namespace."""
    try:
        body = [ln.strip() for ln in armored.strip().splitlines()]
        if not body or body[0] != _BEGIN or body[-1] != _END:
            return False
        blob = base64.b64decode("".join(body[1:-1]), validate=True)
        if blob[:6] != _MAGIC:
            return False
        (version,) = struct.unpack_from(">I", blob, 6)
        if version != 1:
            return False
        off = 10
        pub, off = _read_string(blob, off)
        ns, off = _read_string(blob, off)
        _reserved, off = _read_string(blob, off)
        alg, off = _read_string(blob, off)
        sigblob, off = _read_string(blob, off)
        if off != len(blob):
            return False
        if pub != _public_blob_from_openssh(public_openssh):
            return False
        if ns != namespace.encode() or alg != _HASH:
            return False
        kt, so = _read_string(sigblob, 0)
        sig, so = _read_string(sigblob, so)
        if kt != _KEYTYPE or so != len(sigblob):
            return False
        _kt, po = _read_string(pub, 0)
        raw, _ = _read_string(pub, po)
        Ed25519PublicKey.from_public_bytes(raw).verify(sig, _signed_blob(data, namespace))
        return True
    except (InvalidSignature, ValueError, binascii.Error, struct.error):
        return False
