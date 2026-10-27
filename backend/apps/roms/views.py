import logging
import mimetypes
import re
from pathlib import PurePosixPath

from django.http import FileResponse, Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from birdroms.tasks import scrape_rom_cover

from .models import ROM
from .pagination import ROMPagination
from .permissions import IsSuperAdminOrReadOnlyRole
from .serializers import ROMSerializer
from .cover_art import scrape_rom

logger = logging.getLogger(__name__)

# Control characters (CR/LF in particular) must never reach a response header.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def download_filename(rom):
    """Friendly attachment name: the ROM title plus its extension, not the storage key
    (which may carry a dedup suffix like `zelda_OvlBGqX.nes`)."""
    title = _CONTROL_CHARS.sub("", rom.title).replace("/", "_").replace("\\", "_").strip()
    if not title:
        return PurePosixPath(rom.file.name).name
    if rom.extension and not title.lower().endswith(rom.extension):
        title += rom.extension
    return title


class ROMViewSet(viewsets.ModelViewSet):
    # `-id` breaks uploaded_at ties so pages never repeat or skip a ROM.
    queryset = ROM.objects.select_related("uploaded_by").order_by("-uploaded_at", "-id")
    serializer_class = ROMSerializer
    permission_classes = [IsSuperAdminOrReadOnlyRole]
    pagination_class = ROMPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action != "list":
            return queryset
        search = self.request.query_params.get("search", "").strip()
        platform = self.request.query_params.get("platform", "").strip()
        if search:
            queryset = queryset.filter(title__icontains=search)
        if platform:
            queryset = queryset.filter(platform=platform)
        return queryset

    def perform_create(self, serializer):
        rom = serializer.save(uploaded_by=self.request.user)
        # The upload has already succeeded; the scrape runs in the background and a failure
        # there (including an unreachable queue broker) is logged, never surfaced.
        try:
            scrape_rom_cover(rom.id)
        except Exception:
            logger.exception("Could not enqueue the cover art scrape for ROM %s", rom.id)

    @action(detail=False, methods=["get"])
    def platforms(self, request):
        platforms = (
            ROM.objects.exclude(platform="").order_by("platform").values_list("platform", flat=True).distinct()
        )
        return Response(list(platforms))

    @action(detail=True, methods=["post"])
    def scrape_cover(self, request, pk=None):
        # Manual (re-)scrape: replaces any existing cover art. 200 when anything was saved (cover
        # or metadata), 404 only when nothing was found. Never a 500: provider errors are logged.
        rom = self.get_object()
        try:
            saved = any(scrape_rom(rom))
        except Exception:
            logger.exception("Manual cover art scrape failed for ROM %s", rom.pk)
            saved = False
        if saved:
            return Response(self.get_serializer(rom).data, status=status.HTTP_200_OK)
        return Response({"detail": "No cover art found."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["get"])
    def cover(self, request, pk=None):
        # Cover art lives next to the ROMs in private storage, so it is served the same way.
        rom = self.get_object()
        if not rom.cover_art:
            raise Http404("This ROM has no cover art.")
        content_type = mimetypes.guess_type(rom.cover_art.name)[0] or "application/octet-stream"
        return FileResponse(rom.cover_art.open("rb"), content_type=content_type)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        # Always stream through the app so every download is permission-checked and no
        # backend (filesystem or S3) ever hands the client a permanent public URL.
        rom = self.get_object()
        return FileResponse(rom.file.open("rb"), as_attachment=True, filename=download_filename(rom))
