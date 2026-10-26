from django.urls import reverse
from rest_framework import serializers

from .models import ROM


class ROMSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)
    # The stored file is upload-only; clients download via the authenticated endpoint.
    file = serializers.FileField(write_only=True)
    download_url = serializers.SerializerMethodField()

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
            "uploaded_by",
            "uploaded_by_username",
            "uploaded_at",
        ]
        read_only_fields = ["uploaded_by", "extension", "cover_art_source"]

    def get_download_url(self, obj):
        path = reverse("rom-download", args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path
