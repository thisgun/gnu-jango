from functools import partial
from importlib import import_module
import logging
from warnings import warn
from weakref import WeakKeyDictionary

from django.conf import settings
from django.core.files.storage import storages
from django.utils.functional import Promise, cached_property, LazyObject
from django.utils.module_loading import module_has_submodule
from django.dispatch import receiver


from .utils import index_exists_return
from gnu_jango import defaults
from ..core.request import current_request
from . import signals

logger = logging.getLogger(__name__)

# import django
# from django.utils.functional import LazyObject

# if django.VERSION < (3, 2):  # pragma: no cover
#     default_app_config = 'django.apps.GnuJangoConfig'

# class LazyConfig(LazyObject):
#     def _setup(self):
#         from .models import Config
#         self._wrapped = Config()

# config = LazyConfig()


class Config:
    def __init__(self):
        # super().__init__()
        self.rows = {}

    # These functions map setting types to the functions that should be
    # used to convert them from the Unicode string stored in the database.
    # If a type doesn't appear in this map, the type itself will be used.
    TYPE_FUNCTIONS = {
        bool: lambda val: str(val).strip().lower() not in {"", "0", "false", "no", "off"},
        bytes: partial(bytes, encoding="utf8"),
    }

    def clear(self):
        self.rows = {}

    def get_all(self):

        if self.rows:
            return self.rows

        from .models import Config

        tmp = {}

        for name, vars in defaults.CONFIGS.items():
            self.rows[name] = vars[0]

        try:
            for config_obj in Config.objects.all()[:200]:

                current_config = defaults.CONFIGS.get(config_obj.name) or None

                if current_config != None:
                    # 데이터베이스 Config 테이블의 value 값인 string 문자열을 defaults.CONFIGS 의 type 에 맞게 형변환 합니다.
                    config_value = self._to_python(current_config, config_obj.value)

                    tmp[config_obj.name] = config_value

        except Exception:
            logger.warning("Failed to load site configuration from database.", exc_info=True)

        self.rows.update(tmp)

        return self.rows

    def get_conf_all(self):

        tmp = {}
        tmps = self.get_all()

        for name, vars in defaults.CONFIGS.items():

            # dicts = index_exists_return(vars, 4) or {}
            # choices = dicts["choices"] if "choices" in dicts else None
            # group = dicts["group"] if "group" in dicts else None

            tmp[name] = {
                "name": name,
                "value": index_exists_return(tmps, name, vars[0]),
                "type": vars[1],
                "label": index_exists_return(vars, 2),
                "description": index_exists_return(vars, 3),
                "choices": index_exists_return(vars, 4),
            }

        return tmp

    @classmethod
    def _to_python(cls, config, raw_value):
        if config is None:
            return raw_value

        fallback = None
        if isinstance(config, tuple):
            casting_str = config[1] if len(config) > 1 else str
            fallback = config[0] if config else None
        elif isinstance(config, dict):
            casting_str = config.get("type")
            fallback = config.get("default", config.get("value"))
        else:
            return None

        casting_type = {
            "float": float,
            "int": int,
            "chr": chr,
            "bool": bool,
            "str": str,
        }.get(casting_str, casting_str if isinstance(casting_str, type) else str)
        type_fn = cls.TYPE_FUNCTIONS.get(casting_type, casting_type)

        try:
            return type_fn(raw_value)
        except (TypeError, ValueError, OverflowError):
            warn("A site configuration value could not be converted; using its default.")
            return fallback

    def __getattr__(self, name):

        # If this setting isn't registered, defer to Django's settings object
        try:
            config_row = self.get_all()
        except KeyError:
            return getattr(settings, name, None)

        return getattr(settings, name, config_row.get(name, None))

    # def __setattr__(self, key, value):
    #     """Forward attribute setting to the Django settings object."""
    #     setattr(django_settings, key, value)

    # def __delattr__(self, item):
    #     """Forward attribute deletion to the Django settings object."""
    #     delattr(django_settings, item)


