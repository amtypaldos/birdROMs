import os
import re
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

# Allowed for upload.
SUPPORTED_EXTENSIONS = frozenset(EXTENSION_TO_PLATFORM)
# Every known single-file ROM/disc format: what a library scan imports and what a title drops.
ROM_EXTENSIONS = SUPPORTED_EXTENSIONS | frozenset(
    {
        ".rom", ".mgw", ".p8", ".min", ".vb", ".pak", ".a52", ".fds", ".sgx", ".col", ".adf", ".d64",
        ".t64", ".prg", ".dsk", ".st", ".msa", ".mx1", ".mx2",
    }
)  # fmt: skip
SUPPORTED_PLATFORMS = tuple(sorted(set(EXTENSION_TO_PLATFORM.values())))


def get_extension(filename: str) -> str:
    """Return the lowercase final suffix of `filename` (e.g. ".sfc"), or "" if none."""
    return os.path.splitext(os.path.basename(filename))[1].lower()


def classify_platform_from_extension(filename: str) -> str:
    return EXTENSION_TO_PLATFORM.get(get_extension(filename), UNKNOWN_PLATFORM)



@dataclass(frozen=True)
class ParsedName:
    title: str
    tags: tuple[str, ...]


# Region codes are case-sensitive ("U"); region names match case-insensitively.
REGION_CODES = {
    "U": "USA", "US": "USA", "E": "Europe", "EU": "Europe", "J": "Japan", "JP": "Japan",
    "W": "World", "UE": "USA, Europe", "JU": "Japan, USA", "K": "Korea", "G": "Germany",
    "F": "France", "S": "Spain", "I": "Italy", "A": "Australia", "B": "Brazil", "Br": "Brazil",
    "Ch": "China", "UK": "UK",
}  # fmt: skip
REGION_NAMES = {
    name.lower(): name
    for name in (
        "USA", "Europe", "Japan", "World", "Korea", "Germany", "France", "Spain", "Italy",
        "Australia", "Brazil", "China", "Asia", "Canada", "Netherlands", "Sweden", "UK",
    )
}  # fmt: skip
GROUP_REPLACEMENTS = {"proto": "Prototype", "unl": "Unlicensed"}
BRACKET_FLAGS = {"a": "Alternate", "b": "Bad dump", "f": "Fixed", "h": "Hack", "o": "Overdump", "p": "Pirate", "t": "Trained"}
SCENE_NUMBER_EXTENSIONS = frozenset({".gba", ".nds", ".3ds"})

GROUP_RE = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")
SCENE_NUMBER_RE = re.compile(r"^\d{4}\s*-\s+")
LANGUAGE_CODE_RE = re.compile(r"^[A-Z][a-z]$")
BRACKET_FLAG_RE = re.compile(r"^([abfhopt])(?:$|[0-9A-Z])")
TRAILING_ARTICLE_RE = re.compile(r"^(.+?), (the|a|an)(?= - |$)", re.IGNORECASE)


def _paren_tag(content: str) -> str:
    tokens = [token.strip() for token in content.split(",")]
    regions = [REGION_CODES.get(token) or REGION_NAMES.get(token.lower()) for token in tokens]
    if all(regions):
        return ", ".join(regions)
    if len(tokens) >= 2 and all(LANGUAGE_CODE_RE.match(token) for token in tokens):
        return ", ".join(tokens)
    content = content.strip()
    return GROUP_REPLACEMENTS.get(content.lower(), content)


def _bracket_tag(content: str) -> str:
    content = content.strip()
    if content == "!":
        return "Verified good dump"
    if content[:2] in ("T+", "T-"):
        return "Translation"
    flag = BRACKET_FLAG_RE.match(content)
    return BRACKET_FLAGS[flag.group(1)] if flag else content


def parse_rom_filename(name: str) -> ParsedName:
    """Split a ROM file name into a clean display title and region/dump tags."""
    stem = name
    first_extension = ""
    while (extension := get_extension(stem)) in ROM_EXTENSIONS:
        first_extension = first_extension or extension
        stem = stem[: -len(extension)]
    if " " not in stem:
        stem = stem.replace("_", " ")
    if first_extension in SCENE_NUMBER_EXTENSIONS:
        stem = SCENE_NUMBER_RE.sub("", stem)

    tags: list[str] = []
    for match in GROUP_RE.finditer(stem):
        paren, bracket = match.groups()
        tag = _paren_tag(paren) if paren is not None else _bracket_tag(bracket)
        if tag and tag not in tags:
            tags.append(tag)

    title = " ".join(GROUP_RE.sub(" ", stem).split()).strip(" -_")
    article = TRAILING_ARTICLE_RE.match(title)
    if article:
        title = f"{article.group(2)} {article.group(1)}{title[article.end():]}"
    title = title or stem.strip() or name.strip()
    return ParsedName(title=title, tags=tuple(tags))
