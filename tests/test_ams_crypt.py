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
        cx, cy, cz, rad = struct.unpack_from("<4f", fast, foff_r + 4 + 16)
        nx, ny, nz, sg = struct.unpack_from("<3fI", fast, noff_r + 4)
        self.assertEqual(flg, 2)
        self.assertEqual(sg, 7)
        self.assertAlmostEqual(nx, 0.0, places=5)
        self.assertAlmostEqual(ny, 1.0, places=5)
        self.assertAlmostEqual(nz, 0.0, places=5)
        # FaceData centroid & bounding-sphere radius rebuilt from vertex geometry
        # (not triangle area 0.5, which is smaller than radius ~0.745356 on small triangles).
        self.assertAlmostEqual(cx, 1.0 / 3.0, places=5)
        self.assertAlmostEqual(cy, 0.0, places=5)
        self.assertAlmostEqual(cz, 1.0 / 3.0, places=5)
        expected_rad = ((2.0 / 3.0) ** 2 + (1.0 / 3.0) ** 2) ** 0.5
        self.assertAlmostEqual(rad, expected_rad, places=5)

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

    def test_texture_scale_min_size_is_inclusive_at_1024_and_excludes_512(self):
        # Default min_size=1024: 1024+ scaled, 512 and smaller left unscaled.
        self.assertEqual(fix_textures.target_dimensions(4096, 2048, 0.5, 1024), (2048, 1024))
        self.assertEqual(fix_textures.target_dimensions(1024, 1024, 0.5, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(1024, 256, 0.5, 1024), (512, 128))
        self.assertEqual(fix_textures.target_dimensions(512, 512, 0.5, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(512, 256, 0.5, 1024), (512, 256))
        self.assertEqual(fix_textures.target_dimensions(256, 256, 0.5, 1024), (256, 256))
        # Non-pow2 below threshold snaps to pow2 without downscaling.
        self.assertEqual(fix_textures.target_dimensions(600, 600, 0.5, 1024), (1024, 1024))
        # min_size=0 scales everything.
        self.assertEqual(fix_textures.target_dimensions(512, 512, 0.5, 0), (256, 256))

        # Destination floor: when texture_scale < 0.5 (e.g. 0.25 or 0.125),
        # scaled textures are not reduced below the largest pow2 < min_size
        # (512 for min_size=1024), while preserving aspect ratio.
        self.assertEqual(fix_textures.target_dimensions(4096, 4096, 0.25, 1024), (1024, 1024))
        self.assertEqual(fix_textures.target_dimensions(4096, 2048, 0.25, 1024), (1024, 512))
        self.assertEqual(fix_textures.target_dimensions(2048, 2048, 0.25, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(2048, 512, 0.25, 1024), (512, 128))
        self.assertEqual(fix_textures.target_dimensions(1024, 1024, 0.25, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(1024, 512, 0.25, 1024), (512, 256))
        self.assertEqual(fix_textures.target_dimensions(1024, 256, 0.25, 1024), (512, 128))
        self.assertEqual(fix_textures.target_dimensions(1024, 4, 0.25, 1024), (512, 4))
        self.assertEqual(fix_textures.target_dimensions(512, 512, 0.25, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(2048, 2048, 0.125, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(1024, 1024, 0.125, 1024), (512, 512))
        self.assertEqual(fix_textures.target_dimensions(512, 512, 0.25, 512), (256, 256))
        self.assertEqual(fix_textures.target_dimensions(1024, 1024, 0.25, 512), (256, 256))
        self.assertEqual(fix_textures.target_dimensions(1024, 1024, 0.25, 0), (256, 256))
        self.assertEqual(fix_textures.target_dimensions(512, 512, 0.25, 0), (128, 128))


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

    def test_load_config_reads_texture_scale_from_ini_and_validates(self):
        import steam_paths

        with tempfile.TemporaryDirectory() as root:
            # Missing ini falls back to defaults.
            cfg = steam_paths.load_config(root)
            self.assertFalse(cfg["exists"])
            self.assertEqual(cfg["texture_scale"], 0.5)
            self.assertEqual(cfg["texture_scale_source"], "default")
            self.assertEqual(cfg["texture_scale_min_size"], 1024)
            self.assertEqual(cfg["texture_scale_min_size_source"], "default")
            self.assertEqual(cfg["road_smoothness"], 0.5)
            self.assertEqual(cfg["road_smoothness_source"], "default")
            self.assertEqual(cfg["road_smooth_sigma"], 4.0)
            self.assertEqual(cfg["mesh_coarsening"], 0.0)
            self.assertEqual(cfg["mesh_coarsening_source"], "default")
            self.assertTrue(cfg["strip_unused_gmt_data"])
            self.assertEqual(cfg["strip_unused_gmt_data_source"], "default")
            self.assertEqual(cfg["track_shadows"], "compact")
            self.assertEqual(cfg["track_shadows_source"], "default")
            self.assertNotIn("road_smooth", cfg)

            # Partial ini marks only specified keys as read from ini.
            ini = os.path.join(root, "ac2ams1.ini")
            with open(ini, "w", encoding="utf-8") as f:
                f.write(
                    "[track]\n"
                    "texture_scale=0.25 # quarter\n"
                    "road_smoothness=0\n"
                    "mesh_coarsening=0.6\n"
                    "strip_unused_gmt_data=false\n"
                    "track_shadows=off\n"
                )
            cfg = steam_paths.load_config(root)
            self.assertTrue(cfg["exists"])
            self.assertEqual(cfg["texture_scale"], 0.25)
            self.assertEqual(cfg["texture_scale_source"], "ini")
            self.assertEqual(cfg["texture_scale_min_size"], 1024)
            self.assertEqual(cfg["texture_scale_min_size_source"], "default")
            self.assertEqual(cfg["road_smoothness"], 0.0)
            self.assertEqual(cfg["road_smoothness_source"], "ini")
            self.assertEqual(cfg["road_smooth_sigma"], 0.0)
            self.assertEqual(cfg["mesh_coarsening"], 0.6)
            self.assertEqual(cfg["mesh_coarsening_source"], "ini")
            self.assertFalse(cfg["strip_unused_gmt_data"])
            self.assertEqual(cfg["strip_unused_gmt_data_source"], "ini")
            self.assertEqual(cfg["track_shadows"], "off")
            self.assertEqual(cfg["track_shadows_source"], "ini")

            # Legacy alias strip_non_collidable_faces still works if present.
            with open(ini, "w", encoding="utf-8") as f:
                f.write("[track]\nstrip_non_collidable_faces=false\n")
            cfg = steam_paths.load_config(root)
            self.assertFalse(cfg["strip_unused_gmt_data"])
            self.assertEqual(cfg["strip_unused_gmt_data_source"], "ini")

            # Uniform road_smoothness [0.0, 1.0] -> road_smooth_sigma [0.0, 8.0]
            # with arbitrary floating-point precision.
            self.assertEqual(steam_paths.road_smoothness_to_sigma(0.0), 0.0)
            self.assertEqual(steam_paths.road_smoothness_to_sigma(0.25), 2.0)
            self.assertEqual(steam_paths.road_smoothness_to_sigma(0.123456), 0.987648)
            self.assertEqual(steam_paths.road_smoothness_to_sigma(0.5), 4.0)
            self.assertEqual(steam_paths.road_smoothness_to_sigma(0.6), 4.8)
            self.assertEqual(steam_paths.road_smoothness_to_sigma(0.75), 6.0)
            self.assertEqual(steam_paths.road_smoothness_to_sigma(1.0), 8.0)
            with open(ini, "w", encoding="utf-8") as f:
                f.write("[track]\nroad_smoothness=0.62512345\n")
            cfg = steam_paths.load_config(root)
            self.assertAlmostEqual(cfg["road_smoothness"], 0.62512345, places=8)
            self.assertEqual(cfg["road_smooth_sigma"], 5.000988)

            # Full ini overrides both defaults.
            with open(ini, "w", encoding="utf-8") as f:
                f.write("[track]\ntexture_scale=0.75\ntexture_scale_min_size=512\n")
            cfg = steam_paths.load_config(root)
            self.assertTrue(cfg["exists"])
            self.assertEqual(cfg["texture_scale"], 0.75)
            self.assertEqual(cfg["texture_scale_source"], "ini")
            self.assertEqual(cfg["texture_scale_min_size"], 512)
            self.assertEqual(cfg["texture_scale_min_size_source"], "ini")

            # Out-of-range scale raises ValueError.
            with open(ini, "w", encoding="utf-8") as f:
                f.write("[track]\ntexture_scale=2.0\n")
            with self.assertRaises(ValueError):
                steam_paths.load_config(root)

            # Negative min size raises ValueError.
            with open(ini, "w", encoding="utf-8") as f:
                f.write("[track]\ntexture_scale_min_size=-1\n")
            with self.assertRaises(ValueError):
                steam_paths.load_config(root)

            # Out-of-range / non-finite road_smoothness raises ValueError.
            for bad in ("-0.1", "1.1", "nan", "inf"):
                with open(ini, "w", encoding="utf-8") as f:
                    f.write("[track]\nroad_smoothness=%s\n" % bad)
                with self.assertRaises(ValueError):
                    steam_paths.load_config(root)

            # Out-of-range / non-finite mesh_coarsening raises ValueError.
            for bad in ("-0.01", "1.01", "nan", "inf", "abc"):
                with open(ini, "w", encoding="utf-8") as f:
                    f.write("[track]\nmesh_coarsening=%s\n" % bad)
                with self.assertRaises(ValueError):
                    steam_paths.load_config(root)

            # Invalid boolean for strip_unused_gmt_data raises ValueError.
            for bad in ("maybe", "2", ""):
                with open(ini, "w", encoding="utf-8") as f:
                    f.write("[track]\nstrip_unused_gmt_data=%s\n" % bad)
                with self.assertRaises(ValueError):
                    steam_paths.load_config(root)

            # Invalid track_shadows mode raises ValueError.
            for bad in ("ultra", "on", ""):
                with open(ini, "w", encoding="utf-8") as f:
                    f.write("[track]\ntrack_shadows=%s\n" % bad)
                with self.assertRaises(ValueError):
                    steam_paths.load_config(root)

    def test_patch_tdf_preserves_template_bump_defaults(self):
        import convert_track

        sample_tdf = (
            "[TRACKVARS]\n"
            "RoadBumpAmp=0.010\n"
            "RoadBumpLen=13.0\n"
            "RumbleBumpAmp=0.015\n"
            "RumbleBumpLen=8.0\n"
            "[FEEDBACK]\n"
            "Dry=1.00 Wet=0.80 BumpAmp=RoadBumpAmp BumpWavelen=RoadBumpLen\n"
            "Materials=road\n"
        )
        with tempfile.TemporaryDirectory() as root:
            tdf_path = os.path.join(root, "terrain.tdf")
            with open(tdf_path, "w", encoding="utf-8") as f:
                f.write(sample_tdf)

            patched, applied = convert_track.patch_tdf(tdf_path, {"road": 0.97}, ["road"])
            self.assertEqual(applied, {"road": 0.97})
            self.assertIn("Dry=0.970", patched)
            self.assertIn("RoadBumpAmp=0.010", patched)
            self.assertIn("RoadBumpLen=13.0", patched)
            self.assertIn("RumbleBumpAmp=0.015", patched)
            self.assertIn("RumbleBumpLen=8.0", patched)

    def test_road_smooth_preserves_slope_and_crest_while_damping_micro_bumps(self):
        import numpy as np
        import road_smooth

        # Build a 20m x 10m grid (0.5m spacing) with a smooth sloped hill + quadratic crest.
        xs = np.linspace(0.0, 20.0, 41)
        zs = np.linspace(0.0, 10.0, 21)
        gx, gz = np.meshgrid(xs, zs, indexing="ij")
        nx, nz = gx.shape
        # Exact quadratic surface: 5% slope + gentle crest + 2% banking.
        y_true = 0.05 * gx - 0.002 * (gx - 10.0) ** 2 + 0.02 * gz
        pos_clean = np.column_stack((gx.ravel(), y_true.ravel(), gz.ravel()))

        tris = []
        for i in range(nx - 1):
            for j in range(nz - 1):
                v00 = i * nz + j
                v10 = (i + 1) * nz + j
                v01 = i * nz + (j + 1)
                v11 = (i + 1) * nz + (j + 1)
                tris.append((v00, v10, v11))
                tris.append((v00, v11, v01))
        tris = np.array(tris, dtype=np.int64)

        # 0. sigma=0 disables smoothing completely (returns positions unchanged).
        sm_zero, st_zero = road_smooth.smooth_positions_mls(pos_clean, tris, sigma=0.0)
        self.assertEqual(st_zero["smoothed"], 0)
        self.assertTrue(np.array_equal(sm_zero, pos_clean))

        # 1. Clean quadratic hill/crest/banking must be reproduced with ~0 distortion
        #    at both default and large sigma.
        for s in (2.0, 5.0):
            sm_clean, _ = road_smooth.smooth_positions_mls(pos_clean, tris, sigma=s)
            self.assertLess(float(np.abs(sm_clean[:, 1] - pos_clean[:, 1]).max()), 1e-4)

        # 2. High-frequency +/-5mm micro-bumps must be strongly damped across the
        #    surface, and larger sigma must be strictly smoother (monotonic).
        rng = np.random.default_rng(42)
        noise = rng.normal(0.0, 0.005, size=len(pos_clean))
        pos_noisy = pos_clean.copy()
        pos_noisy[:, 1] += noise
        sm_2, stats = road_smooth.smooth_positions_mls(pos_noisy, tris, sigma=2.0)
        sm_4, _ = road_smooth.smooth_positions_mls(pos_noisy, tris, sigma=4.0)

        is_interior = (
            (gx.ravel() > 1.5) & (gx.ravel() < 18.5)
            & (gz.ravel() > 1.5) & (gz.ravel() < 8.5)
        )
        raw_err = float(np.std(pos_noisy[is_interior, 1] - pos_clean[is_interior, 1]))
        sm2_err = float(np.std(sm_2[is_interior, 1] - pos_clean[is_interior, 1]))
        sm4_err = float(np.std(sm_4[is_interior, 1] - pos_clean[is_interior, 1]))
        self.assertLess(sm2_err, raw_err * 0.4)
        self.assertLess(sm4_err, sm2_err)
        # Whole-mesh (including edges) should also be smoother at larger sigma.
        self.assertLess(
            float(np.std(sm_4[:, 1] - pos_clean[:, 1])),
            float(np.std(sm_2[:, 1] - pos_clean[:, 1])),
        )
        self.assertGreater(stats["smoothed"], 0)

        # 3. Overpass 6m above must not bleed into lower road even at large sigma.
        upper = pos_clean.copy()
        upper[:, 1] += 6.0
        both_pos = np.vstack((pos_clean, upper))
        both_tris = np.vstack((tris, tris + len(pos_clean)))
        for s in (2.0, 5.0):
            sm_both, _ = road_smooth.smooth_positions_mls(both_pos, both_tris, sigma=s)
            self.assertLess(float(np.abs(sm_both[:, 1] - both_pos[:, 1]).max()), 1e-4)


    def test_instance_identifier_caps_overlong_names_for_ams1(self):
        used = {"skyboxi", "clouds", "sky", "xpitin", "xpitout"}
        # Short and special names pass through unchanged.
        self.assertEqual(finalize_track.instance_identifier("xfinish", used), "xfinish")
        self.assertEqual(
            finalize_track.instance_identifier("a" * 31, used), "a" * 31
        )

        # Laguna Seca names that overflowed AMS1's 32-byte Instance buffer.
        long_names = [
            "pitstop__metal_fence_extruded_001_SUB0",
            "pitstop__metal_fence_extruded_001_SUB1",
            "corkscrew_traliccio_fili_001_SUB1",
            "ADV_corkscrew_mazda_coopertires_navidad_SUB0",
            "ADV_corkscrew_mazda_coopertires_navidad_SUB1",
        ]
        shortened = [finalize_track.instance_identifier(n, used) for n in long_names]
        for s in shortened:
            self.assertLessEqual(len(s), finalize_track.MAX_INSTANCE_NAME_LENGTH)
        self.assertEqual(len({s.casefold() for s in shortened}), len(long_names))

        # Deterministic without collision set.
        self.assertEqual(
            finalize_track.instance_identifier(long_names[0]),
            finalize_track.instance_identifier(long_names[0]),
        )

        # Duplicate short names get disambiguated when a used set is supplied.
        dup_used = set()
        first = finalize_track.instance_identifier("x" * 20, dup_used)
        second = finalize_track.instance_identifier("x" * 20, dup_used)
        self.assertNotEqual(first.casefold(), second.casefold())
        self.assertLessEqual(len(second), finalize_track.MAX_INSTANCE_NAME_LENGTH)

    def test_read_ini_and_cameras_tolerate_preamble_and_bom(self):
        import convert_track
        import make_cam

        with tempfile.TemporaryDirectory() as root:
            surf = os.path.join(root, "surfaces.ini")
            with open(surf, "wb") as f:
                f.write(
                    b"\xef\xbb\xbfV1.0\r\n"
                    b"[SURFACE_0]\r\n"
                    b"// comment\r\n"
                    b"KEY=ROAD\r\n"
                    b"FRICTION=0.97\r\n"
                )
            cp = convert_track.read_ini(surf)
            self.assertEqual(cp["SURFACE_0"]["KEY"], "ROAD")
            self.assertEqual(cp["SURFACE_0"]["FRICTION"], "0.97")

            cam = os.path.join(root, "cameras.ini")
            with open(cam, "wb") as f:
                f.write(
                    b"\xef\xbb\xbfV1.0\r\n"
                    b"[CAMERA_0]\r\n"
                    b"POSITION=1,2,3\r\n"
                    b"FORWARD=0,0,1\r\n"
                )
            cams = make_cam.read_cameras(root)
            self.assertEqual(len(cams), 1)
            self.assertEqual(cams[0]["pos"], [-1.0, 2.0, 3.0])

    def test_long_texture_filenames_stay_within_gmt_limit(self):
        import convert_track

        long_a = "veg_nurb_tree_pine_b_xlarge_background_002_diff_packmaskNEW.dds"
        long_b = "veg_nurb_tree_pine_b_xlarge_background_002_diff_packmaskOLD.dds"
        mapped = convert_track.texture_filenames([long_a, long_b, "short.dds"])
        self.assertEqual(mapped["short.dds"], "short.dds")
        for orig in (long_a, long_b):
            self.assertLessEqual(len(mapped[orig]), convert_track.MAX_TEX_FILENAME)
            self.assertTrue(mapped[orig].endswith(".dds"))
        self.assertNotEqual(mapped[long_a].lower(), mapped[long_b].lower())

        # Suffixes appended in bake_layers keep total filename <= MAX_TEX_FILENAME
        # while preserving the trailing suffix (_a102, _a102_d80, _baked, _base).
        stem = os.path.splitext(mapped[long_a])[0]
        for suf in ("_a102", "_a102_d80", "_baked", "_base", "_detail_nm"):
            out = convert_track.fit_tex_stem(stem, suf) + ".dds"
            self.assertLessEqual(len(out), convert_track.MAX_TEX_FILENAME)
            self.assertTrue(out.endswith(suf + ".dds"))

        # verify_install.read_gmt reads exact GMT texture entries (catching names
        # truncated before ".dds").
        with tempfile.TemporaryDirectory() as root:
            gmt_path = os.path.join(root, "trunc.gmt")
            trunc = "veg_nurb_tree_pine_b_xlarge_background_002_diff_packmaskNEW_a1"
            with open(gmt_path, "wb") as f:
                f.write(_make_rf2_gmt(
                    "tree",
                    shader="L2BUMPSPECMAPT0",
                    textures=[
                        (trunc, 0x88, 1, 3, 0, 191),
                        ("_flat_spec.dds", 0x08, 2, 4, 1, 0),
                        ("_flat_nm.dds", 0x08, 5, 4, 2, 0),
                    ],
                ))
            parsed = verify_install.read_gmt(gmt_path)
            self.assertIn(trunc.encode("ascii"), parsed["textures"])

    def test_kn5_reads_skinned_mesh_nodes(self):
        import kn5

        def kstr(s):
            b = s.encode("utf-8")
            return struct.pack("<I", len(b)) + b

        buf = bytearray(b"sc6969")
        buf += struct.pack("<II", 6, 0)  # version 6 + extra u32
        buf += struct.pack("<I", 0)      # 0 textures
        # 1 minimal material
        buf += struct.pack("<I", 1)
        buf += kstr("marshal_mat") + kstr("ksPerPixel")
        buf += struct.pack("<BBI", 0, 0, 0)
        buf += struct.pack("<II", 0, 0)  # 0 props, 0 textures
        # Root type=1 node with 1 skinned child (type=3)
        buf += struct.pack("<I", 1) + kstr("root") + struct.pack("<IB", 1, 1)
        buf += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        # Type=3 skinned mesh: cs, vis, tr BEFORE bones; ends at lod_out (no sphere/renderable)
        buf += struct.pack("<I", 3) + kstr("Marshall_02") + struct.pack("<IB", 0, 1)
        buf += struct.pack("<BBB", 1, 1, 0)  # cast_shadows, visible, transparent
        buf += struct.pack("<I", 1) + kstr("Hips") + struct.pack("<16f", *([0.0] * 16))
        buf += struct.pack("<I", 3)          # 3 vertices * 76 bytes
        for x in (0.0, 1.0, 2.0):
            buf += struct.pack("<3f3f2f3f4f4f",
                               x, 1.5, 0.0,       # pos
                               0.0, 1.0, 0.0,     # normal
                               0.25, 0.75,        # uv
                               1.0, 0.0, 0.0,     # tangent
                               1.0, 0.0, 0.0, 0.0,# bone weights
                               0.0, 0.0, 0.0, 0.0)# bone indices
        buf += struct.pack("<I3H", 3, 0, 1, 2)
        buf += struct.pack("<IIff", 0, 0, 0.0, 250.0)  # material_id, layer, lod_in, lod_out

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "marshal.kn5")
            with open(path, "wb") as f:
                f.write(buf)
            k = kn5.KN5(path, geometry=True)
            self.assertEqual(k.consumed, k.size)
            skinned = [n for n in k.walk() if n.type == 3]
            self.assertEqual(len(skinned), 1)
            n = skinned[0]
            self.assertEqual((n.cast_shadows, n.visible, n.transparent, n.renderable), (1, 1, 0, 1))
            self.assertEqual(n.lod_out, 250.0)
            self.assertEqual(n.verts, [(0.0, 1.5, 0.0), (1.0, 1.5, 0.0), (2.0, 1.5, 0.0)])
            self.assertEqual(n.normals[0], (0.0, 1.0, 0.0))
            self.assertEqual(n.uvs[0], (0.25, 0.75))
            self.assertEqual(n.indices, (0, 1, 2))

    def test_reserved_null_texture_and_render_false_timing_and_collision(self):
        import json
        import convert_track

        mapped = convert_track.texture_filenames(["NULL.dds", "NONE.dds", "ok.dds"])
        self.assertEqual(mapped["NULL.dds"], "tex_null.dds")
        self.assertEqual(mapped["NONE.dds"], "tex_none.dds")
        self.assertEqual(mapped["ok.dds"], "ok.dds")

        mats = convert_track.Materials()
        self.assertEqual(mats.rf2_name("NULL", "NULL"), "mat_null")
        self.assertEqual(mats.rf2_name("NULL", "NULL", "wall"), "wall_NULL")

        # gmt_rf1 rewrites reserved NULL.dds texture record without error.
        rf2 = _make_rf2_gmt(
            "1WALL",
            shader="L2DIFFUSET0",
            textures=[("NULL.dds", 0x18, 1, 3, 0, 0)],
        )
        rf1 = gmt_rf1.convert_rf2_to_rf1(rf2)
        self.assertIn(b"tex_null.dds\x00", rf1)
        self.assertNotIn(b"NULL.dds\x00", rf1)

        # finalize_track emits Response=VEHICLE,TIMING for timing strips (which
        # omit "render") AND Render=False for collision-only shells.
        with tempfile.TemporaryDirectory() as root:
            venue = "sample_ra"
            out_dir = os.path.join(root, venue)
            gmt_dir = os.path.join(out_dir, "gmt")
            tex_dir = os.path.join(out_dir, "textures")
            os.makedirs(gmt_dir)
            os.makedirs(tex_dir)
            rows = [
                {"gmt": "xfinish.gmt", "mesh": "xfinish", "physical": True,
                 "timing": True, "tris": 2},
                {"gmt": "xsector1.gmt", "mesh": "xsector1", "physical": True,
                 "timing": True, "tris": 2},
                {"gmt": "xsector2.gmt", "mesh": "xsector2", "physical": True,
                 "timing": True, "tris": 2},
                {"gmt": "1WALL_001.gmt", "mesh": "1WALL_001", "physical": True,
                 "render": False, "tris": 4},
                {"gmt": "vis.gmt", "mesh": "vis", "physical": False,
                 "render": True, "tris": 2},
            ]
            for r in rows:
                with open(os.path.join(gmt_dir, r["gmt"]), "wb") as f:
                    f.write(b"mesh")
            with open(os.path.join(gmt_dir, "exported.json"), "w") as f:
                json.dump(rows, f)
            with open(os.path.join(out_dir, venue + ".tdf"), "w") as f:
                f.write("[TRACKVARS]\n")

            with mock.patch.object(sys, "argv", ["finalize_track.py", out_dir]), \
                    mock.patch("ams_crypt.encrypt_assets", return_value=3):
                finalize_track.main()

            scn_path = os.path.join(out_dir, "ams1", venue, venue, venue + ".scn")
            with open(scn_path, encoding="utf-8") as f:
                scene = f.read()
            self.assertIn("Instance=xfinish\n{\n  Render=False Change=False VisGroups=(32)\n"
                          "  MeshFile=xfinish.gmt CollTarget=True HATTarget=False\n"
                          "  Response=VEHICLE,TIMING\n}", scene)
            self.assertIn("Instance=1WALL_001\n{\n  Render=False Change=False\n"
                          "  MeshFile=1WALL_001.gmt CollTarget=True HATTarget=False\n}", scene)
            self.assertIn("Instance=vis\n{\n  MeshFile=vis.gmt CollTarget=False HATTarget=False ShadowReceiver=False\n}", scene)

    def test_fix_textures_reencodes_malformed_dds_byte_size(self):
        # 4x4 DXT5 with 3 mips should be 128 + 16*3 = 176 bytes; Road Atlanta's
        # embedded NULL.dds has 96 bytes of body (224 bytes total), causing AMS1
        # to fail loading it.
        self.assertEqual(fix_textures.expected_dds_bytes(4, 4, b"DXT5", 3), 176)
        self.assertEqual(fix_textures.expected_dds_bytes(4, 4, b"DXT1", 1), 136)
        self.assertEqual(fix_textures.expected_dds_bytes(4, 4, b"DXT1", 0), 136)

        hdr = bytearray(128)
        hdr[0:4] = b"DDS "
        struct.pack_into("<I", hdr, 4, 124)
        struct.pack_into("<I", hdr, 8, 0xA1007)
        struct.pack_into("<II", hdr, 12, 4, 4)
        struct.pack_into("<I", hdr, 20, 16)
        struct.pack_into("<I", hdr, 28, 3)
        struct.pack_into("<II", hdr, 76, 32, 0x4)
        hdr[84:88] = b"DXT5"
        struct.pack_into("<I", hdr, 108, 0x401008)

        seen_cmds = []

        def fake_run(cmd, **_kwargs):
            seen_cmds.append(cmd)
            out_dir = cmd[cmd.index("-o") + 1]
            with open(os.path.join(out_dir, "tex_null.dds"), "wb") as f:
                f.write(bytes(hdr) + bytes(48))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root:
            tex_dir = os.path.join(root, "textures")
            os.makedirs(tex_dir)
            bad = os.path.join(tex_dir, "tex_null.dds")
            with open(bad, "wb") as f:
                f.write(bytes(hdr) + bytes(96))  # 224 bytes instead of 176

            with mock.patch.object(sys, "argv", ["fix_textures.py", tex_dir, "--jobs", "1"]), \
                    mock.patch.object(fix_textures.subprocess, "run", side_effect=fake_run):
                fix_textures.main()

            self.assertEqual(len(seen_cmds), 1)
            self.assertEqual(os.path.getsize(bad), 176)

    def test_mesh_coarsening_role_classification_and_monotonic_ratios(self):
        import mesh_coarsen

        # Skipped roles: tiny meshes, backdrops, timing, non-rendered non-physical.
        self.assertIsNone(mesh_coarsen.classify_mesh_role(
            {"render": True, "physical": False, "tris": 32}))
        self.assertIsNone(mesh_coarsen.classify_mesh_role(
            {"render": True, "physical": False, "backdrop": True, "tris": 500}))
        self.assertIsNone(mesh_coarsen.classify_mesh_role(
            {"render": False, "physical": True, "timing": True, "tris": 500}))
        self.assertIsNone(mesh_coarsen.classify_mesh_role(
            {"render": False, "physical": False, "tris": 500}))

        # Active roles.
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": False, "physical": True, "surface": "ROAD", "tris": 500}),
            "road_physical",
        )
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": True, "physical": True, "surface": "GRASS", "tris": 500}),
            "road_physical",
        )
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": False, "physical": True, "surface": "WALL", "tris": 500}),
            "collision_offtrack",
        )
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": False, "physical": True, "surface": "GRASS", "tris": 500}),
            "collision_offtrack",
        )
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": True, "physical": False, "decal": True, "tris": 500}),
            "road_physical",
        )
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": True, "physical": False, "track_surface": True, "tris": 500}),
            "track_visual",
        )
        self.assertEqual(
            mesh_coarsen.classify_mesh_role(
                {"render": True, "physical": False, "track_surface": False, "tris": 500}),
            "scenery",
        )

        # Disabled at 0.0; strictly decreasing (stronger coarsening) as c -> 1.0.
        for role, expected_min in mesh_coarsen.ROLE_MIN_RATIO.items():
            self.assertEqual(mesh_coarsen.coarsen_ratio(0.0, role), 1.0)
            r25 = mesh_coarsen.coarsen_ratio(0.25, role)
            r50 = mesh_coarsen.coarsen_ratio(0.50, role)
            r75 = mesh_coarsen.coarsen_ratio(0.75, role)
            r100 = mesh_coarsen.coarsen_ratio(1.0, role)
            self.assertTrue(1.0 > r25 > r50 > r75 > r100 == expected_min)

        # Invalid coarsening values raise ValueError.
        for bad in (-0.1, 1.1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                mesh_coarsen.coarsen_ratio(bad, "scenery")

        # Early no-op guard returns input unchanged without needing Blender.
        v = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        u = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        f = [(0, 1, 2)]
        n = [(0.0, 0.0, 1.0)] * 3
        self.assertEqual(mesh_coarsen.coarsen_geometry(v, u, f, n, 1.0), (v, u, f, n))
        self.assertEqual(mesh_coarsen.coarsen_geometry(v, u, f, n, 0.5), (v, u, f, n))

    def test_normal_dedup_scales_with_mesh_coarsening_and_preserves_creases(self):
        # 0.0 preserves legacy 500.0 quantization; higher coarsening loosens monotonically.
        self.assertEqual(gmt_rf1.normal_dedup_quant(0.0), gmt_rf1.DEFAULT_NORMAL_QUANT)
        q25 = gmt_rf1.normal_dedup_quant(0.25)
        q50 = gmt_rf1.normal_dedup_quant(0.50)
        q75 = gmt_rf1.normal_dedup_quant(0.75)
        q100 = gmt_rf1.normal_dedup_quant(1.0)
        self.assertTrue(gmt_rf1.DEFAULT_NORMAL_QUANT > q25 > q50 > q75 > q100 > 6.0)
        for bad in (-0.1, 1.1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                gmt_rf1.normal_dedup_quant(bad)

        # Build 3 vertices at the same (pos, uv):
        #   v0: normal (0, 1, 0)
        #   v1: normal tilted ~2.5 deg (sin=0.0436, cos=0.9990) -> smooth jitter
        #   v2: normal tilted 90 deg (1, 0, 0) -> hard architectural crease
        import math
        a = math.radians(2.5)
        verts = (
            struct.pack("<6f2I", 1.0, 2.0, 3.0, 0.0, 1.0, 0.0, 0xFFFFFFFF, 0)
            + struct.pack("<6f2I", 1.0, 2.0, 3.0, math.sin(a), math.cos(a), 0.0, 0xFFFFFFFF, 0)
            + struct.pack("<6f2I", 1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0xFFFFFFFF, 0)
        )
        uvs = struct.pack("<8f", 0.25, 0.75, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) * 3

        # At coarsening=0.0 (K=500): all 3 remain separate (legacy behavior).
        q0 = gmt_rf1.normal_dedup_quant(0.0)
        _, _, _, vc0, _ = gmt_rf1._dedup_mesh_vertices(verts, uvs, None, 3, normal_quant=q0)
        self.assertEqual(vc0, 3)

        # At coarsening=1.0 (K~=7.16, ~8 deg): v0 and v1 merge, 90 deg crease v2 stays split!
        nv_fast, nu_fast, _, vc_fast, rm_fast = gmt_rf1._dedup_mesh_vertices(
            verts, uvs, None, 3, normal_quant=q100)
        self.assertEqual(vc_fast, 2)
        self.assertEqual(int(rm_fast[0]), int(rm_fast[1]))
        self.assertNotEqual(int(rm_fast[0]), int(rm_fast[2]))

        # NumPy and pure-Python paths must stay byte-for-byte identical.
        with mock.patch.object(gmt_rf1, "_np", None):
            nv_py, nu_py, _, vc_py, rm_py = gmt_rf1._dedup_mesh_vertices(
                verts, uvs, None, 3, normal_quant=q100)
        self.assertEqual((nv_fast, nu_fast, vc_fast, list(rm_fast)),
                         (nv_py, nu_py, vc_py, list(rm_py)))

    def test_billboard_card_thinning_spatial_uniformity_and_determinism(self):
        import mesh_coarsen

        # Role classification: only visual non-physical ksGrass / ksTree >= MIN_TRIS.
        self.assertEqual(
            mesh_coarsen.classify_billboard_role(
                {"render": True, "physical": False, "shader": "ksGrass", "tris": 200}),
            "grass_cards",
        )
        self.assertEqual(
            mesh_coarsen.classify_billboard_role(
                {"render": True, "physical": False, "shader": "ksTree", "tris": 200}),
            "tree_cards",
        )
        for skipped in (
            {"render": True, "physical": False, "shader": "ksPerPixelAT", "tris": 200},
            {"render": True, "physical": False, "shader": "ksGrass", "tris": 32},
            {"render": True, "physical": True, "shader": "ksGrass", "tris": 200},
            {"render": True, "physical": False, "shader": "ksTree", "backdrop": True, "tris": 200},
            {"render": True, "physical": False, "shader": "ksTree", "decal": True, "tris": 200},
        ):
            self.assertIsNone(mesh_coarsen.classify_billboard_role(skipped))

        # Monotonic keep ratios.
        for role, (min_keep, _max_c) in mesh_coarsen.BILLBOARD_ROLES.items():
            self.assertEqual(mesh_coarsen.billboard_keep_ratio(0.0, role), 1.0)
            k50 = mesh_coarsen.billboard_keep_ratio(0.5, role)
            k100 = mesh_coarsen.billboard_keep_ratio(1.0, role)
            self.assertTrue(1.0 > k50 > k100 == min_keep)

        # Build 10x10 grid of 100 disconnected 2-tri grass quads (200 tris).
        verts, uvs, faces, norms = [], [], [], []
        for gx in range(10):
            for gz in range(10):
                x0, z0 = gx * 5.0, gz * 5.0
                o = len(verts)
                verts.extend([
                    (x0, 0.0, z0), (x0 + 1.0, 0.0, z0),
                    (x0 + 1.0, 1.0, z0), (x0, 1.0, z0),
                ])
                uvs.extend([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
                norms.extend([(0.0, 1.0, 0.0)] * 4)
                faces.extend([(o, o + 1, o + 2), (o, o + 2, o + 3)])

        # c=0.0 -> untouched
        self.assertEqual(
            mesh_coarsen.thin_billboard_cards(verts, uvs, faces, norms, 1.0),
            (verts, uvs, faces, norms),
        )
        # c=0.5 (keep=0.65) and c=1.0 (keep=0.30): deterministic & monotonic
        v50, u50, f50, n50 = mesh_coarsen.thin_billboard_cards(
            verts, uvs, faces, norms, mesh_coarsen.billboard_keep_ratio(0.5, "grass_cards"),
            max_comp_tris=16,
        )
        v100, u100, f100, n100 = mesh_coarsen.thin_billboard_cards(
            verts, uvs, faces, norms, mesh_coarsen.billboard_keep_ratio(1.0, "grass_cards"),
            max_comp_tris=16,
        )
        v100_b, u100_b, f100_b, n100_b = mesh_coarsen.thin_billboard_cards(
            verts, uvs, faces, norms, mesh_coarsen.billboard_keep_ratio(1.0, "grass_cards"),
            max_comp_tris=16,
        )
        self.assertEqual((v100, u100, f100, n100), (v100_b, u100_b, f100_b, n100_b))
        self.assertEqual(len(f50), 130)   # 65 quads * 2 tris
        self.assertEqual(len(f100), 60)   # 30 quads * 2 tris
        self.assertEqual(len(u100), len(v100))
        self.assertEqual(len(n100), len(v100))
        # Spatial uniformity: all 4 quadrants of the 10x10 grid retain cards.
        quads = [0, 0, 0, 0]
        for a, b, c in f100:
            cx = (v100[a][0] + v100[b][0] + v100[c][0]) / 3.0
            cz = (v100[a][2] + v100[b][2] + v100[c][2]) / 3.0
            q = (1 if cx >= 25.0 else 0) + (2 if cz >= 25.0 else 0)
            quads[q] += 1
        for count in quads:
            self.assertGreaterEqual(count, 10)  # each quadrant keeps >= 5 quads

        # Crossed 4-tri X-trees sharing center axis vertices stay whole (divisible by 4).
        xv, xu, xf, xn = [], [], [], []
        for k in range(40):
            x0, z0 = (k % 8) * 10.0, (k // 8) * 10.0
            o = len(xv)
            # Plane 1 + Plane 2 sharing center spine (x0, 0..4, z0)
            xv.extend([
                (x0 - 1.0, 0.0, z0), (x0, 0.0, z0), (x0, 4.0, z0), (x0 - 1.0, 4.0, z0),
                (x0, 0.0, z0), (x0 + 1.0, 0.0, z0), (x0 + 1.0, 4.0, z0), (x0, 4.0, z0),
            ])
            xu.extend([(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)] * 2)
            xn.extend([(0.0, 1.0, 0.0)] * 8)
            xf.extend([
                (o, o + 1, o + 2), (o, o + 2, o + 3),
                (o + 4, o + 5, o + 6), (o + 4, o + 6, o + 7),
            ])
        _, _, xf50, _ = mesh_coarsen.thin_billboard_cards(
            xv, xu, xf, xn, 0.5, max_comp_tris=128)
        self.assertEqual(len(xf50), 80)  # 20 whole 4-tri X-trees kept
        self.assertEqual(len(xf50) % 4, 0)

    def test_strip_faces_on_non_collidable_gmts(self):
        rf2_buf = bytearray(_make_rf2_gmt(
            "scenery",
            shader="L2DIFFUSET0",
            textures=[("wall.dds", 0x18, 1, 3, 0, 0)],
        ))
        # Give vertex 2 a non-collinear Z so the triangle has non-zero area.
        voff = struct.unpack_from("<I", rf2_buf, 0x140)[0] + 4
        struct.pack_into("<3f", rf2_buf, voff + 2 * gmt_rf1.RF2_VERTEX_SIZE, 0.0, 1.0, 4.0)
        rf2 = bytes(rf2_buf)
        with_faces = gmt_rf1.convert_rf2_to_rf1(rf2, include_faces=True)
        no_faces = gmt_rf1.convert_rf2_to_rf1(rf2, include_faces=False)
        self.assertTrue(gmt_rf1.is_rf1_gmt(no_faces))

        # Check RF1 header at 0x174: nmesh, moff, nface, foff, nnorm, noff, unk, voff
        nm1, mo1, nf1, fo1, nn1, no1, _, vo1 = struct.unpack_from("<8I", with_faces, 0x174)
        nm0, mo0, nf0, fo0, nn0, no0, _, vo0 = struct.unpack_from("<8I", no_faces, 0x174)
        self.assertEqual((nm0, mo0), (nm1, mo1))
        self.assertGreater(nf1, 0)
        self.assertGreater(nn1, 0)
        self.assertEqual((nf0, fo0, nn0, no0), (0, 0, 0, 0))
        self.assertGreater(vo0, 0)
        expected_saved = nf1 * gmt_rf1.FACE_SIZE + nn1 * gmt_rf1.NORMAL_SIZE
        self.assertEqual(len(with_faces) - len(no_faces), expected_saved)

        # Mesh descriptor vertex/triangle counts and material table remain intact.
        m1 = struct.unpack_from("<10I", with_faces, gmt_rf1.RF1_HEADER_SIZE)
        m0 = struct.unpack_from("<10I", no_faces, gmt_rf1.RF1_HEADER_SIZE)
        self.assertEqual(m0[6], m1[6])  # new_vcount
        self.assertEqual(m0[8], m1[8])  # m_tcount
        mat_off0 = struct.unpack_from("<I", no_faces, 0)[0] + 4
        self.assertEqual(struct.unpack_from("<I", no_faces, mat_off0)[0], 1)

        # Pure-Python fallback parity with include_faces=False.
        with mock.patch.object(gmt_rf1, "_np", None):
            no_faces_py = gmt_rf1.convert_rf2_to_rf1(rf2, include_faces=False)
        self.assertEqual(no_faces, no_faces_py)

        # ams_crypt.encrypt_assets strips faces only on non-collidable GMTs.
        with tempfile.TemporaryDirectory() as root:
            phys_p = os.path.join(root, "1ROAD.gmt")
            vis_p = os.path.join(root, "tree.gmt")
            with open(phys_p, "wb") as f:
                f.write(rf2)
            with open(vis_p, "wb") as f:
                f.write(rf2)

            seen_flags = {}

            def fake_encrypt(src, dst, key, sig):
                with open(src, "rb") as fh:
                    raw = fh.read()
                _, _, nf, _, nn, _, _, _ = struct.unpack_from("<8I", raw, 0x174)
                seen_flags[os.path.basename(src)] = (nf, nn)
                with open(dst, "wb") as fh:
                    fh.write(struct.pack("<QQ", sig ^ key, key))

            fake_tools = types.SimpleNamespace(encrypt_file=fake_encrypt)
            with mock.patch.object(ams_crypt, "_library", return_value=fake_tools):
                ams_crypt.encrypt_assets(root, collidable_gmts={"1road.gmt"})

            self.assertGreater(seen_flags["1ROAD.gmt"][0], 0)
            self.assertEqual(seen_flags["tree.gmt"], (0, 0))

            # finalize_track honors --no-strip-non-collidable-faces vs enabled default.
            import json
            out_dir = os.path.join(root, "sample_strip")
            gmt_dir = os.path.join(out_dir, "gmt")
            os.makedirs(gmt_dir)
            rows = [
                {"gmt": "xfinish.gmt", "mesh": "xfinish", "physical": True, "timing": True, "tris": 2},
                {"gmt": "xsector1.gmt", "mesh": "xsector1", "physical": True, "timing": True, "tris": 2},
                {"gmt": "xsector2.gmt", "mesh": "xsector2", "physical": True, "timing": True, "tris": 2},
                {"gmt": "tree.gmt", "mesh": "tree", "physical": False, "render": True, "tris": 2},
            ]
            for r in rows:
                with open(os.path.join(gmt_dir, r["gmt"]), "wb") as f:
                    f.write(b"mesh")
            with open(os.path.join(gmt_dir, "exported.json"), "w") as f:
                json.dump(rows, f)
            with open(os.path.join(out_dir, "sample_strip.tdf"), "w") as f:
                f.write("[TRACKVARS]\n")

            recorded = []

            def fake_encrypt_assets(stage, **kwargs):
                recorded.append((
                    kwargs.get("collidable_gmts"),
                    kwargs.get("drop_flat_tangents"),
                ))
                return 4

            with mock.patch("ams_crypt.encrypt_assets", side_effect=fake_encrypt_assets):
                with mock.patch.object(sys, "argv", ["finalize_track.py", out_dir, "--strip-unused-gmt-data"]):
                    finalize_track.main()
                with mock.patch.object(sys, "argv", ["finalize_track.py", out_dir, "--no-strip-unused-gmt-data"]):
                    finalize_track.main()

            self.assertIsNotNone(recorded[0][0])
            self.assertNotIn("tree.gmt", recorded[0][0])
            self.assertIn("xfinish.gmt", recorded[0][0])
            self.assertTrue(recorded[0][1])
            self.assertIsNone(recorded[1][0])
            self.assertFalse(recorded[1][1])

    def test_drop_flat_tangents_downgrades_dummy_bump_cutouts_to_diffuse(self):
        # Alpha-tested tree cutout with neutral _flat_spec.dds + _flat_nm.dds.
        flat_cutout = _make_rf2_gmt(
            "tree_card",
            shader="L2BUMPSPECMAPT0",
            textures=[
                ("tree_a128.dds", 0x88, 1, 3, 0, 191),
                ("_flat_spec.dds", 0x08, 2, 4, 1, 0),
                ("_flat_nm.dds", 0x08, 5, 4, 2, 0),
            ],
        )
        kept = gmt_rf1.convert_rf2_to_rf1(flat_cutout, drop_flat_tangents=False)
        dropped = gmt_rf1.convert_rf2_to_rf1(flat_cutout, drop_flat_tangents=True)

        # Kept version uses L2BUMPSPECMAPT0 with UVTangents; dropped uses L2DIFFUSET0 without tangents.
        m_kept = struct.unpack_from("<10I", kept, gmt_rf1.RF1_HEADER_SIZE)
        m_drop = struct.unpack_from("<10I", dropped, gmt_rf1.RF1_HEADER_SIZE)
        self.assertTrue(m_kept[0] & gmt_rf1.MESH_FLAG_TANGENTS)
        self.assertGreater(m_kept[5], 0)  # rf1_tan_rel > 0
        self.assertFalse(m_drop[0] & gmt_rf1.MESH_FLAG_TANGENTS)
        self.assertEqual(m_drop[5], 0)    # rf1_tan_rel == 0
        self.assertIn(b"L2DIFFUSET0\x00", dropped)
        self.assertNotIn(b"L2BUMPSPECMAPT0\x00", dropped)
        self.assertNotIn(b"_flat_nm.dds", dropped)
        self.assertNotIn(b"_flat_spec.dds", dropped)
        self.assertLess(len(dropped), len(kept))

        # ColorKey (0x80) and Alpha_Reference (191) are preserved on tree_a128.dds!
        tex_pos = dropped.index(b"tree_a128.dds\x00")
        tflags = struct.unpack_from("<I", dropped, tex_pos + 64)[0]
        aref = struct.unpack_from("<I", dropped, tex_pos + 100)[0]
        self.assertTrue(tflags & gmt_rf1.TEX_FLAG_COLOR_KEY)
        self.assertEqual(aref, 191)

        # Pure-Python fallback parity.
        with mock.patch.object(gmt_rf1, "_np", None):
            dropped_py = gmt_rf1.convert_rf2_to_rf1(flat_cutout, drop_flat_tangents=True)
        self.assertEqual(dropped, dropped_py)

        # Real normal map or real specular map MUST keep L2BUMPSPECMAPT0 + UVTangents!
        for spec_name, nm_name in (
            ("_flat_spec.dds", "bark_nm.dds"),
            ("metal_spec.dds", "_flat_nm.dds"),
        ):
            real_bump = _make_rf2_gmt(
                "real_bump",
                shader="L2BUMPSPECMAPT0",
                textures=[
                    ("base.dds", 0x18, 1, 3, 0, 0),
                    (spec_name, 0x08, 2, 4, 1, 0),
                    (nm_name, 0x08, 5, 4, 2, 0),
                ],
            )
            out = gmt_rf1.convert_rf2_to_rf1(real_bump, drop_flat_tangents=True)
            m = struct.unpack_from("<10I", out, gmt_rf1.RF1_HEADER_SIZE)
            self.assertTrue(m[0] & gmt_rf1.MESH_FLAG_TANGENTS)
            self.assertGreater(m[5], 0)
            self.assertIn(b"L2BUMPSPECMAPT0\x00", out)

    def test_write_dds_preserves_all_zero_alpha_for_cutout_textures(self):
        import numpy as np
        import bake_layers
        import steam_paths

        if not os.path.isfile(steam_paths.TEXCONV):
            self.skipTest("texconv.exe not installed")

        with tempfile.TemporaryDirectory() as root:
            tex_dir = os.path.join(root, "textures")
            tmp_dir = os.path.join(root, "tmp")
            os.makedirs(tex_dir)
            os.makedirs(tmp_dir)

            # Reproduces AC's marker_transparent.dds: bright magenta RGB, alpha=0 everywhere
            rgb = np.zeros((64, 64, 3), dtype=np.float32)
            rgb[:, :, 0] = 241.0 / 255.0
            rgb[:, :, 2] = 1.0
            alpha = np.zeros((64, 64), dtype=np.float32)

            src_name = bake_layers.write_dds(
                "marker_transparent", rgb, alpha, tex_dir, tmp_dir, steam_paths.TEXCONV
            )
            self.assertEqual(src_name, "marker_transparent.dds")

            # Remapping cut-out alpha with -keepcoverage must keep alpha=0 everywhere (not 255)
            out_name = bake_layers.coverage_copy(
                src_name, 128, tex_dir, tmp_dir, steam_paths.TEXCONV, rgb_scale=0.7
            )
            self.assertIsNotNone(out_name)
            dec = bake_layers.to_rgba(os.path.join(tex_dir, out_name), tmp_dir, 64, 64)
            self.assertIsNotNone(dec)
            self.assertEqual(float(dec[:, :, 3].max()), 0.0)
            dec_mip = bake_layers.to_rgba(os.path.join(tex_dir, out_name), tmp_dir, 16, 16)
            self.assertIsNotNone(dec_mip)
            self.assertEqual(float(dec_mip[:, :, 3].max()), 0.0)

    def test_ams_shadow_modes_receivers_and_lod_culling(self):
        road_meta = {
            "render": True, "cast_shadows": False, "decal": False, "backdrop": False,
            "alpha_test": False, "needs_blend": False, "shader": "ksPerPixel",
            "rf2_material": "road_asphalt", "ground_like": True, "upward": 1.0,
        }
        tree_meta = {
            "render": True, "cast_shadows": True, "decal": False, "backdrop": False,
            "alpha_test": True, "needs_blend": False, "shader": "ksTree",
            "rf2_material": "tree_01", "ground_like": False, "upward": 0.0,
        }
        hut_meta = {
            "render": True, "cast_shadows": True, "decal": False, "backdrop": False,
            "alpha_test": False, "needs_blend": False, "shader": "ksPerPixel",
            "rf2_material": "hut", "ground_like": False, "upward": 0.2,
        }
        cutouts = {"tree_01": 191}

        # Road receives shadows in all modes; trees/huts do not in compact/off.
        self.assertTrue(finalize_track.is_shadow_receiver(road_meta, {"render": True, "physical": True}, "compact"))
        self.assertTrue(finalize_track.is_shadow_receiver(road_meta, {"render": True, "physical": True}, "off"))
        self.assertFalse(finalize_track.is_shadow_receiver(tree_meta, {"render": True, "physical": False}, "compact"))
        self.assertFalse(finalize_track.is_shadow_receiver(hut_meta, {"render": True, "physical": False}, "compact"))
        self.assertTrue(finalize_track.is_shadow_receiver(hut_meta, {"render": True, "physical": False}, "full"))

        # Compact casts only on compact opaque structures (<= 60 m, <= 8000 tris), never foliage.
        self.assertIsNone(finalize_track.shadow_caster(tree_meta, cutouts, mode="compact", radius=15.0, tris=200))
        self.assertEqual(finalize_track.shadow_caster(hut_meta, cutouts, mode="compact", radius=15.0, tris=200), ("Solid", 32))
        self.assertEqual(finalize_track.shadow_caster(hut_meta, cutouts, mode="compact", radius=40.0, tris=200), ("Solid", 64))
        self.assertIsNone(finalize_track.shadow_caster(hut_meta, cutouts, mode="compact", radius=80.0, tris=200))
        self.assertIsNone(finalize_track.shadow_caster(hut_meta, cutouts, mode="compact", radius=15.0, tris=12000))

        # Off disables all track casters.
        self.assertIsNone(finalize_track.shadow_caster(hut_meta, cutouts, mode="off", radius=15.0, tris=200))

        # Full enables Texture foliage casters up to 150 m at 64x64.
        self.assertEqual(finalize_track.shadow_caster(tree_meta, cutouts, mode="full", radius=40.0, tris=500), ("Texture", 64))
        self.assertIsNone(finalize_track.shadow_caster(tree_meta, cutouts, mode="full", radius=200.0, tris=500))

        # Distance LOD culling: grass=250m, tree=800m, small prop=600m, road=0 (full range).
        self.assertEqual(finalize_track.ams_lod_range(road_meta, {"physical": True, "radius": 20.0}), (0.0, 0.0))
        self.assertEqual(finalize_track.ams_lod_range(tree_meta, {"physical": False, "radius": 100.0}), (0.0, 800.0))
        self.assertEqual(finalize_track.ams_lod_range(hut_meta, {"physical": False, "radius": 15.0}), (0.0, 600.0))
        grass_meta = dict(tree_meta, shader="ksGrass")
        self.assertEqual(finalize_track.ams_lod_range(grass_meta, {"physical": False, "radius": 120.0}), (0.0, 250.0))

    def test_drops_degenerate_and_oversized_collision_faces_and_guards_helpers(self):
        # Case A: degenerate zero-area face is dropped (NumPy and pure-Python parity).
        degen = bytearray(_make_rf2_gmt("1ROAD_degen"))
        (_vc, voff_r, _tc, _to, _nm, _mo, _nf, _fo, _nn, noff_r, _bc, _bo) = struct.unpack_from("<12I", degen, 0x13C)
        voff, noff = voff_r + 4, noff_r + 4
        for vi, (x, y, z) in enumerate(((1.0, 2.0, 3.0), (5.0, 2.0, 3.0), (1.0, 2.0, 3.0))):
            struct.pack_into("<3f", degen, voff + vi * gmt_rf1.RF2_VERTEX_SIZE, x, y, z)
        struct.pack_into("<3fI", degen, noff, 0.0, 0.0, 0.0, 0)

        fast_d = gmt_rf1.convert_rf2_to_rf1(bytes(degen))
        with mock.patch.object(gmt_rf1, "_np", None):
            pure_d = gmt_rf1.convert_rf2_to_rf1(bytes(degen))
        self.assertEqual(fast_d, pure_d)
        _nm, _mo, nface_d, _fo, nnorm_d, _no = struct.unpack_from("<6I", fast_d, 0x174)
        self.assertEqual((nface_d, nnorm_d), (0, 0))

        # Case B: oversized triangle (80m x 40m) kept when max_face_span=None, dropped when 50.0.
        big = bytearray(_make_rf2_gmt("1GRASS_big"))
        for vi, (x, y, z) in enumerate(((0.0, 0.0, 0.0), (80.0, 0.0, 0.0), (0.0, 0.0, 40.0))):
            struct.pack_into("<3f", big, voff + vi * gmt_rf1.RF2_VERTEX_SIZE, x, y, z)

        kept = gmt_rf1.convert_rf2_to_rf1(bytes(big), max_face_span=None)
        self.assertEqual(struct.unpack_from("<I", kept, 0x17C)[0], 1)
        fast_b = gmt_rf1.convert_rf2_to_rf1(bytes(big), max_face_span=50.0)
        with mock.patch.object(gmt_rf1, "_np", None):
            pure_b = gmt_rf1.convert_rf2_to_rf1(bytes(big), max_face_span=50.0)
        self.assertEqual(fast_b, pure_b)
        _nm, _mo, nface_b, _fo, nnorm_b, _no = struct.unpack_from("<6I", fast_b, 0x174)
        self.assertEqual((nface_b, nnorm_b), (0, 0))

        # Case C: corrupted long needle sliver (>50m span, <10m altitude) is dropped
        # even when max_face_span=None (e.g. on 1ROAD_* / 1KERB_* meshes).
        sliver = bytearray(_make_rf2_gmt("1ROAD_sliver"))
        for vi, (x, y, z) in enumerate(((0.0, 1.0, 0.0), (200.0, 1.0, 200.0), (200.1, 1.0, 200.0))):
            struct.pack_into("<3f", sliver, voff + vi * gmt_rf1.RF2_VERTEX_SIZE, x, y, z)
        fast_s = gmt_rf1.convert_rf2_to_rf1(bytes(sliver), max_face_span=None)
        with mock.patch.object(gmt_rf1, "_np", None):
            pure_s = gmt_rf1.convert_rf2_to_rf1(bytes(sliver), max_face_span=None)
        self.assertEqual(fast_s, pure_s)
        self.assertEqual(struct.unpack_from("<I", fast_s, 0x17C)[0], 0)

        # Case D: barrier/offroad classification + finalize_track end-to-end.
        wall_row = {"gmt": "1WALL_01.gmt", "mesh": "1WALL_01", "physical": True,
                    "_meta": {"surface": "WALL", "rf2_material": "wall_collision"}}
        grass_row = {"gmt": "1GRASS_01.gmt", "mesh": "1GRASS_01", "physical": True,
                     "_meta": {"surface": "GRASS", "rf2_material": "gras_terrain"}}
        road_row = {"gmt": "1ROAD_01.gmt", "mesh": "1ROAD_01", "physical": True,
                    "_meta": {"surface": "ROAD", "rf2_material": "road_asphalt"}}
        self.assertTrue(finalize_track.is_barrier_row(wall_row))
        self.assertFalse(finalize_track.is_offroad_terrain_row(wall_row))
        self.assertFalse(finalize_track.is_barrier_row(grass_row))
        self.assertTrue(finalize_track.is_offroad_terrain_row(grass_row))
        self.assertFalse(finalize_track.is_barrier_row(road_row))
        self.assertFalse(finalize_track.is_offroad_terrain_row(road_row))

        def _rf2_with_tri(name, pts):
            buf = bytearray(_make_rf2_gmt(name))
            vo = struct.unpack_from("<I", buf, 0x140)[0] + 4
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            struct.pack_into("<3f", buf, 0x0C8, min(xs), min(ys), min(zs))
            struct.pack_into("<3f", buf, 0x0D4, max(xs), max(ys), max(zs))
            for vi, (x, y, z) in enumerate(pts):
                struct.pack_into("<3f", buf, vo + vi * gmt_rf1.RF2_VERTEX_SIZE, x, y, z)
            return bytes(buf)

        import json
        with tempfile.TemporaryDirectory() as root:
            venue = "hat_guard_ams"
            layout_id = finalize_track.layout_identifier(venue)
            out_dir = os.path.join(root, venue)
            gmt_dir = os.path.join(out_dir, "gmt")
            os.makedirs(gmt_dir)
            with open(os.path.join(out_dir, venue + ".tdf"), "w") as f:
                f.write("[TRACKVARS]\n")
            with open(os.path.join(out_dir, venue + ".AIW"), "w", encoding="utf-8") as f:
                f.write("[Waypoint]\nwp_pos=(0.0,0.0,0.0)\nwp_pos=(20.0,0.0,0.0)\n")

            small_tri = ((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 0.0, 4.0))
            huge_tri = ((0.0, 0.0, 0.0), (120.0, 0.0, 0.0), (0.0, 0.0, 80.0))
            remote_tri = ((500.0, 0.0, 500.0), (504.0, 0.0, 500.0), (500.0, 0.0, 504.0))
            files_spec = [
                ("xfinish.gmt", "xfinish", True, True, small_tri),
                ("xsector1.gmt", "xsector1", True, True, small_tri),
                ("xsector2.gmt", "xsector2", True, True, small_tri),
                ("1ROAD_main.gmt", "1ROAD_main", True, False, huge_tri),
                ("1WALL_01.gmt", "1WALL_01", True, False, small_tri),
                ("1GRASS_near.gmt", "1GRASS_near", True, False, small_tri),
                ("1GRASS_far.gmt", "1GRASS_far", True, False, huge_tri),
                ("1TERRAIN_remote.gmt", "1TERRAIN_remote", True, False, remote_tri),
                ("skyboxi.gmt", "skyboxi", False, False, small_tri),
            ]
            rows = []
            for fname, mname, phys, timing, pts in files_spec:
                with open(os.path.join(gmt_dir, fname), "wb") as f:
                    f.write(_rf2_with_tri(mname, pts))
                rows.append({
                    "gmt": fname, "mesh": mname, "physical": phys,
                    "timing": timing, "blend": False, "radius": 10.0,
                })
            # Verify gmt_bbox_xz works for both rF2 v2.52 and rF1 v2.20 headers.
            remote_rf2_path = os.path.join(gmt_dir, "1TERRAIN_remote.gmt")
            self.assertEqual(gmt_rf1.gmt_bbox_xz(remote_rf2_path), (500.0, 504.0, 500.0, 504.0))
            rf1_bbox_path = os.path.join(root, "bbox_rf1.gmt")
            with open(remote_rf2_path, "rb") as src_f:
                remote_rf2_bytes = src_f.read()
            with open(rf1_bbox_path, "wb") as f:
                f.write(gmt_rf1.convert_rf2_to_rf1(remote_rf2_bytes))
            self.assertEqual(gmt_rf1.gmt_bbox_xz(rf1_bbox_path), (500.0, 504.0, 500.0, 504.0))

            with open(os.path.join(gmt_dir, "exported.json"), "w") as f:
                json.dump(rows, f)

            face_counts = {}

            def fake_encrypt(src, dst, key, sig):
                fc = gmt_rf1.rf1_gmt_face_count(src)
                if fc is not None:
                    face_counts[os.path.basename(src).lower()] = fc
                with open(dst, "wb") as fh:
                    fh.write(struct.pack("<QQ", sig ^ key, key))

            fake_tools = types.SimpleNamespace(encrypt_file=fake_encrypt)
            with mock.patch.object(ams_crypt, "_library", return_value=fake_tools), \
                    mock.patch.object(sys, "argv", ["finalize_track.py", out_dir]):
                finalize_track.main()

            stage = os.path.join(out_dir, "ams1", venue)
            with open(os.path.join(stage, layout_id, layout_id + ".scn"), encoding="utf-8") as f:
                scn = f.read()

            self.assertIn("MeshFile=1WALL_01.gmt CollTarget=True HATTarget=False", scn)
            self.assertIn("MeshFile=1ROAD_main.gmt CollTarget=True HATTarget=True", scn)
            self.assertEqual(face_counts["1road_main.gmt"], 1)
            self.assertIn("MeshFile=1GRASS_near.gmt CollTarget=True HATTarget=True", scn)
            self.assertEqual(face_counts["1grass_near.gmt"], 1)
            self.assertEqual(face_counts["1grass_far.gmt"], 0)
            self.assertIn("MeshFile=1GRASS_far.gmt CollTarget=False HATTarget=False", scn)
            self.assertIn("MeshFile=1TERRAIN_remote.gmt CollTarget=False HATTarget=False", scn)
            self.assertEqual(face_counts["1terrain_remote.gmt"], 0)
            self.assertTrue(os.path.isfile(os.path.join(stage, "gmt", "track_skyboxi.gmt")))
            self.assertIn("MeshFile=track_skyboxi.gmt", scn)


if __name__ == "__main__":
    unittest.main()
