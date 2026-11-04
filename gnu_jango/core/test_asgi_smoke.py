"""Every API GET without path parameters answers under ASGI, the way Vercel serves Django.

The sync test Client goes through WSGI, so code that touches the database in the event loop (URL
resolving, async views or middleware) passes the rest of the suite and fails only on Vercel with
SynchronousOnlyOperation (the plugin API 500 fixed in #140). AsyncClient goes through the ASGI
handler and re-raises such an error here. The paths come from the API contract, so new endpoints are
checked without editing this file; plugin URLs are not in the contract (test_plugin_admin.py).
"""

import json
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient

pytestmark = pytest.mark.django_db

SCHEMA = Path(__file__).resolve().parents[2] / "openapi" / "schema.json"


def _get_paths():
    paths = json.loads(SCHEMA.read_text(encoding="utf-8"))["paths"]
    return sorted(path for path, operations in paths.items() if "get" in operations and "{" not in path)


GET_PATHS = _get_paths()


def _get(client, path):
    return async_to_sync(client.get)(path)


def test_the_contract_lists_get_paths_to_check():
    assert "/api/v1/status" in GET_PATHS
    assert len(GET_PATHS) > 50


@pytest.mark.parametrize("path", GET_PATHS)
def test_an_anonymous_get_answers_under_asgi(path):
    response = _get(AsyncClient(), path)

    assert response.status_code < 500, (path, response.status_code)


@pytest.mark.parametrize("path", GET_PATHS)
def test_a_signed_in_member_s_get_answers_under_asgi(path, member):
    client = AsyncClient()
    async_to_sync(client.aforce_login)(member)

    response = _get(client, path)

    assert response.status_code < 500, (path, response.status_code)
