from huey import Huey, MemoryHuey, RedisHuey

from .auth_config import _parse_bool

QUEUE_NAME = "birdroms"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


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
