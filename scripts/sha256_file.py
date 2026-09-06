#!/usr/bin/env python3
"""Chunked SHA256. Same digest as hashlib.sha256(path.read_bytes()), no full-file RAM spike."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path: Path, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def self_test() -> int:
    payload = b"omlx-recipe-sha256-self-test\n" * 17
    fd, name = tempfile.mkstemp(prefix="sha256self")
    os.close(fd)
    p = Path(name)
    try:
        p.write_bytes(payload)
        got = sha256_file(p, chunk=8)
        want = hashlib.sha256(payload).hexdigest()
        if got != want:
            print("FAIL: %s != %s" % (got, want), file=sys.stderr)
            return 1
    finally:
        p.unlink(missing_ok=True)
    print("PASS: sha256_file chunked matches hashlib")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        print("usage: python3 scripts/sha256_file.py PATH | --self-test", file=sys.stderr)
        raise SystemExit(2)
    print(sha256_file(Path(sys.argv[1])))
