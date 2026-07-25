#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.docx_links import inspect_docx_citation_links, link_citations_and_dois


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _minimal_docx(path: Path, body_paragraphs: list[str]) -> None:
    paragraphs = "".join(f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in body_paragraphs)
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{paragraphs}<w:sectPr/></w:body></w:document>'''
    relationships = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL}"></Relationships>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", relationships)


class DocxCitationLinkTests(unittest.TestCase):
    def test_references_bookmarks_internal_links_and_doi_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review.docx"
            _minimal_docx(path, ["A supported statement [1].", "A repeated statement [1].", "References", "[1] A. Author. Study. DOI: 10.1000/example"])
            report = link_citations_and_dois(path)
            self.assertEqual(report["internal_hyperlink_count"], 2)
            self.assertEqual(report["bookmark_count"], 1)
            self.assertEqual(report["doi_hyperlink_count"], 1)
            with zipfile.ZipFile(path) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
                rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            bookmarks = document.findall(f".//{{{W}}}bookmarkStart")
            self.assertEqual([item.attrib[f"{{{W}}}name"] for item in bookmarks], ["ref_1"])
            anchors = document.findall(f".//{{{W}}}hyperlink[@{{{W}}}anchor='ref_1']")
            self.assertEqual(len(anchors), 2)
            external = [item for item in rels if item.attrib.get("Target") == "https://doi.org/10.1000/example"]
            self.assertEqual(len(external), 1)
            self.assertEqual(external[0].attrib.get("TargetMode"), "External")
            inspection = inspect_docx_citation_links(path)
            self.assertEqual(inspection["status"], "PASS")
            self.assertEqual(inspection["bookmark_count"], 1)
            self.assertEqual(inspection["internal_hyperlink_count"], 2)
            self.assertEqual(inspection["doi_hyperlink_count"], 1)

    def test_missing_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review.docx"
            _minimal_docx(path, ["A supported statement [2].", "References", "[1] A. Author. DOI: 10.1000/example"])
            with self.assertRaisesRegex(ValueError, "missing reference entries for citations: 2"):
                link_citations_and_dois(path)

    def test_chemical_cycloaddition_notation_is_not_a_citation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review.docx"
            _minimal_docx(path, ["The [2+2] and [3+2] cycloadditions are distinct [1].", "References", "[1] A. Author. DOI: 10.1000/example"])
            link_citations_and_dois(path)
            with zipfile.ZipFile(path) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
            text = "".join(item.text or "" for item in document.findall(f".//{{{W}}}t"))
            self.assertIn("[2+2]", text)
            self.assertIn("[3+2]", text)
            self.assertEqual(len(document.findall(f".//{{{W}}}hyperlink[@{{{W}}}anchor='ref_1']")), 1)

    def test_doi_split_across_styled_runs_keeps_full_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review.docx"
            _minimal_docx(path, ["A supported statement [1].", "References", "[1] placeholder"])
            with zipfile.ZipFile(path, "r") as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            document = ET.fromstring(members["word/document.xml"])
            reference = list(document.iter(f"{{{W}}}p"))[-1]
            for child in list(reference):
                reference.remove(child)
            for text_value in ("[1] A. Author. DOI: 10.1021/ja", "005921", "o"):
                run = ET.SubElement(reference, f"{{{W}}}r")
                ET.SubElement(run, f"{{{W}}}t").text = text_value
            members["word/document.xml"] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
            with zipfile.ZipFile(path, "w") as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)
            link_citations_and_dois(path)
            inspection = inspect_docx_citation_links(path)
            self.assertEqual(inspection["doi_hyperlink_count"], 1)
            with zipfile.ZipFile(path) as archive:
                rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            self.assertTrue(any(item.attrib.get("Target") == "https://doi.org/10.1021/ja005921o" for item in rels))


if __name__ == "__main__":
    unittest.main(verbosity=2)
