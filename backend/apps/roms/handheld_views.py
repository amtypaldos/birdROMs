"""Handheld app info + download for signed-in users (any role, including device tokens)."""

from django.http import FileResponse
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .handheld import handheld_info, handheld_path


class HandheldInfoView(APIView):
    def get(self, request):
        return Response(handheld_info() or {"available": False})


class HandheldDownloadView(APIView):
    def get(self, request):
        path = handheld_path()
        if not path.is_file():
            raise NotFound("The handheld app has not been published yet.")
        return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
