from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from review_writer.delivery.docx_integrity import (
    DocxIntegrityError,
    validate_docx_integrity,
)


WORKFLOW_DIGEST = "a" * 64
IMAGE_BYTES = b"current-source-figure"
ATTRIBUTION = (
    "Source Figure Attribution: source-figure-1 | study-a | page 3 | "
    "Figure 1 | Reaction scope."
)
MARKDOWN = f"# Current review\n\nEvidence-bound sentence.\n\n{ATTRIBUTION}\n"


def _load_converter():
    path = Path(__file__).resolve().parents[1] / "skills/review-export-docx/scripts/md2docx.py"
    spec = importlib.util.spec_from_file_location("review_writer_md2docx", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _document_xml(*paragraphs: str, relationship_id: str | None = "rIdImage1") -> bytes:
    text = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs
    )
    drawing = ""
    if relationship_id is not None:
        drawing = (
            "<w:p><w:r><w:drawing><a:blip r:embed=\""
            f"{relationship_id}"
            "\"/></w:drawing></w:r></w:p>"
        )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        f"<w:body>{text}{drawing}</w:body></w:document>"
    ).encode("utf-8")


def _write_docx(
    path: Path,
    *,
    document_xml: bytes | None = None,
    image_bytes: bytes = IMAGE_BYTES,
    relationship_target: str = "media/image1.png",
    include_relationship: bool = True,
    extra_relationships: str = "",
    metadata: str = "current",
) -> Path:
    document_xml = document_xml or _document_xml(
        "Current review", "Evidence-bound sentence.", ATTRIBUTION
    )
    relationships = ""
    if include_relationship:
        relationships = (
            "<Relationship Id=\"rIdImage1\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" "
            f"Target=\"{relationship_target}\"/>"
        )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
            "<Default Extension=\"png\" ContentType=\"image/png\"/>"
            "</Types>",
        )
        package.writestr(
            "_rels/.rels",
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rIdOffice\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
            "Target=\"word/document.xml\"/>"
            "</Relationships>",
        )
        package.writestr("word/document.xml", document_xml)
        package.writestr(
            "word/_rels/document.xml.rels",
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            f"{relationships}{extra_relationships}</Relationships>",
        )
        package.writestr("word/media/image1.png", image_bytes)
        package.writestr("docProps/core.xml", f"<metadata>{metadata}</metadata>")
    return path


def _validate(path: Path, *, legacy_docx: Path | None = None) -> dict[str, object]:
    return validate_docx_integrity(
        path,
        markdown=MARKDOWN,
        expected_media_sha256=[hashlib.sha256(IMAGE_BYTES).hexdigest()],
        required_attributions=[ATTRIBUTION],
        workflow_digest=WORKFLOW_DIGEST,
        snapshot_workflow_digest=WORKFLOW_DIGEST,
        legacy_docx=legacy_docx,
    )


def test_integrity_checks_zip_xml_relationships_media_attribution_and_roundtrip(
    tmp_path: Path,
) -> None:
    report = _validate(_write_docx(tmp_path / "current.docx"))

    assert report["zip_valid"] is True
    assert report["relationships_valid"] is True
    assert report["markdown_roundtrip_match"] is True
    assert report["attribution_complete"] is True
    assert report["workflow_digest_match"] is True
    assert report["media_sha256"] == [hashlib.sha256(IMAGE_BYTES).hexdigest()]
    assert report["legacy_repackage_only"] is False


def test_integrity_normalizes_internal_claim_markers_on_both_sides(
    tmp_path: Path,
) -> None:
    markdown = (
        "# Current review\n\n"
        "First supported sentence. [evidence:evidence-one] "
        "Second supported sentence.\n\n"
        f"{ATTRIBUTION}\n"
    )
    docx = _write_docx(
        tmp_path / "claim-marker.docx",
        document_xml=_document_xml(
            "Current review",
            "First supported sentence. [evidence:evidence-one] Second supported sentence.",
            ATTRIBUTION,
        ),
    )

    report = validate_docx_integrity(
        docx,
        markdown=markdown,
        expected_media_sha256=[hashlib.sha256(IMAGE_BYTES).hexdigest()],
        required_attributions=[ATTRIBUTION],
        workflow_digest=WORKFLOW_DIGEST,
        snapshot_workflow_digest=WORKFLOW_DIGEST,
    )

    assert report["markdown_roundtrip_match"] is True


def test_integrity_rejects_unrelated_or_missing_media_relationship(tmp_path: Path) -> None:
    docx = _write_docx(tmp_path / "broken.docx", include_relationship=False)

    with pytest.raises(DocxIntegrityError, match="DOCX_RELATIONSHIPS_INVALID"):
        _validate(docx)


def test_integrity_allows_external_attached_template_relationship(tmp_path: Path) -> None:
    docx = _write_docx(
        tmp_path / "template.docx",
        extra_relationships=(
            '<Relationship Id="rIdTemplate" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
            'Target="file:///template.dotx" TargetMode="External"/>'
        ),
    )

    assert _validate(docx)["relationships_valid"] is True


@pytest.mark.parametrize(
    "relationship",
    [
        (
            '<Relationship Id="rIdTemplate" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
            'Target="https://example.invalid/template.dotx" TargetMode="External"/>'
        ),
        (
            '<Relationship Id="rIdLink" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            'Target="file:///private/source.txt" TargetMode="External"/>'
        ),
    ],
)
def test_integrity_rejects_unsafe_external_relationship_target(
    tmp_path: Path, relationship: str
) -> None:
    docx = _write_docx(
        tmp_path / "unsafe-external.docx", extra_relationships=relationship
    )

    with pytest.raises(DocxIntegrityError, match="DOCX_RELATIONSHIPS_INVALID"):
        _validate(docx)


