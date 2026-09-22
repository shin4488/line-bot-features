# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import monitoring

monitoring.init_monitoring()

try:
    from const import env
    from line import service as line_service
except (Exception, SystemExit) as error:
    # Gunicorn catches import errors before sys.excepthook can report them.
    monitoring.capture_exception(error, operation="startup")
    monitoring.flush()
    raise

from flask import Flask, request, abort
from linebot import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, LocationMessage, ImageMessage,
    StickerMessage, PostbackEvent, VideoMessage, AudioMessage,
)

app = Flask(__name__)
handler = WebhookHandler(env.CHANNEL_SECRET)

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        abort(400)

    # 署名は受信した本文に対するものなので、JSONの解析・再シリアライズをせずSDKへ渡す。
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(PostbackEvent)
@handler.add(MessageEvent, message=LocationMessage)
@handler.add(MessageEvent, message=TextMessage)
@handler.add(MessageEvent, message=ImageMessage)
@handler.add(MessageEvent, message=VideoMessage)
@handler.add(MessageEvent, message=AudioMessage)
@handler.add(MessageEvent, message=StickerMessage)
# TODO: file event
def main(event):
    line_service.call_message_handler(event)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=env.PORT)
