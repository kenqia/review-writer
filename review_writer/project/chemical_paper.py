"""Fail-closed import and lineage for MinerU Chemical Paper manual exports.

The original project PDF remains authoritative.  This module never extracts an
archive to disk, contacts MinerU, or synthesizes a missing chemical field.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from jsonschema import Draft202012Validator

from .paper_evidence_store import PaperEvidenceStoreError, project_write_lock
from .source_truth import (
    REPO_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
    project_source_binding,
    source_truth_asset,
)


STATE_ROOT = Path("01_evidence/chemical_paper")
STATE_NAME = "state.json"
STATE_SCHEMA = REPO_ROOT / "schemas/evidence/chemical_paper_state.v1.schema.json"
FIELD_NAMES = ("mol_idt", "smiles_expanded", "smiles_unexpanded")
REQUIRED_FIELD_NAMES = frozenset((*FIELD_NAMES, "elements"))
ELEMENT_REVIEW_STATES = frozenset({"not_reviewed", "confirmed", "corrected", "not_applicable"})
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ENTRY_COUNT = 16
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
NESTED_ARCHIVE_SUFFIXES = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^(?!\.\.?$)(?!.*[/\\\x00\r\n])\S{1,240}$")
_ELEMENT = re.compile(r"^[A-Z][a-z]?$|^\*$")
_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce "
    "Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn "
    "Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc "
    "Lv Ts Og".split()
)


class ChemicalPaperError(ValueError):
    """Stable fail-closed Chemical Paper error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ChemicalPaperError(code)
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ChemicalPaperError(code)
    return value


def _actor(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"actor_type", "actor_label"}:
        raise ChemicalPaperError("ACTOR_INVALID")
    actor_type = value.get("actor_type")
    actor_label = value.get("actor_label")
    if actor_type not in {"human_researcher", "simulated_researcher_agent"}:
        raise ChemicalPaperError("ACTOR_INVALID")
    if not isinstance(actor_label, str) or actor_label != actor_label.strip() or not actor_label or len(actor_label) > 200:
        raise ChemicalPaperError("ACTOR_INVALID")
    return {"actor_type": actor_type, "actor_label": actor_label}


def _reason(value: object) -> str:
    if not isinstance(value, str) or value != value.strip() or not value or len(value) > 2000:
        raise ChemicalPaperError("REASON_INVALID")
    return value


def _project(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise ChemicalPaperError("PROJECT_INVALID")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ChemicalPaperError("PROJECT_INVALID") from exc
    path = root / STATE_ROOT
    if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
        raise ChemicalPaperError("CHEMICAL_PAPER_PATH_INVALID")
    return root


def _state_path(project: Path, study_id: str) -> Path:
    return project / STATE_ROOT / _identifier(study_id, "STUDY_ID_INVALID") / STATE_NAME


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ChemicalPaperError("ZIP_INVALID") from exc
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ChemicalPaperError("CHEMICAL_PAPER_STATE_INVALID") from exc


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (os.path.lexists(path) and (path.is_symlink() or not path.is_file())):
        raise ChemicalPaperError("CHEMICAL_PAPER_PATH_INVALID")
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise ChemicalPaperError("CHEMICAL_PAPER_WRITE_FAILED") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _canonical_state_digest(state: dict[str, Any]) -> str:
    return canonical_digest({key: value for key, value in state.items() if key != "state_digest"})


def _version_token(state: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(bytes.fromhex(state["state_digest"])).decode("ascii").rstrip("=")
    return f"cpv1.{encoded}"


def _validate_event_chain(rows: list[dict[str, Any]], *, event_key: str, prior_key: str) -> str | None:
    head: str | None = None
    for row in rows:
        if row.get(prior_key) != head:
            raise ChemicalPaperError("CHEMICAL_PAPER_HISTORY_INVALID")
        expected = canonical_digest({key: value for key, value in row.items() if key != event_key})
        if row.get(event_key) != expected:
            raise ChemicalPaperError("CHEMICAL_PAPER_HISTORY_INVALID")
        head = expected
    return head


def _validate_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ChemicalPaperError("CHEMICAL_PAPER_STATE_INVALID")
    try:
        schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChemicalPaperError("CHEMICAL_PAPER_SCHEMA_INVALID") from exc
    if list(Draft202012Validator(schema).iter_errors(state)):
        raise ChemicalPaperError("CHEMICAL_PAPER_STATE_INVALID")
    imports = list(state["imports"].values())
    for index, row in enumerate(imports):
        expected_prior = imports[index - 1]["import_event_digest"] if index else None
        if row["prior_import_event_digest"] != expected_prior:
            raise ChemicalPaperError("CHEMICAL_PAPER_HISTORY_INVALID")
        if state["imports"].get(row["import_digest"]) != row:
            raise ChemicalPaperError("CHEMICAL_PAPER_HISTORY_INVALID")
        event = canonical_digest({key: value for key, value in row.items() if key != "import_event_digest"})
        if row["import_event_digest"] != event:
            raise ChemicalPaperError("CHEMICAL_PAPER_HISTORY_INVALID")
    if imports[-1]["import_digest"] != state["current_import_digest"]:
        raise ChemicalPaperError("CHEMICAL_PAPER_STATE_INVALID")
    correction_head = _validate_event_chain(
        state["field_corrections"], event_key="event_digest", prior_key="prior_event_digest"
    )
    review_head = _validate_event_chain(
        state["element_reviews"], event_key="event_digest", prior_key="prior_event_digest"
    )
    if state["field_correction_head_digest"] != correction_head or state["element_review_head_digest"] != review_head:
        raise ChemicalPaperError("CHEMICAL_PAPER_HISTORY_INVALID")
    if state.get("state_digest") != _canonical_state_digest(state):
        raise ChemicalPaperError("CHEMICAL_PAPER_STATE_INVALID")
    return copy.deepcopy(state)


def load_chemical_paper_state(project: Path, study_id: str) -> dict[str, Any]:
    root = _project(project)
    path = _state_path(root, study_id)
    if not path.is_file() or path.is_symlink():
        raise ChemicalPaperError("CHEMICAL_PAPER_NOT_IMPORTED")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChemicalPaperError("CHEMICAL_PAPER_STATE_INVALID") from exc
    state = _validate_state(value)
    try:
        bundle = load_source_truth_bundle(root, study_id)
        for current_study_id in declared_study_ids(root):
            current_bundle = (
                bundle
                if current_study_id == study_id
                else load_source_truth_bundle(root, current_study_id)
            )
            if (
                current_bundle.get("project_id") != root.name
                or current_bundle.get("study_id") != current_study_id
            ):
                raise SourceTruthError("SOURCE_TRUTH_IDENTITY_MISMATCH")
        resolved_study_id, resolved_source = project_source_binding(
            root,
            state["source_id"],
        )
    except SourceTruthError as exc:
        raise ChemicalPaperError("CHEMICAL_PAPER_SOURCE_TRUTH_STALE") from exc
    sources = bundle.get("sources")
    current = [
        row
        for row in sources
        if isinstance(row, dict)
        and row.get("document_role") == "MAIN"
        and row.get("source_id") == state["source_id"]
        and isinstance(row.get("pdf"), dict)
        and row["pdf"].get("sha256") == state["source_pdf_sha256"]
    ] if isinstance(sources, list) else []
    active = state["imports"][state["current_import_digest"]]
    if (
        bundle.get("bundle_digest") != state["source_truth_bundle_digest"]
        or state["project_id"] != root.name
        or state["study_id"] != study_id
        or bundle.get("project_id") != root.name
        or bundle.get("study_id") != study_id
        or resolved_study_id != study_id
        or len(current) != 1
        or resolved_source != current[0]
        or active["source_id"] != state["source_id"]
        or active["source_pdf_sha256"] != state["source_pdf_sha256"]
        or active["source_truth_bundle_digest"] != state["source_truth_bundle_digest"]
        or active["page_count"] != current[0]["page_count"]
        or active["molecule_count"] != len(state["molecules"])
        or any(
            molecule["page_index"] >= current[0]["page_count"]
            for molecule in state["molecules"]
        )
    ):
        raise ChemicalPaperError("CHEMICAL_PAPER_SOURCE_TRUTH_STALE")
    try:
        source_truth_asset(root, study_id, state["source_id"], "pdf")
    except SourceTruthError as exc:
        raise ChemicalPaperError(exc.code) from exc
    return state


def chemical_paper_current_binding(project: Path, study_id: str) -> dict[str, str]:
    """Return current Chemical provenance without exposing archive or molecule payloads."""
    state = load_chemical_paper_state(project, study_id)
    return {
        "source_pdf_sha256": state["source_pdf_sha256"],
        "source_truth_bundle_digest": state["source_truth_bundle_digest"],
        "import_digest": state["current_import_digest"],
        "state_digest": state["state_digest"],
    }


def _safe_member_name(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name)
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or "\\" in normalized
        or normalized.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in pure.parts)
        or normalized.endswith("/")
    ):
        raise ChemicalPaperError("ZIP_PATH_UNSAFE")
    return normalized


