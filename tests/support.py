"""Only synthetic data and an in-memory Sentry transport are used in tests."""
import os
from unittest.mock import patch

import sentry_sdk
from sentry_sdk.transport import Transport

import monitoring

DSN = "https://test-key@sentry.invalid/1"
ENVIRONMENT = {
    "LINE_CHANNEL_SECRET": "synthetic-channel-secret",
    "LINE_CHANNEL_ACCESS_TOKEN": "synthetic-access-token",
    "GOOGLE_API_KEY": "synthetic-api-key",
    "GOOGLE_APP_SCRIPTS_ENDPOINT": "https://translation.invalid/test",
}


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
