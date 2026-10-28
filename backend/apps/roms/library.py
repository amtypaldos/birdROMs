"""The ROM library: a muOS-layout tree (`ROMS/<SYSTEM>/<file>`, `ROMS/<SYSTEM>/Imgs/<png>`)
on a folder or in an S3 bucket, listed in place.

birdROMs never deletes, moves or overwrites anything here; `write_new` only creates files.
"""

import contextlib
import os
import secrets
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage, Storage

from .platform_aliases import platform_for_folder

SYSTEMS_FOLDERS = ("ROMS", "Roms")
IMGS_FOLDER = "imgs"
# Hidden upload temp name, short whatever the target's name (file names are capped at 255 bytes).
TEMP_NAME = ".birdroms-upload.{}.part"


class LibraryUnavailable(Exception):
    """The library root or its systems folder can't be listed (share down, bucket unreachable)."""


@dataclass(frozen=True)
class LibraryEntry:
    path: str  # "/"-separated, relative to the library root
    size: int
    modified: datetime  # timezone-aware UTC


def _hidden(name):
    return name.startswith(".")


def _in_layout(relative_parts):
    """True for `<SYS>/<file>` and `<SYS>/<Imgs>/<file>` (parts relative to the systems folder)."""
    if any(not part or _hidden(part) for part in relative_parts):
        return False
    if len(relative_parts) == 2:
        return True
    return len(relative_parts) == 3 and relative_parts[1].lower() == IMGS_FOLDER


class Library(ABC):
    read_only = False
    # After `entries()` is exhausted: system folder name -> number of non-Imgs subfolders the
    # listing skipped (games inside subfolders are not imported).
    subfolders: dict[str, int]

    @property
    @abstractmethod
    def systems_prefix(self) -> str:
        """`"ROMS"`, `"Roms"`, or `""` when the system folders sit directly at the root."""

    @property
    @abstractmethod
    def writable(self) -> bool: ...

    @property
    @abstractmethod
    def storage(self) -> Storage:
        """A Django storage rooted at the library root."""

    @abstractmethod
    def entries(self) -> Iterator[LibraryEntry]: ...

    def exists(self, path: str) -> bool:
        return self.storage.exists(path)

    def exists_exact(self, path: str, names: dict[str, set[str]]) -> bool:
        """`exists`, with every component of `path` in its exact case; `names` caches folder ->
        child names across the calls of one scan. This default suits case-sensitive backends."""
        return self.exists(path)

    def modified_time(self, path: str) -> datetime:
        """When `path` last changed (UTC), as a scan sees it; now when the backend can't tell."""
        try:
            return self.storage.get_modified_time(path).astimezone(timezone.utc)
        except Exception:  # an S3 HEAD that failed, a storage without modified times
            return datetime.now(timezone.utc)

    def system_folder(self, systems: str, muos_folder: str) -> str:
        """The folder under `systems` for a `muos_folder` upload: that folder when it exists, else
        an existing folder of the same platform (`snes`, a lower-case `sfc`), else `muos_folder`."""
        names = sorted(name for name, is_dir in self._children(systems) if is_dir)
        if muos_folder in names:
            return muos_folder
        for name in names:
            info = platform_for_folder(name)
            if info is not None and info.muos_folder == muos_folder:
                return name
        return muos_folder

    @abstractmethod
    def _children(self, path: str) -> list[tuple[str, bool]]:
        """`(name, is_dir)` of the visible direct children of the library-relative folder `path`."""

    def find_cover(self, system_dir: str, stem: str) -> tuple[str, str | None]:
        """`(cover folder name, path of an existing cover or None)` for `stem` in `system_dir`.

        The cover folder keeps whatever case it already has (`imgs`, `IMGS`, ...), `Imgs` when
        there is none; an existing `<stem>.png` is matched in any case (`Game.PNG`).
        """
        folders = sorted(name for name, is_dir in self._children(system_dir) if is_dir and name.lower() == IMGS_FOLDER)
        if not folders:
            return "Imgs", None
        folder = "Imgs" if "Imgs" in folders else folders[0]
        wanted = f"{stem}.png".lower()
        names = sorted(name for name, is_dir in self._children(f"{system_dir}/{folder}") if not is_dir)
        found = next((name for name in names if name.lower() == wanted), None)
        return folder, f"{system_dir}/{folder}/{found}" if found else None

    def _ensure_available(self) -> None:
        """Raise `LibraryUnavailable` when the library can't be reached (checked before writing)."""

    def write_new(self, path: str, content: bytes | File) -> None:
        """Create `path` from `content` (bytes or a Django `File`, streamed); never overwrites.

        Raises `PermissionError` (read-only), `LibraryUnavailable`, `ValueError` (the path
        escapes the library) or `FileExistsError`.
        """
        if self.read_only:
            raise PermissionError("The library is read-only.")
        self._ensure_available()
        if not self.writable:
            raise PermissionError("The library is read-only.")
        if path.startswith("/") or ".." in path.replace("\\", "/").split("/"):
            raise ValueError(f"Path escapes the library: {path!r}")
        try:
            if self.exists(path):
                raise FileExistsError(path)
            self._write(path, content if isinstance(content, File) else ContentFile(content))
        except SuspiciousFileOperation as exc:
            raise ValueError(f"Path escapes the library: {path!r}") from exc

    @abstractmethod
    def _write(self, path: str, content: File) -> None: ...


