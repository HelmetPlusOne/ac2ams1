# AC to Automobilista 1 — Standalone Converter

Standalone Windows distribution for converting Assetto Corsa (AC) tracks into
Automobilista 1 (AMS1) locations. No pre-installed Python, Blender, Assetto
Corsa, Automobilista 1, or rFactor 2 is required.

Converted tracks are automatically installed into the `out\` folder next to
`ac2ams1.exe`. To play a converted track in AMS1, copy `out\<track>\` into
`<Automobilista>\GameData\Locations\`.

## Changelog

### 21 Nov 2026

- **Configuration file support (`ac2ams1.ini`)**: Added INI configuration next to `ac2ams1.exe` (`[track]` `texture_scale`, `texture_scale_min_size`, and `road_smoothness`), with matching CLI overrides and clear startup reporting of whether each value came from `ac2ams1.ini`, defaults, or CLI flags.
- **Road surface smoothness**: Added C2 triweight quadratic MLS Y-smoothing for physical road meshes via `road_smoothness` (`0.0`–`1.0`, default `0.5` -> `4.0m` effective `road_smooth_sigma`, `0.0` disables), and fixed AMS1/rF1 GMT face bounding-sphere radii so laser-scanned AC tracks drive smoothly without excessive high-frequency bumpiness.
- **Exit-to-menu crash fix**: Shortened `.scn` `Instance=` names longer than 31 characters (keeping `MeshFile=` intact) to prevent AMS1 from overflowing its 32-byte instance name buffer and crashing when returning to the main menu.

### 20 Nov 2026

- Initial version.

## Usage

### 1. Drag and Drop (Windows Explorer)

Drag and drop any of the following directly onto `ac2ams1.exe`:

- **An AC track folder** (e.g. `ks_laguna_seca`)
  — if the track has multiple layouts (`models_*.ini`), the console will list
  them and prompt you to pick one.
- **Multiple AC track folders** at once — converts each track sequentially.
- **An AC track `.zip` archive** — extracts it into `work\_zips\` and converts it.
- **A batch `.txt` track list** — runs `convert_multiple_tracks` on the file.

When launched via drag-and-drop, the console window stays open after completion
so you can review the output.

### 2. Single Track CLI (`build_track`)

```bat
ac2ams1.exe build_track "<path to AC track folder or zip>"
```

You can also pass the track path directly without `build_track`:

```bat
ac2ams1.exe "<path to AC track folder or zip>" [--layout <name>]
```

Common options:

- `--layout <name>` — layout name for multi-layout tracks (the part after `models_` in `models_<name>.ini`).
- `--hour HH:MM` — session start time (default `12:00`).
- `--texture-scale <0..1>` — texture resolution scale per dimension (overrides `ac2ams1.ini`; default `0.5`).
- `--texture-scale-min-size <px>` — minimum `max(width, height)` (inclusive) to scale textures (overrides `ac2ams1.ini`; default `1024`, so `1024x1024`+ are scaled while `512x512` and smaller are kept unscaled).
- `--road-smoothness <0..1>` — C2 triweight quadratic MLS Y-smoothing strength for physical road meshes (overrides `ac2ams1.ini`; default `0.5`). Mapped uniformly to effective `road_smooth_sigma` in `[0m, 8m]` (`0.0` disables smoothing, `0.5 -> 4m` default, `1.0 -> 8m` max).
- `--jobs <n>` — number of parallel Blender and texture conversion workers.
- `--skip-geometry` — reuse previously exported GMT meshes in `work\<track>\gmt\`.
- `--install "<dir>"` — override the automatic install destination (defaults to `out\` next to `ac2ams1.exe`).

Run `ac2ams1.exe build_track --help` for the full option list.

### 3. Batch Conversion CLI (`convert_multiple_tracks`)

Create a text file with one `<path to track>;<layout name>` entry per line
(`<layout name>` may be left empty; blank lines and `#` comments are ignored):

```text
C:\tracks\ks_laguna_seca;
C:\tracks\ks_nordschleife;nordschleife
C:\tracks\ks_nordschleife;endurance
```

Then run:

```bat
ac2ams1.exe convert_multiple_tracks "<path to tracks.txt>"
```

