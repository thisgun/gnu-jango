"""OpenAPI response contracts for the v1 API.

The v1 views build plain dicts and wrap them with ``api_response``; DRF serializers are not used to
render them. The serializers in this package only *describe* those dicts for drf-spectacular, so
the generated schema (``openapi/schema.json``) and the TypeScript types made from it
(``nextjs/src/types/api.gen.ts``) carry real response shapes.

A description can drift from the dict a view really returns, so every view annotated here also
has a contract test (``gnu_jango/core/contract_testing.py``) that calls it and validates the JSON
against the generated schema, with undeclared keys rejected.

Usage::

    @extend_schema(responses=envelope("SiteSettings", SiteSettingsSerializer()))
    @api_view(["GET"])
    def settings_view(request): ...
"""

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


class FreeformObjectField(serializers.DictField):
    """An object whose keys are not fixed (theme settings, error maps)."""


def envelope(name, data, *, meta=None):
    """The ``api_response`` wrapper around ``data`` as a named schema component."""
    return inline_serializer(
        name=f"{name}Envelope",
        fields={
            "success": serializers.BooleanField(),
            "ok": serializers.BooleanField(),
            "data": data,
            "message": serializers.CharField(allow_blank=True),
            "meta": meta if meta is not None else FreeformObjectField(),
            "errors": FreeformObjectField(),
        },
    )


def _page_meta_fields():
    # "from" is a Python keyword, so the fields are collected in a dict.
    return {
        "total": serializers.IntegerField(),
        "current_page": serializers.IntegerField(),
        "per_page": serializers.IntegerField(),
        "last_page": serializers.IntegerField(),
        "from": serializers.IntegerField(allow_null=True),
        "to": serializers.IntegerField(allow_null=True),
    }


PageMetaSerializer = type("PageMetaSerializer", (serializers.Serializer,), _page_meta_fields())
PageMetaSerializer.__doc__ = "Numbered-page metadata of the list endpoints (shop_common / v1_board)."
