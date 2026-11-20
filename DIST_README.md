# AC to Automobilista 1 — Standalone Converter

Standalone Windows distribution for converting Assetto Corsa (AC) tracks into
Automobilista 1 (AMS1) locations. No pre-installed Python, Blender, Assetto
Corsa, Automobilista 1, or rFactor 2 is required.

Converted tracks are automatically installed into the `out\` folder next to
`ac2ams1.exe`. To play a converted track in AMS1, copy `out\<track>\` into
`<Automobilista>\GameData\Locations\`.

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
- `--texture-scale <0..1>` — texture resolution scale per dimension (default `0.5`).
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
| `tools\blender\` | Portable **Blender 3.6 LTS** (`blender.exe`) with the **rFactor 2 GMT Exporter add-on (`io_rf2_gmt_release`)** pre-installed under `3.6\scripts\addons\io_rf2_gmt_release\`. |
| `tools\blender_scripts\` | Plain Python scripts executed inside Blender's own interpreter (`blender_stage.py`, `kn5.py`, `backdrop.py`). |
| `tools\texconv\texconv.exe` | **Microsoft DirectXTex `texconv.exe`** for DX9 power-of-two DDS conversion, mipmap generation, multilayer material baking, and loading screen / minimap composition. |
| `tools\rfactortools\` | **`rfactorcrypt.exe`** (from `rfactortools`, with its bundled Python 3.3 runtime) for GSC/AMS1 encryption of staged `.gmt` and `.dds` assets. |
| `data\ac\system\data\surfaces.ini` | Default Assetto Corsa surface physics definitions. |
| `data\ams1\GameData\Locations\terrain.tdf` | AMS1 terrain template file patched with AC surface grip values. |
| `data\ams1\GameData\Locations\sky\` | Stock AMS1 skybox meshes (`SRPL_SKY3_DOME1.GMT`, `SRPL_SKY3_SUN1.GMT`). |
| `out\` | Ready-to-install AMS1 track folders produced by conversions. |
| `work\` | Intermediate working files (extracted textures, baked layers, raw GMTs, AIW/CAM, extracted zips), created at runtime. |

## Notes

- Converted tracks contain the original track's models and textures; do not
  redistribute converted content without permission from the original authors.
