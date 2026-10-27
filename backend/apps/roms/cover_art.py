"""Cover-art providers and the scrape-and-store pipeline.

Providers are tried in the order given by `COVER_ART_PROVIDERS` until one returns an image.
The image is downloaded (with a timeout and size cap), saved to the configured storage
(spec 005) and attached to the ROM, so cover art keeps working offline and is served through
the same permission-checked API as everything else.
"""

import html
import logging
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import quote, unquote

import requests
from django.conf import settings
from django.core.cache import cache
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
LIBRETRO_BASE = "https://thumbnails.libretro.com/"
# The name index is a ~MB directory listing per system; cache it rather than fetch on every upload.
LIBRETRO_INDEX_TTL = 24 * 60 * 60
# Minimum difflib ratio (0-1) between normalized titles to accept a libretro match. High enough
# to reject different games (and "Foo" vs "Foo Deluxe"), low enough to forgive small typos.
LIBRETRO_MATCH_THRESHOLD = 0.85

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
# Languages preferred for free text (synopsis, genre names); otherwise the first one ScreenScraper lists.
SCREENSCRAPER_LANGUAGES = ("en",)
# ROM columns filled from ScreenScraper's game metadata.
METADATA_FIELDS = ("description", "genre", "release_year", "developer", "publisher", "players", "rating", "region")


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


_TAGS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NON_WORD = re.compile(r"[\W_]+")
_TRAILING_ARTICLE = re.compile(r"^(.*), (the|a|an)$")
_HREF_PNG = re.compile(r'href="([^"]+)\.png"', re.IGNORECASE)
# Sequel markers: digits and roman numerals. "Sonic 2" is not a match for "Sonic", however
# similar the strings are.
_SEQUEL_TOKEN = re.compile(r"^(\d+|[ivx]{2,})$")
_REGION_PREFERENCE = ("(usa", "(world", "(europe")


def normalize_title(name: str) -> str:
    """Lowercase `name`, dropping `(region)`/`[flag]` tags and punctuation, collapsing whitespace.
    No-Intro's trailing article ("Legend of Zelda, The") is moved to the front."""
    name = _TAGS.sub(" ", name).casefold().strip()
    article = _TRAILING_ARTICLE.match(name)
    if article:
        name = f"{article.group(2)} {article.group(1)}"
    return _NON_WORD.sub(" ", name).strip()


