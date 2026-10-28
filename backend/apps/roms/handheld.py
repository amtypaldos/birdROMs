"""The handheld app package (`birdROMs.muxapp`) that signed-in users download from the website.

The owner publishes a build with `manage.py publish_handheld <file>`; it lands at
`settings.HANDHELD_APP_PATH` (default `MEDIA_ROOT/handheld/birdROMs.muxapp`)."""

import hashlib
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "available": True,
        "filename": path.name,
        "size": stat.st_size,
        "sha256": digest.hexdigest(),
        "published_at": datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc).isoformat(),
    }
