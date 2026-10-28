"""The handheld app package (`birdROMs.muxapp`) that signed-in users download from the website.

The owner publishes a build with `manage.py publish_handheld <file>`; it lands at
`settings.HANDHELD_APP_PATH` (default `MEDIA_ROOT/handheld/birdROMs.muxapp`)."""

import json
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


def handheld_path() -> Path:
    return Path(settings.HANDHELD_APP_PATH)


def handheld_info():
    """Details of the published package, or None when nothing is published."""
    path = handheld_path()
    if not path.is_file():
        return None
    stat = path.stat()
    return {
        "available": True,
        "filename": path.name,
        "size": stat.st_size,
        "published_at": datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc).isoformat(),
    }


SEED_ENTRY = "birdROMs/server.json"


def personalized_package(server_url: str):
    """The published package plus a `server.json` naming this server, as a readable temp file.

    The device has no keyboard, so it learns which server to pair with from this file. It is a
    separate file from the device's `config.json` (which holds the pairing token) so installing
    an update never wipes the pairing."""
    seed = json.dumps({"server_url": server_url.rstrip("/")}) + "\n"
    out = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with zipfile.ZipFile(handheld_path()) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename != SEED_ENTRY:
                target.writestr(item, source.read(item.filename))
        target.writestr(SEED_ENTRY, seed)
    out.seek(0)
    return out
