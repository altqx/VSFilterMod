"""Lay out the release: dist/x64, dist/x86 and VSFilterMod_bin.zip.

    python package.py <x64 VSFilterMod.dll> <x86 VSFilterMod.dll> <dist-dir> <zip>

The zip holds exactly x64/VSFilterMod.dll and x86/VSFilterMod.dll, with
forward slashes, like the upstream VSFilterMod_bin.zip.
"""
import shutil
import sys
import zipfile
from pathlib import Path


def main():
    x64, x86, dist, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arch, dll in (("x64", x64), ("x86", x86)):
            (dist / arch).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dll, dist / arch / "VSFilterMod.dll")
            z.write(dll, arch + "/VSFilterMod.dll")
    with zipfile.ZipFile(out) as z:
        for info in z.infolist():
            print("%10d  %s" % (info.file_size, info.filename))


if __name__ == "__main__":
    main()
