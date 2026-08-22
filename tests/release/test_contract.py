from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from review_writer.release import ReleaseError, publish_release, resume_release


MARKDOWN = """# Review title

## Findings

AI_PROVISIONAL and GAP remain visible. This is NON_COMPARABLE evidence.

## References

1. A source-bound reference.
"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_publish_binds_same_version_markdown_to_editable_docx_and_manifest(
    tmp_path: Path,
) -> None:
    metadata = {
        "source_roles": {"source-1": "core", "source-2": "background"},
        "statuses": ["AI_PROVISIONAL", "GAP", "NON_COMPARABLE"],
        "lineage": {"parent_version": "v0", "divergent": True},
    }

    result = publish_release(
        tmp_path / "release-root",
        release_id="review-1",
        version_id="v1",
        markdown=MARKDOWN,
        metadata=metadata,
    )

    assert result["status"] == "PUBLISHED"
    assert result["write_mode"] == "WRITE"
    manifest_path = Path(result["manifest_path"])
    markdown_path = Path(result["markdown_path"])
    docx_path = Path(result["docx_path"])
    assert manifest_path.parent.name == "v1"
    assert markdown_path.parent == docx_path.parent == manifest_path.parent
    assert markdown_path.read_text(encoding="utf-8") == MARKDOWN

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "release-contract.v1"
    assert manifest["version_id"] == "v1"
    assert manifest["source_metadata"] == metadata
    assert manifest["artifacts"]["markdown"]["sha256"] == _sha256(
        MARKDOWN.encode("utf-8")
    )
    assert manifest["artifacts"]["docx"]["sha256"] == _sha256(
        docx_path.read_bytes()
    )
    readiness = manifest["release_readiness"]
    assert readiness["scope"] == "ENGINEERING_ONLY"
    assert readiness["release_ready"] is True
    assert readiness["layers"]["Engineering"] == "READY"
    assert readiness["layers"]["Product Use"] == "UNVERIFIED"
    assert readiness["layers"]["PUBLIC_E2E"] == "UNVERIFIED"
    assert readiness["layers"]["Independent Quality"] == "UNVERIFIED"
    assert readiness["layers"]["HUMAN_ACCEPTANCE"] == "UNVERIFIED"
    assert readiness["layers"]["scientific validity"] == "UNVERIFIED"

    with zipfile.ZipFile(docx_path) as package:
        names = set(package.namelist())
        assert {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
            "word/_rels/document.xml.rels",
        } <= names
        document_xml = package.read("word/document.xml")
    assert b"Review title" in document_xml
    assert b"AI_PROVISIONAL" in document_xml

    pointer = json.loads(
        (tmp_path / "release-root" / "current.json").read_text(encoding="utf-8")
    )
    assert pointer["version_id"] == "v1"
    assert pointer["manifest_sha256"] == _sha256(manifest_path.read_bytes())


def test_publish_is_idempotent_and_resume_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "release-root"
    first = publish_release(
        root,
        release_id="review-1",
        version_id="v1",
        markdown=MARKDOWN,
    )
    pointer_path = root / "current.json"
    before = pointer_path.read_bytes()

    second = publish_release(
        root,
        release_id="review-1",
        version_id="v1",
        markdown=MARKDOWN,
    )
    resumed = resume_release(root)

    assert first["write_mode"] == "WRITE"
    assert second["write_mode"] == "NONE"
    assert second["status"] == "UNCHANGED"
    assert resumed["write_mode"] == "NONE"
    assert resumed["status"] == "UNCHANGED"
    assert pointer_path.read_bytes() == before


def test_resume_fails_closed_when_a_bound_artifact_changes(tmp_path: Path) -> None:
    root = tmp_path / "release-root"
    result = publish_release(
        root,
        release_id="review-1",
        version_id="v1",
        markdown=MARKDOWN,
    )
    Path(result["markdown_path"]).write_text(MARKDOWN + "\nchanged\n", encoding="utf-8")

    with pytest.raises(ReleaseError) as exc_info:
        resume_release(root)

    assert exc_info.value.code == "RELEASE_ARTIFACT_STALE"


def test_optional_pdf_is_bound_without_becoming_required(tmp_path: Path) -> None:
    pdf_bytes = b"%PDF-1.7\nminimal generated output\n%%EOF\n"
    result = publish_release(
        tmp_path / "release-root",
        release_id="review-1",
        version_id="v1",
        markdown=MARKDOWN,
        pdf_bytes=pdf_bytes,
    )

    pdf_path = Path(result["pdf_path"])
    assert pdf_path.read_bytes() == pdf_bytes
    manifest = json.loads(
        Path(result["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["artifacts"]["pdf"]["sha256"] == _sha256(pdf_bytes)


def test_historical_version_is_inspectable_without_moving_current(tmp_path: Path) -> None:
    root = tmp_path / "release-root"
    publish_release(root, release_id="review-1", version_id="v1", markdown=MARKDOWN)
    publish_release(root, release_id="review-1", version_id="v2", markdown=MARKDOWN)
    pointer_path = root / "current.json"
    before = pointer_path.read_bytes()

    historical = resume_release(root, version_id="v1")

    assert historical["status"] == "HISTORICAL_INSPECT"
    assert historical["write_mode"] == "NONE"
    assert pointer_path.read_bytes() == before