def _zip_inventory(path: Path) -> tuple[zipfile.ZipFile, list[zipfile.ZipInfo]]:
    if path.is_symlink() or not path.is_file():
        raise ChemicalPaperError("ZIP_INVALID")
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ChemicalPaperError("ZIP_SIZE_LIMIT")
        archive = zipfile.ZipFile(path, "r")
        members = archive.infolist()
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ChemicalPaperError("ZIP_INVALID") from exc
    if not members or len(members) > MAX_ENTRY_COUNT:
        archive.close()
        raise ChemicalPaperError("ZIP_ENTRY_COUNT_LIMIT")
    names: set[str] = set()
    total = 0
    try:
        for member in members:
            name = _safe_member_name(member.filename)
            folded = name.casefold()
            if folded in names:
                raise ChemicalPaperError("ZIP_DUPLICATE_ENTRY")
            names.add(folded)
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ChemicalPaperError("ZIP_SYMLINK_UNSAFE")
            if member.flag_bits & 0x1:
                raise ChemicalPaperError("ZIP_ENCRYPTED")
            if PurePosixPath(name).suffix.casefold() in NESTED_ARCHIVE_SUFFIXES:
                raise ChemicalPaperError("ZIP_NESTED_ARCHIVE")
            if member.file_size > MAX_ENTRY_BYTES:
                raise ChemicalPaperError("ZIP_SIZE_LIMIT")
            total += member.file_size
            if total > MAX_TOTAL_BYTES:
                raise ChemicalPaperError("ZIP_SIZE_LIMIT")
            ratio = member.file_size / max(member.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise ChemicalPaperError("ZIP_COMPRESSION_RATIO_LIMIT")
    except Exception:
        archive.close()
        raise
    return archive, members


def _read_entry(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> bytes:
    try:
        payload = archive.read(member)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ChemicalPaperError("ZIP_ENTRY_INVALID") from exc
    if len(payload) != member.file_size:
        raise ChemicalPaperError("ZIP_ENTRY_INVALID")
    return payload


def _json_entry(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ChemicalPaperError("CHEMICAL_PAPER_JSON_INVALID") from exc


def _bbox(value: object) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in value)
    ):
        raise ChemicalPaperError("MOLECULE_BBOX_INVALID")
    result = [float(item) for item in value]
    if any(item < 0 or item > 1 for item in result) or result[0] > result[2] or result[1] > result[3]:
        raise ChemicalPaperError("MOLECULE_BBOX_INVALID")
    return result


def _molblock_elements(value: object) -> tuple[str, dict[str, int]]:
    if not isinstance(value, str) or not value.endswith(("M  END", "M  END\n", "M  END\r\n")):
        raise ChemicalPaperError("MOLBLOCK_INVALID")
    lines = value.replace("\r\n", "\n").splitlines()
    counts_index = next((index for index, line in enumerate(lines) if "V2000" in line or "V3000" in line), None)
    if counts_index is None:
        raise ChemicalPaperError("MOLBLOCK_INVALID")
    counts: Counter[str] = Counter()
    if "V2000" in lines[counts_index]:
        try:
            atom_count = int(lines[counts_index][:3])
        except ValueError as exc:
            raise ChemicalPaperError("MOLBLOCK_INVALID") from exc
        atom_lines = lines[counts_index + 1 : counts_index + 1 + atom_count]
        if atom_count < 0 or len(atom_lines) != atom_count:
            raise ChemicalPaperError("MOLBLOCK_INVALID")
        for line in atom_lines:
            parts = line.split()
            if len(parts) < 4:
                raise ChemicalPaperError("MOLBLOCK_INVALID")
            symbol = parts[3]
            if not _ELEMENT.fullmatch(symbol) or symbol not in _ELEMENTS:
                raise ChemicalPaperError("MOLBLOCK_INVALID")
            counts[symbol] += 1
        version = "V2000"
    else:
        try:
            begin = lines.index("M  V30 BEGIN ATOM")
            end = lines.index("M  V30 END ATOM")
        except ValueError as exc:
            raise ChemicalPaperError("MOLBLOCK_INVALID") from exc
        if begin >= end or "M  V30 BEGIN CTAB" not in lines or "M  V30 END CTAB" not in lines:
            raise ChemicalPaperError("MOLBLOCK_INVALID")
        for line in lines[begin + 1 : end]:
            parts = line.split()
            if len(parts) < 7 or parts[:2] != ["M", "V30"]:
                raise ChemicalPaperError("MOLBLOCK_INVALID")
            symbol = parts[3]
            if not _ELEMENT.fullmatch(symbol) or symbol not in _ELEMENTS:
                raise ChemicalPaperError("MOLBLOCK_INVALID")
            counts[symbol] += 1
        if not counts:
            raise ChemicalPaperError("MOLBLOCK_INVALID")
        version = "V3000"
    return version, dict(sorted(counts.items()))


def _field(value: object) -> dict[str, Any]:
    if value is None or value == "":
        return {"status": "unresolved", "value": None}
    if not isinstance(value, str) or value != value.strip() or len(value) > 20000:
        raise ChemicalPaperError("MOLECULE_FIELD_INVALID")
    return {"status": "candidate", "value": value}


def _normalize_molecules(value: object, page_count: int, import_digest_seed: str) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"molecules"} or not isinstance(value["molecules"], list) or not value["molecules"]:
        raise ChemicalPaperError("CHEMICAL_PAPER_CONTRACT_MISSING")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {"mol_id", "page_idx", "bbox_normalized", "smiles_expanded", "smiles_unexpanded", "mol_idt", "mol_block"}
    for raw in value["molecules"]:
        if not isinstance(raw, dict) or not required <= set(raw):
            raise ChemicalPaperError("MOLECULE_INVALID")
        molecule_id = _identifier(raw.get("mol_id"), "MOLECULE_ID_INVALID")
        if molecule_id in seen:
            raise ChemicalPaperError("MOLECULE_ID_DUPLICATE")
        seen.add(molecule_id)
        page = raw.get("page_idx")
        if not isinstance(page, int) or isinstance(page, bool) or page < 0 or page >= page_count:
            raise ChemicalPaperError("MOLECULE_PAGE_INVALID")
        block_version, elements = _molblock_elements(raw.get("mol_block"))
        body = {
            "molecule_id": molecule_id,
            "page_index": page,
            "normalized_bbox": _bbox(raw.get("bbox_normalized")),
            "mol_block": raw["mol_block"],
            "molblock_format": block_version,
            "fields": {field: _field(raw.get(field)) for field in FIELD_NAMES},
            "element_candidate_counts": elements,
            "element_review_state": "not_reviewed",
            "bound_import_seed": import_digest_seed,
        }
        body["molecule_digest"] = canonical_digest(body)
        rows.append(body)
    return rows


