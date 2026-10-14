"""Render the cases from make_cases.py through a CSRI DLL and check pixels.

    python run_cases.py <csri_render command> <renderer.dll> <cases-dir> <out-dir>

<csri_render command> is the harness, e.g. "csri_render.exe" or
"wine csri_render.exe". Every frame is written to <out-dir>/<case>.ppm.
Exit status 1 when a check fails.
"""
import shlex
import subprocess
import sys
from pathlib import Path

BG = (0x20, 0x20, 0x20)
R, G, B, Y = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)
M, C = (255, 0, 255), (0, 255, 255)

# The 128x128 box is drawn at (100,100)-(227,227). The texture repeats from
# the left edge of the box and from the bottom of the drawing's bitmap (two
# rows below the box at this size), which is how VSFilterMod has always
# placed it. +x moves the pattern left, +y moves it down.
QUAD = {(110, 115): R, (145, 115): G, (110, 150): B, (145, 150): Y}
QUAD_32_16 = {(110, 108): Y, (110, 130): G, (145, 108): B, (145, 130): R}
STRIPES = {(105, 150): M, (120, 150): C, (140, 150): M}
STRIPES_8 = {(104, 150): M, (115, 150): C, (130, 150): M}
BOX = (100, 100, 227, 227)

CASES = {
    "text": {"changed": True},
    "img_path": {"pixels": QUAD, "bbox": BOX},
    "img_offset": {"pixels": QUAD_32_16, "bbox": BOX},
    "img_backslash_offset": {"pixels": QUAD_32_16, "bbox": BOX},
    "img_offset_spaces": {"pixels": QUAD_32_16, "bbox": BOX},
    # halfway through \t(0,2000,...) at 1.0 s: offset 16,16
    "img_offset_anim": {"pixels": {(110, 104): B, (110, 125): R, (130, 104): Y, (130, 125): G}, "bbox": BOX},
    "img_attached": {"pixels": STRIPES, "bbox": BOX},
    "img_attached_offset": {"pixels": STRIPES_8, "bbox": BOX},
    "img_attached_by_path": {"pixels": STRIPES, "bbox": BOX},
    "img_attached_case": {"pixels": STRIPES, "bbox": BOX},
    "img_attached_packed": {"pixels": STRIPES, "bbox": BOX},
    "graphics_before_styles": {"changed": True, "left_of": 40, "above": 60},
}


def read_ppm(path):
    data = path.read_bytes()
    magic, size, maxval, pixels = data.split(b"\n", 3)
    w, h = map(int, size.split())
    return w, h, pixels


# CSRI_F_BGRA is straight alpha, 255 opaque, laid over what the frame holds
# (asa, the renderer by CSRI's author, blends it so): on a cleared frame a drawn
# pixel carries its colour and coverage, an empty pixel keeps alpha 0, and
# that frame laid over a background matches BGR_ drawn on the background.
# BGR_ has no alpha: its fourth byte is padding, kept where nothing is drawn.
ALPHA_BOX, ALPHA_HALF, ALPHA_EMPTY = (160, 160), (360, 160), [(20, 20), (600, 300), (260, 160)]
# (case, format, background, background alpha): {pixel: (colour, alpha)},
# colour and alpha None when not checked, alpha within 2 levels
ALPHA_CASES = [
    ("alpha", "bgra", 0x000000, 0x00,
     {ALPHA_BOX: ((255, 255, 255), 255), ALPHA_HALF: ((255, 0, 0), 127),
      **{p: ((0, 0, 0), 0) for p in ALPHA_EMPTY}}),
    ("alpha", "bgra", 0x202020, 0xff,
     {ALPHA_BOX: ((255, 255, 255), 255), ALPHA_HALF: (None, 255),
      **{p: ((0x20, 0x20, 0x20), 255) for p in ALPHA_EMPTY}}),
    ("alpha", "bgr_", 0x202020, 0xff,
     {ALPHA_BOX: ((255, 255, 255), None), ALPHA_HALF: ((0x8f, 0x10, 0x10), None),
      **{p: ((0x20, 0x20, 0x20), 255) for p in ALPHA_EMPTY}}),
]
# BGRA drawn on a cleared frame and laid over 202020 is BGR_ drawn on 202020
OVER_CASES = ["alpha", "text", "img_path"]
TOLERANCE = 2


def render(harness, dll, cases, out, name, fmt="bgr_", bg=0x202020, bga=0):
    stem = "%s-%s-%06x-%02x" % (name, fmt, bg, bga)
    ppm = out / (stem + ".ppm")
    run = subprocess.run(harness + [dll, str(cases / (name + ".ass")), "640", "360", "1.0", str(ppm),
                                    "%06x" % bg, "file", fmt, "%02x" % bga],
                         capture_output=True, text=True, timeout=300)
    report = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else run.stderr.strip()
    pgm = out / (stem + ".alpha.pgm")
    if run.returncode != 0 or not ppm.exists() or not pgm.exists():
        return None, "harness exit %d: %s" % (run.returncode, report)
    w, _, colour = read_ppm(ppm)
    _, _, alpha = read_ppm(pgm)
    return (w, colour, alpha), report


