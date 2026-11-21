"""Assemble an Automobilista 1 track from the converted parts.

AMS1 uses loose encrypted GMT and DDS files beside a layout folder:

  Locations/<venue>/
      <venue>.tdf
      gmt/*.gmt
      maps/*.dds
      <layout>/
          <layout>.scn  .gdb  .AIW  .cam

The scene file is rebuilt from the gmt files that were actually exported rather
than from the pre-export plan.
"""
import os
import json
import shutil
import argparse
import hashlib
import re
import struct
import subprocess
import tempfile

SCN_HEADER = """CUBEASF
// {venue}, converted from Assetto Corsa

SearchPath=.
SearchPath=ReizaCommon
SearchPath=ReizaCommon\\bak
SearchPath={venue}
SearchPath={venue}\\{layout}
SearchPath={venue}\\gmt
SearchPath={venue}\\maps

{mas_files}
MASFile=CloudsDefault.MAS
MASFile=SkyEuro.MAS
MASFile=COMMONMAPS.MAS

View=mainview
{{
  Clear=True
  Color=(145, 185, 230)
  Size=(1.00, 1.00) Center=(0.5, 0.5)
  FOV=(77.75, 31.25)
  ClipPlanes=(0.05, 5000.00)
  View=rearview
  {{
    Clear=True
    Color=(145, 185, 230)
    Size=(1024.00, 64.00) Center=(512, 32.00)
    FOV=(77.75, 31.25)
    ClipPlanes=(0.30, 500.00)
  }}
}}

GroupMethod=Dynamic
MaxShadowRange(500.00)
AmbientColor=({amb}, {amb}, {amb})
FogMode=LINEAR FogIn=(50.00) FogOut=(5000.00) FogDensity=(0.30) FogColor=(205, 215, 235)

Light=FDirect01
{{
 Type=Directional Pos=(0.0,25000.0,0.0) Dir=({sx:.3f}, {sy:.3f}, {sz:.3f}) Intensity=(1.0) Color=({sun}, {sun}, {sun})
}}

{skybox}
"""

GDB = """{layout}
{{
  Filter Properties = * StockV8
  Attrition = 30
  Max Vehicles = 32
  TrackName = {venue}
  EventName = {venue}
  GrandPrixName = {venue}
  VenueName = {venue}
  Location = converted from Assetto Corsa
  Length = {km:.3f} KM / {mi:.2f} Miles
  TrackType = Permanent Road Course
  TerrainDataFile = ..\{venue}.tdf
  HeadlightsRequired = false
  FormationAndStart = 0
  GarageDepth = 3.5
  NumStartingLights = 2
  RaceLaps = 10
  RacePitKPH = 60
  NormalPitKPH = 60

  SkyBlendSunAngles=(-20.0,-5.0,10.0,25.0)
  ShadowMinSunAngle=15.0

  // Sun high overhead. Change these to move the sun.
  TestDayStart = {hour}
  Practice1Start = {hour}
  Practice2Start = {hour}
  Practice3Start = {hour}
  QualifyStart = {hour}
  WarmupStart = {hour}
  RaceStart = {hour}

  Latitude = -25.0
  NorthDirection = 0
  Altitude = 0
  RaceDate = March 17

  SunriseAmbientRGB = (150,150,175)
  SunriseDirectionalRGB = (180,155,145)
  SunriseFogRGB = (113,123,152)
  SunriseFogIn = (0)
  SunriseFogOut = (1000)

  DayAmbientRGB = (165,165,170)
  DayDirectionalRGB = (255,250,240)
  DayFogRGB = (185,211,243)
  DayFogIn = (250)
  DayFogOut = (4000)

  SunsetAmbientRGB = (171,172,190)
  SunsetDirectionalRGB = (223,157,117)
  SunsetFogRGB = (90,85,50)
  SunsetFogIn = (0)
  SunsetFogOut = (1000)

  NightAmbientRGB = (22,30,42)
  NightDirectionalRGB = (10,10,16)
  NightFogRGB = (15,12,10)
  NightFogIn = (0)
  NightFogOut = (750)

  SettingsFolder = {venue}
}}
"""


# Where the light travels, from AC's own sun for the track. Falls back to the
# direction we used before when a track says nothing.
FALLBACK_SUN = (0.25, -0.95, 0.18)
MAX_LAYOUT_ID_LENGTH = 16