def _source_binding(project: Path, study_id: str, pdf_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _digest(pdf_sha256, "SOURCE_PDF_SHA256_INVALID")
    try:
        bundle = load_source_truth_bundle(project, study_id)
    except SourceTruthError as exc:
        raise ChemicalPaperError(exc.code) from exc
    sources = bundle.get("sources")
    matches = [
        row for row in sources if isinstance(row, dict) and row.get("document_role") == "MAIN"
        and isinstance(row.get("pdf"), dict) and row["pdf"].get("sha256") == pdf_sha256
    ] if isinstance(sources, list) else []
    if len(matches) != 1:
        raise ChemicalPaperError("SOURCE_PDF_STALE")
    return bundle, matches[0]


def _validate_main(value: object, expected_pages: int) -> tuple[str, str, int]:
    if not isinstance(value, dict):
        raise ChemicalPaperError("CHEMICAL_PAPER_MAIN_INVALID")
    backend, version, pages = value.get("_backend"), value.get("_version_name"), value.get("pdf_info")
    if not isinstance(backend, str) or not backend or not isinstance(version, str) or not version or not isinstance(pages, list):
        raise ChemicalPaperError("CHEMICAL_PAPER_MAIN_INVALID")
    if len(pages) != expected_pages:
        raise ChemicalPaperError("CHEMICAL_PAPER_PAGE_COUNT_MISMATCH")
    indexes: list[int] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("page_idx"), int) or isinstance(page.get("page_idx"), bool):
            raise ChemicalPaperError("CHEMICAL_PAPER_PAGE_INVALID")
        indexes.append(page["page_idx"])
    if sorted(indexes) != list(range(expected_pages)):
        raise ChemicalPaperError("CHEMICAL_PAPER_PAGE_INVALID")
    return backend, version, len(pages)