def alpha_checks(harness, dll, cases, out):
    failures = total = 0
    for name, fmt, bg, bga, want in ALPHA_CASES:
        total += 1
        frame, report = render(harness, dll, cases, out, name, fmt, bg, bga)
        problems = [report] if frame is None else []
        if frame:
            w, colour, alpha = frame
            for (x, y), (c, a) in want.items():
                i = y * w + x
                got_c, got_a = tuple(colour[i * 3:i * 3 + 3]), alpha[i]
                if c is not None and max(abs(g - e) for g, e in zip(got_c, c)) > TOLERANCE:
                    problems.append("(%d,%d) colour is %s, want %s" % (x, y, got_c, c))
                if a is not None and abs(got_a - a) > TOLERANCE:
                    problems.append("(%d,%d) alpha is %d, want %d" % (x, y, got_a, a))
        label = "%s %s on %06x/%02x" % (name, fmt, bg, bga)
        print("%-34s %s" % (label, "ok" if not problems else "FAIL"))
        for p in problems:
            print("    " + p)
        failures += bool(problems)
    for name in OVER_CASES:
        total += 1
        over, report_a = render(harness, dll, cases, out, name, "bgra", 0x000000, 0x00)
        frame, report_b = render(harness, dll, cases, out, name, "bgr_", 0x202020, 0xff)
        problems = [r for f, r in ((over, report_a), (frame, report_b)) if f is None]
        if not problems:
            _, colour_a, alpha_a = over
            _, colour_b, _ = frame
            worst, where = 0, None
            for i, a in enumerate(alpha_a):
                for c in range(3):
                    laid = (colour_a[i * 3 + c] * a + 0x20 * (255 - a) + 127) // 255
                    diff = abs(laid - colour_b[i * 3 + c])
                    if diff > worst:
                        worst, where = diff, i
            if worst > TOLERANCE:
                problems.append("BGRA laid over 202020 is %d levels off BGR_ at (%d,%d)"
                                % (worst, where % 640, where // 640))
            if "changed=0" in report_b:
                problems.append("nothing was drawn")
        label = "%s bgra over 202020 = bgr_" % name
        print("%-34s %s" % (label, "ok" if not problems else "FAIL"))
        for p in problems:
            print("    " + p)
        failures += bool(problems)
    return failures, total


def main():
    # LoadLibrary wants backslashes on Windows: hand over resolved paths.
    harness = [str(Path(a).resolve()) if Path(a).is_file() else a for a in shlex.split(sys.argv[1])]
    dll, cases, out = str(Path(sys.argv[2]).resolve()), Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, want in CASES.items():
        ppm = out / (name + ".ppm")
        run = subprocess.run(harness + [dll, str(cases / (name + ".ass")), "640", "360", "1.0", str(ppm), "202020", "file"],
                             capture_output=True, text=True, timeout=300)
        report = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else run.stderr.strip()
        problems = []
        if run.returncode != 0 or not ppm.exists():
            problems.append("harness exit %d: %s" % (run.returncode, report))
        else:
            w, _, px = read_ppm(ppm)
            pixel = lambda x, y: tuple(px[(y * w + x) * 3:(y * w + x) * 3 + 3])
            if want.get("changed") and "changed=0" in report:
                problems.append("nothing was drawn")
            for (x, y), colour in want.get("pixels", {}).items():
                if pixel(x, y) != colour:
                    problems.append("(%d,%d) is %s, want %s" % (x, y, pixel(x, y), colour))
            if "left_of" in want or "above" in want:
                try:
                    x0, y0 = map(int, report.split("bbox=")[1].split("-")[0].split(","))
                except (IndexError, ValueError):
                    x0 = y0 = 1 << 30
                if x0 >= want.get("left_of", 1 << 30) or y0 >= want.get("above", 1 << 30):
                    problems.append("drawn area %s, want it to start left of x=%d and above y=%d"
                                    % (report, want.get("left_of", 0), want.get("above", 0)))
            if "bbox" in want and "bbox=%d,%d-%d,%d" % want["bbox"] not in report:
                problems.append("drawn area %s, want bbox=%d,%d-%d,%d" % ((report,) + want["bbox"]))
        print("%-24s %s" % (name, "ok" if not problems else "FAIL"))
        for p in problems:
            print("    " + p)
        failures += bool(problems)
    alpha_failures, alpha_total = alpha_checks(harness, dll, cases, out)
    failures += alpha_failures
    print("%d of %d cases failed" % (failures, len(CASES) + alpha_total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
