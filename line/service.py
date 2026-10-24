"""
Handle LINE webhook events and build the reply messages.
"""

from const import env, message
from util import util
from store import service as store_service
from ocr import service as ocr_service
from database import service as db_service

import copy
import monitoring
import base64
from io import BytesIO
from linebot.models import (
    TextSendMessage, StickerSendMessage,
    QuickReplyButton, QuickReply, PostbackAction,
)

def __reply_message(event, request_message):
    env.LINE_BOT_API.reply_message(
        event.reply_token,
        messages=request_message
    )

def __create_quickreply(user_id):
    quick_reply_list = []
    # Labels are replaced with each user's translation, so copy the shared actions first.
    quick_access_menu_list = copy.deepcopy(message.QUICK_ACCESS_TOP_MENUS)
    for quick_access_menu in quick_access_menu_list:
        translated_label = util.translate_if_not_default_language(quick_access_menu.label, user_id)
        # A translated label can exceed LINE's 20-character limit for action labels.
        quick_access_menu.label = translated_label[:20]
        quick_reply_list.append(
            QuickReplyButton(action=quick_access_menu),
        )

    quick_reply_list.append(
        QuickReplyButton(action=PostbackAction(
            label="Setting", data="setting" + message.SPLITTER + ",".join(message.SETTING_LIST)
        )),
    )
    return TextSendMessage(
        text=util.translate_if_not_default_language("メニューからお選びください", user_id),
        quick_reply=QuickReply(items=quick_reply_list)
    )

"""
Build one quick reply button per setting in setting_data, the comma-separated names from message.SETTING_LIST. Each button posts back "subsetting::<setting name>::<label>:<value>,...", from which handle_postback_message builds the option buttons.
"""
def __create_subsetting_list(setting_data, user_id):
    setting_menu_list = setting_data.split(",")
    postback_data_list = {
        setting_menu_list[0]:message.LANGUAGES,
        setting_menu_list[1]:message.RANGE,
    }
    key_value_list = postback_data_list.items()
    key_value_list = list(key_value_list)
    subsetting_postback_quickbuttons = []
    for setting_menu_index in range(len(setting_menu_list)):
        # postbackのdataは文字列なので、選択肢を「表示名:値」のカンマ区切りにして渡す。
        setting_contents = [f"{key}:{value}" for (key, value) in key_value_list[setting_menu_index][1].items()]
        subsetting_postback_quickbuttons.append(
            QuickReplyButton(action=PostbackAction(
                # 翻訳後のラベルが、LINEのアクションラベルの上限20文字を超えることがある。
                label=util.translate_if_not_default_language(setting_menu_list[setting_menu_index], user_id)[:20],
                # 次のpostbackでどの設定項目が選ばれたかわかるよう、dataに設定項目名も入れる。
                data="subsetting" + message.SPLITTER + key_value_list[setting_menu_index][0] + message.SPLITTER
                + ",".join(setting_contents)
            ))
        )

    return subsetting_postback_quickbuttons

"""
Build one quick reply button per option. Each button posts back "<setting name>::<label>::<value>", which handle_postback_message uses to save the setting.
"""
def __create_detail_setting_list(setting_type, detail_setting):
    detail_setting_list = []
    for details in detail_setting.split(","):
        detail_setting_list.append(
            QuickReplyButton(action=PostbackAction(
                # detailsの例: 「日本語:ja」「0.3km:1」
                label=details.split(":")[0],
                data=setting_type + message.SPLITTER + details.split(":")[0] + message.SPLITTER + details.split(":")[1]
            ))
        )
    return detail_setting_list

