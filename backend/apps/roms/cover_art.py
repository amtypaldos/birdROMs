"""Cover-art providers and the scrape-and-store pipeline.

Providers are tried in the order given by `COVER_ART_PROVIDERS` until one returns an image.
The image is downloaded (with a timeout and size cap), saved to the configured storage
(spec 005) and attached to the ROM, so cover art keeps working offline and is served through
the same permission-checked API as everything else.
"""

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

LIBRETRO = "libretro"
SCREENSCRAPER = "screenscraper"
PROVIDERS = (LIBRETRO, SCREENSCRAPER)
DEFAULT_PROVIDERS = (LIBRETRO, SCREENSCRAPER)
DEFAULT_TIMEOUT = 10.0
MAX_IMAGE_BYTES = 10 * 1024**2  # Cover art is small; anything larger is not a thumbnail.
USER_AGENT = "birdROMs cover-art scraper"

IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# birdROMs platform -> libretro-thumbnails system directory.
LIBRETRO_SYSTEMS = {
    "NES": "Nintendo - Nintendo Entertainment System",
    "SNES": "Nintendo - Super Nintendo Entertainment System",
    "Nintendo 64": "Nintendo - Nintendo 64",
    "Nintendo GameCube": "Nintendo - GameCube",
    "Nintendo Wii": "Nintendo - Wii",
    "Game Boy": "Nintendo - Game Boy",
    "Game Boy Color": "Nintendo - Game Boy Color",
    "Game Boy Advance": "Nintendo - Game Boy Advance",
    "Nintendo DS": "Nintendo - Nintendo DS",
    "Nintendo 3DS": "Nintendo - Nintendo 3DS",
    "Sega Master System": "Sega - Master System - Mark III",
    "Sega Genesis": "Sega - Mega Drive - Genesis",
    "Sega Game Gear": "Sega - Game Gear",
    "Sega 32X": "Sega - 32X",
    "Sega Dreamcast": "Sega - Dreamcast",
    "Sony PlayStation": "Sony - PlayStation",
    "Sony PSP": "Sony - PlayStation Portable",
    "PC Engine / TurboGrafx-16": "NEC - PC Engine - TurboGrafx 16",
    "Neo Geo Pocket": "SNK - Neo Geo Pocket",
    "Neo Geo Pocket Color": "SNK - Neo Geo Pocket Color",
    "WonderSwan": "Bandai - WonderSwan",
    "WonderSwan Color": "Bandai - WonderSwan Color",
    "Atari 2600": "Atari - 2600",
    "Atari 7800": "Atari - 7800",
    "Atari Lynx": "Atari - Lynx",
    "Atari Jaguar": "Atari - Jaguar",
}
# Boxart first, then title screen, then in-game snapshot.
LIBRETRO_KINDS = ("Named_Boxarts", "Named_Titles", "Named_Snaps")
# libretro-thumbnails replaces these characters with "_" in file names.
LIBRETRO_UNSAFE = re.compile(r'[&*/:`<>?\\|"]')

# birdROMs platform -> ScreenScraper `systemeid`.
SCREENSCRAPER_SYSTEMS = {
    "Sega Genesis": 1,
    "Sega Master System": 2,
    "NES": 3,
    "SNES": 4,
    "Game Boy": 9,
    "Game Boy Color": 10,
    "Game Boy Advance": 12,
    "Nintendo GameCube": 13,
    "Nintendo 64": 14,
    "Nintendo DS": 15,
    "Nintendo Wii": 16,
    "Nintendo 3DS": 17,
    "Sega 32X": 19,
    "Sega Game Gear": 21,
    "Sega Dreamcast": 23,
    "Neo Geo Pocket": 25,
    "Atari 2600": 26,
    "Atari Jaguar": 27,
    "Atari Lynx": 28,
    "PC Engine / TurboGrafx-16": 31,
    "Atari 7800": 41,
    "WonderSwan": 45,
    "WonderSwan Color": 46,
    "Sony PlayStation": 57,
    "Sony PSP": 61,
    "Neo Geo Pocket Color": 82,
}
SCREENSCRAPER_API = "https://api.screenscraper.fr/api2/jeuInfos.php"
# Preferred media types, best first: 2D box front, title screen, screenshot.
SCREENSCRAPER_MEDIA = ("box-2D", "sstitle", "ss")
SCREENSCRAPER_REGIONS = ("us", "wor", "eu", "ss", "jp")


@dataclass(frozen=True)
class CoverArtSettings:
    providers: tuple
    timeout: float
    screenscraper: dict


