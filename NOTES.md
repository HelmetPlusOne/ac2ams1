# AMS1 compatibility measurements

## GMT and DDS encryption

The installed AMS1 assets use the GSC signature handled by rfactortools:

- `DeLaSarthe\gmt\XFINISH.GMT` begins
  `e9 24 05 96 9f ca 1d 4b 01 00 00 00 00 00 00 00`.
  The first 64-bit value XOR the second is `0x4b1dca9f960524e8`; the key is 1.
- `2014Kyalami\2014Kyalami\SKIDHARD.dds` begins
  `e8 03 0d d7 fa a5 96 07 00 27 08 41 65 6f 8b 4c`.
  It decodes to the same signature with key `0x4c8b6f6541082700`.

The converter therefore re-encrypts both loose GMT and DDS assets with the
GSC/AMS1 signature and verifies the resulting header before installation.

## GMT format version

Blender's `io_rf2_gmt_release` (24.3.9) exports rFactor 2 GMT v2.52
(`GMOTOR_GMT_2.52\0` encoded at offset `0x1BC`, 884-byte header, 156-byte mesh
descriptors, interleaved 96-byte `TVertex2` vertices, single-level materials
with 180-byte textures). Stock AMS1 tracks instead use rFactor 1 / gMotor 2.0
GMT v2.20 (`GMOTOR_GMT_2.20\0` encoded at offset `0x1D4`, 740-byte header,
132-byte mesh descriptors, split 32-byte `TVertex` / 32-byte `TexturesUV` /
optional 24-byte `UVTangents` arrays, and 3-level `L0`/`L1`/`L2` materials with
172-byte textures).

Patching only header bytes 4–7 from `20 00 00 04` to `20 00 00 00` left the
file in rF2 v2.52 layout, causing AMS1 to read zeros at `0x1D4` and abort with
`Wrong GMT version or GMT version not allowed`. `gmt_rf1.py` (invoked by
`ams_crypt._prepare_gmt_for_ams1` before encryption) now performs a full binary
conversion from rF2 GMT v2.52 to AMS1 GMT v2.20, sets mesh tangent flag `0x04`
and emits `UVTangents` for bump-mapped shaders, strips the rF2-only material
bit `0x2000`, and maps rF2's `L2BUMPSPECMAPT0XT1` (absent from AMS1's
`coreshaders.mas`) to AMS1's `L2BUMPSPECMAPT0MULT1CUSTOM` with reordered
texture stages and permuted vertex UV channels. Existing rF1 GMT v2.20 files
pass through unchanged; unknown formats fail explicitly.

`io_rf2_gmt_release` also double-swaps Y and Z on collision `NormalData` and
swaps Y (`2/3`) vs Z (`4/5`) in `FaceData.flags` (because `TPoint3D(X, Z, Y)`
already swaps Y and Z before `AddXZYas021` swaps them again), giving flat road
triangles horizontal `+Z` collision normals and flag `4` instead of upward `+Y`
and flag `2`. It also writes triangle area instead of face bounding-sphere radius
(`max(||p_i - centroid||)`) into `FaceData`'s 4th float; on dense laser-scanned
road meshes (e.g. `ks_laguna_seca`, where 99.67% of road triangles have
`area < radius` with median ratio `0.333`), AMS1's HAT bounding-sphere test
rejects triangle edges/corners and produces severe artificial bumpiness. Verified
100% against official ISI `Joesville` and stock AMS1 `DeLaSarthe`/`2014Kyalami`
GMTs, `gmt_rf1.py` now rebuilds `NormalData`, `FaceData.flags`, `FaceData`
centroids, and `FaceData` bounding-sphere radii directly from triangle vertex
geometry during conversion, and generates double-sided `xpitin`/`xpitout` quads.

## Location structure and terrain

AMS1's installed tracks place `<venue>.tdf` at the location root, with the
`.scn`, `.gdb`, `.AIW`, and `.cam` in a nested layout folder. The 2014 Kyalami
scene uses `Light=FDirect01`, `MaxShadowRange(500.00)`, and search paths for
the venue and nested layout; the AMS1 finalizer follows that layout.

