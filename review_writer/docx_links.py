from __future__ import annotations

import os
import re
import tempfile
import zipfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
XML = "http://www.w3.org/XML/1998/namespace"
HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
CITATION_RE = re.compile(r"\[(\d+)\]")
REFERENCE_RE = re.compile(r"^\s*\[(\d+)\]\s+")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")

ET.register_namespace("w", W)
ET.register_namespace("r", R)
ET.register_namespace("", REL)


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(_tag(W, "t")))


def _new_text_run(text: str, run_properties: ET.Element | None = None) -> ET.Element:
    run = ET.Element(_tag(W, "r"))
    if run_properties is not None:
        run.append(deepcopy(run_properties))
    node = ET.SubElement(run, _tag(W, "t"))
    if text.startswith(" ") or text.endswith(" "):
        node.set(_tag(XML, "space"), "preserve")
    node.text = text
    return run


def _hyperlink_run(text: str, *, anchor: str | None = None, relationship_id: str | None = None) -> ET.Element:
    hyperlink = ET.Element(_tag(W, "hyperlink"))
    if anchor:
        hyperlink.set(_tag(W, "anchor"), anchor)
        hyperlink.set(_tag(W, "history"), "1")
    if relationship_id:
        hyperlink.set(_tag(R, "id"), relationship_id)
    run = ET.SubElement(hyperlink, _tag(W, "r"))
    run_properties = ET.SubElement(run, _tag(W, "rPr"))
    style = ET.SubElement(run_properties, _tag(W, "rStyle"))
    style.set(_tag(W, "val"), "Hyperlink")
    node = ET.SubElement(run, _tag(W, "t"))
    node.text = text
    return hyperlink


def _replace_run_matches(
    paragraph: ET.Element,
    pattern: re.Pattern[str],
    replacement,
) -> int:
    count = 0
    for run in list(paragraph.findall(_tag(W, "r"))):
        text_nodes = list(run.iter(_tag(W, "t")))
        if not text_nodes:
            continue
        text = "".join(node.text or "" for node in text_nodes)
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        run_properties = run.find(_tag(W, "rPr"))
        parent_index = list(paragraph).index(run)
        paragraph.remove(run)
        position = 0
        insertions: list[ET.Element] = []
        for match in matches:
            if match.start() > position:
                insertions.append(_new_text_run(text[position : match.start()], run_properties))
            insertions.append(replacement(match))
            position = match.end()
            count += 1
        if position < len(text):
            insertions.append(_new_text_run(text[position:], run_properties))
        for offset, element in enumerate(insertions):
            paragraph.insert(parent_index + offset, element)
    return count


def _replace_paragraph_matches(
    paragraph: ET.Element,
    pattern: re.Pattern[str],
    replacement,
) -> int:
    """Replace matches over the paragraph's logical text, including split runs."""
    text = _paragraph_text(paragraph)
    matches = list(pattern.finditer(text))
    if not matches:
        return 0
    first_run = paragraph.find(_tag(W, "r"))
    run_properties = first_run.find(_tag(W, "rPr")) if first_run is not None else None
    for child in list(paragraph):
        if child.tag in {_tag(W, "r"), _tag(W, "hyperlink")}:
            paragraph.remove(child)
    insert_at = next(
        (index for index, child in enumerate(paragraph) if child.tag == _tag(W, "bookmarkEnd")),
        len(paragraph),
    )
    position = 0
    insertions: list[ET.Element] = []
    for match in matches:
        if match.start() > position:
            insertions.append(_new_text_run(text[position : match.start()], run_properties))
        insertions.append(replacement(match))
        position = match.end()
    if position < len(text):
        insertions.append(_new_text_run(text[position:], run_properties))
    for offset, element in enumerate(insertions):
        paragraph.insert(insert_at + offset, element)
    return len(matches)


def _next_relationship_id(relationships: ET.Element) -> int:
    values = []
    for relationship in relationships:
        match = re.fullmatch(r"rId(\d+)", relationship.attrib.get("Id", ""))
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0) + 1


