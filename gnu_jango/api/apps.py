from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'gnu_jango.api'

    def ready(self):
        from .page_bootstrap import register_bootstrap_invalidation

        register_bootstrap_invalidation()