The supplied Targa Tas High Plains test track converted with the AMS1
`GameData\Locations\terrain.tdf` template. Its generated TDF applied road dry
grip `0.970` and grass dry grip `0.650` from the AC surface data.

The full Targa build read 44 materials and 66 source textures, then staged 198
GMTs and 114 DDS textures. The encryptor processed all 312 files. The installed
AMS verifier found zero missing textures, zero wrong alpha tests, zero wrong
upright normals, zero default-range meshes, and reported `all checks passed`.
The in-game load/drive check remains to be done.

## Track menu filter

The installed Targa GDB originally declared `Filter Properties = StockV8 *`.
In the installed AMS1 locations, 113 GDBs use this class-first pattern, while
the four inspected broadly available tracks (Ambush Canyon, Daytona, and
Knockhill) use `Filter Properties = * StockV8`. The converter's GDB template
already uses the wildcard-first pattern. Updated the installed Targa GDB to
match it; the user reports that this alone did not make the track appear.

The installed location has 249 GDB layouts. 248 have a matching
`*_loading.jpg` (predominantly 1920x1080 dark loading screens with a white
track map), and 246 have a matching `*mini.tga` (predominantly 252x249 32-bit
RGBA transparent track maps). Multi-layout AC tracks store their rasterized
maps at `<layout>\map.png` and UI assets under `ui\<layout>\` rather than
`<layout>\ui\`. The converter now prefers the layout's `map.png` (then
`outline.png`, then `preview.png`), crops transparent margins, preserves aspect
ratio, and composes both the 1920x1080 `*_loading.jpg` and 252x249 `*mini.tga`.

Targa's GDB `TrackName` is 27 characters; installed stock values reach 38, so
the displayed-name length is not an outlier. Before the scene fix, the full
Targa GDB path was 146 characters, compared with 124 for the longest stock GDB
path. The shortened layout now brings its GDB path to 124 characters.

## Scene filename limit and MAS registration

The AMS1 trace reported that `targa_tas_21_s1_high_plains.scn` exceeded the
scene filename maximum by 8 characters. The filename is 31 characters, so the
measured maximum is 23 including `.scn`. The finalizer now uses a deterministic
16-character layout identifier when the source track name is longer, keeping
the `.scn` name to 20 characters. The GDB, SCN, AIW, CAM, layout directory, and
menu images all use the same shortened identifier; displayed GDB names retain
the full venue name. The installed layout is `targata_3ecef12f`; the old
overlong layout files have been removed.

The manually packaged venue MAS and MAP MAS archives are registered in the
generated scene and staged from `out\<track>` when both are present. The
converter does not create these MAS archives.

The trace's `BoxerCup_33.veh` warning is separate from the track. Two files
with that basename exist under `BoxerCup\Teams\BoxerTeam11` and
`BoxerCup\Teams\BoxerTeam7`; the track converter does not install vehicle
files.

## Instance name length limit (exit-to-menu crash)

AMS1's scene `Instance` struct stores the `Instance=` name in a fixed 32-byte
buffer (`+0x1e8..+0x207`) immediately followed by a linked-list head pointer at
`+0x208`. Parsing an `Instance=` name longer than 31 characters overflows past
the buffer; names of 33+ characters overwrite `+0x208` with ASCII bytes (e.g.
`pitstop__metal_fence_extruded_001_SUB0` writes `'1_SU'` = `0x55535f31`,
`corkscrew_traliccio_fili_001_SUB1` writes `'1\0'` = `0x00000031`). The track
loads and drives normally, then crashes with `0xc0000005` at `AMS.exe+0x0000b552`
inside `VidMan::Post()` when exiting to the menu. `finalize_track.py` now caps
`Instance=` names to 31 characters via `instance_identifier()` while keeping
`MeshFile=` filenames intact, and `verify_install.py` checks the limit.
