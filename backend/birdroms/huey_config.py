from django.core.exceptions import ImproperlyConfigured
from huey import Huey, MemoryHuey, RedisHuey, crontab

from .auth_config import _parse_bool

QUEUE_NAME = "birdroms"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_SWEEP_CRONTAB = "0 * * * *"
DEFAULT_SCAN_CRONTAB = "*/15 * * * *"


def build_huey(env, debug: bool) -> Huey:
    """The task queue: immediate (in-process, no broker) in dev, Redis-backed in production.

    Tasks run inline, synchronously, when `DEBUG` is on or `HUEY_IMMEDIATE=true`, so local
    development and tests need neither Redis nor a worker. Otherwise tasks go to the Redis
    server at `REDIS_URL` and are run by `manage.py run_huey`.
    """
    raw = env.get("HUEY_IMMEDIATE", "").strip()
    immediate = _parse_bool("HUEY_IMMEDIATE", raw) if raw else debug
    if immediate:
        return MemoryHuey(QUEUE_NAME, immediate=True)
    return RedisHuey(QUEUE_NAME, url=env.get("REDIS_URL", "").strip() or DEFAULT_REDIS_URL)


def _parse_crontab(env, var, default):
    """A five-field cron expression from env var `var` (or `default`); malformed raises ImproperlyConfigured."""
    raw = env.get(var, "").strip() or default
    fields = raw.split()
    if len(fields) != 5:
        raise ImproperlyConfigured(f"{var} must have five cron fields (minute hour day month weekday), got {raw!r}.")
    minute, hour, day, month, day_of_week = fields
    return crontab(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)


def parse_sweep_crontab(env):
    """Schedule for the cover-art backfill sweep, from `COVER_ART_SWEEP_CRONTAB`; default hourly.

    Raises ImproperlyConfigured on a malformed value so a typo fails at startup, not silently.
    """
    return _parse_crontab(env, "COVER_ART_SWEEP_CRONTAB", DEFAULT_SWEEP_CRONTAB)


def parse_scan_crontab(env):
    """Schedule for the periodic library scan, from `LIBRARY_SCAN_CRONTAB`; default every 15 minutes."""
    return _parse_crontab(env, "LIBRARY_SCAN_CRONTAB", DEFAULT_SCAN_CRONTAB)
