#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from validation_core import read_json, sha256_file, validate_results


def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = root / "output"
    manifest_path = output / "OUTPUT_MANIFEST.json"
    checksum_path = output / "OUTPUT_MANIFEST.sha256"
    manifest_path.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)
    results = output / "results.jsonl"
    allowed_before_finalize = {"results.jsonl"}
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    issues = []
    if actual != allowed_before_finalize:
        issues.append("output must contain exactly results.jsonl before finalization")
    semantic_issues, stats = validate_results(root, results)
    issues.extend(semantic_issues)
    if issues:
        print(json.dumps({"status": "FAIL", "issues": sorted(set(issues)), **stats}, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    input_manifest = read_json(root / "INPUT_MANIFEST.json")
    output_manifest = {
        "schema_version": input_manifest["schema_version"],
        "package_role": input_manifest["package_role"],
        "input_manifest_hash": sha256_file(root / "INPUT_MANIFEST.json"),
        "results_sha256": sha256_file(results),
        **stats,
        "status": "PASS",
    }
    atomic_write(manifest_path, json.dumps(output_manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    atomic_write(checksum_path, f"{sha256_file(manifest_path)}  OUTPUT_MANIFEST.json\n{sha256_file(results)}  results.jsonl\n")
    print(json.dumps(output_manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
