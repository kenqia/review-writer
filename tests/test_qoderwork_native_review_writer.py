#!/usr/bin/env python3
"""Focused, provider-free checks for the QoderWork CN native review writer slice."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote


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
EXPECTED_AGENT_TOOLS = {
    "ADVERSARIAL_EVIDENCE_REVIEWER": ("Read", "Write"),
    "DISCOVERY_ACQUISITION_PLANNER": ("Read", "Write", "Bash"),
    "PER_STUDY_EVIDENCE_EXTRACTOR": ("Read", "Write"),
    "QUALITY_RELEASE_REVIEWER": ("Read", "Write", "Bash"),
    "REVIEW_BRIEFING_AGENT": ("Read", "Write"),
    "SYNTHESIS_MANUSCRIPT_WRITER": ("Read", "Write"),
}
ALLOWED_MAIN_COMMANDS = {
    "scripts/acquisition/acquire_public_corpus.py",
    "scripts/discovery/discover_scholarly_corpus.py",
    "scripts/evidence/assemble_evidence_candidate_from_atoms.py",
    "scripts/evidence/build_page_atom_catalog.py",
    "scripts/evidence/build_pdf_text_layers.py",
    "scripts/evidence/validate_evidence_candidate.py",
    "scripts/run_vertical_review.py",
    "scripts/validators/validate_review_quality.py",
    "skills/review-export-docx/scripts/md2docx.py",
    "skills/review-final-audit-release/scripts/final_audit_scan.py",
    "view/serve_review_dashboard.py",
}

VISIBLE_EVIDENCE_CARD_FIELDS = {
    "study_id",
    "citation",
    "activation_mode",
    "reaction_class",
    "observations",
    "limitations",
    "claims",
    "source_excerpt",
    "locators",
}
VISIBLE_RISK_TARGET_FIELDS = {
    "target_id",
    "claim_text",
    "risk_categories",
    "evidence_summary",
    "source_excerpt",
    "source_label",
    "page",
    "proposed_action",
    "existing_decision",
    "decision_token",
}


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self.parts)


class NativeReviewWriterPluginTests(unittest.TestCase):
    def test_plugin_manifest_inventory_and_runtime_boundaries(self) -> None:
        manifest = json.loads((PLUGIN / ".qoder-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(MANIFEST_KEYS, set(manifest))
        self.assertEqual("research-review-writer", manifest["name"])
        self.assertEqual("0.2.0", manifest["version"])
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

    def test_plugin_exposes_exactly_three_researcher_interactions(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("研究者只进行以下三次 interaction", skill)
        self.assertEqual(
            ["1. Review Brief", "2. Scientific Risk Packet", "3. Final Review"],
            re.findall(r"^## ([1-9]\. .+)$", skill, flags=re.MULTILINE),
        )
        for forbidden in (
            "复制 Prompt",
            "编辑 JSON",
            "git ",
            "worktree",
            "逐篇确认",
            "七个检查点",
            "七检查点",
            "选择 sub-Agent",
            "打开 output folder",
        ):
            self.assertNotIn(forbidden.casefold(), skill.casefold())

    def test_main_skill_orders_automatic_work_between_three_interactions(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")
        markers = (
            "## 1. Review Brief",
            "### Automatic corpus/evidence",
            "## 2. Scientific Risk Packet",
            "### Automatic Draft/Final",
            "## 3. Final Review",
        )
        for marker in markers:
            self.assertIn(marker, skill)
        positions = [skill.index(marker) for marker in markers]
        self.assertEqual(sorted(positions), positions)

        for required in (
            "只询问缺失的 material scope",
            "本地 product command",
            "review_state.json",
            "localhost dashboard",
            "brief URL",
            "只等待一次确认",
            "bounded scholarly-search-plan.v1",
            "三篇 calibration",
            "credits forecast",
            "4–6 篇 batch",
            "deterministic registration",
            "exception_queue.json",
            "所有可处理研究完成后",
            "去重",
            "approve / reword / exclude / unresolved",
            "review_target_digest",
            "writer_packet.json",
            "APPROVED",
            "authoritative manuscript",
            "manuscript_lineage.json",
            "DOCX",
            "最终确认",
            "job-level Qoder egress/credits 授权",
            "paid run",
        ):
            self.assertIn(required, skill)

        command_refs = set(re.findall(r"`((?:scripts|skills|view)/[^`\s]+\.py)`", skill))
        self.assertTrue(command_refs)
        self.assertLessEqual(command_refs, ALLOWED_MAIN_COMMANDS)
        self.assertIn("scripts/run_vertical_review.py", command_refs)
        self.assertIn("view/serve_review_dashboard.py", command_refs)

    def test_agent_contracts_and_tool_permissions_are_exact(self) -> None:
        contracts = {
            "REVIEW_BRIEFING_AGENT": (
                "Input: topic/context",
                "Output: human-readable brief fields only",
            ),
            "DISCOVERY_ACQUISITION_PLANNER": (
                "Input: confirmed brief + candidate pool",
                "Output: scholarly-search-plan.v1 + screening decisions + acquisition rows",
            ),
            "PER_STUDY_EVIDENCE_EXTRACTOR": (
                "Input: one evidence_atom_catalog.v1 + semantic schema",
                "Output: evidence-atom-semantic-decision.v1 only",
            ),
            "ADVERSARIAL_EVIDENCE_REVIEWER": (
                "Input: one assembled candidate + selected atoms",
                "Output: SUPPORT | REJECT | AMBIGUOUS per target + concise reason",
            ),
            "SYNTHESIS_MANUSCRIPT_WRITER": (
                "Input: writer_packet.json only",
                "Output: section drafts + authoritative manuscript + manuscript_lineage.json",
            ),
            "QUALITY_RELEASE_REVIEWER": (
                "Input: authoritative manuscript + lineage + quality report",
                "Output: semantic release verdict",
            ),
        }
        actual_names = set()
        for path in (PLUGIN / "agents").glob("*.md"):
            content = path.read_text(encoding="utf-8")
            name_match = re.search(r"^name:\s*(\S+)\s*$", content, flags=re.MULTILINE)
            tools_match = re.search(r"^tools:\s*(.+?)\s*$", content, flags=re.MULTILINE)
            self.assertIsNotNone(name_match, path.name)
            self.assertIsNotNone(tools_match, path.name)
            name = name_match.group(1)
            actual_names.add(name)
            tools = tuple(value.strip() for value in tools_match.group(1).split(","))
            self.assertEqual(EXPECTED_AGENT_TOOLS[name], tools, name)
            for required in contracts[name]:
                self.assertIn(required, content)
        self.assertEqual(set(EXPECTED_AGENT_TOOLS), actual_names)

        for name in (
            "ADVERSARIAL_EVIDENCE_REVIEWER",
            "SYNTHESIS_MANUSCRIPT_WRITER",
            "QUALITY_RELEASE_REVIEWER",
        ):
            content = (PLUGIN / "agents" / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("fresh delegation contract", content)
            self.assertIn("不声称底层平台保证独立 context", content)

        discovery = (PLUGIN / "agents" / "DISCOVERY_ACQUISITION_PLANNER.md").read_text(encoding="utf-8")
        quality = (PLUGIN / "agents" / "QUALITY_RELEASE_REVIEWER.md").read_text(encoding="utf-8")
        self.assertIn("scripts/discovery/discover_scholarly_corpus.py", discovery)
        self.assertIn("scripts/acquisition/acquire_public_corpus.py", discovery)
        self.assertIn("scripts/validators/validate_review_quality.py", quality)
        self.assertIn("skills/review-export-docx/scripts/md2docx.py", quality)

    def test_extractor_selects_existing_atoms_and_cannot_author_mechanical_fields(self) -> None:
        extractor = (PLUGIN / "agents" / "PER_STUDY_EVIDENCE_EXTRACTOR.md").read_text(encoding="utf-8")
        self.assertIn("Select existing atom_id only", extractor)
        self.assertIn(
            "Do not write source_id, page, exact_quote, depiction, coverage, or self_check fields",
            extractor,
        )

    def test_writer_reads_only_approved_writer_packet(self) -> None:
        writer = (PLUGIN / "agents" / "SYNTHESIS_MANUSCRIPT_WRITER.md").read_text(encoding="utf-8")
        self.assertIn("Input: writer_packet.json only", writer)
        self.assertIn("只读取 decision=APPROVED", writer)
        self.assertIn("Do not read full PDF files", writer)
        self.assertNotIn("完整 PDF", writer)

    def test_agents_enforce_monotonic_claim_decisions(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")
        writer = (PLUGIN / "agents" / "SYNTHESIS_MANUSCRIPT_WRITER.md").read_text(encoding="utf-8")
        reviewer = (PLUGIN / "agents" / "QUALITY_RELEASE_REVIEWER.md").read_text(encoding="utf-8")

        self.assertIn("BLOCKED 决定具有单调性", skill)
        self.assertIn("不得用 hedging、改写或模型复审重新放行", writer)
        self.assertIn("不得覆盖或降级上游 BLOCKED 决定", reviewer)

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
    def _copy_fixture(destination: Path) -> Path:
        review_root = destination / "review-root"
        shutil.copytree(FIXTURE, review_root)
        return review_root

    @staticmethod
    def _project_file_bytes(review_root: Path) -> dict[str, bytes]:
        project = review_root / "review-projects" / "synthetic-review"
        return {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }

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
            export_result = {
                "ok": True,
                "filename": "final_draft.docx",
                "size": 1,
                "release_status": "AI_REVIEWED_BENCHMARK",
            }
            with patch.object(dashboard, "export_project_docx", return_value=export_result) as export:
                status, _, body = self._request(dashboard, review_root, b"POST /api/project/synthetic-review/export-docx HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n")
            self.assertEqual(200, status)
            self.assertEqual(export_result, json.loads(body))
            export.assert_called_once_with(review_root, "synthetic-review")
            self.assertIn('self.send_header("Location", "/review")', SERVER.read_text(encoding="utf-8"))
            review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
            self.assertIn('fetch(`/api/project/${encodeURIComponent(projectId)}/review-state`)', review_html)
            self.assertIn('<link rel="icon" href="data:,">', review_html)

    def test_draft_route_exposes_sections_and_rejects_whole_manuscript_payload(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        manuscript = (
            "# Synthetic Review\n\nIntro.\n\n"
            "## Results\n\nEvidence-backed text [1].\n\n"
            "## References\n\n[1] Synthetic reference.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            manuscript_path = project / "04_first_draft" / "first_draft.md"
            manuscript_path.write_text(manuscript, encoding="utf-8")
            before = self._project_file_bytes(review_root)

            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/draft HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            payload = json.loads(body)
            self.assertEqual(["synthetic-review", "results", "references"], [row["id"] for row in payload["sections"]])
            self.assertRegex(payload["manuscript_version"], r"^[0-9a-f]{64}$")
            payload["sections"][1]["body"] = "Revised evidence-backed text [1]."
            request_body = json.dumps({"sections": payload["sections"]}).encode("utf-8")
            request = (
                b"PUT /api/project/synthetic-review/draft HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(request_body)).encode()
                + b"\r\n\r\n"
                + request_body
            )
            status, _, response = self._request(dashboard, review_root, request)
            self.assertEqual(400, status)
            self.assertIn(b"section_id", response)
            self.assertEqual(before, self._project_file_bytes(review_root))

    def test_draft_get_and_put_reject_symlinked_stage_without_touching_outside(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        manuscript = (
            "# Synthetic Review\n\nIntro.\n\n"
            "## Results\n\nEvidence-backed text [1].\n\n"
            "## References\n\n[1] Synthetic reference.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            review_root = self._copy_fixture(temp)
            project = review_root / "review-projects" / "synthetic-review"
            stage = project / "04_first_draft"
            (stage / "first_draft.md").write_text(manuscript, encoding="utf-8")
            draft = dashboard.project_draft_payload(review_root, "synthetic-review")
            edit = {
                "section_id": "results",
                "body": "This write must not reach the outside target [1].",
                "manuscript_version": draft["manuscript_version"],
            }

            outside = temp / "outside-stage"
            stage.rename(outside)
            stage.symlink_to(outside, target_is_directory=True)
            before = {
                path.relative_to(outside).as_posix(): path.read_bytes()
                for path in outside.rglob("*")
                if path.is_file()
            }

            get_status, _, _ = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/draft HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(400, get_status)

            request_body = json.dumps(edit).encode("utf-8")
            request = (
                b"PUT /api/project/synthetic-review/draft HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(request_body)).encode()
                + b"\r\n\r\n"
                + request_body
            )
            put_status, _, _ = self._request(dashboard, review_root, request)
            self.assertEqual(400, put_status)
            after = {
                path.relative_to(outside).as_posix(): path.read_bytes()
                for path in outside.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_stale_release_api_and_guessed_docx_download_fail_closed(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            manuscript_path = project / "04_first_draft" / "first_draft.md"
            snapshot_path = project / "05_final_audit" / "final_draft.md"
            docx_path = project / "05_final_audit" / "final_draft.docx"
            quality_path = project / "05_final_audit" / "quality_report.json"
            snapshot_path.write_bytes(manuscript_path.read_bytes())
            docx_path.write_bytes(b"current-synthetic-docx")
            valid_report = {
                "release_status": "AI_REVIEWED_BENCHMARK",
                "manuscript_sha256": hashlib.sha256(manuscript_path.read_bytes()).hexdigest(),
                "docx_sha256": hashlib.sha256(docx_path.read_bytes()).hexdigest(),
            }
            quality_path.write_text(json.dumps(valid_report) + "\n", encoding="utf-8")

            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/final HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            current = json.loads(body)
            self.assertTrue(current["final_draft_docx_exists"])
            self.assertEqual(
                "review-projects/synthetic-review/05_final_audit/final_draft.docx",
                current["final_draft_docx_path"],
            )
            download = f"GET /file?path={quote(current['final_draft_docx_path'], safe='')} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            status, _, body = self._request(dashboard, review_root, download)
            self.assertEqual(200, status)
            self.assertEqual(b"current-synthetic-docx", body)

            docx_path.write_bytes(b"tampered-docx-replacement")
            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/final HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            tampered = json.loads(body)
            self.assertFalse(tampered["release_snapshot"]["integrity_valid"])
            self.assertFalse(tampered["final_draft_docx_exists"])
            status, _, _ = self._request(dashboard, review_root, download)
            self.assertEqual(403, status)

            docx_path.write_bytes(b"current-synthetic-docx")
            for name, report in (
                ("missing report", None),
                ("malformed report", []),
                ("missing manuscript hash", {"docx_sha256": valid_report["docx_sha256"]}),
                ("missing docx hash", {"manuscript_sha256": valid_report["manuscript_sha256"]}),
            ):
                with self.subTest(name=name):
                    if report is None:
                        quality_path.unlink(missing_ok=True)
                    else:
                        quality_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
                    status, _, body = self._request(
                        dashboard,
                        review_root,
                        b"GET /api/project/synthetic-review/final HTTP/1.1\r\nHost: localhost\r\n\r\n",
                    )
                    self.assertEqual(200, status)
                    unavailable = json.loads(body)
                    self.assertFalse(unavailable["release_snapshot"]["integrity_valid"])
                    self.assertFalse(unavailable["final_draft_docx_exists"])
                    status, _, _ = self._request(dashboard, review_root, download)
                    self.assertEqual(403, status)

            quality_path.write_text(json.dumps(valid_report) + "\n", encoding="utf-8")
            manuscript_path.write_bytes(manuscript_path.read_bytes() + b"\nScientist edit.\n")
            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/final HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            stale = json.loads(body)
            self.assertFalse(stale["release_snapshot"]["docx_exists"])
            self.assertFalse(stale["final_draft_docx_exists"])
            self.assertEqual("", stale["final_draft_docx_path"])

            status, _, _ = self._request(dashboard, review_root, download)
            self.assertEqual(403, status)
            ordinary = f"GET /file?path={quote(str(manuscript_path), safe='')} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            status, _, body = self._request(dashboard, review_root, ordinary)
            self.assertEqual(200, status)
            self.assertEqual(manuscript_path.read_bytes(), body)

    def test_file_route_rejects_symlink_alias_to_stale_release_docx(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            manuscript_path = project / "04_first_draft" / "first_draft.md"
            snapshot_path = project / "05_final_audit" / "final_draft.md"
            docx_path = project / "05_final_audit" / "final_draft.docx"
            quality_path = project / "05_final_audit" / "quality_report.json"
            snapshot_path.write_bytes(manuscript_path.read_bytes())
            docx_path.write_bytes(b"current-synthetic-docx")
            quality_path.write_text(
                json.dumps(
                    {
                        "release_status": "AI_REVIEWED_BENCHMARK",
                        "manuscript_sha256": hashlib.sha256(manuscript_path.read_bytes()).hexdigest(),
                        "docx_sha256": hashlib.sha256(docx_path.read_bytes()).hexdigest(),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            direct = f"GET /file?path={quote(str(docx_path), safe='')} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            status, _, body = self._request(dashboard, review_root, direct)
            self.assertEqual(200, status)
            self.assertEqual(b"current-synthetic-docx", body)

            ordinary_path = project / "assets" / "ordinary.txt"
            ordinary_path.parent.mkdir(parents=True, exist_ok=True)
            ordinary_path.write_bytes(b"ordinary-project-asset")
            ordinary = f"GET /file?path={quote(str(ordinary_path), safe='')} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            status, _, body = self._request(dashboard, review_root, ordinary)
            self.assertEqual(200, status)
            self.assertEqual(b"ordinary-project-asset", body)

            alias_path = project / "alias.docx"
            alias_path.symlink_to(docx_path)
            docx_path.write_bytes(b"tampered-stale-docx")
            alias = f"GET /file?path={quote(str(alias_path), safe='')} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            status, _, _ = self._request(dashboard, review_root, alias)
            self.assertEqual(403, status)

    def test_review_projects_symlink_escape_rejects_api_read_write_without_outside_changes(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            review_root = temp / "trusted-review-root"
            review_root.mkdir()
            outside = temp / "outside-projects"
            shutil.copytree(FIXTURE / "review-projects", outside)
            (review_root / "review-projects").symlink_to(outside, target_is_directory=True)
            before = {
                path.relative_to(outside).as_posix(): path.read_bytes()
                for path in outside.rglob("*")
                if path.is_file()
            }

            status, _, _ = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/draft HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(400, status)
            edit = json.dumps(
                {"section_id": "synthetic-review", "body": "outside write", "manuscript_version": "0" * 64}
            ).encode()
            request = (
                b"PUT /api/project/synthetic-review/draft HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(edit)).encode()
                + b"\r\n\r\n"
                + edit
            )
            status, _, _ = self._request(dashboard, review_root, request)
            self.assertEqual(400, status)
            after = {
                path.relative_to(outside).as_posix(): path.read_bytes()
                for path in outside.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_explicit_review_root_is_trusted_when_its_parent_path_is_a_symlink(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            real_parent = temp / "real-parent"
            review_root = self._copy_fixture(real_parent)
            parent_link = temp / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            supplied_root = parent_link / review_root.name

            project = dashboard.project_dir(supplied_root, "synthetic-review")

            self.assertEqual(
                review_root / "review-projects" / "synthetic-review",
                project,
            )

    def test_docx_export_uses_project_release_and_browser_fields_are_bounded(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            docx = project / "05_final_audit" / "final_draft.docx"
            docx.write_bytes(b"synthetic-docx")
            release = {
                "status": "AI_REVIEWED_BENCHMARK",
                "manuscript_sha256": "hidden-manuscript-hash",
                "docx_sha256": "hidden-docx-hash",
                "docx": docx,
            }
            with patch.object(dashboard, "build_project_release", return_value=release) as build:
                result = dashboard.export_project_docx(review_root, "synthetic-review")

            build.assert_called_once_with(project)
            self.assertEqual(
                {
                    "ok": True,
                    "filename": "final_draft.docx",
                    "size": len(b"synthetic-docx"),
                    "release_status": "AI_REVIEWED_BENCHMARK",
                },
                result,
            )
            self.assertNotIn("hash", json.dumps(result).casefold())

    def test_draft_and_final_pages_use_sections_and_release_status_without_hash_values(self) -> None:
        draft_html = (ROOT / "view" / "assets" / "dashboard" / "draft.html").read_text(encoding="utf-8")
        final_html = (ROOT / "view" / "assets" / "dashboard" / "final.html").read_text(encoding="utf-8")
        self.assertIn("payload.sections", draft_html)
        self.assertIn('id="sectionEditor"', draft_html)
        self.assertIn("section_id:selectedSectionId", draft_html)
        self.assertIn("body:els.sectionEditor.value", draft_html)
        self.assertIn("manuscript_version:payload.manuscript_version", draft_html)
        self.assertNotIn("JSON.stringify({sections:", draft_html)
        self.assertIn("Authoritative project manuscript", draft_html)
        self.assertNotIn("Draft Files", draft_html)
        self.assertNotIn("${esc(payload?.paths?.stage_dir", draft_html)
        self.assertNotIn("first_draft_md", draft_html)
        self.assertNotIn('id="draftEditor"', draft_html)
        self.assertIn("release_status", final_html)
        self.assertIn("Current project manuscript", final_html)
        self.assertNotIn("file:'final_draft.md'", final_html)
        self.assertNotIn("${d.file}", final_html)
        self.assertNotIn("manuscript_sha256", final_html)
        self.assertNotIn("docx_sha256", final_html)
        self.assertNotIn("missing final_draft", final_html)
        self.assertNotIn("missing release_report", final_html)

    def test_draft_and_final_reports_hide_internal_details_but_keep_scientific_prose(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        scientific_prose = "The catalyst retained selectivity under the measured conditions."
        windows_path = r"C:\Users\Scientist\private\quality_report.json"
        posix_path = "/home/scientist/private/release/final_draft.md"
        digest = "a3" * 32
        internal_names = (
            "merge_report.md",
            "final_audit_report.md",
            "quality_report.json",
            "release_report.md",
        )
        raw_report = (
            f"# Scientific review\n\n{scientific_prose}\n\n"
            f"Windows: {windows_path}\n\nPOSIX: {posix_path}\n\nDigest: {digest}\n\n"
            f"Artifacts: {', '.join(internal_names)}\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            draft_stage = project / "04_first_draft"
            final_stage = project / "05_final_audit"
            (draft_stage / "merge_report.md").write_text(raw_report, encoding="utf-8")
            (draft_stage / "remaining_issues.md").write_text(raw_report, encoding="utf-8")
            (final_stage / "final_audit_report.md").write_text(raw_report, encoding="utf-8")
            (final_stage / "quality_report.md").write_text(raw_report, encoding="utf-8")
            (final_stage / "release_report.md").write_text(raw_report, encoding="utf-8")

            draft = dashboard.project_draft_payload(review_root, "synthetic-review")
            final = dashboard.project_final_payload(review_root, "synthetic-review")
            report_text = "\n".join(
                [
                    draft["merge_report_md"],
                    draft["remaining_issues_md"],
                    final["final_audit_report_md"],
                    final["quality_report_md"],
                    final["release_report_md"],
                ]
            )

            self.assertIn(scientific_prose, report_text)
            for hidden in (windows_path, posix_path, digest, *internal_names):
                self.assertNotIn(hidden, report_text)
            self.assertTrue(all(not Path(path).is_absolute() for path in draft["paths"].values()))
            self.assertTrue(all(not Path(path).is_absolute() for path in final["paths"].values()))

    def test_evidence_and_risk_payloads_are_scientist_safe(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            with patch.object(
                dashboard,
                "benchmark_metrics",
                wraps=dashboard.benchmark_metrics,
            ) as metrics:
                evidence = dashboard.project_evidence_payload(review_root, "synthetic-review")
            metrics.assert_called_once_with(
                review_root / "review-projects" / "synthetic-review"
            )
            self.assertEqual(
                {"studies": 1, "processable": 1, "blocked": 0, "claims": 1},
                evidence["coverage"],
            )
            self.assertEqual(1, len(evidence["cards"]))
            card = evidence["cards"][0]
            self.assertEqual(VISIBLE_EVIDENCE_CARD_FIELDS, set(card))
            self.assertEqual(["A defined synthetic intervention was associated with a measured response under the reported conditions."], card["claims"])
            self.assertEqual("Synthetic study, Results · p. 3 · Results, measured response", card["locators"][0]["label"])
            self.assertTrue(card["locators"][0]["href"].startswith("/library?"))

            risk = dashboard.project_risk_payload(review_root, "synthetic-review")
            self.assertEqual(1, risk["coverage"]["targets"])
            self.assertEqual(VISIBLE_RISK_TARGET_FIELDS, set(risk["targets"][0]))
            self.assertEqual("unresolved", risk["targets"][0]["existing_decision"])
            self.assertEqual(
                "b4dac5597d27c55c41a2438b9cbe38d267495993d1c88f17fabbe54c386b1afc",
                risk["targets"][0]["decision_token"],
            )

            visible_payload = json.dumps({"evidence": evidence, "risk": risk}, ensure_ascii=False)
            for hidden in (
                "schema_version",
                "job_id",
                "sha256",
                "self_check",
                "prompt",
                "absolute_source_path",
                "review_target_digest",
                "/synthetic-fixture/",
                "internal fixture marker",
            ):
                self.assertNotIn(hidden, visible_payload)

    def test_risk_decision_write_maps_to_task4_and_fails_closed(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            token = dashboard.project_risk_payload(review_root, "synthetic-review")["targets"][0]["decision_token"]
            result = dashboard.write_project_risk_decisions(
                review_root,
                "synthetic-review",
                {
                    "decisions": [
                        {
                            "target_id": "claim-neutral-01",
                            "decision": "reword",
                            "approved_text": "The measured response changed under the reported conditions.",
                            "decision_token": token,
                        }
                    ]
                },
            )
            self.assertEqual(
                {"status": "saved", "decisions": [{"target_id": "claim-neutral-01", "decision": "reword"}]},
                result,
            )
            serialized_result = json.dumps(result)
            self.assertNotIn("token", serialized_result)
            self.assertNotIn("digest", serialized_result)
            stored = json.loads(
                (
                    review_root
                    / "review-projects"
                    / "synthetic-review"
                    / "03_review"
                    / "risk_decisions.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual("REWORD", stored["decisions"][0]["action"])
            self.assertEqual(token, stored["decisions"][0]["review_target_digest"])

        invalid_cases = {
            "empty reword": lambda token: {"decisions": [{"target_id": "claim-neutral-01", "decision": "reword", "approved_text": "  ", "decision_token": token}]},
            "duplicate target": lambda token: {"decisions": [{"target_id": "claim-neutral-01", "decision": "approve", "decision_token": token}, {"target_id": "claim-neutral-01", "decision": "exclude", "decision_token": token}]},
            "unknown target": lambda token: {"decisions": [{"target_id": "claim-unknown", "decision": "approve", "decision_token": token}]},
            "stale token": lambda token: {"decisions": [{"target_id": "claim-neutral-01", "decision": "approve", "decision_token": "stale-review-binding"}]},
            "missing token": lambda token: {"decisions": [{"target_id": "claim-neutral-01", "decision": "approve"}]},
            "invalid decision": lambda token: {"decisions": [{"target_id": "claim-neutral-01", "decision": "maybe", "decision_token": token}]},
        }
        for name, make_payload in invalid_cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                review_root = self._copy_fixture(Path(temp_dir))
                token = dashboard.project_risk_payload(review_root, "synthetic-review")["targets"][0]["decision_token"]
                before = self._project_file_bytes(review_root)
                with self.assertRaises(ValueError):
                    dashboard.write_project_risk_decisions(
                        review_root,
                        "synthetic-review",
                        make_payload(token),
                    )
                self.assertEqual(before, self._project_file_bytes(review_root))

    def test_risk_get_fails_closed_during_staged_decision_commit_and_recovers(self) -> None:
        sys.path.insert(0, str(ROOT))
        import review_writer.project.vertical_review as vertical_review
        from view import serve_review_dashboard as dashboard

        for new_decision in ("exclude", "unresolved"):
            with self.subTest(decision=new_decision), tempfile.TemporaryDirectory() as temp_dir:
                review_root = self._copy_fixture(Path(temp_dir))
                project = review_root / "review-projects" / "synthetic-review"
                decisions_path = project / "03_review" / "risk_decisions.json"
                token = dashboard.project_risk_payload(review_root, "synthetic-review")["targets"][0]["decision_token"]
                dashboard.write_project_risk_decisions(
                    review_root,
                    "synthetic-review",
                    {"decisions": [{"target_id": "claim-neutral-01", "decision": "approve", "decision_token": token}]},
                )
                self.assertEqual(
                    "approve",
                    dashboard.project_risk_payload(review_root, "synthetic-review")["targets"][0]["existing_decision"],
                )
                decisions_before = decisions_path.read_bytes()

                with patch.object(
                    vertical_review,
                    "_write_json",
                    side_effect=OSError("synthetic final decision commit failure"),
                ):
                    with self.assertRaises(OSError):
                        dashboard.write_project_risk_decisions(
                            review_root,
                            "synthetic-review",
                            {"decisions": [{"target_id": "claim-neutral-01", "decision": new_decision, "decision_token": token}]},
                        )

                self.assertEqual(decisions_before, decisions_path.read_bytes())
                with self.assertRaises(dashboard.VerticalReviewError) as error:
                    dashboard.project_risk_payload(review_root, "synthetic-review")
                self.assertEqual("PROJECTION_INVALID", error.exception.code)
                status, _, _ = self._request(
                    dashboard,
                    review_root,
                    b"GET /api/project/synthetic-review/risk-packet HTTP/1.1\r\nHost: localhost\r\n\r\n",
                )
                self.assertEqual(400, status)

                dashboard.write_project_risk_decisions(
                    review_root,
                    "synthetic-review",
                    {"decisions": [{"target_id": "claim-neutral-01", "decision": new_decision, "decision_token": token}]},
                )
                recovered = dashboard.project_risk_payload(review_root, "synthetic-review")
                self.assertEqual(new_decision, recovered["targets"][0]["existing_decision"])
                status, _, body = self._request(
                    dashboard,
                    review_root,
                    b"GET /api/project/synthetic-review/risk-packet HTTP/1.1\r\nHost: localhost\r\n\r\n",
                )
                self.assertEqual(200, status)
                self.assertEqual(new_decision, json.loads(body)["targets"][0]["existing_decision"])

    def test_evidence_risk_and_decision_routes_return_expected_statuses(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            for route in ("evidence", "risk-packet"):
                status, _, body = self._request(
                    dashboard,
                    review_root,
                    f"GET /api/project/synthetic-review/{route} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
                )
                self.assertEqual(200, status, route)
                self.assertIsInstance(json.loads(body), dict)
            token = dashboard.project_risk_payload(review_root, "synthetic-review")["targets"][0]["decision_token"]
            request_body = json.dumps(
                {"decisions": [{"target_id": "claim-neutral-01", "decision": "approve", "decision_token": token}]}
            ).encode()
            request = (
                b"PUT /api/project/synthetic-review/risk-decisions HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(request_body)).encode()
                + b"\r\n\r\n"
                + request_body
            )
            status, _, body = self._request(dashboard, review_root, request)
            self.assertEqual(200, status)
            self.assertEqual("saved", json.loads(body)["status"])

    def test_review_workbench_has_four_accessible_tabs_and_no_internal_visible_text(self) -> None:
        review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
        self.assertEqual(4, len(re.findall(r'<button[^>]+role="tab"', review_html)))
        for tab in ("Overview", "Evidence", "Decisions", "Manuscript"):
            self.assertRegex(review_html, rf">\s*{tab}\s*<")
        for control in ("ArrowLeft", "ArrowRight", "Home", "End"):
            self.assertIn(control, review_html)
        for link in ('href="/sections"', 'href="/final"'):
            self.assertIn(link, review_html)
        for decision in ("approve", "reword", "exclude", "unresolved"):
            self.assertRegex(review_html, rf"\b{decision}:'[^']+'")
        self.assertIn('data-decision="${value}"', review_html)
        self.assertIn('type="text"', review_html)
        self.assertIn("decision_token", review_html)
        self.assertNotRegex(review_html, r"(?:textContent|innerHTML)\s*=\s*[^;\n]*decision_token")

        parser = VisibleTextParser()
        parser.feed(review_html)
        visible = parser.text.casefold()
        for forbidden in ("json", "hash", "path", "agent", "prompt", "git", "provider", "decision_token"):
            self.assertNotIn(forbidden, visible)

    def test_dashboard_accepts_qoderwork_native_project_root_without_library_metadata(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir)
            state = review_root / "review-projects" / "native-demo" / "00_brief" / "review_state.json"
            state.parent.mkdir(parents=True)
            state.write_text('{"project_id":"native-demo"}\n', encoding="utf-8")

            self.assertTrue(dashboard.has_dashboard_data(review_root))
            empty_root = Path(temp_dir) / "empty"
            (empty_root / "review-projects" / "empty-project").mkdir(parents=True)
            self.assertFalse(dashboard.has_dashboard_data(empty_root))

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
