from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.intelligence'
    verbose_name = 'Research Intelligence'

    def ready(self):
        from . import checks  # noqa: F401
