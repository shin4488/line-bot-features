"""
OCR process by using Google OCR Web API
"""

from const import env, message
from util import util
from database import service as db_service

import json
import requests
import monitoring

"""
detect text from image sent to the bot using google vision api
"""
def detect_words(base64_encoded_image, user_id):
    if env.GOOGLE_API_KEY is None:
        monitoring.report_api_failure("vision", "configuration")
        error_msg = message.ERROR_MESSAGE('api_error')
        error_msg = util.translate_if_not_default_language(error_msg, user_id)
        return error_msg

    endpoint = 'https://vision.googleapis.com/v1/images:annotate?key=' + env.GOOGLE_API_KEY
    header = {'Content-Type':'application/json'}
    payload = {'requests':[{'image':{'content':base64_encoded_image}, 'features':[{'type':'TEXT_DETECTION'}]}]}
    text_detection_res = requests.post(endpoint, data=json.dumps(payload), headers=header, timeout=monitoring.HTTP_TIMEOUT)

    if text_detection_res.status_code != 200:
        monitoring.report_api_failure("vision", "http", text_detection_res.status_code)
        target_text = message.ERROR_MESSAGE(2200)
        return __translate_by_user_language(target_text, user_id)

    text_detection_result = text_detection_res.json()
    responses = text_detection_result.get("responses")
    if not isinstance(responses, list) or not responses:
        monitoring.report_api_failure("vision", "response")
        return __translate_by_user_language(message.ERROR_MESSAGE(2200), user_id)

    target_text = message.ERROR_MESSAGE(2100)
    for res_content in responses:
        if "error" in res_content:
            monitoring.report_api_failure("vision", "api")
            return __translate_by_user_language(message.ERROR_MESSAGE(2200), user_id)
        if "fullTextAnnotation" in res_content:
            target_text = res_content["fullTextAnnotation"]["text"].replace("\n", " ")

    translated_text = __translate_by_user_language(target_text, user_id)
    if len(translated_text) > 2000:
        translated_text = translated_text[:1997] + '...'

    return translated_text

def __translate_by_user_language(text, user_id):
    dict_login_user_document = db_service.get_login_user_document(user_id)
    output_language = dict_login_user_document['language']
    return util.translate(text, output_language)
