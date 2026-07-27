#!/usr/bin/env python3
"""Focused, provider-free checks for the QoderWork CN native review writer slice."""

from __future__ import annotations

import argparse
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
    "scripts/acquisition/import_manual_archive.py",
    "scripts/discovery/discover_scholarly_corpus.py",
    "scripts/evidence/assemble_evidence_candidate_from_atoms.py",
    "scripts/evidence/build_page_atom_catalog.py",
    "scripts/evidence/build_pdf_text_layers.py",
    "scripts/evidence/validate_evidence_candidate.py",
    "scripts/run_vertical_review.py",
    "scripts/validators/validate_review_quality.py",
    "skills/review-export-docx/scripts/md2docx.py",
    "skills/review-final-audit-release/scripts/final_audit_scan.py",
    "skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py",
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
    "claim_details",
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
    "approved_text",
    "decision_token",
}


def payload_field_names(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for child in value.values()
            for key in payload_field_names(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in payload_field_names(child)}
    return set()


def payload_string_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [text for child in value.values() for text in payload_string_values(child)]
    if isinstance(value, list):
        return [text for child in value for text in payload_string_values(child)]
    return [value] if isinstance(value, str) else []


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
        self.assertEqual("0.2.4", manifest["version"])
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

    def test_main_skill_blocks_discovery_until_brief_confirmation(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")

        for required in (
            "AWAITING_BRIEF_CONFIRMATION",
            "BRIEF_CONFIRMED",
            "ready_for_discovery",
            "未观察到 `BRIEF_CONFIRMED` 前不得",
            "同一个 QoderWork 任务",
        ):
            self.assertIn(required, skill)
        self.assertLess(
            skill.index("BRIEF_CONFIRMED"),
            skill.index("DISCOVERY_ACQUISITION_PLANNER"),
        )

    def test_main_skill_initializes_project_and_opens_gui_before_brief_confirmation(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")

        for required in (
            "不得再次调用 Skill 工具",
            "不得探索插件目录、仓库结构、README 或 docs",
            "直接委派 `REVIEW_BRIEFING_AGENT`",
            "scripts/run_vertical_review.py init",
            "--review-root . --host 127.0.0.1 --port 8765",
            "127.0.0.1:8765/review",
            "只在 dashboard 的 Brief 确认界面等待",
            "不得在聊天中索取 Brief 确认",
        ):
            self.assertIn(required, skill)

        self.assertLess(
            skill.index("scripts/run_vertical_review.py init"),
            skill.index("view/serve_review_dashboard.py"),
        )
        self.assertLess(
            skill.index("view/serve_review_dashboard.py"),
            skill.index("只在 dashboard 的 Brief 确认界面等待"),
        )

    def test_source_handoff_uses_one_zip_then_the_existing_mineru_route(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")
        planner = (PLUGIN / "agents" / "DISCOVERY_ACQUISITION_PLANNER.md").read_text(encoding="utf-8")

        for required in (
            "Qwen 不逐篇浏览或下载论文",
            "一次 consolidated HTML queue",
            "一个 ZIP",
            "不逐篇提问",
            "scripts/acquisition/import_manual_archive.py",
            "--verify-only",
            "unmatched / ambiguous / missing",
            "skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py",
            "incremental",
            "不得使用 `--force`",
            "MinerU",
            "pdftotext",
            "locator/page/quote",
            "full-PDF MinerU egress",
            "一个具体 blocker",
            "atom catalog",
            "Qwen selector",
            "deterministic assembly/R0",
            "fresh reviewer",
            "registration",
            "输入 handoff",
            "插件在同一个任务内运行",
        ):
            self.assertIn(required, skill)
        self.assertLess(
            skill.index("scripts/acquisition/import_manual_archive.py"),
            skill.index("skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py"),
        )
        self.assertNotIn("browser automation", skill.casefold())

        for required in (
            "每个 expected MAIN/SI",
            "target_path",
            "download_id",
            "scripts/discovery/discover_scholarly_corpus.py",
            "scripts/acquisition/acquire_public_corpus.py",
            "scripts/acquisition/import_manual_archive.py",
            "不得使用浏览器自动化",
            "archive_names",
            "optional deterministic metadata",
            "不要求研究者",
        ):
            self.assertIn(required, planner)

    def test_expert_kit_consumes_dashboard_source_inbox(self) -> None:
        skill = (PLUGIN / "skills" / "research-review-writer" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("00_sources/manual_upload/inbox/source_bundle.zip", skill)
        self.assertIn("同一个任务", skill)
        self.assertIn("不要求研究者再次点击继续", skill)
        self.assertIn("只运行一次 `scripts/acquisition/import_manual_archive.py`", skill)
        self.assertIn("随后立即运行", skill)
        self.assertNotIn("请提供 ZIP 路径", skill)

    def test_quickstart_keeps_commands_inside_expert_task_and_out_of_scientist_steps(self) -> None:
        quickstart = (ROOT / "docs/qoderwork/research_review_writer_quickstart.md").read_text(encoding="utf-8")

        self.assertIn("准备好的 review-writer 仓库工作区", quickstart)
        self.assertNotIn("选择一个 Windows 原生工作文件夹", quickstart)
        self.assertIn("专家套件在同一个任务中", quickstart)
        for scientist_action in ("确认 Review Brief", "上传一个 ZIP", "审阅 Scientific Risk Packet", "编辑并下载最终 DOCX"):
            self.assertIn(scientist_action, quickstart)
        self.assertIn("维护者专用诊断/恢复", quickstart)
        self.assertIn("不是正常产品操作", quickstart)
        maintainer_section = quickstart.split("## 维护者专用诊断/恢复", 1)[1]
        for command in (
            "scripts/acquisition/acquire_public_corpus.py",
            "scripts/acquisition/import_manual_archive.py",
            "skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py",
        ):
            self.assertIn(command, maintainer_section)

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
                "Output: one JSON object bound to `job_id` and `study_id`",
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
        self.assertIn("consumer-first", extractor)
        self.assertIn("minimum sufficient set", extractor)
        self.assertIn("Unselected atoms are expected", extractor)
        self.assertIn("Each selected atom_id must appear in at most one decision", extractor)
        self.assertNotIn("every atom_id", extractor.lower())
        self.assertIn(
            "Do not write source_id, page, exact_quote, depiction, coverage, or self_check fields",
            extractor,
        )

    def test_adversarial_reviewer_uses_canonical_registration_contract(self) -> None:
        reviewer = (PLUGIN / "agents" / "ADVERSARIAL_EVIDENCE_REVIEWER.md").read_text(encoding="utf-8")
        self.assertIn("SUPPORT | REJECT | AMBIGUOUS", reviewer)
        self.assertIn("job_id", reviewer)
        self.assertIn("study_id", reviewer)
        self.assertIn("target_id", reviewer)
        self.assertIn("ACCEPT_WITH_NOTES is invalid", reviewer)

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
    def _bind_authoritative_fixture_draft(
        project: Path,
        *,
        manuscript: str | None = None,
        claims: list[dict[str, object]] | None = None,
    ) -> None:
        projection_path = project / "02_claims" / "claim_projection.jsonl"
        projection = [
            json.loads(line)
            for line in projection_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        projection_bytes = json.dumps(
            projection,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        projection_sha256 = hashlib.sha256(projection_bytes).hexdigest()
        manuscript_path = project / "04_first_draft" / "first_draft.md"
        if manuscript is None:
            manuscript = manuscript_path.read_text(encoding="utf-8")
            if not any(
                section.strip().casefold() == "references"
                for section in re.findall(r"^##\s+(.+)$", manuscript, flags=re.MULTILINE)
            ):
                manuscript = manuscript.rstrip() + "\n\n## References\n\n[1] Synthetic reference.\n"
        manuscript_path.write_text(manuscript, encoding="utf-8")
        writer_packet = {
            "projection_sha256": projection_sha256,
            "claims": [row for row in projection if row.get("decision") == "APPROVED"],
        }
        writer_path = project / "02_claims" / "writer_packet.json"
        writer_path.write_text(json.dumps(writer_packet, ensure_ascii=False) + "\n", encoding="utf-8")
        lineage = {
            "manuscript_sha256": hashlib.sha256(manuscript.encode("utf-8")).hexdigest(),
            "projection_sha256": projection_sha256,
            "claims": claims or [],
        }
        lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
        lineage_path.write_text(json.dumps(lineage, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _copy_fixture(destination: Path) -> Path:
        review_root = destination / "review-root"
        shutil.copytree(FIXTURE, review_root)
        NativeReviewWriterDashboardTests._bind_authoritative_fixture_draft(
            review_root / "review-projects" / "synthetic-review"
        )
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
            self.assertEqual("cockpit", state["default_workspace"])
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
            self.assertIn('getPayload(`/api/project/${encoded}/review-state`)', review_html)
            self.assertIn('<link rel="icon" href="data:,">', review_html)

    def test_projects_api_filters_directories_without_review_product_data(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            projects = review_root / "review-projects"
            state_project = projects / "state-project" / "00_brief"
            state_project.mkdir(parents=True)
            (state_project / "review_state.json").write_text("{}\n", encoding="utf-8")
            stage_project = projects / "stage-project" / "01_evidence"
            stage_project.mkdir(parents=True)
            (stage_project / "evidence_cards.jsonl").write_text("\n", encoding="utf-8")
            non_project = projects / "prepared-material" / "inputs"
            non_project.mkdir(parents=True)
            (non_project / "notes.txt").write_text("not a review project\n", encoding="utf-8")
            legacy_artifacts = {
                "root-blueprint": "section_blueprint.json",
                "section-one": "02_section_drafting/section_1.md",
                "legacy-figure": "03_figure_redraw/figure_manifest.json",
                "legacy-draft": "04_first_draft/final_draft.md",
            }
            for project_id, relative in legacy_artifacts.items():
                artifact = projects / project_id / relative
                artifact.parent.mkdir(parents=True)
                artifact.write_text("legacy review product\n", encoding="utf-8")

            listed = dashboard.list_review_projects(review_root)

            self.assertEqual(
                [
                    "legacy-draft",
                    "legacy-figure",
                    "root-blueprint",
                    "section-one",
                    "stage-project",
                    "state-project",
                ],
                [row["project_id"] for row in listed],
            )
            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/projects HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            self.assertEqual(listed, json.loads(body))

    def test_projects_api_returns_empty_list_for_empty_review_root(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "empty-review-root"

            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/projects HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )

            self.assertEqual(200, status)
            self.assertEqual([], json.loads(body))

    def test_source_handoff_payload_is_researcher_safe(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            project = review_root / "review-projects" / "source-review"
            state = project / "00_brief" / "review_state.json"
            state.parent.mkdir(parents=True)
            state.write_text(
                json.dumps({"project_id": "source-review", "current_stage": "ready_for_discovery"}) + "\n",
                encoding="utf-8",
            )
            manifest = project / "00_discovery" / "acquisition_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "public-corpus-acquisition.v1",
                        "downloads": [
                            {
                                "download_id": "STUDY_01_MAIN",
                                "study_id": "STUDY-01",
                                "doi": "10.1000/source-01",
                                "document_role": "MAIN",
                                "landing_page_url": "https://publisher.example/source-01",
                                "source_url": "https://publisher.example/source-01.pdf",
                                "target_path": "/private/internal/source-01.pdf",
                            },
                            {
                                "download_id": "STUDY_01_SI",
                                "study_id": "STUDY-01",
                                "doi": "10.1000/source-01",
                                "document_role": "SI",
                                "landing_page_url": "javascript:alert(1)",
                                "source_url": "https://publisher.example/source-01-si.pdf",
                                "target_path": "/private/internal/source-01-si.pdf",
                            },
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            receipt = project / "00_sources" / "acquisition_receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "download_id": "STUDY_01_MAIN",
                                "status": "MANUAL_REQUIRED",
                                "reason": "NO_PUBLIC_DIRECT_PDF",
                                "target_path": "/private/internal/source-01.pdf",
                                "sha256": "a" * 64,
                            },
                            {
                                "download_id": "STUDY_01_SI",
                                "status": "VERIFIED_EXISTING",
                                "target_path": "/private/internal/source-01-si.pdf",
                                "sha256": "b" * 64,
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            payload = dashboard.project_source_handoff_payload(review_root, "source-review")

            self.assertEqual(
                {"project_id", "counts", "upload_required", "sources"},
                set(payload),
            )
            self.assertEqual({"total": 2, "ready": 1, "missing": 1}, payload["counts"])
            self.assertTrue(payload["upload_required"])
            self.assertEqual(
                {
                    "study_id",
                    "citation",
                    "role",
                    "status",
                    "download_url",
                    "message",
                },
                set(payload["sources"][0]),
            )
            self.assertEqual("https://publisher.example/source-01", payload["sources"][0]["download_url"])
            self.assertEqual(
                "https://publisher.example/source-01-si.pdf",
                payload["sources"][1]["download_url"],
            )
            serialized = json.dumps(payload, ensure_ascii=False)
            for forbidden in ("/private/", "sha256", "target_path", "MANUAL_REQUIRED"):
                self.assertNotIn(forbidden, serialized)
            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/source-review/sources HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            self.assertEqual(payload, json.loads(body))

    def test_source_handoff_payload_rejects_malformed_canonical_data(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        for relative in (
            "00_discovery/acquisition_manifest.json",
            "00_sources/acquisition_receipt.json",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                review_root = Path(temp_dir) / "review-root"
                project = review_root / "review-projects/source-review"
                state = project / "00_brief/review_state.json"
                state.parent.mkdir(parents=True)
                state.write_text("{}\n", encoding="utf-8")
                canonical = project / relative
                canonical.parent.mkdir(parents=True, exist_ok=True)
                canonical.write_text("{", encoding="utf-8")

                with self.assertRaises(ValueError):
                    dashboard.project_source_handoff_payload(review_root, "source-review")
                status, _, _ = self._request(
                    dashboard,
                    review_root,
                    b"GET /api/project/source-review/sources HTTP/1.1\r\nHost: localhost\r\n\r\n",
                )
                self.assertEqual(400, status)

    def test_source_archive_route_publishes_one_valid_zip_atomically(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("study-main.pdf", b"%PDF-1.4\nsynthetic source\n%%EOF\n")
            archive_bytes = buffer.getvalue()
            request = (
                b"POST /api/project/synthetic-review/source-archive HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Type: application/zip\r\nContent-Length: "
                + str(len(archive_bytes)).encode()
                + b"\r\n\r\n"
                + archive_bytes
            )

            status, _, body = self._request(dashboard, review_root, request)

            self.assertEqual(201, status)
            self.assertEqual(
                {"status": "received", "message": "压缩包已接收，正在核验来源。"},
                json.loads(body),
            )
            inbox = (
                review_root
                / "review-projects/synthetic-review/00_sources/manual_upload/inbox/source_bundle.zip"
            )
            self.assertEqual(archive_bytes, inbox.read_bytes())
            self.assertEqual([], list(inbox.parent.glob(".source_bundle.zip.*.tmp")))

            status, _, _ = self._request(dashboard, review_root, request)
            self.assertEqual(409, status)

    def test_source_archive_route_rejects_invalid_or_unapproved_input(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            invalid = b"PK\x03\x04not-a-valid-zip"
            invalid_request = (
                b"POST /api/project/synthetic-review/source-archive HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Length: "
                + str(len(invalid)).encode()
                + b"\r\n\r\n"
                + invalid
            )
            status, _, _ = self._request(dashboard, review_root, invalid_request)
            self.assertEqual(400, status)
            inbox = (
                review_root
                / "review-projects/synthetic-review/00_sources/manual_upload/inbox/source_bundle.zip"
            )
            self.assertFalse(inbox.exists())

            with patch.object(dashboard, "DEFAULT_MAX_ARCHIVE_BYTES", 4):
                oversized = (
                    b"POST /api/project/synthetic-review/source-archive HTTP/1.1\r\n"
                    b"Host: localhost\r\nContent-Length: 5\r\n\r\n12345"
                )
                status, _, _ = self._request(dashboard, review_root, oversized)
            self.assertEqual(413, status)

            status, _, _ = self._request(
                dashboard,
                review_root,
                b"POST /api/project/missing/source-archive HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Length: 4\r\n\r\nPK00",
            )
            self.assertEqual(404, status)

    def test_source_archive_route_replaces_only_a_reported_invalid_upload(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        def zipped(name: str, payload: bytes) -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(name, payload)
            return buffer.getvalue()

        def request(payload: bytes, *, replace: bool = False) -> bytes:
            suffix = b"?replace=invalid" if replace else b""
            return (
                b"POST /api/project/synthetic-review/source-archive"
                + suffix
                + b" HTTP/1.1\r\nHost: localhost\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\n\r\n"
                + payload
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            original = zipped("old.pdf", b"%PDF-1.4\nold\n%%EOF\n")
            replacement = zipped("new.pdf", b"%PDF-1.4\nnew\n%%EOF\n")
            status, _, _ = self._request(dashboard, review_root, request(original))
            self.assertEqual(201, status)

            status, _, _ = self._request(
                dashboard,
                review_root,
                request(replacement, replace=True),
            )
            self.assertEqual(409, status)

            state_path = (
                review_root
                / "review-projects/synthetic-review/00_brief/review_state.json"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["blockers"] = ["SOURCE_ARCHIVE_INVALID"]
            state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
            status, _, _ = self._request(
                dashboard,
                review_root,
                request(replacement, replace=True),
            )
            self.assertEqual(201, status)
            inbox = (
                review_root
                / "review-projects/synthetic-review/00_sources/manual_upload/inbox/source_bundle.zip"
            )
            self.assertEqual(replacement, inbox.read_bytes())

    def test_project_progress_payload_uses_existing_artifacts_only(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            project = review_root / "review-projects/progress-review"

            def write_json(relative: str, payload: object) -> None:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

            write_json(
                "00_brief/review_state.json",
                {
                    "project_id": "progress-review",
                    "brief": {"topic": "Synthetic progress review"},
                    "current_stage": "evidence_review",
                    "status": "in_progress",
                    "blockers": [],
                    "counts": {"sources": 2, "evidence": 1, "claims": 1},
                },
            )
            write_json(
                "00_discovery/screening_decisions.json",
                {
                    "decisions": [
                        {"candidate_id": "STUDY-01", "disposition": "INCLUDE_FOR_FULL_TEXT"},
                        {"candidate_id": "STUDY-02", "disposition": "INCLUDE_FOR_FULL_TEXT"},
                    ]
                },
            )
            downloads = [
                {
                    "download_id": f"STUDY_0{index}_MAIN",
                    "study_id": f"STUDY-0{index}",
                    "doi": f"10.1000/progress-0{index}",
                    "document_role": "MAIN",
                    "landing_page_url": f"https://publisher.example/progress-0{index}",
                }
                for index in (1, 2)
            ]
            write_json(
                "00_discovery/acquisition_manifest.json",
                {"schema_version": "public-corpus-acquisition.v1", "downloads": downloads},
            )
            write_json(
                "00_sources/acquisition_receipt.json",
                {
                    "results": [
                        {"download_id": row["download_id"], "status": "VERIFIED_EXISTING"}
                        for row in downloads
                    ]
                },
            )
            write_json(
                "01_evidence/mineru/manifest.json",
                {
                    "completed": [
                        {"source_id": "STUDY_01_MAIN"},
                        {"source_id": "STUDY_02_MAIN"},
                    ],
                    "failed": [],
                },
            )
            cards = project / "01_evidence/evidence_cards.jsonl"
            cards.parent.mkdir(parents=True, exist_ok=True)
            cards.write_text(
                json.dumps({"study_id": "STUDY-01", "candidate": {"study_id": "STUDY-01"}})
                + "\n",
                encoding="utf-8",
            )

            payload = dashboard.project_progress_payload(review_root, "progress-review")

            self.assertEqual("evidence", payload["active_stage"])
            self.assertEqual(
                ["complete", "complete", "active", "pending", "pending", "pending"],
                [stage["status"] for stage in payload["stages"]],
            )
            self.assertEqual(
                {"STUDY-01": "已完成", "STUDY-02": "正在处理"},
                {row["study_id"]: row["status"] for row in payload["studies"]},
            )
            self.assertEqual("继续处理下一篇研究证据", payload["recommended_next"])
            self.assertEqual("", payload["blocker"])
            serialized = json.dumps(payload, ensure_ascii=False)
            for forbidden in ("manifest.json", "evidence_cards.jsonl", "hash", "Agent", "/home/"):
                self.assertNotIn(forbidden, serialized)
            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/progress-review/progress HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            self.assertEqual(payload, json.loads(body))

    def test_dashboard_run_keeps_serving_when_review_root_is_empty(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            dashboard,
            "ThreadingHTTPServer",
        ) as server_factory:
            server = server_factory.return_value
            server.serve_forever.side_effect = KeyboardInterrupt
            args = argparse.Namespace(
                review_root=Path(temp_dir) / "empty-review-root",
                host="127.0.0.1",
                port=0,
            )

            result = dashboard.run(args)

            self.assertEqual(0, result)
            server_factory.assert_called_once_with(
                ("127.0.0.1", 0),
                dashboard.DashboardHandler,
            )
            server.serve_forever.assert_called_once_with()
            server.server_close.assert_called_once_with()

    def test_default_workspace_requires_a_real_manuscript_for_manuscript_stages(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        cases = (
            ("evidence_review", False, "cockpit"),
            ("evidence_review", True, "cockpit"),
            ("drafting", False, "cockpit"),
            ("drafting", True, "manuscript"),
            ("final_review", True, "manuscript"),
            ("complete", True, "manuscript"),
            ("complete", False, "cockpit"),
        )
        for current_stage, first_draft_exists, expected in cases:
            with self.subTest(current_stage=current_stage, first_draft_exists=first_draft_exists):
                self.assertEqual(
                    expected,
                    dashboard.select_default_workspace(
                        {"current_stage": current_stage},
                        first_draft_exists=first_draft_exists,
                    ),
                )

    def test_case02_like_cockpit_prioritizes_unreviewed_evidence_corpus(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            project = review_root / "review-projects" / "case-like"

            def write_json(relative: str, value: object) -> None:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")

            write_json(
                "00_brief/review_state.json",
                {
                    "project_id": "case-like",
                    "brief": {"topic": "Case-neutral evidence review"},
                    "current_stage": "evidence_review",
                    "status": "NEEDS_HUMAN_REVIEW",
                    "blockers": [],
                    "counts": {"sources": 26, "evidence": 4, "claims": 6},
                },
            )
            write_json(
                "00_discovery/screening_decisions.json",
                {
                    "decisions": [
                        {"candidate_id": f"candidate-{index:02d}", "disposition": "INCLUDE_FOR_FULL_TEXT"}
                        for index in range(26)
                    ]
                },
            )
            write_json(
                "00_sources/acquisition_final_receipt.json",
                {
                    "full_text_acquired": 25,
                    "total_studies": 26,
                    "studies": [
                        {"status": "ACQUIRED", "main_pdf": {"bytes": 100}}
                        for _ in range(25)
                    ]
                    + [{"status": "MISSING", "main_pdf": None}],
                },
            )
            classifications = [
                {
                    "doi": f"10.1000/case-{index:02d}",
                    "activation_mode": "Photochemical" if index < 13 else "Electrochemical",
                }
                for index in range(26)
            ]
            write_json("01_evidence/pilot_mode_classification.json", classifications)
            cards_path = project / "01_evidence" / "evidence_cards.jsonl"
            cards_path.parent.mkdir(parents=True, exist_ok=True)
            cards = [
                {
                    "study_id": f"study-{index:02d}",
                    "candidate": {
                        "study_id": f"study-{index:02d}",
                        "doi": f"https://doi.org/10.1000/case-{index:02d}",
                        "claims": [],
                    },
                    "reviewer": {"verdict": "SUPPORT"},
                }
                for index in range(4)
            ]
            cards_path.write_text(
                "".join(json.dumps(card, ensure_ascii=False) + "\n" for card in cards),
                encoding="utf-8",
            )
            write_json("03_review/risk_packet.json", {"targets": [{"claim_id": f"risk-{index}"} for index in range(4)]})

            payload = dashboard.project_cockpit_payload(review_root, "case-like")

            self.assertEqual(
                {
                    "included_studies": 26,
                    "full_text_main_coverage": 25,
                    "reviewed_studies": 4,
                    "scientific_risks": 4,
                },
                payload["metrics"],
            )
            self.assertEqual("继续处理下一批证据", payload["recommended_next"])
            self.assertEqual(
                [
                    {"activation_mode": "Electrochemical", "included_studies": 13, "reviewed_studies": 0},
                    {"activation_mode": "Photochemical", "included_studies": 13, "reviewed_studies": 4},
                ],
                payload["mode_coverage"],
            )
            self.assertEqual("evidence_review", payload["current_stage"])
            self.assertEqual("cockpit", dashboard.project_review_state_payload(review_root, "case-like")["default_workspace"])
            self.assertTrue(
                {"path", "hash", "prompt", "job", "provider", "git", "receipt"}.isdisjoint(
                    payload_field_names(payload)
                )
            )

            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/case-like/cockpit HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )
            self.assertEqual(200, status)
            self.assertEqual(payload, json.loads(body))

    def test_mode_coverage_keeps_included_total_when_classification_is_missing_or_partial(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        cards = [
            {"candidate": {"doi": "10.1000/a", "activation_mode": "Photochemical"}},
            {"candidate": {"doi": "10.1000/b", "activation_mode": "Electrochemical"}},
        ]
        cases = (
            (
                None,
                4,
                [
                    {"activation_mode": "Electrochemical", "included_studies": 1, "reviewed_studies": 1},
                    {"activation_mode": "Photochemical", "included_studies": 1, "reviewed_studies": 1},
                    {"activation_mode": "Unclassified", "included_studies": 2, "reviewed_studies": 0},
                ],
            ),
            (
                [{"doi": "10.1000/a", "activation_mode": "Photochemical"}],
                4,
                [
                    {"activation_mode": "Electrochemical", "included_studies": 1, "reviewed_studies": 1},
                    {"activation_mode": "Photochemical", "included_studies": 1, "reviewed_studies": 1},
                    {"activation_mode": "Unclassified", "included_studies": 2, "reviewed_studies": 0},
                ],
            ),
        )
        for classifications, included, expected in cases:
            with self.subTest(classifications=classifications):
                coverage = dashboard._mode_coverage(classifications, cards, included)
                self.assertEqual(expected, coverage)
                self.assertEqual(included, sum(row["included_studies"] for row in coverage))
                self.assertEqual(2, sum(row["reviewed_studies"] for row in coverage))
                self.assertTrue(all(row["included_studies"] >= row["reviewed_studies"] for row in coverage))

    def test_cockpit_counts_only_current_unclosed_scientific_risks(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            project = review_root / "review-projects" / "risk-closure"

            def write_json(relative: str, value: object) -> None:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")

            write_json("00_brief/review_state.json", {"current_stage": "evidence_review"})
            write_json(
                "00_discovery/screening_decisions.json",
                {"decisions": [{"disposition": "INCLUDE_FOR_FULL_TEXT"}]},
            )
            write_json(
                "00_sources/acquisition_final_receipt.json",
                {"studies": [{"main_pdf": {"path": "study/MAIN.pdf"}}]},
            )
            cards = project / "01_evidence" / "evidence_cards.jsonl"
            cards.parent.mkdir(parents=True)
            cards.write_text(
                json.dumps({"study_id": "study-1", "candidate": {"study_id": "study-1", "claims": []}})
                + "\n",
                encoding="utf-8",
            )
            targets = [
                {"claim_id": f"claim-{index}", "review_target_digest": f"digest-{index}"}
                for index in range(1, 5)
            ]
            write_json("03_review/risk_packet.json", {"targets": targets})
            write_json(
                "03_review/risk_decisions.json",
                {
                    "decisions": [
                        {"claim_id": "claim-1", "review_target_digest": "digest-1", "action": "APPROVE"},
                        {"claim_id": "claim-2", "review_target_digest": "stale", "action": "REWORD"},
                        {"claim_id": "claim-3", "review_target_digest": "digest-3", "action": "UNRESOLVED"},
                    ]
                },
            )

            open_payload = dashboard.project_cockpit_payload(review_root, "risk-closure")

            self.assertEqual(3, open_payload["metrics"]["scientific_risks"])
            self.assertEqual("复核集中科学风险", open_payload["recommended_next"])

            write_json(
                "03_review/risk_decisions.json",
                {
                    "decisions": [
                        {
                            "claim_id": target["claim_id"],
                            "review_target_digest": target["review_target_digest"],
                            "action": ("APPROVE", "REWORD", "EXCLUDE")[index % 3],
                        }
                        for index, target in enumerate(targets)
                    ]
                },
            )

            closed_payload = dashboard.project_cockpit_payload(review_root, "risk-closure")

            self.assertEqual(0, closed_payload["metrics"]["scientific_risks"])
            self.assertEqual("开始撰写证据约束的综述正文", closed_payload["recommended_next"])

    def test_brief_confirmation_endpoint_is_idempotent_and_rejects_scope_mutation(self) -> None:
        sys.path.insert(0, str(ROOT))
        from review_writer.project.vertical_review import initialize_review
        from view import serve_review_dashboard as dashboard

        brief = {
            "topic": "Katritzky salt deaminative functionalization",
            "review_question": "How do activation modes differ?",
            "from_year": 2017,
            "to_year": 2025,
            "target_primary_studies": 24,
            "acceptable_core_range": [20, 30],
            "required_modes": ["photoredox", "electrochemical"],
            "exclusions": ["abstract-only evidence"],
            "output_language": "English",
            "deliverables": ["dynamic workbench", "editable DOCX"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            projects = review_root / "review-projects"
            project_id = "case-02"
            project = initialize_review(projects, project_id, brief)
            state_path = project / "00_brief" / "review_state.json"

            def put(payload: dict) -> tuple[int, bytes]:
                request_body = json.dumps(payload).encode("utf-8")
                request = (
                    f"PUT /api/project/{project_id}/review-state HTTP/1.1\r\n"
                    "Host: localhost\r\nContent-Type: application/json\r\nContent-Length: "
                ).encode() + str(len(request_body)).encode() + b"\r\n\r\n" + request_body
                status, _, body = self._request(dashboard, review_root, request)
                return status, body

            action = {"action": "confirm_brief", "project_id": project_id}
            initial_bytes = state_path.read_bytes()
            for bypass in (
                {
                    "project_id": project_id,
                    "brief": brief,
                    "current_stage": "ready_for_discovery",
                    "status": "BRIEF_CONFIRMED",
                    "blockers": [],
                    "counts": {"sources": 0, "evidence": 0, "claims": 0},
                },
                {
                    "project_id": project_id,
                    "brief": {**brief, "topic": "mutated scope"},
                    "current_stage": "review_brief",
                    "status": "AWAITING_BRIEF_CONFIRMATION",
                    "blockers": [],
                    "counts": {"sources": 0, "evidence": 0, "claims": 0},
                },
            ):
                with self.subTest(bypass=bypass):
                    status, _ = put(bypass)
                    self.assertEqual(400, status)
                    self.assertEqual(initial_bytes, state_path.read_bytes())

            status, body = put(action)
            self.assertEqual(200, status)
            self.assertEqual("BRIEF_CONFIRMED", json.loads(body)["status"])
            confirmed = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(brief, confirmed["brief"])
            self.assertEqual("ready_for_discovery", confirmed["current_stage"])
            confirmed_bytes = state_path.read_bytes()

            status, _ = put(action)
            self.assertEqual(200, status)
            self.assertEqual(confirmed_bytes, state_path.read_bytes())

            for invalid in (
                {**action, "brief": {"topic": "mutated scope"}},
                {"action": "confirm", "project_id": project_id},
                {"action": "confirm_brief"},
            ):
                with self.subTest(payload=invalid):
                    status, _ = put(invalid)
                    self.assertEqual(400, status)
                    self.assertEqual(confirmed_bytes, state_path.read_bytes())

    def test_review_workbench_shows_scientist_readable_brief_and_confirmation(self) -> None:
        review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")

        for element_id in (
            "review-question",
            "review-years",
            "review-target",
            "required-modes",
            "review-exclusions",
            "output-language",
            "review-deliverables",
            "confirm-brief",
        ):
            self.assertIn(f'id="{element_id}"', review_html)
        for label in (
            "研究问题",
            "年份范围",
            "目标研究数",
            "必需激活方式",
            "排除范围",
            "输出语言",
            "交付物",
            "确认综述简报",
        ):
            self.assertIn(label, review_html)
        self.assertIn("AWAITING_BRIEF_CONFIRMATION", review_html)
        self.assertIn("BRIEF_CONFIRMED", review_html)
        self.assertIn("action:'confirm_brief'", review_html)
        self.assertNotIn("action:'confirm_brief',brief:", review_html)

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
            self._bind_authoritative_fixture_draft(project, manuscript=manuscript)
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

    def test_draft_route_returns_a_real_empty_state_when_first_draft_is_absent(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            (project / "04_first_draft" / "first_draft.md").unlink()

            status, _, body = self._request(
                dashboard,
                review_root,
                b"GET /api/project/synthetic-review/draft HTTP/1.1\r\nHost: localhost\r\n\r\n",
            )

            self.assertEqual(200, status)
            payload = json.loads(body)
            self.assertFalse(payload["available"])
            self.assertEqual([], payload["sections"])
            self.assertEqual([], payload["claim_lineage"])
            self.assertEqual(
                {"needs_evidence_review": False, "pending_scientific_edits": []},
                payload["revision_status"],
            )

    def test_draft_payload_rejects_malformed_pending_scientific_edits(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            lineage_path = (
                review_root
                / "review-projects"
                / "synthetic-review"
                / "04_first_draft"
                / "manuscript_lineage.json"
            )
            lineage = {
                "pending_scientific_edits": [
                    {"section_id": "results", "verified_body": 42, "reasons": []}
                ]
            }
            lineage_path.write_text(json.dumps(lineage) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "pending_scientific_edits"):
                dashboard.project_draft_payload(review_root, "synthetic-review")

    def test_review_state_and_draft_require_first_draft_to_be_a_project_regular_file(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        for invalid_kind in ("directory", "symlink", "empty", "whitespace"):
            with self.subTest(invalid_kind=invalid_kind), tempfile.TemporaryDirectory() as temp_dir:
                temp = Path(temp_dir)
                review_root = self._copy_fixture(temp)
                project = review_root / "review-projects" / "synthetic-review"
                state_path = project / "00_brief" / "review_state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["current_stage"] = "drafting"
                state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
                manuscript = project / "04_first_draft" / "first_draft.md"
                manuscript.unlink()
                if invalid_kind == "directory":
                    manuscript.mkdir()
                elif invalid_kind == "symlink":
                    outside = temp / "outside.md"
                    outside.write_text("# Outside\n", encoding="utf-8")
                    manuscript.symlink_to(outside)
                elif invalid_kind == "empty":
                    manuscript.write_bytes(b"")
                else:
                    manuscript.write_text(" \n\t\n", encoding="utf-8")

                review_state = dashboard.project_review_state_payload(review_root, "synthetic-review")

                self.assertFalse(review_state["draft"]["first_draft_exists"])
                self.assertEqual("cockpit", review_state["default_workspace"])
                self.assertFalse(review_state["summary"]["has_first_draft"])
                if invalid_kind != "symlink":
                    draft = dashboard.project_draft_payload(review_root, "synthetic-review")
                    self.assertFalse(draft["available"])
                    self.assertEqual([], draft["sections"])
                else:
                    with self.assertRaises(ValueError):
                        dashboard.project_draft_payload(review_root, "synthetic-review")

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
            self._bind_authoritative_fixture_draft(project, manuscript=manuscript)
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
            self.assertEqual("authoritative_manuscript", tampered["manuscript_source"])
            self.assertEqual(manuscript_path.read_text(encoding="utf-8"), tampered["final_draft_md"])
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
        scientific_slashes = "The /m/z 44/28 signal, DOI 10.1000/example/path, and A/B selectivity were retained."
        windows_path = r"C:\Users\Research Team\Review Project\quality_report.json"
        wsl_path = r"\\wsl.localhost\Ubuntu\home\Research Team\release_report.md"
        posix_path = "/home/scientist/Review Project/final audit/final_draft.md"
        digest = "a3" * 32
        internal_names = (
            "merge_report.md",
            "final_audit_report.md",
            "quality_report.json",
            "release_report.md",
        )
        raw_report = (
            f"# Scientific review\n\n{scientific_prose}\n\n{scientific_slashes}\n\n"
            f"Windows: {windows_path}\n\nWSL: {wsl_path}\n\nPOSIX: {posix_path}\n\nDigest: {digest}\n\n"
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
            self.assertIn(scientific_slashes, report_text)
            for hidden in (windows_path, wsl_path, posix_path, digest, *internal_names):
                self.assertNotIn(hidden, report_text)
            for leaked_fragment in ("Research Team", "Review Project", "wsl.localhost", "final audit"):
                self.assertNotIn(leaked_fragment, report_text)
            self.assertTrue(all(not Path(path).is_absolute() for path in draft["paths"].values()))
            self.assertTrue(all(not Path(path).is_absolute() for path in final["paths"].values()))

    def test_researcher_safe_paths_preserve_following_scientific_clause(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        scientific_clause = "; the /m/z signal retained selectivity at substrate/catalyst = 2:1."
        absolute_paths = (
            r"C:\Users\Research Team\Review Project\quality_report.json",
            r"\\wsl.localhost\Ubuntu\home\Research Team\quality_report.json",
            "/home/scientist/Review Project/final audit/quality_report.json",
        )
        for absolute_path in absolute_paths:
            with self.subTest(path=absolute_path):
                safe = dashboard.researcher_safe_markdown(
                    f"Internal artifact: {absolute_path}{scientific_clause}"
                )
                self.assertIn(scientific_clause, safe)
                self.assertNotIn(absolute_path, safe)
                self.assertNotIn("quality_report.json", safe)
                self.assertNotIn("Research Team", safe)

    def test_researcher_safe_artifact_suffix_preserves_following_sentence(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        scientific_sentence = ". The /m/z signal retained selectivity at substrate/catalyst = 2:1."
        absolute_paths = (
            r"C:\Users\Research Team\Review Project\quality_report.json",
            r"\\wsl.localhost\Ubuntu\home\Research Team\quality_report.json",
            "/home/scientist/Review Project/final audit/quality_report.json",
        )
        for absolute_path in absolute_paths:
            with self.subTest(path=absolute_path):
                safe = dashboard.researcher_safe_markdown(
                    f"Internal artifact: {absolute_path}{scientific_sentence}"
                )
                self.assertIn(scientific_sentence, safe)
                self.assertNotIn(absolute_path, safe)
                self.assertNotIn("quality_report.json", safe)
                self.assertNotIn("Research Team", safe)

    def test_evidence_and_risk_payloads_are_scientist_safe(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            cards_path = project / "01_evidence" / "evidence_cards.jsonl"
            original_cards = cards_path.read_bytes()
            card_row = json.loads(cards_path.read_text(encoding="utf-8"))
            second_ref = {
                "exact_quote": "A second bounded observation was reported.",
                "page": 4,
                "section_or_item": "Supporting result",
                "source_id": "synthetic-study-02",
                "source_label": "Synthetic study, supporting result",
            }
            card_row["candidate"]["claims"][0]["evidence_refs"].append(second_ref)
            card_row["reviewer"].update(
                {
                    "verdict": "REJECT",
                    "summary": "Root reviewer summary.",
                    "findings": [
                        {
                            "claim_id": "claim-neutral-01",
                            "target_id": "different-target",
                            "verdict": "SUPPORT",
                            "reason": "This non-target row must not override the root verdict.",
                        },
                        {
                            "target_id": "claim-neutral-01",
                            "verdict": "AMBIGUOUS",
                            "reason": "The wording exceeds the directly quoted observation.",
                        }
                    ],
                }
            )
            cards_path.write_text(json.dumps(card_row, ensure_ascii=False) + "\n", encoding="utf-8")
            projection_path = project / "02_claims" / "claim_projection.jsonl"
            original_projection = projection_path.read_bytes()
            projection_row = json.loads(projection_path.read_text(encoding="utf-8"))
            projection_row["evidence_refs"].append(second_ref)
            projection_path.write_text(json.dumps(projection_row, ensure_ascii=False) + "\n", encoding="utf-8")
            with patch.object(
                dashboard,
                "benchmark_metrics",
                return_value={
                    "registered_study_count": 1,
                    "approved_claim_count": 0,
                    "human_required_claim_count": 1,
                    "blocked_claim_count": 0,
                    "exception_count": 0,
                    "projected_claim_count": 1,
                },
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
            self.assertEqual("", card["locators"][0]["href"])
            self.assertEqual(2, len(card["locators"]), "card locators retain all unique claim evidence")
            detail = card["claim_details"][0]
            self.assertEqual("claim-neutral-01", detail["claim_id"])
            self.assertEqual("HUMAN_REQUIRED", detail["decision"])
            self.assertEqual("R3", detail["risk_level"])
            self.assertEqual(["MECHANISM_CAUSALITY"], detail["risk_categories"])
            self.assertEqual(2, len(detail["evidence"]))
            self.assertEqual(
                {"source_label", "excerpt", "page", "section", "locator"},
                set(detail["evidence"][0]),
            )
            self.assertEqual("", detail["evidence"][0]["locator"]["href"])
            self.assertEqual("AMBIGUOUS", detail["review_verdict"])
            self.assertEqual(
                "The wording exceeds the directly quoted observation.",
                detail["review_summary"],
            )

            cards_path.write_bytes(original_cards)
            projection_path.write_bytes(original_projection)
            risk = dashboard.project_risk_payload(review_root, "synthetic-review")
            self.assertEqual(1, risk["coverage"]["targets"])
            self.assertEqual(VISIBLE_RISK_TARGET_FIELDS, set(risk["targets"][0]))
            self.assertEqual("unresolved", risk["targets"][0]["existing_decision"])
            self.assertEqual("", risk["targets"][0]["approved_text"])
            self.assertEqual(
                "自动证据审查支持；该主张属于高风险类别，需要您确认是否进入正文。",
                risk["targets"][0]["proposed_action"],
            )
            self.assertEqual(
                "b4dac5597d27c55c41a2438b9cbe38d267495993d1c88f17fabbe54c386b1afc",
                risk["targets"][0]["decision_token"],
            )

            visible_payload = {"evidence": evidence, "risk": risk}
            self.assertTrue(
                {
                    "schema_version",
                    "job_id",
                    "sha256",
                    "self_check",
                    "prompt",
                    "absolute_source_path",
                    "review_target_digest",
                }.isdisjoint(payload_field_names(visible_payload))
            )
            visible_values = payload_string_values(visible_payload)
            for hidden_value in (
                "/synthetic-fixture/not-for-display/source.md",
                "internal fixture marker",
                "internal-fixture-digest",
            ):
                self.assertNotIn(hidden_value, visible_values)

    def test_claim_details_require_a_claim_specific_reviewer_finding(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            cards_path = project / "01_evidence" / "evidence_cards.jsonl"
            card = json.loads(cards_path.read_text(encoding="utf-8"))
            first_claim = card["candidate"]["claims"][0]
            second_claim = json.loads(json.dumps(first_claim))
            second_claim["claim_id"] = "claim-neutral-02"
            second_claim["claim_text"] = "A second claim has no claim-specific reviewer finding."
            card["candidate"]["claims"] = [first_claim, second_claim]
            card["reviewer"] = {
                "verdict": "REJECT",
                "summary": "Study-level reviewer text must not be attached to every claim.",
                "findings": [
                    {
                        "target_id": first_claim["claim_id"],
                        "verdict": "SUPPORT",
                        "reason": "The first claim has a matching finding.",
                    },
                    {
                        "claim_id": second_claim["claim_id"],
                        "verdict": "AMBIGUOUS",
                        "reason": "A claim_id-only row is not claim-specific.",
                    },
                ],
            }
            cards_path.write_text(json.dumps(card, ensure_ascii=False) + "\n", encoding="utf-8")

            projection_path = project / "02_claims" / "claim_projection.jsonl"
            first_projection = json.loads(projection_path.read_text(encoding="utf-8"))
            second_projection = dict(first_projection)
            second_projection["claim_id"] = second_claim["claim_id"]
            second_projection["text"] = second_claim["claim_text"]
            projection_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in (first_projection, second_projection))
                + "\n",
                encoding="utf-8",
            )

            with patch.object(
                dashboard,
                "benchmark_metrics",
                return_value={
                    "registered_study_count": 1,
                    "approved_claim_count": 1,
                    "human_required_claim_count": 1,
                    "blocked_claim_count": 0,
                    "exception_count": 0,
                    "projected_claim_count": 2,
                },
            ):
                payload = dashboard.project_evidence_payload(review_root, "synthetic-review")

            details = {
                detail["claim_id"]: detail
                for detail in payload["cards"][0]["claim_details"]
            }
            self.assertEqual("SUPPORT", details[first_claim["claim_id"]]["review_verdict"])
            self.assertEqual(
                "The first claim has a matching finding.",
                details[first_claim["claim_id"]]["review_summary"],
            )
            self.assertEqual("", details[second_claim["claim_id"]]["review_verdict"])
            self.assertEqual("", details[second_claim["claim_id"]]["review_summary"])

    def test_claim_details_use_root_reviewer_conclusion_when_no_findings_exist(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = self._copy_fixture(Path(temp_dir))
            project = review_root / "review-projects" / "synthetic-review"
            cards_path = project / "01_evidence" / "evidence_cards.jsonl"
            card = json.loads(cards_path.read_text(encoding="utf-8"))
            card["reviewer"] = {
                "verdict": "SUPPORT",
                "summary": "The reviewer found the bounded claim supported by the cited evidence.",
                "findings": [],
            }
            cards_path.write_text(json.dumps(card, ensure_ascii=False) + "\n", encoding="utf-8")

            with patch.object(
                dashboard,
                "benchmark_metrics",
                return_value={
                    "registered_study_count": 1,
                    "approved_claim_count": 1,
                    "human_required_claim_count": 0,
                    "blocked_claim_count": 0,
                    "exception_count": 0,
                    "projected_claim_count": 1,
                },
            ):
                detail = dashboard.project_evidence_payload(
                    review_root, "synthetic-review"
                )["cards"][0]["claim_details"][0]

            self.assertEqual("SUPPORT", detail["review_verdict"])
            self.assertEqual(
                "The reviewer found the bounded claim supported by the cited evidence.",
                detail["review_summary"],
            )

    def test_evidence_locator_opens_a_uniquely_matched_project_pdf_page_and_fails_closed(self) -> None:
        sys.path.insert(0, str(ROOT))
        from review_writer.delivery import project_release
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            review_root = self._copy_fixture(temp)
            project = review_root / "review-projects" / "synthetic-review"
            source_id = "10_1234_Test_DOI_main"
            source_dir = project / "00_sources" / "10.1234_test-doi"
            source_dir.mkdir(parents=True)
            pdf_bytes = b"%PDF-1.4\nsynthetic project source\n%%EOF\n"
            (source_dir / "MAIN.pdf").write_bytes(pdf_bytes)
            for index in range(20):
                unrelated = project / "00_sources" / f"unrelated-{index:02d}"
                unrelated.mkdir()
                (unrelated / "MAIN.pdf").write_bytes(b"%PDF-1.4\nunrelated\n%%EOF\n")
            unrelated_outside = temp / "unrelated-outside.pdf"
            unrelated_outside.write_bytes(b"unrelated-outside-must-not-be-read")
            unrelated_bad = project / "00_sources" / "unrelated-bad"
            unrelated_bad.mkdir()
            (unrelated_bad / "MAIN.pdf").symlink_to(unrelated_outside)

            cards_path = project / "01_evidence" / "evidence_cards.jsonl"
            card = json.loads(cards_path.read_text(encoding="utf-8"))
            refs = [
                {
                    **card["candidate"]["claims"][0]["evidence_refs"][0],
                    "source_id": source_id,
                    "page": page,
                    "section_or_item": f"Measured result {page}",
                }
                for page in range(1, 171)
            ]
            card["candidate"]["claims"][0]["evidence_refs"] = refs
            cards_path.write_text(json.dumps(card, ensure_ascii=False) + "\n", encoding="utf-8")
            projection_path = project / "02_claims" / "claim_projection.jsonl"
            projection = json.loads(projection_path.read_text(encoding="utf-8"))
            projection["evidence_refs"] = refs
            projection["decision"] = "APPROVED"
            projection_path.write_text(json.dumps(projection, ensure_ascii=False) + "\n", encoding="utf-8")
            claim_text = projection.get("text", "Synthetic claim")
            self._bind_authoritative_fixture_draft(
                project,
                manuscript=(
                    "# Synthetic Review\n\n"
                    "## Results\n\n"
                    f"{claim_text} [1].\n\n"
                    "## References\n\n"
                    "[1] Synthetic reference.\n"
                ),
                claims=[
                    {
                        "claim_id": projection["claim_id"],
                        "section_id": "results",
                        "text_span": claim_text,
                    }
                ],
            )

            with (
                patch.object(
                    dashboard,
                    "benchmark_metrics",
                    return_value={
                        "registered_study_count": 1,
                        "approved_claim_count": 0,
                        "human_required_claim_count": 1,
                        "blocked_claim_count": 0,
                        "exception_count": 0,
                        "projected_claim_count": 1,
                    },
                ),
                patch.object(
                    dashboard,
                    "build_project_source_index",
                    wraps=dashboard.build_project_source_index,
                ) as build_source_index,
                patch.object(
                    dashboard,
                    "validate_project_file_path",
                    wraps=dashboard.validate_project_file_path,
                ) as validate_source_path,
            ):
                evidence = dashboard.project_evidence_payload(review_root, "synthetic-review")
            self.assertEqual(1, build_source_index.call_count)
            build_source_index.assert_called_once_with(project, {source_id})
            validate_source_path.assert_called_once_with(
                project,
                Path("00_sources/10.1234_test-doi/MAIN.pdf"),
                "PROJECT_SOURCE_INVALID",
            )
            self.assertEqual(170, len(evidence["cards"][0]["locators"]))
            self.assertEqual(170, len(evidence["cards"][0]["claim_details"][0]["evidence"]))
            href = evidence["cards"][0]["claim_details"][0]["evidence"][0]["locator"]["href"]
            self.assertTrue(href.startswith("/api/project/synthetic-review/source?source_id="))
            self.assertTrue(href.endswith("#page=1"))
            with (
                patch.object(
                    project_release,
                    "benchmark_metrics",
                    return_value={"project_id": "synthetic-review"},
                ),
                patch.object(
                    dashboard,
                    "build_project_source_index",
                    wraps=dashboard.build_project_source_index,
                ) as draft_source_index,
            ):
                draft = dashboard.project_draft_payload(review_root, "synthetic-review")
            draft_source_index.assert_called_once_with(project, {source_id})
            self.assertEqual(
                href,
                draft["claim_lineage"][0]["evidence"][0]["locator"]["href"],
            )
            request_target = href.split("#", 1)[0]
            with patch.object(
                dashboard,
                "build_project_source_index",
                wraps=dashboard.build_project_source_index,
            ) as route_source_index:
                status, headers, body = self._request(
                    dashboard,
                    review_root,
                    f"GET {request_target} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
                )
            route_source_index.assert_called_once_with(project, {source_id})
            self.assertEqual(200, status)
            self.assertEqual("application/pdf", headers["Content-Type"])
            self.assertEqual(pdf_bytes, body)
            self.assertNotIn("00_sources", href)

            (source_dir / "MAIN.pdf").unlink()
            outside = temp / "outside.pdf"
            outside.write_bytes(b"outside-pdf-must-not-be-read")
            (source_dir / "MAIN.pdf").symlink_to(outside)
            status, _, body = self._request(
                dashboard,
                review_root,
                f"GET {request_target} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
            )
            self.assertNotEqual(200, status)
            self.assertNotIn(outside.read_bytes(), body)
            with patch.object(
                dashboard,
                "benchmark_metrics",
                return_value={
                    "registered_study_count": 1,
                    "approved_claim_count": 0,
                    "human_required_claim_count": 1,
                    "blocked_claim_count": 0,
                    "exception_count": 0,
                    "projected_claim_count": 1,
                },
            ):
                fallback = dashboard.project_evidence_payload(review_root, "synthetic-review")
            fallback_href = fallback["cards"][0]["claim_details"][0]["evidence"][0]["locator"]["href"]
            self.assertEqual("", fallback_href)

    def test_acquisition_manifest_maps_nested_pdf_aliases_with_portable_separators(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        for collection, separator in (("rows", "\\"), ("downloads", "/")):
            with self.subTest(collection=collection), tempfile.TemporaryDirectory() as temp_dir:
                review_root = self._copy_fixture(Path(temp_dir))
                project = review_root / "review-projects" / "synthetic-review"
                target = project / "00_sources" / "custom" / "nested" / "article.pdf"
                target.parent.mkdir(parents=True)
                pdf_bytes = b"%PDF-1.4\nnested mapped source\n%%EOF\n"
                target.write_bytes(pdf_bytes)
                source_id = f"CUSTOM_{collection.upper()}_MAIN"
                doi = f"10.1234/{collection}-custom"
                manifest_path = project / "00_discovery" / (
                    "acquisition_manifest.json"
                    if collection == "rows"
                    else "acquisition_manifest_converted.json"
                )
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(
                    json.dumps(
                        {
                            collection: [
                                {
                                    "download_id": source_id,
                                    "doi": doi,
                                    "document_role": "MAIN",
                                    "target_path": separator.join(("custom", "nested", "article.pdf")),
                                }
                            ]
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )

                index = dashboard.build_project_source_index(project, {source_id, f"{doi}_MAIN"})

                self.assertEqual(target, index[dashboard._normalized_project_source_id(source_id)])
                self.assertEqual(
                    target,
                    index[dashboard._normalized_project_source_id(f"{doi}_MAIN")],
                )
                href = dashboard._evidence_locator_href(
                    project,
                    "synthetic-review",
                    source_id,
                    7,
                    index,
                )
                self.assertTrue(href.startswith("/api/project/synthetic-review/source?"))
                self.assertTrue(href.endswith("#page=7"))

    def test_acquisition_manifest_mapping_rejects_unsafe_or_symlink_targets(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            review_root = self._copy_fixture(temp)
            project = review_root / "review-projects" / "synthetic-review"
            manifest_path = project / "00_discovery" / "acquisition_manifest_converted.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            outside = temp / "outside.pdf"
            outside.write_bytes(b"outside")
            alias = "UNSAFE_MAIN"

            for target_path in ("/absolute.pdf", r"C:\absolute.pdf", "../escape.pdf"):
                with self.subTest(target_path=target_path):
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "downloads": [
                                    {
                                        "download_id": alias,
                                        "doi": "10.1234/unsafe",
                                        "document_role": "MAIN",
                                        "target_path": target_path,
                                    }
                                ]
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    index = dashboard.build_project_source_index(project, {alias})
                    self.assertIsNone(index.get(dashboard._normalized_project_source_id(alias)))

            symlink = project / "00_sources" / "custom" / "nested" / "article.pdf"
            symlink.parent.mkdir(parents=True)
            symlink.symlink_to(outside)
            manifest_path.write_text(
                json.dumps(
                    {
                        "downloads": [
                            {
                                "download_id": alias,
                                "doi": "10.1234/unsafe",
                                "document_role": "MAIN",
                                "target_path": "custom/nested/article.pdf",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            index = dashboard.build_project_source_index(project, {alias})
            self.assertIsNone(index.get(dashboard._normalized_project_source_id(alias)))

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
            self.assertEqual(
                "The measured response changed under the reported conditions.",
                dashboard.project_risk_payload(review_root, "synthetic-review")["targets"][0]["approved_text"],
            )

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

    def test_early_stage_routes_return_explicit_empty_evidence_and_risk_payloads(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        with tempfile.TemporaryDirectory() as temp_dir:
            review_root = Path(temp_dir) / "review-root"
            project = review_root / "review-projects" / "brief-only"
            state_path = project / "00_brief" / "review_state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps({"project_id": "brief-only", "current_stage": "review_brief"}) + "\n",
                encoding="utf-8",
            )
            decisions_path = project / "03_review" / "risk_decisions.json"
            decisions_path.parent.mkdir(parents=True)
            decisions_path.write_text('{"decisions":[]}\n', encoding="utf-8")

            expected = {
                "evidence": {
                    "project_id": "brief-only",
                    "coverage": {"studies": 0, "processable": 0, "blocked": 0, "claims": 0},
                    "cards": [],
                },
                "risk-packet": {
                    "project_id": "brief-only",
                    "coverage": {"targets": 0, "human_required": 0, "low_risk_audit": 0},
                    "targets": [],
                },
            }
            for route, payload in expected.items():
                with self.subTest(route=route):
                    status, _, body = self._request(
                        dashboard,
                        review_root,
                        f"GET /api/project/brief-only/{route} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
                    )
                    self.assertEqual(200, status)
                    self.assertEqual(payload, json.loads(body))

    def test_early_stage_routes_do_not_mask_existing_malformed_canonical_state(self) -> None:
        sys.path.insert(0, str(ROOT))
        from view import serve_review_dashboard as dashboard

        cases = (
            ("evidence", "01_evidence/evidence_cards.jsonl", "{"),
            ("risk-packet", "03_review/risk_packet.json", "{}\n"),
            ("risk-packet", "03_review/risk_decisions.json", "{"),
        )
        for route, relative, content in cases:
            with self.subTest(route=route, relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                review_root = self._copy_fixture(Path(temp_dir))
                canonical = review_root / "review-projects" / "synthetic-review" / relative
                canonical.parent.mkdir(parents=True, exist_ok=True)
                canonical.write_text(content, encoding="utf-8")

                status, _, _ = self._request(
                    dashboard,
                    review_root,
                    f"GET /api/project/synthetic-review/{route} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
                )

                self.assertEqual(400, status)

    def test_review_workbench_binds_default_workspace_and_real_cockpit_fields(self) -> None:
        review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
        for element_id in (
            "cockpit-workspace",
            "manuscript-workspace",
            "metric-included",
            "metric-main-coverage",
            "metric-reviewed",
            "metric-scientific-risks",
            "mode-coverage",
            "recommended-next",
            "cockpit-context",
        ):
            self.assertIn(f'id="{element_id}"', review_html)
        for binding in (
            "projectState.default_workspace",
            "setWorkspace(projectState.default_workspace)",
            "cockpitPayload.metrics.included_studies",
            "cockpitPayload.metrics.full_text_main_coverage",
            "cockpitPayload.metrics.reviewed_studies",
            "cockpitPayload.metrics.scientific_risks",
            "cockpitPayload.mode_coverage",
            "cockpitPayload.recommended_next",
            "/cockpit`",
        ):
            self.assertIn(binding, review_html)
        self.assertNotIn('role="tab"', review_html)

    def test_review_workbench_waits_for_qoderwork_projects_and_polls(self) -> None:
        review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
        parser = VisibleTextParser()
        parser.feed(review_html)

        self.assertIn('id="empty-project-workspace"', review_html)
        self.assertIn("等待 QoderWork 创建科研综述", parser.text)
        self.assertIn("请在 QoderWork CN 中选择科研综述专家并创建任务", parser.text)
        self.assertIn("async function refreshProjects()", review_html)
        self.assertIn("setInterval(refreshProjects, 3000)", review_html)

    def test_review_workbench_exposes_one_zip_drop_and_automatic_progress(self) -> None:
        review_html = (ROOT / "view/assets/dashboard/review.html").read_text(encoding="utf-8")
        parser = VisibleTextParser()
        parser.feed(review_html)
        visible = parser.text.casefold()

        for element_id in (
            "brief-stage-panel",
            "source-stage-panel",
            "source-drop-zone",
            "source-archive-input",
            "processing-stage-panel",
            "processing-stage-list",
            "processing-study-list",
        ):
            self.assertIn(f'id="{element_id}"', review_html)
        for binding in (
            "/sources`",
            "/progress`",
            "body:file",
            "'Content-Type':'application/zip'",
            "source-archive",
            "renderStageWorkspace",
            "uploadSourceArchive",
        ):
            self.assertIn(binding, review_html)
        self.assertIn("拖入一个 pdf zip", visible)
        self.assertIn("上传成功后立即开始核验", visible)
        for forbidden in ("mapping file", "manifest path", "json", "agent", "prompt", "git"):
            self.assertNotIn(forbidden, visible)

    def test_review_workbench_completes_risk_packet_in_scientific_language(self) -> None:
        review_html = (ROOT / "view/assets/dashboard/review.html").read_text(encoding="utf-8")
        parser = VisibleTextParser()
        parser.feed(review_html)
        visible = parser.text

        for element_id in (
            "risk-stage-panel",
            "risk-decision-list",
            "submit-risk-decisions",
            "risk-decision-message",
        ):
            self.assertIn(f'id="{element_id}"', review_html)
        for decision in ("approve", "reword", "exclude", "unresolved"):
            self.assertIn(f"value = '{decision}'", review_html)
        for binding in (
            "decision_token:target.decision_token",
            "approved_text:riskRewordText(target.target_id)",
            "/risk-decisions`",
            "method:'PUT'",
            "renderRiskPacket",
            "submitRiskDecisions",
        ):
            self.assertIn(binding, review_html)
        for copy in (
            "采纳",
            "改写",
            "排除",
            "暂缓",
            "尚有暂缓项，完成决定后才能进入写作",
        ):
            self.assertIn(copy, visible)
        self.assertNotIn("decision_token", visible)

    def test_review_workbench_binds_manuscript_lineage_pending_restore_and_empty_state(self) -> None:
        review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
        review_css = (ROOT / "view" / "assets" / "dashboard" / "review-ui.css").read_text(encoding="utf-8")
        for element_id in (
            "section-outline",
            "section-reading",
            "section-editor",
            "evidence-inspector",
            "pending-review-banner",
            "restore-verified",
            "manuscript-empty",
        ):
            self.assertIn(f'id="{element_id}"', review_html)
        for binding in (
            "draftPayload.available",
            "draftPayload.claim_lineage",
            "pending_scientific_edits",
            "pending.verified_body",
            "saveDraftBody(pending.verified_body)",
            "edit_classification",
            "needs_evidence_review",
            "detail.review_verdict",
            "detail.review_summary",
            "detail.decision",
            "evidence.locator.href",
            "data-claim-id",
            "claim-mark",
            "method:'PUT'",
        ):
            self.assertIn(binding, review_html)
        for copy in (
            "尚无 claim-specific 复核结论",
            "原文文件暂不可用",
            "恢复本节已验证版本",
            "将替换当前未复核编辑",
        ):
            self.assertIn(copy, review_html)
        for draft_guard in (
            "let editorDirty = false",
            "confirmDiscardDraftChanges",
            "window.confirm",
            "beforeunload",
            "submittedProjectId",
            "submittedSectionId",
            "submittedBody",
            "submittedVersion",
            "editorUnchanged",
            "setEditorBusy(true)",
            "$('section-editor').disabled = busy",
            "$('project').disabled = busy",
            "document.querySelectorAll('[data-workspace], .outline-section')",
        ):
            self.assertIn(draft_guard, review_html)
        self.assertRegex(
            review_html,
            r"JSON\.stringify\(\{section_id:submittedSectionId,body:submittedBody,manuscript_version:submittedVersion\}\)",
        )
        self.assertIn("@media (max-width: 1100px)", review_css)
        self.assertIn("@media (max-width: 640px)", review_css)
        self.assertIn("overflow-wrap: anywhere", review_css)

        parser = VisibleTextParser()
        parser.feed(review_html)
        visible = parser.text.casefold()
        for forbidden in (
            "json",
            "hash",
            "path",
            "agent",
            "prompt",
            "git",
            "provider",
            "receipt",
            "decision_token",
        ):
            self.assertNotIn(forbidden, visible)

    def test_cockpit_context_preview_clamps_excerpt_without_clamping_manuscript_quotes(self) -> None:
        review_css = (ROOT / "view" / "assets" / "dashboard" / "review-ui.css").read_text(encoding="utf-8")

        preview_rule = re.search(
            r"#cockpit-context \.context-item > p\s*\{(?P<body>[^}]*)\}",
            review_css,
        )
        self.assertIsNotNone(preview_rule)
        for declaration in (
            "display: -webkit-box",
            "-webkit-box-orient: vertical",
            "-webkit-line-clamp: 7",
            "line-clamp: 7",
            "overflow: hidden",
        ):
            self.assertIn(declaration, preview_rule.group("body"))

        manuscript_quote_rule = re.search(
            r"\.chain-node blockquote\s*\{(?P<body>[^}]*)\}",
            review_css,
        )
        self.assertIsNotNone(manuscript_quote_rule)
        self.assertNotIn("line-clamp", manuscript_quote_rule.group("body"))

    def test_review_workbench_guards_async_project_loads_and_inline_js_compiles(self) -> None:
        review_html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
        load_match = re.search(
            r"async function loadProject\(\) \{(?P<body>[\s\S]*?)\n    \}\n\n    async function loadProjects",
            review_html,
        )
        self.assertIsNotNone(load_match)
        load_body = load_match.group("body")
        for guard in (
            "let projectLoadGeneration = 0",
            "let projectLoadBusy = false",
            "const requestedProjectId = projectId",
            "const generation = ++projectLoadGeneration",
            "setProjectLoadBusy(true)",
            "generation !== projectLoadGeneration",
            "projectId !== requestedProjectId",
            "return 'stale'",
            "return 'loaded'",
            "const [nextProjectState, nextCockpitPayload, nextDraftPayload, nextEvidencePayload, nextRiskPayload, nextSourcePayload, nextProgressPayload]",
            "projectState = nextProjectState",
            "cockpitPayload = nextCockpitPayload",
            "draftPayload = nextDraftPayload",
            "evidencePayload = nextEvidencePayload",
            "riskPayload = nextRiskPayload",
            "sourcePayload = nextSourcePayload",
            "progressPayload = nextProgressPayload",
            "if (generation === projectLoadGeneration) setProjectLoadBusy(false)",
            "applyWorkbenchBusyState(editorBusy || projectLoadBusy)",
            "button.disabled = editorBusy || projectLoadBusy",
        ):
            self.assertIn(guard, review_html)
        self.assertLess(
            load_body.index("const [nextProjectState"),
            load_body.index("projectState = nextProjectState"),
        )
        self.assertLess(
            load_body.index("generation !== projectLoadGeneration"),
            load_body.index("editorDirty = false"),
        )
        self.assertGreaterEqual(review_html.count("if (loadResult === 'stale') return"), 3)

        script_match = re.search(r"<script>(?P<script>[\s\S]*?)</script>", review_html)
        self.assertIsNotNone(script_match)
        node = shutil.which("node")
        self.assertIsNotNone(node)
        completed = subprocess.run(
            [node, "-e", f"new Function({json.dumps(script_match.group('script'))});"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

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
