from django.apps import AppConfig


class OrderNotifyConfig(AppConfig):
    name = "gnu_plugins.order_notify"
    label = "order_notify"
    verbose_name = "주문 알림"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import listeners  # noqa: F401 - registers the plugin's hooks
