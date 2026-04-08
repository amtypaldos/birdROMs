from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import ROM
from .permissions import IsSuperAdminOrReadOnlyRole
from .serializers import ROMSerializer
from .services import scrape_cover_art


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
