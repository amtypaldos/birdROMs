from pathlib import PurePosixPath

from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import ROM
from .permissions import IsSuperAdminOrReadOnlyRole
from .serializers import ROMSerializer
from .services import scrape_cover_art


def download_filename(rom):
    """Friendly attachment name: the ROM title plus its extension, not the storage key
    (which may carry a dedup suffix like `zelda_OvlBGqX.nes`)."""
    title = rom.title.replace("/", "_").replace("\\", "_").strip()
    if not title:
        return PurePosixPath(rom.file.name).name
    if rom.extension and not title.lower().endswith(rom.extension):
        title += rom.extension
    return title


class ROMViewSet(viewsets.ModelViewSet):
    queryset = ROM.objects.select_related("uploaded_by").all()
    serializer_class = ROMSerializer
    permission_classes = [IsSuperAdminOrReadOnlyRole]

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)

    @action(detail=True, methods=["post"])
    def scrape_cover(self, request, pk=None):
        rom = self.get_object()
        result = scrape_cover_art(rom.title, rom.platform)
        if result.image_url:
            rom.cover_art_url = result.image_url
            rom.cover_art_source = result.source or "unknown"
            rom.save(update_fields=["cover_art_url", "cover_art_source"])
            return Response(ROMSerializer(rom).data, status=status.HTTP_200_OK)
        return Response({"detail": "No cover art found."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        # Always stream through the app so every download is permission-checked and no
        # backend (filesystem or S3) ever hands the client a permanent public URL.
        rom = self.get_object()
        return FileResponse(rom.file.open("rb"), as_attachment=True, filename=download_filename(rom))
