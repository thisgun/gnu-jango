import hashlib
import time

from django.core.cache import cache
from django.utils.encoding import smart_bytes

from gnu_jango import defaults

# https://hulk89.github.io/python/2016/08/08/static-var/


def static_vars(**kwargs):
    def decorate(func):
        for k in kwargs:
            setattr(func, k, kwargs[k])
        return func

    return decorate


# @static_vars(str='')
# def gnu_cache_secret_key():

#     if str != '':
#         return str


def get_hexdigest(plaintext, length=None):
    digest = hashlib.sha256(smart_bytes(plaintext)).hexdigest()
    if length:
        return digest[:length]
    return digest


# https://docs.djangoproject.com/en/dev/topics/cache/#the-low-level-cache-api


def gnu_set_cache(key, save_data, ttl=None):

    if ttl == None:
        ttl = defaults.CACHE_TIMEOUT

    expired_time = ttl + time.time()
    packed_val = (save_data, expired_time)
    return cache.set(key, packed_val, ttl)


def gnu_get_cache(key, expired_time=0):

    packed_val = cache.get(key)
    if packed_val is None:
        return None

    data, expired_time = packed_val

    if expired_time and (time.time() > expired_time):
        gnu_set_cache(key, data, defaults.CACHE_TIMEOUT)
        return None

    return data


def gnu_delete_cache(key):
    cache.delete(key)


# prefix 미구현
# https://stackoverflow.com/questions/46421840/django-delete-cache-with-specific-key-prefix

# def gnu_delete_cache_prefix(like_key):

#     try:
#         for key in cache._cache.keys():
#             print(key)
#             if key.startswith(like_key):
#                 del cache._cache[key]

#         # cache.clear(prefix=like_key)

#         # cache.delete_many(keys=cache.keys(like_key + '.*'))
#         # cache.clear(prefix=like_key)
#     except:
#         pass
