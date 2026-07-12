#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
RESULTS = OUTPUT / "results.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if not RESULTS.is_file():
    raise SystemExit("output/results.jsonl is missing")
rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
input_hash = sha256(ROOT / "INPUT_MANIFEST.json")
manifest = {
    "schema_version": "1.0",
    "results_file": "results.jsonl",
    "results_sha256": sha256(RESULTS),
    "row_count": len(rows),
    "input_manifest_hash": input_hash,
}
manifest_path = OUTPUT / "OUTPUT_MANIFEST.json"
atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
atomic_write(OUTPUT / "OUTPUT_MANIFEST.sha256", f"{sha256(manifest_path)}  OUTPUT_MANIFEST.json\n")
