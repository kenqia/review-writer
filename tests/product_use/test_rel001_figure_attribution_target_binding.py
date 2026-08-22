from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from review_writer.project.manuscript_v2 import merge_authoritative_manuscript
from review_writer.project.review_figures import load_source_figure_registry
from review_writer.project.source_truth import canonical_digest
from tests.product_use.test_prod006_source_to_release import (
    EVIDENCE_ID,
    PROJECT_ID,
    _build_project,
    _post_release,
    _start_dashboard,
    _stop_dashboard,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> tuple[int, bytes]:
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if body is not None:
        headers["Content-Length"] = str(len(body))
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> tuple[int, dict[str, object]]:
    status, body = _request(base_url, path, method=method, payload=payload)
    value = json.loads(body.decode("utf-8"))
    assert isinstance(value, dict)
    return status, value


def _release_bytes(project: Path) -> dict[str, bytes]:
    return {
        relative: (project / relative).read_bytes()
        for relative in (
            "05_release/self_reviewed_draft.md",
            "05_release/self_reviewed_draft.docx",
            "05_release/release_snapshot.json",
            "05_release/quality_report.json",
        )
    }


def _make_attribution_missing(project: Path) -> dict[str, object]:
    registry_path = project / "03_figures/source_figure_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert isinstance(registry, dict)
    figures = registry["figures"]
    assert isinstance(figures, list) and len(figures) == 1
    figure = figures[0]
    assert isinstance(figure, dict)
    figure["figure_label"] = "Figure 1 Repaired Label"
    registry["registry_digest"] = canonical_digest(
        {
            key: registry[key]
            for key in (
                "source_truth_digest",
                "content_list_v2_digest",
                "chemical_paper_project_binding_digest",
                "figures",
                "locator_gaps",
            )
        }
    )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert merge_authoritative_manuscript(project)["status"] == "approved"
    return figure


def test_rel001_figure_attribution_target_binding_repairs_release_and_survives_restart() -> None:
    with tempfile.TemporaryDirectory(prefix="rel001-figure-target-binding-") as temporary_root:
        review_root = Path(temporary_root)
        project = _build_project(review_root)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            initial_status, initial_release = _post_release(base_url)
            assert initial_status == 200
            assert initial_release["ok"] is True
            old_release_bytes = _release_bytes(project)

            figure = _make_attribution_missing(project)
            figure_id = str(figure["figure_id"])
            registry_path = project / "03_figures/source_figure_registry.json"
            before_failed_writes = registry_path.read_bytes()

            workspace_status, workspace = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/review-figures"
            )
            assert workspace_status == 200
            assert workspace["manuscript"]["sha256"] == _sha256(
                (project / "04_manuscript/manuscript.md").read_bytes()
            )
            row = next(
                item
                for item in workspace["source_figures"]
                if item["figure_id"] == figure_id
            )
            assert row["target_binding"] is None
            assert row["target_binding_status"] == "missing"
            assert workspace["manuscript"]["sections"]

            valid_binding = {
                "figure_id": figure_id,
                "asset_sha256": figure["asset_sha256"],
                "manuscript_sha256": workspace["manuscript"]["sha256"],
                "section_id": "reported-result",
                "marker": f"[evidence:{EVIDENCE_ID}]",
                "occurrence": 1,
            }
            invalid_status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                payload={
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": row["version_token"],
                    "target_binding": {**valid_binding, "marker": "free text"},
                },
            )
            assert invalid_status in {400, 409}
            assert registry_path.read_bytes() == before_failed_writes
            assert _release_bytes(project) == old_release_bytes

            stale_status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                payload={
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": "stale-version-token",
                    "target_binding": valid_binding,
                },
            )
            assert stale_status == 409
            assert registry_path.read_bytes() == before_failed_writes
            assert _release_bytes(project) == old_release_bytes

            nonunique_status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                payload={
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": row["version_token"],
                    "target_binding": {**valid_binding, "occurrence": 2},
                },
            )
            assert nonunique_status == 400
            assert registry_path.read_bytes() == before_failed_writes
            assert _release_bytes(project) == old_release_bytes

            repaired_status, repaired = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                payload={
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": row["version_token"],
                    "target_binding": valid_binding,
                },
            )
            assert repaired_status == 200
            repaired_row = next(
                item
                for item in repaired["source_figures"]
                if item["figure_id"] == figure_id
            )
            assert repaired_row["target_binding"] == valid_binding
            assert repaired_row["target_binding_status"] == "current"
            persisted = load_source_figure_registry(project)["figures"][0]
            assert persisted["target_binding"] == valid_binding
            assert registry_path.read_bytes() != before_failed_writes

            regenerated_status, regenerated = _post_release(base_url)
            assert regenerated_status == 200
            assert regenerated["ok"] is True
            new_release_bytes = _release_bytes(project)
            assert any(
                new_release_bytes[relative] != old_release_bytes[relative]
                for relative in (
                    "05_release/self_reviewed_draft.md",
                    "05_release/self_reviewed_draft.docx",
                    "05_release/release_snapshot.json",
                    "05_release/quality_report.json",
                )
            )

            manuscript_digest = _sha256(
                (project / "04_manuscript/manuscript.md").read_bytes()
            )
            stale_binding = {**valid_binding, "manuscript_sha256": "0" * 64}
            stale_after_repair_status, _ = _json_request(
                base_url,
                f"/api/project/{PROJECT_ID}/review-figures",
                method="PUT",
                payload={
                    "figure_id": figure_id,
                    "selection_status": "selected",
                    "version_token": repaired_row["version_token"],
                    "target_binding": stale_binding,
                },
            )
            assert stale_after_repair_status in {400, 409}
            assert _sha256((project / "04_manuscript/manuscript.md").read_bytes()) == manuscript_digest
            assert _release_bytes(project) == new_release_bytes

            asset_path = project / str(figure["asset_path"])
            original_asset = asset_path.read_bytes()
            before_asset_failure_registry = registry_path.read_bytes()
            asset_path.write_bytes(original_asset + b"asset-drift")
            try:
                stale_asset_status, _ = _json_request(
                    base_url,
                    f"/api/project/{PROJECT_ID}/review-figures",
                    method="PUT",
                    payload={
                        "figure_id": figure_id,
                        "selection_status": "selected",
                        "version_token": repaired_row["version_token"],
                        "target_binding": valid_binding,
                    },
                )
                assert stale_asset_status == 409
                assert registry_path.read_bytes() == before_asset_failure_registry
                assert _release_bytes(project) == new_release_bytes
            finally:
                asset_path.write_bytes(original_asset)
        finally:
            _stop_dashboard(server, thread)

        server, thread, base_url = _start_dashboard(review_root)
        try:
            current_status, current = _json_request(
                base_url, f"/api/project/{PROJECT_ID}/review-figures"
            )
            assert current_status == 200
            current_row = next(
                item for item in current["source_figures"] if item["figure_id"] == figure_id
            )
            assert current_row["target_binding"] == valid_binding
            final_status, final = _json_request(base_url, f"/api/project/{PROJECT_ID}/final")
            assert final_status == 200
            assert final["release_snapshot"]["matches_authoritative"] is True
            download_path = f"/file?path={quote(f'{PROJECT_ID}/05_release/self_reviewed_draft.docx', safe='')}"
            download_status, downloaded = _request(base_url, download_path)
            assert download_status == 200
            assert downloaded == new_release_bytes["05_release/self_reviewed_draft.docx"]
        finally:
            _stop_dashboard(server, thread)
