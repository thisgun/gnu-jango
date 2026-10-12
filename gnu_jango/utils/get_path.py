import datetime
import os
import re
from django.contrib.staticfiles.finders import find
from django.templatetags.static import static

from gnu_jango import defaults

def static_url_version(path, is_filetime=False):
    """
    Wrapper for Django's static file finder to append a cache-busting query parameter
    """
    # An absolute path is returned unchanged (either a full URL, or processed already)
    if path.startswith(("http://", "https://", "/")):
        return path
    
    full_path = find(path)
    url = static(path)

    if not full_path:
        return url
    
    str_version = defaults.__STATIC_VERSION__
    
    # cache busting - 파일이 수정된 마지막시간으로
    if is_filetime or defaults.IS_STATIC_URL_FILETIME:
        # file modification timestamp of a file
        m_time = os.path.getmtime(full_path)
        dt_m = datetime.datetime.fromtimestamp(m_time)
        str_version = re.sub(r'[^0-9]', '', str(dt_m))
            
    # if URL already contains a querystring, don't add our own, to avoid interfering
    # with existing mechanisms
    if "?" in url:
        return url
    else:
        return url + '?v=' + str(str_version)