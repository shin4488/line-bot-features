"""Real Gunicorn + real Sentry HTTP transport, confined to loopback and fake data."""
import base64
import gzip
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import requests
from sentry_sdk.envelope import Envelope

import monitoring
from tests.support import ENVIRONMENT


class GunicornTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.received = queue.Queue()
        cls.collector_status = 200

        class Collector(BaseHTTPRequestHandler):
            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                if self.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                cls.received.put(data)
                self.send_response(cls.collector_status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        cls.collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
        cls.addClassCleanup(cls.collector.server_close)
        thread = threading.Thread(target=cls.collector.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(cls.collector.shutdown)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            app_port = reservation.getsockname()[1]
        cls.base_url = "http://127.0.0.1:" + str(app_port)
        cls.logs = tempfile.TemporaryFile()
        cls.addClassCleanup(cls.logs.close)
        env = {"SENTRY_DSN": f"http://synthetic@127.0.0.1:{cls.collector.server_port}/1",
               "SENTRY_ENVIRONMENT": "local-integration", "RENDER_GIT_COMMIT": "b" * 40,
               "PYTHONUNBUFFERED": "1"}
        cls.process = subprocess.Popen([
            sys.executable, "-m", "gunicorn", "tests.gunicorn_fixture:app",
            "--bind", "127.0.0.1:" + str(app_port), "--workers", "1",
            "--timeout", "3", "--graceful-timeout", "2"],
            env=env, stdout=cls.logs, stderr=cls.logs)

        def stop():
            cls.process.terminate()
            try:
                cls.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=3)

        cls.addClassCleanup(stop)
        cls.http = requests.Session()
        cls.http.trust_env = False
        cls.addClassCleanup(cls.http.close)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                break
            try:
                if cls.http.get(cls.base_url + "/callback", timeout=0.2).status_code == 405:
                    return
            except requests.RequestException:
                time.sleep(0.05)
        cls.logs.seek(0)
        raise AssertionError("Gunicorn did not start: " + cls.logs.read().decode()[-4000:])

    def setUp(self):
        self.__class__.collector_status = 200
        while not self.received.empty():
            self.received.get_nowait()

    def signed_post(self, body):
        signature = base64.b64encode(hmac.new(ENVIRONMENT["LINE_CHANNEL_SECRET"].encode(),
            body.encode(), hashlib.sha256).digest()).decode()
        return self.http.post(self.base_url + "/callback", data=body,
            headers={"X-Line-Signature": signature, "Content-Type": "application/json"}, timeout=5)

    def get_event(self):
        data = self.received.get(timeout=5)
        envelope = Envelope.deserialize(data)
        items = [item for item in envelope.items if item.headers["type"] == "event"]
        self.assertEqual(len(items), 1)
        self.assertNotIn(b"SYNTHETIC_PRIVATE", data)
        return items[0].payload.json

    def test_real_http_envelope_contains_only_sanitized_error(self):
        response = self.http.get(self.base_url + "/test/error?private=SYNTHETIC_PRIVATE",
            headers={"Authorization": "SYNTHETIC_PRIVATE", "Cookie": "test=SYNTHETIC_PRIVATE"}, timeout=5)
        self.assertEqual(response.status_code, 500)
        self.http.get(self.base_url + "/test/flush", timeout=5)
        event = self.get_event()
        self.assertEqual(event["environment"], "local-integration")
        self.assertEqual(event["release"], monitoring.REPOSITORY + "@" + "b" * 40)
        self.assertEqual(event["exception"]["values"][-1]["type"], "RuntimeError")
        self.assertTrue(self.received.empty())

    def test_real_server_valid_and_invalid_webhooks_are_quiet(self):
        self.assertEqual(self.signed_post('{"events":[]}').status_code, 200)
        self.assertEqual(self.http.post(self.base_url + "/callback", data="invalid", timeout=5).status_code, 400)
        self.http.get(self.base_url + "/test/flush", timeout=5)
        self.assertTrue(self.received.empty())

    def test_sentry_unavailable_does_not_block_webhooks(self):
        self.__class__.collector_status = 503
        self.assertEqual(self.http.get(self.base_url + "/test/error", timeout=5).status_code, 500)
        started = time.monotonic()
        self.assertEqual(self.signed_post('{"events":[]}').status_code, 200)
        self.assertLess(time.monotonic() - started, 2)
        self.http.get(self.base_url + "/test/flush", timeout=5)

    def test_worker_timeout_is_reported_and_worker_recovers(self):
        try:
            self.http.get(self.base_url + "/test/slow", timeout=8)
        except requests.RequestException:
            pass  # Gunicorn may close the connection instead of returning HTTP 500.
        event = self.get_event()
        exception = event["exception"]["values"][-1]
        self.assertEqual(exception["type"], "SystemExit")
        self.assertIn("handle_abort", [frame.get("function") for frame in exception["stacktrace"]["frames"]])
        self.assertEqual(self.signed_post('{"events":[]}').status_code, 200)
