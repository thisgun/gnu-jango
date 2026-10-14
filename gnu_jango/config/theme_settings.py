"""Settings a Next.js theme reads at run time.

A static export is built once and served by every Django (local, Vercel), so what differs per
installation cannot be baked into it. The handbook theme needs one value: which board group holds
the manual (cf_docs_group). Django hands it over twice — in the page's runtime config
(window.__G5_NEXTJS25_CONFIG__.themeSettings, for a static export) and in GET /api/v1/settings as
theme_settings (for a server runtime) — in the shape the theme's parser expects.
"""

HANDBOOK_THEME = "handbook"


def theme_settings_for(theme_name, data):
    """The settings object of the active theme, or None when that theme needs none.

    `data` is the site configuration (config.get_all()). `revision` is the theme's "was it ever
    saved" marker: it must be above 0 or the theme ignores the object.
    """
    if theme_name != HANDBOOK_THEME:
        return None
    group = str(data.get("cf_docs_group") or "").strip()
    return {
        "theme": HANDBOOK_THEME,
        "revision": 1,
        "docs": {"group": group, "hints": {}},
        "sidebar": {},
        "site": {},
    }
