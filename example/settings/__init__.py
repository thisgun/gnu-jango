from .base import *
import os

# if os.environ.get("ENVIRONMENT") == 'Production':
#     from .production import *
# else:
#     from .development import *

# https://stackoverflow.com/questions/9383450/how-can-i-detect-herokus-environment
# herokus 에 배포한 경우

# if 'YOUR_ENV_VAR' in os.environ:
#     print('bb')

if os.environ.get("ENVIRONMENT") == 'Production':
    from .production import *
elif os.environ.get("ENVIRONMENT") == 'Preview':
    from .preview import *
else:
    from .development import *
