"""
util methods for entire app
"""

from const import env, message
from database import service as db_service
import requests
import monitoring

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
        monitoring.report_api_failure("translation", "configuration")
        return message.ERROR_MESSAGE('translation_error')

    #text - text that you want to translate, target - the language that you want to translate
    #no need the language of the raw text, possible to detect the language automatically
    parameter = {'text':text, 'target':output_language}
    response = requests.get(env.GAS_TRANSLATE_ENDPOINT, params=parameter, timeout=monitoring.HTTP_TIMEOUT)

    if response.status_code != 200:
        monitoring.report_api_failure("translation", "http", response.status_code)
        return message.ERROR_MESSAGE('translation_error')

    # Expected response: {result: {text: ..., target: ...}, status: 200}.
    payload = response.json()
    if payload.get('status') != 200:
        monitoring.report_api_failure("translation", "api")
        return message.ERROR_MESSAGE('translation_error')

    result = payload.get('result')
    if (not isinstance(result, dict) or not isinstance(result.get('text'), str)
            or (text.strip() and not result['text'].strip())):
        monitoring.report_api_failure("translation", "response")
        return message.ERROR_MESSAGE('translation_error')
    return result['text']
