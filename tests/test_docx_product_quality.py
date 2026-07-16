#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTER = REPO_ROOT / "skills/review-export-docx/scripts/md2docx.py"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class DocxProductQualityTests(unittest.TestCase):
    def test_export_has_word_headings_toc_clean_properties_and_chemistry_scripts(self) -> None:
        markdown = """# Palladium-Centered Strategies for Asymmetric Allene Synthesis: Selectivity Control, Substrate Constraints, and Mechanistic Evidence

## Abstract

Pd2(dba)3, CH2Cl2, ligand L19, product 3aa, 20 °C, π-allylpalladium, and α-selectivity are discussed [1].

## 1. Scope and Source Selection

Body text [1].

## 2. Catalyst and Ligand Control of Selectivity

Table 1. Transferable design principles.

| Design Lever | Direct Observation | Substrate Boundary | Mechanistic Evidence | Practical Implication |
| --- | --- | --- | --- | --- |
| Ligand | Supported | Defined | Observed | Preserve context |

## References

[1] A. Author. Study. DOI: 10.1000/example
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "review.md"
            target = root / "review.docx"
            source.write_text(markdown, encoding="utf-8")
            subprocess.run([sys.executable, str(EXPORTER), "--input", str(source), "--output", str(target)], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
            document = Document(target)
            self.assertEqual(document.core_properties.title, markdown.splitlines()[0][2:])
            self.assertEqual(document.core_properties.author, "review-writer")
            self.assertEqual(document.core_properties.last_modified_by, "review-writer")
            styles = {paragraph.text: paragraph.style.name for paragraph in document.paragraphs}
            self.assertEqual(styles["1. Scope and Source Selection"], "Heading 1")
            self.assertEqual(styles["2. Catalyst and Ligand Control of Selectivity"], "Heading 1")
            with zipfile.ZipFile(target) as archive:
                xml = ET.fromstring(archive.read("word/document.xml"))
            instr = " ".join(node.text or "" for node in xml.iter(f"{{{W}}}instrText"))
            self.assertIn("TOC", instr)
            header_row = xml.find(f".//{{{W}}}tbl/{{{W}}}tr")
            self.assertIsNotNone(header_row.find(f"{{{W}}}trPr/{{{W}}}tblHeader"))
            self.assertEqual(len(header_row.findall(f"{{{W}}}tc")), 5)
            runs = [("".join(t.text or "" for t in run.findall(f"{{{W}}}t")), run.find(f"{{{W}}}rPr/{{{W}}}vertAlign").attrib.get(f"{{{W}}}val") if run.find(f"{{{W}}}rPr/{{{W}}}vertAlign") is not None else None) for run in xml.iter(f"{{{W}}}r")]
            subscript_text = {text for text, align in runs if align == "subscript"}
            self.assertTrue({"2", "3"}.issubset(subscript_text))
            self.assertTrue(any("L19" in text for text, align in runs if align is None))
            self.assertTrue(any("3aa" in text for text, align in runs if align is None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
