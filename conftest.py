"""pytest fixtures shared by the suite (pytest-django). Factories: gnu_jango/testing/factories.py.

Django ``TestCase`` classes keep working as they are; these fixtures are for function-style tests::

    def test_member_sees_own_orders(member_client, member):
        ShopOrderFactory(user=member)
        assert member_client.get("/api/v1/shop/orders").json()["meta"]["total"] == 1
"""

import pytest
from rest_framework.test import APIClient

from gnu_jango.testing.factories import AdminFactory, MemberFactory


@pytest.fixture(autouse=True)
def _isolated_cache(request):
    """Clear the cache around each function-style test; TestCase classes manage their own."""
    if request.instance is not None:
        yield
        return
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _finish_streamed_responses(monkeypatch):
    """Read to the end the streamed responses a test left unread.

    The test client closes a streamed response, and the file behind a FileResponse, only once its
    body has been read; calling close() directly would also close the test's database connection.
    """
    from django.test import Client

    responses = []
    send = Client.request

    def request(self, **kwargs):
        response = send(self, **kwargs)
        responses.append(response)
        return response

    monkeypatch.setattr(Client, "request", request)
    yield
    for response in responses:
        if response.streaming and not response.is_async:
            for _chunk in response.streaming_content:
                pass


@pytest.fixture
def member(db):
    return MemberFactory()


@pytest.fixture
def admin_member(db):
    return AdminFactory()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def member_client(member):
    client = APIClient()
    client.force_authenticate(user=member)
    return client


@pytest.fixture
def admin_client_api(admin_member):
    client = APIClient()
    client.force_authenticate(user=admin_member)
    return client
