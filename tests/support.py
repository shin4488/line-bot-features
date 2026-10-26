"""Only synthetic data, in-memory fakes of the external services and an in-memory Sentry transport are used in tests."""
import copy
import io
import json
import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import patch

from google.api_core.exceptions import ServiceUnavailable
import requests
import sentry_sdk
from sentry_sdk.transport import Transport
import urllib3

import monitoring

DSN = "https://test-key@sentry.invalid/1"
ENVIRONMENT = {
    "LINE_CHANNEL_SECRET": "synthetic-channel-secret",
    "LINE_CHANNEL_ACCESS_TOKEN": "synthetic-access-token",
    "GOOGLE_API_KEY": "synthetic-api-key",
    "GOOGLE_APP_SCRIPTS_ENDPOINT": "https://translation.invalid/test",
}
# Endpoints defined by the LINE Messaging API, the Places API and the Cloud Vision API.
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_CONTENT_URL = "https://api-data.line.me/v2/bot/message/{}/content"
PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
TRANSLATION_URL = ENVIRONMENT["GOOGLE_APP_SCRIPTS_ENDPOINT"]


class MemoryTransport(Transport):
    def __init__(self, options):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self.events.append(item.payload.json)


def start_monitoring(environment="staging", **extra_env):
    real_init = sentry_sdk.init

    def init(**options):
        return real_init(transport=MemoryTransport, **options)

    with patch.dict(os.environ, {"SENTRY_DSN": DSN, "SENTRY_ENVIRONMENT": environment,
                                 "RENDER_GIT_COMMIT": "a" * 40, **extra_env}, clear=True):
        with patch("monitoring.sentry_sdk.init", side_effect=init):
            assert monitoring.init_monitoring()
    return sentry_sdk.get_client().transport.events


@dataclass
class SentRequest:
    method: str
    url: str  # Without the query string, which is parsed into params.
    params: dict
    body: bytes
    timeout: object

    def json(self):
        return json.loads(self.body)


def raising(error_type, message="SYNTHETIC_PRIVATE"):
    """Return a FakeHttp handler that fails like the transport, raising a new error on each request."""
    def handler(request):
        raise error_type(message)
    return handler


class FakeHttp:
    """Answers the requests sent through the requests library instead of the external APIs, and records them."""

    def __init__(self):
        self.handlers = {}
        self.sent = []

    def patch(self):
        return patch.object(requests.adapters.HTTPAdapter, "send",
                            lambda adapter, request, **kwargs: self.send(adapter, request, **kwargs))

    def handle(self, method, url, handler):
        """Answer requests to the URL with handler(SentRequest), which returns (status, body[, headers])."""
        self.handlers[method, url] = handler

    def respond(self, method, url, status, body, headers=None):
        self.handle(method, url, lambda request: (status, body, headers))

    def requests_to(self, method, url):
        return [request for request in self.sent if (request.method, request.url) == (method, url)]

    def send(self, adapter, request, **kwargs):
        parts = urlsplit(request.url)
        body = request.body.encode() if isinstance(request.body, str) else request.body
        sent = SentRequest(request.method, f"{parts.scheme}://{parts.netloc}{parts.path}",
                           dict(parse_qsl(parts.query)), body, kwargs.get("timeout"))
        self.sent.append(sent)
        handler = self.handlers.get((sent.method, sent.url))
        if handler is None:
            raise AssertionError(f"Unexpected request: {sent.method} {sent.url}")
        status, body, *headers = handler(sent)
        headers = (headers and headers[0]) or {
            "Content-Type": "text/plain" if isinstance(body, bytes) else "application/json"}
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        raw = urllib3.HTTPResponse(body=io.BytesIO(content), headers=headers, status=status,
                                   preload_content=False)
        return adapter.build_response(request, raw)


class FakeFirestore:
    """In-memory Firestore client. Documents are stored by (collection, document ID); merge applies to top-level fields."""

    def __init__(self):
        self.documents = {}
        self.reads = 0
        self.writes = 0
        self.fail_reads = False
        self.fail_writes = False

    def collection(self, name):
        return _FakeCollection(self, name)


class _FakeCollection:
    def __init__(self, store, name):
        self.store = store
        self.name = name

    def document(self, document_id):
        return _FakeDocumentReference(self.store, (self.name, document_id))


class _FakeDocumentReference:
    def __init__(self, store, key):
        self.store = store
        self.key = key
        self.id = key[1]

    def get(self):
        self.store.reads += 1
        if self.store.fail_reads:
            raise ServiceUnavailable("SYNTHETIC_PRIVATE")
        return _FakeSnapshot(self.store.documents.get(self.key))

    def set(self, data, merge=False):
        self.store.writes += 1
        if self.store.fail_writes:
            raise ServiceUnavailable("SYNTHETIC_PRIVATE")
        saved = self.store.documents.get(self.key, {}) if merge else {}
        self.store.documents[self.key] = {**saved, **copy.deepcopy(data)}


class _FakeSnapshot:
    def __init__(self, data):
        self._data = copy.deepcopy(data)
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)
