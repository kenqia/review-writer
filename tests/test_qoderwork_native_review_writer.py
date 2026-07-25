#!/usr/bin/env python3
"""Focused, provider-free checks for the QoderWork CN native review writer slice."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "qoderwork" / "plugins" / "research-review-writer"
BUILDER = ROOT / "scripts" / "build_qoderwork_plugin_zip.py"
SERVER = ROOT / "view" / "serve_review_dashboard.py"
FIXTURE = ROOT / "tests" / "fixtures" / "qoderwork_native_review"

EXPECTED_INVENTORY = (
    ".qoder-plugin/plugin.json",
    "agents/ADVERSARIAL_EVIDENCE_REVIEWER.md",
    "agents/DISCOVERY_ACQUISITION_PLANNER.md",
    "agents/PER_STUDY_EVIDENCE_EXTRACTOR.md",
    "agents/QUALITY_RELEASE_REVIEWER.md",
    "agents/REVIEW_BRIEFING_AGENT.md",
    "agents/SYNTHESIS_MANUSCRIPT_WRITER.md",
    "skills/research-review-writer/SKILL.md",
)
MANIFEST_KEYS = {"name", "displayName", "version", "description", "descriptionZh", "author", "keywords", "skills"}


class NativeReviewWriterPluginTests(unittest.TestCase):
    def test_plugin_manifest_inventory_and_runtime_boundaries(self) -> None:
        manifest = json.loads((PLUGIN / ".qoder-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(MANIFEST_KEYS, set(manifest))
        self.assertEqual("research-review-writer", manifest["name"])
        self.assertEqual("科研综述专家", manifest["displayName"])
        self.assertTrue(manifest["description"].isascii())
        self.assertIn("科研综述", manifest["descriptionZh"])
        self.assertEqual({"name": "review-writer"}, manifest["author"])
        self.assertEqual(["skills/research-review-writer"], manifest["skills"])
        inventory = tuple(sorted(path.relative_to(PLUGIN).as_posix() for path in PLUGIN.rglob("*") if path.is_file()))
        self.assertEqual(EXPECTED_INVENTORY, inventory)
        content = "\n".join(path.read_text(encoding="utf-8") for path in PLUGIN.rglob("*.md"))
        lowered = content.casefold()
        for forbidden in ("openai", "dashscope", "requests.", "http://", "https://", "fallback model", "provider api", "/home/", "allene", "m2"):
            self.assertNotIn(forbidden, lowered)
        self.assertIn("QoderWork", content)
        self.assertIn("写作工作台", content)
        self.assertIn("人工", content)

    def test_plugin_zip_is_deterministic_and_exactly_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first, second = Path(temp_dir) / "first.zip", Path(temp_dir) / "second.zip"
            for output in (first, second):
                subprocess.run([sys.executable, str(BUILDER), "--plugin-dir", str(PLUGIN), "--output", output.name], cwd=temp_dir, check=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(EXPECTED_INVENTORY, tuple(sorted(archive.namelist())))
                self.assertFalse(any(name.startswith((".env", ".git", "__pycache__")) or name.endswith(".pdf") for name in archive.namelist()))

    def test_plugin_builder_rejects_absolute_or_unrelated_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unrelated = Path(temp_dir) / "unrelated.zip"
            unrelated.write_bytes(b"not a plugin archive")
            absolute = Path(temp_dir) / "absolute.zip"
            for output in (unrelated.name, str(absolute)):
                result = subprocess.run(
                    [sys.executable, str(BUILDER), "--plugin-dir", str(PLUGIN), "--output", output],
                    cwd=temp_dir,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode)
            self.assertEqual(b"not a plugin archive", unrelated.read_bytes())


class NativeReviewWriterDashboardTests(unittest.TestCase):
    @staticmethod
    def _request(dashboard, review_root: Path, raw_request: bytes) -> tuple[int, dict[str, str], bytes]:
        class FakeSocket:
            def __init__(self, incoming: bytes) -> None:
                self.input, self.output = io.BytesIO(incoming), io.BytesIO()

            def makefile(self, mode: str, *args, **kwargs):
                return self.input if "r" in mode else self.output

            def sendall(self, data: bytes) -> None:
                self.output.write(data)

            def close(self) -> None:
                pass

        dashboard.DashboardHandler.review_root = review_root
        socket = FakeSocket(raw_request)
        dashboard.DashboardHandler(socket, ("127.0.0.1", 0), object())
        head, body = socket.output.getvalue().split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1").split("\r\n")
        headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
        return int(lines[0].split()[1]), headers, body

    def test_review_home_persists_state_and_exports_docx(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard
        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            shutil.copytree(FIXTURE, review_root)
            projects = dashboard.list_review_projects(review_root)
            self.assertEqual("synthetic-review", projects[0]["project_id"])
            status, headers, _ = self._request(dashboard, review_root, b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            self.assertEqual(302, status)
            self.assertEqual("/review", headers["Location"])
            status, _, body = self._request(dashboard, review_root, b"GET /api/project/synthetic-review/review-state HTTP/1.1\r\nHost: localhost\r\n\r\n")
            self.assertEqual(200, status)
            self.assertEqual("evidence_review", json.loads(body)["current_stage"])
            state = dashboard.project_review_state_payload(review_root, "synthetic-review")
            self.assertEqual("evidence_review", state["current_stage"])
            self.assertEqual(2, state["counts"]["evidence"])
            updated = {**state, "current_stage": "drafting", "status": "in_progress", "blockers": []}
            dashboard.write_project_review_state(review_root, "synthetic-review", updated)
            self.assertEqual("drafting", dashboard.project_review_state_payload(review_root, "synthetic-review")["current_stage"])
            request_body = json.dumps(updated, ensure_ascii=False).encode("utf-8")
            request = b"PUT /api/project/synthetic-review/review-state HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: " + str(len(request_body)).encode() + b"\r\n\r\n" + request_body
            status, _, body = self._request(dashboard, review_root, request)
            self.assertEqual(200, status)
            self.assertTrue(json.loads(body)["ok"])
            status, _, body = self._request(dashboard, review_root, b"POST /api/project/synthetic-review/export-docx HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n")
            self.assertEqual(200, status)
            self.assertTrue(json.loads(body)["ok"])
            self.assertTrue((review_root / "review-projects" / "synthetic-review" / "05_final_audit" / "final_draft.docx").exists())
            self.assertIn('self.send_header("Location", "/review")', SERVER.read_text(encoding="utf-8"))
            self.assertIn('fetch(`/api/project/${encodeURIComponent(projectId)}/review-state`)', (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8"))

    def test_project_id_traversal_is_rejected_for_get_put_and_export(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard
        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            shutil.copytree(FIXTURE, review_root)
            for value in ("", ".", "..", "nested/path", "nested\\path"):
                with self.assertRaises(ValueError):
                    dashboard.project_dir(review_root, value)
            bad_path = "/api/project/%2e%2e/review-state"
            for encoded_id in ("%2e%2e", "%2e%2e%2fescape", "%2e%2e%5cescape"):
                status, _, _ = self._request(dashboard, review_root, f"GET /api/project/{encoded_id}/review-state HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
                self.assertEqual(400, status)
            bad_state = {
                "project_id": "..", "brief": {}, "current_stage": "drafting", "status": "in_progress", "blockers": [],
                "counts": {"sources": 0, "evidence": 0, "claims": 0},
            }
            request_body = json.dumps(bad_state).encode()
            request = b"PUT " + bad_path.encode() + b" HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: " + str(len(request_body)).encode() + b"\r\n\r\n" + request_body
            status, _, _ = self._request(dashboard, review_root, request)
            self.assertEqual(400, status)
            status, _, _ = self._request(dashboard, review_root, b"POST /api/project/%2e%2e/export-docx HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n")
            self.assertEqual(400, status)
            status, _, _ = self._request(dashboard, review_root, b"GET /api/discovery/%2e%2e HTTP/1.1\r\nHost: localhost\r\n\r\n")
            self.assertEqual(400, status)
            status, _, _ = self._request(dashboard, review_root, b"PUT /api/discovery/%2e%2e HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
            self.assertEqual(400, status)
            self.assertFalse((review_root / "00_brief" / "review_state.json").exists())
            self.assertFalse((review_root / "00_discovery" / "combined_results_by_keyword.json").exists())


if __name__ == "__main__":
    unittest.main()
