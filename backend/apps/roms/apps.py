from django.apps import AppConfig


class RomsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.roms"

    def ready(self):
        # `run_huey` only autodiscovers `tasks` modules inside installed apps; importing the
        # shared module here registers the app's tasks with the worker.
        from birdroms import tasks  # noqa: F401
