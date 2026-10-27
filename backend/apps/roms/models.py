from django.conf import settings
from django.db import models

from .services import classify_platform_from_extension, get_extension


class ROM(models.Model):
    title = models.CharField(max_length=255)
    platform = models.CharField(max_length=120, blank=True)
    file = models.FileField(upload_to="roms/")
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
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roms")
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
