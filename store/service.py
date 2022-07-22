
from const import env, message
from util import util
from database import service as db_service

from linebot.models import (
    TextSendMessage, TemplateSendMessage,
    CarouselColumn, CarouselTemplate,
    URIAction,
)
import requests
import urllib.parse

class ConvenienceStoreService():
    __user_id = ''
    __translated_rate_message = ''

    def __init__(self, user_id):
        self.__user_id = user_id
        self.__translated_rate_message = util.translate_if_not_default_language('評価', self.__user_id)

    """
    search convenience store with toilet location, language
    """
    def search_convenience_store(self, latitude, longitude):
        endpoint = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        header = {
            'Content-Type':'application/json'
        }

        dict_login_user_document = db_service.get_login_user_document(self.__user_id)
        output_language = dict_login_user_document['language']
        parameters = {
            'key': env.GOOGLE_API_KEY,
            'radius': 300,
            'type': 'convenience_store',
            'language': output_language,
            'keyword': 'トイレ',
            'location': str(latitude) + ',' + str(longitude)
        }
        store_response = requests.get(endpoint, headers=header, params=parameters)
        store_result_json = store_response.json()

        if store_response.status_code != 200:
            error_message = message.ERROR_MESSAGE(400)
            translated_error_message = util.translate_if_not_default_language(error_message, self.__user_id)
            return [TextSendMessage(text=translated_error_message)]

        store_results = store_result_json['results']
        if len(store_results) == 0:
            error_message = message.ERROR_MESSAGE(404)
            translated_error_message = util.translate_if_not_default_language(error_message, self.__user_id)
            return [TextSendMessage(text=translated_error_message)]

        store_messages = []
        store_count = 0
        for store_result in store_results:
            carouse = self.__create_store_carousel(store_result)
            store_messages.append(carouse)

            store_count += 1
            # line messaging API can handle up to 5 carousels
            if store_count >= 5:
                break

        return [
            TemplateSendMessage(
                alt_text='carousel template',
                template=CarouselTemplate(columns=store_messages)
            )
        ]

    def __create_store_carousel(self, store):
        image_url = store['icon']
        store_name = store['name']
        title = store_name
        if len(title) > 40:
            title = title[:37] + '...'

        open_message = ''
        if store['opening_hours']['open_now']:
            open_message = util.translate_if_not_default_language('営業中', self.__user_id)
        else:
            open_message = util.translate_if_not_default_language('営業時間外', self.__user_id)

        detail_message = open_message + ' ' + \
            self.__translated_rate_message + ': ' + str(store['rating']) + ' / 5'

        location = store['geometry']['location']
        encoded_map_uri = 'https://www.google.co.jp/maps/?q=' + \
            urllib.parse.quote(store_name) + '@' + str(location['lat']) + ',' + str(location['lng'])
        actions = [URIAction(label='Location', uri=encoded_map_uri)]

        return CarouselColumn(
            title=title,
            text=detail_message,
            actions=actions
        )