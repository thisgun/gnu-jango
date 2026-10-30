"""Delivery Tracker (tracker.delivery) GraphQL API: the only module that talks to it.

Verified against https://tracker.delivery/docs (2026-10-30):

- POST https://apis.tracker.delivery/graphql with ``Authorization: TRACKQL-API-KEY
  <client id>:<client secret>`` (docs/authentication) and a JSON ``{"query", "variables"}`` body.
- ``track(carrierId: ID!, trackingNumber: String!): TrackInfo`` - TrackInfo.lastEvent is the most
  likely current event (DELIVERED wins over a later OUT_FOR_DELIVERY) and TrackInfo.events is a
  Relay connection sorted oldest to newest. TrackEvent has status {code, name}, time (RFC 3339
  with an offset), location {name}, description.
- ``registerTrackWebhook(input: {carrierId, trackingNumber, callbackUrl, expirationTime}): Boolean``.
- Errors come back in ``errors[].extensions.code`` even with HTTP 200: UNAUTHENTICATED,
  FORBIDDEN, INTERNAL, BAD_REQUEST, NOT_FOUND.

Requests go to the fixed host only and never follow a redirect (a redirect would carry the
Authorization header elsewhere). Callers get TrackInfo / True or a DeliveryTrackerError."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.views.decorators.debug import sensitive_variables

logger = logging.getLogger(__name__)

API_URL = "https://apis.tracker.delivery/graphql"
# the docs: a track answer usually takes under a second; allow up to 15 seconds
TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 512 * 1024
EVENTS_LIMIT = 30
# docs/api-schema enums TrackEventStatusCode
STATUS_CODES = (
    "UNKNOWN",
    "INFORMATION_RECEIVED",
    "AT_PICKUP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "ATTEMPT_FAIL",
    "DELIVERED",
    "AVAILABLE_FOR_PICKUP",
    "EXCEPTION",
)
STATUS_DELIVERED = "DELIVERED"
# errors worth trying again later; the others need the operator (keys) or will not change
RETRYABLE_CODES = {"INTERNAL", "NETWORK", "RATE_LIMITED", "INVALID_RESPONSE"}

EVENT_FIELDS = "time status { code name } location { name } description"
TRACK_QUERY = (
    "query Track($carrierId: ID!, $trackingNumber: String!, $last: Int) {"
    " track(carrierId: $carrierId, trackingNumber: $trackingNumber) {"
    f" lastEvent {{ {EVENT_FIELDS} }}"
    f" events(last: $last) {{ edges {{ node {{ {EVENT_FIELDS} }} }} }}"
    " } }"
)
REGISTER_WEBHOOK_MUTATION = (
    "mutation RegisterTrackWebhook($input: RegisterTrackWebhookInput!) {"
    " registerTrackWebhook(input: $input) }"
)


class DeliveryTrackerError(Exception):
    """``code`` is the API's error code, or NETWORK / RATE_LIMITED / INVALID_RESPONSE / HTTP_<n>."""

    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code
        self.message = message

    @property
    def retryable(self):
        return self.code in RETRYABLE_CODES or self.code.startswith("HTTP_5")


@dataclass(frozen=True)
class TrackerCredentials:
    client_id: str
    client_secret: str

    def __bool__(self):
        return bool(self.client_id and self.client_secret)

    def __repr__(self):  # never print a secret by accident
        return f"TrackerCredentials(client_id={'set' if self.client_id else 'missing'})"


@dataclass(frozen=True)
class TrackEvent:
    time: datetime | None
    status: str
    name: str
    location: str
    description: str

    def as_dict(self):
        return {
            "time": self.time.isoformat() if self.time else "",
            "status": self.status,
            "name": self.name,
            "location": self.location,
            "description": self.description,
        }


@dataclass(frozen=True)
class TrackInfo:
    last_event: TrackEvent | None
    events: tuple  # TrackEvent, oldest first

    @property
    def delivered(self):
        return bool(self.last_event and self.last_event.status == STATUS_DELIVERED)


class _NoRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib_request.build_opener(_NoRedirect)


