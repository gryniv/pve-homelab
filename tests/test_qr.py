"""QR codes: valid symbols (read back by libzbar where it is installed) and fixed vectors."""

import ctypes
import ctypes.util
import hashlib

import pytest

from pvehomelab import qr

LINK = "https://github.com/gryniv/pve-homelab/issues/new?title=Bug%3A%20x&body=abcdefghijklmnopqrstuvwxyz0123456789-_.~%20"


def text(n):
    return (LINK * (n // len(LINK) + 1))[:n]


def digest(matrix):
    return hashlib.sha256("\n".join("".join("1" if c else "0" for c in row) for row in matrix).encode()).hexdigest()[:16]


def zbar():
    """libzbar's decoder through ctypes, or None (it is an optional system library)."""
    name = ctypes.util.find_library("zbar")
    if not name:
        return None
    lib = ctypes.CDLL(name)
    v = ctypes.c_void_p
    for fn, args, res in (("zbar_image_scanner_create", [], v), ("zbar_image_scanner_set_config", [v, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
                          ("zbar_image_create", [], v), ("zbar_image_set_format", [v, ctypes.c_ulong], None),
                          ("zbar_image_set_size", [v, ctypes.c_uint, ctypes.c_uint], None), ("zbar_image_set_data", [v, v, ctypes.c_ulong, v], None),
                          ("zbar_scan_image", [v, v], ctypes.c_int), ("zbar_image_first_symbol", [v], v),
                          ("zbar_symbol_get_data", [v], v), ("zbar_symbol_get_data_length", [v], ctypes.c_uint),
                          ("zbar_image_destroy", [v], None), ("zbar_image_scanner_destroy", [v], None)):
        getattr(lib, fn).argtypes, getattr(lib, fn).restype = args, res

    def decode(matrix, scale=3, border=4):
        dim = (len(matrix) + 2 * border) * scale
        px = bytearray(b"\xff" * dim * dim)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    for dy in range(scale):
                        o = ((y + border) * scale + dy) * dim + (x + border) * scale
                        px[o:o + scale] = b"\x00" * scale
        sc, img = lib.zbar_image_scanner_create(), lib.zbar_image_create()
        lib.zbar_image_scanner_set_config(sc, 0, 0, 1)
        lib.zbar_image_set_format(img, int.from_bytes(b"Y800", "little"))
        lib.zbar_image_set_size(img, dim, dim)
        buf = ctypes.create_string_buffer(bytes(px), len(px))
        lib.zbar_image_set_data(img, ctypes.cast(buf, v), len(px), None)
        try:
            if lib.zbar_scan_image(sc, img) <= 0:
                return None
            sym = lib.zbar_image_first_symbol(img)
            return ctypes.string_at(lib.zbar_symbol_get_data(sym), lib.zbar_symbol_get_data_length(sym))
        finally:
            lib.zbar_image_destroy(img)
            lib.zbar_image_scanner_destroy(sc)
    return decode


def test_fixed_vectors():
    # v14-M and v40-L (full, so no padding choices) are bit for bit what segno 1.6 draws with the
    # same mask; v3-M is the automatic choice for the bare link
    assert digest(qr.encode("x" * qr.max_bytes(14, "M"), 14, "M", 3)) == "ac916391bd38ce15"
    assert digest(qr.encode("y" * qr.max_bytes(40, "L"), 40, "L", 6)) == "7f07071088a4b583"
    assert qr.choose(37) == (3, "M")
    assert digest(qr.encode("https://github.com/gryniv/pve-homelab")) == "3c3241182702d1d6"


def test_version_and_level_choice():
    assert qr.choose(1) == (1, "M")
    assert qr.choose(qr.max_bytes(25, "M")) == (25, "M") and qr.choose(qr.max_bytes(25, "M") + 1) == (26, "M")
    assert qr.choose(qr.max_bytes(40, "M") + 1)[1] == "L"   # past what M holds, L still does
    with pytest.raises(ValueError):
        qr.choose(qr.max_bytes(40, "L") + 1)
    with pytest.raises(ValueError):
        qr.encode("x" * 100, 2, "M")
    assert [len(qr.encode("a", v, "M")) for v in (1, 7, 40)] == [21, 45, 177]


@pytest.mark.parametrize("ecl", ["M", "L"])
def test_every_version_reads_back(ecl):
    decode = zbar()
    if not decode:
        pytest.skip("libzbar is not installed")
    for ver in range(1, 41):
        s = text(qr.max_bytes(ver, ecl))
        assert decode(qr.encode(s, ver, ecl)) == s.encode(), (ver, ecl)


def test_auto_choice_reads_back():
    decode = zbar()
    if not decode:
        pytest.skip("libzbar is not installed")
    for n in (10, 120, 600, 1200):
        assert decode(qr.encode(text(n))) == text(n).encode(), n
    assert decode(qr.encode("Привіт ✓")) == "Привіт ✓".encode()


def test_svg():
    m = qr.encode("hi")
    s = qr.svg(m)
    dim = len(m) + 8
    assert s.startswith("<svg") and f'viewBox="0 0 {dim} {dim}"' in s and 'fill="#fff"' in s
    assert s.count("h") > len(m)  # one run or more per row
