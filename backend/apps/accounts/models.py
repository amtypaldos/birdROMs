from django.conf import settings
from django.db import models


class OIDCIdentity(models.Model):
    """Links a Django user to the stable `(issuer, sub)` pair of an OIDC provider account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oidc_identity")
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["issuer", "subject"], name="unique_oidc_identity")]

    def __str__(self):
        return f"{self.user} <{self.issuer} {self.subject}>"
