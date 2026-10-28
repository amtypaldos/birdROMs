import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from apps.roms.cover_art import parse_cover_art_settings

from .auth_config import parse_allow_local_login, parse_auth_methods, parse_oidc_settings
from .deploy_config import check_secret_key, parse_csv, parse_debug, parse_num_proxies, parse_proxy_settings
from .huey_config import build_huey
from .library_config import parse_library_settings
from .storage import build_storages
from .uploads import parse_max_upload_bytes

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-dev-secret-key")
# Fails closed: debug is off unless DJANGO_DEBUG=True (set in the .env copied from .env.example).
DEBUG = parse_debug(os.environ)
ALLOWED_HOSTS = parse_csv(os.environ, "DJANGO_ALLOWED_HOSTS") or ["localhost"]

# Reverse-proxy / HTTPS settings (CSRF_TRUSTED_ORIGINS, SECURE_PROXY_SSL_HEADER, secure
# cookies); see birdroms/deploy_config.py and .env.example.
_proxy = parse_proxy_settings(os.environ)
CSRF_TRUSTED_ORIGINS = _proxy["CSRF_TRUSTED_ORIGINS"]
SECURE_PROXY_SSL_HEADER = _proxy["SECURE_PROXY_SSL_HEADER"]
SESSION_COOKIE_SECURE = _proxy["SESSION_COOKIE_SECURE"]
CSRF_COOKIE_SECURE = _proxy["CSRF_COOKIE_SECURE"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "huey.contrib.djhuey",
    "apps.accounts",
    "apps.roms",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves collected static files (Django admin) in production; ROM media is never static.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "birdroms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "birdroms.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "birdroms"),
        "USER": os.getenv("POSTGRES_USER", "birdroms"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "birdroms"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# `collectstatic` target, served by WhiteNoise. The Docker image sets /app/staticfiles.
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))

# The handheld app package users download (publish with `manage.py publish_handheld`).
HANDHELD_APP_PATH = Path(os.getenv("HANDHELD_APP_PATH", MEDIA_ROOT / "handheld" / "birdROMs.muxapp"))

# Default file storage for ROMs and cover art; see birdroms/storage.py and .env.example.
STORAGES = build_storages(os.environ)

# In-place ROM library (folder or S3); see birdroms/library_config.py and apps/roms/library.py.
LIBRARY = parse_library_settings(os.environ)

# Largest accepted ROM upload, in bytes (default 2 GiB); see birdroms/uploads.py.
MAX_ROM_UPLOAD_BYTES = parse_max_upload_bytes(os.environ)

# Cover-art providers (in order), request timeout and ScreenScraper credentials;
# see apps/roms/cover_art.py and .env.example.
COVER_ART = parse_cover_art_settings(os.environ)

# Background-task queue: runs tasks inline under DEBUG / HUEY_IMMEDIATE=true, else on Redis
# (REDIS_URL) via `manage.py run_huey`; see birdroms/huey_config.py and .env.example.
HUEY = build_huey(os.environ, DEBUG)

# Enabled login methods (`local`, `oidc`); see birdroms/auth_config.py and .env.example.
AUTH_METHODS = parse_auth_methods(os.environ)
# Local username/password login is always on when this is true (defaults to DEBUG).
ALLOW_LOCAL_LOGIN = parse_allow_local_login(os.environ, DEBUG)
# Single OIDC/SSO provider (Pocket ID, Authentik, Keycloak, Authelia, Google, ...).
OIDC = parse_oidc_settings(os.environ, AUTH_METHODS)

# `manage.py test` runs on the same PostgreSQL config as above (Django creates a
# `test_<POSTGRES_DB>` database) and uses a throwaway media dir so it never writes
# into the real MEDIA_ROOT.
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
if TESTING:
    MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="birdroms-test-media-"))
    STORAGES = build_storages({})
    atexit.register(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)
    _library_root = tempfile.mkdtemp(prefix="birdroms-test-library-")
    LIBRARY = parse_library_settings({"LIBRARY_ROOT": _library_root})
    atexit.register(shutil.rmtree, _library_root, ignore_errors=True)
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    AUTH_METHODS = parse_auth_methods({})
    ALLOW_LOCAL_LOGIN = False
    OIDC = parse_oidc_settings({}, AUTH_METHODS)
    # No live provider calls from tests; scraping tests opt in with mocked HTTP.
    COVER_ART = parse_cover_art_settings({"COVER_ART_PROVIDERS": ""})
    # Tasks run inline; tests never need Redis or a worker.
    HUEY = build_huey({"HUEY_IMMEDIATE": "true"}, DEBUG)

if not TESTING:
    check_secret_key(SECRET_KEY, DEBUG)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_THROTTLE_RATES = {"login": "10/min", "register": "10/hour", "pair_start": "10/min", "pair_code": "120/min"}
if TESTING:
    # Effectively unlimited so unrelated tests never trip a throttle; throttle tests patch the rates.
    LOGIN_THROTTLE_RATES = {key: "100000/min" for key in LOGIN_THROTTLE_RATES}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "apps.accounts.authentication.DeviceTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Scopes used by the throttles in apps/accounts/throttles.py (login is keyed per username,
    # register per client address).
    "DEFAULT_THROTTLE_RATES": LOGIN_THROTTLE_RATES,
    # Reverse proxies in front of Django, so `X-Forwarded-For` can't be spoofed to dodge the
    # register throttle; see parse_num_proxies and .env.example.
    "NUM_PROXIES": parse_num_proxies(os.environ),
}
