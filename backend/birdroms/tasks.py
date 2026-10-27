"""Background-task API for the rest of the app.

Import `task`, `periodic_task` and `huey` from here, never from `huey` directly, so the queue
implementation stays swappable in one place. The instance is configured by `settings.HUEY`
(see `birdroms/huey_config.py`). The app's own tasks are defined here too.
"""

from huey.contrib.djhuey import HUEY as huey
from huey.contrib.djhuey import periodic_task, task

from apps.roms.cover_art import safe_fetch_cover_for_rom
from apps.roms.models import ROM

__all__ = ["huey", "periodic_task", "scrape_rom_cover", "task"]


@task()
def scrape_rom_cover(rom_id: int) -> bool:
    """Scrape and store cover art for a ROM; returns whether anything changed.

    A missing ROM (deleted before the worker got to it) is a no-op. Provider errors are logged
    by `safe_fetch_cover_for_rom` and never raised, so a bad scrape cannot crash the worker.
    """
    rom = ROM.objects.filter(pk=rom_id).first()
    if rom is None:
        return False
    return safe_fetch_cover_for_rom(rom)
