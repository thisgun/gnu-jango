import asyncio
import contextlib
import json
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from redis.exceptions import RedisError

from .delivery import user_group
from .tickets import consume_ticket, identity_is_valid

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Receive-only private inbox hints. HTTP remains responsible for all mutations."""

    async def __call__(self, scope, receive, send):
        self.guard = None
        self.group = None
        try:
            await super().__call__(scope, receive, send)
        except (RedisError, OSError) as exc:
            logger.warning("notification_channel_failed error_type=%s", type(exc).__name__)
            with contextlib.suppress(RuntimeError, OSError):
                await self.close(code=1013)
        finally:
            # A channel-layer exception can end the ASGI app before websocket.disconnect.
            await self.cleanup()

    async def connect(self):
        self.identity = None
        self.group = None
        self.started = self.last_seen = time.monotonic()
        if self.scope.get("query_string"):
            await self.close(code=4400)  # credentials never belong in access logs
            return
        await self.accept()
        self.guard = asyncio.create_task(self.watch_connection())

    async def valid(self):
        if not self.identity:
            return False
        try:
            return await database_sync_to_async(identity_is_valid)(self.identity)
        except Exception:
            return False  # expired/revoked token, deleted user, or failed DB check

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or text_data is None or len(text_data) > 1024:
            await self.close(code=4400)
            return
        try:
            data = json.loads(text_data)
        except (ValueError, TypeError):
            await self.close(code=4400)
            return
        if not isinstance(data, dict):
            await self.close(code=4400)
            return
        await self.receive_json(data)

    async def receive_json(self, content, **kwargs):
        if self.identity is None:
            if content.get("type") != "authenticate":
                await self.close(code=4401)
                return
            try:
                self.identity = await database_sync_to_async(consume_ticket)(content.get("ticket"))
                if not await self.valid():
                    await self.close(code=4401)
                    return
                self.group = user_group(self.identity["user_id"])
                async with asyncio.timeout(2):
                    await self.channel_layer.group_add(self.group, self.channel_name)
            except Exception as exc:
                logger.warning("notification_connect_failed error_type=%s", type(exc).__name__)
                await self.close(code=1013)
                return
            self.last_seen = time.monotonic()
            await self.send_json({"type": "ready", "version": 1})
            return
        if content.get("type") == "pong":
            self.last_seen = time.monotonic()
            return
        await self.close(code=4400)

    async def notifications_changed(self, event):
        if not await self.valid():
            await self.close(code=4401)
            return
        # Do not send bodies, titles, private order fields or client-supplied nt_data.
        await self.send_json({"type": "notifications.changed", "version": 1})

    async def watch_connection(self):
        await asyncio.sleep(5)
        if self.identity is None:
            await self.close(code=4401)
            return
        while True:
            now = time.monotonic()
            if now - self.started >= settings.NOTIFICATION_CONNECTION_TTL or now - self.last_seen > 75:
                await self.close(code=4000)
                return
            if not await self.valid():
                await self.close(code=4401)
                return
            await self.send_json({"type": "ping"})
            await asyncio.sleep(25)

    async def disconnect(self, code):
        await self.cleanup()

    async def cleanup(self):
        guard = getattr(self, "guard", None)
        if guard:
            guard.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError, RuntimeError):
                await guard
        if self.group:
            try:
                async with asyncio.timeout(2):
                    await self.channel_layer.group_discard(self.group, self.channel_name)
            except Exception:
                pass
            self.group = None
