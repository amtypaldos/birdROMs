from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import DeviceToken, hash_device_token


# Lives apart from the views because it is a DRF default authentication class: DRF imports it while
# importing `rest_framework.views`, so a module that imports APIView can't also define it.
class DeviceTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Device <token>`; rejects revoked tokens and disabled users."""

    keyword = b"device"

    def authenticate(self, request):
        parts = authentication.get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid device token header.")
        try:
            raw = parts[1].decode()
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid device token header.")

        device_token = DeviceToken.objects.select_related("user").filter(token_hash=hash_device_token(raw)).first()
        if device_token is None or device_token.revoked or not device_token.user.is_active:
            raise exceptions.AuthenticationFailed("Invalid or revoked device token.")

        DeviceToken.objects.filter(pk=device_token.pk).update(last_used_at=timezone.now())
        return device_token.user, device_token

    def authenticate_header(self, request):
        return "Device"
