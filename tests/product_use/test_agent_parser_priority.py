from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from review_writer.agent.fresh_bootstrap import FreshAgentBootstrap
from review_writer.agent.local_pdf_parse import parse_project_sources
from review_writer.product_foundation import VersionContext
from tests.product_use import test_public_e2e_source_truth_parse as source_flow


def _text_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 72 720 Td (Source-bound fallback parse text.) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii"))
        payload.extend(value)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(payload)


def _confirm_main_source(base_url: str, project_id: str) -> None:
    project_route = quote(project_id, safe="")
    status, sources = source_flow._request_json(
        base_url, f"/api/project/{project_route}/sources"
    )
    assert status == 200
    assert isinstance(sources, dict)
    preflight = sources["preflight"]
    assert isinstance(preflight, dict)
    member = preflight["member"]
    assert isinstance(member, dict)
    status, mapped = source_flow._request_json(
        base_url,
        f"/api/project/{project_route}/source-mapping",
        method="POST",
        payload={
            "member_id": member["member_id"],
            "download_id": member["download_id"],
            "source_id": member["source_id"],
            "study_id": member["study_id"],
            "document_role": "MAIN",
            "archive_sha256": preflight["archive_sha256"],
        },
    )
    assert status == 200, mapped


def test_agent_parse_records_fallback_provenance_when_mineru_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_pdfs = tmp_path / "authorized-pdfs"
    authorized_pdfs.mkdir()
    (authorized_pdfs / "source.pdf").write_bytes(_text_pdf())
    project = tmp_path / "project"
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)

    bootstrap = FreshAgentBootstrap(project).start(
        topic="Fallback provenance review",
        authorized_pdf_folder=authorized_pdfs,
    )
    try:
        _confirm_main_source(str(bootstrap["dashboard_url"]), project.name)
        result = parse_project_sources(project, session_id="generator-parser-fallback")

        parser = result["parser"]
        assert parser["parser_mode"] == "FALLBACK"
        assert parser["fallback_reason"] == "MINERU_TOKEN_UNAVAILABLE"
        assert parser["sources"][0]["source_pdf_sha256"]
        assert parser["sources"][0]["page_count"] == 1
        assert parser["sources"][0]["output_artifact_sha256"]

        current = VersionContext.load(project).state()
        snapshot = VersionContext.load(project).view_version(current.current_version_id).snapshot
        agent_parse = snapshot["agent_parse"]
        assert agent_parse["parser"] == parser
        assert agent_parse["session_id"] == "generator-parser-fallback"
    finally:
        FreshAgentBootstrap.stop_owned_dashboard(int(bootstrap["dashboard_pid"]))
