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
from unittest.mock import patch

import requests
import sentry_sdk

from tests.support import (ENVIRONMENT, LINE_CONTENT_URL, LINE_REPLY_URL, PLACES_URL, TRANSLATION_URL,
                           VISION_URL, FakeFirestore, FakeHttp, raising, start_monitoring)

# (connect, read) seconds for the Places, Vision and translation APIs.
EXTERNAL_API_TIMEOUT = (3.05, 10)
# Quick reply menu attached to replies: (LINE action type, label).
MENU = [("location", "トイレ付きコンビニ検索"), ("camera", "撮って翻訳"),
        ("cameraRoll", "選択して翻訳"), ("postback", "Setting")]
LANGUAGE_CODES = {"日本語": "ja", "English": "en", "Espanol": "es", "العربية": "ar", "Français": "fr",
                  "中文": "zh", "한국": "ko", "Melayu": "ms", "Kiswahili": "sw", "اردو": "ur", "Tagalog": "tl"}
# Search range options and the values saved in Firestore.
RANGE_VALUES = {"0.3km": 1, "0.5km": 2, "1km": 3, "2km": 4, "3km": 5}
USER_ID = "SYNTHETIC_PRIVATE_USER"
# Synthetic, but in the LINE user ID format: U followed by 32 lowercase hex digits.
LINE_FORMAT_USER_ID = "U" + "0123456789abcdef" * 2
IMAGE = b"synthetic image"


def translate_unchanged(request):
    # Answers like the translation endpoint for text that is already in the target language.
    return 200, {"status": 200, "result": {"text": request.params["text"], "target": request.params["target"]}}


def place(name="Synthetic Store", **fields):
    return {"name": name, "geometry": {"location": {"lat": 35.6815, "lng": 139.7665}}, **fields}


def detected_text(text):
    return {"responses": [{"fullTextAnnotation": {"text": text}}]}


class ApplicationFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Avoid real config and Firebase initialization, even on a developer's machine.
        cls.const_database = types.ModuleType("const.database")
        cls.const_database.FIRESTORE_DB = None
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            with patch.dict(sys.modules, {"const.database": cls.const_database}):
                cls.main = importlib.import_module("main")
                cls.main.app.logger.disabled = True
                cls.env = importlib.import_module("const.env")
                cls.message = importlib.import_module("const.message")

    def setUp(self):
        self.events = start_monitoring()
        self.addCleanup(sentry_sdk.get_client().close)
        self.start_patch(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
        self.firestore = FakeFirestore()
        self.start_patch(patch.object(self.const_database, "FIRESTORE_DB", self.firestore))
        self.http = FakeHttp()
        self.start_patch(self.http.patch())
        self.http.respond("POST", LINE_REPLY_URL, 200, {})
        self.http.respond("GET", LINE_CONTENT_URL.format("1"), 200, IMAGE, {"Content-Type": "image/jpeg"})
        self.http.handle("GET", TRANSLATION_URL, translate_unchanged)
        self.client = self.main.app.test_client()

    def start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, events):
        return self.post_body(json.dumps({"events": events}))

    def post_body(self, body):
        signature = base64.b64encode(hmac.new(
            ENVIRONMENT["LINE_CHANNEL_SECRET"].encode(), body.encode(), hashlib.sha256
        ).digest()).decode()
        return self.client.post("/callback", data=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": signature})

    def text_event(self, user_id=USER_ID, reply_token="synthetic-reply-token"):
        return {"type": "message", "replyToken": reply_token, "timestamp": 1,
                "source": {"type": "user", "userId": user_id},
                "message": {"type": "text", "id": "1", "text": "SYNTHETIC_PRIVATE_TEXT"}}

    def message_event(self, message, **kwargs):
        event = self.text_event(**kwargs)
        event["message"] = message
        return event

    def location_event(self, **kwargs):
        return self.message_event({"type": "location", "id": "1", "latitude": 35.6812, "longitude": 139.7671},
                                  **kwargs)

    def image_event(self):
        return self.message_event({"type": "image", "id": "1"})

    def postback_event(self, data, user_id=USER_ID):
        return {"type": "postback", "replyToken": "synthetic-reply-token", "timestamp": 1,
                "source": {"type": "user", "userId": user_id}, "postback": {"data": data}}

    def clear_records(self):
        self.events.clear()
        self.http.sent.clear()

    def replies(self):
        """Return the bodies of the reply requests sent to the LINE Messaging API, in order."""
        return [request.json() for request in self.http.requests_to("POST", LINE_REPLY_URL)]

    def replied_messages(self):
        """Return the messages of the only reply sent to LINE."""
        replies = self.replies()
        self.assertEqual(len(replies), 1)
        return replies[0]["messages"]

    def labels(self, message):
        return [item["action"]["label"] for item in message["quickReply"]["items"]]

    def assert_menu(self, message):
        # LINE shows quick reply buttons only when they are attached to the last message of a reply.
        self.assertEqual([(item["action"]["type"], item["action"]["label"])
                          for item in message["quickReply"]["items"]], MENU)

    def assert_error_reply(self):
        """The reply is only the fixed error message, without translation or menu."""
        self.assertEqual(self.replied_messages(), [{"type": "text", "text": self.message.ERROR_MESSAGE("api_error")}])

    def api_failures(self):
        return [(event["tags"].get("external_service"), event["tags"].get("failure"), event["tags"].get("http_status"))
                for event in self.events]

    def tap(self, message, label, user_id=USER_ID):
        """Tap a postback button of the message's quick reply, as the LINE app does."""
        [action] = [item["action"] for item in message["quickReply"]["items"] if item["action"]["label"] == label]
        return self.post([self.postback_event(action["data"], user_id)])

    def open_setting(self, user_id, setting):
        """Open a setting from the menu of a reply, and return the message showing its options."""
        self.post([self.text_event(user_id)])
        self.tap(self.replies()[-1]["messages"][-1], "Setting", user_id)
        self.tap(self.replies()[-1]["messages"][-1], setting, user_id)
        return self.replies()[-1]["messages"][-1]

    def save_settings(self, user_id, **settings):
        self.firestore.documents["user_settings", user_id] = {"user_id": user_id, **settings}

    def saved_settings(self, user_id):
        return self.firestore.documents.get(("user_settings", user_id))


class ApplicationTests(ApplicationFixture):
    def test_valid_empty_webhook_and_invalid_signatures_are_quiet(self):
        self.assertEqual(self.post([]).status_code, 200)
        self.assertEqual(self.client.get("/callback").status_code, 405)
        for headers in ({}, {"X-Line-Signature": "invalid"}):
            self.assertEqual(self.client.post("/callback", data='{"events":[]}', headers=headers).status_code, 400)
        self.assertEqual(self.events, [])
        self.assertEqual(self.replies(), [])

    def test_text_message_is_answered_with_usage_guide_and_menu(self):
        self.assertEqual(self.post([self.text_event()]).status_code, 200)
        messages = self.replied_messages()
        self.assertEqual(messages[0]["text"], self.message.REMIND_MESSAGE)
        self.assert_menu(messages[-1])
        self.assertEqual(self.events, [])

    def test_processing_failure_is_reported_once_and_replies_fixed_message(self):
        self.save_settings(USER_ID, language="en", restaurant_range=2)
        self.http.handle("GET", TRANSLATION_URL, raising(requests.Timeout, "SYNTHETIC_PRIVATE_TEXT"))
        self.assertEqual(self.post([self.text_event()]).status_code, 200)
        self.assert_error_reply()
        # The error reply is not translated, so the failed translation API is not called again.
        self.assertEqual(len(self.http.requests_to("GET", TRANSLATION_URL)), 1)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_reply_failure_is_captured_by_flask_once(self):
        self.http.handle("POST", LINE_REPLY_URL, raising(requests.Timeout, "SYNTHETIC_PRIVATE_TOKEN"))
        self.assertEqual(self.post([self.text_event()]).status_code, 500)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_places_zero_results_replies_no_store_message_without_reporting(self):
        self.http.respond("GET", PLACES_URL, 200, {"status": "ZERO_RESULTS", "results": []})
        self.assertEqual(self.post([self.location_event()]).status_code, 200)
        messages = self.replied_messages()
        self.assertEqual(messages[0]["text"], self.message.ERROR_MESSAGE(404))
        self.assert_menu(messages[-1])
        self.assertEqual(self.events, [])
        [places] = self.http.requests_to("GET", PLACES_URL)
        self.assertEqual(places.timeout, EXTERNAL_API_TIMEOUT)

    def test_places_http_and_business_failures_are_reported(self):
        for response, failure in [((503, b"Service Unavailable"), ("places", "http", 503)),
                                  ((200, {"status": "REQUEST_DENIED"}), ("places", "api", None))]:
            with self.subTest(failure=failure[1]):
                self.clear_records()
                self.http.respond("GET", PLACES_URL, *response)
                self.assertEqual(self.post([self.location_event()]).status_code, 200)
                self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE(400))
                self.assertEqual(self.api_failures(), [failure])

    def test_vision_no_text_is_quiet_but_api_failures_are_reported(self):
        self.http.respond("POST", VISION_URL, 200, {"responses": [{}]})
        self.assertEqual(self.post([self.image_event()]).status_code, 200)
        self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE(2100))
        self.assertEqual(self.events, [])
        [vision] = self.http.requests_to("POST", VISION_URL)
        self.assertEqual(vision.timeout, EXTERNAL_API_TIMEOUT)
        for response, failure in [((500, b"Internal Server Error"), ("vision", "http", 500)),
                                  ((200, {"responses": [{"error": {"message": "private"}}]}), ("vision", "api", None)),
                                  ((200, {"responses": []}), ("vision", "response", None))]:
            with self.subTest(failure=failure[1]):
                self.clear_records()
                self.http.respond("POST", VISION_URL, *response)
                self.assertEqual(self.post([self.image_event()]).status_code, 200)
                self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE(2200))
                self.assertEqual(self.api_failures(), [failure])

    def test_translation_success_http_business_and_bad_payload(self):
        self.http.respond("POST", VISION_URL, 200, detected_text("Synthetic text"))
        self.http.respond("GET", TRANSLATION_URL, 200, {"status": 200, "result": {"text": "translated"}})
        self.assertEqual(self.post([self.image_event()]).status_code, 200)
        self.assertEqual(self.replied_messages()[0]["text"], "translated")
        [translation] = self.http.requests_to("GET", TRANSLATION_URL)
        self.assertEqual(translation.timeout, EXTERNAL_API_TIMEOUT)
        self.assertEqual(self.events, [])
        for response, failure in [((502, b"Bad Gateway"), ("translation", "http", 502)),
                                  ((200, {"status": 500}), ("translation", "api", None)),
                                  ((200, {"status": 200, "result": {}}), ("translation", "response", None))]:
            with self.subTest(failure=failure[1]):
                self.clear_records()
                self.http.respond("GET", TRANSLATION_URL, *response)
                self.assertEqual(self.post([self.image_event()]).status_code, 200)
                self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE("translation_error"))
                self.assertEqual(self.api_failures(), [failure])

    def test_location_replies_carousel_of_convenience_stores_with_toilets(self):
        store = place(icon="https://example.invalid/icon", opening_hours={"open_now": True}, rating=4)
        self.http.respond("GET", PLACES_URL, 200, {"status": "OK", "results": [store]})
        self.assertEqual(self.post([self.location_event()]).status_code, 200)
        messages = self.replied_messages()
        self.assertEqual(messages[0]["template"]["columns"], [{
            "title": "Synthetic Store", "text": "営業中 評価: 4 / 5",
            "actions": [{"type": "uri", "label": "Location",
                         "uri": "https://www.google.co.jp/maps/?q=Synthetic%20Store@35.6815,139.7665"}]}])
        self.assert_menu(messages[-1])
        [places] = self.http.requests_to("GET", PLACES_URL)
        self.assertEqual({key: places.params[key] for key in ("keyword", "type", "location")},
                         {"keyword": "トイレ", "type": "convenience_store", "location": "35.6812,139.7671"})
        self.assertEqual(self.events, [])

    def test_image_text_is_translated_into_user_language_and_replied_with_menu(self):
        self.save_settings(USER_ID, language="en", restaurant_range=2)
        self.http.respond("POST", VISION_URL, 200, detected_text("Synthetic\ntext"))
        self.assertEqual(self.post([self.image_event()]).status_code, 200)
        messages = self.replied_messages()
        self.assertEqual(messages[0]["text"], "Synthetic text")
        self.assert_menu(messages[-1])
        self.assertIn({"text": "Synthetic text", "target": "en"},
                      [request.params for request in self.http.requests_to("GET", TRANSLATION_URL)])
        self.assertEqual(self.events, [])

    def test_each_setting_option_saves_its_value_and_the_default_of_the_other_setting(self):
        cases = [("言語", label, {"language": code, "restaurant_range": 2})
                 for label, code in LANGUAGE_CODES.items()]
        cases += [("指定位置からのコンビニ検索範囲", label, {"language": "ja", "restaurant_range": value})
                  for label, value in RANGE_VALUES.items()]
        options = {setting: self.open_setting(USER_ID, setting) for setting in ("言語", "指定位置からのコンビニ検索範囲")}
        for index, (setting, option, saved) in enumerate(cases):
            # Each option is chosen by a user who has no saved settings yet.
            user_id = "U" + format(index, "032x")
            with self.subTest(setting=setting, option=option):
                self.assertEqual(self.tap(options[setting], option, user_id).status_code, 200)
                self.assertEqual(self.saved_settings(user_id), {"user_id": user_id, **saved})
                messages = self.replies()[-1]["messages"]
                self.assertEqual(messages[0]["text"], f"{setting}を{option}に設定しました")
                self.assert_menu(messages[-1])
        self.assertEqual(self.events, [])

    def test_changing_one_setting_keeps_the_other_saved_settings(self):
        user_id = LINE_FORMAT_USER_ID
        self.save_settings(user_id, language="fr", restaurant_range=4, saved_elsewhere="kept")
        self.tap(self.open_setting(user_id, "言語"), "English", user_id)
        self.assertEqual(self.saved_settings(user_id), {
            "user_id": user_id, "language": "en", "restaurant_range": 4, "saved_elsewhere": "kept"})
        self.tap(self.open_setting(user_id, "指定位置からのコンビニ検索範囲"), "1km", user_id)
        self.assertEqual(self.saved_settings(user_id), {
            "user_id": user_id, "language": "en", "restaurant_range": 3, "saved_elsewhere": "kept"})
        self.assertEqual(self.events, [])

    def test_unhandled_event_type_is_quiet(self):
        self.assertEqual(self.post([{"type": "follow", "timestamp": 1,
            "replyToken": "synthetic", "source": {"type": "user", "userId": "synthetic"}}]).status_code, 200)
        self.assertEqual(self.replies(), [])
        self.assertEqual(self.events, [])