def _archive_payload(path: Path, expected_pages: int) -> dict[str, Any]:
    archive, members = _zip_inventory(path)
    try:
        if len(members) != 3:
            raise ChemicalPaperError("CHEMICAL_PAPER_FILE_SET_INVALID")
        decoded: list[tuple[zipfile.ZipInfo, bytes]] = [(member, _read_entry(archive, member)) for member in members]
    finally:
        archive.close()
    markdown = [(member, payload) for member, payload in decoded if member.filename.casefold().endswith(".md")]
    json_rows = [(member, payload, _json_entry(payload)) for member, payload in decoded if member.filename.casefold().endswith(".json")]
    if len(markdown) != 1 or len(json_rows) != 2:
        raise ChemicalPaperError("CHEMICAL_PAPER_FILE_SET_INVALID")
    main = [row for row in json_rows if isinstance(row[2], dict) and {"_backend", "_version_name", "pdf_info"} <= set(row[2])]
    molecules = [row for row in json_rows if isinstance(row[2], dict) and "molecules" in row[2]]
    if len(main) != 1 or len(molecules) != 1:
        raise ChemicalPaperError("CHEMICAL_PAPER_CONTRACT_MISSING")
    backend, version, page_count = _validate_main(main[0][2], expected_pages)
    inventory = []
    for member, payload in [(row[0], row[1]) for row in json_rows] + markdown:
        kind = (
            "main_layout_json" if member is main[0][0]
            else "molecule_info_json" if member is molecules[0][0]
            else "markdown"
        )
        inventory.append({"entry_name": member.filename, "file_kind": kind, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)})
    inventory.sort(key=lambda row: row["file_kind"])
    archive_sha = _sha256_file(path)
    seed = canonical_digest({"archive_sha256": archive_sha, "inventory": inventory})
    normalized_molecules = _normalize_molecules(molecules[0][2], page_count, seed)
    return {
        "archive_sha256": archive_sha,
        "backend": backend,
        "version": version,
        "page_count": page_count,
        "entry_inventory": inventory,
        "molecules": normalized_molecules,
    }


def import_chemical_paper(
    project: Path,
    study_id: str,
    source_pdf_sha256: str,
    zip_path: Path,
    actor: object,
) -> dict[str, Any]:
    """Validate and atomically bind one explicit study/PDF/archive tuple."""
    root = _project(project)
    study_id = _identifier(study_id, "STUDY_ID_INVALID")
    who = _actor(actor)
    bundle, source = _source_binding(root, study_id, source_pdf_sha256)
    parsed = _archive_payload(Path(zip_path), int(source["page_count"]))
    import_body = {
        "archive_sha256": parsed["archive_sha256"],
        "source_pdf_sha256": source_pdf_sha256,
        "source_truth_bundle_digest": bundle["bundle_digest"],
        "source_id": source["source_id"],
        "backend": parsed["backend"],
        "version": parsed["version"],
        "page_count": parsed["page_count"],
        "entry_inventory": parsed["entry_inventory"],
        "molecule_count": len(parsed["molecules"]),
        "reaction_data_status": "unavailable_not_provided",
    }
    import_digest = canonical_digest(import_body)
    path = _state_path(root, study_id)
    try:
        with project_write_lock(root):
            existing: dict[str, Any] | None = None
            if path.exists():
                existing = load_chemical_paper_state(root, study_id)
                active = existing["imports"][existing["current_import_digest"]]
                if active["archive_sha256"] == parsed["archive_sha256"] and active["source_pdf_sha256"] == source_pdf_sha256:
                    return {"status": "unchanged", "study_id": study_id, "version_token": _version_token(existing)}
            prior_import = (
                existing["imports"][existing["current_import_digest"]]["import_event_digest"]
                if existing else None
            )
            event = {
                **import_body,
                "import_digest": import_digest,
                "imported_at": _now(),
                "actor": who,
                "prior_import_event_digest": prior_import,
            }
            event["import_event_digest"] = canonical_digest(event)
            state: dict[str, Any] = {
                "schema_version": "chemical-paper-state.v1",
                "project_id": root.name,
                "study_id": study_id,
                "source_id": source["source_id"],
                "source_truth_bundle_digest": bundle["bundle_digest"],
                "source_pdf_sha256": source_pdf_sha256,
                "current_import_digest": import_digest,
                "imports": {**(existing["imports"] if existing else {}), import_digest: event},
                "molecules": parsed["molecules"],
                "field_corrections": existing["field_corrections"] if existing else [],
                "field_correction_head_digest": existing["field_correction_head_digest"] if existing else None,
                "element_reviews": existing["element_reviews"] if existing else [],
                "element_review_head_digest": existing["element_review_head_digest"] if existing else None,
            }
            state["state_digest"] = _canonical_state_digest(state)
            _validate_state(state)
            _atomic_json(path, state)
    except PaperEvidenceStoreError as exc:
        raise ChemicalPaperError(exc.code) from exc
    return {"status": "imported", "study_id": study_id, "version_token": _version_token(state)}


def _molecule(state: dict[str, Any], molecule_id: str) -> dict[str, Any]:
    molecule_id = _identifier(molecule_id, "MOLECULE_ID_INVALID")
    matches = [row for row in state["molecules"] if row["molecule_id"] == molecule_id]
    if len(matches) != 1:
        raise ChemicalPaperError("MOLECULE_NOT_FOUND")
    return matches[0]


def _molecule_by_index(state: dict[str, Any], molecule_index: object) -> dict[str, Any]:
    if (
        not isinstance(molecule_index, int)
        or isinstance(molecule_index, bool)
        or molecule_index < 0
        or molecule_index >= len(state["molecules"])
    ):
        raise ChemicalPaperError("MOLECULE_NOT_FOUND")
    return state["molecules"][molecule_index]


def _current_value(state: dict[str, Any], molecule: dict[str, Any], field: str) -> str | None:
    value = molecule["fields"][field]["value"]
    for event in state["field_corrections"]:
        if event["bound_import_digest"] == state["current_import_digest"] and event["molecule_id"] == molecule["molecule_id"] and event["field"] == field:
            value = event["value"]
    return value


