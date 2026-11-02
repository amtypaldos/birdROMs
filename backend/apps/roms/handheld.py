"""The handheld app package (`birdROMs.muxapp`) that signed-in users download from the website.

The owner publishes a build with `manage.py publish_handheld <file>`; it lands at
`settings.HANDHELD_APP_PATH` (default `MEDIA_ROOT/handheld/birdROMs.muxapp`)."""

import hashlib
import json
import os
import ipaddress
import re
import stat
from urllib.parse import urlsplit
import shutil
import tempfile
import zipfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

from django.conf import settings

# A package the muOS Archive Manager can install: entries are rooted at `birdROMs/`.
REQUIRED_ENTRIES = ("birdROMs/birdroms", "birdROMs/mux_launch.sh")


class InvalidMuxapp(ValueError):
    pass


def validate_muxapp(path) -> None:
    if not zipfile.is_zipfile(path):
        raise InvalidMuxapp(f"{path} is not a zip archive (a .muxapp is a zip).")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    for required in REQUIRED_ENTRIES:
        if required not in names:
            raise InvalidMuxapp(f"The package has no {required}; entries must be rooted at birdROMs/.")


def handheld_path(platform="muos") -> Path:
    if platform == "switch":
        return Path(settings.SWITCH_APP_PATH)
    if platform != "muos":
        raise InvalidMuxapp("Unknown handheld platform.")
    return Path(settings.HANDHELD_APP_PATH)


def handheld_info(platform="muos"):
    """Details of the published package, or None when nothing is published."""
    path = handheld_path(platform)
    if not path.is_file():
        return None
    stat = path.stat()
    info = {
        "available": True,
        "filename": path.name,
        "size": stat.st_size,
        "sha256": _sha256(path),
        "published_at": datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc).isoformat(),
    }

    if platform == "switch":
        info.update(validate_switch_package(path))
        info["filename"] = "birdROMs-switch.zip"
    return info


# The image build downloads the matching handheld release here. The media directory is a
# volume, so the entrypoint copies this file into HANDHELD_APP_PATH on startup.
BUNDLED_HANDHELD = Path("/app/birdROMs.muxapp")
BUNDLED_SWITCH = Path("/app/birdROMs-switch.zip")


