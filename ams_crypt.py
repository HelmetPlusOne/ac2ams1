"""Encrypt and inspect loose assets in an AMS1 location."""
import os
import shutil
import struct
import subprocess

import gmt_rf1

AMS_SIGNATURE = 0x4B1DCA9F960524E8
AMS_KEY = 1
ASSET_EXTENSIONS = {".dds", ".gmt"}
MAX_COMMAND_CHARS = 28000


def _prepare_gmt_for_ams1(path, mesh_coarsening=0.0, include_faces=True,
                          drop_flat_tangents=False, max_face_span=None):
    """Convert rF2 GMT v2.52 exports to AMS1/rF1 GMT v2.20 before encryption."""
    gmt_rf1.convert_file(
        path, mesh_coarsening=mesh_coarsening, include_faces=include_faces,
        drop_flat_tangents=drop_flat_tangents, max_face_span=max_face_span)


def _library():
    try:
        import rfactortools
    except ImportError:
        return None
    if callable(getattr(rfactortools, "encrypt_file", None)):
        return rfactortools
    return None


def _encryptor():
    import steam_paths
    if steam_paths.IS_STANDALONE:
        return (
            steam_paths.ENCRYPTOR
            if (steam_paths.ENCRYPTOR and os.path.isfile(steam_paths.ENCRYPTOR))
            else None
        )
    configured = os.environ.get("AC2AMS_ENCRYPTOR")
    if configured:
        return configured if os.path.isfile(configured) else None
    if steam_paths.ENCRYPTOR and os.path.isfile(steam_paths.ENCRYPTOR):
        return steam_paths.ENCRYPTOR
    for name in ("rft-rfactorcrypt", "rft-rfactorcrypt.exe",
                 "rfactorcrypt", "rfactorcrypt.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


def encryptor_source():
    """Return the active encryptor executable path or rfactortools module description."""
    lib = _library()
    if lib is not None:
        path = getattr(lib, "__file__", None)
        return "rfactortools (%s)" % path if path else "rfactortools"
    return _encryptor()


def encryption_available():
    return encryptor_source() is not None


def crypt_info(path):
    with open(path, "rb") as f:
        header = f.read(16)
    if len(header) < 16:
        return 0, 0
    value, key = struct.unpack("<QQ", header)
    return value ^ key, key


def _run_encryptor(executable, batch):
    command = [executable, "-e", "-k", str(AMS_KEY), "-s",
               hex(AMS_SIGNATURE)] + batch
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        raise RuntimeError("rfactorcrypt failed:\n%s" % output[-2000:])


def _encrypt_with_executable(files, executable):
    prefix = [executable, "-e", "-k", str(AMS_KEY), "-s", hex(AMS_SIGNATURE)]
    batch = []
    length = sum(len(arg) + 1 for arg in prefix)
    for path in files:
        extra = len(path) + 1
        if batch and length + extra > MAX_COMMAND_CHARS:
            _run_encryptor(executable, batch)
            batch = []
            length = sum(len(arg) + 1 for arg in prefix)
        batch.append(path)
        length += extra
    if batch:
        _run_encryptor(executable, batch)


def encrypt_assets(root, mesh_coarsening=0.0, collidable_gmts=None,
                   drop_flat_tangents=False, max_face_span_gmts=None,
                   max_face_span=None, empty_face_gmts=None):
    """Encrypt all loose GMT and DDS assets under a staged location.

    When ``collidable_gmts`` is provided (a collection of lowercased GMT
    basenames), only those GMTs keep FaceData/NormalData collision tables;
    non-collidable visual GMTs are converted with ``include_faces=False``.
    When ``drop_flat_tangents`` is True, flat-normal/flat-spec bump cutouts
    are downgraded to ``L2DIFFUSET0`` without UVTangents.
    When ``max_face_span_gmts`` and ``max_face_span`` are provided, matching
    GMTs drop oversized collision faces exceeding ``max_face_span`` meters in
    X or Z; any such GMT left with 0 faces is added to ``empty_face_gmts`` if
    a set is supplied.
    """
    tools = _library()
    collidable = (
        {name.lower() for name in collidable_gmts}
        if collidable_gmts is not None else None
    )
    capped = (
        {name.lower() for name in max_face_span_gmts}
        if max_face_span_gmts is not None else None
    )
    files = []
    for folder, _, names in os.walk(root):
        for name in names:
            if os.path.splitext(name)[1].lower() in ASSET_EXTENSIONS:
                files.append(os.path.join(folder, name))

    files.sort()
    to_encrypt = []
    for path in files:
        signature, key = crypt_info(path)
        if signature == AMS_SIGNATURE:
            continue
        if os.path.splitext(path)[1].lower() == ".gmt":
            low = os.path.basename(path).lower()
            include_faces = True if collidable is None else (low in collidable)
            face_span = (
                max_face_span
                if (capped is not None and max_face_span and low in capped)
                else None
            )
            _prepare_gmt_for_ams1(
                path, mesh_coarsening=mesh_coarsening,
                include_faces=include_faces,
                drop_flat_tangents=drop_flat_tangents,
                max_face_span=face_span)
            if (empty_face_gmts is not None and face_span
                    and gmt_rf1.rf1_gmt_face_count(path) == 0):
                empty_face_gmts.add(low)
        to_encrypt.append(path)

    if to_encrypt:
        if tools is None:
            executable = _encryptor()
            if executable is None:
                raise RuntimeError(
                    "AMS1 encryption requires rfactortools or its rfactorcrypt executable")
            _encrypt_with_executable(to_encrypt, executable)
        else:
            for path in to_encrypt:
                tools.encrypt_file(path, path, AMS_KEY, AMS_SIGNATURE)

    for path in files:
        signature, _key = crypt_info(path)
        if signature != AMS_SIGNATURE:
            raise RuntimeError("AMS encryption verification failed for %s" % path)
    return len(files)
