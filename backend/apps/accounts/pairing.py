"""Pairing a handheld to a user: the device shows a code/QR, the owner approves it on their phone.

Flow: the device calls `pair/start`, shows the code and QR, and polls `pair/poll`. The owner opens the QR
URL on their phone (signed in) and the web page calls `pair/approve`, which mints a `DeviceToken`. The next
poll hands the raw token to the device exactly once.

The raw token never appears in a log line or in the approve response (the phone never sees it).
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import authentication, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeviceToken, PairingRequest, generate_pairing_code
from .serializers import UserSerializer
from .services import expire_stale_pairings
from .throttles import PairCodeThrottle, PairStartThrottle

PAIRING_TTL = timedelta(minutes=5)
# Where the web app's approve page lives; it reads `?code=` and calls `pair/approve`.
APPROVE_PAGE_PATH = "/pair"


class ApproveSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)

    def validate_code(self, value):
        return value.strip().upper()


def _normalize_code(value) -> str:
    return str(value or "").strip().upper()


def _create_pairing_request(request):
    """Create a pending request with a fresh unique code."""
    now = timezone.now()
    expire_stale_pairings(now)
    while True:
        code = generate_pairing_code()
        try:
            with transaction.atomic():
                return PairingRequest.objects.create(
                    code=code,
                    qr_payload=request.build_absolute_uri(f"{APPROVE_PAGE_PATH}?{urlencode({'code': code})}"),
                    expires_at=now + PAIRING_TTL,
                )
        except IntegrityError:  # Code collision with an existing row; draw another.
            continue


class PairStartView(APIView):
    """Public: a device asks for a code to show the owner."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PairStartThrottle]

    def post(self, request):
        pairing = _create_pairing_request(request)
        return Response(
            {"code": pairing.code, "qr_url": pairing.qr_payload, "expires_at": pairing.expires_at.isoformat()},
            status=status.HTTP_201_CREATED,
        )


class PairApproveView(APIView):
    """The signed-in owner approves a code, which mints a device token for them.

    Device tokens are deliberately not accepted here: a paired handheld must not be able to mint
    further tokens that would outlive its own revocation.
    """

    authentication_classes = [authentication.SessionAuthentication]
    throttle_classes = [PairCodeThrottle]

    def post(self, request):
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            pairing = PairingRequest.objects.select_for_update().filter(code=serializer.validated_data["code"]).first()
            if pairing is None:
                return Response({"detail": "Unknown pairing code."}, status=status.HTTP_404_NOT_FOUND)
            if pairing.is_expired():
                return Response({"detail": "This pairing code has expired."}, status=status.HTTP_410_GONE)
            if pairing.approved_by_id is not None:
                return Response({"detail": "This pairing code was already approved."}, status=status.HTTP_409_CONFLICT)
            device_token, raw = DeviceToken.mint(request.user)
            pairing.approved_by = request.user
            pairing.device_token = device_token
            pairing.pending_token = raw
            pairing.save(update_fields=["approved_by", "device_token", "pending_token"])
        return Response({"detail": "Device approved."})


class PairPollView(APIView):
    """Public: the device polls with its code until approved, then receives the token once."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PairCodeThrottle]

    def get(self, request):
        code = _normalize_code(request.query_params.get("code"))
        if not code:
            return Response({"detail": "A code is required."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            pairing = PairingRequest.objects.select_for_update().filter(code=code).first()
            if pairing is None:
                return Response({"detail": "Unknown pairing code."}, status=status.HTTP_404_NOT_FOUND)
            if pairing.consumed:
                return Response({"detail": "This pairing code was already used."}, status=status.HTTP_410_GONE)
            if pairing.is_expired():
                # Approved too late to be delivered: kill the token so it can't linger unseen.
                if pairing.device_token_id is not None:
                    DeviceToken.objects.filter(pk=pairing.device_token_id).update(revoked=True)
                if pairing.pending_token:
                    pairing.pending_token = ""
                    pairing.save(update_fields=["pending_token"])
                return Response({"detail": "This pairing code has expired."}, status=status.HTTP_410_GONE)
            if pairing.approved_by_id is None:
                return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)
            raw = pairing.pending_token
            pairing.pending_token = ""
            pairing.consumed = True
            pairing.save(update_fields=["pending_token", "consumed"])
        # A secret in a GET response must never be cached by a browser, proxy or HTTP library.
        return Response(
            {"device_token": raw, "user": UserSerializer(pairing.approved_by).data}, headers={"Cache-Control": "no-store"}
        )
