from django.conf import settings
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from rest_framework import serializers

from .cover_art import METADATA_FIELDS
from .models import ROM
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
