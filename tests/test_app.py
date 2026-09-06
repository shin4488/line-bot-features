import base64
import hashlib
import hmac
import importlib
import json
import os
import socket
import sys
import types
import unittest
from unittest.mock import Mock, patch

import requests
import sentry_sdk

import monitoring
from tests.support import ENVIRONMENT, start_monitoring


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Avoid real config and Firebase initialization, even on a developer's machine.
        database = types.ModuleType("const.database")
        database.FIRESTORE_DB = Mock()
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            with patch.dict(sys.modules, {"const.database": database}):
                cls.main = importlib.import_module("main")
                cls.main.app.logger.disabled = True
                cls.line = importlib.import_module("line.service")
                cls.store = importlib.import_module("store.service")
                cls.ocr = importlib.import_module("ocr.service")
                cls.util = importlib.import_module("util.util")
                cls.db = importlib.import_module("database.service")

    def setUp(self):
        self.events = start_monitoring()
        self.addCleanup(sentry_sdk.get_client().close)
        blocker = patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden"))
        blocker.start()
        self.addCleanup(blocker.stop)
        reply = patch.object(self.main.env.LINE_BOT_API, "reply_message")
        self.reply = reply.start()
        self.addCleanup(reply.stop)
        db = patch.object(self.db, "get_login_user_document",
                          return_value={"language": "ja", "restaurant_range": 2})
        db.start()
        self.addCleanup(db.stop)
        self.client = self.main.app.test_client()

    def post(self, events):
        body = json.dumps({"events": events})
        signature = base64.b64encode(hmac.new(
            ENVIRONMENT["LINE_CHANNEL_SECRET"].encode(), body.encode(), hashlib.sha256
        ).digest()).decode()
        return self.client.post("/callback", data=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": signature})

    def text_event(self):
        return {"type": "message", "replyToken": "synthetic-reply-token", "timestamp": 1,
                "source": {"type": "user", "userId": "SYNTHETIC_PRIVATE_USER"},
                "message": {"type": "text", "id": "1", "text": "SYNTHETIC_PRIVATE_TEXT"}}

    def test_valid_empty_webhook_and_invalid_signatures_are_quiet(self):
        self.assertEqual(self.post([]).status_code, 200)
        self.assertEqual(self.client.get("/callback").status_code, 405)
        for headers in ({}, {"X-Line-Signature": "invalid"}):
            self.assertEqual(self.client.post("/callback", data='{"events":[]}', headers=headers).status_code, 400)
        self.assertEqual(self.events, [])
        self.reply.assert_not_called()

    def test_normal_text_reply_keeps_menu_and_does_not_report(self):
        self.assertEqual(self.post([self.text_event()]).status_code, 200)
        self.reply.assert_called_once()
        self.assertEqual(len(self.reply.call_args.kwargs["messages"]), 2)
        self.assertEqual(self.events, [])

    def test_handled_failure_reports_once_and_sends_static_fallback(self):
        with patch.object(self.line, "handle_text_message", side_effect=RuntimeError("SYNTHETIC_PRIVATE_TEXT")):
            with patch.object(self.util, "translate_if_not_default_language") as translate:
                self.assertEqual(self.post([self.text_event()]).status_code, 200)
                translate.assert_not_called()
        self.reply.assert_called_once()
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_reply_failure_is_captured_by_flask_once(self):
        self.reply.side_effect = requests.Timeout("SYNTHETIC_PRIVATE_TOKEN")
        self.assertEqual(self.post([self.text_event()]).status_code, 500)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_unhandled_webhook_exception_is_captured_once(self):
        with patch.object(self.main.handler, "handle", side_effect=RuntimeError("synthetic")):
            self.assertEqual(self.post([]).status_code, 500)
        self.assertEqual(len(self.events), 1)

    def test_places_zero_results_is_not_an_error(self):
        with patch.object(requests, "get", return_value=Mock(status_code=200,
                json=Mock(return_value={"status": "ZERO_RESULTS", "results": []}))) as get:
            result = self.store.ConvenienceStoreService("synthetic").search_convenience_store(0, 0)
        self.assertEqual(len(result), 1)
        self.assertEqual(self.events, [])
        self.assertEqual(get.call_args.kwargs["timeout"], monitoring.HTTP_TIMEOUT)

    def test_places_http_and_business_failures_are_reported(self):
        for response in [Mock(status_code=503, json=Mock(side_effect=ValueError("not JSON"))),
                         Mock(status_code=200, json=Mock(return_value={"status": "REQUEST_DENIED"}))]:
            with patch.object(requests, "get", return_value=response):
                self.store.ConvenienceStoreService("synthetic").search_convenience_store(0, 0)
        self.assertEqual(len(self.events), 2)
        self.assertEqual([event["tags"]["failure"] for event in self.events], ["http", "api"])

    def test_vision_no_text_is_quiet_but_api_failures_are_reported(self):
        with patch.object(self.ocr, "__translate_by_user_language", side_effect=lambda text, user: text):
            with patch.object(requests, "post", return_value=Mock(status_code=200,
                    json=Mock(return_value={"responses": [{}]}))) as post:
                self.ocr.detect_words("synthetic-image", "synthetic-user")
                self.assertEqual(post.call_args.kwargs["timeout"], monitoring.HTTP_TIMEOUT)
            self.assertEqual(self.events, [])
            for response in [Mock(status_code=500, json=Mock(side_effect=ValueError())),
                             Mock(status_code=200, json=Mock(return_value={"responses": [{"error": {"message": "private"}}]})),
                             Mock(status_code=200, json=Mock(return_value={"responses": []}))]:
                with patch.object(requests, "post", return_value=response):
                    self.ocr.detect_words("synthetic-image", "synthetic-user")
        self.assertEqual([e["tags"]["failure"] for e in self.events], ["http", "api", "response"])

    def test_translation_success_http_business_and_bad_payload(self):
        with patch.object(requests, "get", return_value=Mock(status_code=200,
                json=Mock(return_value={"status": 200, "result": {"text": "translated"}}))) as get:
            self.assertEqual(self.util.translate("synthetic", "ja"), "translated")
            self.assertEqual(get.call_args.kwargs["timeout"], monitoring.HTTP_TIMEOUT)
        self.assertEqual(self.events, [])
        for response in [Mock(status_code=502, json=Mock(side_effect=ValueError())),
                         Mock(status_code=200, json=Mock(return_value={"status": 500})),
                         Mock(status_code=200, json=Mock(return_value={"status": 200, "result": {}}))]:
            with patch.object(requests, "get", return_value=response):
                self.assertEqual(self.util.translate("synthetic", "ja"), "Translation error...")
        self.assertEqual([e["tags"]["failure"] for e in self.events], ["http", "api", "response"])

    def test_request_timeout_is_captured_and_replied_to(self):
        event = self.text_event()
        event["message"] = {"type": "location", "id": "1", "latitude": 0, "longitude": 0}
        with patch.object(requests, "get", side_effect=requests.Timeout("private-url")):
            self.assertEqual(self.post([event]).status_code, 200)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["exception"]["values"][-1]["type"], "Timeout")
        self.reply.assert_called_once()

    def test_store_success_still_builds_a_carousel(self):
        store = {"icon": "https://example.invalid/icon", "name": "Synthetic Store",
                 "opening_hours": {"open_now": True}, "rating": 4,
                 "geometry": {"location": {"lat": 0, "lng": 0}}}
        with patch.object(requests, "get", return_value=Mock(status_code=200,
                json=Mock(return_value={"status": "OK", "results": [store]}))):
            result = self.store.ConvenienceStoreService("synthetic").search_convenience_store(0, 0)
        self.assertEqual(result[0].template.columns[0].title, "Synthetic Store")
        self.assertEqual(self.events, [])

    def test_image_success_still_replies_with_ocr_text_and_menu(self):
        event = self.text_event()
        event["message"] = {"type": "image", "id": "1"}
        response = Mock(status_code=200, json=Mock(return_value={
            "responses": [{"fullTextAnnotation": {"text": "Synthetic\ntext"}}]}))
        with patch.object(self.main.env.LINE_BOT_API, "get_message_content", return_value=Mock(content=b"synthetic")):
            with patch.object(requests, "post", return_value=response):
                with patch.object(self.util, "translate", side_effect=lambda text, lang: text):
                    self.assertEqual(self.post([event]).status_code, 200)
        messages = self.reply.call_args.kwargs["messages"]
        self.assertEqual(messages[0].text, "Synthetic text")
        self.assertEqual(len(messages), 2)
        self.assertEqual(self.events, [])

    def test_language_setting_preserves_firestore_merge_write(self):
        document = Mock()
        document.get.return_value.to_dict.return_value = None
        event = {"type": "postback", "replyToken": "synthetic", "timestamp": 1,
                 "source": {"type": "user", "userId": "synthetic-user"},
                 "postback": {"data": "言語::English::en"}}
        with patch.object(self.db, "get_document_reference", return_value=document):
            self.assertEqual(self.post([event]).status_code, 200)
        document.set.assert_called_once_with(
            {"user_id": "synthetic-user", "language": "en", "restaurant_range": 2}, merge=True)
        self.reply.assert_called_once()
        self.assertEqual(self.events, [])

    def test_unhandled_event_type_is_quiet(self):
        self.assertEqual(self.post([{"type": "follow", "timestamp": 1,
            "replyToken": "synthetic", "source": {"type": "user", "userId": "synthetic"}}]).status_code, 200)
        self.reply.assert_not_called()
        self.assertEqual(self.events, [])