def inspect_docx_citation_links(docx_path: Path) -> dict[str, object]:
    """Read a DOCX without mutating it and verify citation/DOI link integrity."""
    docx_path = Path(docx_path).resolve()
    with zipfile.ZipFile(docx_path, "r") as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))

    paragraphs = list(document.iter(_tag(W, "p")))
    references_heading_index = next(
        (index for index, paragraph in enumerate(paragraphs) if _paragraph_text(paragraph).strip().casefold() == "references"),
        None,
    )
    if references_heading_index is None:
        raise ValueError("DOCX lacks References heading")

    reference_ids = {
        int(match.group(1))
        for paragraph in paragraphs[references_heading_index + 1 :]
        if (match := REFERENCE_RE.match(_paragraph_text(paragraph)))
    }
    cited_ids = {
        int(match.group(1))
        for paragraph in paragraphs[:references_heading_index]
        for match in CITATION_RE.finditer(_paragraph_text(paragraph))
    }
    bookmark_names = [
        node.attrib.get(_tag(W, "name"), "")
        for node in document.iter(_tag(W, "bookmarkStart"))
        if node.attrib.get(_tag(W, "name"), "").startswith("ref_")
    ]
    expected_bookmarks = {f"ref_{value}" for value in reference_ids}
    if set(bookmark_names) != expected_bookmarks or len(bookmark_names) != len(expected_bookmarks):
        raise ValueError("DOCX reference bookmarks are incomplete or duplicated")

    anchor_counts = {
        citation_id: len(document.findall(f".//{{{W}}}hyperlink[@{{{W}}}anchor='ref_{citation_id}']"))
        for citation_id in cited_ids
    }
    citation_counts = Counter(
        int(match.group(1))
        for paragraph in paragraphs[:references_heading_index]
        for match in CITATION_RE.finditer(_paragraph_text(paragraph))
    )
    if any(anchor_counts.get(citation_id) != count for citation_id, count in citation_counts.items()):
        raise ValueError("DOCX internal citation hyperlinks are incomplete")

    external_targets = {
        item.attrib.get("Target")
        for item in relationships
        if item.attrib.get("Type") == HYPERLINK_REL and item.attrib.get("TargetMode") == "External"
    }
    doi_targets = {
        f"https://doi.org/{match.group(0).rstrip('.,;)')}"
        for paragraph in paragraphs[references_heading_index + 1 :]
        for match in DOI_RE.finditer(_paragraph_text(paragraph))
    }
    if not doi_targets.issubset(external_targets):
        raise ValueError("DOCX DOI hyperlinks are incomplete")
    return {
        "status": "PASS",
        "bookmark_count": len(bookmark_names),
        "internal_hyperlink_count": sum(anchor_counts.values()),
        "doi_hyperlink_count": len(doi_targets),
        "cited_reference_ids": sorted(cited_ids),
        "reference_ids": sorted(reference_ids),
    }


def link_citations_and_dois(docx_path: Path) -> dict[str, object]:
    docx_path = Path(docx_path).resolve()
    if not docx_path.is_file():
        raise ValueError(f"DOCX not found: {docx_path}")
    with zipfile.ZipFile(docx_path, "r") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    document_name = "word/document.xml"
    relationships_name = "word/_rels/document.xml.rels"
    if document_name not in members or relationships_name not in members:
        raise ValueError("DOCX lacks document XML or relationships")

    document = ET.fromstring(members[document_name])
    relationships = ET.fromstring(members[relationships_name])
    paragraphs = list(document.iter(_tag(W, "p")))
    references_heading_index = next(
        (index for index, paragraph in enumerate(paragraphs) if _paragraph_text(paragraph).strip().casefold() == "references"),
        None,
    )
    if references_heading_index is None:
        raise ValueError("DOCX lacks References heading")

    reference_paragraphs: dict[int, ET.Element] = {}
    for paragraph in paragraphs[references_heading_index + 1 :]:
        match = REFERENCE_RE.match(_paragraph_text(paragraph))
        if match:
            reference_paragraphs[int(match.group(1))] = paragraph
    cited_ids = {
        int(match.group(1))
        for paragraph in paragraphs[:references_heading_index]
        for match in CITATION_RE.finditer(_paragraph_text(paragraph))
    }
    missing = sorted(cited_ids - set(reference_paragraphs))
    if missing:
        raise ValueError(f"missing reference entries for citations: {', '.join(map(str, missing))}")

    bookmark_count = 0
    for bookmark_id, citation_id in enumerate(sorted(reference_paragraphs), start=1000):
        paragraph = reference_paragraphs[citation_id]
        start = ET.Element(_tag(W, "bookmarkStart"))
        start.set(_tag(W, "id"), str(bookmark_id))
        start.set(_tag(W, "name"), f"ref_{citation_id}")
        end = ET.Element(_tag(W, "bookmarkEnd"))
        end.set(_tag(W, "id"), str(bookmark_id))
        paragraph.insert(0, start)
        paragraph.append(end)
        bookmark_count += 1

    internal_count = 0
    for paragraph in paragraphs[:references_heading_index]:
        internal_count += _replace_run_matches(
            paragraph,
            CITATION_RE,
            lambda match: _hyperlink_run(match.group(0), anchor=f"ref_{int(match.group(1))}"),
        )

    relationship_index = _next_relationship_id(relationships)
    target_to_id: dict[str, str] = {}

    def external_link(match: re.Match[str]) -> ET.Element:
        nonlocal relationship_index
        doi = match.group(0).rstrip(".,;)")
        target = f"https://doi.org/{doi}"
        relationship_id = target_to_id.get(target)
        if relationship_id is None:
            relationship_id = f"rId{relationship_index}"
            relationship_index += 1
            relationship = ET.SubElement(relationships, _tag(REL, "Relationship"))
            relationship.set("Id", relationship_id)
            relationship.set("Type", HYPERLINK_REL)
            relationship.set("Target", target)
            relationship.set("TargetMode", "External")
            target_to_id[target] = relationship_id
        return _hyperlink_run(match.group(0), relationship_id=relationship_id)

    doi_count = 0
    for paragraph in reference_paragraphs.values():
        doi_count += _replace_paragraph_matches(paragraph, DOI_RE, external_link)

    members[document_name] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    members[relationships_name] = ET.tostring(relationships, encoding="utf-8", xml_declaration=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{docx_path.name}.", suffix=".tmp", dir=docx_path.parent)
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        temporary.replace(docx_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "status": "PASS",
        "bookmark_count": bookmark_count,
        "internal_hyperlink_count": internal_count,
        "doi_hyperlink_count": doi_count,
        "cited_reference_ids": sorted(cited_ids),
        "reference_ids": sorted(reference_paragraphs),
    }
