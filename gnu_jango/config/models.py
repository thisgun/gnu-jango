from django.db import models
from django.utils.translation import gettext_lazy as _

# https://kgu0724.tistory.com/99
# https://learndjango.com/tutorials/django-slug-tutorial
# https://onsil-thegreenhouse.github.io/programming/django/web_programmig/2017/10/14/django_tutorial2_ch1-2/

# Create your models here.

class Config(models.Model):
    """
    Stores values for ``gnu_jango.conf`` that can be edited via the admin.
    """
    name = models.CharField(max_length=50, unique=True, db_index=True)
    value = models.TextField()
    class Meta:
        # Django names tables `<app_label>_<model>`, and this app's label is
        # "config", so the default was the stuttering `config_config`. Only the
        # physical table is renamed here: app_label stays "config", so admin URL
        # names such as `admin:config_config_changelist` are unaffected.
        db_table = "gnu_jango_config"
        verbose_name = _("기본설정")
        verbose_name_plural = _("기본환경설정")
     
    def __str__(self):
        return f"{self.name}: {self.value}"
