"""Env-driven selection of the default file storage (ROMs and cover art).

`STORAGE_BACKEND=filesystem` (default) stores files under `MEDIA_ROOT`, which can be any
local or NFS-mounted path. `STORAGE_BACKEND=s3` uses django-storages' S3 backend, which
works with any S3-compatible service (AWS S3, MinIO, Cloudflare R2, Backblaze B2).
"""

FILESYSTEM_STORAGE = "django.core.files.storage.FileSystemStorage"
S3_STORAGE = "storages.backends.s3.S3Storage"
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
STORAGE_BACKENDS = ("filesystem", "s3")


def _env_bool(value, default=False):
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _s3_options(env):
    options = {
        "bucket_name": env.get("S3_BUCKET_NAME", ""),
        "access_key": env.get("S3_ACCESS_KEY_ID", ""),
        "secret_key": env.get("S3_SECRET_ACCESS_KEY", ""),
        # ROMs are private: never make objects public; serve via signed URLs.
        "default_acl": None,
        "querystring_auth": _env_bool(env.get("S3_QUERYSTRING_AUTH"), default=True),
        "file_overwrite": False,
    }
    optional = {
        "endpoint_url": env.get("S3_ENDPOINT_URL"),
        "region_name": env.get("S3_REGION"),
        "custom_domain": env.get("S3_CUSTOM_DOMAIN"),
        "location": env.get("S3_LOCATION"),
    }
    options.update({key: value for key, value in optional.items() if value})
    if _env_bool(env.get("S3_PATH_STYLE")):
        options["addressing_style"] = "path"
    return options


def build_storages(env):
    """Return a Django `STORAGES` dict for the backend named in `env["STORAGE_BACKEND"]`."""
    backend = (env.get("STORAGE_BACKEND") or "filesystem").strip().lower()
    if backend == "filesystem":
        default = {"BACKEND": FILESYSTEM_STORAGE}
    elif backend == "s3":
        default = {"BACKEND": S3_STORAGE, "OPTIONS": _s3_options(env)}
    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND {backend!r}; expected one of: {', '.join(STORAGE_BACKENDS)}"
        )
    return {
        "default": default,
        "staticfiles": {"BACKEND": STATICFILES_STORAGE},
    }
