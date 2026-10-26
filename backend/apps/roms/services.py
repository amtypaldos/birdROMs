import os
from dataclasses import dataclass


DISC_IMAGE = "Disc Image"
ARCHIVE = "Archive"
UNKNOWN_PLATFORM = "unknown"

# Canonical extension -> platform map. Keys are lowercase and include the leading dot.
# Extensions shared by several systems (.iso, .bin, .cue, .chd, .zip, .7z) map to a generic
# label; uploaders can set `platform` explicitly to override it.
EXTENSION_TO_PLATFORM = {
    # Nintendo
    ".nes": "NES",
    ".sfc": "SNES",
    ".smc": "SNES",
    ".n64": "Nintendo 64",
    ".z64": "Nintendo 64",
    ".v64": "Nintendo 64",
    ".gcm": "Nintendo GameCube",
    ".rvz": "Nintendo GameCube",
    ".gcz": "Nintendo GameCube",
    ".wbfs": "Nintendo Wii",
    ".gb": "Game Boy",
    ".gbc": "Game Boy Color",
    ".gba": "Game Boy Advance",
    ".nds": "Nintendo DS",
    ".3ds": "Nintendo 3DS",
    ".cia": "Nintendo 3DS",
    # Sega
    ".sms": "Sega Master System",
    ".gen": "Sega Genesis",
    ".md": "Sega Genesis",
    ".smd": "Sega Genesis",
    ".gg": "Sega Game Gear",
    ".32x": "Sega 32X",
    ".gdi": "Sega Dreamcast",
    ".cdi": "Sega Dreamcast",
    # Sony
    ".pbp": "Sony PlayStation",
    ".cso": "Sony PSP",
    # Others
    ".pce": "PC Engine / TurboGrafx-16",
    ".ngp": "Neo Geo Pocket",
    ".ngc": "Neo Geo Pocket Color",
    ".ws": "WonderSwan",
    ".wsc": "WonderSwan Color",
    ".a26": "Atari 2600",
    ".a78": "Atari 7800",
    ".lnx": "Atari Lynx",
    ".jag": "Atari Jaguar",
    ".j64": "Atari Jaguar",
    # Ambiguous (Saturn, PlayStation, PS2, PSP, Sega CD, ...)
    ".iso": DISC_IMAGE,
    ".bin": DISC_IMAGE,
    ".cue": DISC_IMAGE,
    ".chd": DISC_IMAGE,
    ".zip": ARCHIVE,
    ".7z": ARCHIVE,
}

SUPPORTED_EXTENSIONS = frozenset(EXTENSION_TO_PLATFORM)
SUPPORTED_PLATFORMS = tuple(sorted(set(EXTENSION_TO_PLATFORM.values())))


def get_extension(filename: str) -> str:
    """Return the lowercase final suffix of `filename` (e.g. ".sfc"), or "" if none."""
    return os.path.splitext(os.path.basename(filename))[1].lower()


def classify_platform_from_extension(filename: str) -> str:
    return EXTENSION_TO_PLATFORM.get(get_extension(filename), UNKNOWN_PLATFORM)


@dataclass
class CoverArtResult:
    image_url: str | None
    source: str | None


def scrape_cover_art(title: str, platform: str) -> CoverArtResult:
    """
    Placeholder hook for cover scraping integrations.
    Replace this with calls to provider APIs (IGDB, ScreenScraper, etc).
    """
    _ = (title, platform)
    return CoverArtResult(image_url=None, source=None)
