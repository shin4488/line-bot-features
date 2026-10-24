"""
Reply texts, menu actions and setting options.
"""

from linebot.models import (
    LocationAction, CameraAction, CameraRollAction
)

# Separates the fields of postback data.
SPLITTER = '::'
# Usage guide sent in reply to text, video and audio messages.
REMIND_MESSAGE = '位置情報を送信すると、\n近くのコンビニを検索するよ\n画像を送ると、画像の中の文字を日本語に翻訳するよ'

# The numeric keys only identify messages. They are not the status codes returned by the APIs.
def ERROR_MESSAGE(error_code):
    __ERROR_MESSAGE_LIST = {
        400: '結果を取得できませんでした',
        404: '検索条件にあう店舗がありません',
        2100: '画像読み取りに失敗しました\n別の画像を送ってください',
        2200: '画像読み取りに失敗しました\nもう一度画像を送るか、別の画像を送ってください',
        'translation_error': 'Translation error...',
        'api_error': 'サーバエラーです\n開発者にお問い合わせください\nwfshinya48@gmail.com'
    }
    return __ERROR_MESSAGE_LIST[error_code]

# Each name is also posted back to identify the setting to save, so it must match the names compared in handle_postback_message.
# Keep language first and search range second, because their option lists are assigned by position.
SETTING_LIST = [
    '言語',
    '指定位置からのコンビニ検索範囲',
]

# top menus excluding setting
QUICK_ACCESS_TOP_MENUS = [
    LocationAction(label='トイレ付きコンビニ検索'),
    CameraAction(label='撮って翻訳'),
    CameraRollAction(label='選択して翻訳'),
]

LANGUAGES = {
    '日本語': 'ja',
    'English': 'en',
    'Espanol': 'es',
    'العربية': 'ar',
    'Français': 'fr',
    '中文': 'zh',
    '한국': 'ko',
    'Melayu': 'ms',
    'Kiswahili': 'sw',
    'اردو': 'ur',
    'Tagalog': 'tl',
}

DEFAULT_LANGUAGE = LANGUAGES['日本語']

RANGE = {
    '0.3km': '1',
    '0.5km': '2',
    '1km': '3',
    '2km': '4',
    '3km': '5',
}
