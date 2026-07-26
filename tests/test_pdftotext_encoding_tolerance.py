#!/usr/bin/env python3
"""Regression tests for lossless pdftotext UTF-8 normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.evidence.build_pdf_text_layers import (
    decode_pdftotext_utf8,
    run_pdftotext,
)


CESU8_MATHEMATICAL_DIGIT_ONE = bytes.fromhex("eda0b5edbf8f")


def test_decodes_cesu8_surrogate_pair_without_replacement_characters() -> None:
    raw = b"yield 0.551\r\n" + CESU8_MATHEMATICAL_DIGIT_ONE + b"\f"

    text = decode_pdftotext_utf8(raw)

    assert text == "yield 0.551\r\n\U0001d7cf\f"
    assert "\ufffd" not in text
    assert text.encode("utf-8").decode("utf-8") == text


def test_rejects_arbitrary_invalid_utf8_instead_of_silently_replacing() -> None:
    with pytest.raises(UnicodeDecodeError):
        decode_pdftotext_utf8(b"unsupported byte: \xff")


def test_run_pdftotext_rewrites_cesu8_output_as_standard_utf8(tmp_path: Path) -> None:
    executable = tmp_path / "fake-pdftotext"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[-1]).write_bytes(b'page\\n' + bytes.fromhex('eda0b5edbf8f') + b'\\f')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    destination = tmp_path / "output.txt"

    run_pdftotext(executable, source, destination, layout=False)

    assert destination.read_text(encoding="utf-8") == "page\n\U0001d7cf\f"
    assert destination.read_bytes() == "page\n\U0001d7cf\f".encode("utf-8")