class SiteConfig(LazyObject):
    def _setup(self):
        self._wrapped = Config()


class Configs(LazyObject):
    def _setup(self):
        self._wrapped = storages["staticfiles"]

    class Placeholder:
        """A Weakly-referable wrapper of ``object``."""

        pass

    NULL_REQUEST = Placeholder()

    # These functions map setting types to the functions that should be
    # used to convert them from the Unicode string stored in the database.
    # If a type doesn't appear in this map, the type itself will be used.
    TYPE_FUNCTIONS = {
        bool: lambda val: str(val).strip().lower() not in {"", "0", "false", "no", "off"},
        bytes: partial(bytes, encoding="utf8"),
    }

    rows = {}

    def get_all(self):

        if self.rows:
            return self.rows

        from .models import Config

        # all = Config.objects.all().__dict__

        tmp = {}

        # Configs.rows = defaults.CONFIGS

        for name, vars in defaults.CONFIGS.items():
            self.rows[name] = vars[0]

        # for config_obj in Config.objects.all()[:200]:

        #     current_config = defaults.CONFIGS.get(config_obj.name) or None

        #     if current_config != None:

        #         # # 데이터베이스 Config 테이블의 value 값인 string 문자열을 defaults.CONFIGS 의 type 에 맞게 형변환 합니다.
        #         config_value = self._to_python(current_config, config_obj.value)

        #         tmp[config_obj.name] = config_value

        try:
            for config_obj in Config.objects.all()[:200]:

                # current_config = getattr(defaults.CONFIGS, config_obj.name, None)

                current_config = defaults.CONFIGS.get(config_obj.name) or None

                if current_config != None:
                    # 데이터베이스 Config 테이블의 value 값인 string 문자열을 defaults.CONFIGS 의 type 에 맞게 형변환 합니다.
                    config_value = self._to_python(current_config, config_obj.value)

                    tmp[config_obj.name] = config_value
                    # try:
                    #     tmp[config_obj.name] = config_obj.value
                    # except KeyError:
                    #     continue

        except Exception:
            logger.warning("Failed to load editable configuration from database.", exc_info=True)

            # Convert a string from the database to the correct Python type.
            # row_value = self._to_python(row, config_obj.value)

            # If nothing went wrong, use the value from the database!

        # https://stackoverflow.com/questions/21925671/convert-django-model-object-to-dict-with-all-of-the-fields-intact
        # print( alls.update(Config.objects.all().items()) )

        # print( Config.objects.exclude(pk=instance.pk).all().values() )
        self.rows.update(tmp)

        return self.rows

    def get_conf_all(self):

        tmp = {}
        tmps = self.get_all()

        # print(defaults.CONFIGS)
        for name, vars in defaults.CONFIGS.items():
            # tmp[name] = {'name': name, 'value': utils.index_exists_return(tmps, name, vars[0]), 'type': vars[1], 'label': utils.index_exists_return(vars, 2), 'description': utils.index_exists_return(vars, 3), 'choices': utils.index_exists_return(vars, 4)}
            tmp[name] = {
                "name": name,
                "value": index_exists_return(tmps, name, vars[0]),
                "type": vars[1],
                "label": index_exists_return(vars, 2),
                "description": index_exists_return(vars, 3),
                "choices": None,
            }

            # Convert a string from the database to the correct Python type.
            # row_value = self._to_python(row, config_obj.value)

            # If nothing went wrong, use the value from the database!

        # https://stackoverflow.com/questions/21925671/convert-django-model-object-to-dict-with-all-of-the-fields-intact
        # print( alls.update(Config.objects.all().items()) )

        # print( Config.objects.exclude(pk=instance.pk).all().values() )
        # Configs.rows.update(tmp)
        return tmp

    @property
    def _current_request(self):
        return current_request() or self.NULL_REQUEST

    def clear_cache(self):
        """Clear the settings cache for the current request."""
        if hasattr(self, "_editable_caches"):
            self._editable_caches.pop(self._current_request, None)

    def _get_editable(self, request):
        """
        Get the dictionary of editable settings for a given request. Settings
        are fetched from the database once per request and then stored in
        ``_editable_caches``, a WeakKeyDictionary that will automatically
        discard each entry when no more references to the request exist.
        """
        if not hasattr(self, "_editable_caches"):
            # The ``_editable_caches`` attribute maps Request objects to dicts of
            # editable settings loaded from the database. We cache settings per-request
            # to ensure that the database is hit at most once per request, and that each
            # request sees the same settings for its duration.
            self._editable_caches = WeakKeyDictionary()
        try:
            editable_settings = self._editable_caches[request]
        except KeyError:
            editable_settings = self._load()
            if request is not self.NULL_REQUEST:
                self._editable_caches[request] = editable_settings
        return editable_settings

    @classmethod
    def _to_python(cls, config, raw_value):
        """
        Convert a value stored in the database for a particular config
        to its correct type, as determined by ``register_setting()``.
        """

        if config == None:
            return raw_value

        if type(config) is tuple:
            casting_str = config[1]
        elif type(config) is dict:
            casting_str = config.get("type")
        else:
            return None

        casting_type = str

        if casting_str == "float":
            casting_type = float
        elif casting_str == "int":
            casting_type = int
        elif casting_str == "chr":
            casting_type = chr
        elif casting_str == "bool":
            casting_type = bool

        # if casting_str not in ['float', 'int', 'str', 'chr', 'bool']:
        #     casting_str = 'str'

        type_fn = cls.TYPE_FUNCTIONS.get(casting_type, casting_type)

        try:
            value = type_fn(raw_value)
        except ValueError:
            # Shouldn't occur, but just a safeguard in case
            # the db value somehow ended up as an invalid type.
            warn(
                "The config %s should be of type %s, but the value "
                "retrieved from the database (%s) could not be converted. "
                "Using the default instead: %s"
                % (
                    config["name"],
                    config["type"].__name__,
                    repr(raw_value),
                    repr(config["value"]),
                )
            )
            value = config["value"]

        return value

    def _load(self):

        return Configs.get_all(self)
        """
        Load editable settings from the database and return them as a dict.
        Delete any settings from the database that are no longer registered,
        and emit a warning if there are settings that are defined in both
        settings.py and the database.
        """
        from .models import Config

        removed_settings = []
        new_cache = {}

        for config_obj in Config.objects.all():

            # Check that the Setting object corresponds to a setting that has
            # been declared in code using ``register_setting()``. If not, add
            # it to a list of items to be deleted from the database later.
            try:
                config_row = defaults[config_obj.name]
            except KeyError:
                removed_settings.append(config_obj.name)
                continue

            # Convert a string from the database to the correct Python type.
            config_value = self._to_python(config_row, config_obj.value)

            # If nothing went wrong, use the value from the database!
            new_cache[config_row["name"]] = config_value

        # if removed_settings:
        #    Setting.objects.filter(name__in=removed_settings).delete()

        # 값이 아예 비어있으면 defaults.CONFIGS 값과 merge
        # if not new_cache:
        #    new_cache = new_cache.update(defaults.CONFIGS)

        return new_cache

    def __getattr__(self, name):

        # If this setting isn't registered, defer to Django's settings object
        try:
            config_row = Configs.get_all(self)[name]
        except KeyError:
            return getattr(settings, name)

        editable_cache = self._get_editable(request=self._current_request)

        return getattr(settings, name, editable_cache.get(name, config_row))


# mezz_first = lambda app: not app.startswith("gnu_jango.")
# for app in sorted(settings.INSTALLED_APPS, key=mezz_first):
#     try:
#         module = import_module(app)
#     except ImportError:
#         pass
#     else:
#         try:
#             import_module("%s.defaults" % app)
#         except:  # noqa
#             if module_has_submodule(module, "defaults"):
#                 raise

# config = Configs()
config = SiteConfig()

# signal 을 받아서 config 값을 초기화 합니다.
@receiver(signals.config_done)
def config_created_or_update(sender, **kwargs):
    config.clear()
