"""Background-task API for the rest of the app.

Import `task`, `periodic_task` and `huey` from here, never from `huey` directly, so the queue
implementation stays swappable in one place. The instance is configured by `settings.HUEY`
(see `birdroms/huey_config.py`).
"""

from huey.contrib.djhuey import HUEY as huey
from huey.contrib.djhuey import periodic_task, task

__all__ = ["huey", "periodic_task", "task"]
