"""Encrypt and inspect loose assets in an AMS1 location."""
import os
import shutil
import struct
import subprocess

AMS_SIGNATURE = 0x4B1DCA9F960524E8
AMS_KEY = 1
ASSET_EXTENSIONS = {".dds", ".gmt"}
MAX_COMMAND_CHARS = 28000
GMT_FORMAT_OFFSET = 4
AMS_GMT_FORMAT = b"\x20\x00\x00\x00"
RF2_GMT_FORMAT = b"\x20\x00\x00\x04"


def _prepare_gmt_for_ams1(path):
    with open(path, "r+b") as f:
        header = f.read(GMT_FORMAT_OFFSET + len(AMS_GMT_FORMAT))
        if len(header) < GMT_FORMAT_OFFSET + len(AMS_GMT_FORMAT):
            raise RuntimeError("GMT file is too short to contain its format word: %s"
                               % path)
        format_word = header[GMT_FORMAT_OFFSET:]
        if format_word == AMS_GMT_FORMAT:
            return
        if format_word != RF2_GMT_FORMAT:
            value = " ".join("%02x" % b for b in format_word)
            raise RuntimeError("unsupported GMT format word %s in %s"
                               % (value, path))
        f.seek(GMT_FORMAT_OFFSET)
        f.write(AMS_GMT_FORMAT)


def _library():
    try:
        import rfactortools
    except ImportError:
        return None
    if callable(getattr(rfactortools, "encrypt_file", None)):
        return rfactortools
    return None


def _encryptor():
    configured = os.environ.get("AC2AMS_ENCRYPTOR")
    if configured:
        return configured if os.path.isfile(configured) else None
    for name in ("rft-rfactorcrypt", "rft-rfactorcrypt.exe",
                 "rfactorcrypt", "rfactorcrypt.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


def encryption_available():
    return _library() is not None or _encryptor() is not None


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


def encrypt_assets(root):
    """Encrypt all loose GMT and DDS assets under a staged location."""
    tools = _library()
    files = []
    for folder, _, names in os.walk(root):
        for name in names:
            if os.path.splitext(name)[1].lower() in ASSET_EXTENSIONS:
                files.append(os.path.join(folder, name))

    files.sort()
    for path in files:
        if os.path.splitext(path)[1].lower() == ".gmt":
            _prepare_gmt_for_ams1(path)

    if tools is None:
        executable = _encryptor()
        if executable is None:
            raise RuntimeError(
                "AMS1 encryption requires rfactortools or its rfactorcrypt executable")
        _encrypt_with_executable(files, executable)
    else:
        for path in files:
            tools.encrypt_file(path, path, AMS_KEY, AMS_SIGNATURE)

    for path in files:
        signature, key = crypt_info(path)
        if signature != AMS_SIGNATURE or key != AMS_KEY:
            raise RuntimeError("AMS encryption verification failed for %s" % path)
    return len(files)