def _current_element_review(state: dict[str, Any], molecule: dict[str, Any]) -> tuple[str, dict[str, int], str | None]:
    review_state = "not_reviewed"
    counts = molecule["element_candidate_counts"]
    digest: str | None = None
    for event in state["element_reviews"]:
        if event["bound_import_digest"] == state["current_import_digest"] and event["molecule_id"] == molecule["molecule_id"]:
            review_state = event["state"]
            counts = event["reviewed_counts"] if event["reviewed_counts"] is not None else counts
            digest = event["event_digest"]
    return review_state, counts, digest


def _require_mutation_binding(
    state: dict[str, Any], expected_version_token: str, bound_import_digest: str,
    molecule: dict[str, Any], bound_molecule_digest: str,
) -> None:
    if expected_version_token != _version_token(state):
        raise ChemicalPaperError("STALE_CHEMICAL_PAPER_STATE")
    if bound_import_digest != state["current_import_digest"]:
        raise ChemicalPaperError("CHEMICAL_PAPER_IMPORT_STALE")
    if bound_molecule_digest != molecule["molecule_digest"]:
        raise ChemicalPaperError("MOLECULE_BINDING_STALE")


def append_chemical_field_correction(
    project: Path,
    study_id: str,
    molecule_id: str,
    field: str,
    value: str,
    actor: object,
    *,
    reason: str,
    expected_version_token: str,
    bound_import_digest: str,
    bound_molecule_digest: str,
) -> dict[str, Any]:
    root = _project(project)
    if field not in FIELD_NAMES:
        raise ChemicalPaperError("CHEMICAL_FIELD_INVALID")
    if not isinstance(value, str) or value != value.strip() or not value or len(value) > 20000:
        raise ChemicalPaperError("CHEMICAL_FIELD_VALUE_INVALID")
    who, why = _actor(actor), _reason(reason)
    try:
        with project_write_lock(root):
            state = load_chemical_paper_state(root, study_id)
            molecule = _molecule(state, molecule_id)
            _require_mutation_binding(state, expected_version_token, bound_import_digest, molecule, bound_molecule_digest)
            prior = _current_value(state, molecule, field)
            event = {
                "molecule_id": molecule["molecule_id"], "field": field, "prior_value": prior, "value": value,
                "actor": who, "reason": why, "recorded_at": _now(),
                "bound_import_digest": state["current_import_digest"], "bound_molecule_digest": molecule["molecule_digest"],
                "prior_event_digest": state["field_correction_head_digest"],
            }
            event["event_digest"] = canonical_digest(event)
            state["field_corrections"].append(event)
            state["field_correction_head_digest"] = event["event_digest"]
            state["state_digest"] = _canonical_state_digest(state)
            _validate_state(state)
            _atomic_json(_state_path(root, study_id), state)
    except PaperEvidenceStoreError as exc:
        raise ChemicalPaperError(exc.code) from exc
    return {"status": "corrected", "study_id": study_id, "molecule_id": molecule_id, "field": field, "version_token": _version_token(state)}


def correct_chemical_paper_field(
    project: Path,
    *,
    study_id: str,
    molecule_index: int,
    field: str,
    value: str,
    actor: object,
    reason: str,
    version_token: str,
) -> dict[str, Any]:
    """Apply one safe index-addressed, optimistic-concurrency field correction."""
    state = load_chemical_paper_state(project, study_id)
    molecule = _molecule_by_index(state, molecule_index)
    result = append_chemical_field_correction(
        project,
        study_id,
        molecule["molecule_id"],
        field,
        value,
        actor,
        reason=reason,
        expected_version_token=version_token,
        bound_import_digest=state["current_import_digest"],
        bound_molecule_digest=molecule["molecule_digest"],
    )
    return {
        "status": result["status"],
        "study_id": study_id,
        "molecule_index": molecule_index,
        "field": field,
        "version_token": result["version_token"],
    }


def _element_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ChemicalPaperError("ELEMENT_COUNTS_INVALID")
    result: dict[str, int] = {}
    for key, count in value.items():
        if key not in _ELEMENTS or not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ChemicalPaperError("ELEMENT_COUNTS_INVALID")
        result[key] = count
    return dict(sorted(result.items()))