class FilesystemLibrary(Library):
    def __init__(self, root: str, read_only: bool):
        self.root = root
        self.read_only = read_only

    @property
    def systems_prefix(self) -> str:
        try:
            names = {entry.name for entry in os.scandir(self.root) if entry.is_dir()}
        except OSError:
            return ""
        return next((name for name in SYSTEMS_FOLDERS if name in names), "")

    @property
    def writable(self) -> bool:
        return not self.read_only and os.access(self.root, os.W_OK)

    def _ensure_available(self):
        if not os.path.isdir(self.root):
            raise LibraryUnavailable(f"The library folder {self.root} does not exist.")

    @property
    def storage(self) -> Storage:
        return FileSystemStorage(location=self.root)

    def _dirs(self, path):
        with os.scandir(path) as it:
            return [e for e in it if not _hidden(e.name) and e.is_dir()]

    def exists_exact(self, path, names):
        """exFAT, APFS and SMB match names in any case, so `exists` can't tell that `SFC/Game.smc`
        became `sfc/game.smc`: each component must be listed, in that case, in its parent."""
        folder = ""
        for part in path.split("/"):
            if folder not in names:
                names[folder] = self._names(folder)
            if part not in names[folder]:
                return False
            folder = f"{folder}/{part}" if folder else part
        return True

    def _names(self, folder):
        """Every name (hidden ones too) directly in the library-relative `folder`."""
        try:
            return set(os.listdir(os.path.join(self.root, folder)))
        except (FileNotFoundError, NotADirectoryError):
            return set()
        except OSError as exc:
            raise LibraryUnavailable(f"Cannot list {folder} in the library at {self.root}: {exc}") from exc

    def _children(self, path):
        try:
            with os.scandir(os.path.join(self.root, path)) as it:
                return [(e.name, e.is_dir()) for e in it if not _hidden(e.name)]
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise LibraryUnavailable(f"Cannot list {path} in the library at {self.root}: {exc}") from exc

    def _files(self, path):
        with os.scandir(path) as it:
            for e in it:
                if not _hidden(e.name) and e.is_file():
                    yield e

    def _entry(self, dir_entry, prefix):
        stat = dir_entry.stat()
        return LibraryEntry(
            path=f"{prefix}{dir_entry.name}",
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        )

    def entries(self) -> Iterator[LibraryEntry]:
        systems = self.systems_prefix
        base = os.path.join(self.root, systems) if systems else self.root
        lead = f"{systems}/" if systems else ""
        self.subfolders = {}
        try:
            system_dirs = self._dirs(base)
            for system in system_dirs:
                prefix = f"{lead}{system.name}/"
                subdirs = []
                with os.scandir(system.path) as it:
                    for e in it:
                        if _hidden(e.name):
                            continue
                        if e.is_dir():
                            if e.name.lower() == IMGS_FOLDER:
                                subdirs.append(e)
                            else:
                                self.subfolders[system.name] = self.subfolders.get(system.name, 0) + 1
                        elif e.is_file():
                            yield self._entry(e, prefix)
                for imgs in subdirs:
                    for e in self._files(imgs.path):
                        yield self._entry(e, f"{prefix}{imgs.name}/")
        except OSError as exc:
            raise LibraryUnavailable(f"Cannot list the library at {self.root}: {exc}") from exc

    def _write(self, path, content):
        """Write a hidden `.birdroms-upload.<random>.part` beside the target, then publish it with
        a hard link (atomic, and fails if the target appeared meanwhile), so a partial upload is
        never seen under its final name. Without hard links the temp is copied in place ("x":
        never over a file)."""
        target = self.storage.path(path)
        folder = os.path.dirname(target)
        os.makedirs(folder, exist_ok=True)
        temp = os.path.join(folder, TEMP_NAME.format(secrets.token_hex(4)))
        try:
            with open(temp, "xb") as handle:
                for chunk in content.chunks():
                    handle.write(chunk)
            try:
                os.link(temp, target)
            except FileExistsError:
                raise
            except OSError:  # no hard links here (exFAT, some SMB shares)
                with open(temp, "rb") as source, open(target, "xb") as handle:
                    try:
                        shutil.copyfileobj(source, handle)
                    except BaseException:
                        os.unlink(target)  # our own partial copy ("x" made it), never a library file
                        raise
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp)


