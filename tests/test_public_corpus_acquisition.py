from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_writer.acquisition import public_corpus
from review_writer.acquisition.public_corpus import ManifestError, acquire_manifest


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


def make_ooxml_bytes(main_part: str, content_type: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/{main_part}" ContentType="{content_type}"/></Types>',
        )
        archive.writestr(main_part, "<synthetic/>")
    return buffer.getvalue()


DOCX_BYTES = make_ooxml_bytes("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
XLSX_BYTES = make_ooxml_bytes("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
CORRUPT_ZIP_BYTES = b"PK\x03\x04not-a-valid-zip"


class FixtureHandler(BaseHTTPRequestHandler):
    pdf_requests = 0
    redirect_loop_requests = 0
    redirect_sensitive_requests = 0
    redirect_target_url = ""

    def do_GET(self):  # noqa: N802 - stdlib handler contract
        if self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        elif self.path == "/paper.pdf":
            type(self).pdf_requests += 1
            body = PDF_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/redirect-sensitive":
            body = b""
            self.send_response(302)
            self.send_header("Location", "/paper.pdf?token=redirect-secret")
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
        else:
            body = b"login required"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
