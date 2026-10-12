"""Static file storage for production.

WhiteNoise's manifest storage rewrites every url(...) / sourceMappingURL in CSS and JS to the hashed
file name and refuses to collect when a referenced file is missing. The legacy Gnuboard5 skins shipped
with this project reference files that were never included (source maps such as bootstrap.min.js.map)
and absolute paths such as /img/captcha2.png. Those references are left exactly as written - the
browser resolves them as before - instead of failing the whole collectstatic run.
"""

import logging

from django.core.exceptions import SuspiciousFileOperation
from whitenoise.storage import CompressedManifestStaticFilesStorage

logger = logging.getLogger(__name__)


class LegacyTolerantManifestStorage(CompressedManifestStaticFilesStorage):
    # a {% static %} lookup of a file missing from the manifest falls back to the plain name
    manifest_strict = False

    def url_converter(self, name, hashed_files, template=None, ignored_blocks=None):
        convert = super().url_converter(name, hashed_files, template, ignored_blocks)

        def converter(matchobj):
            try:
                return convert(matchobj)
            except (ValueError, SuspiciousFileOperation) as exc:
                logger.warning("Static reference left unchanged in %s: %s", name, str(exc).splitlines()[0])
                return matchobj.group(0)

        return converter
