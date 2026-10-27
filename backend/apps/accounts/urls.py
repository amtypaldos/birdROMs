from django.urls import path

from .pairing import PairApproveView, PairPollView, PairStartView
from .views import AuthConfigView, LoginView, MeView, RegisterView, oidc_callback, oidc_login

urlpatterns = [
    path("config/", AuthConfigView.as_view(), name="auth-config"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("me/", MeView.as_view(), name="me"),
    path("oidc/login/", oidc_login, name="oidc-login"),
    path("oidc/callback/", oidc_callback, name="oidc-callback"),
]

# Mounted at /api/devices/ (see birdroms/urls.py).
device_urlpatterns = [
    path("pair/start", PairStartView.as_view(), name="device-pair-start"),
    path("pair/approve", PairApproveView.as_view(), name="device-pair-approve"),
    path("pair/poll", PairPollView.as_view(), name="device-pair-poll"),
]
