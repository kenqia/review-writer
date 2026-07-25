#!/usr/bin/env python3
"""Test-only fake for the fixed pdftoppm single-page CLI contract."""

from __future__ import annotations

import sys
import binascii
import struct
import zlib
from pathlib import Path


def option(name: str) -> str:
    index = sys.argv.index(name)
    return sys.argv[index + 1]


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))


def one_pixel_png(red: int, green: int, blue: int) -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    scanline = b"\x00" + bytes((red, green, blue))
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(scanline, level=9))
        + png_chunk(b"IEND", b"")
    )


page = int(option("-f"))
if (
    int(option("-l")) != page
    or option("-r") != "144"
    or "-png" not in sys.argv
    or "-singlefile" not in sys.argv
):
    raise SystemExit(2)
source = Path(sys.argv[-2])
if not source.is_file() or page not in {1, 2}:
    raise SystemExit(2)
pixel = (255, 0, 0) if page == 1 else (0, 0, 255)
Path(f"{sys.argv[-1]}.png").write_bytes(one_pixel_png(*pixel))
