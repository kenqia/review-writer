from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_writer.acquisition import public_corpus
from review_writer.acquisition.public_corpus import ManifestError, acquire_manifest


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


def make_ooxml_with_content_types(main_part: str, content_types_xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr(main_part, "<synthetic/>")
    return buffer.getvalue()


def make_ooxml_bytes(main_part: str, content_type: str) -> bytes:
    return make_ooxml_with_content_types(
        main_part,
        f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/{main_part}" ContentType="{content_type}"/></Types>',
    )


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
DOCX_BYTES = make_ooxml_bytes("word/document.xml", DOCX_MIME)
XLSX_BYTES = make_ooxml_bytes("xl/workbook.xml", XLSX_MIME)
CORRUPT_ZIP_BYTES = b"PK\x03\x04not-a-valid-zip"
MALFORMED_TYPES_DOCX_BYTES = make_ooxml_with_content_types("word/document.xml", f"<Types>{DOCX_MIME}")
FAKE_MIME_DOCX_BYTES = make_ooxml_with_content_types(
    "word/document.xml",
    f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="txt" ContentType="{DOCX_MIME}"/><Override PartName="/word/document.xml" ContentType="application/octet-stream"/></Types>',
)
WRONG_MAIN_TYPE_DOCX_BYTES = make_ooxml_with_content_types(
    "word/document.xml",
    f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="{XLSX_MIME}"/><Override PartName="/other.xml" ContentType="{DOCX_MIME}"/></Types>',
)
FOREIGN_NAMESPACE_DOCX_BYTES = make_ooxml_with_content_types(
    "word/document.xml",
    f'<Types xmlns="https://example.com/not-openxml-content-types"><Override PartName="/word/document.xml" ContentType="{DOCX_MIME}"/></Types>',
)


class FixtureHandler(BaseHTTPRequestHandler):
    pdf_requests = 0
    query_pdf_requests = 0
    redirect_loop_requests = 0
    redirect_new_credential_requests = 0
    redirect_sensitive_requests = 0
    redirect_target_url = ""

    def do_GET(self):  # noqa: N802 - stdlib handler contract
        content_length_headers = None
        chunked = False
        if self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        elif self.path == "/paper.pdf":
            type(self).pdf_requests += 1
            body = PDF_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/truncated.pdf":
            body = b"%PDF-1.4\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/too-short.pdf":
            body = b"%PDF-%%EOF"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/no-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = []
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/chunked.pdf":
            body = PDF_BYTES
            content_length_headers = []
            chunked = True
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Transfer-Encoding", "chunked")
        elif self.path == "/invalid-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = ["content-length-secret"]
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/negative-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = ["-1"]
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/duplicate-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = [str(len(body)), str(len(body))]
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/conflicting-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = [str(len(body)), str(len(body) + 1)]
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/over-limit-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = [str(len(body) + 1)]
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/mismatched-content-length.pdf":
            body = PDF_BYTES
            content_length_headers = [str(len(body) + 10)]
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/redirect-sensitive":
            body = b""
            self.send_response(302)
            self.send_header("Location", "/paper.pdf?token=redirect-secret")
        elif self.path == "/redirect-new-credential":
            body = b""
            self.send_response(302)
            self.send_header("Location", "/paper.pdf?download_sig=redirect-credential-secret")
        elif self.path == "/redirect-loop":
            type(self).redirect_loop_requests += 1
            body = b""
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
        elif self.path == "/redirect-other-origin":
            body = b""
            self.send_response(302)
            self.send_header("Location", type(self).redirect_target_url)
        elif self.path.startswith("/paper.pdf?token="):
            type(self).redirect_sensitive_requests += 1
            body = PDF_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path.startswith("/paper.pdf?download_sig="):
            type(self).redirect_new_credential_requests += 1
            body = PDF_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path.startswith("/paper.pdf?"):
            type(self).query_pdf_requests += 1
            body = PDF_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/supp.docx":
            body = DOCX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif self.path == "/supp.xlsx":
            body = XLSX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif self.path == "/corrupt.docx":
            body = CORRUPT_ZIP_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif self.path == "/xlsx-as-docx.docx":
            body = XLSX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif self.path == "/malformed-types.docx":
            body = MALFORMED_TYPES_DOCX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif self.path == "/fake-mime.docx":
            body = FAKE_MIME_DOCX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif self.path == "/wrong-main-type.docx":
            body = WRONG_MAIN_TYPE_DOCX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif self.path == "/foreign-namespace.docx":
            body = FOREIGN_NAMESPACE_DOCX_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            body = b"login required"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        if content_length_headers is None:
            content_length_headers = [str(len(body))]
        for content_length in content_length_headers:
            self.send_header("Content-Length", content_length)
        self.end_headers()
        if chunked:
            self.wfile.write(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n0\r\n\r\n")
        else:
            self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class PublicCorpusAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def write_manifest(self, root: Path, downloads: list[dict]) -> Path:
        path = root / "manifest.json"
        path.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": downloads}))
        return path

    def test_downloads_pdf_and_idempotently_verifies_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{
                    "download_id": "S001_MAIN",
                    "study_id": "S001",
                    "document_role": "MAIN",
                    "url": self.base_url + "/paper.pdf",
                    "target_path": "sources/S001/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                }],
            )
            FixtureHandler.pdf_requests = 0

            first = acquire_manifest(manifest, root / "acquired")
            second = acquire_manifest(manifest, root / "acquired")

            target = root / "acquired/sources/S001/MAIN.pdf"
            self.assertEqual(target.read_bytes(), PDF_BYTES)
            self.assertEqual(first["results"][0]["status"], "DOWNLOADED")
            self.assertEqual(second["results"][0]["status"], "VERIFIED_EXISTING")
            self.assertEqual(second["results"][0]["sha256"], hashlib.sha256(PDF_BYTES).hexdigest())
            self.assertEqual(FixtureHandler.pdf_requests, 1)

    def test_non_pdf_response_enters_manual_queue_without_saved_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{
                    "download_id": "S002_MAIN",
                    "study_id": "S002",
                    "document_role": "MAIN",
                    "url": self.base_url + "/login",
                    "target_path": "sources/S002/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                }],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "MANUAL_OR_AUTHORIZED_ACCESS_REQUIRED")
            self.assertEqual(receipt["results"][0]["reason"], "RESPONSE_NOT_PDF")
            self.assertFalse((root / "acquired/sources/S002/MAIN.pdf").exists())
            self.assertTrue((root / "acquired/manual_acquisition.tsv").is_file())
            self.assertTrue((root / "acquired/manual_acquisition.html").is_file())

    def test_truncated_downloaded_and_existing_pdfs_are_rejected(self):
        download_cases = ["/truncated.pdf", "/too-short.pdf"]
        for index, route in enumerate(download_cases):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target_path = f"sources/PDF_TRUNCATED_{index}/MAIN.pdf"
                manifest = self.write_manifest(
                    root,
                    [{"download_id": f"PDF_TRUNCATED_{index}", "study_id": f"PDF_TRUNCATED_{index}", "document_role": "MAIN", "url": self.base_url + route, "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )

                receipt = acquire_manifest(manifest, root / "acquired")

                self.assertEqual(receipt["results"][0]["reason"], "RESPONSE_NOT_PDF")
                self.assertFalse((root / "acquired" / target_path).exists())

        for index, body in enumerate([b"%PDF-1.4\n", b"%PDF-%%EOF"]):
            with self.subTest(existing_index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output_root = root / "acquired"
                target_path = f"sources/PDF_EXISTING_{index}/MAIN.pdf"
                target = output_root / target_path
                target.parent.mkdir(parents=True)
                target.write_bytes(body)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": f"PDF_EXISTING_{index}", "study_id": f"PDF_EXISTING_{index}", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )

                receipt = acquire_manifest(manifest, output_root, allow_network=False)

                self.assertEqual(receipt["results"][0]["reason"], "EXISTING_FILE_NOT_PDF")
                self.assertEqual(target.read_bytes(), body)

    def test_content_length_is_optional_but_single_valid_value_must_match(self):
        for index, route in enumerate(["/no-content-length.pdf", "/chunked.pdf"]):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target_path = f"sources/OPTIONAL_LENGTH_{index}/MAIN.pdf"
                manifest = self.write_manifest(
                    root,
                    [{"download_id": f"OPTIONAL_LENGTH_{index}", "study_id": f"OPTIONAL_LENGTH_{index}", "document_role": "MAIN", "url": self.base_url + route, "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )

                receipt = acquire_manifest(manifest, root / "acquired")

                self.assertEqual(receipt["results"][0]["status"], "DOWNLOADED")
                self.assertEqual((root / "acquired" / target_path).read_bytes(), PDF_BYTES)

        cases = [
            ("/invalid-content-length.pdf", "INVALID_CONTENT_LENGTH", None),
            ("/negative-content-length.pdf", "INVALID_CONTENT_LENGTH", None),
            ("/duplicate-content-length.pdf", "INVALID_CONTENT_LENGTH", None),
            ("/conflicting-content-length.pdf", "INVALID_CONTENT_LENGTH", None),
            ("/over-limit-content-length.pdf", "FILE_EXCEEDS_SIZE_LIMIT", len(PDF_BYTES)),
            ("/mismatched-content-length.pdf", "CONTENT_LENGTH_MISMATCH", None),
        ]
        for index, (route, reason, limit) in enumerate(cases):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target_path = f"sources/LENGTH_{index}/MAIN.pdf"
                manifest = self.write_manifest(
                    root,
                    [{"download_id": f"LENGTH_{index}", "study_id": f"LENGTH_{index}", "document_role": "MAIN", "url": self.base_url + route, "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )
                kwargs = {"retries": 0}
                if limit is not None:
                    kwargs["max_bytes"] = limit

                receipt = acquire_manifest(manifest, root / "acquired", **kwargs)

                self.assertEqual(receipt["results"][0]["reason"], reason)
                self.assertFalse((root / "acquired" / target_path).exists())
                rendered_outputs = "\n".join([
                    json.dumps(receipt),
                    (root / "acquired/manual_acquisition.tsv").read_text(),
                    (root / "acquired/manual_acquisition.html").read_text(),
                ])
                self.assertNotIn("content-length-secret", rendered_outputs)

    def test_rejects_external_plain_http_and_sensitive_query_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    {"download_id": "S003_MAIN", "study_id": "S003", "document_role": "MAIN", "url": "http://example.com/paper.pdf", "target_path": "sources/S003/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                    {"download_id": "S004_MAIN", "study_id": "S004", "document_role": "MAIN", "url": "https://example.com/paper.pdf?X-Amz-Signature=synthetic", "target_path": "sources/S004/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                ],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual([row["reason"] for row in receipt["results"]], ["INSECURE_NONLOCAL_HTTP", "SENSITIVE_URL_PARAMETER_FORBIDDEN"])

    def test_rejects_target_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "BAD", "study_id": "S005", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "../escape.pdf", "source_class": "PUBLIC_DIRECT"}],
            )

            with self.assertRaises(ManifestError):
                acquire_manifest(manifest, root / "acquired")

    def test_verify_only_never_uses_network_for_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S006_MAIN", "study_id": "S006", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S006/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            FixtureHandler.pdf_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired", allow_network=False)

            self.assertEqual(receipt["results"][0]["reason"], "LOCAL_FILE_MISSING")
            self.assertEqual(FixtureHandler.pdf_requests, 0)

    def test_landing_page_only_entry_goes_directly_to_manual_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S007_MAIN", "study_id": "S007", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S007/MAIN.pdf", "source_class": "LANDING_PAGE_ONLY"}],
            )
            FixtureHandler.pdf_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["reason"], "NO_PUBLIC_DIRECT_PDF")
            self.assertEqual(FixtureHandler.pdf_requests, 0)

    def test_downloads_explicit_docx_supplement_with_openxml_magic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S008_SI_1", "study_id": "S008", "document_role": "SI", "url": self.base_url + "/supp.docx", "target_path": "sources/S008/SI/supp.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"}],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "DOWNLOADED")
            self.assertEqual((root / "acquired/sources/S008/SI/supp.docx").read_bytes(), DOCX_BYTES)

    def test_preflight_rejects_root_empty_and_metadata_target_paths_without_side_effects(self):
        forbidden = [
            "",
            ".",
            "acquisition_receipt.json",
            "manual_acquisition.tsv",
            "manual_acquisition.html",
            "nested/../manual_acquisition.tsv",
        ]
        for target_path in forbidden:
            with self.subTest(target_path=target_path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "BAD", "study_id": "S009", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )
                output_root = root / "acquired"

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertFalse(output_root.exists())

    def test_reserved_metadata_prefixes_fail_preflight_before_earlier_download(self):
        for index, reserved_name in enumerate(["acquisition_receipt.json", "manual_acquisition.tsv", "manual_acquisition.html"]):
            with self.subTest(reserved_name=reserved_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output_root = root / "acquired"
                earlier_target = output_root / f"sources/PREFIX_{index}/MAIN.pdf"
                manifest = self.write_manifest(
                    root,
                    [
                        {"download_id": f"PREFIX_{index}_EARLY", "study_id": f"PREFIX_{index}", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": f"sources/PREFIX_{index}/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                        {"download_id": f"PREFIX_{index}_BAD", "study_id": f"PREFIX_{index}", "document_role": "SI", "url": self.base_url + "/paper.pdf", "target_path": f"{reserved_name}/child.pdf", "source_class": "PUBLIC_DIRECT"},
                    ],
                )
                FixtureHandler.pdf_requests = 0

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertEqual(FixtureHandler.pdf_requests, 0)
                self.assertFalse(earlier_target.exists())
                self.assertFalse(output_root.exists())

    def test_preflight_rejects_invalid_ids_and_normalized_target_collisions_before_download(self):
        cases = [
            [
                {"download_id": "", "study_id": "S010", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S010/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
            ],
            [
                {"download_id": "DUP", "study_id": "S011", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S011/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                {"download_id": "DUP", "study_id": "S012", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S012/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
            ],
            [
                {"download_id": "ONE", "study_id": "S013", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S013/../S014/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                {"download_id": "TWO", "study_id": "S014", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S014/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
            ],
        ]
        for downloads in cases:
            with self.subTest(downloads=downloads), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(root, downloads)
                output_root = root / "acquired"
                FixtureHandler.pdf_requests = 0

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertEqual(FixtureHandler.pdf_requests, 0)
                self.assertFalse(output_root.exists())

    def test_preflight_rejects_in_root_symlink_alias_target_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            target_root = output_root / "sources/S_ALIAS"
            canonical_dir = target_root / "canonical"
            canonical_dir.mkdir(parents=True)
            alias_dir = target_root / "alias"
            alias_dir.symlink_to(canonical_dir, target_is_directory=True)
            canonical_target = canonical_dir / "MAIN.pdf"
            manifest = self.write_manifest(
                root,
                [
                    {"download_id": "ALIAS_ONE", "study_id": "S_ALIAS", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S_ALIAS/alias/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                    {"download_id": "ALIAS_TWO", "study_id": "S_ALIAS", "document_role": "SI", "url": self.base_url + "/paper.pdf", "target_path": "sources/S_ALIAS/canonical/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                ],
            )

            with mock.patch.object(public_corpus, "_validate_existing_target_boundary", side_effect=AssertionError("canonical aliases must fail during preflight")):
                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root, allow_network=False)

            self.assertTrue(alias_dir.is_symlink())
            self.assertFalse(canonical_target.exists())
            self.assertFalse((output_root / "acquisition_receipt.json").exists())

    def test_later_preexisting_target_symlink_fails_preflight_before_earlier_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            symlink_target = output_root / "sources/S042/MAIN.pdf"
            symlink_target.parent.mkdir(parents=True)
            victim = symlink_target.parent / "victim.pdf"
            victim.write_bytes(PDF_BYTES)
            symlink_target.symlink_to(victim)
            before = {path.relative_to(output_root).as_posix() for path in output_root.rglob("*")}
            earlier_target = output_root / "sources/S041/MAIN.pdf"
            manifest = self.write_manifest(
                root,
                [
                    {"download_id": "S041_MAIN", "study_id": "S041", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S041/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                    {"download_id": "S042_MAIN", "study_id": "S042", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S042/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                ],
            )
            FixtureHandler.pdf_requests = 0

            with self.assertRaises(ManifestError):
                acquire_manifest(manifest, output_root)

            after = {path.relative_to(output_root).as_posix() for path in output_root.rglob("*")}
            self.assertEqual(FixtureHandler.pdf_requests, 0)
            self.assertFalse(earlier_target.exists())
            self.assertEqual(after, before)
            self.assertTrue(symlink_target.is_symlink())
            self.assertEqual(victim.read_bytes(), PDF_BYTES)
            self.assertFalse((output_root / "acquisition_receipt.json").exists())

    def test_preflight_rejects_empty_and_nonstring_study_ids(self):
        for study_id in ["", "   ", None, 123, []]:
            with self.subTest(study_id=study_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "STRICT_STUDY", "study_id": study_id, "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/STRICT_STUDY/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
                )
                output_root = root / "acquired"

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root, allow_network=False)

                self.assertFalse(output_root.exists())

    def test_preflight_rejects_invalid_role_format_and_source_class_shapes(self):
        cases = [
            ("document_role", ["MAIN"]),
            ("expected_format", ["PDF"]),
            ("source_class", ""),
            ("source_class", "   "),
            ("source_class", None),
            ("source_class", []),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                row = {
                    "download_id": "STRICT_SHAPE",
                    "study_id": "STRICT_SHAPE",
                    "document_role": "MAIN",
                    "url": self.base_url + "/paper.pdf",
                    "target_path": "sources/STRICT_SHAPE/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                    **{field: value},
                }
                manifest = self.write_manifest(root, [row])
                output_root = root / "acquired"

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root, allow_network=False)

                self.assertFalse(output_root.exists())

    def test_preflight_rejects_nonempty_string_violations_before_url_or_path_use(self):
        cases = [
            ("url", ""),
            ("url", [self.base_url + "/paper.pdf"]),
            ("target_path", "   "),
            ("target_path", ["sources/STRICT_VALUE/MAIN.pdf"]),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                row = {
                    "download_id": "STRICT_VALUE",
                    "study_id": "STRICT_VALUE",
                    "document_role": "MAIN",
                    "url": self.base_url + "/paper.pdf",
                    "target_path": "sources/STRICT_VALUE/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                    **{field: value},
                }
                manifest = self.write_manifest(root, [row])
                output_root = root / "acquired"

                if field == "url":
                    with mock.patch.object(public_corpus, "_safe_url", side_effect=AssertionError("URL sanitizer must not receive invalid shapes")):
                        with self.assertRaises(ManifestError):
                            acquire_manifest(manifest, output_root, allow_network=False)
                else:
                    with self.assertRaises(ManifestError):
                        acquire_manifest(manifest, output_root, allow_network=False)

                self.assertFalse(output_root.exists())

    def test_nonempty_future_source_class_remains_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "FUTURE_CLASS", "study_id": "FUTURE_CLASS", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/FUTURE_CLASS/MAIN.pdf", "source_class": "FUTURE_GENERIC_CLASS"}],
            )
            FixtureHandler.pdf_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "MANUAL_OR_AUTHORIZED_ACCESS_REQUIRED")
            self.assertEqual(receipt["results"][0]["reason"], "NO_PUBLIC_DIRECT_PDF")
            self.assertEqual(FixtureHandler.pdf_requests, 0)

    def test_acquisition_normalizes_shared_manifest_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{
                    "download_id": "  SHARED_MAIN  ",
                    "study_id": "  SHARED_STUDY  ",
                    "doi": "https://doi.org/10.1000/SHARED.S1.",
                    "document_role": "MAIN",
                    "url": self.base_url + "/paper.pdf",
                    "target_path": "sources/SHARED_STUDY/MAIN.pdf",
                    "source_class": "MANUAL_SHARED_TEST",
                }],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            result = receipt["results"][0]
            self.assertEqual(result["download_id"], "SHARED_MAIN")
            self.assertEqual(result["study_id"], "SHARED_STUDY")
            self.assertEqual(result["doi"], "10.1000/shared.s1")

    def test_acquisition_rejects_invalid_shared_manifest_fields(self):
        invalid_updates = [
            {"expected_format": "TXT"},
            {"expected_format": ["PDF"]},
            {"doi": "https://doi.org/10.1000/shared.s1?credential=hidden"},
            {"doi": 123},
        ]
        for update in invalid_updates:
            with self.subTest(update=update), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                row = {
                    "download_id": "SHARED_INVALID",
                    "study_id": "SHARED_INVALID",
                    "document_role": "MAIN",
                    "url": self.base_url + "/paper.pdf",
                    "target_path": "sources/SHARED_INVALID/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                    **update,
                }
                manifest = self.write_manifest(root, [row])

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, root / "acquired")

                self.assertFalse((root / "acquired").exists())

    def test_url_preflight_rejects_missing_hosts_and_invalid_ports_before_opener(self):
        cases = [
            {"url": "https:///missing-host.pdf"},
            {"url": "https://localhost:not-a-port/paper.pdf"},
            {"url": "https://localhost:70000/paper.pdf"},
            {"landing_page_url": "https://localhost:bad-landing-port/article"},
        ]
        for update in cases:
            with self.subTest(update=update), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                row = {
                    "download_id": "STRICT_URL",
                    "study_id": "STRICT_URL",
                    "document_role": "MAIN",
                    "url": self.base_url + "/paper.pdf",
                    "target_path": "sources/STRICT_URL/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                    **update,
                }
                manifest = self.write_manifest(root, [row])
                output_root = root / "acquired"

                with mock.patch.object(public_corpus.urllib.request, "build_opener", side_effect=AssertionError("opener must not be invoked")):
                    with self.assertRaises(ManifestError):
                        acquire_manifest(manifest, output_root)

                self.assertFalse(output_root.exists())

    def test_url_preflight_rejects_malformed_hostname_syntax_before_opener(self):
        invalid_urls = [
            "https://bad host.example/paper.pdf",
            "https://bad\tlabel.example/paper.pdf",
            "https://bad\x01label.example/paper.pdf",
            "https://-leading.example/paper.pdf",
            "https://double..example/paper.pdf",
            f"https://{'a' * 64}.example/paper.pdf",
            "https://999.999.999.999/paper.pdf",
        ]
        for url in invalid_urls:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "STRICT_HOST", "study_id": "STRICT_HOST", "document_role": "MAIN", "url": url, "target_path": "sources/STRICT_HOST/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
                )
                output_root = root / "acquired"

                with mock.patch.object(public_corpus.urllib.request, "build_opener", side_effect=AssertionError("opener must not receive malformed hostnames")):
                    with self.assertRaises(ManifestError):
                        acquire_manifest(manifest, output_root)

                self.assertFalse(output_root.exists())

    def test_url_safety_accepts_supported_hostname_forms_without_resolution(self):
        urls = [
            "https://papers.example.org/article",
            "https://sub-domain.example.org./article",
            "http://localhost:8080/paper.pdf",
            "http://127.0.0.1:8080/paper.pdf",
            "http://[::1]:8080/paper.pdf",
        ]
        for url in urls:
            with self.subTest(url=url):
                allowed, reason, _ = public_corpus._safe_url(url)
                self.assertTrue(allowed)
                self.assertIsNone(reason)

    def test_invalid_root_target_preserves_file_outside_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "acquired.part"
            outside.write_bytes(b"outside-sentinel")
            manifest = self.write_manifest(
                root,
                [{"download_id": "BAD", "study_id": "S015", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": ".", "source_class": "PUBLIC_DIRECT"}],
            )

            with self.assertRaises(ManifestError):
                acquire_manifest(manifest, root / "acquired")

            self.assertEqual(outside.read_bytes(), b"outside-sentinel")

    def test_precreated_fixed_part_symlink_is_not_followed_or_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            target = output_root / "sources/S016/MAIN.pdf"
            target.parent.mkdir(parents=True)
            victim = root / "victim.txt"
            victim.write_bytes(b"victim-sentinel")
            fixed_partial = target.with_suffix(".pdf.part")
            fixed_partial.symlink_to(victim)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S016_MAIN", "study_id": "S016", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S016/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )

            receipt = acquire_manifest(manifest, output_root)

            self.assertEqual(receipt["results"][0]["status"], "DOWNLOADED")
            self.assertEqual(victim.read_bytes(), b"victim-sentinel")
            self.assertTrue(fixed_partial.is_symlink())
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), PDF_BYTES)

    def test_metadata_publication_failure_preserves_previous_files(self):
        previous = {
            "manual_acquisition.tsv": b"previous-tsv\n",
            "manual_acquisition.html": b"previous-html\n",
            "acquisition_receipt.json": b"previous-receipt\n",
        }
        real_mkstemp = tempfile.mkstemp
        for failing_name in previous:
            with self.subTest(failing_name=failing_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output_root = root / "acquired"
                output_root.mkdir()
                for name, content in previous.items():
                    (output_root / name).write_bytes(content)
                manifest = self.write_manifest(root, [])

                def fail_selected_stage(*args, prefix="", **kwargs):
                    if prefix == f".{failing_name}.":
                        raise OSError("synthetic metadata staging failure")
                    return real_mkstemp(*args, prefix=prefix, **kwargs)

                with mock.patch("tempfile.mkstemp", side_effect=fail_selected_stage):
                    with self.assertRaises(OSError):
                        acquire_manifest(manifest, output_root)

                for name, content in previous.items():
                    self.assertEqual((output_root / name).read_bytes(), content)

    def test_metadata_replace_failure_rolls_back_previous_files(self):
        previous = {
            "manual_acquisition.tsv": b"previous-tsv\n",
            "manual_acquisition.html": b"previous-html\n",
            "acquisition_receipt.json": b"previous-receipt\n",
        }
        real_replace = public_corpus.os.replace
        for failing_name in previous:
            with self.subTest(failing_name=failing_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output_root = root / "acquired"
                output_root.mkdir()
                for name, content in previous.items():
                    (output_root / name).write_bytes(content)
                manifest = self.write_manifest(root, [])
                failed = False

                def fail_selected_replace(source, destination):
                    nonlocal failed
                    if not failed and Path(destination).name == failing_name:
                        failed = True
                        raise OSError("synthetic metadata replace failure")
                    return real_replace(source, destination)

                with mock.patch.object(public_corpus.os, "replace", side_effect=fail_selected_replace):
                    with self.assertRaises(OSError):
                        acquire_manifest(manifest, output_root)

                for name, content in previous.items():
                    self.assertEqual((output_root / name).read_bytes(), content)

    def test_sensitive_source_and_landing_urls_are_redacted_from_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_secret = "source-secret-value"
            landing_secret = "landing-secret-value"
            manifest = self.write_manifest(
                root,
                [{
                    "download_id": "S017_MAIN",
                    "study_id": "S017",
                    "document_role": "MAIN",
                    "url": f"http://example.com/paper.pdf?access_token={source_secret}",
                    "landing_page_url": f"https://example.com/article?session={landing_secret}",
                    "target_path": "sources/S017/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                }],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["reason"], "INSECURE_NONLOCAL_HTTP")
            outputs = [
                json.dumps(receipt),
                (root / "acquired/manual_acquisition.tsv").read_text(),
                (root / "acquired/manual_acquisition.html").read_text(),
            ]
            for output in outputs:
                self.assertNotIn(source_secret, output)
                self.assertNotIn(landing_secret, output)

    def test_sensitive_redirect_is_rejected_before_target_request_or_body_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S018_MAIN", "study_id": "S018", "document_role": "MAIN", "url": self.base_url + "/redirect-sensitive", "target_path": "sources/S018/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            FixtureHandler.redirect_sensitive_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            result = receipt["results"][0]
            self.assertEqual(result["reason"], "SENSITIVE_URL_PARAMETER_FORBIDDEN")
            self.assertNotIn("redirect-secret", json.dumps(receipt))
            self.assertEqual(FixtureHandler.redirect_sensitive_requests, 0)
            self.assertFalse((root / "acquired/sources/S018/MAIN.pdf").exists())

    def test_redirect_count_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S019_MAIN", "study_id": "S019", "document_role": "MAIN", "url": self.base_url + "/redirect-loop", "target_path": "sources/S019/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            FixtureHandler.redirect_loop_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["reason"], "TOO_MANY_REDIRECTS")
            self.assertLessEqual(FixtureHandler.redirect_loop_requests, 6)
            self.assertFalse((root / "acquired/sources/S019/MAIN.pdf").exists())

    def test_redirect_to_new_origin_rechecks_robots_before_download(self):
        events: list[str] = []

        class OtherOriginHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib handler contract
                if self.path == "/robots.txt":
                    events.append("robots")
                    body = b"User-agent: *\nAllow: /\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                elif self.path == "/paper.pdf":
                    events.append("paper")
                    body = PDF_BYTES
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                else:
                    body = b"not found"
                    self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        other_server = ThreadingHTTPServer(("127.0.0.1", 0), OtherOriginHandler)
        other_thread = threading.Thread(target=other_server.serve_forever, daemon=True)
        other_thread.start()
        try:
            FixtureHandler.redirect_target_url = f"http://127.0.0.1:{other_server.server_port}/paper.pdf"
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "S020_MAIN", "study_id": "S020", "document_role": "MAIN", "url": self.base_url + "/redirect-other-origin", "target_path": "sources/S020/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
                )

                receipt = acquire_manifest(manifest, root / "acquired")

                self.assertEqual(receipt["results"][0]["status"], "DOWNLOADED")
                self.assertEqual(events, ["robots", "paper"])
                self.assertEqual((root / "acquired/sources/S020/MAIN.pdf").read_bytes(), PDF_BYTES)
        finally:
            other_server.shutdown()
            other_server.server_close()
            other_thread.join(timeout=2)

    def test_preflight_rejects_malformed_expected_sha256_without_side_effects(self):
        for expected_sha256 in ["", "a" * 63, "z" * 64, 123]:
            with self.subTest(expected_sha256=expected_sha256), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "S021_MAIN", "study_id": "S021", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S021/MAIN.pdf", "source_class": "PUBLIC_DIRECT", "expected_sha256": expected_sha256}],
                )
                output_root = root / "acquired"
                FixtureHandler.pdf_requests = 0

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertEqual(FixtureHandler.pdf_requests, 0)
                self.assertFalse(output_root.exists())

    def test_download_hash_mismatch_leaves_target_absent_and_enters_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S022_MAIN", "study_id": "S022", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S022/MAIN.pdf", "source_class": "PUBLIC_DIRECT", "expected_sha256": hashlib.sha256(b"different").hexdigest()}],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "MANUAL_OR_AUTHORIZED_ACCESS_REQUIRED")
            self.assertEqual(receipt["results"][0]["reason"], "DOWNLOADED_HASH_MISMATCH")
            self.assertFalse((root / "acquired/sources/S022/MAIN.pdf").exists())
            self.assertEqual(receipt["manual_queue_count"], 1)

    def test_download_hash_match_accepts_uppercase_manifest_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S023_MAIN", "study_id": "S023", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S023/MAIN.pdf", "source_class": "PUBLIC_DIRECT", "expected_sha256": hashlib.sha256(PDF_BYTES).hexdigest().upper()}],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "DOWNLOADED")
            self.assertEqual((root / "acquired/sources/S023/MAIN.pdf").read_bytes(), PDF_BYTES)

    def test_ooxml_validation_accepts_docx_and_xlsx_but_rejects_corrupt_and_cross_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    {"download_id": "S024_DOCX", "study_id": "S024", "document_role": "SI", "url": self.base_url + "/supp.docx", "target_path": "sources/S024/SI/supp.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"},
                    {"download_id": "S025_XLSX", "study_id": "S025", "document_role": "SI", "url": self.base_url + "/supp.xlsx", "target_path": "sources/S025/SI/supp.xlsx", "source_class": "PUBLIC_DIRECT", "expected_format": "XLSX"},
                    {"download_id": "S026_CORRUPT", "study_id": "S026", "document_role": "SI", "url": self.base_url + "/corrupt.docx", "target_path": "sources/S026/SI/corrupt.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"},
                    {"download_id": "S027_CROSS", "study_id": "S027", "document_role": "SI", "url": self.base_url + "/xlsx-as-docx.docx", "target_path": "sources/S027/SI/cross.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"},
                ],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual([row["status"] for row in receipt["results"][:2]], ["DOWNLOADED", "DOWNLOADED"])
            self.assertEqual([row["reason"] for row in receipt["results"][2:]], ["RESPONSE_FORMAT_MISMATCH", "RESPONSE_FORMAT_MISMATCH"])
            self.assertEqual((root / "acquired/sources/S024/SI/supp.docx").read_bytes(), DOCX_BYTES)
            self.assertEqual((root / "acquired/sources/S025/SI/supp.xlsx").read_bytes(), XLSX_BYTES)
            self.assertFalse((root / "acquired/sources/S026/SI/corrupt.docx").exists())
            self.assertFalse((root / "acquired/sources/S027/SI/cross.docx").exists())

    def test_existing_format_check_reads_only_the_required_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            target = output_root / "sources/S028/MAIN.pdf"
            target.parent.mkdir(parents=True)
            target.write_bytes(PDF_BYTES)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S028_MAIN", "study_id": "S028", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S028/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            original_read_bytes = Path.read_bytes

            def guarded_read_bytes(path):
                if path == target:
                    raise AssertionError("format validation must not read the complete target")
                return original_read_bytes(path)

            with mock.patch.object(Path, "read_bytes", guarded_read_bytes):
                receipt = acquire_manifest(manifest, output_root, allow_network=False)

            self.assertEqual(receipt["results"][0]["status"], "VERIFIED_EXISTING")

    def test_existing_target_symlink_is_rejected_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            target = output_root / "sources/S038/MAIN.pdf"
            target.parent.mkdir(parents=True)
            victim = target.parent / "victim.pdf"
            victim.write_bytes(PDF_BYTES)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S038_MAIN", "study_id": "S038", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S038/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            original_preflight = public_corpus._preflight_manifest

            def insert_symlink_after_preflight(manifest_data, acquisition_root):
                prepared = original_preflight(manifest_data, acquisition_root)
                target.symlink_to(victim)
                return prepared

            with mock.patch.object(public_corpus, "_preflight_manifest", side_effect=insert_symlink_after_preflight):
                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root, allow_network=False)

            self.assertTrue(target.is_symlink())
            self.assertEqual(victim.read_bytes(), PDF_BYTES)
            self.assertFalse((output_root / "acquisition_receipt.json").exists())

    def test_existing_target_parent_symlink_escape_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            target_parent = output_root / "sources/S039"
            target_parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            outside_target = outside / "MAIN.pdf"
            outside_target.write_bytes(PDF_BYTES)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S039_MAIN", "study_id": "S039", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S039/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            original_preflight = public_corpus._preflight_manifest

            def escape_parent_after_preflight(manifest_data, acquisition_root):
                prepared = original_preflight(manifest_data, acquisition_root)
                target_parent.rmdir()
                target_parent.symlink_to(outside, target_is_directory=True)
                return prepared

            with mock.patch.object(public_corpus, "_preflight_manifest", side_effect=escape_parent_after_preflight):
                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root, allow_network=False)

            self.assertTrue(target_parent.is_symlink())
            self.assertEqual(outside_target.read_bytes(), PDF_BYTES)
            self.assertFalse((output_root / "acquisition_receipt.json").exists())

    def test_containment_revalidation_failure_aborts_without_replacing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            output_root.mkdir()
            previous = {
                "manual_acquisition.tsv": b"previous-tsv\n",
                "manual_acquisition.html": b"previous-html\n",
                "acquisition_receipt.json": b"previous-receipt\n",
            }
            for name, content in previous.items():
                (output_root / name).write_bytes(content)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S029_MAIN", "study_id": "S029", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S029/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            original_validate = public_corpus._validate_target_parent
            validation_calls = 0

            def fail_before_replace(output, target):
                nonlocal validation_calls
                validation_calls += 1
                if validation_calls == 3:
                    raise ManifestError("synthetic containment change")
                return original_validate(output, target)

            with mock.patch.object(public_corpus, "_validate_target_parent", side_effect=fail_before_replace):
                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

            self.assertFalse((output_root / "sources/S029/MAIN.pdf").exists())
            for name, content in previous.items():
                self.assertEqual((output_root / name).read_bytes(), content)

    def test_local_replace_failure_propagates_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            manifest = self.write_manifest(
                root,
                [{"download_id": "S030_MAIN", "study_id": "S030", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S030/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            target = output_root / "sources/S030/MAIN.pdf"
            original_replace = public_corpus.os.replace

            def reject_target_replace(source, destination):
                if Path(destination) == target:
                    raise PermissionError("synthetic local replace failure")
                return original_replace(source, destination)

            with mock.patch.object(public_corpus.os, "replace", side_effect=reject_target_replace):
                with self.assertRaises(PermissionError):
                    acquire_manifest(manifest, output_root)

            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob(".MAIN.pdf.*.part")), [])
            self.assertFalse((output_root / "acquisition_receipt.json").exists())

    def test_local_replace_timeout_is_not_reported_as_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            manifest = self.write_manifest(
                root,
                [{"download_id": "S030_TIMEOUT", "study_id": "S030", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/S030/timeout.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            target = output_root / "sources/S030/timeout.pdf"
            original_replace = public_corpus.os.replace

            def timeout_target_replace(source, destination):
                if Path(destination) == target:
                    raise TimeoutError("synthetic local replace timeout")
                return original_replace(source, destination)

            with mock.patch.object(public_corpus.os, "replace", side_effect=timeout_target_replace):
                with self.assertRaises(TimeoutError):
                    acquire_manifest(manifest, output_root)

            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob(".timeout.pdf.*.part")), [])
            self.assertFalse((output_root / "acquisition_receipt.json").exists())

    def test_cli_rejects_invalid_numeric_limits_before_acquisition(self):
        cases = [
            ("--timeout-seconds", "0", "must be greater than zero"),
            ("--timeout-seconds", "nan", "must be finite and greater than zero"),
            ("--timeout-seconds", "inf", "must be finite and greater than zero"),
            ("--max-bytes", "0", "must be greater than zero"),
            ("--retries", "-1", "must be zero or greater"),
        ]
        for option, value, message in cases:
            with self.subTest(option=option), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(root, [])
                output_root = root / "acquired"

                completed = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/acquisition/acquire_public_corpus.py"), "--manifest", str(manifest), "--output-root", str(output_root), option, value],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertIn(message, completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertFalse(output_root.exists())

    def test_cli_reports_manifest_error_without_echoing_sensitive_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "cli-sensitive-value"
            manifest = self.write_manifest(
                root,
                [{"download_id": "BAD", "study_id": "S031", "document_role": "MAIN", "url": self.base_url + f"/paper.pdf?token={secret}", "target_path": f"../{secret}.pdf", "source_class": "PUBLIC_DIRECT"}],
            )

            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/acquisition/acquire_public_corpus.py"), "--manifest", str(manifest), "--output-root", str(root / "acquired")],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "error: invalid or unsafe acquisition manifest\n")
            self.assertNotIn(secret, completed.stdout + completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_malformed_and_non_object_manifests_fail_preflight_without_output(self):
        for raw_manifest in ["{not-json", "[]"]:
            with self.subTest(raw_manifest=raw_manifest), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = root / "manifest.json"
                manifest.write_text(raw_manifest)
                output_root = root / "acquired"

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertFalse(output_root.exists())

    def test_cli_handles_malformed_manifest_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            manifest.write_text("{not-json")

            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/acquisition/acquire_public_corpus.py"), "--manifest", str(manifest), "--output-root", str(root / "acquired")],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "error: invalid or unsafe acquisition manifest\n")
            self.assertNotIn("Traceback", completed.stderr)

    def test_cli_rejects_malformed_url_authority_without_traceback_or_values(self):
        cases = [
            ("https:///missing-host-secret.pdf", "missing-host-secret"),
            ("https://localhost:invalid-port-secret/paper.pdf", "invalid-port-secret"),
            ("https://localhost:70000/out-of-range-secret.pdf", "out-of-range-secret"),
        ]
        for url, secret in cases:
            with self.subTest(url_kind=secret), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "CLI_URL", "study_id": "CLI_URL", "document_role": "MAIN", "url": url, "target_path": "sources/CLI_URL/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
                )
                output_root = root / "acquired"

                completed = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/acquisition/acquire_public_corpus.py"), "--manifest", str(manifest), "--output-root", str(output_root)],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stderr, "error: invalid or unsafe acquisition manifest\n")
                self.assertNotIn(secret, completed.stdout + completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertFalse(output_root.exists())

    def test_target_path_rejects_ascii_control_characters_before_output(self):
        for control in ["\x00", "\n", "\r", "\t", "\x1f", "\x7f"]:
            with self.subTest(codepoint=ord(control)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target_path = f"sources/S032/bad{control}name.pdf"
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "S032_MAIN", "study_id": "S032", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )
                output_root = root / "acquired"

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertFalse(output_root.exists())

    def test_target_path_uses_portable_posix_relative_syntax(self):
        invalid_paths = [
            r"sources\S043\MAIN.pdf",
            "C:/sources/S043/MAIN.pdf",
            "//server/share/MAIN.pdf",
            "/absolute/MAIN.pdf",
            "sources//MAIN.pdf",
            "sources/./MAIN.pdf",
            "sources/../MAIN.pdf",
            "sources/S043/paper.pdf:stream",
            "sources/S043/CON",
            "sources/S043/con.pdf",
            "sources/S043/LPT9.txt",
            "sources/S043/CONIN$",
            "sources/S043/trailing.",
            "sources/S043/trailing ",
        ]
        for target_path in invalid_paths:
            with self.subTest(target_path=target_path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.write_manifest(
                    root,
                    [{"download_id": "PORTABLE", "study_id": "S043", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": target_path, "source_class": "PUBLIC_DIRECT"}],
                )
                output_root = root / "acquired"

                with self.assertRaises(ManifestError):
                    acquire_manifest(manifest, output_root)

                self.assertFalse(output_root.exists())

    def test_preflight_rejects_existing_parent_symlink_before_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "acquired"
            real_parent = output_root / "sources/real"
            real_parent.mkdir(parents=True)
            alias_parent = output_root / "sources/alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            before = {path.relative_to(output_root).as_posix() for path in output_root.rglob("*")}
            manifest = self.write_manifest(
                root,
                [{"download_id": "PARENT_ALIAS", "study_id": "S044", "document_role": "MAIN", "url": self.base_url + "/paper.pdf", "target_path": "sources/alias/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            FixtureHandler.pdf_requests = 0

            with self.assertRaises(ManifestError):
                acquire_manifest(manifest, output_root)

            self.assertEqual(FixtureHandler.pdf_requests, 0)
            self.assertEqual({path.relative_to(output_root).as_posix() for path in output_root.rglob("*")}, before)
            self.assertFalse((real_parent / "MAIN.pdf").exists())

    def test_reparse_attribute_is_recognized_without_platform_specific_api(self):
        synthetic_stat = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
        )
        with mock.patch.object(os, "lstat", return_value=synthetic_stat):
            self.assertTrue(public_corpus._is_link_or_reparse(Path("synthetic-component")))

    def test_extended_credential_keys_are_redacted_from_source_and_landing_outputs(self):
        credential_keys = ["PaSsWoRd", "passwd", "pass", "client_secret", "download_sig"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = []
            secrets = []
            for index, key in enumerate(credential_keys):
                source_secret = f"source-credential-value-{index}"
                landing_secret = f"landing-credential-value-{index}"
                secrets.extend([source_secret, landing_secret])
                downloads.append({
                    "download_id": f"S033_{index}",
                    "study_id": f"S033_{index}",
                    "document_role": "MAIN",
                    "url": f"http://example.com/paper.pdf?{key}={source_secret}",
                    "landing_page_url": f"https://example.com/article?{key}={landing_secret}",
                    "target_path": f"sources/S033_{index}/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                })
            manifest = self.write_manifest(root, downloads)

            receipt = acquire_manifest(manifest, root / "acquired")

            outputs = [
                json.dumps(receipt),
                (root / "acquired/manual_acquisition.tsv").read_text(),
                (root / "acquired/manual_acquisition.html").read_text(),
            ]
            for secret in secrets:
                for output in outputs:
                    self.assertNotIn(secret, output)

    def test_query_allowlist_accepts_public_selectors_and_rejects_unknown_keys(self):
        allowed_query = (
            "download=1&FORMAT=pdf&type=full&file=paper.pdf&filename=paper.pdf&"
            "article=A1&doi=10.1000%2Fpublic&id=42&lang=en&locale=en-US&pdf=1&"
            "view=full&inline=true&sequence=1&isAllowed=y&utm_source=index"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "QUERY_ALLOWED", "study_id": "QUERY_ALLOWED", "document_role": "MAIN", "url": self.base_url + "/paper.pdf?" + allowed_query, "target_path": "sources/QUERY_ALLOWED/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            FixtureHandler.query_pdf_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "DOWNLOADED")
            self.assertEqual(FixtureHandler.query_pdf_requests, 1)

        unknown_keys = ["code", "ticket", "jwt", "SAMLResponse", "AWSAccessKeyId"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = [f"unknown-query-secret-{index}" for index in range(len(unknown_keys))]
            downloads = [
                {
                    "download_id": f"QUERY_DENIED_{index}",
                    "study_id": f"QUERY_DENIED_{index}",
                    "document_role": "MAIN",
                    "url": self.base_url + f"/paper.pdf?{key}={secrets[index]}",
                    "landing_page_url": self.base_url + f"/article?{key}=landing-{secrets[index]}",
                    "target_path": f"sources/QUERY_DENIED_{index}/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                }
                for index, key in enumerate(unknown_keys)
            ]
            manifest = self.write_manifest(root, downloads)
            FixtureHandler.query_pdf_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual({row["reason"] for row in receipt["results"]}, {"SENSITIVE_URL_PARAMETER_FORBIDDEN"})
            self.assertEqual(FixtureHandler.query_pdf_requests, 0)
            rendered_outputs = "\n".join([
                json.dumps(receipt),
                (root / "acquired/manual_acquisition.tsv").read_text(),
                (root / "acquired/manual_acquisition.html").read_text(),
            ])
            for secret in secrets:
                self.assertNotIn(secret, rendered_outputs)
                self.assertNotIn(f"landing-{secret}", rendered_outputs)

    def test_extended_credential_key_on_redirect_is_rejected_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S034_MAIN", "study_id": "S034", "document_role": "MAIN", "url": self.base_url + "/redirect-new-credential", "target_path": "sources/S034/MAIN.pdf", "source_class": "PUBLIC_DIRECT"}],
            )
            FixtureHandler.redirect_new_credential_requests = 0

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["reason"], "SENSITIVE_URL_PARAMETER_FORBIDDEN")
            outputs = [
                json.dumps(receipt),
                (root / "acquired/manual_acquisition.tsv").read_text(),
                (root / "acquired/manual_acquisition.html").read_text(),
            ]
            self.assertTrue(all("redirect-credential-secret" not in output for output in outputs))
            self.assertEqual(FixtureHandler.redirect_new_credential_requests, 0)
            self.assertFalse((root / "acquired/sources/S034/MAIN.pdf").exists())

    def test_ooxml_content_types_requires_valid_main_part_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [
                    {"download_id": "S035_MALFORMED", "study_id": "S035", "document_role": "SI", "url": self.base_url + "/malformed-types.docx", "target_path": "sources/S035/SI/malformed.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"},
                    {"download_id": "S036_FAKE", "study_id": "S036", "document_role": "SI", "url": self.base_url + "/fake-mime.docx", "target_path": "sources/S036/SI/fake.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"},
                    {"download_id": "S037_WRONG", "study_id": "S037", "document_role": "SI", "url": self.base_url + "/wrong-main-type.docx", "target_path": "sources/S037/SI/wrong.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"},
                ],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual([row["reason"] for row in receipt["results"]], ["RESPONSE_FORMAT_MISMATCH"] * 3)
            self.assertFalse((root / "acquired/sources/S035/SI/malformed.docx").exists())
            self.assertFalse((root / "acquired/sources/S036/SI/fake.docx").exists())
            self.assertFalse((root / "acquired/sources/S037/SI/wrong.docx").exists())

    def test_ooxml_content_types_rejects_foreign_namespace_lookalikes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(
                root,
                [{"download_id": "S040_FOREIGN", "study_id": "S040", "document_role": "SI", "url": self.base_url + "/foreign-namespace.docx", "target_path": "sources/S040/SI/foreign.docx", "source_class": "PUBLIC_DIRECT", "expected_format": "DOCX"}],
            )

            receipt = acquire_manifest(manifest, root / "acquired")

            self.assertEqual(receipt["results"][0]["status"], "MANUAL_OR_AUTHORIZED_ACCESS_REQUIRED")
            self.assertEqual(receipt["results"][0]["reason"], "RESPONSE_FORMAT_MISMATCH")
            self.assertFalse((root / "acquired/sources/S040/SI/foreign.docx").exists())

    def test_cli_reports_local_oserror_without_traceback_or_input_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, [])
            output_root = root / "local-secret-value"
            output_root.write_text("not a directory")

            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/acquisition/acquire_public_corpus.py"), "--manifest", str(manifest), "--output-root", str(output_root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "error: local acquisition I/O failure\n")
            self.assertNotIn(str(output_root), completed.stdout + completed.stderr)
            self.assertNotIn("local-secret-value", completed.stdout + completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_cli_reports_invalid_manifest_encoding_without_traceback_or_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "decode-secret-value.json"
            manifest.write_bytes(b"\xff\xfe\xfa")

            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/acquisition/acquire_public_corpus.py"), "--manifest", str(manifest), "--output-root", str(root / "acquired")],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "error: invalid or unsafe acquisition manifest\n")
            self.assertNotIn(str(manifest), completed.stdout + completed.stderr)
            self.assertNotIn("decode-secret-value", completed.stdout + completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
