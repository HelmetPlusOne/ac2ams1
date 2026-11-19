"""Convert AC textures into formats a DX11 renderer can actually create.

Assetto Corsa ships some textures in legacy D3D9 pixel formats: 24 bit RGB and
8 bit luminance-alpha. Neither exists in DX11, so rF2 cannot make a texture out
of them and dies when the renderer starts, with nothing written to the log.
Anything not already block compressed is re-encoded to BC3 with mipmaps.

AC also caps its mip chains at five levels whatever the texture size, so a
4096x1024 road stops at 256x64. Asked for anything smaller the hardware has to
clamp to that last level, which is what makes distant tarmac and terrain
sparkle. Those get rebuilt with a full chain, each in its own format.
"""
import os
import shutil
import struct
import argparse
import subprocess

from steam_paths import TEXCONV  # in whichever Steam library has rF2
from parallel import default_jobs, ordered_map
# AMS1 runs on DirectX 9 (gMotor 2.0), which requires DXT1/DXT3/DXT5 and
# power-of-two dimensions for mipmapped block-compressed textures.
BLOCK = (b"DXT1", b"DXT3", b"DXT5")
MAX_TEX_DIM = 4096

# Rebuilding a block compressed texture means decoding and recompressing it, so
# it is only worth doing in its own format: turning a normal map into BC3 would
# cost far more than the missing mips are worth.
SAME_FORMAT = {b"DXT1": "BC1_UNORM", b"DXT3": "BC2_UNORM", b"DXT5": "BC3_UNORM"}

# Below this a short chain costs nothing to look at and recompressing only adds
# error, so small masks and markers are left exactly as AC shipped them.
MIP_MIN = 128

# Building mips, texconv weights colour by alpha unless told to treat the two
# separately. AC stores plenty of opaque surfaces with a zero alpha channel, and
# without this their smaller mips come out black.


def is_pow2(n):
    return n >= 4 and (n & (n - 1)) == 0


def pow2_size(n, cap=MAX_TEX_DIM):
    """Next power of two >= max(4, n), capped at MAX_TEX_DIM for DX9."""
    n = max(4, int(n))
    return min(cap, 1 << (n - 1).bit_length())


def full_levels(w, h):
    """How many mip levels a texture of this size needs to reach 1x1."""
    return max(w, h).bit_length()


