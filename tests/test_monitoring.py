import copy
import json
import logging
import os
import unittest
from unittest.mock import patch

import sentry_sdk

import monitoring
from tests.support import DSN, start_monitoring


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.events = start_monitoring()
        self.addCleanup(sentry_sdk.get_client().close)

    def test_removes_sensitive_data_from_all_event_fields(self):
        secret = "SYNTHETIC_PRIVATE_MARKER"
        frame = {"filename": "/private/" + secret + "/service.py", "lineno": 42,
                 "function": "handle", "in_app": True, "vars": {"token": secret},
                 "context_line": secret, "pre_context": [secret]}
        event = {
            "event_id": "a" * 32, "environment": "staging", "release": "repo@abc",
            "exception": {"values": [{"type": "ValueError", "value": secret,
                "stacktrace": {"frames": [frame]},
                "mechanism": {"type": "generic", "handled": True, "data": secret}}]},
            "threads": {"values": [{"name": secret, "stacktrace": {"frames": [frame]}}]},
            "request": {"method": "POST", "url": "https://x/" + secret,
                "query_string": secret, "headers": {"Authorization": secret},
                "data": {"events": [secret]}, "cookies": secret, "env": secret},
            "user": {"id": secret}, "extra": {"image": secret},
            "contexts": {"custom": {"location": secret}}, "server_name": secret,
            "breadcrumbs": {"values": [{"message": secret}]}, "logentry": secret,
            "tags": {"user_id": secret, "external_service": "places", "failure": "http",
                     "http_status": 503, "unrecognized": secret},
            "transaction": secret, "fingerprint": [secret], "future_sdk_field": secret,
        }
        cleaned = monitoring.before_send(copy.deepcopy(event), {})
        self.assertNotIn(secret, json.dumps(cleaned))
        self.assertEqual(cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]["lineno"], 42)
        self.assertEqual(cleaned["tags"]["external_service"], "places")
        self.assertEqual(cleaned["tags"]["http_status"], 503)

    def test_environment_and_repo_are_part_of_issue_fingerprint(self):
        event = {"exception": {"values": [{"type": "RuntimeError"}]}}
        prod = monitoring.before_send(dict(event, environment="production"), {})
        stage = monitoring.before_send(dict(event, environment="staging"), {})
        self.assertNotEqual(prod["fingerprint"], stage["fingerprint"])
        self.assertEqual(stage["fingerprint"][:2], ["{{ default }}", monitoring.REPOSITORY])

    def test_real_sdk_scrubs_exception_and_deduplicates(self):
        try:
            raise ValueError("SYNTHETIC_PRIVATE_MARKER")
        except ValueError as error:
            monitoring.capture_exception(error)
            monitoring.capture_exception(error)
            logging.getLogger("test").debug("SYNTHETIC_PRIVATE_MARKER", exc_info=True)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", json.dumps(self.events))
        self.assertEqual(self.events[0]["release"], monitoring.REPOSITORY + "@" + "a" * 40)

    def test_api_failure_tags_do_not_leak_to_next_event(self):
        monitoring.report_api_failure("vision", "http", 503)
        monitoring.capture_exception(RuntimeError("synthetic"))
        self.assertEqual(len(self.events), 2)
        self.assertEqual(self.events[0]["tags"]["external_service"], "vision")
        self.assertEqual(self.events[0]["tags"]["http_status"], 503)
        self.assertNotIn("external_service", self.events[1]["tags"])

    def test_no_dsn_means_no_initialization(self):
        with patch.dict(os.environ, {}, clear=True), patch("monitoring.sentry_sdk.init") as init:
            self.assertFalse(monitoring.init_monitoring())
            init.assert_not_called()

    def test_legacy_dsn_and_render_environment_default(self):
        with patch.dict(os.environ, {"SENTRY_DNS": DSN, "RENDER": "true"}, clear=True):
            with patch("monitoring.sentry_sdk.init") as init:
                self.assertTrue(monitoring.init_monitoring())
        self.assertEqual(init.call_args.kwargs["dsn"], DSN)
        self.assertEqual(init.call_args.kwargs["environment"], monitoring.DEPLOY_ENVIRONMENT)

    def test_invalid_dsn_does_not_crash_the_app(self):
        with patch.dict(os.environ, {"SENTRY_DSN": "invalid"}, clear=True):
            with self.assertLogs("monitoring", level="WARNING") as logs:
                self.assertFalse(monitoring.init_monitoring())
        self.assertNotIn("invalid", " ".join(logs.output))

    def test_no_messages_breadcrumbs_or_performance_events(self):
        sentry_sdk.add_breadcrumb(message="synthetic user message")
        sentry_sdk.capture_message("synthetic user message")
        with sentry_sdk.start_transaction(name="synthetic"):
            pass
        self.assertEqual(self.events, [])

    def test_exception_chain_and_exception_group_are_scrubbed(self):
        try:
            try:
                raise ValueError("SYNTHETIC_PRIVATE")
            except ValueError as cause:
                raise RuntimeError("SYNTHETIC_PRIVATE") from cause
        except RuntimeError as error:
            monitoring.capture_exception(error)
        self.assertEqual([v["type"] for v in self.events[0]["exception"]["values"]],
                         ["ValueError", "RuntimeError"])
        try:
            raise ExceptionGroup("SYNTHETIC_PRIVATE", [ValueError("SYNTHETIC_PRIVATE"),
                                                      TypeError("SYNTHETIC_PRIVATE")])
        except ExceptionGroup as error:
            monitoring.capture_exception(error)
        self.assertEqual(len(self.events), 2)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_standard_dsn_takes_precedence_and_local_default_is_development(self):
        with patch.dict(os.environ, {"SENTRY_DSN": DSN, "SENTRY_DNS": "wrong-legacy",
                                     "SENTRY_RELEASE": "explicit@commit"}, clear=True):
            with patch("monitoring.sentry_sdk.init") as init:
                self.assertTrue(monitoring.init_monitoring())
        self.assertEqual(init.call_args.kwargs["dsn"], DSN)
        self.assertEqual(init.call_args.kwargs["environment"], "development")
        self.assertEqual(init.call_args.kwargs["release"], "explicit@commit")

    def test_parallel_scopes_do_not_mix_tags(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda service: monitoring.report_api_failure(service, "http", 503),
                          ["places", "vision", "translation"] * 4))
        self.assertEqual(len(self.events), 12)
        for service in ("places", "vision", "translation"):
            self.assertEqual(sum(e["tags"].get("external_service") == service for e in self.events), 4)