def test_integrity_rejects_external_image_relationship(tmp_path: Path) -> None:
    docx = _write_docx(
        tmp_path / "external-image.docx",
        extra_relationships=(
            '<Relationship Id="rIdExternalImage" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="https://example.invalid/image.png" TargetMode="External"/>'
        ),
    )

    with pytest.raises(DocxIntegrityError, match="DOCX_RELATIONSHIPS_INVALID"):
        _validate(docx)


def test_integrity_rejects_markdown_that_is_not_present_in_document(tmp_path: Path) -> None:
    docx = _write_docx(
        tmp_path / "wrong-text.docx",
        document_xml=_document_xml("Old review", "Unrelated body", ATTRIBUTION),
    )

    with pytest.raises(DocxIntegrityError, match="DOCX_MARKDOWN_ROUNDTRIP_MISMATCH"):
        _validate(docx)


def test_integrity_rejects_document_with_markdown_chunks_out_of_order(
    tmp_path: Path,
) -> None:
    docx = _write_docx(
        tmp_path / "wrong-order.docx",
        document_xml=_document_xml(
            "Evidence-bound sentence.", "Current review", ATTRIBUTION
        ),
    )

    with pytest.raises(DocxIntegrityError, match="DOCX_MARKDOWN_ROUNDTRIP_MISMATCH"):
        _validate(docx)


def test_integrity_rejects_workflow_digest_drift(tmp_path: Path) -> None:
    docx = _write_docx(tmp_path / "stale.docx")

    with pytest.raises(DocxIntegrityError, match="RELEASE_WORKFLOW_STALE"):
        validate_docx_integrity(
            docx,
            markdown=MARKDOWN,
            expected_media_sha256=[hashlib.sha256(IMAGE_BYTES).hexdigest()],
            required_attributions=[ATTRIBUTION],
            workflow_digest=WORKFLOW_DIGEST,
            snapshot_workflow_digest="b" * 64,
        )


def test_integrity_rejects_template_identity_when_release_provenance_is_required(
    tmp_path: Path,
) -> None:
    docx = _write_docx(tmp_path / "template-identity.docx")

    with pytest.raises(DocxIntegrityError, match="DOCX_PROVENANCE_INVALID"):
        validate_docx_integrity(
            docx,
            markdown=MARKDOWN,
            expected_media_sha256=[hashlib.sha256(IMAGE_BYTES).hexdigest()],
            required_attributions=[ATTRIBUTION],
            workflow_digest=WORKFLOW_DIGEST,
            snapshot_workflow_digest=WORKFLOW_DIGEST,
            expected_project_id="project-a",
            expected_release_level="SELF_REVIEWED_DRAFT",
        )


def test_integrity_detects_legacy_repackage_even_when_outer_zip_changed(tmp_path: Path) -> None:
    legacy = _write_docx(tmp_path / "legacy.docx", metadata="legacy")
    current = _write_docx(tmp_path / "current.docx", metadata="new-package")
    assert legacy.read_bytes() != current.read_bytes()

    with pytest.raises(DocxIntegrityError, match="LEGACY_REPACKAGE_ONLY"):
        _validate(current, legacy_docx=legacy)


def test_integrity_reports_changed_document_and_media_against_legacy(tmp_path: Path) -> None:
    legacy = _write_docx(
        tmp_path / "legacy.docx",
        document_xml=_document_xml("Legacy review", relationship_id="rIdImage1"),
        image_bytes=b"legacy-figure",
    )
    current = _write_docx(tmp_path / "current.docx")

    report = _validate(current, legacy_docx=legacy)

    assert report["document_xml_changed"] is True
    assert report["media_changed"] is True
    assert report["legacy_repackage_only"] is False


def test_docx_converter_formats_ascii_scientific_exponents_as_runs() -> None:
    converter = _load_converter()

    segments = converter._split_script_segments("10^7 M-1 s-1")

    assert segments == [
        ("normal", "10"),
        ("superscript", "7"),
        ("normal", " M"),
        ("superscript", "-1"),
        ("normal", " s"),
        ("superscript", "-1"),
    ]
    assert converter._split_script_segments("analysis-1 remains bounded") == [
        ("normal", "analysis-1 remains bounded")
    ]


def test_docx_converter_keeps_image_caption_and_attribution_chain_together(
    tmp_path: Path,
) -> None:
    converter = _load_converter()
    image = tmp_path / "figure.png"
    image.write_bytes(
        __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    markdown = tmp_path / "manuscript.md"
    markdown.write_text(
        "# Project\n\n## Evidence synthesis\n\n![Reaction scope](figure.png)\n\n"
        "Figure 1. Reaction scope.\n\n"
        "Source Figure Attribution: figure-1 | study-a | page 3 | Figure 1\n\n"
        "## References\n\n[1] Synthetic reference.\n",
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"

    converter.convert(
        markdown,
        output,
        Path(converter.__file__).resolve().parent.parent / "review_template.docx",
    )

    from docx import Document

    paragraphs = Document(output).paragraphs
    image_index = next(
        index for index, paragraph in enumerate(paragraphs) if paragraph._p.xpath(".//w:drawing")
    )
    assert paragraphs[image_index].paragraph_format.keep_with_next is True
    assert paragraphs[image_index].paragraph_format.keep_together is True
    figure = next(paragraph for paragraph in paragraphs if paragraph.text.startswith("Figure 1."))
    attribution = next(
        paragraph for paragraph in paragraphs if paragraph.text.startswith("Source Figure Attribution:")
    )
    assert figure.paragraph_format.keep_with_next is True
    assert figure.paragraph_format.keep_together is True
    assert attribution.paragraph_format.keep_together is True
