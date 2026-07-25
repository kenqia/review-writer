"""Canonical, conservative helpers shared by the evidence-atom slice."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


SOFT_HYPHEN = "\u00ad"
CURLY_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2212": "-",
    }
)
MIDDLE_DOT_VARIANTS = {"*", "\u2022", "\u2219", "\u22c5"}
RENDERER_CONTRACT = {
    "name": "PDFTOPPM_PNG_SINGLE_PAGE_V1",
    "dpi": 144,
    "format": "png",
    "single_page": True,
}
HIGH_RISK_CATEGORIES = frozenset(
    {
        "STRUCTURE",
        "STEREOCHEMISTRY",
        "MECHANISM_CAUSALITY",
        "NEGATIVE_GENERALIZATION",
        "MATERIAL_COMPARISON",
        "FIGURE_TABLE_CHEMISTRY",
    }
)


class EvidenceAtomCoreError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _chemical_neighbor(character: str) -> bool:
    return character.isalnum() or character in "()[]{}+-"


def canonicalize_text(value: str) -> str:
    """Apply only the explicitly allowed page-local canonicalizations."""

    normalized = unicodedata.normalize("NFKC", value).replace(SOFT_HYPHEN, "")
    normalized = normalized.translate(CURLY_TRANSLATION)
    characters = list(normalized)
    for index, character in enumerate(characters):
        if character not in MIDDLE_DOT_VARIANTS or index == 0 or index + 1 == len(characters):
            continue
        if _chemical_neighbor(characters[index - 1]) and _chemical_neighbor(characters[index + 1]):
            characters[index] = "\u00b7"
    return " ".join("".join(characters).split())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(serialized)


def packet_path(packet_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"path is not packet-relative: {relative_path}")
    resolved = (packet_root / relative).resolve()
    resolved.relative_to(packet_root.resolve())
    return resolved


def split_pages(path: Path) -> list[str]:
    pages = path.read_text(encoding="utf-8").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def verify_job_source_layers(
    job: dict[str, Any],
    packet_root: Path,
) -> dict[str, tuple[dict[str, Any], list[str]]]:
    """Verify every reading/layout layer bound by a sealed job."""

    sources: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for source in job.get("source_files", []):
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in sources:
            raise EvidenceAtomCoreError(
                "JOB_SOURCE_INVALID",
                "job source_id is absent or duplicated",
            )
        try:
            reading_path = packet_path(packet_root, source["reading_order_path"])
            layout_path = packet_path(packet_root, source["layout_path"])
        except (KeyError, OSError, ValueError) as exc:
            raise EvidenceAtomCoreError("JOB_SOURCE_INVALID", str(exc)) from exc
        if not reading_path.is_file() or not layout_path.is_file():
            raise EvidenceAtomCoreError(
                "JOB_SOURCE_INVALID",
                f"bound layers are missing for {source_id}",
            )
        if sha256_file(reading_path) != source.get("reading_order_sha256"):
            raise EvidenceAtomCoreError(
                "SOURCE_LAYER_HASH_MISMATCH",
                f"reading layer drift: {source_id}",
            )
        if sha256_file(layout_path) != source.get("layout_sha256"):
            raise EvidenceAtomCoreError(
                "SOURCE_LAYER_HASH_MISMATCH",
                f"layout layer drift: {source_id}",
            )
        pages = split_pages(reading_path)
        if len(pages) != source.get("page_count"):
            raise EvidenceAtomCoreError(
                "SOURCE_PAGE_COUNT_MISMATCH",
                f"page count drift: {source_id}",
            )
        sources[source_id] = (source, pages)
    if not sources:
        raise EvidenceAtomCoreError("JOB_SOURCE_INVALID", "job contains no source_files")
    return sources


def render_pdf_page(
    source_pdf: Path,
    page: int,
    renderer: Path,
    output_asset: Path,
) -> None:
    """Render exactly one PDF page under the fixed pdftoppm PNG contract."""

    if not source_pdf.is_file():
        raise EvidenceAtomCoreError("SOURCE_PDF_INVALID", f"source PDF is missing: {source_pdf}")
    if not renderer.is_file():
        raise EvidenceAtomCoreError("RENDERER_INVALID", f"renderer is missing: {renderer}")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise EvidenceAtomCoreError("PAGE_OUT_OF_RANGE", "page must be a positive 1-based integer")
    if output_asset.suffix.casefold() != ".png":
        raise EvidenceAtomCoreError("RENDER_OUTPUT_INVALID", "fixed renderer output must end in .png")
    with tempfile.TemporaryDirectory() as temp_dir:
        prefix = Path(temp_dir) / "page"
        result = subprocess.run(
            [
                str(renderer),
                "-f",
                str(page),
                "-l",
                str(page),
                "-r",
                str(RENDERER_CONTRACT["dpi"]),
                "-png",
                "-singlefile",
                str(source_pdf),
                str(prefix),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        rendered = prefix.with_suffix(".png")
        if result.returncode != 0 or not rendered.is_file():
            raise EvidenceAtomCoreError(
                "RENDER_FAILED",
                f"single-page renderer failed with exit {result.returncode}",
            )
        output_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rendered, output_asset)
