"""QR codes (ISO/IEC 18004) for links shown on the screen, so a phone can pick them up.

Byte mode only, error correction M (L when the text is too long for M), the mask with the lowest
penalty. No dependencies: the menu draws the code itself as SVG.

    matrix = encode("https://example.org/…")    # rows of bools, dark = True
    svg(matrix)                                 # '<svg …>'
"""

import collections
import functools

# Per version 1..40 (index 0 unused): error correction codewords per block, and number of blocks.
ECC_PER_BLOCK = {
    "L": (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28,
          28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    "M": (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
          26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
}
BLOCKS = {
    "L": (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8,
          8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    "M": (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
          17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
}
FORMAT_BITS = {"L": 1, "M": 0}
MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def _raw_modules(ver):
    """Modules left for data and error correction once the function patterns are drawn."""
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        a = ver // 7 + 2
        n -= (25 * a - 10) * a - 55
        if ver >= 7:
            n -= 36
    return n


def capacity(ver, ecl):
    """Data codewords (bytes) of a version at an error correction level."""
    return _raw_modules(ver) // 8 - ECC_PER_BLOCK[ecl][ver] * BLOCKS[ecl][ver]


def max_bytes(ver, ecl):
    """The longest byte-mode text that fits."""
    return (capacity(ver, ecl) * 8 - 4 - (8 if ver <= 9 else 16)) // 8


# ---------------- Reed-Solomon over GF(2^8), polynomial 0x11D ----------------
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i], _LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


@functools.lru_cache(maxsize=None)
def _divisor(degree):
    """Coefficients of prod(x - 2^i), i < degree, highest power first and dropped."""
    out = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _mul(root, 2)
    return tuple(out)


def _remainder(data, divisor):
    out = [0] * len(divisor)
    for b in data:
        factor = b ^ out.pop(0)
        out.append(0)
        if factor:
            for i, c in enumerate(divisor):
                out[i] ^= _mul(c, factor)
    return out


def _codewords(data, ver, ecl):
    """The data bytes split into blocks, error correction added, interleaved."""
    nblocks, ecc = BLOCKS[ecl][ver], ECC_PER_BLOCK[ecl][ver]
    raw = _raw_modules(ver) // 8
    nshort, short = nblocks - raw % nblocks, raw // nblocks
    div = _divisor(ecc)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = list(data[k:k + short - ecc + (0 if i < nshort else 1)])
        k += len(dat)
        rem = _remainder(dat, div)
        if i < nshort:
            dat.append(0)  # a gap, so that every block is as long as the long ones
        blocks.append(dat + rem)
    return [blk[i] for i in range(len(blocks[0])) for j, blk in enumerate(blocks)
            if i != short - ecc or j >= nshort]


# ---------------- the symbol ----------------
class _Symbol:
    def __init__(self, ver):
        self.ver, self.size = ver, ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x, y, dark):
        self.m[y][x] = dark
        self.fn[y][x] = True

    def function_patterns(self):
        n = self.size
        for i in range(n):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):  # finders, with their light separators
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self.alignment_positions()
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue  # under a finder
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits("M", 0)  # reserve the areas; the real bits come with the mask
        self.version_bits()

    def alignment_positions(self):
        if self.ver == 1:
            return []
        a = self.ver // 7 + 2
        step = (self.ver * 8 + a * 3 + 5) // (a * 4 - 4) * 2
        return [6] + sorted(self.size - 7 - i * step for i in range(a - 1))

    def format_bits(self, ecl, mask):
        data = FORMAT_BITS[ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        n = self.size
        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, bit(i))
        self.set_fn(8, n - 8, True)  # the dark module

    def version_bits(self):
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.ver << 12 | rem
        for i in range(18):
            dark = (bits >> i) & 1 == 1
            a, b = self.size - 11 + i % 3, i // 3
            self.set_fn(a, b, dark)
            self.set_fn(b, a, dark)

    def place(self, codewords):
        """Data bits in the zigzag from the bottom right, two columns at a time."""
        n, i, total = self.size, 0, len(codewords) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5  # skip the vertical timing pattern
            upward = (right + 1) & 2 == 0
            for vert in range(n):
                y = n - 1 - vert if upward else vert
                for x in (right, right - 1):
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        f = MASKS[mask]
        for y in range(self.size):
            row, fn = self.m[y], self.fn[y]
            for x in range(self.size):
                if not fn[x] and f(x, y):
                    row[x] = not row[x]

    def penalty(self):
        n, m = self.size, self.m
        score = 0

        def lines():
            yield from m
            for x in range(n):
                yield [m[y][x] for y in range(n)]

        for line in lines():
            color, run = False, 0
            history = collections.deque([0] * 7, 7)
            for cell in line:
                if cell == color:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    self._history(run, history)
                    if not color:
                        score += self._finder_like(history) * 40
                    color, run = cell, 1
            if color:  # end the line with the light border after it
                self._history(run, history)
                run = 0
            self._history(run + n, history)
            score += self._finder_like(history) * 40
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in m)
        total = n * n
        score += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
        return score

    def _history(self, run, history):
        if history[0] == 0:
            run += self.size  # the light border before the line
        history.appendleft(run)

    @staticmethod
    def _finder_like(h):
        n = h[1]
        core = n > 0 and h[2] == h[4] == h[5] == n and h[3] == n * 3
        return (1 if core and h[0] >= n * 4 and h[6] >= n else 0) + (1 if core and h[6] >= n * 4 and h[0] >= n else 0)


def _bits(data, ver, ecl):
    """Byte-mode segment, terminator and padding: the data codewords."""
    bits = [0, 1, 0, 0]
    count = 8 if ver <= 9 else 16
    bits += [(len(data) >> i) & 1 for i in reversed(range(count))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    room = capacity(ver, ecl) * 8
    bits += [0] * min(4, room - len(bits))
    bits += [0] * (-len(bits) % 8)
    out = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(out) < capacity(ver, ecl):
        out.append(pad)
        pad ^= 0xEC ^ 0x11
    return out


def choose(length):
    """(version, level) for `length` bytes: M if it fits, else L. ValueError when nothing does."""
    for ecl in ("M", "L"):
        for ver in range(1, 41):
            if length <= max_bytes(ver, ecl):
                return ver, ecl
    raise ValueError(f"{length} bytes don't fit in a QR code")


def encode(text, ver=None, ecl=None, mask=None):
    """Rows of bools (True = dark) of the QR code for `text`. Version, level and mask are picked
    unless given (tests pin them to compare with other encoders)."""
    data = text.encode("utf-8")
    if ver is None or ecl is None:
        ver, ecl = choose(len(data))
    if len(data) > max_bytes(ver, ecl):
        raise ValueError(f"{len(data)} bytes don't fit in version {ver}-{ecl}")
    s = _Symbol(ver)
    s.function_patterns()
    s.place(_codewords(_bits(data, ver, ecl), ver, ecl))
    if mask is None:
        best = None
        for k in range(8):
            s.apply_mask(k)
            s.format_bits(ecl, k)
            p = s.penalty()
            if best is None or p < best[0]:
                best = (p, k)
            s.apply_mask(k)
        mask = best[1]
    s.apply_mask(mask)
    s.format_bits(ecl, mask)
    return s.m


def svg(matrix, border=4):
    """The code as a small SVG: one path of dark runs on white, with the quiet zone around."""
    n = len(matrix)
    runs = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                runs.append(f"M{start + border} {y + border}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    dim = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" shape-rendering="crispEdges">'
            f'<rect width="{dim}" height="{dim}" fill="#fff"/><path d="{"".join(runs)}" fill="#000"/></svg>')