def libretro_name_index(system: str, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """The thumbnail names (without `.png`) libretro has boxart for in `system`. Cached; a missing
    listing yields an empty list, which is not cached. Network errors propagate."""
    key = f"libretro-index:{quote(system)}"  # Cache keys may not contain spaces.
    names = cache.get(key)
    if names is not None:
        return names
    url = f"{LIBRETRO_BASE}{quote(f'{system}/Named_Boxarts/')}"
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    if response.status_code == 404:
        return []
    response.raise_for_status()
    listing = response.content.decode("utf-8", errors="replace")
    names = [html.unescape(unquote(href)) for href in _HREF_PNG.findall(listing)]
    if names:
        cache.set(key, names, LIBRETRO_INDEX_TTL)
    return names


def _sequel_tokens(normalized):
    return sorted(token for token in normalized.split() if _SEQUEL_TOKEN.match(token))


def best_libretro_name(title: str, platform: str, index: list[str]) -> str | None:
    """The `index` entry whose normalized form is closest to `title`, or None if none reaches
    `LIBRETRO_MATCH_THRESHOLD`. Equal matches prefer an exact name, then USA/World/Europe releases."""
    wanted = normalize_title(title)
    if not wanted:
        return None
    wanted_sequel = _sequel_tokens(wanted)
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(wanted)
    best, best_key = None, None
    for name in index:
        candidate = normalize_title(name)
        matcher.set_seq1(candidate)
        # The cheap upper bounds skip nearly all of a multi-thousand entry index.
        if matcher.real_quick_ratio() < LIBRETRO_MATCH_THRESHOLD or matcher.quick_ratio() < LIBRETRO_MATCH_THRESHOLD:
            continue
        ratio = matcher.ratio()
        if ratio < LIBRETRO_MATCH_THRESHOLD or _sequel_tokens(candidate) != wanted_sequel:
            continue
        lowered = name.casefold()
        region = next((i for i, tag in enumerate(_REGION_PREFERENCE) if tag in lowered), len(_REGION_PREFERENCE))
        key = (ratio, name == title.strip(), -region)
        if best_key is None or key > best_key:
            best, best_key = name, key
    return best


def find_libretro(title, platform, filename, config):
    system = LIBRETRO_SYSTEMS.get(platform)
    if not system:
        return []
    try:
        index = libretro_name_index(system, config.timeout)
    except requests.RequestException as exc:
        # Without the index we can still guess the exact name, as we did before it existed.
        logger.warning("libretro name index for %s unavailable: %s", system, exc)
        index = []
    # Use libretro's own spelling when we can match it; otherwise guess the name as given.
    names = []
    for candidate in _title_candidates(title, filename):
        name = best_libretro_name(candidate, platform, index) or candidate
        if name not in names:
            names.append(name)
    urls = []
    for kind in LIBRETRO_KINDS:
        for name in names:
            safe = LIBRETRO_UNSAFE.sub("_", name)
            urls.append(f"{LIBRETRO_BASE}{quote(f'{system}/{kind}/{safe}.png')}")
    return urls


def lookup_screenscraper_game(title, platform, filename, config):
    """The ScreenScraper `jeu` payload for a ROM, or None if it is unconfigured or unknown there.
    Network and decoding errors propagate."""
    creds = config.screenscraper
    if not (creds["dev_id"] and creds["dev_password"]):
        return None  # Not configured: skip silently.
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
        return None  # ScreenScraper answers 404 when it does not know the game.
    response.raise_for_status()
    payload = response.json()
    jeu = payload.get("response", {}).get("jeu") if isinstance(payload, dict) else None
    return jeu if isinstance(jeu, dict) else None


def screenscraper_image_urls(jeu):
    """Cover candidates from a `jeu` payload: box art first, then title screen, then screenshot."""
    medias = (jeu or {}).get("medias") or []

    def rank(media):
        region = media.get("region", "")
        return (
            SCREENSCRAPER_MEDIA.index(media["type"]),
            SCREENSCRAPER_REGIONS.index(region) if region in SCREENSCRAPER_REGIONS else len(SCREENSCRAPER_REGIONS),
        )

    usable = [m for m in medias if m.get("type") in SCREENSCRAPER_MEDIA and m.get("url")]
    return [m["url"] for m in sorted(usable, key=rank)]


def find_screenscraper(title, platform, filename, config):
    return screenscraper_image_urls(lookup_screenscraper_game(title, platform, filename, config))


def _text(value):
    """The string in a ScreenScraper value, which is either a bare string or `{"text": ...}`."""
    if isinstance(value, dict):
        value = value.get("text")
    return value.strip() if isinstance(value, str) else ""


def _entries(value):
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _localized(entries, key, preferred):
    """The text of the entry whose `key` ("langue") ranks best in `preferred`; unlisted values
    rank last, in payload order. Entries without text are ignored."""
    entries = [e for e in _entries(entries) if _text(e)]
    rank = lambda e: preferred.index(e.get(key)) if e.get(key) in preferred else len(preferred)
    return _text(min(entries, key=rank)) if entries else ""


def parse_screenscraper_metadata(jeu: dict) -> dict:
    """Map a ScreenScraper `jeu` payload to ROM metadata fields (see `METADATA_FIELDS`).

    Free text prefers English and dates prefer `SCREENSCRAPER_REGIONS` order; the `region` is that
    of the chosen release date. Best effort: anything missing or malformed is omitted, and values
    are clipped to their column width."""
    from .models import ROM  # Deferred: this module is imported while settings load, before models can be.

    jeu = jeu if isinstance(jeu, dict) else {}
    metadata = {"description": _localized(jeu.get("synopsis"), "langue", SCREENSCRAPER_LANGUAGES)}

    genres = []
    for genre in _entries(jeu.get("genres")):
        name = _localized(genre.get("noms"), "langue", SCREENSCRAPER_LANGUAGES)
        if name and name not in genres:
            genres.append(name)
    metadata["genre"] = ", ".join(genres)

    dates = [(d.get("region"), re.match(r"\d{4}", _text(d))) for d in _entries(jeu.get("dates"))]
    dates = [(region, int(match.group())) for region, match in dates if match]
    if dates:
        unlisted = len(SCREENSCRAPER_REGIONS)
        region, year = min(dates, key=lambda d: SCREENSCRAPER_REGIONS.index(d[0]) if d[0] in SCREENSCRAPER_REGIONS else unlisted)
        metadata.update(release_year=year, region=region if isinstance(region, str) else "")

    metadata["developer"] = _text(jeu.get("developpeur"))
    metadata["publisher"] = _text(jeu.get("editeur"))
    metadata["players"] = _text(jeu.get("joueurs"))
    rating = _text(jeu.get("note"))  # ScreenScraper rates out of 20.
    metadata["rating"] = f"{rating}/20" if re.fullmatch(r"\d+(\.\d+)?", rating) else ""

    for field, value in metadata.items():
        limit = getattr(ROM._meta.get_field(field), "max_length", None)
        if limit and isinstance(value, str):
            metadata[field] = value[:limit]
    return {field: value for field, value in metadata.items() if value not in ("", None)}


class ScreenScraperGame:
    """Lazy, memoized ScreenScraper lookup for one ROM, so a scrape asks the API at most once for
    both the cover and the metadata. A failed lookup is logged and reads as "no game"."""

    def __init__(self, title, platform, filename, config):
        self._args = (title, platform, filename, config)
        self._looked_up = False
        self._jeu = None

    @property
    def jeu(self):
        if not self._looked_up:
            self._looked_up = True
            try:
                self._jeu = lookup_screenscraper_game(*self._args)
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Cover art provider %s failed for %r: %s", SCREENSCRAPER, self._args[0], exc)
        return self._jeu

    def image_urls(self):
        return screenscraper_image_urls(self.jeu)

    def metadata(self):
        return parse_screenscraper_metadata(self.jeu)


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


def scrape_cover_art(title, platform, filename="", config=None, screenscraper=None):
    """Try each configured provider in order. Returns `(image_bytes, extension, CoverArtResult)`
    for the first image found, or None. A failing provider is logged and the next one tried.
    Pass a `ScreenScraperGame` as `screenscraper` to share its lookup with the caller."""
    config = config or settings.COVER_ART
    for provider in config.providers:
        try:
            if provider == SCREENSCRAPER and screenscraper is not None:
                urls = screenscraper.image_urls()
            else:
                urls = FINDERS[provider](title, platform, filename, config)
            for url in urls:
                image = download_image(url, config)
                if image:
                    return image[0], image[1], CoverArtResult(image_url=url, source=provider)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Cover art provider %s failed for %r: %s", provider, title, exc)
    return None


def fetch_cover_for_rom(rom, config=None) -> bool:
    """Scrape cover art and, when ScreenScraper is configured, metadata for `rom` and store them.
    Metadata comes from ScreenScraper whichever provider supplied the cover. Returns True if new
    art was saved."""
    config = config or settings.COVER_ART
    filename = rom.file.name if rom.file else ""
    game = ScreenScraperGame(rom.title, rom.platform, filename, config) if SCREENSCRAPER in config.providers else None
    found = scrape_cover_art(rom.title, rom.platform, filename, config, screenscraper=game)
    metadata = game.metadata() if game else {}
    if not found and not metadata:
        return False
    update_fields = list(metadata)
    for field, value in metadata.items():
        setattr(rom, field, value)
    old = ""
    if found:
        data, extension, result = found
        old = rom.cover_art.name if rom.cover_art else ""
        rom.cover_art.save(f"rom-{rom.pk}{extension}", ContentFile(data), save=False)
        rom.cover_art_source = result.source
        update_fields += ["cover_art", "cover_art_source"]
    rom.save(update_fields=update_fields)
    if old and old != rom.cover_art.name:
        rom.cover_art.storage.delete(old)
    return bool(found)


def safe_fetch_cover_for_rom(rom) -> bool:
    """`fetch_cover_for_rom` that never raises: scraping must not break uploads."""
    try:
        return fetch_cover_for_rom(rom)
    except Exception:
        logger.exception("Cover art scrape failed for ROM %s", rom.pk)
        return False
