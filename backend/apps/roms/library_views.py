"""Library status and on-demand rescans (super admins only)."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from birdroms.tasks import scan_library_task

from .library import get_library
from .models import LibraryScan
from .permissions import IsSuperAdmin

# A "running" scan older than this is stale (the worker was killed); the scanner's advisory
# lock stays the real guard against concurrent runs.
STALE_SCAN_AFTER = timedelta(hours=6)


def scan_running() -> bool:
    cutoff = timezone.now() - STALE_SCAN_AFTER
    return LibraryScan.objects.filter(state="running", started_at__gte=cutoff).exists()


class LibraryScanSerializer(serializers.ModelSerializer):
    class Meta:
        model = LibraryScan
        fields = [
            "state",
            "started_at",
            "finished_at",
            "added",
            "changed",
            "missing",
            "restored",
            "skipped_multifile",
            "skipped_other",
            "unknown_folders",
            "message",
        ]
        read_only_fields = fields


class ScanRequestSerializer(serializers.Serializer):
    accept_removals = serializers.BooleanField(required=False, default=False)


class LibraryStatusView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        config = settings.LIBRARY
        last = LibraryScan.objects.first()
        return Response(
            {
                "backend": config.backend,
                "writable": get_library().writable,
                "write_covers": config.write_covers,
                "running": scan_running(),
                "last_scan": LibraryScanSerializer(last).data if last else None,
            }
        )


class LibraryScanView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        options = ScanRequestSerializer(data=request.data)
        options.is_valid(raise_exception=True)
        if scan_running():
            return Response({"detail": "A library scan is already running."}, status=status.HTTP_409_CONFLICT)
        scan_library_task(accept_removals=options.validated_data["accept_removals"])
        return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)
