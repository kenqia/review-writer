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
