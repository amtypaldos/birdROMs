from django.conf import settings
from django.db import models

from .library import library_storage
from .services import classify_platform_from_extension, get_extension


SOURCE_CHOICES = [("upload", "Upload"), ("library", "Library")]


def keep_name(instance, filename):
    """`upload_to` that keeps the name the code assigned (the library-relative path)."""
    return filename


class ROM(models.Model):
    title = models.CharField(max_length=255)
    platform = models.CharField(max_length=120, blank=True)
    # Library-relative path (e.g. "ROMS/SFC/Game (USA).smc"); unique per ROM.
    file = models.FileField(storage=library_storage, upload_to=keep_name, max_length=1024, unique=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    # Set by a library scan when the file has vanished from the library.
    missing = models.BooleanField(default=False, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="upload")
    # Library-relative path of the cover PNG, when the library has one.
    cover_path = models.CharField(max_length=1024, blank=True, default="")
    # Original upload name; every download uses it (saves and box art key off the file name).
    filename = models.CharField(max_length=255, blank=True, default="")
    # Region / dump tags parsed from the file name, e.g. ["USA", "Verified good dump"].
    tags = models.JSONField(default=list, blank=True)
    extension = models.CharField(max_length=20, blank=True)
    # Scraped cover image, stored in the configured storage (served via /api/roms/{id}/cover/).
    cover_art = models.FileField(upload_to="covers/", blank=True)
    cover_art_source = models.CharField(max_length=120, blank=True)
    # Game metadata, scraped from ScreenScraper when it is configured (blank/null until then).
    description = models.TextField(blank=True, default="")
    genre = models.CharField(max_length=255, blank=True, default="")
    release_year = models.IntegerField(null=True, blank=True)
    developer = models.CharField(max_length=255, blank=True, default="")
    publisher = models.CharField(max_length=255, blank=True, default="")
    players = models.CharField(max_length=50, blank=True, default="")
    rating = models.CharField(max_length=20, blank=True, default="")
    region = models.CharField(max_length=20, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="roms"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def save(self, *args, **kwargs):
        if self.file and self.file.name:
            self.extension = get_extension(self.file.name)
            if not self.platform:
                self.platform = classify_platform_from_extension(self.file.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.platform})"


class Playlist(models.Model):
    """An owner-curated, ordered list of ROMs. Visible to every user; only the owner edits it."""

    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="playlists")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name


class PlaylistItem(models.Model):
    # Deleting a ROM just drops it from the playlists that held it.
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    rom = models.ForeignKey(ROM, on_delete=models.CASCADE, related_name="playlist_items")
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["playlist", "rom"], name="unique_rom_per_playlist")]

    def __str__(self):
        return f"{self.playlist_id}:{self.order}:{self.rom_id}"


class LibraryScan(models.Model):
    """One run of the library scanner: counters, unknown folders and outcome."""

    STATE_CHOICES = [("running", "Running"), ("ok", "OK"), ("aborted", "Aborted"), ("failed", "Failed")]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="running")
    added = models.PositiveIntegerField(default=0)
    changed = models.PositiveIntegerField(default=0)
    missing = models.PositiveIntegerField(default=0)
    restored = models.PositiveIntegerField(default=0)
    skipped_multifile = models.PositiveIntegerField(default=0)
    skipped_other = models.PositiveIntegerField(default=0)
    unknown_folders = models.JSONField(default=list)
    message = models.TextField(blank=True)
    accept_removals = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"scan {self.pk} ({self.state})"
