"""Where Steam put Assetto Corsa, Automobilista 1, and texture tools.

Steam can install a game into any of its library folders, listed in
steamapps/libraryfolders.vdf. Steam's own folder is read from the registry so
the converter works when the games are installed outside the default library.

The game directories can also be named outright; build_track.py sets
AC2AMS_GAME_DIR and AC2AMS_AC_DIR for every step it runs.
"""
import os
import re

STEAM_DEFAULT = r"C:\Program Files (x86)\Steam"


def steam_root():
    """Steam's own folder: from the registry, else the default install path."""
    try:
        import winreg
    except ImportError:
        return STEAM_DEFAULT
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    for hive, key, value in keys:
        try:
            with winreg.OpenKey(hive, key) as k:
                path = winreg.QueryValueEx(k, value)[0]
        except OSError:
            continue
        if path and os.path.isdir(path):
            # Steam stores it lower case; realpath gives the folder's own case.
            return os.path.realpath(path)
    return STEAM_DEFAULT


def libraries():
    """Every Steam library folder, Steam's own first."""
    root = steam_root()
    out = [root]
    if os.path.normcase(STEAM_DEFAULT) != os.path.normcase(root):
        out.append(STEAM_DEFAULT)
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        text = open(vdf, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for path in re.findall(r'"path"\s+"([^"]+)"', text):
        path = os.path.normpath(path.replace("\\\\", "\\"))
        if os.path.normcase(path) not in (os.path.normcase(p) for p in out):
            out.append(path)
    return out


def game_dir(folder):
    """steamapps/common/<folder> in whichever library has it, else Steam's own."""
    for lib in libraries():
        p = os.path.join(lib, "steamapps", "common", folder)
        if os.path.isdir(p):
            return p
    return os.path.join(steam_root(), "steamapps", "common", folder)


AMS_DIR = os.environ.get("AC2AMS_GAME_DIR") or game_dir("Automobilista")
AC_DIR = os.environ.get("AC2AMS_AC_DIR") or game_dir("assettocorsa")
RF2_DIR = os.environ.get("AC2AMS_RF2_DIR") or game_dir("rFactor 2")
TEXCONV = os.environ.get(
    "AC2AMS_TEXCONV",
    os.path.join(RF2_DIR, "Support", "Tools", "MapConverter", "texconv.exe"))
LOCATIONS = os.path.join(AMS_DIR, "GameData", "Locations")


if __name__ == "__main__":
    import sys
    if "--locations" in sys.argv:       # for scripts that only need this
        print(LOCATIONS)
        sys.exit(0)
    print("Steam:         %s" % steam_root())
    print("Automobilista: %s" % AMS_DIR)
    print("Assetto Corsa: %s" % AC_DIR)
    print("texconv:       %s (%s)" % (TEXCONV, "found" if os.path.exists(TEXCONV) else "MISSING"))
    print("install into:  %s" % LOCATIONS)