def handle_postback_message(event):
    messages = []
    posted_data = event.postback.data.split(message.SPLITTER)
    user_id = event.source.user_id

    if posted_data[0] == "setting":
        message_text = util.translate_if_not_default_language("変更する設定を選んでください", user_id)
        messages.append(TextSendMessage(
            text=message_text,
            quick_reply=QuickReply(items=__create_subsetting_list(posted_data[1], user_id))
        ))

    elif posted_data[0] == "subsetting":
        message_text = util.translate_if_not_default_language(posted_data[1] + "を選んでください", user_id)
        messages.append(TextSendMessage(
            text=message_text,
            quick_reply=QuickReply(items=__create_detail_setting_list(posted_data[1], posted_data[2]))
        ))

    elif posted_data[0] == "言語":
        # 設定がまだないユーザーは、検索範囲を初期値の2（0.5km）で保存する。
        target_document = db_service.get_document_reference('user_settings', user_id)
        dict_target_document = target_document.get().to_dict()
        if dict_target_document is None:
            restaurant_range = 2
        else:
            restaurant_range = dict_target_document['restaurant_range']

        language = posted_data[2]
        data = {
            'user_id': user_id,
            'language': language,
            'restaurant_range': restaurant_range
        }
        db_service.upsert(target_document, data)
        message_text = util.translate_if_not_default_language(posted_data[0] + "を" + posted_data[1] + "に設定しました", user_id)
        messages.append(TextSendMessage(text=message_text))
        messages.append(__create_quickreply(user_id))

    elif posted_data[0] == "指定位置からのコンビニ検索範囲":
        # 設定がまだないユーザーは、言語を初期値の日本語で保存する。
        target_document = db_service.get_document_reference('user_settings', user_id)
        dict_target_document = target_document.get().to_dict()
        if dict_target_document is None:
            language = 'ja'
        else:
            language = dict_target_document['language']

        restaurant_range = int(posted_data[2])
        data = {
            'user_id': user_id,
            'language': language,
            'restaurant_range': restaurant_range
        }
        db_service.upsert(target_document, data)
        message_text = util.translate_if_not_default_language(posted_data[0] + "を" + posted_data[1] + "に設定しました", user_id)
        messages.append(TextSendMessage(text=message_text))
        messages.append(__create_quickreply(user_id))
    return messages

def handle_location_message(event):
    store_instance = store_service.ConvenienceStoreService(event.source.user_id)
    store_results = store_instance.search_convenience_store(
        event.message.latitude,
        event.message.longitude
    )
    messages = [* store_results]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

def handle_sticker_message(event):
    messages = [StickerSendMessage(
        package_id=event.message.package_id,
        sticker_id=event.message.sticker_id
    )]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

def handle_image_message(event):
    image_content = env.LINE_BOT_API.get_message_content(event.message.id)
    binary = BytesIO(image_content.content)
    base64_encoded_image = base64.encodebytes(binary.getvalue()).decode("utf-8")
    user_id = event.source.user_id
    detected_text = ocr_service.detect_words(base64_encoded_image, user_id)
    messages = [TextSendMessage(text=detected_text)]
    messages.append(__create_quickreply(user_id))
    return messages

def handle_text_message(event):
    message_text = util.translate_if_not_default_language(message.REMIND_MESSAGE, event.source.user_id)
    messages = [TextSendMessage(text=message_text)]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

def handle_video_message(event):
    message_text = util.translate_if_not_default_language("良い動画だね\n" + message.REMIND_MESSAGE, event.source.user_id)
    messages = [TextSendMessage(text=message_text)]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

def handle_audio_message(event):
    message_text = util.translate_if_not_default_language("良い声してるね\n" + message.REMIND_MESSAGE, event.source.user_id)
    messages = [TextSendMessage(text=message_text)]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

def call_message_handler(event):
    messages = []
    try:
        if event.type == "postback":
            messages = handle_postback_message(event)
            return

        message_type = event.message.type
        if message_type == "location":
            messages = handle_location_message(event)
        elif message_type == "text":
            messages = handle_text_message(event)
        elif message_type == "image":
            messages = handle_image_message(event)
        elif message_type == "video":
            messages = handle_video_message(event)
        elif message_type == "audio":
            messages = handle_audio_message(event)
        elif message_type == "sticker":
            messages = handle_sticker_message(event)
    except Exception as error:
        monitoring.capture_exception(error)
        # The failure may come from Firestore or the translation API itself.
        # Do not call them again while building the error reply; send a static message instead.
        messages = [TextSendMessage(text=message.ERROR_MESSAGE("api_error"))]
    finally:
        if len(messages) != 0:
            __reply_message(event, messages)
