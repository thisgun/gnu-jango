"""The plugin's settings: a Django setting if the site defines one, else the environment variable."""

from decouple import config
from django.conf import settings

DEFAULTS = {
    "ATTENDANCE_POINT": 10,  # points for each check-in
    "ATTENDANCE_STREAK_DAYS": 7,  # every Nth day in a row adds the streak bonus (0: never)
    "ATTENDANCE_STREAK_BONUS": 50,
    "ATTENDANCE_MONTHLY_BONUS": 300,  # for attending every day of a month
    "ATTENDANCE_AUTO_CHECK_IN": False,  # check members in when they visit the site
}


def value(name):
    default = DEFAULTS[name]
    if hasattr(settings, name):
        return getattr(settings, name)
    return config(name, default=default, cast=type(default))
