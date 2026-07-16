from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHANGED_PRODUCTION_SOURCES = (
    ROOT / "review_writer/delivery/finished_review.py",
    ROOT / "scripts/delivery/run_finished_mini_review.py",
    ROOT / "skills/review-export-docx/scripts/md2docx.py",
)


class FreshSourceSyntaxTests(unittest.TestCase):
    def test_smoke_runs_the_fresh_source_syntax_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("/usr/bin/python3 tests/test_fresh_source_syntax.py", makefile)

    def test_changed_production_sources_parse_from_source(self) -> None:
        failures: list[str] = []
        for source_path in CHANGED_PRODUCTION_SOURCES:
            with self.subTest(source_path=source_path):
                try:
                    ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
                except SyntaxError as error:
                    failures.append(f"{source_path}: {error.msg} (line {error.lineno})")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_system_python_310_parses_compiles_and_imports_delivery_sources(self) -> None:
        system_python = Path("/usr/bin/python3")
        self.assertTrue(system_python.is_file(), "/usr/bin/python3 is required for the delivery syntax gate")
        ast_script = """
import ast
from pathlib import Path
for raw in [
    'review_writer/delivery/finished_review.py',
    'scripts/delivery/run_finished_mini_review.py',
    'skills/review-export-docx/scripts/md2docx.py',
]:
    path = Path(raw)
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
"""
        with tempfile.TemporaryDirectory(prefix="review-writer-syntax-") as pycache:
            environment = {**os.environ, "PYTHONPYCACHEPREFIX": pycache}
            subprocess.run([str(system_python), "-c", ast_script], cwd=ROOT, env=environment, check=True)
            subprocess.run(
                [
                    str(system_python),
                    "-m",
                    "py_compile",
                    *(str(path.relative_to(ROOT)) for path in CHANGED_PRODUCTION_SOURCES),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
            )
            subprocess.run(
                [str(system_python), "-c", "import review_writer.delivery.finished_review; import runpy; runpy.run_path('scripts/delivery/run_finished_mini_review.py', run_name='delivery_runner')"],
                cwd=ROOT,
                env={**environment, "PYTHONPATH": str(ROOT)},
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
