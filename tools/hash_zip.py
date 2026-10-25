#!/usr/bin/env python3
"""Calcula tamanho e SHA-256 de um .zip de tradução e imprime o trecho pronto
para colar no manifest.json.

    python tools/hash_zip.py P5R_v2.zip --id v2 --label V2 --version 2.0 --url https://github.com/.../P5R_v2.zip
"""
import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip")
    ap.add_argument("--id", default="v1")
    ap.add_argument("--label", default="")
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--url", default="")
    ap.add_argument("--notes", default="")
    a = ap.parse_args()

    p = Path(a.zip)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    entry = {
        "id": a.id,
        "label": a.label or a.id.upper(),
        "version": a.version,
        "url": a.url,
        "sha256": h.hexdigest(),
        "size": p.stat().st_size,
        "notes": a.notes,
    }
    print(json.dumps(entry, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