def parse_cover_art_settings(env) -> CoverArtSettings:
    """Read `COVER_ART_PROVIDERS`, `COVER_ART_TIMEOUT` and the `SS_*` credentials from `env`."""
    raw = env.get("COVER_ART_PROVIDERS")
    if raw is None:
        providers = DEFAULT_PROVIDERS
    else:
        providers = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
        unknown = [p for p in providers if p not in PROVIDERS]
        if unknown:
            raise ImproperlyConfigured(
                f"Unknown COVER_ART_PROVIDERS {', '.join(unknown)}; expected any of: {', '.join(PROVIDERS)}."
            )
    raw_timeout = (env.get("COVER_ART_TIMEOUT") or "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
    except ValueError:
        raise ImproperlyConfigured(f"COVER_ART_TIMEOUT must be a number of seconds, got {raw_timeout!r}.")
    if timeout <= 0:
        raise ImproperlyConfigured(f"COVER_ART_TIMEOUT must be positive, got {timeout}.")
    screenscraper = {
        key: env.get(f"SS_{key.upper()}", "").strip() for key in ("dev_id", "dev_password", "user", "password")
    }
    return CoverArtSettings(providers=providers, timeout=timeout, screenscraper=screenscraper)


@dataclass
class CoverArtResult:
    image_url: str | None
    source: str | None


def _title_candidates(title, filename):
    """Names to try: the ROM title and the uploaded file's stem (often a No-Intro name)."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    # Drop the dedup suffix Django storage may add (`zelda_OvlBGqX`).
    stem = re.sub(r"_[A-Za-z0-9]{7}$", "", stem)
    candidates = []
    for name in (title, stem):
        name = (name or "").strip()
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def find_libretro(title, platform, filename, config):
    system = LIBRETRO_SYSTEMS.get(platform)
    if not system:
        return []
    urls = []
    for kind in LIBRETRO_KINDS:
        for name in _title_candidates(title, filename):
            safe = LIBRETRO_UNSAFE.sub("_", name)
            urls.append(f"https://thumbnails.libretro.com/{quote(f'{system}/{kind}/{safe}.png')}")
    return urls


def find_screenscraper(title, platform, filename, config):
    creds = config.screenscraper
    if not (creds["dev_id"] and creds["dev_password"]):
        return []  # Not configured: skip silently.
    params = {
        "devid": creds["dev_id"],
        "devpassword": creds["dev_password"],
        "softname": "birdROMs",
        "output": "json",
        "romnom": os.path.basename(filename or "") or title,
        "romtype": "rom",
    }
    if creds["user"] and creds["password"]:
        params.update(ssid=creds["user"], sspassword=creds["password"])
    if platform in SCREENSCRAPER_SYSTEMS:
        params["systemeid"] = SCREENSCRAPER_SYSTEMS[platform]
    response = requests.get(SCREENSCRAPER_API, params=params, timeout=config.timeout, headers={"User-Agent": USER_AGENT})
    if response.status_code == 404:
        return []  # ScreenScraper answers 404 when it does not know the game.
    response.raise_for_status()
    medias = response.json().get("response", {}).get("jeu", {}).get("medias", []) or []

    def rank(media):
        region = media.get("region", "")
        return (
            SCREENSCRAPER_MEDIA.index(media["type"]),
            SCREENSCRAPER_REGIONS.index(region) if region in SCREENSCRAPER_REGIONS else len(SCREENSCRAPER_REGIONS),
        )

    usable = [m for m in medias if m.get("type") in SCREENSCRAPER_MEDIA and m.get("url")]
    return [m["url"] for m in sorted(usable, key=rank)]


FINDERS = {LIBRETRO: find_libretro, SCREENSCRAPER: find_screenscraper}


def download_image(url, config):
    """Fetch `url` and return `(bytes, extension)`, or None if it is missing or not an image."""
    with requests.get(url, timeout=config.timeout, stream=True, headers={"User-Agent": USER_AGENT}) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        extension = IMAGE_EXTENSIONS.get(content_type)
        if not extension:
            return None
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_IMAGE_BYTES:
                logger.warning("Cover art at %s exceeds %d bytes; skipping.", url, MAX_IMAGE_BYTES)
                return None
        return (bytes(data), extension) if data else None


def scrape_cover_art(title, platform, filename="", config=None):
    """Try each configured provider in order. Returns `(image_bytes, extension, CoverArtResult)`
    for the first image found, or None. A failing provider is logged and the next one tried."""
    config = config or settings.COVER_ART
    for provider in config.providers:
        try:
            for url in FINDERS[provider](title, platform, filename, config):
                image = download_image(url, config)
                if image:
                    return image[0], image[1], CoverArtResult(image_url=url, source=provider)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Cover art provider %s failed for %r: %s", provider, title, exc)
    return None


def fetch_cover_for_rom(rom, config=None) -> bool:
    """Scrape cover art for `rom` and store it. Returns True if new art was saved."""
    found = scrape_cover_art(rom.title, rom.platform, rom.file.name if rom.file else "", config)
    if not found:
        return False
    data, extension, result = found
    old = rom.cover_art.name if rom.cover_art else ""
    rom.cover_art.save(f"rom-{rom.pk}{extension}", ContentFile(data), save=False)
    rom.cover_art_source = result.source
    rom.save(update_fields=["cover_art", "cover_art_source"])
    if old and old != rom.cover_art.name:
        rom.cover_art.storage.delete(old)
    return True


def safe_fetch_cover_for_rom(rom) -> bool:
    """`fetch_cover_for_rom` that never raises: scraping must not break uploads."""
    try:
        return fetch_cover_for_rom(rom)
    except Exception:
        logger.exception("Cover art scrape failed for ROM %s", rom.pk)
        return False
