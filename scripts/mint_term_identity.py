#!/usr/bin/env python3
"""Mint term identities for a vocabulary file: UUID v7, written `urn:uuid:<uuid>` (openddil ADR-0056 §1).

This is the generator that `policy/registry/lifecycle_status.yaml` and
`policy/classification/dimensions.yaml` name in their `generator:` key. ADR-0056 ruling 5: "Each
authority has one generator. The generator is recorded in the vocabulary file itself, at release."

It prints identities and writes nothing. A person adding a term pastes one into the file, once. An
identity is never re-minted for a term that has one: the identity is the term, and its label is an
attribute that may change.

Usage:  uv run python scripts/mint_term_identity.py [-n COUNT]
"""
from __future__ import annotations

import argparse
import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 §5.7: 48 bits of Unix milliseconds, version 7, 12 random bits, variant 10, 62 random bits.
    Python 3.12 has no `uuid.uuid7`."""
    ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = ((ms & (2**48 - 1)) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def mint() -> str:
    return f"urn:uuid:{uuid7()}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", "--count", type=int, default=1, help="how many identities to print (default 1)")
    args = ap.parse_args()
    if args.count < 1:
        ap.error("--count must be at least 1")
    for _ in range(args.count):
        print(mint())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
