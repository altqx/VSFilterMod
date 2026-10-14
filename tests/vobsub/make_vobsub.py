"""Write a small two-track VobSub (.idx + .sub) for the VobSub filter tests.

    python make_vobsub.py <out-dir>

Both tracks show one subpicture from 1.000 s to 3.000 s on a 720x480 frame:
  track 0 ("en"): a 100x40 box at (100,380), white inside a blue frame
  track 1 ("ja"): an 80x30 box at (400,100), red inside a blue frame
The inside is pixel type "pattern", the 4 pixel frame "emphasis 1" and the
rest "background" (transparent), so custom colours can recolour each part.
"""
import sys
from pathlib import Path

PALETTE = ["000000", "ffffff", "ff0000", "0000ff", "00ff00", "ffff00", "00ffff", "ff00ff",
           "808080", "404040", "c0c0c0", "800000", "008000", "000080", "808000", "008080"]
FRAME = 4  # frame width in pixels: wide enough to probe past the bilinear edge

TRACKS = [
    # lang, x, y, w, h, colour index of pixel value 1, of pixel value 2
    ("en", 100, 380, 100, 40, 1, 3),
    ("ja", 400, 100, 80, 30, 2, 3),
]


class Nibbles:
    def __init__(self):
        self.n = []

    def put(self, value, count):
        for i in reversed(range(count)):
            self.n.append((value >> (4 * i)) & 15)

    def align(self):
        if len(self.n) % 2:
            self.n.append(0)

    def bytes(self):
        self.align()
        return bytes((self.n[i] << 4) | self.n[i + 1] for i in range(0, len(self.n), 2))


def rle_line(out, pixels):
    """VobSub 2-bit run-length coding of one line."""
    i = 0
    while i < len(pixels):
        p = pixels[i]
        run = 1
        while i + run < len(pixels) and pixels[i + run] == p and run < 255:
            run += 1
        if i + run == len(pixels) and run > 63:
            out.put(p, 4)  # 0000 0000 0000 00pp: to the end of the line
        elif run < 4:
            out.put((run << 2) | p, 1)
        elif run < 16:
            out.put((run << 2) | p, 2)
        elif run < 64:
            out.put((run << 2) | p, 3)
        else:
            out.put((run << 2) | p, 4)
        i += run
    out.align()


def spu(w, h, x, y, duration_ms, c1, c2):
    rows = []
    for r in range(h):
        if r < FRAME or r >= h - FRAME:
            rows.append([2] * w)
        else:
            rows.append([2] * FRAME + [1] * (w - 2 * FRAME) + [2] * FRAME)
    top, bottom = Nibbles(), Nibbles()
    for r in range(0, h, 2):
        rle_line(top, rows[r])
    for r in range(1, h, 2):
        rle_line(bottom, rows[r])
    top_b, bottom_b = top.bytes(), bottom.bytes()
    pix = top_b + bottom_b
    top_off, bottom_off = 4, 4 + len(top_b)
    ctrl1_off = 4 + len(pix)

    x2, y2 = x + w - 1, y + h - 1
    cmds1 = bytes([0x01,                     # STA_DSP
                   0x03, c2, c1 << 4,        # SET_COLOR: e2=0 e1=c2 pattern=c1 background=0
                   0x04, 0xFF, 0xF0,         # SET_CONTR: background transparent
                   0x05, x >> 4, ((x & 15) << 4) | (x2 >> 8), x2 & 255, y >> 4, ((y & 15) << 4) | (y2 >> 8), y2 & 255,
                   0x06, top_off >> 8, top_off & 255, bottom_off >> 8, bottom_off & 255,
                   0xFF])
    ctrl2_off = ctrl1_off + 4 + len(cmds1)
    delay = duration_ms * 90 // 1024
    ctrl1 = bytes([0, 0, ctrl2_off >> 8, ctrl2_off & 255]) + cmds1
    ctrl2 = bytes([delay >> 8, delay & 255, ctrl2_off >> 8, ctrl2_off & 255, 0x02, 0xFF])
    data = pix + ctrl1 + ctrl2
    size = 4 + len(data)
    if size % 2:
        data += b"\xff"
        size += 1
    return bytes([size >> 8, size & 255, ctrl1_off >> 8, ctrl1_off & 255]) + data


def pts_bytes(pts):
    return bytes([0x21 | ((pts >> 29) & 0x0E), (pts >> 22) & 0xFF, 0x01 | ((pts >> 14) & 0xFE),
                  (pts >> 7) & 0xFF, 0x01 | ((pts << 1) & 0xFE)])


def sector(track, pts, payload):
    pack = b"\x00\x00\x01\xba" + bytes([0x44, 0, 4, 0, 4, 1, 0x01, 0x89, 0xC3, 0xF8])
    body = bytes([0x81, 0x80, 5]) + pts_bytes(pts) + bytes([0x20 | track]) + payload
    pes = b"\x00\x00\x01\xbd" + len(body).to_bytes(2, "big") + body
    data = pack + pes
    assert len(data) <= 2048 - 6, "one sector per subpicture"
    pad = 2048 - len(data) - 6
    return data + b"\x00\x00\x01\xbe" + pad.to_bytes(2, "big") + b"\xff" * pad


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    sub = b""
    idx = ["# VobSub index file, v7 (do not modify this line!)",
           "size: 720x480", "org: 0, 0", "scale: 100%, 100%", "alpha: 100%", "smooth: OFF",
           "fadein/out: 0, 0", "align: OFF at LEFT TOP", "time offset: 0", "forced subs: OFF",
           "palette: " + ", ".join(PALETTE),
           "custom colors: OFF, tridx: 0000, colors: 000000, 000000, 000000, 000000",
           "langidx: 0", ""]
    for n, (lang, x, y, w, h, c1, c2) in enumerate(TRACKS):
        pos = len(sub)
        sub += sector(n, 90 * 1000, spu(w, h, x, y, 2000, c1, c2))
        idx += ["id: %s, index: %d" % (lang, n),
                "timestamp: 00:00:01:000, filepos: %09x" % pos, ""]
    (out / "test.sub").write_bytes(sub)
    (out / "test.idx").write_text("\n".join(idx) + "\n", newline="\r\n")


if __name__ == "__main__":
    main()
