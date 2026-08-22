from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from review_writer.project.source_truth import canonical_digest, load_source_truth_bundle
from tests.product_use import test_prod006_source_to_release as prod006_fixture
from tests.product_use import test_res001_paper_evidence_dashboard as res001_fixture


PROJECT_ID = prod006_fixture.PROJECT_ID
STUDY_ID = prod006_fixture.STUDY_ID
SOURCE_ID = prod006_fixture.SOURCE_ID


def _http_json(base_url: str, path: str) -> tuple[int, dict[str, Any]]:
    request = Request(f"{base_url}{path}", method="GET")
    with urlopen(request, timeout=15) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _snapshot_tree(root: Path) -> dict[str, tuple[str, object]]:
    snapshot: dict[str, tuple[str, object]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[relative] = ("directory", None)
    return snapshot


def _descriptor_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    section = payload["source_pdf_descriptors"]
    assert set(section) == {"status", "items"}
    assert section["status"] == "current"
    return section["items"]


def _make_persisted_bundle_stale(project: Path) -> None:
    path = project / "01_evidence/source_truth" / STUDY_ID / "bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    body["warnings"] = sorted({*body["warnings"], "prod002_stale_fixture"})
    stale_bundle = {**body, "bundle_digest": canonical_digest(body)}
    path.write_text(
        json.dumps(stale_bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_prod002_source_pdf_descriptors_are_current_safe_and_stale_fail_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="prod002-source-pdf-descriptors-") as temporary_root:
        review_root = Path(temporary_root)
        project, _ = res001_fixture._build_project(review_root)
        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        try:
            before_get = _snapshot_tree(project)
            status, payload = _http_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
            )
            assert status == 200
            assert payload["route"] == "evidence-to-release.v1"
            descriptors = _descriptor_items(payload)
            source = load_source_truth_bundle(project, STUDY_ID)["sources"][0]
            assert descriptors == [
                {
                    "source": SOURCE_ID,
                    "study": STUDY_ID,
                    "role": source["document_role"],
                    "digest": source["pdf"]["sha256"],
                    "page_count": source["page_count"],
                    "currentness": "current",
                    "locator": f"/api/project/{PROJECT_ID}/source/{SOURCE_ID}/pdf",
                }
            ]
            assert str(project) not in json.dumps(payload, ensure_ascii=False)
            assert _snapshot_tree(project) == before_get

            prod006_fixture._stop_dashboard(server, thread)
            server, thread, base_url = prod006_fixture._start_dashboard(review_root)
            status, cold_payload = _http_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
            )
            assert status == 200
            assert cold_payload == payload

            _make_persisted_bundle_stale(project)
            before_stale_get = _snapshot_tree(project)
            status, stale_payload = _http_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
            )
            assert status == 200
            assert stale_payload["source_pdf_descriptors"] == {
                "status": "stale",
                "items": [],
            }
            assert _snapshot_tree(project) == before_stale_get

            prod006_fixture._stop_dashboard(server, thread)
            server, thread, base_url = prod006_fixture._start_dashboard(review_root)
            status, cold_stale_payload = _http_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
            )
            assert status == 200
            assert cold_stale_payload == stale_payload
            assert cold_stale_payload["source_pdf_descriptors"]["items"] == []
        finally:
            prod006_fixture._stop_dashboard(server, thread)