class S3Library(Library):
    def __init__(self, storage, prefix: str, read_only: bool):
        self._storage = storage
        self.prefix = prefix.strip("/")
        self.read_only = read_only

    @property
    def _list_prefix(self):
        return f"{self.prefix}/" if self.prefix else ""

    @property
    def systems_prefix(self) -> str:
        objects = self._storage.bucket.objects
        try:
            for name in SYSTEMS_FOLDERS:
                if next(iter(objects.filter(Prefix=f"{self._list_prefix}{name}/")), None) is not None:
                    return name
        except Exception as exc:  # botocore errors: unreachable, bad credentials, no bucket
            raise LibraryUnavailable(f"Cannot list the S3 library: {exc}") from exc
        return ""

    @property
    def writable(self) -> bool:
        return not self.read_only

    @property
    def storage(self) -> Storage:
        return self._storage

    def exists(self, path):
        try:
            return self._storage.exists(path)
        except Exception as exc:  # botocore errors: unreachable, bad credentials, no bucket
            raise LibraryUnavailable(f"Cannot reach the S3 library: {exc}") from exc

    def _children(self, path):
        base = f"{self._list_prefix}{path}/" if path else self._list_prefix
        try:
            keys = [obj.key[len(base):] for obj in self._storage.bucket.objects.filter(Prefix=base)]
        except Exception as exc:  # botocore errors: unreachable, bad credentials, no bucket
            raise LibraryUnavailable(f"Cannot list the S3 library: {exc}") from exc
        children = {}
        for key in keys:
            name, slash, _rest = key.partition("/")
            if name and not _hidden(name):
                children[name] = children.get(name, False) or bool(slash)
        return list(children.items())

    def entries(self) -> Iterator[LibraryEntry]:
        cut = len(self._list_prefix)
        try:
            found = [
                LibraryEntry(obj.key[cut:], obj.size, obj.last_modified.astimezone(timezone.utc))
                for obj in self._storage.bucket.objects.filter(Prefix=self._list_prefix)
            ]
        except Exception as exc:  # botocore errors: unreachable, bad credentials, no bucket
            raise LibraryUnavailable(f"Cannot list the S3 library: {exc}") from exc
        if not found:
            raise LibraryUnavailable("The S3 library is empty or unreachable.")
        systems = next((n for n in SYSTEMS_FOLDERS if any(e.path.startswith(f"{n}/") for e in found)), "")
        depth = len(systems.split("/")) if systems else 0
        self.subfolders = {}
        seen = set()
        for entry in found:
            parts = entry.path.split("/")
            if systems and parts[0] != systems:
                continue
            rel = parts[depth:]
            if (
                len(rel) >= 3
                and not any(not part or _hidden(part) for part in rel)
                and rel[1].lower() != IMGS_FOLDER
                and (rel[0], rel[1]) not in seen
            ):
                seen.add((rel[0], rel[1]))
                self.subfolders[rel[0]] = self.subfolders.get(rel[0], 0) + 1
            if _in_layout(parts[depth:]):
                yield entry

    def _write(self, path, content):
        saved = self._storage.save(path, content)
        if saved != path:  # `file_overwrite=False` renames on a race instead of failing
            raise FileExistsError(path)


def get_library() -> Library:
    """The library configured by `settings.LIBRARY`."""
    config = settings.LIBRARY
    if config.backend == "s3":
        from storages.backends.s3 import S3Storage

        from birdroms.storage import _s3_options

        options = {**_s3_options(os.environ), "location": config.s3_prefix.strip("/"), "file_overwrite": False}
        return S3Library(S3Storage(**options), config.s3_prefix, config.read_only)
    return FilesystemLibrary(config.root, config.read_only)


def library_storage() -> Storage:
    """Callable storage for `FileField(storage=...)`, rooted at the library."""
    return get_library().storage
