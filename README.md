# AC to Automobilista 1

Converts an Assetto Corsa track into an Automobilista 1 location. The output
contains loose GMT meshes and DDS textures, AMS-compatible scene and database
files, an AMS terrain definition, and converted AI and camera files.

Converted content contains the source track's models and textures. Do not
redistribute it unless you have permission from the original author.

## Requirements

- Windows
- Assetto Corsa and Automobilista 1 installed
- Python 3.10 or newer and NumPy (`python -m pip install numpy`)
- Blender 3.6 LTS with the `io_rf2_gmt_release` exporter add-on
- `texconv.exe` (by default taken from an installed rFactor 2; otherwise pass
  its path with `--texconv`)
- `rfactortools` for AMS1's GMT/DDS encryption, either installed as a Python
  package or available as `rfactorcrypt.exe` (see the
  [rfactortools download](https://www.overtake.gg/downloads/rfactortools.1954/))

The converter encrypts every staged `.gmt` and `.dds` file with the GSC/AMS1
signature before installation. It also normalizes the GMT format word emitted
by the rFactor 2 exporter to the AMS1 format; an unrecognized format is rejected
instead of being silently rewritten. Install the Python package with
`python -m pip install git+https://github.com/Grumbel/rfactortools.git`; building
it from source may require Microsoft C++ Build Tools. Alternatively, pass the
standalone tool path with `--encryptor "<path to rfactorcrypt.exe>"`.

When the AC track includes a rasterized track map (`<layout>\map.png` or
`map.png`), UI outline (`ui\<layout>\outline.png` or `ui\outline.png`), or
preview (`ui\<layout>\preview.png` or `ui\preview.png`), the converter composes
AMS1's 1920x1080 loading screen (`<layout>_loading.jpg`) and 252x249 transparent
menu minimap (`<layout>mini.tga`).
AMS1 limits scene filenames to 23 characters, including `.scn`; long layout
identifiers are shortened consistently across the GDB, scene, AIW, camera, and
layout filenames. If both `<venue>.mas` and `<venue>MAP.mas` are in
`out\<track>`, the converter stages them and registers them in the scene. The
converter does not create MAS archives; they must be supplied by the packaging
step.

It writes plain working files under `out\<track>` and AMS1-ready files under
`out\<track>\ams1\<track>`.

Run `python check_setup.py` to check dependencies. If Steam does not list a
game installation, provide its path with `--ams` or `--ac`.

## Convert a track

```text
python build_track.py "<AC track folder>" --install auto
```

`--install auto` installs into
`Automobilista\GameData\Locations\<track>`. Without `--install`, the staged
AMS1-ready location remains under `out\<track>\ams1\<track>`.

For a track with multiple layouts, use `--layout <name>` (the part after
`models_`), for example:

```text
python build_track.py "<AC track folder>" --layout gp --install auto
```

On Windows, drag an AC track folder or its download ZIP onto `convert.bat` to
run a full conversion and install it automatically. For multi-layout tracks,
the launcher prompts for a layout. Additional `build_track.py` options can be
passed after the track path, for example:

```text
convert.bat "<AC track folder>" --encryptor "<path to rfactorcrypt.exe>"
```

Useful options:

- `--hour HH:MM` sets the session start time.
- `--skip-geometry` reuses meshes from the previous build.
- `--jobs <n>` controls parallel Blender and texture jobs.
- `--ams "<Automobilista folder>"` and `--ac "<Assetto Corsa folder>"` override
  Steam discovery.
- `--texconv "<path to texconv.exe>"` selects the texture conversion utility.
- `--encryptor "<path to rfactorcrypt.exe>"` selects the AMS1 encryption tool
  when the Python package is not installed.

Check an installed result with:

```text
python verify_install.py "<AMS>\GameData\Locations\<track>" out\<track>
```

The verifier checks the installed AMS1 encryption headers and compares mesh and
texture data against the unencrypted build assets, along with references,
scene, draw ranges, and shadows. The final compatibility check is loading and
driving the track in Automobilista 1.

