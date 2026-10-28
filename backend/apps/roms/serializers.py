import os
import re

from django.conf import settings
from django.db import transaction
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from rest_framework import serializers

from .cover_art import METADATA_FIELDS
from .models import ROM, Playlist, PlaylistItem
from .services import SUPPORTED_EXTENSIONS, get_extension, parse_rom_filename

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def clean_upload_name(name):
    """The uploaded file's own name, safe to store and send back: no path, control chars or separators."""
    name = CONTROL_CHARS.sub("", os.path.basename(name))
    name = name.replace("/", "_").replace("\\", "_").strip()
    if len(name) > 255:
        stem, extension = os.path.splitext(name)
        name = stem[: 255 - len(extension)] + extension
    return name


class ROMSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)
    # The stored file is upload-only; clients download via the authenticated endpoint.
    file = serializers.FileField(write_only=True)
    download_url = serializers.SerializerMethodField()
    # Authenticated endpoint for the stored cover image, or null when there is none.
    cover_art_url = serializers.SerializerMethodField()

    class Meta:
        model = ROM
        fields = [
            "id",
            "title",
            "platform",
            "filename",
            "tags",
            "file",
            "download_url",
            "extension",
            "cover_art_url",
            "cover_art_source",
            *METADATA_FIELDS,
            "uploaded_by",
            "uploaded_by_username",
            "uploaded_at",
        ]
        read_only_fields = ["uploaded_by", "extension", "filename", "tags", "cover_art_source", *METADATA_FIELDS]
        extra_kwargs = {"title": {"required": False, "allow_blank": True}}

    def validate_title(self, title):
        # Blank is allowed only on upload (the title is then derived); editing keeps it required.
        if self.instance is not None and not title.strip():
            raise serializers.ValidationError("This field may not be blank.")
        return title

    def create(self, validated_data):
        filename = clean_upload_name(validated_data["file"].name)
        parsed = parse_rom_filename(filename)
        validated_data["filename"] = filename
        validated_data["tags"] = list(parsed.tags)
        validated_data["title"] = (validated_data.get("title") or "").strip() or parsed.title[:255]
        return super().create(validated_data)

    def validate_file(self, file):
        # Uploads are untrusted: only known ROM/archive extensions, within the size cap.
        # Empty files are already rejected by FileField (allow_empty_file=False).
        extension = get_extension(file.name)
        if extension not in SUPPORTED_EXTENSIONS:
            shown = f'"{extension}"' if extension else "Files without an extension"
            raise serializers.ValidationError(
                f"{shown} is not a supported ROM type. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
            )
        limit = settings.MAX_ROM_UPLOAD_BYTES
        if file.size > limit:
            raise serializers.ValidationError(
                f"File is {filesizeformat(file.size)}; the maximum upload size is {filesizeformat(limit)}."
            )
        return file

    def _api_url(self, name, obj):
        path = reverse(name, args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path

    def get_download_url(self, obj):
        return self._api_url("rom-download", obj)

    def get_cover_art_url(self, obj):
        return self._api_url("rom-cover", obj) if obj.cover_art else None


class DeviceROMSerializer(serializers.ModelSerializer):
    """Compact listing for the handheld client: just enough for a cover grid and a download."""

    size_bytes = serializers.SerializerMethodField()
    # Authenticated cover endpoint (fetched lazily by the client), or null when there is no cover.
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = ROM
        fields = ["id", "title", "platform", "extension", "size_bytes", "cover_url", "filename", "tags"]
        read_only_fields = fields

    def get_size_bytes(self, obj):
        # Reads from the configured storage (a HEAD request on S3). A missing or unreachable
        # file must not break the whole listing, so the size is simply unknown.
        try:
            return obj.file.size
        except Exception:
            return None

    def get_cover_url(self, obj):
        if not obj.cover_art:
            return None
        path = reverse("rom-cover", args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


# Upper bound on a playlist's size in one write; keeps the id lookup and the response bounded.
MAX_PLAYLIST_ROMS = 500


class PlaylistListSerializer(serializers.ModelSerializer):
    """Lightweight row for the (unpaginated) playlist list: no ROMs, just a count.

    `rom_count` comes from the viewset's annotation, so listing never loads the items.
    """

    rom_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Playlist
        fields = ["id", "name", "created_by", "created_at", "rom_count"]
        read_only_fields = fields


class PlaylistSerializer(serializers.ModelSerializer):
    """Detail and write shape. ROMs use the compact device shape; fetch a ROM by id for the rest."""

    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    rom_count = serializers.SerializerMethodField()
    # Read: the playlist's ROMs, in playlist order. Write: `rom_ids` (below) replaces them.
    roms = serializers.SerializerMethodField()
    # Add, remove and reorder in one call: the list is the playlist's new order. Omit to leave
    # the items untouched.
    rom_ids = serializers.ListField(
        child=serializers.IntegerField(), max_length=MAX_PLAYLIST_ROMS, write_only=True, required=False
    )

    class Meta:
        model = Playlist
        fields = ["id", "name", "created_by", "created_by_username", "created_at", "rom_count", "roms", "rom_ids"]
        read_only_fields = ["created_by", "created_at"]

    def get_rom_count(self, obj):
        return len(obj.items.all())

    def get_roms(self, obj):
        # `items` is prefetched (with `rom`) by the viewset and ordered by `PlaylistItem.Meta`.
        roms = [item.rom for item in obj.items.all()]
        return DeviceROMSerializer(roms, many=True, context=self.context).data

    def validate_rom_ids(self, rom_ids):
        if len(set(rom_ids)) != len(rom_ids):
            raise serializers.ValidationError("A ROM can only appear once in a playlist.")
        found = ROM.objects.in_bulk(rom_ids)  # One query for the whole list.
        missing = [pk for pk in rom_ids if pk not in found]
        if missing:
            raise serializers.ValidationError(f"Unknown ROM id(s): {', '.join(map(str, missing))}.")
        return [found[pk] for pk in rom_ids]

    @transaction.atomic
    def create(self, validated_data):
        roms = validated_data.pop("rom_ids", [])
        playlist = super().create(validated_data)
        self._set_items(playlist, roms)
        return playlist

    @transaction.atomic
    def update(self, instance, validated_data):
        roms = validated_data.pop("rom_ids", None)
        playlist = super().update(instance, validated_data)
        if roms is not None:
            self._set_items(playlist, roms)
        return playlist

    def _set_items(self, playlist, roms):
        playlist.items.all().delete()
        PlaylistItem.objects.bulk_create(
            PlaylistItem(playlist=playlist, rom=rom, order=order) for order, rom in enumerate(roms)
        )
        # Drop any prefetched items so the response reflects the new order.
        getattr(playlist, "_prefetched_objects_cache", {}).pop("items", None)
