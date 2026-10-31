"""Exercise real webhook dispatch with faults injected at external boundaries."""
import base64
import json
from unittest.mock import patch

import requests

from tests.support import LINE_CONTENT_URL, LINE_REPLY_URL, PLACES_URL, TRANSLATION_URL, VISION_URL, raising
from tests.test_app import (LANGUAGE_CODES, LINE_FORMAT_USER_ID, RANGE_VALUES, USER_ID, ApplicationFixture,
                            detected_text, place)


class EdgeCaseTests(ApplicationFixture):
    def test_places_optional_fields_do_not_break_results(self):
        # A place can legitimately have no opening hours, rating or icon.
        self.http.respond("GET", PLACES_URL, 200, {"status": "OK", "results": [place()]})
        self.assertEqual(self.post([self.location_event()]).status_code, 200)
        [column] = self.replied_messages()[0]["template"]["columns"]
        self.assertEqual((column["title"], column["text"]), ("Synthetic Store", "営業時間不明"))
        self.assertEqual(self.events, [])

    def test_long_translations_fit_line_carousel_fields(self):
        self.save_settings(USER_ID, language="en", restaurant_range=2)
        self.http.respond("GET", TRANSLATION_URL, 200, {"status": 200, "result": {"text": "長" * 200}})
        store = place("x" * 80, opening_hours={"open_now": True}, rating=4)
        self.http.respond("GET", PLACES_URL, 200, {"status": "OK", "results": [store] * 6})
        self.post([self.location_event()])
        columns = self.replied_messages()[0]["template"]["columns"]
        self.assertEqual(len(columns), 5)
        for column in columns:
            self.assertLessEqual(len(column["title"]), 40)
            self.assertLessEqual(len(column["text"]), 60)

    def test_long_translations_fit_line_quick_reply_labels(self):
        self.save_settings(USER_ID, language="en", restaurant_range=2)
        self.http.respond("GET", TRANSLATION_URL, 200, {"status": 200, "result": {"text": "長" * 200}})
        self.post([self.text_event()])
        menu = self.replies()[-1]["messages"][-1]
        self.tap(menu, "Setting")
        settings = self.replies()[-1]["messages"][-1]
        # The menu has 4 buttons and the setting menu has 2; LINE accepts labels of up to 20 characters.
        for message, count in [(menu, 4), (settings, 2)]:
            labels = self.labels(message)
            self.assertEqual(len(labels), count)
            for label in labels:
                self.assertTrue(0 < len(label) <= 20, label)
        self.assertEqual(self.events, [])

    def test_ocr_empty_annotation_does_not_send_empty_line_text(self):
        self.http.respond("POST", VISION_URL, 200, detected_text(""))
        self.post([self.image_event()])
        self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE(2100))
        self.assertEqual(self.events, [])

    def test_empty_translation_response_is_reported_as_invalid(self):
        self.http.respond("POST", VISION_URL, 200, detected_text("non-empty synthetic text"))
        self.http.respond("GET", TRANSLATION_URL, 200, {"status": 200, "result": {"text": ""}})
        self.post([self.image_event()])
        self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE("translation_error"))
        self.assertEqual(self.api_failures(), [("translation", "response", None)])

    def test_places_timeout_connection_and_malformed_json_each_report_once(self):
        for error_type, handler in [("Timeout", raising(requests.Timeout)),
                                    ("ConnectionError", raising(requests.ConnectionError)),
                                    ("JSONDecodeError", lambda request: (200, b"SYNTHETIC_PRIVATE"))]:
            with self.subTest(error_type=error_type):
                self.clear_records()
                self.http.handle("GET", PLACES_URL, handler)
                self.assertEqual(self.post([self.location_event()]).status_code, 200)
                self.assert_error_reply()
                self.assertEqual([event["exception"]["values"][-1]["type"] for event in self.events], [error_type])
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_bad_api_payload_shapes_are_caught_without_leaking_data(self):
        for payload in (None, [], "SYNTHETIC_PRIVATE", {"status": "OK"},
                        {"status": "OK", "results": None}):
            with self.subTest(payload_type=type(payload).__name__):
                self.clear_records()
                self.http.respond("GET", PLACES_URL, 200, payload)
                self.assertEqual(self.post([self.location_event()]).status_code, 200)
                self.assert_error_reply()
                self.assertEqual(len(self.events), 1)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_database_read_failure_does_not_trigger_more_database_calls(self):
        self.firestore.fail_reads = True
        self.assertEqual(self.post([self.text_event()]).status_code, 200)
        self.assertEqual((self.firestore.reads, self.firestore.writes), (1, 0))
        self.assert_error_reply()
        self.assertEqual(len(self.events), 1)

    def test_database_write_failure_is_reported_and_replied_to(self):
        user_id = LINE_FORMAT_USER_ID
        self.save_settings(user_id, language="ja", restaurant_range=2)
        options = self.open_setting(user_id, "言語")
        self.clear_records()
        self.firestore.fail_writes = True
        self.assertEqual(self.tap(options, "English", user_id).status_code, 200)
        self.assertEqual(self.saved_settings(user_id)["language"], "ja")
        self.assertEqual(len(self.events), 1)
        self.assert_error_reply()

    def test_handled_failure_does_not_prevent_the_next_event(self):
        self.http.handle("GET", PLACES_URL, raising(requests.ConnectionError))
        events = [self.location_event(reply_token="reply-1"), self.text_event(reply_token="reply-2")]
        self.assertEqual(self.post(events).status_code, 200)
        first, second = self.replies()
        self.assertEqual((first["replyToken"], first["messages"]),
                         ("reply-1", [{"type": "text", "text": self.message.ERROR_MESSAGE("api_error")}]))
        self.assertEqual(second["replyToken"], "reply-2")
        self.assertEqual(second["messages"][0]["text"], self.message.REMIND_MESSAGE)
        self.assertEqual(len(self.events), 1)

    def test_simultaneous_processing_and_reply_failure_keeps_both_errors(self):
        self.http.handle("GET", PLACES_URL, raising(requests.ConnectionError))
        self.http.handle("POST", LINE_REPLY_URL, raising(requests.Timeout))
        self.assertEqual(self.post([self.location_event()]).status_code, 500)
        self.assertEqual(sorted(event["exception"]["values"][-1]["type"] for event in self.events),
                         ["ConnectionError", "Timeout"])
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_line_reply_uses_the_reply_token_and_sdk_default_timeout(self):
        self.assertEqual(self.post([self.text_event()]).status_code, 200)
        [reply] = self.http.requests_to("POST", LINE_REPLY_URL)
        self.assertEqual(reply.json()["replyToken"], "synthetic-reply-token")
        self.assertEqual(reply.timeout, 5)
        self.assertEqual(self.events, [])

    def test_real_line_api_error_response_is_filtered(self):
        self.http.respond("POST", LINE_REPLY_URL, 429, {"message": "SYNTHETIC_PRIVATE"},
                          {"Content-Type": "application/json", "x-line-request-id": "SYNTHETIC_PRIVATE"})
        self.assertEqual(self.post([self.text_event()]).status_code, 500)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_video_and_audio_get_usage_guide_and_sticker_is_echoed(self):
        sticker = {"type": "sticker", "id": "1", "packageId": "446", "stickerId": "1988"}
        for message in [{"type": "video", "id": "1", "duration": 1}, {"type": "audio", "id": "1", "duration": 1},
                        sticker]:
            with self.subTest(message_type=message["type"]):
                self.clear_records()
                self.assertEqual(self.post([self.message_event(message)]).status_code, 200)
                messages = self.replied_messages()
                if message is sticker:
                    self.assertEqual({key: messages[0][key] for key in ("type", "packageId", "stickerId")},
                                     {"type": "sticker", "packageId": "446", "stickerId": "1988"})
                else:
                    self.assertIn(self.message.REMIND_MESSAGE, messages[0]["text"])
                self.assert_menu(messages[-1])
                self.assertEqual(self.events, [])

    def test_setting_menu_offers_language_and_search_range_options(self):
        self.post([self.text_event()])
        self.tap(self.replies()[-1]["messages"][-1], "Setting")
        settings = self.replies()[-1]["messages"][-1]
        self.assertEqual(self.labels(settings), ["言語", "指定位置からのコンビニ検索範囲"])
        for setting, options in [("言語", list(LANGUAGE_CODES)), ("指定位置からのコンビニ検索範囲", list(RANGE_VALUES))]:
            with self.subTest(setting=setting):
                self.assertEqual(self.tap(settings, setting).status_code, 200)
                self.assertEqual(self.labels(self.replies()[-1]["messages"][-1]), options)
        self.assertEqual(self.events, [])

    def test_missing_api_settings_are_reported_without_network(self):
        with patch.object(self.env, "GOOGLE_API_KEY", None):
            self.post([self.image_event()])
        self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE("api_error"))
        self.assertEqual(self.http.requests_to("POST", VISION_URL), [])
        self.assertEqual(self.api_failures(), [("vision", "configuration", None)])
        self.clear_records()
        self.http.respond("POST", VISION_URL, 200, detected_text("Synthetic text"))
        with patch.object(self.env, "GAS_TRANSLATE_ENDPOINT", None):
            self.post([self.image_event()])
        self.assertEqual(self.replied_messages()[0]["text"], self.message.ERROR_MESSAGE("translation_error"))
        self.assertEqual(self.http.requests_to("GET", TRANSLATION_URL), [])
        self.assertEqual(self.api_failures(), [("translation", "configuration", None)])

    def test_signed_malformed_webhooks_are_reported_without_body_contents(self):
        for body in ['{"SYNTHETIC_PRIVATE":', '{}', '{"events":null}']:
            with self.subTest(body_shape=body[:10]):
                self.events.clear()
                self.assertEqual(self.post_body(body).status_code, 500)
                self.assertEqual(len(self.events), 1)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))
        self.assertEqual(self.replies(), [])

    def test_ocr_transport_failure_sends_fallback_and_no_private_image(self):
        image = b"SYNTHETIC_PRIVATE image"
        self.http.respond("GET", LINE_CONTENT_URL.format("1"), 200, image, {"Content-Type": "image/jpeg"})
        self.http.handle("POST", VISION_URL, raising(requests.Timeout))
        self.assertEqual(self.post([self.image_event()]).status_code, 200)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))
        self.assertNotIn(base64.b64encode(image).decode(), json.dumps(self.events))
        self.assert_error_reply()

    def test_invalid_postback_does_not_write_to_database(self):
        user_id = LINE_FORMAT_USER_ID
        self.save_settings(user_id, language="ja", restaurant_range=2)
        # The language setting without its value: no button sent by the bot posts this data.
        self.assertEqual(self.post([self.postback_event("言語::", user_id)]).status_code, 200)
        self.assertEqual(self.firestore.writes, 0)
        self.assertEqual(self.saved_settings(user_id), {"user_id": user_id, "language": "ja", "restaurant_range": 2})
        self.assertEqual(len(self.events), 1)
        self.assert_error_reply()

    def test_reply_failure_returns_500_without_implicitly_retrying_batch(self):
        self.http.handle("POST", LINE_REPLY_URL, raising(requests.Timeout))
        self.assertEqual(self.post([self.text_event(), self.text_event()]).status_code, 500)
        self.assertEqual(len(self.http.requests_to("POST", LINE_REPLY_URL)), 1)
        self.assertEqual(len(self.events), 1)

    def test_ocr_text_longer_than_2000_characters_is_truncated_before_line_reply(self):
        self.http.respond("POST", VISION_URL, 200, detected_text("synthetic"))
        for translated, replied in [("字" * 2000, "字" * 2000), ("字" * 2001, "字" * 1997 + "...")]:
            with self.subTest(length=len(translated)):
                self.clear_records()
                self.http.respond("GET", TRANSLATION_URL, 200, {"status": 200, "result": {"text": translated}})
                self.post([self.image_event()])
                self.assertEqual(self.replied_messages()[0]["text"], replied)
                self.assertEqual(self.events, [])

    def test_saved_search_range_is_applied_to_places_request(self):
        self.http.respond("GET", PLACES_URL, 200, {"status": "ZERO_RESULTS", "results": []})
        # None: the user has not saved any settings yet.
        for selection, meters in [(None, 500), (1, 300), (2, 500), (3, 1000), (4, 2000), (5, 3000)]:
            with self.subTest(selection=selection):
                self.clear_records()
                self.firestore.documents.clear()
                if selection is not None:
                    self.save_settings(USER_ID, language="ja", restaurant_range=selection)
                self.post([self.location_event()])
                # Both the search for toilets and the search for nearby stores use the saved range.
                self.assertEqual([int(places.params["radius"]) for places in self.http.requests_to("GET", PLACES_URL)],
                                 [meters, meters])
