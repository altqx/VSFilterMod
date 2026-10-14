"""Write the CSRI render cases (PNG textures and .ass scripts) to a folder.

    python make_cases.py <out-dir>

The scripts exercise VSFilterMod's \\$img tag: plain path, path with x/y
offsets, an image embedded in the script's [Graphics] section, and plain
text as a control; alpha.ass checks the alpha of CSRI_F_BGRA frames. run_cases.py renders them and checks pixels.
"""
import struct
import sys
import zlib
from pathlib import Path


def png(w, h, pix):
    raw = b"".join(b"\0" + bytes(c for x in range(w) for c in pix(x, y)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def quad(x, y):
    """64x64: top-left red, top-right green, bottom-left blue, bottom-right yellow."""
    return [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)][(x >= 32) + 2 * (y >= 32)]


def stripes(x, y):
    """32x32: left half magenta, right half cyan."""
    return (255, 0, 255, 255) if x < 16 else (0, 255, 255, 255)


def uuencode(data):
    """Aegisub's attachment encoding: 6-bit groups + 33, 80 characters a line."""
    out, line = [], ""
    for pos in range(0, len(data), 3):
        src = data[pos:pos + 3] + b"\0" * (3 - len(data[pos:pos + 3]))
        dst = [src[0] >> 2, ((src[0] & 3) << 4) | (src[1] >> 4), ((src[1] & 15) << 2) | (src[2] >> 6), src[2] & 63]
        for i in range(min(len(data) - pos + 1, 4)):
            line += chr(dst[i] + 33)
            if len(line) == 80 and pos + 3 < len(data):
                out.append(line)
                line = ""
    if line:
        out.append(line)
    return out


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 640
PlayResY: 360
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,10,10,10,1
"""

EVENTS = """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

BOX = r"{\an7\pos(100,100)\bord0\shad0%s\p1}m 0 0 l 128 0 128 128 0 128{\p0}"


def dialogue(text):
    return "Dialogue: 0,0:00:00.00,0:00:10.00,Default,,0,0,0,," + text + "\n"


def graphics_block(graphics):
    body = "[Graphics]\n"
    for fname, data in graphics:
        body += "filename: " + fname + "\n" + "\n".join(uuencode(data)) + "\n"
    return body


def write(out, name, text, graphics=None):
    body = HEADER
    if graphics:
        body += "\n" + graphics_block(graphics)
    body += EVENTS + "".join(dialogue(t) for t in text)
    (out / name).write_text(body, encoding="utf-8-sig", newline="\r\n")


def write_packed(out, name, text, graphics):
    """Sections with no blank lines between them, attachments before the
    styles: the [Graphics] block must not swallow the next section header."""
    script_info, styles = HEADER.split("\n[V4+ Styles]\n")
    body = (script_info.rstrip("\n") + "\n" + graphics_block(graphics) + "[V4+ Styles]\n" + styles.rstrip("\n")
            + "\n" + EVENTS.strip("\n") + "\n" + "".join(dialogue(t) for t in text))
    (out / name).write_text(body, encoding="utf-8-sig", newline="\r\n")


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    tex = png(64, 64, quad)
    att = png(32, 32, stripes)
    (out / "tex.png").write_bytes(tex)
    (out / "img").mkdir(exist_ok=True)
    (out / "img" / "tex.png").write_bytes(tex)
    embedded = [("embedded.png", att)]
    write(out, "text.ass", [r"{\an7\pos(100,100)}VSFilterMod"])
    write(out, "img_path.ass", [BOX % r"\1img(tex.png)"])
    write(out, "img_offset.ass", [BOX % r"\1img(tex.png,32,16)"])
    # issue #3: a Windows path (backslashes) with offsets
    write(out, "img_backslash_offset.ass", [BOX % r"\1img(img\tex.png,32,16)"])
    write(out, "img_offset_spaces.ass", [BOX % r"\1img( img/tex.png , 32 , 16 )"])
    write(out, "img_offset_anim.ass", [BOX % r"\1img(img\tex.png)\t(0,2000,\1img(img\tex.png,32,32))"])
    # issue #4: images attached to the script
    write(out, "img_attached.ass", [BOX % r"\1img(embedded.png)"], graphics=embedded)
    write(out, "img_attached_offset.ass", [BOX % r"\1img(embedded.png,8,0)"], graphics=embedded)
    write(out, "img_attached_by_path.ass", [BOX % r"\1img(Q:/elsewhere/embedded.png)"], graphics=embedded)
    write(out, "img_attached_case.ass", [BOX % r"\1img(EMBEDDED.PNG)"], graphics=embedded)
    write_packed(out, "img_attached_packed.ass", [BOX % r"\1img(embedded.png)"], graphics=embedded)
    # no override tags: the style (v4+ alignment 7, top left) places the text
    write_packed(out, "graphics_before_styles.ass", ["VSFilterMod"], graphics=embedded)
    # alpha: an opaque white box at (100,100) and a half transparent red one
    # (\1a&H80&: 127 of 255 covered) at (300,100), both 128x128
    write(out, "alpha.ass", [BOX % r"\1c&HFFFFFF&", (BOX % r"\1c&H0000FF&\1a&H80&").replace(r"\pos(100,100)", r"\pos(300,100)")])


if __name__ == "__main__":
    main()