# AC loads whatever image is inside a .dds name; mod tracks ripped from other
# games often ship PNGs or JPEGs that way. rF2 reads only real DDS and draws
# the rest flat blue (ek_nagao: every texture is a PNG).
IMAGE_MAGIC = ((b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"),
               (b"BM", ".bmp"), (b"GIF8", ".gif"))


def image_kind(path):
    """The real extension of a non-DDS image hiding behind a .dds name."""
    with open(path, "rb") as f:
        head = f.read(8)
    for magic, ext in IMAGE_MAGIC:
        if head.startswith(magic):
            return ext
    return None


def describe(path):
    with open(path, "rb") as f:
        h = f.read(128)
    if len(h) < 128 or h[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", h, 12)
    fourcc = h[84:88]
    bpp = struct.unpack_from("<I", h, 88)[0]
    mips = struct.unpack_from("<I", h, 28)[0]
    return width, height, fourcc, bpp, mips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tex_dir")
    ap.add_argument("--texconv", default=TEXCONV)
    ap.add_argument("--format", default="BC3_UNORM",
                    help="format for textures DX11 cannot load at all")
    ap.add_argument("--keep-mips", action="store_true",
                    help="leave AC's truncated mip chains alone")
    ap.add_argument("--jobs", type=int, default=default_jobs(),
                    help="textures converted at the same time (1: one by one)")
    args = ap.parse_args()

    tex_dir = os.path.abspath(args.tex_dir)
    tmp = os.path.join(os.path.dirname(tex_dir.rstrip("\/")), "_converted")
    os.makedirs(tmp, exist_ok=True)

    todo = []
    for f in sorted(os.listdir(tex_dir)):
        if not f.lower().endswith(".dds"):
            continue
        info = describe(os.path.join(tex_dir, f))
        if info is None:
            kind = image_kind(os.path.join(tex_dir, f))
            if kind:
                todo.append((f, 0, 0, 0, args.format, kind[1:] + " named .dds"))
            else:
                print("skip (not dds): %s" % f)
            continue
        w, h, fourcc, bpp, mips = info
        bad_size = not is_pow2(w) or not is_pow2(h) or max(w, h) > MAX_TEX_DIM
        if min(w, h) < 4:
            todo.append((f, w, h, bpp, args.format, "under 4x4"))
        elif fourcc not in BLOCK:
            todo.append((f, w, h, bpp, args.format, "%dbpp" % bpp))
        elif bad_size:
            todo.append((f, w, h, bpp, SAME_FORMAT[fourcc],
                         "non-pow2 -> %dx%d" % (pow2_size(w), pow2_size(h))))
        elif (not args.keep_mips and fourcc in SAME_FORMAT
              and max(w, h) >= MIP_MIN and mips < full_levels(w, h)):
            todo.append((f, w, h, bpp, SAME_FORMAT[fourcc],
                         "%d of %d mips" % (mips, full_levels(w, h))))

    if not todo:
        print("nothing to convert")
        return

    print("re-encoding %d textures" % len(todo))

    def convert(job, work):
        """One texture; returns the line to print and whether it worked."""
        f, w, h, bpp, fmt, why = job
        src = f
        if why.endswith("named .dds"):
            # texconv picks its decoder by extension: give it the real one.
            src = os.path.join(work, os.path.splitext(f)[0] + "." + why.split()[0])
            shutil.copyfile(os.path.join(tex_dir, f), src)
        cmd = [args.texconv, "-f", fmt, "-m", "0", "-sepalpha", "-y", "-ft", "dds"]
        if w > 0 and h > 0 and (not is_pow2(w) or not is_pow2(h) or max(w, h) > MAX_TEX_DIM):
            cmd += ["-w", str(pow2_size(w)), "-h", str(pow2_size(h))]
        cmd += ["-o", work, src]
        r = subprocess.run(cmd, cwd=tex_dir, capture_output=True, text=True)
        out = None
        for cand in (f, os.path.splitext(f)[0] + ".DDS",
                     os.path.splitext(f)[0] + ".dds"):
            p = os.path.join(work, cand)
            if os.path.exists(p):
                out = p
                break
        # DX9/AMS1 requires power-of-two block-compressed textures (>= 4x4,
        # <= 4096). Images decoded from PNG/JPG-named .dds only reveal their
        # dimensions here, so resize if needed.
        got = describe(out) if out else None
        if r.returncode == 0 and got and (
                not is_pow2(got[0]) or not is_pow2(got[1])
                or max(got[0], got[1]) > MAX_TEX_DIM):
            tw, th = pow2_size(got[0]), pow2_size(got[1])
            r = subprocess.run(
                [args.texconv, "-f", fmt, "-m", "0", "-sepalpha", "-y", "-ft", "dds",
                 "-w", str(tw), "-h", str(th),
                 "-o", work, src], cwd=tex_dir, capture_output=True, text=True)
            why += ", resized to %dx%d" % (tw, th)
        if r.returncode != 0 or out is None:
            return False, "  FAILED %-28s %s" % (f, (r.stdout or r.stderr).strip()[-70:])
        shutil.move(out, os.path.join(tex_dir, f))
        return True, "  %-28s %dx%d %-14s -> %s" % (f, w, h, why, fmt)

    # Each texture is its own texconv run, so they go side by side.
    converted = failed = 0
    for ok, line in ordered_map(convert, todo, args.jobs, tmp):
        print(line)
        if ok:
            converted += 1
        else:
            failed += 1

    shutil.rmtree(tmp, ignore_errors=True)
    print("converted %d, failed %d" % (converted, failed))


if __name__ == "__main__":
    main()
