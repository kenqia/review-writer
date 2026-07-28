from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from review_writer.acquisition import reusable_library
from review_writer.acquisition.reusable_library import ReusableLibraryError, audit_reusable_library


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts/run_vertical_review.py"


def _request_set_digest(requests: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(
            requests,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _write_asset(root: Path, name: str, content: bytes) -> tuple[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return name, hashlib.sha256(content).hexdigest()


def _library_record(
    root: Path,
    *,
    doi: str | None,
    pdf_bytes: bytes,
    parser_contract: str,
    document_role: str = "MAIN",
) -> dict:
    pdf_path, pdf_sha256 = _write_asset(root, "library/main.pdf", pdf_bytes)
    mineru_path, mineru_sha256 = _write_asset(root, "library/mineru/result.md", b"parsed markdown")
    text_path, text_sha256 = _write_asset(root, "library/text/pages.json", b'{"pages": []}')
    atom_path, atom_sha256 = _write_asset(root, "library/atoms/atom_catalog.json", b'{"atoms": []}')
    return {
        "library_id": "LIB-1",
        "doi": doi,
        "document_role": document_role,
        "pdf": {"path": pdf_path, "sha256": pdf_sha256},
        "parser_contract": parser_contract,
        "reusable_assets": {
            "mineru": {
                "path": mineru_path,
                "sha256": mineru_sha256,
                "source_pdf_sha256": pdf_sha256,
                "parser_contract": parser_contract,
            },
            "text": {
                "path": text_path,
                "sha256": text_sha256,
                "source_pdf_sha256": pdf_sha256,
                "parser_contract": parser_contract,
            },
            "atom": {
                "path": atom_path,
                "sha256": atom_sha256,
                "source_pdf_sha256": pdf_sha256,
                "parser_contract": parser_contract,
            },
        },
        "claims": {"path": "forbidden/claims.json"},
        "candidate": {"path": "forbidden/candidate.json"},
        "reviewer": {"path": "forbidden/reviewer.json"},
        "risk": {"path": "forbidden/risk.json"},
        "manuscript": {"path": "forbidden/manuscript.md"},
    }


def _install_pdf_identity_tools(
    monkeypatch: pytest.MonkeyPatch,
    *,
    page_text: str,
    metadata_text: str = "",
    pdftotext_returncode: int = 0,
) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: f"/synthetic/{name}" if name in {"pdftotext", "pdfinfo"} else None,
    )

    def run(command, **kwargs):
        tool = Path(command[0]).name
        if tool == "pdftotext" and pdftotext_returncode == 0:
            Path(command[-1]).write_text(page_text, encoding="utf-8")
        if tool == "pdfinfo" and metadata_text:
            kwargs["stdout"].write(metadata_text.encode("utf-8"))
        return subprocess.CompletedProcess(
            command,
            pdftotext_returncode if tool == "pdftotext" else 0,
        )

    monkeypatch.setattr(subprocess, "run", run)


def test_audit_matches_by_normalized_doi_and_never_projects_semantic_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pdf_identity_tools(monkeypatch, page_text="DOI: 10.1000/ABC.1")
    record = _library_record(
        tmp_path, doi="10.1000/ABC.1", pdf_bytes=b"%PDF- reusable doi", parser_contract="mineru-v2",
    )
    report = audit_reusable_library(
        requests=[
            {
                "study_id": "S1",
                "doi": "https://doi.org/10.1000/abc.1",
                "document_role": "MAIN",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert report["canonical_artifact"] == "00_sources/reusable_library_audit.json"
    assert report["schema_version"] == "reusable-library-audit.v1"
    assert result["status"] == "REUSABLE"
    assert result["match_basis"] == "DOI"
    assert set(result["assets"]) == {"pdf", "mineru", "text", "atom"}
    serialized = json.dumps(report)
    for forbidden in ("claims", "candidate", "reviewer", "risk", "manuscript"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("page_text", "returncode", "expected_status", "expected_reason"),
    (
        ("DOI: 10.1000/different", 0, "NOT_REUSABLE", "PDF_DOI_MISMATCH"),
        (
            "DOI: 10.1000/doi-only and DOI: 10.1000/second",
            0,
            "UNRESOLVED",
            "PDF_IDENTITY_AMBIGUOUS",
        ),
        ("", 1, "UNRESOLVED", "PDF_IDENTITY_UNRESOLVED"),
    ),
)
def test_doi_only_reuse_requires_one_matching_pdf_doi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_text: str,
    returncode: int,
    expected_status: str,
    expected_reason: str,
) -> None:
    _install_pdf_identity_tools(
        monkeypatch,
        page_text=page_text,
        pdftotext_returncode=returncode,
    )
    record = _library_record(
        tmp_path,
        doi="10.1000/doi-only",
        pdf_bytes=b"%PDF- DOI-only identity",
        parser_contract="mineru-v2",
    )

    report = audit_reusable_library(
        requests=[
            {
                "study_id": "DOI-ONLY",
                "doi": "10.1000/doi-only",
                "document_role": "MAIN",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == expected_status
    assert result["reason"] == expected_reason
    assert result["assets"] == {}


@pytest.mark.parametrize(
    ("page_text", "metadata_text", "expected_reason"),
    (
        ("No DOI on the first page", "DOI: 10.1000/page-authority", "PDF_IDENTITY_UNRESOLVED"),
        (
            "DOI: 10.1000/page-authority",
            "DOI: 10.1000/conflicting-metadata",
            "PDF_IDENTITY_AMBIGUOUS",
        ),
        (
            "DOI: 10.1000/page-authority",
            "DOI: 10.1000/page-authority DOI: 10.1000/second-metadata",
            "PDF_IDENTITY_AMBIGUOUS",
        ),
    ),
)
def test_doi_only_reuse_requires_first_page_authority_and_metadata_has_veto_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_text: str,
    metadata_text: str,
    expected_reason: str,
) -> None:
    _install_pdf_identity_tools(
        monkeypatch,
        page_text=page_text,
        metadata_text=metadata_text,
    )
    record = _library_record(
        tmp_path,
        doi="10.1000/page-authority",
        pdf_bytes=b"%PDF- page identity authority",
        parser_contract="mineru-v2",
    )

    report = audit_reusable_library(
        requests=[
            {
                "study_id": "PAGE-AUTHORITY",
                "doi": "10.1000/page-authority",
                "document_role": "MAIN",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == expected_reason
    assert result["assets"] == {}


def test_doi_only_reuse_is_unresolved_when_pdf_tools_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unavailable PDF tools must not be invoked")
        ),
    )
    record = _library_record(
        tmp_path,
        doi="10.1000/no-tools",
        pdf_bytes=b"%PDF- no identity tools",
        parser_contract="mineru-v2",
    )

    report = audit_reusable_library(
        requests=[{"study_id": "NO-TOOLS", "doi": "10.1000/no-tools", "document_role": "MAIN"}],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == "PDF_IDENTITY_UNRESOLVED"
    assert result["assets"] == {}


def test_audit_falls_back_to_pdf_sha256_without_a_doi(tmp_path: Path) -> None:
    pdf_bytes = b"%PDF- reusable hash"
    record = _library_record(tmp_path, doi=None, pdf_bytes=pdf_bytes, parser_contract="mineru-v2")
    report = audit_reusable_library(
        requests=[
            {
                "study_id": "S2",
                "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                "document_role": "MAIN",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    assert report["results"][0]["status"] == "REUSABLE"
    assert report["results"][0]["match_basis"] == "PDF_SHA256"


def test_parser_contract_mismatch_reuses_only_the_verified_pdf(tmp_path: Path) -> None:
    record = _library_record(
        tmp_path, doi="10.1000/parser", pdf_bytes=b"%PDF- parser mismatch", parser_contract="mineru-v1",
    )
    report = audit_reusable_library(
        requests=[
            {
                "study_id": "S3",
                "doi": "10.1000/parser",
                "pdf_sha256": record["pdf"]["sha256"],
                "document_role": "MAIN",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == "PDF_ONLY"
    assert result["reason"] == "PARSER_CONTRACT_MISMATCH"
    assert set(result["assets"]) == {"pdf"}


def test_changed_or_ambiguous_library_assets_are_not_reused(tmp_path: Path) -> None:
    record = _library_record(
        tmp_path, doi="10.1000/changed", pdf_bytes=b"%PDF- original", parser_contract="mineru-v2",
    )
    (tmp_path / record["pdf"]["path"]).write_bytes(b"%PDF- changed")
    duplicate = dict(record)
    duplicate["library_id"] = "LIB-2"

    changed = audit_reusable_library(
        requests=[{"study_id": "S4", "doi": "10.1000/changed", "document_role": "MAIN"}],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )
    ambiguous = audit_reusable_library(
        requests=[{"study_id": "S5", "doi": "10.1000/changed", "document_role": "MAIN"}],
        library_root=tmp_path,
        library_records=[record, duplicate],
        required_parser_contract="mineru-v2",
    )

    assert changed["results"][0]["status"] == "NOT_REUSABLE"
    assert changed["results"][0]["reason"] == "PDF_HASH_MISMATCH"
    assert ambiguous["results"][0]["status"] == "UNRESOLVED"
    assert ambiguous["results"][0]["reason"] == "AMBIGUOUS_LIBRARY_MATCH"


def test_reusable_assets_reject_symlinks_even_when_the_target_stays_in_library(
    tmp_path: Path,
) -> None:
    record = _library_record(
        tmp_path,
        doi="10.1000/symlinked-asset",
        pdf_bytes=b"%PDF- symlink target",
        parser_contract="mineru-v2",
    )
    pdf_path = tmp_path / record["pdf"]["path"]
    real_path = pdf_path.with_name("real-main.pdf")
    pdf_path.rename(real_path)
    pdf_path.symlink_to(real_path.name)

    with pytest.raises(ReusableLibraryError):
        audit_reusable_library(
            requests=[
                {
                    "study_id": "SYMLINKED",
                    "doi": "10.1000/symlinked-asset",
                    "document_role": "MAIN",
                }
            ],
            library_root=tmp_path,
            library_records=[record],
            required_parser_contract="mineru-v2",
        )


def test_reusable_asset_replacement_during_hashing_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _library_record(
        tmp_path,
        doi="10.1000/replaced-asset",
        pdf_bytes=b"%PDF- original descriptor bytes",
        parser_contract="mineru-v2",
    )
    pdf_path = tmp_path / record["pdf"]["path"]
    real_sha256 = hashlib.sha256
    replaced = False

    class ReplacingDigest:
        def __init__(self, data: bytes = b"") -> None:
            self._digest = real_sha256(data)

        def update(self, chunk: bytes) -> None:
            nonlocal replaced
            self._digest.update(chunk)
            if not replaced:
                replaced = True
                old_path = pdf_path.with_name("opened-main.pdf")
                pdf_path.rename(old_path)
                pdf_path.write_bytes(b"%PDF- replacement bytes")

        def hexdigest(self) -> str:
            return self._digest.hexdigest()

    monkeypatch.setattr(reusable_library.hashlib, "sha256", ReplacingDigest)

    with pytest.raises(ReusableLibraryError):
        audit_reusable_library(
            requests=[
                {
                    "study_id": "REPLACED",
                    "doi": "10.1000/replaced-asset",
                    "document_role": "MAIN",
                }
            ],
            library_root=tmp_path,
            library_records=[record],
            required_parser_contract="mineru-v2",
        )

    assert replaced


def test_reusable_asset_size_is_rejected_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_bytes = b"%PDF- bounded reusable bytes"
    record = _library_record(
        tmp_path,
        doi="10.1000/bounded-asset",
        pdf_bytes=pdf_bytes,
        parser_contract="mineru-v2",
    )
    monkeypatch.setattr(reusable_library, "MAX_REUSABLE_ASSET_BYTES", len(pdf_bytes) - 1)
    monkeypatch.setattr(
        reusable_library.hashlib,
        "sha256",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("oversized reusable asset must not be hashed")
        ),
    )

    with pytest.raises(ReusableLibraryError):
        audit_reusable_library(
            requests=[
                {
                    "study_id": "BOUNDED",
                    "doi": "10.1000/bounded-asset",
                    "document_role": "MAIN",
                }
            ],
            library_root=tmp_path,
            library_records=[record],
            required_parser_contract="mineru-v2",
        )


def test_same_doi_with_a_different_requested_pdf_hash_requires_reparse(tmp_path: Path) -> None:
    record = _library_record(
        tmp_path,
        doi="10.1000/same-doi",
        pdf_bytes=b"%PDF- library version",
        parser_contract="mineru-v2",
    )

    report = audit_reusable_library(
        requests=[
            {
                "study_id": "S6",
                "doi": "10.1000/same-doi",
                "pdf_sha256": hashlib.sha256(b"%PDF- changed request").hexdigest(),
                "document_role": "MAIN",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == "NOT_REUSABLE"
    assert result["reason"] == "REQUEST_PDF_HASH_MISMATCH"
    assert result["assets"] == {}


def test_stale_derived_source_binding_reuses_only_pdf(tmp_path: Path) -> None:
    record = _library_record(
        tmp_path,
        doi="10.1000/stale-derived",
        pdf_bytes=b"%PDF- current source",
        parser_contract="mineru-v2",
    )
    record["reusable_assets"]["atom"]["source_pdf_sha256"] = "0" * 64

    report = audit_reusable_library(
        requests=[
                {
                    "study_id": "S7",
                    "doi": "10.1000/stale-derived",
                    "pdf_sha256": record["pdf"]["sha256"],
                    "document_role": "MAIN",
                }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == "PDF_ONLY"
    assert result["reason"] == "DERIVED_ASSET_BINDING_MISMATCH"
    assert set(result["assets"]) == {"pdf"}


def test_main_and_si_records_are_never_interchanged(tmp_path: Path) -> None:
    record = _library_record(
        tmp_path,
        doi="10.1000/role-bound",
        pdf_bytes=b"%PDF- main",
        parser_contract="mineru-v2",
        document_role="MAIN",
    )

    report = audit_reusable_library(
        requests=[
            {
                "study_id": "S8",
                "doi": "10.1000/role-bound",
                "document_role": "SI",
            }
        ],
        library_root=tmp_path,
        library_records=[record],
        required_parser_contract="mineru-v2",
    )

    result = report["results"][0]
    assert result["status"] == "NOT_REUSABLE"
    assert result["reason"] == "DOCUMENT_ROLE_MISMATCH"
    assert result["assets"] == {}


def _run_library_audit(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "audit-reusable-library",
            "--project-dir",
            str(project),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_audits_only_explicit_project_relative_library_descriptor(tmp_path: Path) -> None:
    project = tmp_path / "review-project"
    library_root = project / "researcher-library"
    record = _library_record(
        library_root,
        doi="10.1000/cli-reuse",
        pdf_bytes=b"%PDF- explicit reusable source",
        parser_contract="mineru-v2",
    )
    manifest = project / "00_discovery/acquisition_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "downloads": [
                        {
                            "study_id": "CLI-STUDY",
                            "doi": "10.1000/cli-reuse",
                            "expected_sha256": record["pdf"]["sha256"],
                            "document_role": "MAIN",
                        }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    descriptor = project / "00_sources/reusable_library_descriptor.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(
        json.dumps(
            {
                "library_root": "researcher-library",
                "library_records": [record],
                "required_parser_contract": "mineru-v2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    library_before = {
        path.relative_to(library_root).as_posix(): path.read_bytes()
        for path in library_root.rglob("*")
        if path.is_file()
    }

    completed = _run_library_audit(project)

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary == {
        "command": "audit-reusable-library",
        "library_status": "DECLARED",
        "reusable_count": 1,
        "status": "AUDITED",
    }
    report = json.loads(
        (project / "00_sources/reusable_library_audit.json").read_text(encoding="utf-8")
    )
    assert report["request_set_digest"] == _request_set_digest(
        [
            {
                "document_role": "MAIN",
                "doi": "10.1000/cli-reuse",
                "pdf_sha256": record["pdf"]["sha256"],
                "study_id": "CLI-STUDY",
            }
        ]
    )
    assert report["results"][0]["status"] == "REUSABLE"
    assert report["library_status"] == "DECLARED"
    assert {
        path.relative_to(library_root).as_posix(): path.read_bytes()
        for path in library_root.rglob("*")
        if path.is_file()
    } == library_before
    assert str(tmp_path) not in completed.stdout + completed.stderr


def test_cli_writes_explicit_empty_audit_without_scanning_when_library_is_absent(
    tmp_path: Path,
) -> None:
    project = tmp_path / "review-project"
    manifest = project / "00_discovery/acquisition_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "downloads": [
                    {
                        "study_id": "NO-LIBRARY",
                        "doi": "10.1000/no-library",
                        "document_role": "SI",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = _run_library_audit(project)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(
        (project / "00_sources/reusable_library_audit.json").read_text(encoding="utf-8")
    )
    assert report["library_status"] == "NOT_DECLARED"
    assert report["results"] == [
        {
            "assets": {},
            "document_role": "SI",
            "library_id": None,
            "match_basis": "DOI",
            "reason": "NO_LIBRARY_MATCH",
            "status": "NOT_REUSABLE",
            "study_id": "NO-LIBRARY",
        }
    ]
    assert not (project / "researcher-library").exists()


def test_cli_without_a_manifest_writes_the_empty_request_set_digest(tmp_path: Path) -> None:
    project = tmp_path / "review-project"
    project.mkdir()

    completed = _run_library_audit(project)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(
        (project / "00_sources/reusable_library_audit.json").read_text(encoding="utf-8")
    )
    assert report["request_set_digest"] == _request_set_digest([])
    assert report["results"] == []


def test_cli_rejects_library_roots_outside_the_project_without_writing_audit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "review-project"
    descriptor = project / "00_sources/reusable_library_descriptor.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(
        json.dumps(
            {
                "library_root": str(tmp_path / "private-library"),
                "library_records": [],
                "required_parser_contract": "mineru-v2",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = _run_library_audit(project)

    assert completed.returncode == 2
    assert json.loads(completed.stderr) == {
        "command": "audit-reusable-library",
        "error_code": "INPUT_OR_IO_INVALID",
        "status": "ERROR",
    }
    assert not (project / "00_sources/reusable_library_audit.json").exists()
    assert str(tmp_path) not in completed.stdout + completed.stderr
