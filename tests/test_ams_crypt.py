import os
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

import ams_crypt
import finalize_track
import verify_install


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
                f.write(b"\x00" * 4 + b"\x20\x00\x00\x04" + b"mesh-body")
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
            self.assertEqual(encrypted_gmt[16:24],
                             b"\x00" * 4 + b"\x20\x00\x00\x00")
            self.assertEqual(encrypted_gmt[24:], b"mesh-body")
            with open(tga, "rb") as f:
                self.assertEqual(f.read(), b"asset")

    def test_prepares_only_known_gmt_format_words_for_ams1(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "mesh.gmt")
            body = b"\x00" * 4 + b"\x20\x00\x00\x04" + b"mesh"
            with open(path, "wb") as f:
                f.write(body)

            ams_crypt._prepare_gmt_for_ams1(path)
            with open(path, "rb") as f:
                prepared = f.read()
            self.assertEqual(prepared,
                             b"\x00" * 4 + b"\x20\x00\x00\x00" + b"mesh")

            ams_crypt._prepare_gmt_for_ams1(path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), prepared)

            with open(path, "wb") as f:
                f.write(b"\x00" * 4 + b"\x20\x00\x00\x03")
            with self.assertRaisesRegex(RuntimeError, "unsupported GMT format word"):
                ams_crypt._prepare_gmt_for_ams1(path)

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
                f.write(b"\x00" * 4 + b"\x20\x00\x00\x04" + b"mesh")

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

    def test_stages_ams_menu_images_from_ac_preview(self):
        def convert(command, **_kwargs):
            output_dir = command[command.index("-o") + 1]
            image_format = command[command.index("-ft") + 1].upper()
            output = os.path.join(output_dir, "preview." + image_format)
            with open(output, "wb") as f:
                f.write(image_format.encode("ascii"))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root:
            preview = os.path.join(root, "preview.png")
            layout_dir = os.path.join(root, "layout")
            os.makedirs(layout_dir)
            with open(preview, "wb") as f:
                f.write(b"png")

            with mock.patch.object(finalize_track.subprocess, "run",
                                   side_effect=convert):
                count = finalize_track.stage_menu_images(
                    preview, layout_dir, "sample_track", "texconv.exe")

            self.assertEqual(count, 2)
            for name, body in (("sample_trackmini.tga", b"TGA"),
                               ("sample_track_loading.jpg", b"JPG")):
                with open(os.path.join(layout_dir, name), "rb") as f:
                    self.assertEqual(f.read(), body)

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


if __name__ == "__main__":
    unittest.main()
