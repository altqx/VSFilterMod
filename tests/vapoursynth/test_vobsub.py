"""VobSub options through VapourSynth (vsfm.VobSub), on Windows.

    python test_vobsub.py <VSFilterMod.dll> <dir with test.idx/test.sub> [out-dir]

Needs a VapourSynth that still loads API 3 plugins (R79 or older, e.g.
pip install vapoursynth==79). The VobSub comes from tests/vobsub/make_vobsub.py.
Exit status 1 when a check fails. With [out-dir], each checked frame is
written there as a PPM.
"""
import sys
from pathlib import Path

import vapoursynth as vs

core = vs.core
BLACK, WHITE, RED, BLUE = (0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 0, 255)
GREEN, MAGENTA = (0, 255, 0), (255, 0, 255)


def frame_rgb(clip, n):
    f = clip.get_frame(n)
    planes = [f[p] for p in range(3)]
    w, h = clip.width, clip.height

    def px(x, y):
        out = []
        for p in planes:
            try:
                out.append(p[y, x])
            except (TypeError, NotImplementedError):
                out.append(p.tolist()[y][x])
        return tuple(out)

    return px, f


def save(clip, n, path):
    f = clip.get_frame(n)
    rows = []
    for y in range(clip.height):
        r, g, b = (bytes(f[p])[y * f.get_stride(p):y * f.get_stride(p) + clip.width] for p in range(3))
        rows.append(bytes(c for t in zip(r, g, b) for c in t))
    path.write_bytes(b"P6\n%d %d\n255\n" % (clip.width, clip.height) + b"".join(rows))


def near(a, b, tol=12):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def main():
    dll, src = str(Path(sys.argv[1]).resolve()), Path(sys.argv[2]).resolve()
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    core.std.LoadPlugin(dll)
    blank = core.std.BlankClip(width=720, height=480, format=vs.RGB24, fpsnum=10, fpsden=1, length=60, color=[0, 0, 0])
    idx = str(src / "test.idx")

    # frame 20 = 2.0 s, inside the 1.0-3.0 s subpicture
    cases = [
        ("default (langidx 0)", {}, 20, {(150, 400): WHITE, (150, 380): BLUE, (440, 115): BLACK}),
        ("track=1", {"track": 1}, 20, {(440, 115): RED, (440, 100): BLUE, (150, 400): BLACK}),
        ("delay=1500, before", {"delay": 1500}, 20, {(150, 400): BLACK}),
        ("delay=1500, after", {"delay": 1500}, 30, {(150, 400): WHITE}),
        ("delay=-1500", {"delay": -1500}, 5, {(150, 400): WHITE}),
        ("forced=1", {"forced": 1}, 20, {(150, 400): BLACK}),
        ("colors+tridx", {"colors": "000000,00ff00,ff00ff,000000", "tridx": "1000"}, 20,
         {(150, 400): GREEN, (150, 380): MAGENTA, (90, 370): BLACK}),
        ("palette", {"palette": ",".join(["000000", "00ff00"] + ["ff00ff"] * 14), "track": 1}, 20,
         {(440, 115): MAGENTA, (150, 400): BLACK}),
        ("x,y", {"x": 50, "y": -300}, 20, {(200, 100): WHITE, (150, 400): BLACK}),
        ("align+x,y", {"align": "center center", "x": 360, "y": 240}, 20,
         {(360, 240): WHITE, (360, 220): BLUE, (150, 400): BLACK}),
        ("scale", {"track": 1, "scale_x": 50, "scale_y": 50}, 20, {(220, 57): RED, (440, 115): BLACK}),
        ("alpha=50", {"alpha": 50}, 20, {(150, 400): (128, 128, 128)}),
    ]
    failures = 0
    for name, args, n, want in cases:
        problems = []
        try:
            clip = core.vsfm.VobSub(blank, idx, **args)
            px, _ = frame_rgb(clip, n)
            for (x, y), colour in want.items():
                got = px(x, y)
                if not near(got, colour):
                    problems.append("(%d,%d) is %s, want %s" % (x, y, got, colour))
            if out:
                save(clip, n, out / ("vobsub_" + "".join(c if c.isalnum() else "_" for c in name) + ".ppm"))
        except vs.Error as e:
            problems.append("error: %s" % e)
        print("%-22s %s" % (name, "ok" if not problems else "FAIL"))
        for p in problems:
            print("    " + p)
        failures += bool(problems)

    for name, args, needle in [("track=5", {"track": 5}, "track 5 has no subtitles"),
                               ("tridx=12", {"tridx": "12"}, "tridx"),
                               ("align=up", {"align": "up"}, "align")]:
        try:
            core.vsfm.VobSub(blank, idx, **args)
            ok, msg = False, "no error"
        except vs.Error as e:
            ok, msg = needle in str(e), str(e)
        print("%-22s %s" % ("error " + name, "ok" if ok else "FAIL"))
        if not ok:
            print("    " + msg)
            failures += 1

    print("%d failures" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