Each entry is converted and installed automatically into `out\`. Any entry that
fails is logged and skipped so the remaining tracks still complete.

### 4. Diagnostic Commands

```bat
ac2ams1.exe check_setup ["<path to AC track>"]
ac2ams1.exe verify_install "out\<track>" "work\<track>"
```

## Directory Layout & Bundled Tools

All tool and data paths are resolved relative to `ac2ams1.exe`:

| Path | Contents / Purpose |
| --- | --- |
| `ac2ams1.exe` | Single executable bundling **Python 3.10**, **NumPy**, and the AC-to-AMS1 converter scripts (`build_track`, `convert_multiple_tracks`, `check_setup`, `verify_install`, and all conversion stages). |
| `ac2ams1.ini` | Configuration file read from the same folder as `ac2ams1.exe` (`[track]` `texture_scale`, `texture_scale_min_size`, `road_smoothness`). |
| `tools\blender\` | Portable **Blender 3.6 LTS** (`blender.exe`) with the **rFactor 2 GMT Exporter add-on (`io_rf2_gmt_release`)** pre-installed under `3.6\scripts\addons\io_rf2_gmt_release\`. |
| `tools\blender_scripts\` | Plain Python scripts executed inside Blender's own interpreter (`blender_stage.py`, `kn5.py`, `backdrop.py`). |
| `tools\texconv\texconv.exe` | **Microsoft DirectXTex `texconv.exe`** for DX9 power-of-two DDS conversion, mipmap generation, multilayer material baking, and loading screen / minimap composition. |
| `tools\rfactortools\` | **`rfactorcrypt.exe`** (from `rfactortools`, with its bundled Python 3.3 runtime) for GSC/AMS1 encryption of staged `.gmt` and `.dds` assets. |
| `data\ac\system\data\surfaces.ini` | Default Assetto Corsa surface physics definitions. |
| `data\ams1\GameData\Locations\terrain.tdf` | AMS1 terrain template file patched with AC surface grip values. |
| `data\ams1\GameData\Locations\sky\` | Stock AMS1 skybox meshes (`SRPL_SKY3_DOME1.GMT`, `SRPL_SKY3_SUN1.GMT`). |
| `out\` | Ready-to-install AMS1 track folders produced by conversions. |
| `work\` | Intermediate working files (extracted textures, baked layers, raw GMTs, AIW/CAM, extracted zips). |

## Licenses & Third-Party Notices

This standalone bundle includes third-party tools and runtime libraries, each
governed by its own license:

| Component | Location | License & Source |
| --- | --- | --- |
| **Python 3.10** (and **Python 3.3** runtime in `rfactortools`) | `ac2ams1.exe`, `tools\rfactortools\` | **PSF License Version 2** — Python Software Foundation (https://docs.python.org/3/license.html) |
| **NumPy** | `ac2ams1.exe` | **BSD 3-Clause License** — NumPy Developers (https://numpy.org/doc/stable/license.html) |
| **PyInstaller Bootloader** | `ac2ams1.exe` | **GNU GPL v2 or later with Bootloader Exception** (https://pyinstaller.org/en/stable/license.html) |
| **Blender 3.6 LTS** | `tools\blender\` | **GNU GPL v2 or later** (with GPL-3.0-compatible third-party libraries). Full license texts are included in `tools\blender\copyright.txt` and `tools\blender\license\` (see `THIRD-PARTY-LICENSES.txt`). Source: https://www.blender.org/ |
| **rFactor 2 GMT Exporter (`io_rf2_gmt_release` v24.3.9)** | `tools\blender\3.6\scripts\addons\io_rf2_gmt_release\` | Authored by **rFactor2 IO Group** (distributed via the Studio-397 community forum: https://forum.studio-397.com/index.php?threads/blender-rfactor2-export-scripts.74821/). Shipped without a separate license file; check the author's terms before redistributing. |
| **DirectXTex `texconv.exe`** | `tools\texconv\texconv.exe` | **MIT License** — Microsoft Corporation (https://github.com/microsoft/DirectXTex/blob/main/LICENSE). This copy was taken from rFactor 2's `Support\Tools\MapConverter\` folder and can also be obtained directly from Microsoft's DirectXTex GitHub releases. |
| **rfactortools (`rfactorcrypt.exe`)** | `tools\rfactortools\` | **GNU GPL v3** — full license text included in `tools\rfactortools\COPYING.txt`. Source: https://github.com/Grumbel/rfactortools |

This converter is based on the code from https://github.com/Mewzapchu/ac-to-rf2 ([license](https://github.com/HelmetPlusOne/ac2ams1/blob/master/LICENSE)).

## Included Game Files (Assetto Corsa & Automobilista 1)

To allow standalone conversion on a Windows machine where Assetto Corsa and
Automobilista 1 are not installed, the `data\` directory contains a small set
of proprietary template files copied from local game installations:

- **Assetto Corsa** (© Kunos Simulazioni):
  - `data\ac\system\data\surfaces.ini` — default AC surface physics table.
- **Automobilista 1** (© Reiza Studios):
  - `data\ams1\GameData\Locations\terrain.tdf` — stock AMS1 terrain template.
  - `data\ams1\GameData\Locations\sky\SRPL_SKY3_DOME1.GMT` and `SRPL_SKY3_SUN1.GMT` — stock AMS1 skybox meshes required by the scene loader.

## Notes

- Converted tracks contain the original track's models and textures; do not
  redistribute converted content without permission from the original authors.
