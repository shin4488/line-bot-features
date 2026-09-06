"""Import the real updated libraries in a fresh process, with synthetic credentials."""
import subprocess
import sys
import unittest


class StartupTests(unittest.TestCase):
    def run_script(self, script):
        result = subprocess.run([sys.executable, "-c", script], env={},
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_flask_line_and_firestore_clients_initialize_without_network(self):
        self.run_script('''
import os
import socket
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from tests.support import ENVIRONMENT
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ.update(ENVIRONMENT)
os.environ.update({
    "FIREBASE_PROJECT_ID": "synthetic-project",
    "FIREBASE_PRIVATE_KEY_ID": "synthetic-key-id",
    "FIREBASE_PRIVATE_KEY": key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
    "FIREBASE_CLIENT_EMAIL": "test@synthetic-project.iam.gserviceaccount.com",
    "FIREBASE_TOKEN_URI": "https://oauth.invalid/token",
    "FIRESTORE_EMULATOR_HOST": "127.0.0.1:1",
})
with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
    import main
    from const.database import FIRESTORE_DB
    assert FIRESTORE_DB.project == "synthetic-project"
    assert FIRESTORE_DB.collection("user_settings").document("synthetic").id == "synthetic"
    assert main.app.test_client().get("/callback").status_code == 405
''')

    def test_gunicorn_style_import_configuration_failure_is_reported(self):
        self.run_script('''
from tests.support import start_monitoring
events = start_monitoring()
try:
    import main
except SystemExit as error:
    assert error.code == 1
else:
    raise AssertionError("Missing configuration must stop startup")
assert len(events) == 1, events
assert events[0]["tags"]["operation"] == "startup"
''')
