from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gnu_jango.shop"
    verbose_name = _("Shop")

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from gnu_jango.api.shop_cart_keep import reset_guest_cart_session_on_login

        # Any session sign-in (Django admin included) drops the long guest cart lifetime.
        user_logged_in.connect(reset_guest_cart_session_on_login, dispatch_uid="shop_reset_guest_cart_session")
