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

After decryption, all 198 Targa GMTs from exporter 24.3.9 had bytes
`20 00 00 04` at offsets 4-7 (for example `1GRASS0.gmt` and `xfinish.gmt`).
Three stock AMS1 samples (`DeLaSarthe\gmt\XFINISH.GMT`,
`PerthStreetCircuit\PerthReverse\xfinish.gmt`, and
`2014Kyalami\SRPL_SKY3_DOME1.GMT`) instead had `20 00 00 00` at those offsets.
The AMS1 converter now changes only this measured exporter format word before
encryption. Existing AMS1-format GMTs pass through unchanged, and unknown words
fail explicitly. The outer GSC encryption signature was valid already; it was
separate from this internal GMT-version mismatch.

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
`*_loading.jpg`, and 246 have a matching `*mini.tga`; Targa had neither. Its
AC source does include `ui\preview.png` (551x320). The converter now uses that
image, or falls back to `map.png`, to stage both AMS menu images.

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
