"""Exercise real webhook dispatch with faults injected at external boundaries."""
import json
from unittest.mock import Mock, patch

import requests
from linebot import LineBotApi

from tests.test_app import ApplicationFixture


class EdgeCaseTests(ApplicationFixture):
    def location_event(self):
        event = self.text_event()
        event["message"] = {"type": "location", "id": "1", "latitude": 0, "longitude": 0}
        return event

    def test_places_optional_fields_do_not_break_results(self):
        # A place can legitimately have no opening hours, rating or icon.
        store = {"name": "Synthetic Store", "geometry": {"location": {"lat": 0, "lng": 0}}}
        with patch.object(requests, "get", return_value=Mock(status_code=200,
                json=Mock(return_value={"status": "OK", "results": [store]}))):
            self.assertEqual(self.post([self.location_event()]).status_code, 200)
        messages = self.reply.call_args.kwargs["messages"]
        self.assertEqual(messages[0].type, "template")
        self.assertEqual(self.events, [])

    def test_long_translations_fit_line_carousel_fields(self):
        store = {"icon": "synthetic", "name": "x" * 80,
                 "opening_hours": {"open_now": True}, "rating": 4,
                 "geometry": {"location": {"lat": 0, "lng": 0}}}
        with patch.object(self.util, "translate_if_not_default_language", return_value="長" * 200):
            with patch.object(requests, "get", return_value=Mock(status_code=200,
                    json=Mock(return_value={"status": "OK", "results": [store] * 6}))):
                self.post([self.location_event()])
        columns = self.reply.call_args.kwargs["messages"][0].template.columns
        self.assertEqual(len(columns), 5)
        for column in columns:
            self.assertLessEqual(len(column.title), 40)
            self.assertLessEqual(len(column.text), 60)

    def test_ocr_empty_annotation_does_not_send_empty_line_text(self):
        event = self.text_event()
        event["message"] = {"type": "image", "id": "1"}
        with patch.object(self.main.env.LINE_BOT_API, "get_message_content", return_value=Mock(content=b"synthetic")):
            with patch.object(self.util, "translate", side_effect=lambda text, lang: text):
                with patch.object(requests, "post", return_value=Mock(status_code=200,
                        json=Mock(return_value={"responses": [{"fullTextAnnotation": {"text": ""}}]}))):
                    self.post([event])
        self.assertTrue(self.reply.call_args.kwargs["messages"][0].text.strip())
        self.assertEqual(self.events, [])

    def test_empty_translation_response_is_reported_as_invalid(self):
        with patch.object(requests, "get", return_value=Mock(status_code=200,
                json=Mock(return_value={"status": 200, "result": {"text": ""}}))):
            result = self.util.translate("non-empty synthetic input", "en")
        self.assertTrue(result)
        self.assertEqual(len(self.events), 1)

    def test_places_timeout_connection_and_malformed_json_each_report_once(self):
        for error in (requests.Timeout("SYNTHETIC_PRIVATE"),
                      requests.ConnectionError("SYNTHETIC_PRIVATE"),
                      requests.exceptions.JSONDecodeError("synthetic", "SYNTHETIC_PRIVATE", 0)):
            with self.subTest(error=type(error).__name__):
                self.events.clear()
                with patch.object(requests, "get", side_effect=error):
                    self.assertEqual(self.post([self.location_event()]).status_code, 200)
                self.assertEqual(len(self.events), 1)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_bad_api_payload_shapes_are_caught_without_leaking_data(self):
        for payload in (None, [], "SYNTHETIC_PRIVATE", {"status": "OK"},
                        {"status": "OK", "results": None}):
            with self.subTest(payload_type=type(payload).__name__):
                self.events.clear()
                with patch.object(requests, "get", return_value=Mock(status_code=200,
                        json=Mock(return_value=payload))):
                    self.assertEqual(self.post([self.location_event()]).status_code, 200)
                self.assertEqual(len(self.events), 1)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_database_read_failure_does_not_trigger_more_database_calls(self):
        with patch.object(self.db, "get_login_user_document", side_effect=RuntimeError("SYNTHETIC_PRIVATE")) as get:
            self.assertEqual(self.post([self.text_event()]).status_code, 200)
        get.assert_called_once()
        self.reply.assert_called_once()
        self.assertEqual(len(self.events), 1)

    def test_database_write_failure_is_reported_and_replied_to(self):
        document = Mock()
        document.get.return_value.to_dict.return_value = None
        document.set.side_effect = RuntimeError("SYNTHETIC_PRIVATE")
        event = {"type": "postback", "replyToken": "synthetic", "timestamp": 1,
                 "source": {"type": "user", "userId": "synthetic"},
                 "postback": {"data": "言語::English::en"}}
        with patch.object(self.db, "get_document_reference", return_value=document):
            self.assertEqual(self.post([event]).status_code, 200)
        self.assertEqual(len(self.events), 1)
        self.reply.assert_called_once()

    def test_handled_failure_does_not_prevent_the_next_event(self):
        real_handler = self.line.handle_text_message
        count = 0

        def handler(event):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("synthetic")
            return real_handler(event)

        with patch.object(self.line, "handle_text_message", side_effect=handler):
            self.assertEqual(self.post([self.text_event(), self.text_event()]).status_code, 200)
        self.assertEqual(self.reply.call_count, 2)
        self.assertEqual(len(self.events), 1)

    def test_simultaneous_processing_and_reply_failure_keeps_both_errors(self):
        with patch.object(self.line, "handle_text_message", side_effect=ValueError("SYNTHETIC_PRIVATE")):
            self.reply.side_effect = requests.Timeout("SYNTHETIC_PRIVATE")
            self.assertEqual(self.post([self.text_event()]).status_code, 500)
        self.assertEqual(len(self.events), 2)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_real_line_sdk_serializes_reply_and_has_a_timeout(self):
        api = LineBotApi("synthetic-token")
        with patch.object(self.main.env, "LINE_BOT_API", api):
            with patch.object(requests, "post", return_value=Mock(status_code=200,
                    headers={}, json=Mock(return_value={}))) as post:
                self.assertEqual(self.post([self.text_event()]).status_code, 200)
        sent = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(len(sent["messages"]), 2)
        self.assertEqual(sent["replyToken"], "synthetic-reply-token")
        self.assertEqual(post.call_args.kwargs["timeout"], 5)
        self.assertEqual(self.events, [])

    def test_real_line_api_error_response_is_filtered(self):
        api = LineBotApi("synthetic-token")
        response = Mock(status_code=429, headers={"x-line-request-id": "SYNTHETIC_PRIVATE"},
                        json=Mock(return_value={"message": "SYNTHETIC_PRIVATE"}))
        with patch.object(self.main.env, "LINE_BOT_API", api):
            with patch.object(requests, "post", return_value=response):
                self.assertEqual(self.post([self.text_event()]).status_code, 500)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["exception"]["values"][-1]["type"], "LineBotApiError")
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_video_audio_sticker_and_settings_menu_remain_quiet(self):
        messages = [{"type": "video", "id": "1", "duration": 1},
                    {"type": "audio", "id": "1", "duration": 1},
                    {"type": "sticker", "id": "1", "packageId": "1", "stickerId": "1"}]
        for message in messages:
            event = self.text_event()
            event["message"] = message
            self.assertEqual(self.post([event]).status_code, 200)
        for data in ["setting::言語,指定位置からのコンビニ検索範囲", "subsetting::言語::English:en,日本語:ja"]:
            event = {"type": "postback", "replyToken": "synthetic", "timestamp": 1,
                     "source": {"type": "user", "userId": "synthetic"}, "postback": {"data": data}}
            self.assertEqual(self.post([event]).status_code, 200)
        self.assertEqual(self.reply.call_count, 5)
        self.assertEqual(self.events, [])

    def test_missing_api_settings_are_reported_without_network(self):
        with patch.object(self.main.env, "GOOGLE_API_KEY", None):
            self.ocr.detect_words("synthetic", "synthetic")
        with patch.object(self.main.env, "GAS_TRANSLATE_ENDPOINT", None):
            self.util.translate("synthetic", "en")
        self.assertEqual(len(self.events), 2)
        self.assertTrue(all(e["tags"]["failure"] == "configuration" for e in self.events))

    def test_signed_malformed_webhooks_are_reported_without_body_contents(self):
        for body in ['{"SYNTHETIC_PRIVATE":', '{}', '{"events":null}']:
            with self.subTest(body_shape=body[:10]):
                self.events.clear()
                self.assertEqual(self.post_body(body).status_code, 500)
                self.assertEqual(len(self.events), 1)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))
        self.reply.assert_not_called()

    def test_api_json_decode_failure_is_captured_at_response_parsing(self):
        response = Mock(status_code=200, json=Mock(side_effect=
            requests.exceptions.JSONDecodeError("synthetic", "SYNTHETIC_PRIVATE", 0)))
        with patch.object(requests, "get", return_value=response):
            self.assertEqual(self.post([self.location_event()]).status_code, 200)
        response.json.assert_called_once()
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))

    def test_ocr_transport_failure_sends_fallback_and_no_private_image(self):
        event = self.text_event()
        event["message"] = {"type": "image", "id": "1"}
        with patch.object(self.main.env.LINE_BOT_API, "get_message_content", return_value=Mock(content=b"SYNTHETIC_PRIVATE")):
            with patch.object(requests, "post", side_effect=requests.Timeout("SYNTHETIC_PRIVATE")):
                self.assertEqual(self.post([event]).status_code, 200)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.events))
        self.reply.assert_called_once()

    def test_invalid_postback_does_not_write_to_database(self):
        event = {"type": "postback", "replyToken": "synthetic", "timestamp": 1,
                 "source": {"type": "user", "userId": "synthetic"},
                 "postback": {"data": "言語::"}}
        with patch.object(self.db, "get_document_reference", return_value=Mock()) as reference:
            with patch.object(self.db, "upsert") as upsert:
                self.assertEqual(self.post([event]).status_code, 200)
                upsert.assert_not_called()
        self.assertEqual(len(self.events), 1)

    def test_reply_failure_returns_500_without_implicitly_retrying_batch(self):
        self.reply.side_effect = requests.Timeout("synthetic")
        self.assertEqual(self.post([self.text_event(), self.text_event()]).status_code, 500)
        self.reply.assert_called_once()
        self.assertEqual(len(self.events), 1)

    def test_ocr_long_text_is_truncated_before_line_reply(self):
        with patch.object(self.ocr, "__translate_by_user_language", return_value="字" * 2001):
            with patch.object(requests, "post", return_value=Mock(status_code=200,
                    json=Mock(return_value={"responses": [{"fullTextAnnotation": {"text": "synthetic"}}]}))):
                text = self.ocr.detect_words("synthetic", "synthetic")
        self.assertEqual(len(text), 2000)
        self.assertTrue(text.endswith("..."))
        self.assertEqual(self.events, [])

    def test_saved_search_range_is_applied_to_places_request(self):
        for selection, meters in [(1, 300), (2, 500), (3, 1000), (4, 2000), (5, 3000)]:
            with self.subTest(selection=selection):
                with patch.object(self.db, "get_login_user_document", return_value={
                        "language": "ja", "restaurant_range": selection}):
                    with patch.object(requests, "get", return_value=Mock(status_code=200,
                            json=Mock(return_value={"status": "ZERO_RESULTS", "results": []}))) as get:
                        self.post([self.location_event()])
                self.assertEqual(get.call_args.kwargs["params"]["radius"], meters)
