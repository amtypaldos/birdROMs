from rest_framework import serializers

from .models import ROM


class ROMSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)

    class Meta:
        model = ROM
        fields = [
            "id",
            "title",
            "platform",
            "file",
            "extension",
            "cover_art_url",
            "cover_art_source",
            "uploaded_by",
            "uploaded_by_username",
            "uploaded_at",
        ]
        read_only_fields = ["uploaded_by", "extension", "cover_art_source"]
