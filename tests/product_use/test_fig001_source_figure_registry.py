from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from review_writer.project.paper_evidence import paper_evidence_state
from review_writer.project.review_figures import load_source_figure_registry
from review_writer.project.source_truth import canonical_digest, load_source_truth_bundle
from tests.product_use.test_prod006_source_to_release import (
    EVIDENCE_ID,
    PROJECT_ID,
    SOURCE_ID,
    STUDY_ID,
    _TINY_PNG,
    _build_project,
    _http_bytes,
    _http_json,
    _sha256_bytes,
    _start_dashboard,
    _stop_dashboard,
    _write_json,
)


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
) -> tuple[int, bytes]:
    headers = {}
    if body is not None:
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def _registry_digest_payload(registry: dict[str, object]) -> dict[str, object]:
    return {
        "source_truth_digest": registry["source_truth_digest"],
        "content_list_v2_digest": registry["content_list_v2_digest"],
        "chemical_paper_project_binding_digest": registry[
            "chemical_paper_project_binding_digest"
        ],
        "figures": registry["figures"],
        "locator_gaps": registry["locator_gaps"],
    }


def _set_initial_selection_available(project: Path) -> None:
    registry_path = project / "03_figures/source_figure_registry.json"
    registry = load_source_figure_registry(project)
    registry["figures"][0]["selection_status"] = "available"
    registry["registry_digest"] = canonical_digest(_registry_digest_payload(registry))
    _write_json(registry_path, registry)


def _bytes_snapshot(project: Path, figure: dict[str, object]) -> dict[str, bytes | None]:
    source_bundle = load_source_truth_bundle(project, STUDY_ID)
    source = next(row for row in source_bundle["sources"] if row["source_id"] == SOURCE_ID)
    paths = {
        "registry": project / "03_figures/source_figure_registry.json",
        "asset": project / str(figure["asset_path"]),
        "source_pdf": project / str(source["pdf"]["path"]),
        "state_current": project / "state/current.json",
        "versions_current": project / "versions/current.json",
    }
    return {
        name: path.read_bytes() if path.is_file() and not path.is_symlink() else None
        for name, path in paths.items()
    }


def _figure_binding_snapshot(project: Path) -> dict[str, object]:
    registry = load_source_figure_registry(project)
    figure = registry["figures"][0]
    source_bundle = load_source_truth_bundle(project, STUDY_ID)
    source = next(row for row in source_bundle["sources"] if row["source_id"] == SOURCE_ID)
    evidence = next(
        row
        for row in paper_evidence_state(project)["rows"]
        if row["evidence_id"] == EVIDENCE_ID
    )
    asset_path = project / str(figure["asset_path"])
    assert asset_path.resolve().is_relative_to(project.resolve())
    assert asset_path.read_bytes() == _TINY_PNG
    assert _sha256_bytes(asset_path.read_bytes()) == figure["asset_sha256"]
    assert figure["source_pdf_sha256"] == source["pdf"]["sha256"]
    assert figure["source_id"] == SOURCE_ID
    assert figure["evidence_ids"] == [EVIDENCE_ID]
    assert source["document_role"] == "MAIN"
    assert set(evidence["risk_classes"]) == {
        "AI_PROVISIONAL",
        "GAP",
        "NON_COMPARABLE",
    }
    return {
        "figure_id": figure["figure_id"],
        "source_id": figure["source_id"],
        "evidence_ids": tuple(figure["evidence_ids"]),
        "source_pdf_sha256": figure["source_pdf_sha256"],
        "document_role": source["document_role"],
        "source_truth_digest": registry["source_truth_digest"],
        "content_list_v2_digest": registry["content_list_v2_digest"],
        "risk_classes": tuple(sorted(evidence["risk_classes"])),
    }


