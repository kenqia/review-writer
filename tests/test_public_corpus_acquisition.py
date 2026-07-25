from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_writer.acquisition.public_corpus import ManifestError, acquire_manifest


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
DOCX_BYTES = b"PK\x03\x04synthetic-openxml-fixture"


class FixtureHandler(BaseHTTPRequestHandler):
    pdf_requests = 0

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
        elif self.path == "/supp.docx":
            body = DOCX_BYTES
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
