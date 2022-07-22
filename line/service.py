"""
process for line
create text, carousel, quick message
receive text, location, image messsage
"""

from const import env, message
from util import util
from store import service as store_service
from ocr import service as ocr_service
from database import service as db_service

import copy
import base64
from io import BytesIO
from linebot.models import (
    MessageEvent, TextMessage, LocationMessage, ImageMessage,
    StickerMessage, PostbackEvent, VideoMessage, AudioMessage,
    TextSendMessage, StickerSendMessage,
    QuickReplyButton, QuickReply,
    URITemplateAction, MessageAction, PostbackAction,
    CameraAction, CameraRollAction, LocationAction
)

#reply message in LINE
def __reply_message(event, request_message):
    env.LINE_BOT_API.reply_message(
        event.reply_token,
        messages=request_message
    )

"""
create quick access list for 「コンビニ検索」「撮って翻訳」「選択して翻訳」
"""
def __create_quickreply(user_id):
    quick_reply_list = []
    quick_access_menu_list = copy.deepcopy(message.QUICK_ACCESS_TOP_MENUS)
    for quick_access_menu in quick_access_menu_list:
        # translate quick access label to the login user's language
        translated_label = util.translate_if_not_default_language(quick_access_menu.label, user_id)
        # TODO:label must be within 20 charcters
        quick_access_menu.label = translated_label[:20]
        quick_reply_list.append(
            QuickReplyButton(action=quick_access_menu),
        )

    # append setting button at last
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
create setting options for 「言語」（language）「指定位置からのコンビニ検索範囲」（range for searching restaurant）
@param setting_data -> 設定項目のリスト
"""
def __create_subsetting_list(setting_data, user_id):
    setting_menu_list = setting_data.split(",")
    postback_data_list = {
        setting_menu_list[0]:message.LANGUAGES,
        setting_menu_list[1]:message.RANGE,
    }
    # settingで何を選んだのかわかるようにdataに設定項目名(言語、検索範囲)も入れるために、
    # postback_data_listのキーを取得
    key_value_list = postback_data_list.items()
    # 連想配列からキーを取得したときのデータ型がdict_keysになっており、
    # dict_keysでは要素番号を指定して値を取得できないため、要素番号を指定可能なデータ型listに変換
    key_value_list = list(key_value_list)
    subsetting_postback_quickbuttons = []
    # 設定項目分だけループ(設定項目：「言語」「コンビニ検索範囲」など)
    for setting_menu_index in range(len(setting_menu_list)):
        # 「{"日本語":"ja", "英語":"en"}」(連想配列)を「["日本語":"ja","英語":"en"]」(リスト))に変換
        # postbackのdataには文字列しかいれられず、連想配列から直接文字列変換は不明なため、
        # 連想配列をいったんリスト(setting_contents)に変換し、リストをjoinすることで連想配列を文字列に変換する
        setting_contents = [f"{key}:{value}" for (key, value) in key_value_list[setting_menu_index][1].items()]
        subsetting_postback_quickbuttons.append(
            QuickReplyButton(action=PostbackAction(
                # TODO:labelは20文字以内でないといけない
                label=util.translate_if_not_default_language(setting_menu_list[setting_menu_index], user_id)[:20],
                data="subsetting" + message.SPLITTER + key_value_list[setting_menu_index][0] + message.SPLITTER
                + ",".join(setting_contents)
            ))
        )

    return subsetting_postback_quickbuttons

"""
create setting options for language list or range distance lists
「<各言語>」（each language）または「<距離>km」（range）
"""
def __create_detail_setting_list(setting_type, detail_setting):
    detail_setting_list = []
    for details in detail_setting.split(","):
        detail_setting_list.append(
            QuickReplyButton(action=PostbackAction(
                # detailsの各要素値の例：「"日本語":"ja"」「"0.3km":1」
                label=details.split(":")[0],
                data=setting_type + message.SPLITTER + details.split(":")[0] + message.SPLITTER + details.split(":")[1]
            ))
        )
    return detail_setting_list

"""
handler for postback event
"""
def handle_postback_message(event):
    messages = []
    posted_data = event.postback.data.split(message.SPLITTER)
    user_id = event.source.user_id

    if posted_data[0] == "setting":
        # quick reply for subsetting
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
        # 言語DB更新処理
        # 新規レコード作成時はコンビニ検索範囲は固定値とする
        target_document = db_service.get_document_reference('user_settings', user_id)
        dict_target_document = target_document.get().to_dict()
        if dict_target_document is None:
            restaurant_range = 2
        else:
            restaurant_range = dict_target_document['restaurant_range']

        # 更新処理
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
        # 検索範囲DB更新処理
        # 新規レコード作成時は言語は固定値とする
        target_document = db_service.get_document_reference('user_settings', user_id)
        dict_target_document = target_document.get().to_dict()
        if dict_target_document is None:
            language = 'ja'
        else:
            language = dict_target_document['language']

        # 更新処理
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

"""
handler for location message event
"""
def handle_location_message(event):
    store_instance = store_service.ConvenienceStoreService(event.source.user_id)
    store_results = store_instance.search_convenience_store(
        event.message.latitude,
        event.message.longitude
    )
    messages = [* store_results]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

"""
handler for sticker message event
"""
def handle_sticker_message(event):
    messages = [StickerSendMessage(
        package_id=event.message.package_id,
        sticker_id=event.message.sticker_id
    )]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

"""
handler for image message event
"""
def handle_image_message(event):
    #get image data(binary) by message id
    image_content = env.LINE_BOT_API.get_message_content(event.message.id)
    binary = BytesIO(image_content.content)
    base64_encoded_image = base64.encodebytes(binary.getvalue()).decode("utf-8")
    user_id = event.source.user_id
    detected_text = ocr_service.detect_words(base64_encoded_image, user_id)
    messages = [TextSendMessage(text=detected_text)]
    messages.append(__create_quickreply(user_id))
    return messages

"""
handler for text message event
"""
def handle_text_message(event):
    message_text = util.translate_if_not_default_language(message.REMIND_MESSAGE, event.source.user_id)
    messages = [TextSendMessage(text=message_text)]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

"""
handler for video message event
"""
def handle_video_message(event):
    message_text = util.translate_if_not_default_language("良い動画だね\n" + message.REMIND_MESSAGE, event.source.user_id)
    messages = [TextSendMessage(text=message_text)]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

"""
handler for audio message event
"""
def handle_audio_message(event):
    message_text = util.translate_if_not_default_language("良い声してるね\n" + message.REMIND_MESSAGE, event.source.user_id)
    messages = [TextSendMessage(text=message_text)]
    messages.append(__create_quickreply(event.source.user_id))
    return messages

"""
handler all event from main.py
"""
def call_message_handler(event):
    # TODO:delete after debug
    print(event)
    print(str(event.timestamp) + ":" + event.source.user_id)
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
        else:
            print("method is not yet prepared")
            # TODO:delete after debug
            print(message_type)
    except Exception as error:
        # TODO:delete after debug
        print(util.handle_failure(error))
        error_message = message.ERROR_MESSAGE("api_error")
        user_id = event.source.user_id
        messages = [TextSendMessage(text=util.translate_if_not_default_language(error_message, user_id))]
        messages.append(__create_quickreply(event.source.user_id))
    finally:
        if len(messages) != 0:
            __reply_message(event, messages)