def layout_identifier(venue):
    """Keep generated AMS filenames below the measured 23-character SCN limit."""
    if len(venue) <= MAX_LAYOUT_ID_LENGTH:
        return venue
    prefix = re.sub(r"[^A-Za-z0-9]", "", venue)[:7].lower() or "track"
    suffix = hashlib.sha1(venue.casefold().encode("utf-8")).hexdigest()[:8]
    return "%s_%s" % (prefix, suffix)


def install_location(stage, locations, venue):
    dest = os.path.join(locations, venue)
    os.makedirs(locations, exist_ok=True)
    if os.path.isdir(dest) and not os.listdir(dest):
        shutil.copytree(stage, dest, dirs_exist_ok=True)
        return dest

    swap_root = tempfile.mkdtemp(prefix=".ac2ams-install-", dir=locations)
    candidate = os.path.join(swap_root, venue)
    previous = os.path.join(swap_root, "previous")
    previous_saved = False
    try:
        shutil.copytree(stage, candidate)
        if os.path.exists(dest):
            os.replace(dest, previous)
            previous_saved = True
        try:
            os.replace(candidate, dest)
        except OSError as install_error:
            if previous_saved:
                try:
                    os.replace(previous, dest)
                    previous_saved = False
                except OSError as restore_error:
                    raise RuntimeError(
                        "installation failed and the previous location could "
                        "not be restored; its backup is at %s: %s"
                        % (previous, restore_error)) from install_error
            raise
        if previous_saved:
            try:
                shutil.rmtree(previous)
                previous_saved = False
            except OSError as exc:
                print("installed, but could not remove previous location "
                      "backup %s: %s" % (previous, exc))
        return dest
    finally:
        if not previous_saved:
            try:
                shutil.rmtree(swap_root)
            except OSError as exc:
                print("could not clean temporary install folder %s: %s"
                      % (swap_root, exc))


def sun_direction(out_dir):
    """Turn AC's sun pitch and heading into an AMS light direction.

    Pitch is degrees above the horizon, heading degrees around it. AMS wants
    the direction the light travels, so everything points down and away. The
    X sign carries the AC to AMS mirror; if a track ends up lit from the wrong
    side, that is the term to flip.
    """
    import math
    path = os.path.join(out_dir, "material_map.json")
    lit = {}
    if os.path.exists(path):
        with open(path) as f:
            lit = json.load(f).get("lighting") or {}
    if "sun_pitch_angle" not in lit:
        return FALLBACK_SUN
    pitch = math.radians(float(lit["sun_pitch_angle"]))
    heading = math.radians(float(lit.get("sun_heading_angle", 0.0)))
    flat = math.cos(pitch)
    return (flat * math.sin(heading), -math.sin(pitch), -flat * math.cos(heading))


def shadow_caster(row, cutouts):
    """How this mesh casts a shadow in AMS, or None.

    Nothing did. The scene never named a caster, so roofs left the stand
    seating in full sun, trees left no shade on the grass and rocks none on
    themselves: a good part of every "too bright" report, where AC (and CSP,
    which turns casting on for more) shades them. Studio 397's Loch Drummond
    marks 385 instances (Static, Solid), or (Static, Texture) for cut-outs so
    the leaves cast and the cards around them do not.

    AC's own per-mesh flag decides. Left out: what is not drawn, blended
    surfaces and backdrops (AMS casts the whole card), decals, and flat
    ground, which official tracks give a separate shadow object if anything
    and which would only shade itself.
    """
    if not row.get("render", True) or not row.get("cast_shadows"):
        return None
    if row.get("decal") or row.get("backdrop"):
        return None
    if row.get("needs_blend") and not row.get("alpha_test"):
        return None
    if float(row.get("upward", 0.0)) >= 0.9:
        return None
    if row.get("alpha_test"):
        return "Texture" if row["rf2_material"] in cutouts else None
    return "Solid"


LOADING_SIZE = (1920, 1080)
LOADING_FIT = (1536, 820)
MINI_SIZE = (252, 249)
MINI_FIT = (216, 213)
MAX_DECODE_DIM = 2048


