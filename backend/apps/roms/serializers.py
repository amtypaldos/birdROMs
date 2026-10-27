from django.conf import settings
from django.db import transaction
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from rest_framework import serializers

from .cover_art import METADATA_FIELDS
from .models import ROM, Playlist, PlaylistItem
from .services import SUPPORTED_EXTENSIONS, get_extension


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
        read_only_fields = ["uploaded_by", "extension", "cover_art_source", *METADATA_FIELDS]

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
        fields = ["id", "title", "platform", "extension", "size_bytes", "cover_url"]
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


class PlaylistSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    rom_count = serializers.SerializerMethodField()
    # Read: the playlist's ROMs, in playlist order. Write: `rom_ids` (below) replaces them.
    roms = serializers.SerializerMethodField()
    # Add, remove and reorder in one call: the list is the playlist's new order. Omit to leave
    # the items untouched.
    rom_ids = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=ROM.objects.all()), write_only=True, required=False
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
        return ROMSerializer(roms, many=True, context=self.context).data

    def validate_rom_ids(self, roms):
        if len({rom.pk for rom in roms}) != len(roms):
            raise serializers.ValidationError("A ROM can only appear once in a playlist.")
        return roms

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
