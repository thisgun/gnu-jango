"""Shop admin package.

Split out of the former 2500-line shop/admin.py. Shared imports, helpers,
filters and inlines live in _common; the registered ModelAdmins are grouped
by domain. Importing the submodules here runs their admin registrations.
"""

from . import banners, catalog, orders, coupons, misc, returns  # noqa: F401
