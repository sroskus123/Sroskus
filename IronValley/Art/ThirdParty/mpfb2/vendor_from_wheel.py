"""
Re-create this folder's vendored MakeHuman / MPFB2 data (CC0 1.0) from the PyPI wheel
anny 0.6.0 (NAVER; package code Apache-2.0, bundled MPFB2 data CC0 1.0).

    python3 vendor_from_wheel.py [path/to/anny-0.6.0-py3-none-any.whl]

Without an argument the wheel is fetched with `pip download anny==0.6.0 --no-deps`.
Only the files in FILES are extracted (the scripts in Art/Source/Blender/characters load
exactly these).  The wheel's SHA-256 is checked first.  Nothing is modified on extraction.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile

WHEEL_SHA256 = "050a0b24a3e7fdb89b46dc3581947ea84225305425ac9a1a97b65ea997fb2ad6"
PREFIX = "anny/data/mpfb2/"
FILES = [
    "LICENSE.md",
    "3dobjs/base.obj",
    "rigs/standard/rig.game_engine.json",
    "rigs/standard/weights.game_engine.json",
    "mesh_metadata/basemesh_vertex_groups.json",
    "mesh_metadata/hm08.mirror",
    # macro targets needed for gender 1.0, age 28 y (young/old mix), muscle 0.5..1.0,
    # weight 0.5, height 0.5, proportions 0.5, race 1/3 each
    "targets/macrodetails/universal-male-young-averagemuscle-averageweight.target.gz",
    "targets/macrodetails/universal-male-young-maxmuscle-averageweight.target.gz",
    "targets/macrodetails/universal-male-old-averagemuscle-averageweight.target.gz",
    "targets/macrodetails/universal-male-old-maxmuscle-averageweight.target.gz",
    "targets/macrodetails/african-male-young.target.gz",
    "targets/macrodetails/african-male-old.target.gz",
    "targets/macrodetails/asian-male-young.target.gz",
    "targets/macrodetails/asian-male-old.target.gz",
    "targets/macrodetails/caucasian-male-young.target.gz",
    "targets/macrodetails/caucasian-male-old.target.gz",
    # proportion (measure) targets used to rebalance upper arm / forearm
    "targets/arms/measure-upperarm-length-incr.target.gz",
    "targets/arms/measure-lowerarm-length-decr.target.gz",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) > 1:
        whl = sys.argv[1]
    else:
        tmp = tempfile.mkdtemp()
        subprocess.check_call([sys.executable, "-m", "pip", "download", "anny==0.6.0",
                               "--no-deps", "-d", tmp])
        whl = os.path.join(tmp, "anny-0.6.0-py3-none-any.whl")
    got = sha256(whl)
    if got != WHEEL_SHA256:
        raise SystemExit(f"wheel sha256 mismatch: {got}")
    with zipfile.ZipFile(whl) as z:
        for rel in FILES:
            dst = os.path.join(here, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(PREFIX + rel) as src, open(dst, "wb") as out:
                out.write(src.read())
            print(f"{sha256(dst)}  {rel}")


if __name__ == "__main__":
    main()
