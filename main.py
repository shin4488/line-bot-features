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

from const import env
from line import service as line_service

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
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

#fired when post back(click button in carousel)
@handler.add(PostbackEvent)
#fired when location info is sent
@handler.add(MessageEvent, message=LocationMessage)
#fired when text message is sent
@handler.add(MessageEvent, message=TextMessage)
#fired when text image is sent
@handler.add(MessageEvent, message=ImageMessage)
#fired when text video is sent
@handler.add(MessageEvent, message=VideoMessage)
#fired when text audio is sent
@handler.add(MessageEvent, message=AudioMessage)
#fired when sticker is sent
@handler.add(MessageEvent, message=StickerMessage)
# TODO: file event
def main(event):
    line_service.call_message_handler(event)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=env.PORT)
