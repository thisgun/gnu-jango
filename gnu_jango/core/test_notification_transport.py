"""Real HTTP + WebSocket transport against an explicitly configured disposable Redis.

Set NOTIFICATION_TEST_REDIS_URL=redis://127.0.0.1:6399/2 to opt in. Each class owns its
Redis key prefix; this module never flushes Redis or stops containers.
"""

import importlib
import json
import os
import socket
import threading
import time
import unittest
import uuid
from datetime import timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from gnu_jango.core.models import Notification, NotificationWork
from gnu_jango.notifications.delivery import invalidate_on_commit
from gnu_jango.notifications.outbox import process_pending

REDIS_URL = os.environ.get("NOTIFICATION_TEST_REDIS_URL", "")


@unittest.skipUnless(REDIS_URL == "redis://127.0.0.1:6399/2", "Requires disposable notification test Redis on 6399")
class LiveNotificationTransportTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import uvicorn

        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.listener.listen(128)
        port = cls.listener.getsockname()[1]
        cls.origin = f"http://127.0.0.1:{port}"
        cls.ws_url = f"ws://127.0.0.1:{port}/ws/notifications/"
        prefix = f"notification-test-{uuid.uuid4().hex}"
        cls.layer = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {
            "hosts": [{"address": REDIS_URL, "socket_connect_timeout": 0.2, "socket_timeout": 10}],
            "prefix": prefix,
        }}}
        cls.settings_override = override_settings(
            DEBUG=True, ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"],
            NOTIFICATION_WS_ENABLED=True, NOTIFICATION_REDIS_URL=REDIS_URL,
            NOTIFICATION_WS_ORIGINS=[cls.origin], NOTIFICATION_WS_URL=cls.ws_url,
            CHANNEL_LAYERS=cls.layer, CACHES={
                "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": prefix},
                "notifications": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL, "KEY_PREFIX": prefix},
            },
        )
        cls.settings_override.enable()
        import example.asgi

        cls.server = uvicorn.Server(uvicorn.Config(
            importlib.reload(example.asgi).application, log_level="error", lifespan="off", ws_max_size=1024,
        ))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.server.started:
            raise RuntimeError("Notification ASGI server did not start")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.should_exit = True
            cls.thread.join(10)
            cls.listener.close()
        finally:
            cls.settings_override.disable()
            super().tearDownClass()

    def setUp(self):
        self.alice = get_user_model().objects.create_user(username="live-alice")
        self.bob = get_user_model().objects.create_user(username="live-bob")
        self.token = AccessToken.for_user(self.alice)

    def ticket(self, token=None):
        request = Request(f"{self.origin}/api/v1/notifications/ticket", data=b"{}", headers={
            "Authorization": f"Bearer {token or self.token}", "Content-Type": "application/json",
        })
        with urlopen(request, timeout=5) as response:
            self.assertIn("no-store", response.headers["Cache-Control"])
            return json.load(response)["data"]["ticket"]

    def connect(self, ticket=None):
        from websockets.sync.client import connect

        ws = connect(self.ws_url, origin=self.origin, open_timeout=5)
        ws.send(json.dumps({"type": "authenticate", "ticket": ticket or self.ticket()}))
        self.assertEqual(json.loads(ws.recv(timeout=5))["type"], "ready")
        self.addCleanup(ws.close)
        return ws

    def changed(self, ws):
        while True:
            message = json.loads(ws.recv(timeout=5))
            if message["type"] == "ping":
                ws.send('{"type":"pong"}')
            else:
                self.assertEqual(message["type"], "notifications.changed")
                self.assertNotIn("nt_body", message)
                return

    def test_real_network_delivery_is_private(self):
        alice_ws = self.connect()
        bob_ws = self.connect(self.ticket(AccessToken.for_user(self.bob)))
        Notification.objects.create(user=self.alice, nt_title="Private", nt_body="must stay in REST")
        self.assertEqual(process_pending()["completed"], 1)
        self.changed(alice_ws)
        with self.assertRaises(TimeoutError):
            bob_ws.recv(timeout=0.3)

    def test_ticket_is_consumed_once(self):
        from websockets.sync.client import connect
        from websockets.exceptions import ConnectionClosed

        ticket = self.ticket()
        self.connect(ticket)
        with connect(self.ws_url, origin=self.origin) as other:
            other.send(json.dumps({"type": "authenticate", "ticket": ticket}))
            with self.assertRaises(ConnectionClosed):
                other.recv(timeout=3)

    def test_forged_ticket_is_rejected(self):
        from websockets.sync.client import connect
        from websockets.exceptions import ConnectionClosed

        with connect(self.ws_url, origin=self.origin) as ws:
            ws.send(json.dumps({"type": "authenticate", "ticket": "x" * 43}))
            with self.assertRaises(ConnectionClosed):
                ws.recv(timeout=3)

    def test_expired_ticket_is_rejected(self):
        from django.core.cache import caches
        from websockets.sync.client import connect
        from websockets.exceptions import ConnectionClosed

        ticket = self.ticket()
        caches["notifications"].delete(f"ticket.{ticket}")
        with connect(self.ws_url, origin=self.origin) as ws:
            ws.send(json.dumps({"type": "authenticate", "ticket": ticket}))
            with self.assertRaises(ConnectionClosed):
                ws.recv(timeout=3)

    def test_untrusted_origin_is_rejected(self):
        from websockets.sync.client import connect
        from websockets.exceptions import InvalidStatus

        with self.assertRaises(InvalidStatus):
            connect(self.ws_url, origin="https://evil.test", open_timeout=3)

    def test_anonymous_ticket_request_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(f"{self.origin}/api/v1/notifications/ticket", data=b"{}"), timeout=5)
        self.assertEqual(caught.exception.code, 401)

    def test_revoked_account_version_closes_connection(self):
        from gnu_jango.users.models import Profile
        from websockets.exceptions import ConnectionClosed

        ws = self.connect()
        profile, _ = Profile.objects.get_or_create(user=self.alice)
        profile.token_version += 1
        profile.save(update_fields=["token_version"])
        invalidate_on_commit(self.alice.pk)
        process_pending()
        with self.assertRaises(ConnectionClosed):
            ws.recv(timeout=5)

    def test_redis_unavailable_does_not_prevent_inbox_and_pending_work_recovers(self):
        ws = self.connect()
        # A bound, non-listening socket provides a local refused endpoint without touching Redis.
        with socket.socket() as refused:
            refused.bind(("127.0.0.1", 0))
            port = refused.getsockname()[1]
            broken = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {
                "hosts": [{"address": f"redis://127.0.0.1:{port}/2", "socket_connect_timeout": 0.1, "socket_timeout": 0.1}],
            }}}
            with override_settings(CHANNEL_LAYERS=broken):
                note = Notification.objects.create(user=self.alice, nt_title="Survives outage")
                self.assertTrue(Notification.objects.filter(pk=note.pk).exists())
                self.assertEqual(process_pending()["failed"], 1)
        NotificationWork.objects.filter(completed_at__isnull=True).update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(process_pending()["completed"], 1)
        self.changed(ws)

    def test_reconnect_receives_new_changes(self):
        ws = self.connect()
        ws.close()
        replacement = self.connect()
        Notification.objects.create(user=self.alice, nt_title="After reconnect")
        process_pending()
        self.changed(replacement)

    def test_idle_connection_survives_blocking_redis_read(self):
        ws = self.connect()
        time.sleep(6)
        Notification.objects.create(user=self.alice, nt_title="After idle")
        process_pending()
        self.changed(ws)
