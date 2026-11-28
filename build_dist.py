"""Build a standalone Windows ``dist/`` bundle for AC-to-AMS1 conversion.

Recreates ``dist/`` from scratch with:
  - ``ac2ams1.exe`` (bundled Python runtime + NumPy + converter exposing
    ``build_track``, ``convert_multiple_tracks``, and drag-and-drop support)
  - ``ac2ams1.ini`` (default configuration, e.g. ``[track] texture_scale``)
  - ``README.md`` (usage instructions and list of bundled tools)
  - ``tools/blender/`` (portable Blender 3.6 LTS with ``io_rf2_gmt_release``
    pre-installed inside ``3.6/scripts/addons/``)
  - ``tools/blender_scripts/`` (``blender_stage.py``, ``kn5.py``, ``backdrop.py``, ``mesh_coarsen.py``)
  - ``tools/texconv/texconv.exe``
  - ``tools/rfactortools/`` (``rfactorcrypt.exe`` and its runtime files)
  - ``data/ac/system/data/surfaces.ini``
  - ``data/ams1/GameData/Locations/terrain.tdf``
  - ``data/ams1/GameData/Locations/sky/SRPL_SKY3_{DOME1,SUN1}.GMT``
  - ``out/`` (default automatic install destination for converted tracks, with ``readme.txt``)
  - ``work/`` (intermediate build workspace, with ``readme.txt``)

Usage:
    python build_dist.py [--dist <output dir>]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import steam_paths

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_NAME = "io_rf2_gmt_release"
SKY_ASSETS = ("SRPL_SKY3_DOME1.GMT", "SRPL_SKY3_SUN1.GMT")
BLENDER_SCRIPTS = ("blender_stage.py", "kn5.py", "backdrop.py", "mesh_coarsen.py")
HIDDEN_IMPORTS = (
    "ams_crypt",
    "backdrop",
    "bake_layers",
    "build_track",
    "check_setup",
    "convert_multiple_tracks",
    "convert_track",
    "finalize_track",
    "fix_textures",
    "gmt_rf1",
    "kn5",
    "make_aiw",
    "make_cam",
    "mesh_coarsen",
    "numpy",
    "parallel",
    "road_smooth",
    "steam_paths",
    "track_zip",
    "verify_install",
)


OUT_README = (
    "Converted Automobilista 1 tracks are installed here automatically.\n"
    "Copy any track folder from this directory into:\n"
    "  <Automobilista>\\GameData\\Locations\\\n"
)

WORK_README = (
    "Intermediate conversion files (extracted textures, baked layers, raw GMTs,\n"
    "AIW/CAM files, and extracted track zips) are stored here during builds.\n"
    "Subfolders here can be deleted safely after conversion, or kept to reuse\n"
    "exported geometry with --skip-geometry.\n"
)


def _program_files_dirs():
    out = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        val = os.environ.get(var)
        if val and os.path.isdir(val):
            out.append(val)
    return out


def find_blender_dir(explicit, fallback_dist=None):
    candidates = []
    if explicit:
        path = os.path.abspath(explicit)
        if os.path.isfile(path):
            path = os.path.dirname(path)
        return path
    env_b = os.environ.get("AC2AMS_BLENDER")
    if env_b:
        path = os.path.abspath(env_b)
        return os.path.dirname(path) if os.path.isfile(path) else path
    which_b = shutil.which("blender")
    if which_b:
        candidates.append(os.path.dirname(os.path.abspath(which_b)))
    for pf in _program_files_dirs():
        candidates.append(os.path.join(pf, "Blender Foundation", "Blender 3.6"))
    if fallback_dist:
        candidates.append(os.path.join(fallback_dist, "tools", "blender"))
    for path in candidates:
        if os.path.isfile(os.path.join(path, "blender.exe")):
            return path
    return candidates[0] if candidates else ""


def find_texconv(explicit, fallback_dist=None):
    if explicit:
        return os.path.abspath(explicit)
    env_t = os.environ.get("AC2AMS_TEXCONV")
    if env_t:
        return os.path.abspath(env_t)
    which_t = shutil.which("texconv")
    if which_t:
        return os.path.abspath(which_t)
    rf2_dir = os.environ.get("AC2AMS_RF2_DIR") or steam_paths.game_dir("rFactor 2")
    if rf2_dir:
        cand = os.path.join(rf2_dir, "Support", "Tools", "MapConverter", "texconv.exe")
        if os.path.isfile(cand):
            return cand
    if fallback_dist:
        cand = os.path.join(fallback_dist, "tools", "texconv", "texconv.exe")
        if os.path.isfile(cand):
            return cand
    return ""


def find_ac_dir(explicit, fallback_dist=None):
    if explicit:
        return os.path.abspath(explicit)
    env_ac = os.environ.get("AC2AMS_AC_DIR")
    if env_ac:
        return os.path.abspath(env_ac)
    cand = steam_paths.game_dir("assettocorsa")
    if cand and os.path.isfile(os.path.join(cand, "system", "data", "surfaces.ini")):
        return cand
    if fallback_dist:
        fb = os.path.join(fallback_dist, "data", "ac")
        if os.path.isfile(os.path.join(fb, "system", "data", "surfaces.ini")):
            return fb
    return cand


def find_ams_dir(explicit, fallback_dist=None):
    if explicit:
        return os.path.abspath(explicit)
    env_ams = os.environ.get("AC2AMS_GAME_DIR")
    if env_ams:
        return os.path.abspath(env_ams)
    cand = steam_paths.game_dir("Automobilista")
    if cand and os.path.isfile(os.path.join(cand, "GameData", "Locations", "terrain.tdf")):
        return cand
    if fallback_dist:
        fb = os.path.join(fallback_dist, "data", "ams1")
        if os.path.isfile(os.path.join(fb, "GameData", "Locations", "terrain.tdf")):
            return fb
    return cand


def find_addon_dir(blender_dir, explicit):
    candidates = []
    if explicit:
        candidates.append(os.path.abspath(explicit))
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(
            os.path.join(appdata, "Blender Foundation", "Blender", "3.6",
                         "scripts", "addons", ADDON_NAME)
        )
    candidates.append(
        os.path.join(blender_dir, "3.6", "scripts", "addons", ADDON_NAME)
    )
    for path in candidates:
        if os.path.isdir(path):
            return path
    raise FileNotFoundError(
        "Blender add-on %s not found; checked: %s" % (ADDON_NAME, ", ".join(candidates))
    )


def find_rfactortools_dir(explicit, fallback_dist=None):
    if explicit:
        path = os.path.abspath(explicit)
        if os.path.isfile(path):
            path = os.path.dirname(path)
        return path
    env_enc = os.environ.get("AC2AMS_ENCRYPTOR")
    if env_enc:
        path = os.path.abspath(env_enc)
        return os.path.dirname(path) if os.path.isfile(path) else path
    for name in ("rfactorcrypt", "rft-rfactorcrypt"):
        found = shutil.which(name)
        if found:
            return os.path.dirname(os.path.abspath(found))
    if fallback_dist:
        cand = os.path.join(fallback_dist, "tools", "rfactortools")
        if os.path.isfile(os.path.join(cand, "rfactorcrypt.exe")):
            return cand
    return ""


def find_sky_assets(locations_dir):
    found = {}
    wanted = {name.lower(): name for name in SKY_ASSETS}
    if os.path.isdir(locations_dir):
        for entry in sorted(os.listdir(locations_dir)):
            folder = os.path.join(locations_dir, entry)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                key = name.lower()
                if key in wanted and wanted[key] not in found:
                    src = os.path.join(folder, name)
                    if os.path.isfile(src):
                        found[wanted[key]] = src
            if len(found) == len(SKY_ASSETS):
                break
    missing = [name for name in SKY_ASSETS if name not in found]
    if missing:
        raise FileNotFoundError(
            "AMS1 skybox asset(s) not found under %s: %s"
            % (locations_dir, ", ".join(missing))
        )
    return found


def _ignore_blender(_dirpath, names):
    skip = set()
    for name in names:
        low = name.lower()
        if low == "blender.pdb" or low == "__pycache__":
            skip.add(name)
    return skip


def _ignore_pycache(_dirpath, names):
    return {n for n in names if n == "__pycache__"}


def dir_size_mb(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024.0 * 1024.0)


def build_exe(dist_dir):
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is required to build ac2ams1.exe. "
            "Install it with: python -m pip install pyinstaller"
        ) from exc

    cli_script = os.path.join(HERE, "ac2ams1.py")
    with tempfile.TemporaryDirectory(prefix="ac2ams1-pyi-") as tmp:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name", "ac2ams1",
            "--distpath", dist_dir,
            "--workpath", os.path.join(tmp, "build"),
            "--specpath", tmp,
            "--paths", HERE,
        ]
        for mod in HIDDEN_IMPORTS:
            cmd.extend(["--hidden-import", mod])
        cmd.append(cli_script)
        print("Building ac2ams1.exe with PyInstaller...", flush=True)
        result = subprocess.run(cmd, cwd=HERE)
        if result.returncode != 0:
            raise SystemExit("PyInstaller failed with exit code %d" % result.returncode)

    exe_path = os.path.join(dist_dir, "ac2ams1.exe")
    if not os.path.isfile(exe_path):
        raise SystemExit("PyInstaller did not produce %s" % exe_path)
    return exe_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", default=os.path.join(HERE, "dist"),
                    help="output distribution directory (default: ./dist)")
    ap.add_argument("--blender", default=None,
                    help="path to Blender folder or blender.exe")
    ap.add_argument("--addon", default=None,
                    help="path to io_rf2_gmt_release addon folder")
    ap.add_argument("--texconv", default=None,
                    help="path to texconv.exe")
    ap.add_argument("--rfactortools", default=None,
                    help="path to rfactortools folder or rfactorcrypt.exe")
    ap.add_argument("--ac", default=None,
                    help="Assetto Corsa folder containing system\\data\\surfaces.ini")
    ap.add_argument("--ams", default=None,
                    help="Automobilista folder containing GameData\\Locations")
    args = ap.parse_args(argv)

    dist_dir = os.path.abspath(args.dist)

    # Reuse an existing ./dist bundle as fallback source only when building
    # into a different target directory.
    default_dist = os.path.abspath(os.path.join(HERE, "dist"))
    fallback_dist = (
        default_dist
        if os.path.isdir(default_dist)
        and os.path.normcase(dist_dir) != os.path.normcase(default_dist)
        else None
    )

    blender_src = find_blender_dir(args.blender, fallback_dist=fallback_dist)
    addon_src = find_addon_dir(blender_src, args.addon) if blender_src else ""
    texconv_src = find_texconv(args.texconv, fallback_dist=fallback_dist)
    rfactortools_src = find_rfactortools_dir(args.rfactortools, fallback_dist=fallback_dist)
    ac_dir = find_ac_dir(args.ac, fallback_dist=fallback_dist)
    ams_dir = find_ams_dir(args.ams, fallback_dist=fallback_dist)

    surfaces_src = os.path.join(ac_dir, "system", "data", "surfaces.ini") if ac_dir else ""
    locations_src = os.path.join(ams_dir, "GameData", "Locations") if ams_dir else ""
    terrain_src = os.path.join(locations_src, "terrain.tdf") if locations_src else ""

    for label, path, check, hint in (
        ("Blender", os.path.join(blender_src, "blender.exe") if blender_src else "", os.path.isfile, "--blender"),
        ("Blender addon", addon_src, os.path.isdir, "--addon"),
        ("texconv.exe", texconv_src, os.path.isfile, "--texconv"),
        ("rfactorcrypt.exe", os.path.join(rfactortools_src, "rfactorcrypt.exe") if rfactortools_src else "", os.path.isfile, "--rfactortools"),
        ("AC surfaces.ini", surfaces_src, os.path.isfile, "--ac"),
        ("AMS1 terrain.tdf", terrain_src, os.path.isfile, "--ams"),
    ):
        if not path or not check(path):
            raise SystemExit(
                "Required source missing (%s): %s (pass %s)"
                % (label, path or "<not found>", hint)
            )

    sky_sources = find_sky_assets(locations_src)

    print("Recreating %s ..." % dist_dir, flush=True)
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir, exist_ok=True)

    # 1. Copy Blender + embed io_rf2_gmt_release directly in Blender's addons folder.
    blender_dst = os.path.join(dist_dir, "tools", "blender")
    print("Copying Blender -> %s ..." % blender_dst, flush=True)
    shutil.copytree(blender_src, blender_dst, ignore=_ignore_blender)
    addon_dst = os.path.join(blender_dst, "3.6", "scripts", "addons", ADDON_NAME)
    if os.path.exists(addon_dst):
        shutil.rmtree(addon_dst)
    print("Copying %s -> %s ..." % (ADDON_NAME, addon_dst), flush=True)
    shutil.copytree(addon_src, addon_dst, ignore=_ignore_pycache)

    # 2. Copy plain scripts executed inside Blender's own Python runtime.
    scripts_dst = os.path.join(dist_dir, "tools", "blender_scripts")
    os.makedirs(scripts_dst, exist_ok=True)
    for script in BLENDER_SCRIPTS:
        shutil.copy2(os.path.join(HERE, script), os.path.join(scripts_dst, script))

    # 3. Copy texconv.exe.
    texconv_dst = os.path.join(dist_dir, "tools", "texconv")
    os.makedirs(texconv_dst, exist_ok=True)
    shutil.copy2(texconv_src, os.path.join(texconv_dst, "texconv.exe"))

    # 4. Copy rfactortools (rfactorcrypt.exe + bundled Python 3.3 runtime).
    rft_dst = os.path.join(dist_dir, "tools", "rfactortools")
    print("Copying rfactortools -> %s ..." % rft_dst, flush=True)
    shutil.copytree(rfactortools_src, rft_dst, ignore=_ignore_pycache)

    # 5. Copy standalone template data from AC and AMS1.
    ac_data_dst = os.path.join(dist_dir, "data", "ac", "system", "data")
    ams_loc_dst = os.path.join(dist_dir, "data", "ams1", "GameData", "Locations")
    ams_sky_dst = os.path.join(ams_loc_dst, "sky")
    os.makedirs(ac_data_dst, exist_ok=True)
    os.makedirs(ams_sky_dst, exist_ok=True)
    shutil.copy2(surfaces_src, os.path.join(ac_data_dst, "surfaces.ini"))
    shutil.copy2(terrain_src, os.path.join(ams_loc_dst, "terrain.tdf"))
    for asset_name, asset_path in sky_sources.items():
        shutil.copy2(asset_path, os.path.join(ams_sky_dst, asset_name))

    # 6. Copy standalone README.md, ac2ams1.ini, and create out/ and work/ with readme.txt.
    dist_readme = os.path.join(HERE, "DIST_README.md")
    if not os.path.isfile(dist_readme):
        raise SystemExit("Required source missing (DIST_README.md): %s" % dist_readme)
    shutil.copy2(dist_readme, os.path.join(dist_dir, "README.md"))

    ini_src = os.path.join(HERE, steam_paths.INI_NAME)
    if not os.path.isfile(ini_src):
        raise SystemExit("Required source missing (%s): %s" % (steam_paths.INI_NAME, ini_src))
    shutil.copy2(ini_src, os.path.join(dist_dir, steam_paths.INI_NAME))

    out_dir = os.path.join(dist_dir, "out")
    work_dir = os.path.join(dist_dir, "work")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    with open(os.path.join(out_dir, "readme.txt"), "w", encoding="utf-8") as f:
        f.write(OUT_README)
    with open(os.path.join(work_dir, "readme.txt"), "w", encoding="utf-8") as f:
        f.write(WORK_README)

    # 7. Bundle Python runtime + converter CLI into dist/ac2ams1.exe.
    exe_path = build_exe(dist_dir)

    print("\nStandalone distribution ready: %s" % dist_dir)
    print("  executable:         %s (%.1f MB)" % (
        os.path.relpath(exe_path, dist_dir),
        os.path.getsize(exe_path) / (1024.0 * 1024.0),
    ))
    print("  documentation:      README.md")
    print("  tools/blender:      %.1f MB (with %s)" % (dir_size_mb(blender_dst), ADDON_NAME))
    print("  tools/rfactortools: %.1f MB" % dir_size_mb(rft_dst))
    print("  tools/texconv:      %.1f MB" % dir_size_mb(texconv_dst))
    print("  total size:         %.1f MB" % dir_size_mb(dist_dir))
    print("\nUsage:")
    print("  Drag and drop an AC track folder onto %s" % exe_path)
    print("  %s build_track \"<AC track folder or zip>\"" % exe_path)
    print("  %s convert_multiple_tracks \"<tracks.txt>\"" % exe_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
