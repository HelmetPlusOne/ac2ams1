import os
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

import ac2ams1
import ams_crypt
import build_track
import convert_multiple_tracks
import finalize_track
import fix_textures
import gmt_rf1
import verify_install


def _make_rf2_gmt(name="mesh", shader="L2DIFFUSET0", textures=None,
                  mat_flags=0x68902003, blend=(2, 1)):
    """Build a minimal valid rF2 GMT v2.52 binary with 1 triangle (3 verts)."""
    if textures is None:
        textures = [("base.dds", 0x18, 1, 3, 0, 0)]

    nmesh = 1
    nface = 1
    nnorm = 1
    vcount = 3
    tcount = 3

    out = bytearray(gmt_rf1.RF2_HEADER_SIZE)
    struct.pack_into("<I", out, 4, 0x04000020)
    struct.pack_into("<3f", out, 0x0C8, -1.0, 0.0, -2.0)
    struct.pack_into("<3f", out, 0x0D4, 1.0, 3.0, 2.0)
    struct.pack_into("<f", out, 0x0E0, 5.0)
    struct.pack_into("<3f", out, 0x0E4, 0.0, 1.5, 0.0)
    struct.pack_into("<3f", out, 0x0F0, 0.0, 1.5, 0.0)
    struct.pack_into("<2f", out, 0x100, 0.0, 13000.0)
    out[0x17C:0x1BC] = gmt_rf1._pad_ascii(name, 64)
    out[0x1BC:0x1CC] = gmt_rf1.RF2_GMT_MAGIC

    moff = len(out)
    mesh = bytearray(gmt_rf1.RF2_MESH_SIZE)
    struct.pack_into("<10I", mesh, 0, 0x20004011, vcount, 0, tcount, 0, 0, 0, 0, 0, 0)
    out.extend(mesh)

    foff = len(out)
    out.extend(struct.pack("<4H2I4f", 0, 1, 2, 4, 0, 0, 0.0, 0.0, 0.0, 1.0))

    noff = len(out)
    out.extend(struct.pack("<3fI", 0.0, 1.0, 0.0, 1))

    voff = len(out)
    for vi in range(vcount):
        v = bytearray(gmt_rf1.RF2_VERTEX_SIZE)
        struct.pack_into("<6fI", v, 0, float(vi), 1.0, 2.0, 0.0, 1.0, 0.0, 0xFFFFFFFF)
        struct.pack_into("<6f", v, 40, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        # Distinct UVs per channel so permutation is verifiable.
        struct.pack_into("<8f", v, 64,
                         0.1 + vi, 0.2,   # UV0
                         1.1 + vi, 1.2,   # UV1
                         2.1 + vi, 2.2,   # UV2
                         3.1 + vi, 3.2)   # UV3
        out.extend(v)

    toff = len(out)
    out.extend(struct.pack("<3H", 0, 1, 2))

    mat_off = len(out)
    out.extend(struct.pack("<I", 1))
    mat = bytearray(gmt_rf1.RF2_MAT_HEADER_SIZE)
    mat[0:64] = gmt_rf1._pad_ascii("mat0", 64)
    struct.pack_into("<I", mat, 64, mat_flags)
    struct.pack_into("<16f", mat, 68, *([0.5, 0.5, 0.5, 1.0] * 4))
    struct.pack_into("<2If", mat, 132, blend[0], blend[1], 10.0)
    mat[148:212] = gmt_rf1._pad_ascii(shader, 64)
    struct.pack_into("<I", mat, 256, len(textures))
    out.extend(mat)
    for tname, tflags, actor, action, stage, aref in textures:
        tex = bytearray(gmt_rf1.RF2_TEXTURE_SIZE)
        tex[0:64] = gmt_rf1._pad_ascii(tname, 64)
        struct.pack_into("<IiIIIfI", tex, 64, tflags, -1, 1, actor, action, 1.0, stage)
        struct.pack_into("<I", tex, 100, aref)
        out.extend(tex)

    struct.pack_into("<I", out, 0, mat_off - 4)
    struct.pack_into("<12I", out, 0x13C,
                     vcount, voff - 4, tcount, toff - 4,
                     nmesh, moff - 4, nface, foff - 4, nnorm, noff - 4, 0, voff - 4)
    return bytes(out)


class AmsCryptTests(unittest.TestCase):
    def test_reads_gsc_signature_from_ams_gmt_and_dds_headers(self):
        headers = (
            bytes.fromhex("e92405969fca1d4b0100000000000000"),
            bytes.fromhex("e8030dd7faa5960700270841656f8b4c"),
        )
        expected = (
            (ams_crypt.AMS_SIGNATURE, ams_crypt.AMS_KEY),
            (ams_crypt.AMS_SIGNATURE, 0x4C8B6F6541082700),
        )
        with tempfile.TemporaryDirectory() as root:
            for index, (header, pair) in enumerate(zip(headers, expected)):
                path = os.path.join(root, "%d.gmt" % index)
                with open(path, "wb") as f:
                    f.write(header)
                self.assertEqual(ams_crypt.crypt_info(path), pair)

    def test_encrypts_only_gmt_and_dds_assets(self):
        def encrypt_file(source, destination, key, signature):
            with open(source, "rb") as f:
                body = f.read()
            header = struct.pack("<QQ", signature ^ key, key)
            with open(destination, "wb") as f:
                f.write(header + body)

        fake_tools = types.SimpleNamespace(encrypt_file=encrypt_file)
        with tempfile.TemporaryDirectory() as root:
            gmt = os.path.join(root, "mesh.gmt")
            dds = os.path.join(root, "map.dds")
            tga = os.path.join(root, "unwrapped.tga")
            with open(gmt, "wb") as f:
                f.write(_make_rf2_gmt("mesh"))
            for path in (dds, tga):
                with open(path, "wb") as f:
                    f.write(b"asset")

            with mock.patch.dict(sys.modules, {"rfactortools": fake_tools}):
                count = ams_crypt.encrypt_assets(root)

            self.assertEqual(count, 2)
            self.assertEqual(ams_crypt.crypt_info(gmt),
                             (ams_crypt.AMS_SIGNATURE, ams_crypt.AMS_KEY))
            self.assertEqual(ams_crypt.crypt_info(dds),
                             (ams_crypt.AMS_SIGNATURE, ams_crypt.AMS_KEY))
            with open(gmt, "rb") as f:
                encrypted_gmt = f.read()
            body = encrypted_gmt[16:]
            self.assertTrue(gmt_rf1.is_rf1_gmt(body))
            self.assertEqual(body[4:8], b"\x20\x00\x00\x00")
            with open(tga, "rb") as f:
                self.assertEqual(f.read(), b"asset")

    def test_converts_rf2_gmt_to_ams1_rf1_layout_and_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "mesh.gmt")
            with open(path, "wb") as f:
                f.write(_make_rf2_gmt(
                    "1GRASS0",
                    shader="L2BUMPSPECMAPT0XT1",
                    textures=[
                        ("base.dds", 0x18, 1, 3, 0, 0),
                        ("detail.dds", 0x18, 1, 3, 1, 0),
                        ("spec.dds", 0x18, 2, 4, 2, 0),
                        ("bump.dds", 0x18, 5, 4, 3, 0),
                    ],
                ))

            ams_crypt._prepare_gmt_for_ams1(path)
            with open(path, "rb") as f:
                prepared = f.read()
            self.assertTrue(gmt_rf1.is_rf1_gmt(prepared))
            self.assertEqual(prepared[0x194:0x19B], b"1GRASS0")
            # Bump-mapped mesh sets tangent bit 0x04 and emits tangents.
            mflags = struct.unpack_from("<I", prepared, gmt_rf1.RF1_HEADER_SIZE)[0]
            self.assertEqual(mflags, 0x20004015)
            uv_off = struct.unpack_from("<I", prepared, gmt_rf1.RF1_HEADER_SIZE + 12)[0] + 4
            tan_off = struct.unpack_from("<I", prepared, gmt_rf1.RF1_HEADER_SIZE + 20)[0] + 4
            self.assertGreater(tan_off, uv_off)
            # UVs permuted from (base=0, detail=1, spec=2, bump=3) to (base=0, spec=2, bump=3, detail=1).
            uv0 = struct.unpack_from("<8f", prepared, uv_off)
            self.assertAlmostEqual(uv0[0], 0.1, places=5)
            self.assertAlmostEqual(uv0[2], 2.1, places=5)
            self.assertAlmostEqual(uv0[4], 3.1, places=5)
            self.assertAlmostEqual(uv0[6], 1.1, places=5)
            # L2 shader mapped to AMS1's L2BUMPSPECMAPT0MULT1CUSTOM.
            mat_off = struct.unpack_from("<I", prepared, 0)[0] + 4
            mflags_mat = struct.unpack_from("<I", prepared, mat_off + 4 + 64)[0]
            self.assertEqual(mflags_mat, 0x68900003)
            l2_shader = prepared[mat_off + 4 + 144 + 2 * 264 + 8:
                                 mat_off + 4 + 144 + 2 * 264 + 72].split(b"\x00", 1)[0]
            self.assertEqual(l2_shader, b"L2BUMPSPECMAPT0MULT1CUSTOM")

            # Idempotent on already-converted rF1 GMT v2.20.
            ams_crypt._prepare_gmt_for_ams1(path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), prepared)

            # Reject unknown GMT version.
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)
            with self.assertRaisesRegex(RuntimeError, "unsupported GMT version"):
                ams_crypt._prepare_gmt_for_ams1(path)

    def test_preserves_alpha_reference_and_numpy_fallback_parity(self):
        rf2 = _make_rf2_gmt(
            "fence",
            shader="L2BUMPSPECMAPT0",
            textures=[
                ("fence.dds", 0x88, 1, 3, 0, 191),
                ("_flat_spec.dds", 0x08, 2, 4, 1, 0),
                ("_flat_nm.dds", 0x08, 5, 4, 2, 0),
            ],
        )
        fast = gmt_rf1.convert_rf2_to_rf1(rf2)
        with mock.patch.object(gmt_rf1, "_np", None):
            pure = gmt_rf1.convert_rf2_to_rf1(rf2)
        self.assertEqual(fast, pure)
        # Verify ColorKey alpha reference 191 survived on all 3 shader levels' diffuse texture.
        mat_off = struct.unpack_from("<I", fast, 0)[0] + 4
        tex0_off = mat_off + 4 + 144 + 3 * 264 + 32 + 4
        self.assertEqual(struct.unpack_from("<I", fast, tex0_off + 100)[0], 191)

    def test_rebuilds_swapped_face_normals_and_dominant_axis_flags(self):
        # Build a horizontal CW triangle whose true gMotor normal is (0, +1, 0)
        # (dominant axis 2), but feed it io_rf2_gmt_release's double-swapped
        # normal (0, 0, +1) and flag 4.
        rf2 = bytearray(_make_rf2_gmt("road"))
        (vcount, voff_rel, _tc, _to, _nm, _mo,
         _nf, foff_rel, _nn, noff_rel, _bc, _bo) = struct.unpack_from("<12I", rf2, 0x13C)
        voff, foff, noff = voff_rel + 4, foff_rel + 4, noff_rel + 4
        pts = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        for vi, (x, y, z) in enumerate(pts):
            struct.pack_into("<3f", rf2, voff + vi * gmt_rf1.RF2_VERTEX_SIZE, x, y, z)
        struct.pack_into("<H", rf2, foff + 6, 4)
        struct.pack_into("<3fI", rf2, noff, 0.0, 0.0, 1.0, 7)

        fast = gmt_rf1.convert_rf2_to_rf1(bytes(rf2))
        with mock.patch.object(gmt_rf1, "_np", None):
            pure = gmt_rf1.convert_rf2_to_rf1(bytes(rf2))
        self.assertEqual(fast, pure)

        _nm, _mo, nface, foff_r, nnorm, noff_r = struct.unpack_from("<6I", fast, 0x174)
        self.assertEqual((nface, nnorm), (1, 1))
        flg = struct.unpack_from("<H", fast, foff_r + 4 + 6)[0]
        nx, ny, nz, sg = struct.unpack_from("<3fI", fast, noff_r + 4)
        self.assertEqual(flg, 2)
        self.assertEqual(sg, 7)
        self.assertAlmostEqual(nx, 0.0, places=5)
        self.assertAlmostEqual(ny, 1.0, places=5)
        self.assertAlmostEqual(nz, 0.0, places=5)

    def test_deduplicates_vertices_and_remaps_triangles_and_faces(self):
        # 2-triangle quad (6 unshared verts -> 4 unique) + 1 vertex with flipped
        # tangent handedness at the same pos/normal/UV (must stay separate -> 5 unique).
        nmesh, nface, nnorm, vcount, tcount = 1, 2, 2, 7, 6
        out = bytearray(gmt_rf1.RF2_HEADER_SIZE)
        struct.pack_into("<I", out, 4, 0x04000020)
        struct.pack_into("<3f", out, 0x0C8, 0.0, 0.0, 0.0)
        struct.pack_into("<3f", out, 0x0D4, 1.0, 0.0, 1.0)
        struct.pack_into("<f", out, 0x0E0, 1.0)
        struct.pack_into("<2f", out, 0x100, 0.0, 1000.0)
        out[0x17C:0x1BC] = gmt_rf1._pad_ascii("quad", 64)
        out[0x1BC:0x1CC] = gmt_rf1.RF2_GMT_MAGIC

        moff = len(out)
        mesh = bytearray(gmt_rf1.RF2_MESH_SIZE)
        struct.pack_into("<10I", mesh, 0, 0x20004011, vcount, 0, tcount, 0, 0, 0, 0, 0, 0)
        out.extend(mesh)

        foff = len(out)
        out.extend(struct.pack("<4H2I4f", 0, 1, 2, 4, 0, 0, 0.3, 0.0, 0.3, 0.5))
        out.extend(struct.pack("<4H2I4f", 3, 4, 5, 4, 0, 1, 0.7, 0.0, 0.7, 0.5))

        noff = len(out)
        out.extend(struct.pack("<3fI", 0.0, 0.0, 1.0, 1))
        out.extend(struct.pack("<3fI", 0.0, 0.0, 1.0, 1))

        # Shared corners (0==3 and 2==4) have 1e-5 normal noise; vertex 6 has
        # flipped bitangent (opposite handedness) and must not merge with 0.
        vert_specs = [
            ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0), (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0), (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
            ((1.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 1.0), (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
            ((0.0, 0.0, 0.0), (1e-5, 0.99999, -1e-5), (0.0, 0.0), (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
            ((1.0, 0.0, 1.0), (-1e-5, 0.99999, 1e-5), (1.0, 1.0), (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
            ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 1.0), (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
            ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0), (1.0, 0.0, 0.0, 0.0, 0.0, -1.0)),
        ]
        voff = len(out)
        for pos, nrm, uv, tb in vert_specs:
            v = bytearray(gmt_rf1.RF2_VERTEX_SIZE)
            struct.pack_into("<6fI", v, 0, *pos, *nrm, 0xFFFFFFFF)
            struct.pack_into("<6f", v, 40, *tb)
            struct.pack_into("<8f", v, 64, uv[0], uv[1], uv[0], uv[1], uv[0], uv[1], uv[0], uv[1])
            out.extend(v)

        toff = len(out)
        out.extend(struct.pack("<6H", 0, 1, 2, 3, 4, 5))

        mat_off = len(out)
        out.extend(struct.pack("<I", 1))
        mat = bytearray(gmt_rf1.RF2_MAT_HEADER_SIZE)
        mat[0:64] = gmt_rf1._pad_ascii("mat0", 64)
        struct.pack_into("<I", mat, 64, 0x68900003)
        struct.pack_into("<16f", mat, 68, *([0.5, 0.5, 0.5, 1.0] * 4))
        struct.pack_into("<2If", mat, 132, 2, 1, 10.0)
        mat[148:212] = gmt_rf1._pad_ascii("L2BUMPSPECMAPT0", 64)
        struct.pack_into("<I", mat, 256, 3)
        out.extend(mat)
        for stage, tname in enumerate(("a.dds", "s.dds", "b.dds")):
            tex = bytearray(gmt_rf1.RF2_TEXTURE_SIZE)
            tex[0:64] = gmt_rf1._pad_ascii(tname, 64)
            struct.pack_into("<IiIIIfI", tex, 64, 0x18, -1, 1, 1, 3, 1.0, stage)
            out.extend(tex)

        struct.pack_into("<I", out, 0, mat_off - 4)
        struct.pack_into("<12I", out, 0x13C,
                         vcount, voff - 4, tcount, toff - 4,
                         nmesh, moff - 4, nface, foff - 4, nnorm, noff - 4, 0, voff - 4)
        rf2 = bytes(out)

        fast = gmt_rf1.convert_rf2_to_rf1(rf2)
        with mock.patch.object(gmt_rf1, "_np", None):
            pure = gmt_rf1.convert_rf2_to_rf1(rf2)
        self.assertEqual(fast, pure)

        _nm, moff_r, nf, foff_r, _nn, _no = struct.unpack_from("<6I", fast, 0x174)
        _mf, voff_r, _, _, _, _, new_vc, _, new_tc, toff_r = struct.unpack_from("<10I", fast, moff_r + 4)
        self.assertEqual((new_vc, new_tc), (5, 6))
        tris = struct.unpack_from("<6H", fast, toff_r + 4)
        self.assertEqual(tris, (0, 1, 2, 0, 2, 3))
        f0 = struct.unpack_from("<3H", fast, foff_r + 4)
        f1 = struct.unpack_from("<3H", fast, foff_r + 4 + gmt_rf1.FACE_SIZE)
        self.assertEqual((f0, f1), ((0, 1, 2), (0, 2, 3)))
        # Vertex positions after remapping match original corners exactly.
        for fi, orig_tri in enumerate(((0, 1, 2), (3, 4, 5))):
            new_tri = struct.unpack_from("<3H", fast, foff_r + 4 + fi * gmt_rf1.FACE_SIZE)
            for oi, ni in zip(orig_tri, new_tri):
                got_pos = struct.unpack_from("<3f", fast, voff_r + 4 + ni * gmt_rf1.RF1_VERTEX_SIZE)
                self.assertEqual(got_pos, vert_specs[oi][0])

    def test_encrypts_with_standalone_tool_when_package_is_unavailable(self):
        def run(command, **_kwargs):
            for path in command[6:]:
                with open(path, "rb") as f:
                    body = f.read()
                header = struct.pack("<QQ", ams_crypt.AMS_SIGNATURE ^ 1, 1)
                with open(path, "wb") as f:
                    f.write(header + body)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "mesh.gmt")
            with open(path, "wb") as f:
                f.write(_make_rf2_gmt("mesh"))

            with mock.patch.object(ams_crypt, "_library", return_value=None), \
                    mock.patch.object(ams_crypt, "_encryptor",
                                      return_value="rfactorcrypt.exe"), \
                    mock.patch.object(ams_crypt.subprocess, "run", side_effect=run):
                self.assertEqual(ams_crypt.encrypt_assets(root), 1)

            self.assertEqual(ams_crypt.crypt_info(path),
                             (ams_crypt.AMS_SIGNATURE, ams_crypt.AMS_KEY))


class AmsFinalizeTests(unittest.TestCase):
    def test_install_populates_an_existing_empty_location(self):
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            locations = os.path.join(root, "locations")
            dest = os.path.join(locations, "sample")
            os.makedirs(stage)
            os.makedirs(dest)
            with open(os.path.join(stage, "mesh.gmt"), "wb") as f:
                f.write(b"mesh")

            self.assertEqual(
                finalize_track.install_location(stage, locations, "sample"),
                dest)
            with open(os.path.join(dest, "mesh.gmt"), "rb") as f:
                self.assertEqual(f.read(), b"mesh")

    def test_install_keeps_existing_location_when_swap_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            locations = os.path.join(root, "locations")
            dest = os.path.join(locations, "sample")
            os.makedirs(stage)
            os.makedirs(dest)
            with open(os.path.join(stage, "new.txt"), "w") as f:
                f.write("new")
            with open(os.path.join(dest, "old.txt"), "w") as f:
                f.write("old")

            with mock.patch("finalize_track.os.replace",
                            side_effect=PermissionError("location is in use")):
                with self.assertRaises(PermissionError):
                    finalize_track.install_location(stage, locations, "sample")

            self.assertTrue(os.path.isfile(os.path.join(dest, "old.txt")))
            self.assertFalse(os.path.exists(os.path.join(dest, "new.txt")))
            self.assertEqual(os.listdir(locations), ["sample"])

    def test_long_layout_identifier_fits_ams_scene_filename_limit(self):
        venue = "targa_tas_21_s1_high_plains"
        layout = finalize_track.layout_identifier(venue)
        self.assertEqual(len(layout), finalize_track.MAX_LAYOUT_ID_LENGTH)
        self.assertLessEqual(len(layout + ".scn"), 23)
        self.assertEqual(layout, finalize_track.layout_identifier(venue))

    def test_verifier_finds_short_scene_name_from_gdb(self):
        with tempfile.TemporaryDirectory() as root:
            layout_dir = os.path.join(root, "short_layout")
            os.makedirs(layout_dir)
            gdb = os.path.join(layout_dir, "short_layout.gdb")
            scene = os.path.join(layout_dir, "short_layout.scn")
            with open(gdb, "w") as f:
                f.write("short_layout\n")
            with open(scene, "w") as f:
                f.write("CUBEASF\n")
            self.assertEqual(verify_install.installed_scene_path(
                root, "long_venue_name"), scene)

    def test_requires_mas_archives_as_a_pair(self):
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            os.makedirs(stage)
            with open(os.path.join(root, "sample.mas"), "wb") as f:
                f.write(b"mesh archive")
            with self.assertRaisesRegex(RuntimeError, "both sample.mas"):
                finalize_track.stage_mas_archives(root, stage, "sample")

    def test_track_preview_prefers_layout_map_and_skips_tiny_placeholders(self):
        def write_png_header(path, width, height):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            header = (
                b"\x89PNG\r\n\x1a\n"
                + struct.pack(">I", 13)
                + b"IHDR"
                + struct.pack(">II", width, height)
                + b"\x08\x06\x00\x00\x00"
            )
            with open(path, "wb") as f:
                f.write(header)

        with tempfile.TemporaryDirectory() as root:
            write_png_header(os.path.join(root, "map.png"), 800, 600)
            write_png_header(os.path.join(root, "ui", "nords", "preview.png"), 355, 200)
            write_png_header(os.path.join(root, "ui", "nords", "outline.png"), 365, 192)
            # Layout-specific outline beats root map when layout map is missing or tiny.
            write_png_header(os.path.join(root, "nords", "map.png"), 20, 20)
            self.assertEqual(
                build_track.track_preview(root, "nords"),
                os.path.join(root, "ui", "nords", "outline.png"),
            )
            # Full-size layout map beats outline and preview.
            write_png_header(os.path.join(root, "nords", "map.png"), 1579, 1244)
            self.assertEqual(
                build_track.track_preview(root, "nords"),
                os.path.join(root, "nords", "map.png"),
            )

    def test_stages_ams_menu_images_from_ac_track_map(self):
        import numpy as np

        seen_loading_canvas = {}

        def fake_texconv(command, **_kwargs):
            output_dir = command[command.index("-o") + 1]
            image_format = command[command.index("-ft") + 1].upper()
            src = command[-1]
            stem = os.path.splitext(os.path.basename(src))[0]
            out_path = os.path.join(output_dir, stem + "." + image_format)

            if image_format == "TGA":
                if "-w" in command and "-h" in command:
                    tw = int(command[command.index("-w") + 1])
                    th = int(command[command.index("-h") + 1])
                    src_img = finalize_track._read_tga_bgra(src)
                    ys = np.linspace(0, src_img.shape[0] - 1, th).astype(np.intp)
                    xs = np.linspace(0, src_img.shape[1] - 1, tw).astype(np.intp)
                    resized = src_img[np.ix_(ys, xs)]
                    finalize_track._write_tga_bgra(out_path, resized, bottom_up=False)
                else:
                    # Synthetic 200x400 RGBA track map: transparent border + bright vertical stripe
                    arr = np.zeros((400, 200, 4), dtype=np.uint8)
                    arr[40:360, 80:120, :3] = 255
                    arr[40:360, 80:120, 3] = 255
                    finalize_track._write_tga_bgra(out_path, arr, bottom_up=False)
            elif image_format == "JPG":
                seen_loading_canvas["img"] = finalize_track._read_tga_bgra(src)
                with open(out_path, "wb") as f:
                    f.write(b"\xff\xd8\xffJPG")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root:
            preview = os.path.join(root, "map.png")
            layout_dir = os.path.join(root, "layout")
            os.makedirs(layout_dir)
            with open(preview, "wb") as f:
                f.write(b"png")

            with mock.patch.object(finalize_track.subprocess, "run",
                                   side_effect=fake_texconv):
                count = finalize_track.stage_menu_images(
                    preview, layout_dir, "sample_track", "texconv.exe")

            self.assertEqual(count, 2)
            # Loading screen canvas is 1920x1080, dark background, centered bright track.
            canvas = seen_loading_canvas["img"]
            self.assertEqual(canvas.shape, (1080, 1920, 4))
            self.assertLess(int(canvas[0, 0, 0]), 40)
            self.assertGreater(int(canvas[540, 960, 0]), 200)
            with open(os.path.join(layout_dir, "sample_track_loading.jpg"), "rb") as f:
                self.assertEqual(f.read(), b"\xff\xd8\xffJPG")

            # Mini TGA is 252x249 32-bit bottom-up RGBA with transparent corners and visible center.
            mini_path = os.path.join(layout_dir, "sample_trackmini.tga")
            with open(mini_path, "rb") as f:
                hdr = f.read(18)
            self.assertEqual(hdr[2], 2)
            self.assertEqual(struct.unpack_from("<HH", hdr, 12), (252, 249))
            self.assertEqual((hdr[16], hdr[17]), (32, 8))
            mini = finalize_track._read_tga_bgra(mini_path)
            self.assertEqual(int(mini[0, 0, 3]), 0)
            self.assertEqual(int(mini[124, 126, 3]), 255)

    def test_stages_ams_location_layout_and_references(self):
        with tempfile.TemporaryDirectory() as root:
            venue = "sample_track_name_that_exceeds_the_scene_filename_limit"
            layout_id = finalize_track.layout_identifier(venue)
            out_dir = os.path.join(root, venue)
            gmt_dir = os.path.join(out_dir, "gmt")
            tex_dir = os.path.join(out_dir, "textures")
            os.makedirs(gmt_dir)
            os.makedirs(tex_dir)
            rows = []
            for name in ("xfinish", "xsector1", "xsector2"):
                filename = name + ".gmt"
                with open(os.path.join(gmt_dir, filename), "wb") as f:
                    f.write(b"mesh")
                rows.append({
                    "gmt": filename,
                    "mesh": name,
                    "physical": False,
                    "blend": False,
                    "radius": 1.0,
                })
            with open(os.path.join(gmt_dir, "exported.json"), "w") as f:
                import json
                json.dump(rows, f)
            with open(os.path.join(tex_dir, "road.dds"), "wb") as f:
                f.write(b"texture")
            with open(os.path.join(out_dir, venue + ".tdf"), "w") as f:
                f.write("[TRACKVARS]\n")
            for name in (venue + ".mas", venue + "MAP.mas"):
                with open(os.path.join(out_dir, name), "wb") as f:
                    f.write(b"mas archive")

            with mock.patch.object(
                    sys, "argv",
                    ["finalize_track.py", out_dir, "--install",
                     os.path.join(root, "install")]), \
                    mock.patch("ams_crypt.encrypt_assets", return_value=4), \
                    mock.patch("finalize_track.shutil.copytree",
                               side_effect=PermissionError("location is in use")):
                with self.assertRaises(SystemExit):
                    finalize_track.main()

            stage = os.path.join(out_dir, "ams1", venue)
            layout = os.path.join(stage, layout_id)
            self.assertTrue(os.path.isfile(os.path.join(stage, venue + ".tdf")))
            self.assertTrue(os.path.isfile(os.path.join(stage, venue + ".mas")))
            self.assertTrue(os.path.isfile(os.path.join(stage, venue + "MAP.mas")))
            self.assertTrue(os.path.isfile(os.path.join(stage, "gmt", "xfinish.gmt")))
            self.assertTrue(os.path.isfile(os.path.join(stage, "maps", "road.dds")))
            scene_path = os.path.join(layout, layout_id + ".scn")
            self.assertLessEqual(len(os.path.basename(scene_path)), 23)
            with open(scene_path, encoding="utf-8") as f:
                scene = f.read()
            self.assertIn("Light=FDirect01", scene)
            self.assertIn("SearchPath=%s\\%s" % (venue, layout_id), scene)
            self.assertIn("MASFile=%s.MAS" % venue, scene)
            self.assertIn("MASFile=%sMAP.MAS" % venue, scene)
            self.assertIn("SearchPath=%s\\gmt" % venue, scene)
            with open(os.path.join(layout, layout_id + ".gdb"), encoding="utf-8") as f:
                database = f.read()
            self.assertTrue(database.startswith(layout_id + "\n"))
            self.assertIn("GrandPrixName = %s" % venue, database)
            self.assertIn("TerrainDataFile = ..\\%s.tdf" % venue, database)

    def test_texture_target_size_halves_and_snaps_to_dx9_pow2(self):
        self.assertEqual(fix_textures.target_size(4096, 0.5), 2048)
        self.assertEqual(fix_textures.target_size(2048, 0.5), 1024)
        self.assertEqual(fix_textures.target_size(1024, 0.5), 512)
        self.assertEqual(fix_textures.target_size(600, 0.5), 512)
        self.assertEqual(fix_textures.target_size(124, 0.5), 64)
        self.assertEqual(fix_textures.target_size(8, 0.5), 4)
        self.assertEqual(fix_textures.target_size(4, 0.5), 4)
        self.assertEqual(fix_textures.target_size(4096, 1.0), 4096)
        self.assertEqual(fix_textures.target_size(600, 1.0), 1024)


class ConvertMultipleTracksTests(unittest.TestCase):
    def test_runs_all_lines_with_install_auto_and_skips_errors(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[2].endswith("broken"):
                return types.SimpleNamespace(returncode=1)
            if command[2].endswith("oserror"):
                raise OSError("boom")
            return types.SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as root:
            list_file = os.path.join(root, "tracks.txt")
            with open(list_file, "w", encoding="utf-8-sig") as f:
                f.write("\n")
                f.write("# comment\n")
                f.write(";orphan_layout\n")
                f.write("C:\\tracks\\alpha;\n")
                f.write("C:\\tracks\\broken;gp\n")
                f.write("C:\\tracks\\oserror;west\n")
                f.write("C:\\tracks\\beta;normal\n")
                f.write("C:\\tracks\\gamma\n")

            with mock.patch.object(convert_multiple_tracks.subprocess, "run",
                                   side_effect=fake_run):
                succeeded, skipped = convert_multiple_tracks.convert_file(list_file)

            self.assertEqual(len(succeeded), 3)
            self.assertEqual(len(skipped), 3)
            self.assertEqual(
                [c[2:] for c in calls],
                [
                    ["C:\\tracks\\alpha", "--install", "auto"],
                    ["C:\\tracks\\broken", "--install", "auto", "--layout", "gp"],
                    ["C:\\tracks\\oserror", "--install", "auto", "--layout", "west"],
                    ["C:\\tracks\\beta", "--install", "auto", "--layout", "normal"],
                    ["C:\\tracks\\gamma", "--install", "auto"],
                ],
            )


class StandaloneCliTests(unittest.TestCase):
    def test_cli_dispatches_build_track_and_convert_multiple_tracks(self):
        seen = []

        def fake_build():
            seen.append(("build", list(sys.argv)))
            return 0

        def fake_batch():
            seen.append(("batch", list(sys.argv)))
            return 0

        with mock.patch.object(build_track, "main", side_effect=fake_build), \
                mock.patch.object(convert_multiple_tracks, "main", side_effect=fake_batch):
            self.assertEqual(ac2ams1.main(["build_track", "C:\\track", "--hour", "10:00"]), 0)
            self.assertEqual(ac2ams1.main(["convert_multiple_tracks", "tracks.txt"]), 0)
            self.assertEqual(ac2ams1.main(["--stage", "build_track", "C:\\track2"]), 0)

        self.assertEqual(seen[0][0], "build")
        self.assertEqual(seen[0][1][1:], ["C:\\track", "--hour", "10:00"])
        self.assertEqual(seen[1][0], "batch")
        self.assertEqual(seen[1][1][1:], ["tracks.txt"])
        self.assertEqual(seen[2][0], "build")
        self.assertEqual(seen[2][1][1:], ["C:\\track2"])

    def test_cli_stage_dispatch_handles_script_only_modules(self):
        for stage in ("make_aiw", "make_cam"):
            self.assertEqual(ac2ams1.main(["--stage", stage, "--help"]), 0)

    def test_drag_and_drop_directory_and_batch_file(self):
        seen = []

        def fake_build():
            seen.append(("build", list(sys.argv)))
            return 0

        def fake_batch():
            seen.append(("batch", list(sys.argv)))
            return 0

        with tempfile.TemporaryDirectory() as root:
            single_track = os.path.join(root, "targa")
            multi_track = os.path.join(root, "nords")
            batch_file = os.path.join(root, "tracks.txt")
            os.makedirs(single_track)
            os.makedirs(multi_track)
            with open(os.path.join(multi_track, "models_endurance.ini"), "w") as f:
                f.write("")
            with open(os.path.join(multi_track, "models_nordschleife.ini"), "w") as f:
                f.write("")
            with open(batch_file, "w") as f:
                f.write(single_track + ";\n")

            with mock.patch.object(build_track, "main", side_effect=fake_build), \
                    mock.patch.object(convert_multiple_tracks, "main", side_effect=fake_batch), \
                    mock.patch.object(ac2ams1, "_pause_if_explorer"), \
                    mock.patch.object(sys.stdin, "isatty", return_value=True), \
                    mock.patch("builtins.input", return_value="2"):
                self.assertEqual(ac2ams1.main([single_track]), 0)
                self.assertEqual(ac2ams1.main([multi_track]), 0)
                self.assertEqual(ac2ams1.main([batch_file]), 0)

        self.assertEqual(seen[0][0], "build")
        self.assertEqual(seen[0][1][1:], [single_track])
        self.assertEqual(seen[1][0], "build")
        self.assertEqual(seen[1][1][1:], [multi_track, "--layout", "nordschleife"])
        self.assertEqual(seen[2][0], "batch")
        self.assertEqual(seen[2][1][1:], [batch_file])


if __name__ == "__main__":
    unittest.main()
