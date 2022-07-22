"""
const message
"""

from linebot.models import (
    LocationAction, CameraAction, CameraRollAction
)

#str that is used for identifying the postback data type
SPLITTER = '::'
# bot message for invalid message from user
REMIND_MESSAGE = '位置情報を送信すると、\n近くのコンビニを検索するよ\n画像を送ると、画像の中の文字を日本語に翻訳するよ'

#return error message according to api response status code
def ERROR_MESSAGE(error_code):
    __ERROR_MESSAGE_LIST = {
        400: '結果を取得できませんでした',
        401: '結果を取得できませんでした\n申し訳ございませんが開発者にお問い合わせくださいwfshinya48@gmail.com',
        404: '検索条件にあう店舗がありません',
        405: '不正なアクセスを検出しました',
        429: '大変申し訳ございません\n今日はこれ以上検索できません\n明日またお会いできることを楽しみにしています',
        500: '申し訳ございません、もう1度試してみてください\n良くならない時は開発者に問い合わせてみてくださいwfshinya48@gmail.com',
        1404: '申し訳ございません。画像の中に翻訳できないコンテンツが含まれています\nもう一度画像を送るか、別の画像を送ってください',
        2100: '画像読み取りに失敗しました\n別の画像を送ってください',
        2200: '画像読み取りに失敗しました\nもう一度画像を送るか、別の画像を送ってください',
        'translation_error': 'Translation error...',
        'api_error': 'サーバエラーです\n開発者にお問い合わせください\nwfshinya48@gmail.com'
    }
    return __ERROR_MESSAGE_LIST[error_code]

SETTING_LIST = [
    '言語',
    '指定位置からのコンビニ検索範囲',
]

# top menus excluding setting
QUICK_ACCESS_TOP_MENUS = [
    LocationAction(label='コンビニ検索'),
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
