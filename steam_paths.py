"""Where Assetto Corsa, Automobilista 1, and bundled/external tools live.

In a standalone ``dist`` layout (next to ``ac2ams1.exe``), all tools and template
game data resolve relative to the executable directory so the converter runs on
a clean Windows machine with no AC, AMS1, rF2, Python, or Blender installed:

  <dist>/
      ac2ams1.exe
      tools/blender/blender.exe
      tools/blender_scripts/blender_stage.py
      tools/texconv/texconv.exe
      tools/rfactortools/rfactorcrypt.exe
      data/ac/system/data/surfaces.ini
      data/ams1/GameData/Locations/terrain.tdf
      data/ams1/GameData/Locations/sky/SRPL_SKY3_*.GMT
      work/
      out/

Outside a standalone bundle, Steam libraries and registry paths are used, and
environment variables (AC2AMS_GAME_DIR, AC2AMS_AC_DIR, AC2AMS_TEXCONV,
AC2AMS_BLENDER, AC2AMS_ENCRYPTOR) can override any path.
"""
import os
import re
import sys

STEAM_DEFAULT = r"C:\Program Files (x86)\Steam"
DEFAULT_BLENDER = r"D:\Apps\Blender\blender.exe"
DEFAULT_ENCRYPTOR = r"D:\Mods\Automobilista\Tools\rfactortools-0.3.1.win32\rfactorcrypt.exe"


def app_dir():
    """Directory containing the running EXE (frozen) or repository scripts."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


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
        with open(vdf, encoding="utf-8", errors="replace") as f:
            text = f.read()
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


APP_DIR = app_dir()
BUNDLED_BLENDER = os.path.join(APP_DIR, "tools", "blender", "blender.exe")
BUNDLED_BLENDER_STAGE = os.path.join(APP_DIR, "tools", "blender_scripts", "blender_stage.py")
BUNDLED_TEXCONV = os.path.join(APP_DIR, "tools", "texconv", "texconv.exe")
BUNDLED_ENCRYPTOR = os.path.join(APP_DIR, "tools", "rfactortools", "rfactorcrypt.exe")
BUNDLED_AC_DIR = os.path.join(APP_DIR, "data", "ac")
BUNDLED_AMS_DIR = os.path.join(APP_DIR, "data", "ams1")

IS_STANDALONE = bool(
    getattr(sys, "frozen", False)
    or (os.path.isfile(BUNDLED_BLENDER) and os.path.isdir(os.path.join(APP_DIR, "data")))
)

_bundled_ams_ok = os.path.isfile(
    os.path.join(BUNDLED_AMS_DIR, "GameData", "Locations", "terrain.tdf")
)
_bundled_ac_ok = os.path.isfile(
    os.path.join(BUNDLED_AC_DIR, "system", "data", "surfaces.ini")
)

AMS_DIR = (
    os.environ.get("AC2AMS_GAME_DIR")
    or (BUNDLED_AMS_DIR if _bundled_ams_ok else game_dir("Automobilista"))
)
AC_DIR = (
    os.environ.get("AC2AMS_AC_DIR")
    or (BUNDLED_AC_DIR if _bundled_ac_ok else game_dir("assettocorsa"))
)
RF2_DIR = os.environ.get("AC2AMS_RF2_DIR") or game_dir("rFactor 2")
TEXCONV = (
    os.environ.get("AC2AMS_TEXCONV")
    or (BUNDLED_TEXCONV if os.path.isfile(BUNDLED_TEXCONV)
        else os.path.join(RF2_DIR, "Support", "Tools", "MapConverter", "texconv.exe"))
)
BLENDER = (
    os.environ.get("AC2AMS_BLENDER")
    or (BUNDLED_BLENDER if os.path.isfile(BUNDLED_BLENDER) else DEFAULT_BLENDER)
)
BLENDER_STAGE = (
    BUNDLED_BLENDER_STAGE
    if os.path.isfile(BUNDLED_BLENDER_STAGE)
    else os.path.join(APP_DIR, "blender_stage.py")
)
ENCRYPTOR = (
    os.environ.get("AC2AMS_ENCRYPTOR")
    or (BUNDLED_ENCRYPTOR if os.path.isfile(BUNDLED_ENCRYPTOR) else DEFAULT_ENCRYPTOR)
)

LOCATIONS = os.path.join(AMS_DIR, "GameData", "Locations")
INSTALL_LOCATIONS = os.path.join(APP_DIR, "out") if IS_STANDALONE else LOCATIONS
WORK_ROOT = os.path.join(APP_DIR, "work") if IS_STANDALONE else os.path.join(APP_DIR, "out")


if __name__ == "__main__":
    if "--locations" in sys.argv:       # for scripts that only need this
        print(INSTALL_LOCATIONS)
        sys.exit(0)
    print("Standalone:    %s" % IS_STANDALONE)
    print("App dir:       %s" % APP_DIR)
    print("Automobilista: %s" % AMS_DIR)
    print("Assetto Corsa: %s" % AC_DIR)
    print("Blender:       %s (%s)" % (BLENDER, "found" if os.path.exists(BLENDER) else "MISSING"))
    print("texconv:       %s (%s)" % (TEXCONV, "found" if os.path.exists(TEXCONV) else "MISSING"))
    print("encryptor:     %s (%s)" % (ENCRYPTOR, "found" if os.path.exists(ENCRYPTOR) else "MISSING"))
    print("work root:     %s" % WORK_ROOT)
    print("install into:  %s" % INSTALL_LOCATIONS)
