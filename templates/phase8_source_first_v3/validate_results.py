#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from validation_core import validate_results


ROOT = Path(__file__).resolve().parents[1]
issues, stats = validate_results(ROOT)
print(json.dumps({"status": "PASS" if not issues else "FAIL", "issues": issues, **stats}, ensure_ascii=True, sort_keys=True))
raise SystemExit(0 if not issues else 1)
