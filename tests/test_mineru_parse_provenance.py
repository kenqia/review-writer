from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from review_writer.project.dual_parse_bootstrap import (
    DualParseBootstrapError,
    bind_generic_parse_outputs,
    bootstrap_dual_parse_project,
)


PRODUCER_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py"
)


def _load_producer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mineru_parse_producer", PRODUCER_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load producer script: {PRODUCER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _source_request(tmp_path: Path) -> dict[str, object]:
    sources = []
    for index in range(3):
        payload = f"%PDF-1.7\nsource-a-{index}\n%%EOF\n".encode()
        path = tmp_path / "inputs" / f"paper-{index}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sources.append(
            {
                "study_id": f"study-{index}",
                "source_id": f"source-{index}",
                "doi": f"10.1000/producer-{index}",
                "title": f"Producer study {index}",
                "tier": "core",
                "document_role": "MAIN",
                "pdf_input_path": str(path),
                "expected_pdf_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "schema_version": "dual-parse-bootstrap-request.v1",
        "project_id": "producer-provenance",
        "brief": {"topic": "Synthetic producer provenance"},
        "sources": sources,
    }


def _result_zip() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("full.md", "# Uploaded A\n")
        archive.writestr("layout.json", "{}")
        archive.writestr("parse_content_list.json", "[]")
        archive.writestr("parse_content_list_v2.json", "[[{}]]")
    return payload.getvalue()


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class _UploadResponse:
    def raise_for_status(self) -> None:
        return None


class _DownloadResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_DownloadResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.payload]


def test_producer_binds_uploaded_a_not_mutated_b_and_restores_without_stale_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    producer = _load_producer()
    request = _source_request(tmp_path)
    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    project_source_pdf = project / "00_sources" / "papers" / "source-0.pdf"
    producer_root = tmp_path / "producer-inputs"
    producer_root.mkdir()
    for index, source in enumerate(request["sources"]):
        source_path = Path(source["pdf_input_path"])
        (producer_root / f"source-{index}.pdf").write_bytes(source_path.read_bytes())
    producer_pdf = producer_root / "source-0.pdf"
    source_a = producer_pdf.read_bytes()
    source_b = b"%PDF-1.7\nsource-b\n%%EOF\n"
    project_source_pdf.write_bytes(source_b)
    receipt_path = project / "00_sources" / "acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"][0]["main_pdf"]["sha256"] = hashlib.sha256(source_b).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    jobs = [
        producer.ParseJob(
            index=index + 1,
            pdf_path=producer_root / f"source-{index}.pdf",
            source_root=producer_root,
            slug=f"source-{index}",
            data_id=f"00{index + 1}-source-{index}",
        )
        for index in range(3)
    ]
    output_dir = tmp_path / "mineru-output"
    uploaded: list[bytes] = []

    def fake_put(url: str, data: object, timeout: int) -> _UploadResponse:
        if isinstance(data, bytes):
            payload = data
        elif hasattr(data, "read"):
            payload = data.read()
        else:
            raise AssertionError(f"unexpected upload payload: {type(data)!r}")
        uploaded.append(payload)
        if len(uploaded) == 1:
            producer_pdf.write_bytes(source_b)
        return _UploadResponse()

    monkeypatch.setattr(
        producer,
        "request_upload_batch",
        lambda session, token, jobs, args: {
            "batch_id": "batch-producer-1",
            "file_urls": [
                f"https://upload.invalid/{item.slug}" for item in jobs
            ],
        },
    )
    monkeypatch.setattr(
        producer,
        "poll_batch_results",
        lambda **kwargs: {
            item.data_id: {
                "state": "done",
                "full_zip_url": f"https://download.invalid/{item.slug}.zip",
            }
            for item in jobs
        },
    )
    monkeypatch.setattr(producer.requests, "put", fake_put)
    monkeypatch.setattr(
        producer.requests,
        "get",
        lambda url, stream=True, timeout=300: _DownloadResponse(_result_zip()),
    )

    manifest: dict[str, object] = {
        "settings": {
            "language": "en",
            "model_version": "vlm",
            "enable_formula": True,
            "enable_table": True,
            "ocr": False,
        },
        "batches": [],
        "completed": [],
        "failed": [],
    }
    args = argparse.Namespace(force=False, poll_interval=1, timeout_minutes=1)
    producer.run_batch(object(), "test-token", jobs, args, output_dir, manifest)
    manifest["completed_count"] = len(manifest["completed"])
    manifest["failed_count"] = len(manifest["failed"])
    producer.write_json(output_dir / "manifest.json", manifest)

    completed = manifest["completed"]
    assert isinstance(completed, list)
    assert len(uploaded) == 3
    assert uploaded[0] == source_a
    assert completed[0]["source_pdf_sha256"] == hashlib.sha256(source_a).hexdigest()
    assert completed[0]["raw_zip_sha256"] == hashlib.sha256(
        (output_dir / "raw_zips/source-0.zip").read_bytes()
    ).hexdigest()

    before_bind = _snapshot(project)
    with pytest.raises(
        DualParseBootstrapError,
        match="GENERIC_SOURCE_PDF_HASH_MISMATCH",
    ):
        bind_generic_parse_outputs(project, output_dir)
    assert _snapshot(project) == before_bind
    assert not (project / "01_evidence").exists()

    producer_pdf.write_bytes(source_a)
    project_source_pdf.write_bytes(source_a)
    receipt["studies"][0]["main_pdf"]["sha256"] = hashlib.sha256(source_a).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    result = bind_generic_parse_outputs(project, output_dir)
    assert result["status"] == "bound"
    assert (project / "01_evidence").is_dir()
