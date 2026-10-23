from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
from simple_history.signals import pre_create_historical_record

# https://kgu0724.tistory.com/99
# https://learndjango.com/tutorials/django-slug-tutorial
# https://onsil-thegreenhouse.github.io/programming/django/web_programmig/2017/10/14/django_tutorial2_ch1-2/

# Create your models here.

# Names that must never be copied into the history table. The settings form masks some of
# them (Configforms.SECRET_CONFIG_FIELDS), but the database also receives them from the shop
# PG screen and the theme screen, so the check lives here rather than in one form.
SECRET_CONFIG_NAMES = {
    "cf_cert_kg_mid",
    "cf_cert_kg_cd",
    "cf_twitter_key",
    "cf_kakao_rest_key",
}
SECRET_CONFIG_NAME_PARTS = (
    "secret",
    "password",
    "passwd",
    "private_key",
    "api_key",
    "access_key",
    "token",
)
REDACTED_CONFIG_VALUE = "********"

# Only real site settings are audited. Config also holds short-lived rows such as the guest
# cart (auth_cart_*), social identity links and sample-data manifests; copying those into a
# second table on every cart update would bloat the database without answering an audit
# question. All real settings use one of these prefixes.
TRACKED_CONFIG_PREFIXES = ("cf_", "de_", "shop_", "pg_")


def is_tracked_config_name(name):
    return str(name or "").startswith(TRACKED_CONFIG_PREFIXES)


class ConfigHistoryRecords(HistoricalRecords):
    """HistoricalRecords that ignores Config rows which are not site settings."""

    def create_historical_record(self, instance, history_type, using=None):
        if not is_tracked_config_name(instance.name):
            return
        return super().create_historical_record(instance, history_type, using=using)


def is_secret_config_name(name):
    """True for settings whose value is a credential (and therefore redacted in history)."""

    lowered = str(name or "").lower()
    return lowered in SECRET_CONFIG_NAMES or any(part in lowered for part in SECRET_CONFIG_NAME_PARTS)


class Config(models.Model):
    """
    Stores values for ``gnu_jango.conf`` that can be edited via the admin.
    """
    name = models.CharField(max_length=50, unique=True, db_index=True)
    value = models.TextField()

    # Admin settings changes are part of the audit trail. Historical values for credentials are
    # replaced by REDACTED_CONFIG_VALUE in the pre_create_historical_record receiver below.
    history = ConfigHistoryRecords()

    class Meta:
        # Django names tables `<app_label>_<model>`, and this app's label is
        # "config", so the default was the stuttering `config_config`. Only the
        # physical table is renamed here: app_label stays "config", so admin URL
        # names such as `admin:config_config_changelist` are unaffected.
        db_table = "gnu_jango_config"
        verbose_name = _("기본설정")
        verbose_name_plural = _("기본환경설정")

    def __str__(self):
        # The value may be a credential; the name alone is what logs and history titles need.
        return self.name


@receiver(pre_create_historical_record, dispatch_uid="config_redact_secret_history")
def redact_secret_config_history(sender, instance, history_instance, **kwargs):
    """Never store a credential in the Config history table.

    Reverting a redacted row is disabled by the admin (see config/admin.py), so the mask can
    never overwrite the live setting.
    """

    if not isinstance(instance, Config):
        return
    if is_secret_config_name(history_instance.name):
        history_instance.value = REDACTED_CONFIG_VALUE
        history_instance.history_change_reason = "credential value redacted"


@receiver(post_save, sender=Config, dispatch_uid="config_clear_cache_after_save")
def clear_config_cache_after_save(sender, instance, **kwargs):
    """A settings save (including a history revert) must be visible on the next request."""

    if not is_tracked_config_name(instance.name):
        return
    from . import config

    config.clear()


@receiver(post_delete, sender=Config, dispatch_uid="config_clear_cache_after_delete")
def clear_config_cache_after_delete(sender, instance, **kwargs):
    if not is_tracked_config_name(instance.name):
        return
    from . import config

    config.clear()
