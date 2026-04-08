from dataclasses import dataclass


EXTENSION_TO_PLATFORM = {
    ".nes": "NES",
    ".sfc": "SNES",
    ".smc": "SNES",
    ".gba": "Game Boy Advance",
    ".gb": "Game Boy",
    ".gbc": "Game Boy Color",
    ".n64": "Nintendo 64",
    ".z64": "Nintendo 64",
    ".v64": "Nintendo 64",
    ".gen": "Sega Genesis",
    ".md": "Sega Genesis",
    ".sms": "Sega Master System",
    ".gg": "Game Gear",
    ".iso": "Disc Image",
    ".cue": "Disc Image",
    ".bin": "Disc Image",
}


def classify_platform_from_extension(filename: str) -> str:
    lower = filename.lower()
    for ext, platform in EXTENSION_TO_PLATFORM.items():
        if lower.endswith(ext):
            return platform
    return "unknown"


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
