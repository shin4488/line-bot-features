"""Error-only Sentry reporting with an explicit, minimal data allowlist."""

import logging
import os

import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.integrations.flask import FlaskIntegration

REPOSITORY = "line-bot-features"
DEPLOY_ENVIRONMENT = "production"
HTTP_TIMEOUT = (3.05, 10)  # connect/read seconds; never retry a webhook implicitly
_SERVICES = {"places", "vision", "translation"}
_FAILURES = {"configuration", "http", "api", "response"}
_OPERATIONS = {"startup", "message"}


class ExternalServiceError(Exception):
    """A controlled error: response bodies and URLs must never be included."""


def _stacktrace(stacktrace):
    frames = []
    for frame in stacktrace.get("frames", []):
        clean = {key: frame[key] for key in
                 ("function", "module", "lineno", "colno", "in_app") if key in frame}
        # Keep code locations, never absolute paths, source text or local variables.
        if frame.get("filename"):
            clean["filename"] = str(frame["filename"]).replace("\\", "/").split("/")[-1]
        frames.append(clean)
    return {"frames": frames}


def before_send(event, hint):
    """Rebuild the event so new SDK fields cannot accidentally contain user data."""
    if event.get("type") in {"transaction", "profile"}:
        return None
    clean = {key: event[key] for key in
             ("event_id", "timestamp", "level", "platform", "release", "environment")
             if key in event}
    exceptions = []
    for value in event.get("exception", {}).get("values", []):
        item = {key: value[key] for key in ("type", "module") if key in value}
        # Exception text can contain LINE payloads, OCR text, URLs or credentials.
        item["value"] = "[Filtered]"
        if "stacktrace" in value:
            item["stacktrace"] = _stacktrace(value["stacktrace"])
        mechanism = value.get("mechanism", {})
        item["mechanism"] = {key: mechanism[key] for key in
                             ("type", "handled") if key in mechanism}
        exceptions.append(item)
    if not exceptions:
        return None  # Do not transmit arbitrary log messages/capture_message text.
    clean["exception"] = {"values": exceptions}
    if "threads" in event:
        clean["threads"] = {"values": [
            {"stacktrace": _stacktrace(thread["stacktrace"])}
            for thread in event["threads"].get("values", []) if "stacktrace" in thread
        ]}
    tags = event.get("tags", {})
    clean["tags"] = {"repository": REPOSITORY}
    for key, allowed in (("external_service", _SERVICES), ("failure", _FAILURES),
                         ("operation", _OPERATIONS)):
        if tags.get(key) in allowed:
            clean["tags"][key] = tags[key]
    status = tags.get("http_status")
    if isinstance(status, int) and 100 <= status <= 599:
        clean["tags"]["http_status"] = status
    request = event.get("request", {})
    if request.get("method") in {"GET", "POST", "HEAD", "OPTIONS"}:
        clean["request"] = {"method": request["method"]}
    if event.get("transaction") in {"callback", "/callback"}:
        clean["transaction"] = event["transaction"]
    clean["fingerprint"] = ["{{ default }}", REPOSITORY, clean.get("environment", "development")]
    # Controlled API failures have no exception traceback; split them by service/reason.
    if any(value.get("type") == "ExternalServiceError" for value in exceptions):
        clean["fingerprint"] += [clean["tags"].get("external_service", "unknown"),
                                 clean["tags"].get("failure", "unknown")]
    return clean


def before_breadcrumb(breadcrumb, hint):
    # HTTP/SDK breadcrumbs can include message bodies, query strings and DB paths.
    return None


def init_monitoring():
    dsn = os.getenv("SENTRY_DSN") or os.getenv("SENTRY_DNS")
    if not dsn:
        return False
    environment = os.getenv("SENTRY_ENVIRONMENT") or (
        DEPLOY_ENVIRONMENT if os.getenv("RENDER") else "development"
    )
    release = os.getenv("SENTRY_RELEASE") or (
        REPOSITORY + "@" + os.getenv("RENDER_GIT_COMMIT", "local")
    )
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            default_integrations=False,
            auto_enabling_integrations=False,
            integrations=[FlaskIntegration(), DedupeIntegration(),
                          ExcepthookIntegration(), AtexitIntegration()],
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            before_send=before_send,
            before_breadcrumb=before_breadcrumb,
            max_breadcrumbs=0,
            attach_stacktrace=True,
            sample_rate=1.0,
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            enable_logs=False,
            send_client_reports=False,
            auto_session_tracking=False,
        )
    except Exception:
        # A monitoring configuration error should not take the bot offline.
        logging.getLogger(__name__).warning("Sentry initialization failed; check SENTRY_DSN.")
        return False
    return True


def capture_exception(error, operation="message"):
    with sentry_sdk.new_scope() as scope:
        if operation in _OPERATIONS:
            scope.set_tag("operation", operation)
        return sentry_sdk.capture_exception(error)


def report_api_failure(service, failure, http_status=None):
    if service not in _SERVICES or failure not in _FAILURES:
        raise ValueError("Unknown monitoring category")
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("external_service", service)
        scope.set_tag("failure", failure)
        if http_status is not None:
            scope.set_tag("http_status", http_status)
        sentry_sdk.capture_exception(ExternalServiceError("External service failed"))


def flush():
    sentry_sdk.flush(timeout=2)
