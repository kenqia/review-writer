#!/usr/bin/env python3
"""Synthetic, offline tests for the bounded manual source archive importer."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acquisition" / "import_manual_archive.py"
sys.path.insert(0, str(ROOT))

try:
    manual_archive = importlib.import_module("review_writer.acquisition.manual_archive")
except ModuleNotFoundError:
    manual_archive = None


def make_minimal_pdf() -> bytes:
    parts = [b"%PDF-1.4\n"]
    offsets = []
    for body in (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n",
    ):
        offsets.append(sum(len(part) for part in parts))
        parts.append(body)
    xref_offset = sum(len(part) for part in parts)
    parts.append(
        b"xref\n0 3\n0000000000 65535 f \n"
        + f"{offsets[0]:010d} 00000 n \n{offsets[1]:010d} 00000 n \n".encode("ascii")
        + b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return b"".join(parts)


def make_identity_pdf(*, doi: str | None = None, title: str | None = None) -> bytes:
    info_fields = []
    if doi:
        info_fields.append(f"/Subject (DOI: {doi})")
    if title:
        info_fields.append(f"/Title ({title})")
    parts = [b"%PDF-1.4\n"]
    offsets = []
    for body in (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n",
        ("3 0 obj\n<< " + " ".join(info_fields) + " >>\nendobj\n").encode("utf-8"),
    ):
        offsets.append(sum(len(part) for part in parts))
        parts.append(body)
    xref_offset = sum(len(part) for part in parts)
    parts.append(
        b"xref\n0 4\n0000000000 65535 f \n"
        + b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
        + b"trailer\n<< /Size 4 /Root 1 0 R /Info 3 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return b"".join(parts)


def make_real_identity_pdf(
    *, first_page_text: str = "Synthetic article", metadata_title: str | None = None
) -> bytes:
    """Build one real page with a compressed text stream and optional UTF-16 title metadata."""

    escaped = first_page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("ascii")
    compressed = zlib.compress(content)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(compressed)).encode("ascii")
        + b" /Filter /FlateDecode >>\nstream\n"
        + compressed
        + b"\nendstream",
    ]
    if metadata_title is not None:
        title_hex = (b"\xfe\xff" + metadata_title.encode("utf-16-be")).hex().upper().encode("ascii")
        objects.append(b"<< /Title <" + title_hex + b"> >>")

    parts = [b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"]
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(len(part) for part in parts)
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R".encode("ascii")
    if metadata_title is not None:
        trailer += f" /Info {len(objects)} 0 R".encode("ascii")
    trailer += b" >>"
    parts.append(
        f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
        + b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
        + b"trailer\n"
        + trailer
        + b"\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return b"".join(parts)


def make_docx() -> bytes:
    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/word/document.xml" ContentType="{content_type}"/>'
            "</Types>",
        )
        archive.writestr("word/document.xml", "<synthetic/>")
    return buffer.getvalue()


PDF_BYTES = make_minimal_pdf()
DOCX_BYTES = make_docx()


class ManualArchiveModuleContractTests(unittest.TestCase):
    def test_manual_archive_module_exists(self) -> None:
        self.assertIsNotNone(manual_archive)


@unittest.skipIf(manual_archive is None, "manual archive importer is not implemented yet")
class ManualArchiveImportTests(unittest.TestCase):
    def write_manifest(self, root: Path, rows: list[dict]) -> Path:
        path = root / "acquisition_manifest.json"
        path.write_text(
            json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": rows}),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def row(
        download_id: str,
        target_path: str,
        *,
        url: str | None = None,
        expected_format: str = "PDF",
        **extra,
    ) -> dict:
        return {
            "download_id": download_id,
            "study_id": download_id.split("_", 1)[0],
            "document_role": "SI" if expected_format != "PDF" else "MAIN",
            "url": url or f"https://example.org/{download_id.lower()}.{expected_format.lower()}",
            "target_path": target_path,
            "source_class": "LANDING_PAGE_ONLY",
            "expected_format": expected_format,
            **extra,
        }

    @staticmethod
    def write_zip(path: Path, members: list[tuple[str | zipfile.ZipInfo, bytes]]) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in members:
                archive.writestr(name, content)

    @staticmethod
    def result_by_id(receipt: dict) -> dict[str, dict]:
        return {row["download_id"]: row for row in receipt["results"]}

    @staticmethod
    def mark_zip_encrypted(path: Path) -> None:
        data = bytearray(path.read_bytes())
        for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            position = data.find(signature)
            if position < 0:
                raise AssertionError("synthetic ZIP header missing")
            flags = int.from_bytes(data[position + flag_offset : position + flag_offset + 2], "little")
            data[position + flag_offset : position + flag_offset + 2] = (flags | 0x1).to_bytes(2, "little")
        path.write_bytes(data)

    def test_successful_flat_zip_import_records_only_bounded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [self.row("D1_MAIN", "sources/D1/main.pdf", url="https://example.org/article.pdf")],
            )
            archive = root / "researcher_sources.zip"
            self.write_zip(archive, [("article.pdf", PDF_BYTES), ("notes.txt", b"not imported")])
            output_root = root / "acquired"

            receipt = manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertEqual(PDF_BYTES, (output_root / "sources/D1/main.pdf").read_bytes())
            self.assertEqual("IMPORTED", receipt["results"][0]["status"])
            self.assertEqual(1, receipt["unmatched_count"])
            self.assertEqual("manual-archive-import-receipt.v1", receipt["schema_version"])
            self.assertEqual("00_sources/manual_import_receipt.json", receipt["canonical_artifact"])
            self.assertEqual(manifest.name, receipt["manifest_basename"])
            self.assertEqual(archive.name, receipt["archive_basename"])
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), receipt["manifest_sha256"])
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), receipt["archive_sha256"])
            serialized = (output_root / "manual_import_receipt.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("notes.txt", serialized)

    def test_exact_target_path_and_casefolded_download_id_alias_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("EXACT_MAIN", "sources/exact/paper.pdf"),
                    self.row("ALIAS_MAIN", "sources/alias/main.pdf"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("sources/exact/paper.pdf", PDF_BYTES), ("alias_main.PDF", PDF_BYTES)],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual({"IMPORTED": 2}, receipt["counts"])
            self.assertTrue((root / "out/sources/exact/paper.pdf").is_file())
            self.assertTrue((root / "out/sources/alias/main.pdf").is_file())

    def test_exact_target_paths_win_when_declared_rows_share_a_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("ROW_A", "sources/A/MAIN.pdf"),
                    self.row("ROW_B", "sources/B/MAIN.pdf"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [
                    ("sources/A/MAIN.pdf", PDF_BYTES),
                    ("sources/B/MAIN.pdf", PDF_BYTES),
                ],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual({"IMPORTED": 2}, receipt["counts"])
            self.assertEqual(PDF_BYTES, (root / "out/sources/A/MAIN.pdf").read_bytes())
            self.assertEqual(PDF_BYTES, (root / "out/sources/B/MAIN.pdf").read_bytes())

    def test_shared_flat_basename_remains_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("ROW_A", "sources/A/MAIN.pdf"),
                    self.row("ROW_B", "sources/B/MAIN.pdf"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("MAIN.pdf", PDF_BYTES)])
            output_root = root / "out"

            receipt = manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertEqual({"AMBIGUOUS": 2}, receipt["counts"])
            self.assertEqual(1, receipt["unmatched_count"])
            self.assertFalse((output_root / "sources/A/MAIN.pdf").exists())
            self.assertFalse((output_root / "sources/B/MAIN.pdf").exists())

    def test_safe_archive_name_alias_and_docx_use_shared_structure_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row(
                        "SUPP_DOCX",
                        "sources/SUPP/supplement.docx",
                        expected_format="DOCX",
                        archive_names=["publisher-supplement.docx"],
                    )
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("download/publisher-supplement.docx", DOCX_BYTES)])

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("IMPORTED", receipt["results"][0]["status"])
            self.assertEqual(DOCX_BYTES, (root / "out/sources/SUPP/supplement.docx").read_bytes())

    def test_target_and_url_basename_collision_is_ambiguous_with_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("ROW_A", "sources/A/shared.pdf", url="https://example.org/a.pdf"),
                    self.row("ROW_B", "sources/B/b.pdf", url="https://example.org/shared.pdf"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("shared.pdf", PDF_BYTES)])
            output_root = root / "out"

            receipt = manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertEqual({"AMBIGUOUS": 2}, receipt["counts"])
            self.assertFalse((output_root / "sources/A/shared.pdf").exists())
            self.assertFalse((output_root / "sources/B/b.pdf").exists())
            self.assertEqual(1, receipt["unmatched_count"])

    def test_multiple_members_for_one_row_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("DUP_MAIN", "sources/DUP/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("DUP_MAIN.pdf", PDF_BYTES), ("main.pdf", PDF_BYTES)])

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("AMBIGUOUS", receipt["results"][0]["status"])
            self.assertEqual(2, receipt["unmatched_count"])
            self.assertFalse((root / "out/sources/DUP/main.pdf").exists())

    def test_doi_filename_matches_after_exact_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [self.row("OPAQUE_MAIN", "sources/S1/MAIN.pdf", doi="10.1000/abc.1")],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("10.1000_ABC.1.pdf", PDF_BYTES)])

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            result = receipt["results"][0]
            self.assertEqual("IMPORTED", result["status"])
            self.assertEqual("DOI_FILENAME", result["match_basis"])

    def test_pdf_embedded_doi_matches_when_filename_is_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [self.row("S2_MAIN", "sources/S2/MAIN.pdf", doi="10.1000/embedded")],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("download.pdf", make_real_identity_pdf(first_page_text="DOI: 10.1000/embedded"))],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("PDF_DOI", receipt["results"][0]["match_basis"])

    def test_compressed_first_page_doi_is_parsed_by_the_real_pdf_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [self.row("COMPRESSED_MAIN", "sources/C/MAIN.pdf", doi="10.1000/compressed.1")],
            )
            archive = root / "sources.zip"
            pdf = make_real_identity_pdf(
                first_page_text="Article DOI: 10.1000/compressed.1"
            )
            self.assertNotIn(b"10.1000/compressed.1", pdf)
            self.write_zip(archive, [("opaque.pdf", pdf)])

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("PDF_DOI", receipt["results"][0]["match_basis"])

    def test_utf16_unicode_pdf_metadata_title_matches_uniquely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            title = "铜催化羧化：范围与机理"
            manifest = self.write_manifest(
                root,
                [self.row("UNICODE_MAIN", "sources/U/MAIN.pdf", title=title)],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("opaque.pdf", make_real_identity_pdf(metadata_title=title))],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("PDF_TITLE", receipt["results"][0]["match_basis"])

    def test_unique_normalized_title_matches_but_title_collision_never_guesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", title="Copper–Catalyzed Carboxylation"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", title="A Different Study"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [
                    (
                        "opaque.pdf",
                        make_real_identity_pdf(
                            metadata_title="Copper-Catalyzed   Carboxylation"
                        ),
                    )
                ],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            results = self.result_by_id(receipt)
            self.assertEqual("PDF_TITLE", results["A_MAIN"]["match_basis"])
            self.assertEqual("MISSING", results["B_MAIN"]["status"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", title="Shared Study"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", title="Shared Study"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("opaque.pdf", make_real_identity_pdf(metadata_title="Shared Study"))],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual({"AMBIGUOUS": 2}, receipt["counts"])
            self.assertEqual(1, len(receipt["unresolved"]))
            self.assertEqual("AMBIGUOUS_PDF_TITLE", receipt["unresolved"][0]["reason"])
            self.assertEqual(["A_MAIN", "B_MAIN"], receipt["unresolved"][0]["download_ids"])
            self.assertEqual("opaque.pdf", receipt["unresolved"][0]["member_display_name"])
            self.assertRegex(receipt["unresolved"][0]["member_id"], r"^MEMBER-\d{4}$")
            self.assertNotIn(str(root), json.dumps(receipt))

    def test_unique_normalized_title_can_come_from_the_pdf_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row(
                        "TITLE_MAIN",
                        "sources/TITLE/MAIN.pdf",
                        title="Electrochemical Reductive Carboxylation: Scope and Mechanism",
                    )
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("Electrochemical Reductive Carboxylation - Scope and Mechanism.pdf", PDF_BYTES)],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            result = receipt["results"][0]
            self.assertEqual("IMPORTED", result["status"])
            self.assertEqual("PDF_TITLE", result["match_basis"])

    def test_explicit_member_override_resolves_only_a_listed_candidate_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", title="Shared Study"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", title="Shared Study"),
                ],
            )
            archive = root / "sources.zip"
            payload = make_real_identity_pdf(metadata_title="Shared Study")
            self.write_zip(archive, [("opaque.pdf", payload)])
            output_root = root / "out"
            first = manual_archive.import_manual_archive(manifest, archive, output_root)
            unresolved = first["unresolved"][0]

            second = manual_archive.import_manual_archive(
                manifest,
                archive,
                output_root,
                member_overrides={unresolved["member_id"]: "B_MAIN"},
            )

            results = self.result_by_id(second)
            self.assertEqual("MISSING", results["A_MAIN"]["status"])
            self.assertEqual("IMPORTED", results["B_MAIN"]["status"])
            self.assertEqual("USER_CONFIRMED", results["B_MAIN"]["match_basis"])
            self.assertEqual(payload, (output_root / "sources/B/MAIN.pdf").read_bytes())
            self.assertFalse((output_root / "sources/A/MAIN.pdf").exists())
            self.assertEqual([], second["unresolved"])
            self.assertEqual(
                [{"member_id": unresolved["member_id"], "download_id": "B_MAIN"}],
                second["confirmed_mappings"],
            )
            persisted = json.loads(
                (output_root / "manual_import_receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(second, persisted)
            self.assertNotIn(str(root), json.dumps(second))

    def test_confirmed_member_overrides_can_be_replayed_while_resolving_the_next_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", title="Shared Study"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", title="Shared Study"),
                ],
            )
            archive = root / "sources.zip"
            first_payload = make_real_identity_pdf(
                first_page_text="First member", metadata_title="Shared Study"
            )
            second_payload = make_real_identity_pdf(
                first_page_text="Second member", metadata_title="Shared Study"
            )
            self.write_zip(
                archive,
                [("opaque-a.pdf", first_payload), ("opaque-b.pdf", second_payload)],
            )
            output_root = root / "out"
            initial = manual_archive.import_manual_archive(manifest, archive, output_root)
            first_member, second_member = [row["member_id"] for row in initial["unresolved"]]

            first = manual_archive.import_manual_archive(
                manifest,
                archive,
                output_root,
                member_overrides={first_member: "A_MAIN"},
            )
            self.assertEqual(["B_MAIN"], first["unresolved"][0]["download_ids"])

            second = manual_archive.import_manual_archive(
                manifest,
                archive,
                output_root,
                member_overrides={first_member: "A_MAIN", second_member: "B_MAIN"},
            )

            self.assertEqual([], second["unresolved"])
            self.assertEqual(
                [
                    {"member_id": first_member, "download_id": "A_MAIN"},
                    {"member_id": second_member, "download_id": "B_MAIN"},
                ],
                second["confirmed_mappings"],
            )
            self.assertEqual(first_payload, (output_root / "sources/A/MAIN.pdf").read_bytes())
            self.assertEqual(second_payload, (output_root / "sources/B/MAIN.pdf").read_bytes())

    def test_explicit_member_override_rejects_unlisted_candidate_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", title="Shared Study"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", title="Shared Study"),
                    self.row("C_MAIN", "sources/C/MAIN.pdf", title="Different Study"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("opaque.pdf", make_real_identity_pdf(metadata_title="Shared Study"))],
            )
            output_root = root / "out"
            first = manual_archive.import_manual_archive(manifest, archive, output_root)
            receipt_path = output_root / "manual_import_receipt.json"
            before = receipt_path.read_bytes()

            with self.assertRaises(manual_archive.ManualArchiveError):
                manual_archive.import_manual_archive(
                    manifest,
                    archive,
                    output_root,
                    member_overrides={first["unresolved"][0]["member_id"]: "C_MAIN"},
                )

            self.assertEqual(before, receipt_path.read_bytes())
            self.assertFalse((output_root / "sources/A/MAIN.pdf").exists())
            self.assertFalse((output_root / "sources/B/MAIN.pdf").exists())
            self.assertFalse((output_root / "sources/C/MAIN.pdf").exists())

    def test_pdf_tool_failure_stays_unresolved_with_compatible_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [self.row("FAILED_PARSE_MAIN", "sources/F/MAIN.pdf")],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("opaque.pdf", PDF_BYTES)])

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("MISSING", receipt["results"][0]["status"])
            self.assertEqual(
                [
                    {
                        "reason": "NO_DETERMINISTIC_MATCH",
                        "member_id": "MEMBER-0001",
                        "member_display_name": "opaque.pdf",
                        "download_ids": ["FAILED_PARSE_MAIN"],
                    }
                ],
                receipt["unresolved"],
            )

    def test_conflicting_pdf_identity_is_visible_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", doi="10.1000/a"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", doi="10.1000/b"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [
                    (
                        "10.1000_a.pdf",
                        make_real_identity_pdf(first_page_text="DOI: 10.1000/b"),
                    )
                ],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual(1, len(receipt["unresolved"]))
            self.assertEqual("CONFLICTING_MEMBER_IDENTITY", receipt["unresolved"][0]["reason"])
            self.assertFalse((root / "out/sources/A/MAIN.pdf").exists())
            self.assertFalse((root / "out/sources/B/MAIN.pdf").exists())

    def test_exact_path_alias_wins_over_conflicting_embedded_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("A_MAIN", "sources/A/MAIN.pdf", doi="10.1000/a"),
                    self.row("B_MAIN", "sources/B/MAIN.pdf", doi="10.1000/b"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [
                    (
                        "sources/A/MAIN.pdf",
                        make_real_identity_pdf(first_page_text="DOI: 10.1000/b"),
                    )
                ],
            )

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            results = self.result_by_id(receipt)
            self.assertEqual("IMPORTED", results["A_MAIN"]["status"])
            self.assertEqual("EXACT_ALIAS", results["A_MAIN"]["match_basis"])
            self.assertEqual("MISSING", results["B_MAIN"]["status"])
            self.assertEqual([], receipt["unresolved"])

    def test_archive_names_must_be_safe_basenames(self) -> None:
        unsafe_values = (
            "../publisher.pdf",
            "nested/publisher.pdf",
            "publisher\\paper.pdf",
            "/absolute.pdf",
            "CON.pdf",
            "control\x01.pdf",
        )
        for value in unsafe_values:
            with self.subTest(value=repr(value)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [self.row("D1", "sources/D1/main.pdf", archive_names=[value])],
                )
                archive = root / "sources.zip"
                self.write_zip(archive, [("D1.pdf", PDF_BYTES)])

                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(manifest, archive, root / "out")

                self.assertFalse((root / "out").exists())

    def test_unsafe_members_fail_preflight_with_zero_target_writes(self) -> None:
        unsafe_members: list[tuple[str, str | zipfile.ZipInfo]] = [
            ("traversal", "../D1.pdf"),
            ("absolute", "/D1.pdf"),
            ("drive_absolute", "C:/D1.pdf"),
            ("backslash", "folder\\D1.pdf"),
            ("dot", "folder/./D1.pdf"),
            ("control", "D1\x01.pdf"),
            ("windows_reserved", "AUX.pdf"),
        ]
        symlink = zipfile.ZipInfo("D1.pdf")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        fifo = zipfile.ZipInfo("D1.pdf")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
        unsafe_members.extend((("symlink", symlink), ("special", fifo)))

        for label, member in unsafe_members:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
                archive = root / "sources.zip"
                self.write_zip(archive, [(member, PDF_BYTES)])

                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(manifest, archive, root / "out")

                self.assertFalse((root / "out").exists())

    def test_encrypted_duplicate_and_invalid_zip_fail_preflight(self) -> None:
        cases = ("encrypted", "duplicate", "invalid")
        for label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
                archive = root / "sources.zip"
                if label == "encrypted":
                    self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
                    self.mark_zip_encrypted(archive)
                elif label == "duplicate":
                    self.write_zip(archive, [("Paper.pdf", PDF_BYTES), ("paper.pdf", PDF_BYTES)])
                else:
                    archive.write_bytes(b"not-a-zip")

                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(manifest, archive, root / "out")

                self.assertFalse((root / "out").exists())

    def test_member_count_member_bytes_and_total_bytes_are_bounded(self) -> None:
        cases = (
            ("members", [("one.bin", b"1"), ("two.bin", b"2")], {"max_members": 1}),
            ("member_bytes", [("large.bin", b"12345")], {"max_member_bytes": 4}),
            ("total_bytes", [("one.bin", b"123"), ("two.bin", b"456")], {"max_total_bytes": 5}),
        )
        for label, members, policy in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
                archive = root / "sources.zip"
                self.write_zip(archive, members)

                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(manifest, archive, root / "out", **policy)

                self.assertFalse((root / "out").exists())

    def test_raw_archive_bytes_are_checked_before_hashing_or_zip_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
            output_root = root / "out"

            with mock.patch.object(
                manual_archive.hashlib,
                "sha256",
                side_effect=AssertionError("oversized archive must not be hashed"),
            ):
                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(
                        manifest,
                        archive,
                        output_root,
                        max_archive_bytes=archive.stat().st_size - 1,
                    )

            self.assertFalse(output_root.exists())

    def test_archive_growth_during_descriptor_hashing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
            initial_size = archive.stat().st_size
            output_root = root / "out"
            real_sha256 = hashlib.sha256
            appended = False

            class GrowingDigest:
                def __init__(self, data: bytes = b"") -> None:
                    self._digest = real_sha256(data)

                def update(self, chunk: bytes) -> None:
                    nonlocal appended
                    self._digest.update(chunk)
                    if not appended:
                        appended = True
                        with archive.open("ab") as handle:
                            handle.write(b"growth-after-fstat")

                def hexdigest(self) -> str:
                    return self._digest.hexdigest()

            with mock.patch.object(manual_archive.hashlib, "sha256", side_effect=GrowingDigest):
                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(
                        manifest,
                        archive,
                        output_root,
                        max_archive_bytes=initial_size,
                    )

            self.assertTrue(appended)
            self.assertFalse(output_root.exists())

    def test_archive_growth_after_hash_before_zip_parse_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
            initial_size = archive.stat().st_size
            output_root = root / "out"
            real_zip_file = zipfile.ZipFile
            appended = False

            def growing_zip_file(file, *args, **kwargs):
                nonlocal appended
                if not appended and hasattr(file, "fileno"):
                    appended = True
                    with archive.open("ab") as handle:
                        handle.write(b"growth-after-hash")
                return real_zip_file(file, *args, **kwargs)

            with mock.patch.object(manual_archive.zipfile, "ZipFile", side_effect=growing_zip_file):
                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive.import_manual_archive(
                        manifest,
                        archive,
                        output_root,
                        max_archive_bytes=initial_size,
                    )

            self.assertTrue(appended)
            self.assertFalse(output_root.exists())

    def test_html_disguised_as_pdf_and_hash_mismatch_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    self.row("HTML_MAIN", "sources/HTML/main.pdf"),
                    self.row(
                        "HASH_MAIN",
                        "sources/HASH/main.pdf",
                        expected_sha256=hashlib.sha256(b"different").hexdigest(),
                    ),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("HTML_MAIN.pdf", b"<!doctype html>not a pdf"), ("HASH_MAIN.pdf", PDF_BYTES)])
            output_root = root / "out"

            receipt = manual_archive.import_manual_archive(manifest, archive, output_root)
            results = self.result_by_id(receipt)

            self.assertEqual("FORMAT_MISMATCH", results["HTML_MAIN"]["status"])
            self.assertEqual("HASH_MISMATCH", results["HASH_MAIN"]["status"])
            self.assertFalse((output_root / "sources/HTML/main.pdf").exists())
            self.assertFalse((output_root / "sources/HASH/main.pdf").exists())

    def test_existing_valid_and_invalid_targets_remain_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out"
            valid_target = output_root / "sources/VALID/main.pdf"
            invalid_target = output_root / "sources/INVALID/main.pdf"
            valid_target.parent.mkdir(parents=True)
            invalid_target.parent.mkdir(parents=True)
            valid_target.write_bytes(PDF_BYTES)
            invalid_bytes = b"existing invalid sentinel"
            invalid_target.write_bytes(invalid_bytes)
            manifest = self.write_manifest(
                root,
                [
                    self.row("VALID_MAIN", "sources/VALID/main.pdf"),
                    self.row("INVALID_MAIN", "sources/INVALID/main.pdf"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("VALID_MAIN.pdf", b"replacement"), ("INVALID_MAIN.pdf", PDF_BYTES)])

            receipt = manual_archive.import_manual_archive(manifest, archive, output_root)
            results = self.result_by_id(receipt)

            self.assertEqual("VERIFIED_EXISTING", results["VALID_MAIN"]["status"])
            self.assertEqual("INVALID_EXISTING", results["INVALID_MAIN"]["status"])
            self.assertEqual("EXISTING_FORMAT_MISMATCH", results["INVALID_MAIN"]["reason"])
            self.assertEqual(PDF_BYTES, valid_target.read_bytes())
            self.assertEqual(invalid_bytes, invalid_target.read_bytes())

    def test_existing_hash_drift_is_explicit_and_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out"
            target = output_root / "sources/D1/main.pdf"
            target.parent.mkdir(parents=True)
            target.write_bytes(PDF_BYTES)
            manifest = self.write_manifest(
                root,
                [
                    self.row(
                        "D1",
                        "sources/D1/main.pdf",
                        expected_sha256=hashlib.sha256(b"other").hexdigest(),
                    )
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", b"replacement")])

            receipt = manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertEqual("INVALID_EXISTING", receipt["results"][0]["status"])
            self.assertEqual("EXISTING_HASH_MISMATCH", receipt["results"][0]["reason"])
            self.assertEqual(PDF_BYTES, target.read_bytes())

    def test_missing_rows_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("unrelated.txt", b"safe unmatched")])

            receipt = manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertEqual("MISSING", receipt["results"][0]["status"])
            self.assertEqual(1, receipt["unmatched_count"])

    def test_receipt_publication_is_atomic_and_reserved_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out"
            target = output_root / "sources/D1/main.pdf"
            target.parent.mkdir(parents=True)
            target.write_bytes(PDF_BYTES)
            old_receipt = b"previous receipt sentinel\n"
            receipt_path = output_root / "manual_import_receipt.json"
            receipt_path.write_bytes(old_receipt)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [])
            real_replace = os.replace

            def fail_receipt_replace(source, destination):
                if Path(destination).name == "manual_import_receipt.json":
                    raise OSError("synthetic receipt replacement failure")
                return real_replace(source, destination)

            with mock.patch.object(manual_archive.os, "replace", side_effect=fail_receipt_replace):
                with self.assertRaises(OSError):
                    manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertEqual(old_receipt, receipt_path.read_bytes())
            self.assertEqual(PDF_BYTES, target.read_bytes())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [self.row("RESERVED", "manual_import_receipt.json")],
            )
            archive = root / "sources.zip"
            self.write_zip(archive, [("RESERVED.pdf", PDF_BYTES)])

            with self.assertRaises(manual_archive.ManualArchiveError):
                manual_archive.import_manual_archive(manifest, archive, root / "out")

            self.assertFalse((root / "out").exists())

    def test_second_target_publication_failure_rolls_back_all_new_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out"
            output_root.mkdir()
            receipt_path = output_root / "manual_import_receipt.json"
            old_receipt = b"previous receipt sentinel\n"
            receipt_path.write_bytes(old_receipt)
            manifest = self.write_manifest(
                root,
                [
                    self.row("ROW_A", "sources/A/MAIN.pdf"),
                    self.row("ROW_B", "sources/B/MAIN.pdf"),
                ],
            )
            archive = root / "sources.zip"
            self.write_zip(
                archive,
                [("ROW_A.pdf", PDF_BYTES), ("ROW_B.pdf", PDF_BYTES)],
            )
            real_link = os.link
            calls = 0

            def fail_second_link(source, destination, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic second target publication failure")
                return real_link(source, destination, *args, **kwargs)

            with mock.patch.object(manual_archive.os, "link", side_effect=fail_second_link):
                with self.assertRaises(OSError):
                    manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertEqual(2, calls)
            self.assertFalse((output_root / "sources/A/MAIN.pdf").exists())
            self.assertFalse((output_root / "sources/B/MAIN.pdf").exists())
            self.assertEqual(old_receipt, receipt_path.read_bytes())

    def test_receipt_replace_failure_rolls_back_new_targets_and_preserves_old_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out"
            output_root.mkdir()
            receipt_path = output_root / "manual_import_receipt.json"
            old_receipt = b"previous receipt sentinel\n"
            receipt_path.write_bytes(old_receipt)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/MAIN.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
            real_replace = os.replace

            def fail_receipt_replace(source, destination):
                if Path(destination).name == "manual_import_receipt.json":
                    raise OSError("synthetic receipt replacement failure")
                return real_replace(source, destination)

            with mock.patch.object(manual_archive.os, "replace", side_effect=fail_receipt_replace):
                with self.assertRaises(OSError):
                    manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertFalse((output_root / "sources/D1/MAIN.pdf").exists())
            self.assertEqual(old_receipt, receipt_path.read_bytes())

    def test_publication_revalidates_a_replaced_output_root_before_linking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out"
            target_parent = output_root / "sources/D1"
            target_parent.mkdir(parents=True)
            external = root / "external"
            (external / "sources/D1").mkdir(parents=True)
            staged = root / "staged.pdf"
            staged.write_bytes(PDF_BYTES)
            prepared = [{"row": {"target_path": "sources/D1/MAIN.pdf"}}]
            real_stage_receipt = manual_archive._stage_receipt

            def stage_then_replace_root(root_path, receipt):
                destination, staged_receipt = real_stage_receipt(root_path, receipt)
                moved = root / "moved-output"
                root_path.rename(moved)
                root_path.symlink_to(external, target_is_directory=True)
                return destination, staged_receipt

            def forbid_external_link(source, destination, *args, **kwargs):
                raise AssertionError(f"publication reached replaced root: {Path(destination).name}")

            with mock.patch.object(
                manual_archive,
                "_stage_receipt",
                side_effect=stage_then_replace_root,
            ), mock.patch.object(manual_archive.os, "link", side_effect=forbid_external_link):
                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive._publish_transaction(
                        output_root,
                        prepared,
                        {0: (staged, hashlib.sha256(PDF_BYTES).hexdigest(), len(PDF_BYTES))},
                        {"schema_version": "manual-archive-import-receipt.v1"},
                    )

            self.assertFalse((external / "sources/D1/MAIN.pdf").exists())

    def test_publication_revalidates_a_replaced_output_parent_before_linking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            container = root / "container"
            output_root = container / "out"
            (output_root / "sources/D1").mkdir(parents=True)
            external_container = root / "external-container"
            (external_container / "out/sources/D1").mkdir(parents=True)
            staged = root / "staged.pdf"
            staged.write_bytes(PDF_BYTES)
            prepared = [{"row": {"target_path": "sources/D1/MAIN.pdf"}}]
            real_stage_receipt = manual_archive._stage_receipt

            def stage_then_replace_parent(root_path, receipt):
                destination, staged_receipt = real_stage_receipt(root_path, receipt)
                container.rename(root / "moved-container")
                container.symlink_to(external_container, target_is_directory=True)
                return destination, staged_receipt

            def forbid_external_link(source, destination, *args, **kwargs):
                raise AssertionError(f"publication reached replaced parent: {Path(destination).name}")

            with mock.patch.object(
                manual_archive,
                "_stage_receipt",
                side_effect=stage_then_replace_parent,
            ), mock.patch.object(manual_archive.os, "link", side_effect=forbid_external_link):
                with self.assertRaises(manual_archive.ManualArchiveError):
                    manual_archive._publish_transaction(
                        output_root,
                        prepared,
                        {0: (staged, hashlib.sha256(PDF_BYTES).hexdigest(), len(PDF_BYTES))},
                        {"schema_version": "manual-archive-import-receipt.v1"},
                    )

            self.assertFalse((external_container / "out/sources/D1/MAIN.pdf").exists())
            self.assertEqual(PDF_BYTES, staged.read_bytes())

    def test_nonportable_download_id_is_rejected_before_output_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("D／1", "sources/D1/MAIN.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
            output_root = root / "out"

            with self.assertRaises(manual_archive.ManualArchiveError):
                manual_archive.import_manual_archive(manifest, archive, output_root)

            self.assertFalse(output_root.exists())

    def test_cli_success_summary_and_errors_do_not_expose_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
            archive = root / "sources.zip"
            self.write_zip(archive, [("D1.pdf", PDF_BYTES)])
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest), "--archive", str(archive), "--output-root", str(root / "out")],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual({"IMPORTED": 1}, summary["counts"])
            self.assertEqual(0, summary["unmatched_count"])
            self.assertNotIn(str(root), completed.stdout + completed.stderr)

        with tempfile.TemporaryDirectory(prefix="manual-import-sensitive-marker-") as tmp:
            root = Path(tmp)
            manifest = root / "unsafe-manifest.json"
            manifest.write_text('{"secret":"do-not-echo"}', encoding="utf-8")
            archive = root / "unsafe-archive.zip"
            archive.write_bytes(b"not-a-zip")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest), "--archive", str(archive), "--output-root", str(root / "out")],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(2, completed.returncode)
            self.assertEqual("error: manual archive import failed\n", completed.stderr)
            self.assertNotIn("sensitive-marker", completed.stdout + completed.stderr)
            self.assertNotIn("do-not-echo", completed.stdout + completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_cli_rejects_policy_values_above_hard_ceilings_without_leaking_them(self) -> None:
        options = (
            ("--max-archive-bytes", manual_archive.HARD_MAX_ARCHIVE_BYTES + 1),
            ("--max-members", manual_archive.HARD_MAX_MEMBERS + 1),
            ("--max-member-bytes", manual_archive.HARD_MAX_MEMBER_BYTES + 1),
            ("--max-total-bytes", manual_archive.HARD_MAX_TOTAL_BYTES + 1),
        )
        for option, value in options:
            with self.subTest(option=option), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(root, [self.row("D1", "sources/D1/main.pdf")])
                archive = root / "sources.zip"
                self.write_zip(archive, [("D1.pdf", PDF_BYTES)])

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--manifest",
                        str(manifest),
                        "--archive",
                        str(archive),
                        "--output-root",
                        str(root / "out"),
                        option,
                        str(value),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(2, completed.returncode)
                self.assertEqual("error: manual archive import failed\n", completed.stderr)
                self.assertNotIn(str(value), completed.stdout + completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
