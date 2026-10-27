from django.core.exceptions import ImproperlyConfigured

DEFAULT_MAX_ROM_UPLOAD_BYTES = 2 * 1024**3  # 2 GiB: generous enough for most disc images.


def parse_max_upload_bytes(env) -> int:
    """Read `MAX_ROM_UPLOAD_BYTES` from `env`, falling back to the 2 GiB default."""
    raw = env.get("MAX_ROM_UPLOAD_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_ROM_UPLOAD_BYTES
    try:
        value = int(raw)
    except ValueError:
        raise ImproperlyConfigured(f"MAX_ROM_UPLOAD_BYTES must be an integer byte count, got {raw!r}.")
    if value <= 0:
        raise ImproperlyConfigured(f"MAX_ROM_UPLOAD_BYTES must be positive, got {value}.")
    return value