def publish_package(source: Path, platform="muos") -> Path:
    """Validate `source` and install it at HANDHELD_APP_PATH. Returns the installed path."""
    if not source.is_file():
        raise InvalidMuxapp(f"{source} does not exist.")
    target = handheld_path(platform)
    validator = validate_switch_package if platform == "switch" else validate_muxapp
    validator(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    try:
        shutil.copyfile(source, partial)
        # Validate the copied bytes too, so concurrent source changes cannot bypass validation.
        validator(partial)
        with partial.open("rb") as copied:
            os.fsync(copied.fileno())
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def install_bundled(source: Path | None = None, platform="muos") -> bool:
    """Install the package shipped in the image when it differs from the published one.

    Returns True when the published file was replaced. A missing or empty bundle does nothing.
    """
    target = handheld_path(platform)
    env_name, default = ("BUNDLED_SWITCH_PATH", BUNDLED_SWITCH) if platform == "switch" else ("BUNDLED_HANDHELD_PATH", BUNDLED_HANDHELD)
    source = source or Path(os.environ.get(env_name, default))
    if not source.is_file() or source.stat().st_size == 0:
        return False
    if target.is_file() and _sha256(source) == _sha256(target):
        return False
    publish_package(source, platform=platform)
    return True


def _sha256(path: Path) -> str:
    """Hash of the stored package, before a download adds server.json."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


SEED_ENTRY = "birdROMs/server.json"


def personalized_package(server_url: str, platform="muos"):
    """The published package plus a `server.json` naming this server, as a readable temp file.

    The device has no keyboard, so it learns which server to pair with from this file. It is a
    separate file from the device's `config.json` (which holds the pairing token) so installing
    an update never wipes the pairing."""
    path = handheld_path(platform)
    if platform == "switch":
        validate_switch_package(path)
    seed_entry = SWITCH_PREFIX + "server.json" if platform == "switch" else SEED_ENTRY
    seed = json.dumps({"server_url": server_url.rstrip("/")}) + "\n"
    if platform == "switch" and len(seed.encode("utf-8")) > SWITCH_MAX_SEED_BYTES:
        raise InvalidMuxapp("Switch server seed exceeds its size limit.")
    out = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename != seed_entry:
                with source.open(item) as original, target.open(item, "w") as destination:
                    shutil.copyfileobj(original, destination, length=1024 * 1024)
        entry = zipfile.ZipInfo(seed_entry, date_time=datetime.now(dt_timezone.utc).timetuple()[:6])
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o100644 << 16  # a regular rw-r--r-- file
        target.writestr(entry, seed)
    if platform == "switch" and out.tell() > SWITCH_MAX_ZIP_BYTES:
        out.close()
        raise InvalidMuxapp("Personalized Switch ZIP exceeds the native 64 MiB limit.")
    out.seek(0)
    return out


SWITCH_PREFIX = "switch/birdroms/"
SWITCH_NRO = SWITCH_PREFIX + "birdroms.nro"
SWITCH_MANIFEST = SWITCH_PREFIX + "version.json"
# Keep these limits aligned with switch/include/update/parsing.hpp and the native
# staging/downloader budget. Leave room for the generated server seed ZIP entry.
SWITCH_MAX_NRO_BYTES = 64 * 1024 * 1024
SWITCH_MAX_ZIP_BYTES = 64 * 1024 * 1024
SWITCH_SEED_RESERVE_BYTES = 4096
SWITCH_MAX_SEED_BYTES = 1024


def _strict_json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidMuxapp("Duplicate JSON keys in Switch package.")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError) as exc:
        raise InvalidMuxapp("Malformed JSON in Switch package.") from exc


def _validate_public_seed(data):
    seed = _strict_json(data)
    if not isinstance(seed, dict) or set(seed) != {"server_url"} or not isinstance(seed["server_url"], str):
        raise InvalidMuxapp("Switch seed must contain only server_url.")
    try:
        url = urlsplit(seed["server_url"])
        host = url.hostname
        if (url.scheme not in {"http", "https"} or not host or url.username is not None
                or url.password is not None or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError
        # Reject private installation defaults in publicly distributed release archives.
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal", ".lan")):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise InvalidMuxapp("Published Switch seed must name a public server origin without credentials.") from exc


def validate_switch_package(path):
    """Validate the only permitted SD archive layout and return verified executable metadata.

    No configuration or credentials may ship in a release. Untrusted ZIP names are never
    extracted; bounded reads and streaming hashes avoid inflating executable data in memory.
    """
    allowed_files = {SWITCH_NRO, SWITCH_MANIFEST, SWITCH_PREFIX + "server.json"}
    allowed_dirs = {"switch/", SWITCH_PREFIX}
    try:
        if Path(path).stat().st_size > SWITCH_MAX_ZIP_BYTES - SWITCH_SEED_RESERVE_BYTES:
            raise InvalidMuxapp("Switch ZIP exceeds the native 64 MiB budget including server seed headroom.")
        with zipfile.ZipFile(path) as archive:
            names = set()
            for item in archive.infolist():
                name = item.filename
                if name in names or item.orig_filename != name:
                    raise InvalidMuxapp("Duplicate or unsafe Switch ZIP entry.")
                names.add(name)
                if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise InvalidMuxapp("Switch ZIP entries must use stored or deflated compression.")
                kind = stat.S_IFMT(item.external_attr >> 16)
                if item.flag_bits & 1 or kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise InvalidMuxapp("Encrypted or special Switch ZIP entries are forbidden.")
                if name not in allowed_files | allowed_dirs or "\\" in name:
                    raise InvalidMuxapp("Unexpected Switch ZIP entry; only the NRO, manifest and optional server seed are allowed.")
                if name in allowed_dirs:
                    if not item.is_dir() or kind == stat.S_IFREG or item.file_size != 0:
                        raise InvalidMuxapp("Invalid Switch ZIP directory.")
                elif item.is_dir() or kind == stat.S_IFDIR:
                    raise InvalidMuxapp("Invalid Switch ZIP file.")
                limit = SWITCH_MAX_NRO_BYTES if name == SWITCH_NRO else 16 * 1024
                if item.file_size > limit or item.file_size < 0:
                    raise InvalidMuxapp("Switch ZIP entry exceeds its size limit.")
            if not {SWITCH_NRO, SWITCH_MANIFEST} <= names:
                raise InvalidMuxapp("Switch package requires birdroms.nro and version.json under switch/birdroms/.")
            manifest = _strict_json(archive.read(SWITCH_MANIFEST))
            expected_keys = {"platform", "version", "nro_sha256", "nro_size"}
            if not isinstance(manifest, dict) or set(manifest) != expected_keys or manifest["platform"] != "switch":
                raise InvalidMuxapp("Invalid Switch version manifest fields.")
            version = manifest["version"]
            if not isinstance(version, str) or not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\.[1-9][0-9]*)?", version):
                raise InvalidMuxapp("Switch version must be a date version YYYY.MM.DD[.N].")
            parts = version.split(".")
            if int(parts[0]) < 2020:
                raise InvalidMuxapp("Switch version year must be at least 2020.")
            if len(parts) == 4 and (len(parts[3]) > 10 or (len(parts[3]) == 10 and parts[3] > "4294967295")):
                raise InvalidMuxapp("Switch version revision exceeds the native unsigned 32-bit limit.")
            try:
                datetime.strptime(version[:10], "%Y.%m.%d")
            except ValueError as exc:
                raise InvalidMuxapp("Switch version contains an invalid date.") from exc
            if type(manifest["nro_size"]) is not int or not isinstance(manifest["nro_sha256"], str):
                raise InvalidMuxapp("Invalid Switch executable size or digest.")
            digest = hashlib.sha256()
            length = 0
            with archive.open(SWITCH_NRO) as nro:
                header = nro.read(20)
                if len(header) < 20 or header[16:20] != b"NRO0":
                    raise InvalidMuxapp("Switch executable has no NRO0 magic.")
                digest.update(header)
                length += len(header)
                for chunk in iter(lambda: nro.read(1024 * 1024), b""):
                    digest.update(chunk)
                    length += len(chunk)
            if manifest["nro_size"] != length or manifest["nro_sha256"] != digest.hexdigest():
                raise InvalidMuxapp("Switch executable hash or size does not match version.json.")
            if SWITCH_PREFIX + "server.json" in names:
                _validate_public_seed(archive.read(SWITCH_PREFIX + "server.json"))
            return manifest
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise InvalidMuxapp("Cannot read a valid Switch ZIP package.") from exc
