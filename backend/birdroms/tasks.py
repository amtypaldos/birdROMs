"""Background-task API for the rest of the app.

Import `task`, `periodic_task`, `db_task`, `db_periodic_task` and `huey` from here, never from
`huey` directly, so the queue implementation stays swappable in one place. Tasks that touch the
ORM must use the `db_*` variants: they close stale database connections around each run, which
a long-lived `run_huey` worker needs (and which is a no-op in immediate mode). The instance is configured by `settings.HUEY`
(see `birdroms/huey_config.py`). The app's own tasks are defined here too.
"""

import os

from huey.contrib.djhuey import HUEY as huey
from huey.contrib.djhuey import db_periodic_task, db_task, periodic_task, task

from apps.roms.cover_art import safe_fetch_cover_for_rom
from apps.roms.models import ROM

from .huey_config import parse_sweep_crontab

__all__ = [
    "db_periodic_task",
    "db_task",
    "huey",
    "periodic_task",
    "scrape_rom_cover",
    "sweep_missing_cover_art",
    "task",
]


@db_task()
def scrape_rom_cover(rom_id: int) -> bool:
    """Scrape and store cover art for a ROM; returns whether anything changed.

    A missing ROM (deleted before the worker got to it) is a no-op. Provider errors are logged
    by `safe_fetch_cover_for_rom` and never raised, so a bad scrape cannot crash the worker.
    """
    rom = ROM.objects.filter(pk=rom_id).first()
    if rom is None:
        return False
    return safe_fetch_cover_for_rom(rom)


def roms_missing_cover_art():
    """ROMs that still have no cover art."""
    return ROM.objects.filter(cover_art="")


@db_periodic_task(parse_sweep_crontab(os.environ))
def sweep_missing_cover_art() -> int:
    """Enqueue a cover-art scrape for every ROM still missing art; returns how many were queued.

    Runs hourly by default (`COVER_ART_SWEEP_CRONTAB` overrides). The per-ROM scrapes are
    separate tasks, so one slow or failing provider lookup cannot hold up the rest.
    """
    queued = 0
    for rom_id in roms_missing_cover_art().values_list("pk", flat=True):
        scrape_rom_cover(rom_id)
        queued += 1
    return queued
