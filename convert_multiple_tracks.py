"""Convert tracks listed as one ``<track path>;<layout>`` entry per line.

    python convert_multiple_tracks.py tracks.txt
"""
import argparse
import os
import subprocess
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_TRACK = os.path.join(HERE, "build_track.py")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input_file", help="text file with one track path and layout per line")
    args = ap.parse_args()

    failed = False
    try:
        with open(args.input_file, encoding="utf-8-sig") as tracks:
            for line_number, line in enumerate(tracks, 1):
                entry = line.strip()
                if not entry:
                    continue
                track_dir, separator, layout = entry.partition(";")
                track_dir = track_dir.strip()
                layout = layout.strip()
                if not separator or not track_dir:
                    print("%s:%d: expected <track path>;<layout>" %
                          (args.input_file, line_number), file=sys.stderr)
                    failed = True
                    continue

                command = [sys.executable, BUILD_TRACK, track_dir, "--install", "auto"]
                if layout:
                    command.extend(["--layout", layout])
                print("Converting %s%s" % (
                    track_dir, " (%s)" % layout if layout else ""))
                try:
                    result = subprocess.run(command)
                except OSError as exc:
                    print("Could not start conversion for %s: %s" %
                          (track_dir, exc), file=sys.stderr)
                    failed = True
                    continue
                if result.returncode:
                    print("Conversion failed for %s (exit code %d)" %
                          (track_dir, result.returncode), file=sys.stderr)
                    failed = True
    except OSError as exc:
        print("Could not read %s: %s" % (args.input_file, exc), file=sys.stderr)
        return 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