def _png_dimensions(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return struct.unpack_from(">II", head, 16)
    return None


def _run_texconv(command, description):
    result = subprocess.run(
        command, capture_output=True, text=True, errors="replace"
    )
    if result.returncode:
        details = (result.stdout or "") + (result.stderr or "")
        raise RuntimeError("texconv failed %s:\n%s" % (description, details[-2000:]))


def _read_tga_bgra(path):
    import numpy as np

    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 18:
        raise RuntimeError("truncated TGA image: %s" % path)
    id_len = data[0]
    img_type = data[2]
    width, height = struct.unpack_from("<HH", data, 12)
    bpp = data[16]
    descriptor = data[17]
    if img_type != 2 or bpp not in (24, 32) or not width or not height:
        raise RuntimeError(
            "unsupported TGA format in %s (type=%d, bpp=%d, %dx%d)"
            % (path, img_type, bpp, width, height)
        )
    channels = bpp // 8
    start = 18 + id_len
    need = width * height * channels
    if len(data) < start + need:
        raise RuntimeError("truncated TGA pixel data: %s" % path)
    pixels = np.frombuffer(
        data, dtype=np.uint8, count=need, offset=start
    ).reshape(height, width, channels)
    if (descriptor & 0x20) == 0:
        pixels = pixels[::-1]
    if channels == 3:
        bgra = np.empty((height, width, 4), dtype=np.uint8)
        bgra[:, :, :3] = pixels
        bgra[:, :, 3] = 255
        return bgra
    return pixels.copy()


def _write_tga_bgra(path, bgra, bottom_up=True):
    import numpy as np

    height, width, channels = bgra.shape
    if channels != 4:
        raise ValueError("expected 4-channel BGRA image, got %d" % channels)
    descriptor = 8 if bottom_up else 40
    header = struct.pack(
        "<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, width, height, 32, descriptor
    )
    body = bgra[::-1] if bottom_up else bgra
    with open(path, "wb") as f:
        f.write(header)
        f.write(np.ascontiguousarray(body, dtype=np.uint8).tobytes())


def _dilate_track(bgra, radius):
    """Slightly thicken thin transparent track maps so they survive downscaling."""
    import numpy as np

    if radius <= 0:
        return bgra
    out = bgra.copy()
    height, width, _ = bgra.shape
    for _ in range(radius):
        padded = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        best = out.copy()
        best_score = (
            best[:, :, 3].astype(np.int32) * 768
            + best[:, :, 0].astype(np.int32)
            + best[:, :, 1].astype(np.int32)
            + best[:, :, 2].astype(np.int32)
        )
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                nb = padded[1 + dy:1 + dy + height, 1 + dx:1 + dx + width]
                nb_score = (
                    nb[:, :, 3].astype(np.int32) * 768
                    + nb[:, :, 0].astype(np.int32)
                    + nb[:, :, 1].astype(np.int32)
                    + nb[:, :, 2].astype(np.int32)
                )
                mask = nb_score > best_score
                best[mask] = nb[mask]
                best_score[mask] = nb_score[mask]
        out = best
    return out


def _resize_tga_bgra(bgra, width, height, texconv, temp_dir, tag):
    src_path = os.path.join(temp_dir, tag + "_src.tga")
    out_dir = os.path.join(temp_dir, tag + "_out")
    os.makedirs(out_dir, exist_ok=True)
    _write_tga_bgra(src_path, bgra, bottom_up=False)
    _run_texconv(
        [texconv, "-y", "-ft", "tga", "-f", "B8G8R8A8_UNORM",
         "-w", str(width), "-h", str(height), "-o", out_dir, src_path],
        "resizing %s" % tag,
    )
    resized_path = os.path.join(out_dir, tag + "_src.TGA")
    if not os.path.isfile(resized_path):
        raise RuntimeError("texconv did not produce %s" % resized_path)
    return _read_tga_bgra(resized_path)


def _loading_background(width=LOADING_SIZE[0], height=LOADING_SIZE[1]):
    """Dark charcoal radial-gradient canvas matching AMS1's loading screen style."""
    import numpy as np

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dist = np.sqrt(
        ((xx - width * 0.5) / (width * 0.55)) ** 2
        + ((yy - height * 0.5) / (height * 0.65)) ** 2
    )
    val = np.clip(32.0 - 22.0 * np.clip(dist, 0.0, 1.0), 10.0, 32.0).astype(np.uint8)
    canvas = np.empty((height, width, 4), dtype=np.uint8)
    canvas[:, :, 0] = val
    canvas[:, :, 1] = val
    canvas[:, :, 2] = val
    canvas[:, :, 3] = 255
    return canvas


def stage_menu_images(preview, layout_dir, layout, texconv):
    """Create the 252x249 TGA minimap and 1920x1080 JPEG loading screen for AMS.

    Preserves the aspect ratio of AC track maps (``map.png`` / ``outline.png``)
    and previews, crops transparent borders, composites onto an AMS1-style dark
    16:9 canvas for ``<layout>_loading.jpg``, and keeps transparency for
    ``<layout>mini.tga``.
    """
    import numpy as np

    if not preview:
        return 0
    if not os.path.isfile(preview):
        raise FileNotFoundError("track preview image not found: %s" % preview)

    with tempfile.TemporaryDirectory() as temp_dir:
        decode_cmd = [texconv, "-y", "-ft", "tga", "-f", "B8G8R8A8_UNORM"]
        dims = _png_dimensions(preview)
        if dims and max(dims) > MAX_DECODE_DIM:
            scale = MAX_DECODE_DIM / float(max(dims))
            decode_cmd += [
                "-w", str(max(1, int(round(dims[0] * scale)))),
                "-h", str(max(1, int(round(dims[1] * scale)))),
            ]
        decode_cmd += ["-o", temp_dir, preview]
        _run_texconv(decode_cmd, "decoding %s" % os.path.basename(preview))

        decoded = os.path.join(
            temp_dir, os.path.splitext(os.path.basename(preview))[0] + ".TGA"
        )
        if not os.path.isfile(decoded):
            raise RuntimeError("texconv did not produce %s" % decoded)

        bgra = _read_tga_bgra(decoded)
        alpha = bgra[:, :, 3]
        has_alpha = bool((alpha < 250).any() and (alpha > 16).any())
        if has_alpha:
            ys, xs = np.where(alpha > 8)
            if len(xs):
                bgra = bgra[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
            visible = bgra[bgra[:, :, 3] > 32]
            if len(visible):
                luma = (
                    0.114 * visible[:, 0]
                    + 0.587 * visible[:, 1]
                    + 0.299 * visible[:, 2]
                )
                if np.percentile(luma, 90) < 40.0:
                    bgra[:, :, :3] = 255 - bgra[:, :, :3]

        src_h, src_w = bgra.shape[:2]

        # 1. Loading screen: 1920x1080 JPEG on dark charcoal background.
        load_w, load_h = LOADING_SIZE
        fit_w, fit_h = LOADING_FIT
        load_scale = min(fit_w / float(src_w), fit_h / float(src_h))
        dst_w = max(1, int(round(src_w * load_scale)))
        dst_h = max(1, int(round(src_h * load_scale)))
        load_src = bgra
        if has_alpha and load_scale < 0.6:
            radius = min(3, max(1, int(round(0.7 / load_scale)) // 2))
            load_src = _dilate_track(bgra, radius)
        load_resized = _resize_tga_bgra(
            load_src, dst_w, dst_h, texconv, temp_dir, "loading"
        )
        canvas = _loading_background(load_w, load_h)
        x0 = (load_w - dst_w) // 2
        y0 = (load_h - dst_h) // 2
        if has_alpha:
            a = load_resized[:, :, 3:4].astype(np.float32) / 255.0
            bg = canvas[y0:y0 + dst_h, x0:x0 + dst_w, :3].astype(np.float32)
            fg = load_resized[:, :, :3].astype(np.float32)
            canvas[y0:y0 + dst_h, x0:x0 + dst_w, :3] = np.clip(
                fg * a + bg * (1.0 - a), 0.0, 255.0
            ).astype(np.uint8)
        else:
            canvas[y0:y0 + dst_h, x0:x0 + dst_w, :3] = load_resized[:, :, :3]

        load_tga = os.path.join(temp_dir, "loading_canvas.tga")
        _write_tga_bgra(load_tga, canvas, bottom_up=False)
        _run_texconv(
            [texconv, "-y", "-ft", "jpg", "-wicq", "0.92", "-o", temp_dir, load_tga],
            "creating %s_loading.jpg" % layout,
        )
        load_jpg = os.path.join(temp_dir, "loading_canvas.JPG")
        if not os.path.isfile(load_jpg):
            raise RuntimeError("texconv did not produce %s" % load_jpg)
        shutil.copy2(load_jpg, os.path.join(layout_dir, layout + "_loading.jpg"))

        # 2. Menu minimap: 252x249 32-bit bottom-up uncompressed TGA matching stock AMS1.
        mini_w, mini_h = MINI_SIZE
        mfit_w, mfit_h = MINI_FIT
        mini_scale = min(mfit_w / float(src_w), mfit_h / float(src_h))
        mdst_w = max(1, int(round(src_w * mini_scale)))
        mdst_h = max(1, int(round(src_h * mini_scale)))
        mini_src = bgra
        if has_alpha and mini_scale < 0.5:
            radius = min(4, max(1, int(round(1.0 / (mini_scale * 2.5)))))
            mini_src = _dilate_track(bgra, radius)
        mini_resized = _resize_tga_bgra(
            mini_src, mdst_w, mdst_h, texconv, temp_dir, "mini"
        )
        mini_canvas = np.zeros((mini_h, mini_w, 4), dtype=np.uint8)
        mx0 = (mini_w - mdst_w) // 2
        my0 = (mini_h - mdst_h) // 2
        mini_canvas[my0:my0 + mdst_h, mx0:mx0 + mdst_w] = mini_resized
        _write_tga_bgra(
            os.path.join(layout_dir, layout + "mini.tga"),
            mini_canvas,
            bottom_up=True,
        )
    return 2


def stage_mas_archives(source_dir, stage_dir, venue):
    names = (venue + ".mas", venue + "MAP.mas")
    sources = [os.path.join(source_dir, name) for name in names]
    present = [os.path.isfile(path) for path in sources]
    if any(present) and not all(present):
        raise RuntimeError("both %s and %s are required for MAS packaging" % names)
    if not all(present):
        return ""
    for source, name in zip(sources, names):
        shutil.copy2(source, os.path.join(stage_dir, name))
    return "\n".join("MASFile=" + name for name in
                     (venue + ".MAS", venue + "MAP.MAS"))


SKY_ASSETS = (
    "SRPL_SKY3_DOME1.GMT",
    "SRPL_SKY3_SUN1.GMT",
)


def stage_skybox(stage_dir, locations, venue):
    """Stage AMS1's required skyboxi / CLOUDS / Sky hierarchy.

    Every stock AMS1 scene defines Instance=skyboxi; without it AMS1 crashes
    dereferencing a null Instance pointer on the first render frame and leaves
    daytime lighting at midnight black.
    """
    import gmt_rf1

    with open(os.path.join(stage_dir, "skyboxi.gmt"), "wb") as f:
        f.write(gmt_rf1.make_minimal_rf1_gmt("skyboxi", "_invisible.dds"))

    import steam_paths

    found = {}
    search_roots = []
    for root in (locations, steam_paths.LOCATIONS):
        if root and os.path.isdir(root):
            norm = os.path.normcase(os.path.abspath(root))
            if norm not in {os.path.normcase(os.path.abspath(r)) for r in search_roots}:
                search_roots.append(root)

    wanted = {name.lower(): name for name in SKY_ASSETS}
    for root in search_roots:
        for entry in sorted(os.listdir(root)):
            if entry.casefold() == venue.casefold():
                continue
            folder = os.path.join(root, entry)
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
        if len(found) == len(SKY_ASSETS):
            break

    sky_meshes = []
    for asset in SKY_ASSETS:
        src = found.get(asset)
        if src:
            shutil.copy2(src, os.path.join(stage_dir, asset))
            sky_meshes.append(
                "      MeshFile=%s CollTarget=False HATTarget=False ShadowReceiver=False"
                % asset
            )

    if not sky_meshes:
        sky_meshes.append(
            "      MeshFile=skyboxi.gmt CollTarget=False HATTarget=False Render=False"
        )

    return (
        "Instance=skyboxi\n"
        "{\n"
        "  Moveable=True\n"
        "  MeshFile=skyboxi.gmt CollTarget=False HATTarget=False Render=False\n"
        "  Instance=CLOUDS\n"
        "  {\n"
        "    Moveable=True\n"
        "    MeshFile=skyboxi.gmt CollTarget=False HATTarget=False Render=False\n"
        "    Instance=Sky\n"
        "    {\n"
        "      Moveable=True\n"
        + "\n".join(sky_meshes) + "\n"
        "    }\n"
        "  }\n"
        "}\n"
    )


def _pit_gate_corners(pos, perp, half_width=8.0, height=8.0):
    x, y, z = pos
    px, _py, pz = perp
    plen = (px * px + pz * pz) ** 0.5 or 1.0
    px, pz = px / plen, pz / plen
    y0 = y - 1.0
    y1 = y + height
    return (
        (x - px * half_width, y0, z - pz * half_width),
        (x + px * half_width, y0, z + pz * half_width),
        (x + px * half_width, y1, z + pz * half_width),
        (x - px * half_width, y1, z - pz * half_width),
    )


def stage_pit_gates(stage_dir, aiw_path):
    """Stage AMS1's required xpitin.gmt and xpitout.gmt trigger gates.

    All 77 stock AMS1 tracks define Instance=xpitin and Instance=xpitout;
    without them AMS1 logs 'No pit-in/pit-out poly found' and crashes when
    spawning vehicles in the garage/pitlane.
    """
    import gmt_rf1

    pit_wps = []
    if aiw_path and os.path.isfile(aiw_path):
        with open(aiw_path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        blocks = txt.split("wp_pos=")[1:]
        for blk in blocks:
            if "wp_branchID=(1)" not in blk:
                continue
            pm = re.match(r"\(([-\d.]+),([-\d.]+),([-\d.]+)\)", blk)
            rm = re.search(r"wp_perp=\(([-\d.]+),([-\d.]+),([-\d.]+)\)", blk)
            if pm and rm:
                pos = tuple(float(v) for v in pm.groups())
                perp = tuple(float(v) for v in rm.groups())
                pit_wps.append((pos, perp))

    if len(pit_wps) >= 2:
        in_pos, in_perp = pit_wps[0]
        out_pos, out_perp = pit_wps[-1]
    elif pit_wps:
        in_pos, in_perp = pit_wps[0]
        out_pos, out_perp = pit_wps[0]
    else:
        in_pos, in_perp = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
        out_pos, out_perp = (0.0, 0.0, 10.0), (1.0, 0.0, 0.0)

    blocks = []
    for name, pos, perp in (("xpitin", in_pos, in_perp),
                            ("xpitout", out_pos, out_perp)):
        corners = _pit_gate_corners(pos, perp)
        with open(os.path.join(stage_dir, name + ".gmt"), "wb") as f:
            f.write(gmt_rf1.make_quad_rf1_gmt(name, corners, "_invisible.dds"))
        blocks.append(
            "Instance=%s\n"
            "{\n"
            "  Render=False Change=False VisGroups=(32)\n"
            "  MeshFile=%s.gmt CollTarget=True HATTarget=False\n"
            "  Response=VEHICLE,PITSTOP\n"
            "}\n" % (name, name)
        )
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", help="out/<track> from convert_track.py")
    ap.add_argument("--minimal", action="store_true",
                    help="diagnostic: only collidable meshes, no scenery")
    # Measured against AC the ground ran between 0.65 and 0.92 of its
    # brightness, so both go up. The sun goes up further than the ambient:
    # lifting the two together flattens a scene, and AC's is the crisper of
    # the two, not merely the brighter.
    ap.add_argument("--ambient", type=int, default=192,
                    help="scene ambient level, 0-255; lower if surfaces blow out")
    ap.add_argument("--sun", type=int, default=255,
                    help="directional light level, 0-255")
    ap.add_argument("--hour", default="12:00",
                    help="time of day for every session, e.g. 12:00")
    ap.add_argument("--install", default=None,
                    help="AMS GameData\\Locations folder to copy into")
    ap.add_argument("--preview",
                    help="AC track map or UI preview image for AMS menu/loading screens")
    ap.add_argument("--texconv", default="texconv.exe",
                    help="path to texconv.exe for converting menu images")
    ap.add_argument("--road-smoothness", type=float, default=None,
                    help="road surface smoothing in [0.0, 1.0] mapped uniformly to sigma in [0m, 8m] (0 disables, 0.5 -> 4m default, 1.0 -> 8m max; default from ac2ams1.ini / 0.5)")
    args = ap.parse_args()

    import steam_paths
    try:
        _cfg = steam_paths.load_config()
    except ValueError as exc:
        raise SystemExit("config error: %s" % exc)
    if args.road_smoothness is None:
        args.road_smoothness = _cfg["road_smoothness"]
    try:
        eff_road_smooth_sigma = steam_paths.road_smoothness_to_sigma(args.road_smoothness)
    except ValueError as exc:
        raise SystemExit("--road-smoothness: %s" % exc)

    out_dir = os.path.abspath(args.out_dir)
    venue = os.path.basename(out_dir)
    layout = layout_identifier(venue)
    gmt_dir = os.path.join(out_dir, "gmt")
    with open(os.path.join(gmt_dir, "exported.json")) as f:
        exported = json.load(f)

    # Take the draw flags from the mapping rather than the export record, so
    # changing what is drawn does not mean re-exporting every mesh.
    mapping = os.path.join(out_dir, "material_map.json")
    mdata = None
    cutouts = {}
    if os.path.exists(mapping):
        with open(mapping) as f:
            mdata = json.load(f)
        cutouts = mdata.get("alpha_ref", {})
        # By id where the export recorded one; by name for meshes exported
        # before ids existed (--skip-geometry over an older build).
        flags = {m["mesh"]: m for m in mdata["meshes"]}
        by_id = {m["id"]: m for m in mdata["meshes"] if "id" in m}
        for row in exported:
            cur = (by_id.get(row["id"]) if row.get("id")
                   else flags.get(row.get("mesh")))
            if cur is not None:
                row["render"] = cur.get("render", True)
                row["shadow"] = shadow_caster(cur, cutouts)
                # AC's switching distances come from here too, for the same
                # reason: they decide what the scene says, not what the
                # geometry stage happened to record an hour earlier.
                row["lod_in"] = cur.get("lod_in", 0.0)
                row["lod_out"] = cur.get("lod_out", 0.0)

    stage = os.path.join(out_dir, "ams1", venue)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    lay_dir = os.path.join(stage, layout)
    gmts = os.path.join(stage, "gmt")
    maps = os.path.join(stage, "maps")
    for d in (lay_dir, gmts, maps):
        os.makedirs(d)
    mas_files = stage_mas_archives(out_dir, stage, venue)

    aiw_src = os.path.join(out_dir, venue + ".AIW")
    lap_km = 0.0
    if os.path.exists(aiw_src):
        import re as _re
        with open(aiw_src, encoding="utf-8", errors="replace") as f:
            m = _re.search(r"lap_length=([\d.]+)", f.read())
        if m:
            lap_km = float(m.group(1)) / 1000.0

    if args.minimal:
        keep = [r for r in exported if r["physical"]]
        print("MINIMAL build: %d of %d instances" % (len(keep), len(exported)))
        exported = keep

    # Opaque geometry first, then transparent, biggest first. Blended surfaces
    # do not write depth, so a huge backdrop drawn after the trees paints over
    # them.
    exported.sort(key=lambda r: (bool(r.get("blend")), -float(r.get("radius", 0.0))))

    skybox = stage_skybox(stage, args.install, venue)
    sx, sy, sz = sun_direction(out_dir)
    lines = [SCN_HEADER.format(venue=venue, layout=layout,
                               mas_files=mas_files,
                               amb=args.ambient, sun=args.sun,
                               sx=sx, sy=sy, sz=sz,
                               skybox=skybox)]
    phys = 0
    for row in exported:
        name = os.path.splitext(row["gmt"])[0]
        coll = "True" if row["physical"] else "False"
        if row["physical"]:
            phys += 1
        # Timing strips collide but must not act as ground, or the car sits on
        # them instead of the road.
        hat = "False" if row.get("timing") else coll
        # AC marks some meshes as collision-only shells. Drawing them puts a
        # blank wall over the real road and barriers, so keep the collision but
        # close the visible range to nothing.
        invisible = row.get("timing") or not row.get("render", True)
        if invisible:
            extra = " LODIn=(0.0) LODOut=(0.01)"
        else:
            # AC's switching distances, carried straight across. Without them
            # every detail level of a surface drew at once and the coplanar
            # copies flickered against each other.
            lin = float(row.get("lod_in") or 0.0)
            lout = float(row.get("lod_out") or 0.0)
            extra = (" LODIn=(%.1f) LODOut=(%.1f)" % (lin, lout)) if lout > 0.0 else ""
        if not invisible:
            extra += " ShadowReceiver=True"
        if row.get("shadow") and not invisible:
            # AMS1/rF1 requires 4-argument ShadowCaster with shadow map size
            # (width, height); 2-argument rF2 syntax crashes on shadow pass.
            extra += " ShadowCaster=(Static, %s, 128, 128)" % row["shadow"]
        if row.get("timing"):
            lines.append(
                "Instance=%s\n{\n"
                "  Render=False Change=False VisGroups=(32)\n"
                "  MeshFile=%s CollTarget=True HATTarget=False\n"
                "  Response=VEHICLE,TIMING\n}\n"
                % (name, row["gmt"])
            )
            continue
        lines.append("Instance=%s\n{\n  MeshFile=%s CollTarget=%s HATTarget=%s%s\n}\n"
                     % (name, row["gmt"], coll, hat, extra))
    if not args.minimal:
        lines.extend(stage_pit_gates(stage, aiw_src))
    write(os.path.join(lay_dir, layout + ".scn"), "\n".join(lines))
    write(os.path.join(lay_dir, layout + ".gdb"),
          GDB.format(venue=venue, layout=layout, km=lap_km,
                     mi=lap_km * 0.621371, hour=args.hour))
    menu_images = stage_menu_images(args.preview, lay_dir, layout, args.texconv)
    if menu_images:
        print("  menu images %d (thumbnail and loading screen)" % menu_images)

    tdf = os.path.join(out_dir, venue + ".tdf")
    if not os.path.exists(tdf):
        raise SystemExit("refusing to stage track without its terrain file: %s" % tdf)
    shutil.copy2(tdf, os.path.join(stage, venue + ".tdf"))

    aiw = os.path.join(out_dir, venue + ".AIW")
    has_aiw = os.path.exists(aiw)
    if has_aiw:
        shutil.copy2(aiw, os.path.join(lay_dir, layout + ".AIW"))

    wanted = {r["gmt"].lower() for r in exported}
    n_gmt = 0
    for f in os.listdir(gmt_dir):
        if not f.lower().endswith(".gmt"):
            continue
        if args.minimal and f.lower() not in wanted:
            continue
        shutil.copy2(os.path.join(gmt_dir, f), gmts)
        n_gmt += 1

    n_tex = 0
    tex_dir = os.path.join(out_dir, "textures")
    if os.path.isdir(tex_dir):
        for f in os.listdir(tex_dir):
            src = os.path.join(tex_dir, f)
            if not os.path.isfile(src):
                continue
            shutil.copy2(src, maps)
            n_tex += 1

    # AMS needs these timing meshes for sectors and collision.
    names = {os.path.splitext(r["gmt"])[0].lower() for r in exported}
    need = {"xfinish", "xsector1", "xsector2"}
    missing = sorted(need - names)
    if missing and not args.minimal:
        raise SystemExit("refusing to install: timing strips missing (%s). "
                         "Re-run the geometry stage." % ", ".join(missing))

    print("staged %s" % stage)
    print("  instances   %d  (%d collidable)" % (len(exported), phys))
    print("  gmt files   %d" % n_gmt)
    print("  textures    %d" % n_tex)
    print("  waypoints   %s" % ("yes" if has_aiw else "MISSING"))

    cam = os.path.join(out_dir, venue + ".cam")
    if os.path.exists(cam):
        shutil.copy2(cam, os.path.join(lay_dir, layout + ".cam"))
        print("  cameras     converted from AC")
    elif args.install:
        fallback = os.path.join(args.install, "default.cam")
        if os.path.exists(fallback):
            shutil.copy2(fallback, os.path.join(lay_dir, layout + ".cam"))
            print("  cameras     placeholder (default.cam)")

    if eff_road_smooth_sigma > 0.0:
        import road_smooth
        rs = road_smooth.smooth_staged_road_gmts(
            gmts, exported, mdata=mdata, sigma=eff_road_smooth_sigma)
        if rs["meshes"]:
            print("  road smooth %d meshes, %d/%d verts (road_smoothness=%s, effective road_smooth_sigma=%sm, dY rms=%.2fmm, max=%.1fmm)"
                  % (rs["meshes"], rs["smoothed"], rs["verts"],
                     args.road_smoothness, eff_road_smooth_sigma,
                     rs["dy_rms_mm"], rs["dy_max_mm"]))
    else:
        print("  road smooth disabled (road_smoothness=%s, effective road_smooth_sigma=0.0m)"
              % (args.road_smoothness,))

    from ams_crypt import encrypt_assets
    encrypted = encrypt_assets(stage)
    print("  encrypted   %d GMT/DDS assets for AMS1" % encrypted)

    if args.install:
        try:
            dest = install_location(stage, args.install, venue)
            print("installed -> %s" % dest)
        except (OSError, RuntimeError) as exc:
            print("could not install: %s" % exc)
            print("staged copy: %s" % stage)
            raise SystemExit(1)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