def _text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
    # DateTime always carries an offset; a value without one is not trusted as a moment
    return parsed if parsed.tzinfo else None


def parse_event(node):
    if not isinstance(node, dict):
        return None
    status = node.get("status") if isinstance(node.get("status"), dict) else {}
    location = node.get("location") if isinstance(node.get("location"), dict) else {}
    code = str(status.get("code") or "").strip().upper()
    return TrackEvent(
        time=parse_time(node.get("time")),
        status=code if code in STATUS_CODES else "UNKNOWN",
        name=_text(status.get("name"), 100),
        location=_text(location.get("name"), 200),
        description=_text(node.get("description"), 500),
    )


def parse_track_info(data):
    """TrackInfo from the ``data`` of a track answer; NOT_FOUND when ``track`` is null."""
    track = data.get("track") if isinstance(data, dict) else None
    if not isinstance(track, dict):
        raise DeliveryTrackerError("NOT_FOUND", "No tracking information.")
    connection = track.get("events") if isinstance(track.get("events"), dict) else {}
    edges = connection.get("edges") if isinstance(connection.get("edges"), list) else []
    events = [parse_event(edge.get("node")) for edge in edges if isinstance(edge, dict)]
    events = tuple(event for event in events if event is not None)[-EVENTS_LIMIT:]
    last_event = parse_event(track.get("lastEvent")) or (events[-1] if events else None)
    return TrackInfo(last_event=last_event, events=events)


def _graphql_error(payload):
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if not errors:
        return None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    extensions = first.get("extensions") if isinstance(first.get("extensions"), dict) else {}
    code = _text(extensions.get("code"), 40).upper() or "INVALID_RESPONSE"
    return DeliveryTrackerError(code, _text(first.get("message"), 200))


@sensitive_variables("credentials", "headers")
def _post(query, variables, *, credentials):
    if not credentials:
        raise DeliveryTrackerError("UNAUTHENTICATED", "Delivery Tracker keys are not set.")
    headers = {
        "Authorization": f"TRACKQL-API-KEY {credentials.client_id}:{credentials.client_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = json.dumps({"query": query, "variables": variables}, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(API_URL, data=body, method="POST", headers=headers)
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib_error.HTTPError as exc:
        # GraphQL errors may come with any status; read them before falling back to the status
        try:
            payload = json.loads(exc.read(MAX_RESPONSE_BYTES).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError, OSError):
            payload = {}
        error = _graphql_error(payload)
        if error is not None:
            raise error from None
        code = "RATE_LIMITED" if exc.code == 429 else f"HTTP_{exc.code}"
        raise DeliveryTrackerError(code, f"HTTP {exc.code}") from None
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Delivery Tracker request failed: %s", type(exc).__name__)
        raise DeliveryTrackerError("NETWORK", "Could not reach Delivery Tracker.") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DeliveryTrackerError("INVALID_RESPONSE", "The answer is too large.")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        raise DeliveryTrackerError("INVALID_RESPONSE", "The answer is not JSON.") from None
    error = _graphql_error(payload)
    if error is not None:
        raise error
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise DeliveryTrackerError("INVALID_RESPONSE", "The answer has no data.")
    return data


def track(carrier_id, tracking_number, *, credentials):
    """The shipment's TrackInfo (the newest EVENTS_LIMIT events)."""
    data = _post(
        TRACK_QUERY,
        {"carrierId": carrier_id, "trackingNumber": tracking_number, "last": EVENTS_LIMIT},
        credentials=credentials,
    )
    return parse_track_info(data)


def register_webhook(carrier_id, tracking_number, *, callback_url, expires_at, credentials):
    """Ask Delivery Tracker to POST ``callback_url`` when the shipment changes, until
    ``expires_at`` (calling it again extends the webhook). True when it was accepted."""
    data = _post(
        REGISTER_WEBHOOK_MUTATION,
        {
            "input": {
                "carrierId": carrier_id,
                "trackingNumber": tracking_number,
                "callbackUrl": callback_url,
                "expirationTime": expires_at.isoformat(),
            }
        },
        credentials=credentials,
    )
    return data.get("registerTrackWebhook") is True