def test_fig001_source_figure_registry_product_use_is_bounded_and_restart_stable() -> None:
    with tempfile.TemporaryDirectory(
        prefix="fig001-source-registry-product-use-"
    ) as temporary_root:
        review_root = Path(temporary_root)
        project = _build_project(review_root)
        _set_initial_selection_available(project)

        before_binding = _figure_binding_snapshot(project)
        before_registry = load_source_figure_registry(project)
        figure = before_registry["figures"][0]
        figure_id = str(figure["figure_id"])
        before_bytes = _bytes_snapshot(project, figure)
        assert before_bytes["state_current"] is None
        assert before_bytes["versions_current"] is None

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, projection = _http_json(
                base_url, f"/api/project/{PROJECT_ID}/review-figures"
            )
            assert status == 200
            projected = next(
                row for row in projection["source_figures"] if row["figure_id"] == figure_id
            )
            assert projection["route"] == "evidence-to-release.v1"
            assert projection["status"] == "current"
            assert projected["selection_status"] == "available"
            assert projected["evidence_ids"] == [EVIDENCE_ID]
            assert "promotion" not in projection
            assert "b2" not in projection

            asset_query = urlencode({"figure_id": figure_id})
            status, asset_bytes = _http_bytes(
                base_url,
                f"/api/project/{PROJECT_ID}/source-figure?{asset_query}",
            )
            assert status == 200
            assert asset_bytes == _TINY_PNG
            fragment_query = urlencode({"figure_id": figure_id, "fragment": "0"})
            status, fragment_bytes = _http_bytes(
                base_url,
                f"/api/project/{PROJECT_ID}/source-figure?{fragment_query}",
            )
            assert status == 200
            assert fragment_bytes == _TINY_PNG
            assert _sha256_bytes(fragment_bytes) == figure["asset_sha256"]
            assert (
                project / str(figure["asset_path"])
            ).resolve().is_relative_to(project.resolve())

            blank_status, _ = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                body=b"",
            )
            assert blank_status == 400
            assert _bytes_snapshot(project, figure) == before_bytes
            assert _figure_binding_snapshot(project) == before_binding

            stale_payload = json.dumps(
                {
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": "stale-version-token",
                    "reason": "Stale synthetic decision must not write.",
                }
            ).encode("utf-8")
            stale_status, _ = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                body=stale_payload,
            )
            assert stale_status == 409
            assert _bytes_snapshot(project, figure) == before_bytes
            assert _figure_binding_snapshot(project) == before_binding

            valid_payload = json.dumps(
                {
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": projected["version_token"],
                    "reason": "Human selected the source-bound figure for bounded review.",
                }
            ).encode("utf-8")
            valid_status, valid_body = _request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                body=valid_payload,
            )
            assert valid_status == 200
            valid_projection = json.loads(valid_body.decode("utf-8"))
            valid_row = next(
                row
                for row in valid_projection["source_figures"]
                if row["figure_id"] == figure_id
            )
            assert valid_row["selection_status"] == "selected"
            assert _figure_binding_snapshot(project) == before_binding
            after_valid_bytes = _bytes_snapshot(project, figure)
            assert after_valid_bytes["registry"] != before_bytes["registry"]
            assert after_valid_bytes["asset"] == before_bytes["asset"]
            assert after_valid_bytes["source_pdf"] == before_bytes["source_pdf"]
            assert after_valid_bytes["state_current"] is None
            assert after_valid_bytes["versions_current"] is None
            after_valid_registry = load_source_figure_registry(project)
            assert after_valid_registry["figures"][0]["selection_status"] == "selected"
            selected_registry_bytes = after_valid_bytes["registry"]
            selected_asset_bytes = after_valid_bytes["asset"]
            selected_asset_hash = _sha256_bytes(selected_asset_bytes or b"")

        finally:
            _stop_dashboard(server, thread)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            status, restarted_projection = _http_json(
                base_url, f"/api/project/{PROJECT_ID}/review-figures"
            )
            assert status == 200
            assert restarted_projection == valid_projection
            restarted_row = next(
                row
                for row in restarted_projection["source_figures"]
                if row["figure_id"] == figure_id
            )
            assert restarted_row["selection_status"] == "selected"
            assert restarted_row["version_token"] == valid_row["version_token"]

            status, restarted_asset = _http_bytes(
                base_url,
                f"/api/project/{PROJECT_ID}/source-figure?{fragment_query}",
            )
            assert status == 200
            assert restarted_asset == selected_asset_bytes
            assert _sha256_bytes(restarted_asset) == selected_asset_hash
            restarted_bytes = _bytes_snapshot(project, figure)
            assert restarted_bytes["registry"] == selected_registry_bytes
            assert restarted_bytes["asset"] == before_bytes["asset"]
            assert restarted_bytes["source_pdf"] == before_bytes["source_pdf"]
            assert restarted_bytes["state_current"] is None
            assert restarted_bytes["versions_current"] is None
            assert _figure_binding_snapshot(project) == before_binding
        finally:
            _stop_dashboard(server, thread)