def append_element_review(
    project: Path,
    study_id: str,
    molecule_id: str,
    state_value: str,
    actor: object,
    *,
    reason: str,
    expected_version_token: str,
    bound_import_digest: str,
    bound_molecule_digest: str,
    corrected_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    root = _project(project)
    if state_value not in ELEMENT_REVIEW_STATES or state_value == "not_reviewed":
        raise ChemicalPaperError("ELEMENT_REVIEW_STATE_INVALID")
    if state_value == "corrected":
        reviewed_counts: dict[str, int] | None = _element_counts(corrected_counts)
    elif corrected_counts is not None:
        raise ChemicalPaperError("ELEMENT_COUNTS_NOT_ALLOWED")
    else:
        reviewed_counts = None
    who, why = _actor(actor), _reason(reason)
    try:
        with project_write_lock(root):
            state = load_chemical_paper_state(root, study_id)
            molecule = _molecule(state, molecule_id)
            _require_mutation_binding(state, expected_version_token, bound_import_digest, molecule, bound_molecule_digest)
            prior_state, prior_counts, _ = _current_element_review(state, molecule)
            event = {
                "molecule_id": molecule["molecule_id"], "prior_state": prior_state, "state": state_value,
                "prior_counts": prior_counts, "reviewed_counts": reviewed_counts,
                "actor": who, "reason": why, "recorded_at": _now(),
                "bound_import_digest": state["current_import_digest"], "bound_molecule_digest": molecule["molecule_digest"],
                "prior_event_digest": state["element_review_head_digest"],
            }
            event["event_digest"] = canonical_digest(event)
            state["element_reviews"].append(event)
            state["element_review_head_digest"] = event["event_digest"]
            state["state_digest"] = _canonical_state_digest(state)
            _validate_state(state)
            _atomic_json(_state_path(root, study_id), state)
    except PaperEvidenceStoreError as exc:
        raise ChemicalPaperError(exc.code) from exc
    return {"status": state_value, "study_id": study_id, "molecule_id": molecule_id, "version_token": _version_token(state)}


def review_chemical_paper_elements(
    project: Path,
    *,
    study_id: str,
    molecule_index: int,
    review_state: str,
    actor: object,
    reason: str,
    version_token: str,
    corrected_elements: object = None,
) -> dict[str, Any]:
    """Record an optional element review without exposing raw molecule IDs."""
    state = load_chemical_paper_state(project, study_id)
    molecule = _molecule_by_index(state, molecule_index)
    normalized_elements: dict[str, int] | None
    if isinstance(corrected_elements, list):
        normalized_elements = {}
        for row in corrected_elements:
            if not isinstance(row, dict) or set(row) != {"symbol", "count"} or row.get("symbol") in normalized_elements:
                raise ChemicalPaperError("ELEMENT_COUNTS_INVALID")
            normalized_elements[row["symbol"]] = row.get("count")
    elif corrected_elements is None or isinstance(corrected_elements, dict):
        normalized_elements = corrected_elements
    else:
        raise ChemicalPaperError("ELEMENT_COUNTS_INVALID")
    result = append_element_review(
        project,
        study_id,
        molecule["molecule_id"],
        review_state,
        actor,
        reason=reason,
        expected_version_token=version_token,
        bound_import_digest=state["current_import_digest"],
        bound_molecule_digest=molecule["molecule_digest"],
        corrected_counts=normalized_elements,
    )
    return {
        "status": result["status"],
        "study_id": study_id,
        "molecule_index": molecule_index,
        "version_token": result["version_token"],
    }


def _study_summary(state: dict[str, Any]) -> dict[str, Any]:
    unresolved = {field: 0 for field in FIELD_NAMES}
    unreviewed = 0
    molecules: list[dict[str, Any]] = []
    version_token = _version_token(state)
    for molecule_index, molecule in enumerate(state["molecules"]):
        values: dict[str, str | None] = {}
        for field in FIELD_NAMES:
            current = _current_value(state, molecule, field)
            values[field] = current
            if current is None:
                unresolved[field] += 1
        review_state, _, _ = _current_element_review(state, molecule)
        if review_state == "not_reviewed":
            unreviewed += 1
        safe_history = []
        for event in [*state["field_corrections"], *state["element_reviews"]]:
            if event["bound_import_digest"] != state["current_import_digest"] or event["molecule_id"] != molecule["molecule_id"]:
                continue
            safe_history.append({
                "kind": "field_correction" if "field" in event else "element_review",
                "field": event.get("field"), "prior_value": event.get("prior_value"), "value": event.get("value"),
                "prior_state": event.get("prior_state"), "state": event.get("state"),
                "actor_type": event["actor"]["actor_type"], "actor_label": event["actor"]["actor_label"],
                "reason": event["reason"], "recorded_at": event["recorded_at"],
                "pdf_locator": event.get("pdf_locator"),
            })
        missing_fields = [field for field in FIELD_NAMES if values[field] is None]
        molecules.append({
            "molecule_index": molecule_index,
            "page": molecule["page_index"] + 1,
            "bbox_normalized": molecule["normalized_bbox"],
            "molblock_available": bool(molecule["element_candidate_counts"]),
            **values,
            "missing_fields": missing_fields,
            "candidate_elements": [
                {"symbol": symbol, "count": count}
                for symbol, count in sorted(molecule["element_candidate_counts"].items())
            ],
            "element_review_state": review_state,
            "pdf_page_url": (
                f"/api/project/{quote(state['project_id'], safe='')}/source/"
                f"{quote(state['source_id'], safe='')}"
                f"/pdf-page?page={molecule['page_index'] + 1}"
            ),
            "version_token": version_token,
            "history": safe_history,
        })
    active = state["imports"][state["current_import_digest"]]
    gaps = [f"{count} molecule(s) have unresolved {field}." for field, count in unresolved.items() if count]
    status = "needs_review" if gaps else "ready"
    return {
        "study_id": state["study_id"], "status": status, "backend": active["backend"],
        "version": active["version"], "pdf_binding_status": "bound",
        "imported_at": active["imported_at"], "page_count": active["page_count"],
        "file_kinds": ["layout", "markdown", "molecule_info"], "molecule_count": len(molecules),
        "reaction_data_status": "unavailable_not_provided", "missing_field_counts": unresolved,
        "unreviewed_element_molecule_count": unreviewed, "gaps": gaps,
        "limitations": [
            "Reaction data was not provided in this export.",
            "No exported image assets were provided; molecule boxes are original-PDF locators only.",
        ],
        "version_token": version_token, "molecules": molecules,
    }


def chemical_paper_safe_project_state(project: Path) -> dict[str, Any]:
    root = _project(project)
    try:
        studies = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ChemicalPaperError(exc.code) from exc
    summaries: list[dict[str, Any]] = []
    for study_id in studies:
        path = _state_path(root, study_id)
        if path.exists():
            summaries.append(_study_summary(load_chemical_paper_state(root, study_id)))
        else:
            summaries.append({
                "study_id": study_id, "status": "missing", "backend": None,
                "version": None, "pdf_binding_status": "missing", "imported_at": None,
                "page_count": None, "file_kinds": [], "molecule_count": None,
                "reaction_data_status": "unavailable_not_provided",
                "missing_field_counts": None, "unreviewed_element_molecule_count": 0,
                "gaps": ["A valid MinerU Chemical Paper manual export has not been imported."],
                "limitations": ["Reaction data was not provided in this export."], "version_token": None, "molecules": [],
            })
    imported = [row for row in summaries if row["status"] != "missing"]
    project_status = (
        "missing" if summaries and not imported
        else "ready" if len(imported) == len(summaries) and all(row["status"] == "ready" for row in imported)
        else "needs_review"
    )
    molecule_count = sum(int(row["molecule_count"] or 0) for row in imported)
    unresolved_count = sum(
        sum((row["missing_field_counts"] or {}).values()) for row in imported
    )
    return {
        "schema_version": "chemical-paper-projection.v1",
        "route": "chemical-paper-zip-only",
        "project_status": project_status,
        "summary": {
            "studies": len(summaries),
            "imported": len(imported),
            "molecules": molecule_count,
            "unresolved_fields": unresolved_count,
            "reaction_data_status": "unavailable_not_provided",
        },
        "studies": summaries,
    }


def chemical_paper_projection(project: Path) -> dict[str, Any]:
    return chemical_paper_safe_project_state(project)


def chemical_paper_manuscript_bindings(project: Path) -> dict[str, Any]:
    """Return the exact frozen v1 manuscript provenance fields."""
    root = _project(project)
    try:
        study_ids = declared_study_ids(root)
    except SourceTruthError as exc:
        raise ChemicalPaperError(exc.code) from exc
    import_rows: list[dict[str, str]] = []
    molecule_count = 0
    unresolved_field_count = 0
    review_counts = {state: 0 for state in ("not_reviewed", "confirmed", "corrected", "not_applicable")}
    for study_id in study_ids:
        if not _state_path(root, study_id).is_file():
            continue
        state = load_chemical_paper_state(root, study_id)
        import_rows.append(
            {
                "study_id": study_id,
                "import_digest": state["current_import_digest"],
                "state_digest": state["state_digest"],
            }
        )
        molecule_count += len(state["molecules"])
        for molecule in state["molecules"]:
            unresolved_field_count += sum(
                _current_value(state, molecule, field) is None for field in FIELD_NAMES
            )
            review_state, _, _ = _current_element_review(state, molecule)
            review_counts[review_state] += 1
    import_rows.sort(key=lambda row: row["study_id"])
    return {
        "chemical_paper_import_digests": import_rows,
        "chemical_paper_safe_summary": {
            "schema_version": "chemical-paper-safe-summary.v1",
            "route": "chemical-paper-zip-only",
            "study_count": len(import_rows),
            "molecule_count": molecule_count,
            "unresolved_field_count": unresolved_field_count,
            "element_review_counts": review_counts,
            "reaction_data_status": "unavailable_not_provided",
        },
    }


def _validated_import_digest_rows(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ChemicalPaperError("CHEMICAL_PAPER_LINEAGE_INVALID")
    rows: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"study_id", "import_digest", "state_digest"}:
            raise ChemicalPaperError("CHEMICAL_PAPER_LINEAGE_INVALID")
        rows.append(
            {
                "study_id": _identifier(row.get("study_id"), "CHEMICAL_PAPER_LINEAGE_INVALID"),
                "import_digest": _digest(row.get("import_digest"), "CHEMICAL_PAPER_LINEAGE_INVALID"),
                "state_digest": _digest(row.get("state_digest"), "CHEMICAL_PAPER_LINEAGE_INVALID"),
            }
        )
    if rows != sorted(rows, key=lambda row: row["study_id"]) or len({row["study_id"] for row in rows}) != len(rows):
        raise ChemicalPaperError("CHEMICAL_PAPER_LINEAGE_INVALID")
    return rows


def _validated_claim_dependency_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ChemicalPaperError("CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID")
    rows: list[dict[str, Any]] = []
    required_keys = {
        "claim_id", "study_id", "molecule_index", "required_fields",
        "requires_element_review", "requires_reaction_data",
    }
    for row in value:
        if not isinstance(row, dict) or set(row) != required_keys:
            raise ChemicalPaperError("CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID")
        fields = row.get("required_fields")
        if (
            not isinstance(fields, list)
            or fields != sorted(fields)
            or len(fields) != len(set(fields))
            or not set(fields) <= set(FIELD_NAMES)
        ):
            raise ChemicalPaperError("CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID")
        molecule_index = row.get("molecule_index")
        if not isinstance(molecule_index, int) or isinstance(molecule_index, bool) or molecule_index < 0:
            raise ChemicalPaperError("CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID")
        if not isinstance(row.get("requires_element_review"), bool) or not isinstance(row.get("requires_reaction_data"), bool):
            raise ChemicalPaperError("CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID")
        rows.append(
            {
                "claim_id": _identifier(row.get("claim_id"), "CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID"),
                "study_id": _identifier(row.get("study_id"), "CHEMICAL_PAPER_CLAIM_DEPENDENCY_INVALID"),
                "molecule_index": molecule_index,
                "required_fields": list(fields),
                "requires_element_review": row["requires_element_review"],
                "requires_reaction_data": row["requires_reaction_data"],
            }
        )
    return rows


def chemical_paper_dependency_currentness(
    project: Path,
    *,
    import_digests: object,
    claim_dependencies: object,
) -> dict[str, Any]:
    """Resolve release currentness without making Release parse private state."""
    root = _project(project)
    import_rows = _validated_import_digest_rows(import_digests)
    dependency_rows = _validated_claim_dependency_rows(claim_dependencies)
    binding_by_study = {row["study_id"]: row for row in import_rows}
    states: dict[str, dict[str, Any]] = {}
    study_status: dict[str, str] = {}
    for study_id, binding in binding_by_study.items():
        try:
            state = load_chemical_paper_state(root, study_id)
        except ChemicalPaperError as exc:
            study_status[study_id] = "missing" if exc.code == "CHEMICAL_PAPER_NOT_IMPORTED" else "stale"
            continue
        states[study_id] = state
        study_status[study_id] = (
            "current"
            if binding["import_digest"] == state["current_import_digest"]
            and binding["state_digest"] == state["state_digest"]
            else "stale"
        )
    if not import_rows and dependency_rows:
        lineage_status = "missing"
    elif any(value == "stale" for value in study_status.values()):
        lineage_status = "stale"
    elif any(value == "missing" for value in study_status.values()):
        lineage_status = "missing"
    else:
        lineage_status = "current"

    by_claim: dict[str, list[dict[str, Any]]] = {}
    for dependency in dependency_rows:
        claim_id = dependency["claim_id"]
        study_id = dependency["study_id"]
        blocking: list[str] = []
        required_statuses: dict[str, str] = {}
        state = states.get(study_id)
        status = study_status.get(study_id, "missing")
        element_state = "not_reviewed"
        reaction_status = "unavailable_not_provided"
        if status == "current" and state is not None:
            try:
                molecule = _molecule_by_index(state, dependency["molecule_index"])
            except ChemicalPaperError:
                status = "missing"
            else:
                for field in dependency["required_fields"]:
                    value = _current_value(state, molecule, field)
                    corrected = any(
                        event["bound_import_digest"] == state["current_import_digest"]
                        and event["molecule_id"] == molecule["molecule_id"]
                        and event["field"] == field
                        for event in state["field_corrections"]
                    )
                    field_status = "corrected" if corrected else ("resolved" if value is not None else "unresolved")
                    required_statuses[field] = field_status
                    if field_status == "unresolved":
                        blocking.append(f"{claim_id}:{field}:unresolved")
                element_state, _, _ = _current_element_review(state, molecule)
                if dependency["requires_element_review"] and element_state == "not_reviewed":
                    blocking.append(f"{claim_id}:elements:not_reviewed")
                if dependency["requires_reaction_data"]:
                    blocking.append(f"{claim_id}:reaction_data:unavailable_not_provided")
                status = "unavailable" if dependency["requires_reaction_data"] else ("needs_review" if blocking else "current")
        if status in {"stale", "missing"}:
            blocking.append(f"{claim_id}:chemical_paper:{status}")
        row = {
            "study_id": study_id,
            "molecule_index": dependency["molecule_index"],
            "status": status,
            "required_field_statuses": required_statuses,
            "element_review_state": element_state,
            "reaction_data_status": reaction_status,
            "blocking_reasons": sorted(set(blocking)),
        }
        by_claim.setdefault(claim_id, []).append(row)

    claims: list[dict[str, Any]] = []
    top_blocking: list[str] = []
    priority = {"stale": 4, "missing": 3, "unavailable": 2, "needs_review": 1, "current": 0}
    for claim_id in sorted(by_claim):
        dependencies = sorted(by_claim[claim_id], key=lambda row: (row["study_id"], row["molecule_index"]))
        status = max((row["status"] for row in dependencies), key=lambda value: priority[value])
        blocking = sorted({reason for row in dependencies for reason in row["blocking_reasons"]})
        claims.append({"claim_id": claim_id, "status": status, "dependencies": dependencies, "blocking_reasons": blocking})
        top_blocking.extend(blocking)
    if lineage_status != "current":
        top_blocking.append(f"chemical_paper_import_digests:{lineage_status}")
    top_blocking = sorted(set(top_blocking))
    return {
        "schema_version": "chemical-paper-dependency-currentness.v1",
        "lineage_binding_status": lineage_status,
        "claims": claims,
        "can_release": lineage_status == "current" and all(row["status"] == "current" for row in claims),
        "blocking_reasons": top_blocking,
    }


def _resolution_digest(state: dict[str, Any]) -> str:
    rows = []
    for molecule in state["molecules"]:
        rows.append({"molecule_id": molecule["molecule_id"], **{field: _current_value(state, molecule, field) for field in FIELD_NAMES}})
    return canonical_digest(rows)


def _element_review_digest(state: dict[str, Any]) -> str:
    rows = []
    for molecule in state["molecules"]:
        review_state, counts, event_digest = _current_element_review(state, molecule)
        rows.append({"molecule_id": molecule["molecule_id"], "state": review_state, "counts": counts, "event_digest": event_digest})
    return canonical_digest(rows)


def chemical_dependency_state(project: Path, evidence_id: str, dependencies: object) -> dict[str, Any]:
    evidence_id = _identifier(evidence_id, "EVIDENCE_ID_INVALID")
    if not isinstance(dependencies, list):
        raise ChemicalPaperError("CHEMICAL_DEPENDENCY_INVALID")
    rows: list[dict[str, Any]] = []
    gaps: list[str] = []
    statuses: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict) or set(dependency) != {"study_id", "molecule_id", "molecule_digest", "chemical_paper_import_digest", "required_fields"}:
            raise ChemicalPaperError("CHEMICAL_DEPENDENCY_INVALID")
        state = load_chemical_paper_state(project, dependency["study_id"])
        molecule = _molecule(state, dependency["molecule_id"])
        if dependency["chemical_paper_import_digest"] != state["current_import_digest"]:
            raise ChemicalPaperError("CHEMICAL_PAPER_IMPORT_STALE")
        if dependency["molecule_digest"] != molecule["molecule_digest"]:
            raise ChemicalPaperError("MOLECULE_BINDING_STALE")
        required = dependency["required_fields"]
        if not isinstance(required, list) or len(required) != len(set(required)) or not set(required) <= REQUIRED_FIELD_NAMES:
            raise ChemicalPaperError("CHEMICAL_DEPENDENCY_INVALID")
        status = "ready"
        for field in required:
            if field in FIELD_NAMES and _current_value(state, molecule, field) is None:
                gaps.append(f"{state['study_id']}/{molecule['molecule_id']}:{field}:unresolved")
                status = "blocked_unresolved"
        review_state, _, review_digest = _current_element_review(state, molecule)
        if "elements" in required and review_state == "not_reviewed":
            gaps.append(f"{state['study_id']}/{molecule['molecule_id']}:elements:not_reviewed")
            if status == "ready":
                status = "blocked_unreviewed"
        row = {
            "evidence_id": evidence_id, "study_id": state["study_id"], "molecule_id": molecule["molecule_id"],
            "molecule_digest": molecule["molecule_digest"], "chemical_paper_import_digest": state["current_import_digest"],
            "required_fields": sorted(required), "field_resolution_digest": _resolution_digest(state),
            "element_review_digest": review_digest, "dependency_status": status,
        }
        row["dependency_digest"] = canonical_digest({key: value for key, value in row.items() if key != "dependency_status"})
        rows.append(row)
        statuses.append(status)
    overall = "blocked_unresolved" if "blocked_unresolved" in statuses else ("blocked_unreviewed" if "blocked_unreviewed" in statuses else "ready")
    return {"evidence_id": evidence_id, "dependency_status": overall, "dependencies": rows, "gaps": sorted(gaps)}
