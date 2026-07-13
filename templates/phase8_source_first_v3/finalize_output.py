#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

from validation_core import read_jsonl, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
RESULTS = OUTPUT / "results.jsonl"
MANIFEST = OUTPUT / "OUTPUT_MANIFEST.json"
CHECKSUM = OUTPUT / "OUTPUT_MANIFEST.sha256"


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


for stale in (MANIFEST, CHECKSUM):
    stale.unlink(missing_ok=True)
for script in ("verify_input_package.py", "validate_results.py"):
    completed = subprocess.run([sys.executable, str(ROOT / "input" / script)], cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(f"{script} failed; success manifest not created")
rows = read_jsonl(RESULTS)
claim_count = sum(len(row["claims"]) for row in rows)
manifest = {
    "schema_version": "3.0",
    "input_manifest_hash": sha256_file(ROOT / "INPUT_MANIFEST.json"),
    "results_file": "results.jsonl",
    "results_sha256": sha256_file(RESULTS),
    "source_unit_row_count": len(rows),
    "claim_count": claim_count,
    "input_package_validation": "PASS",
    "result_validation": "PASS",
}
atomic_write(MANIFEST, json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
atomic_write(CHECKSUM, f"{sha256_file(MANIFEST)}  OUTPUT_MANIFEST.json\n{sha256_file(RESULTS)}  results.jsonl\n")
print(json.dumps({"status": "PASS", "source_unit_row_count": len(rows), "claim_count": claim_count}, sort_keys=True))
