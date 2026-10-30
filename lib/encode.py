"""Minimal, size-optimised PNG encoder (stdlib only).

Why not Pillow or ImageIO? Each emulator icon has a fixed byte budget (the size
of the PNG it replaces), and ImageIO adds metadata chunks (including an EXIF
orientation that rotates the icon in some viewers). This encoder writes only
IHDR + IDAT + IEND, tries all five PNG row filters per row, and uses maximum
zlib compression, so the result reliably fits.

Input is raw premultiplied RGBA (what CoreGraphics produces), output is a
non-premultiplied 8-bit RGBA PNG, which is what PNG stores.
"""
import struct
import zlib


def _chunk(chunk_type, payload):
    """Serialise one PNG chunk: length, type, payload, CRC32 over type+payload."""
    return (struct.pack(">I", len(payload)) + chunk_type + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload)))


def _paeth(a, b, c):
    """PNG Paeth predictor: pick whichever of left (a), up (b), up-left (c) is closest to a+b-c."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _filter_rows(rows, width):
    """Apply the best PNG row filter to each scanline.

    For every row all five filters (None, Sub, Up, Average, Paeth) are computed
    and the one with the smallest sum of absolute residuals is kept, a standard
    heuristic that tends to compress best. Each filtered row is prefixed with
    its filter-type byte, as the PNG format requires.
    """
    bytes_per_pixel = 4
    out = bytearray()
    prev = bytes(width * bytes_per_pixel)
    for row in rows:
        best = None
        for ftype in range(5):
            filtered = bytearray(len(row))
            for i, x in enumerate(row):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                up = prev[i]
                up_left = prev[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                predictor = (0, left, up, (left + up) // 2, _paeth(left, up, up_left))[ftype]
                filtered[i] = (x - predictor) & 255
            score = sum(v if v < 128 else 256 - v for v in filtered)
            if best is None or score < best[0]:
                best = (score, ftype, filtered)
        out.append(best[1])
        out += best[2]
        prev = row
    return bytes(out)


def _unpremultiply(pixels):
    """Convert premultiplied RGBA to straight RGBA in place, rounding to nearest."""
    for i in range(0, len(pixels), 4):
        alpha = pixels[i + 3]
        if 0 < alpha < 255:
            for k in range(3):
                pixels[i + k] = min(255, (pixels[i + k] * 255 + alpha // 2) // alpha)


def encode(raw_rgba, size):
    """Encode ``size`` x ``size`` premultiplied RGBA bytes as a minimal PNG and return its bytes."""
    pixels = bytearray(raw_rgba)
    _unpremultiply(pixels)
    stride = size * 4
    rows = [bytes(pixels[y * stride:(y + 1) * stride]) for y in range(size)]
    compressor = zlib.compressobj(9, zlib.DEFLATED, 15, 9)  # level 9, 32K window, max memory
    idat = compressor.compress(_filter_rows(rows, size)) + compressor.flush()
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit, color type 6 = RGBA
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
