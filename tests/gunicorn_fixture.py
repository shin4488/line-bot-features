"""Local integration-test application. Never use as a deployment entry point."""
import os
import sys
import time
import types
from unittest.mock import Mock

from tests.support import ENVIRONMENT

os.environ.update(ENVIRONMENT)
database = types.ModuleType("const.database")
database.FIRESTORE_DB = Mock()
sys.modules["const.database"] = database

import main
import monitoring
from database import service as db_service
from flask import request

app = main.app
db_service.get_login_user_document = lambda user: {"language": "ja", "restaurant_range": 2}
main.env.LINE_BOT_API.reply_message = lambda *args, **kwargs: None


@app.route("/test/error")
def synthetic_error():
    raise RuntimeError(request.args.get("private", "synthetic"))


@app.route("/test/flush")
def flush():
    monitoring.flush()
    return "OK"


@app.route("/test/slow")
def slow():
    time.sleep(15)
    return "OK"
