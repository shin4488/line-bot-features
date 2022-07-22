"""
util methods for entire app
"""

from const import env, message
from database import service as db_service
import sys
import requests

"""
return translated text if user language is not app default language
return param text if user language is app default language
"""
def translate_if_not_default_language(text, user_id):
    dict_login_user_document = db_service.get_login_user_document(user_id)
    output_language = dict_login_user_document['language']
    if output_language == message.DEFAULT_LANGUAGE:
        return text

    return translate(text, output_language)

"""
translation from parameter text by parameter language
"""
def translate(text, output_language):
    if env.GAS_TRANSLATE_ENDPOINT is None:
        return message.ERROR_MESSAGE('translation_error')

    #text - text that you want to translate, target - the language that you want to translate
    #no need the language of the raw text, possible to detect the language automatically
    parameter = {'text':text, 'target':output_language}
    response = requests.get(env.GAS_TRANSLATE_ENDPOINT, params=parameter)

    #the form of returned value is {result:{text:(translated text), target:(translated language)}, status:status_code}
    if response.status_code != 200 or response.json().get('status') != 200:
        return message.ERROR_MESSAGE('translation_error')

    result = response.json().get('result')
    translated_text = result['text']
    return translated_text

"""
get error info
"""
def handle_failure(e):
    exc_type, exc_obj, tb=sys.exc_info()
    lineno=tb.tb_lineno
    return str(lineno) + ':' + str(type(e)) + '\n' + str(e)
