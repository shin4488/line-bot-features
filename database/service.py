"""
database process
"""

from const import database, env, message

def get_login_user_document(user_id):
    target_document = get_document_reference('user_settings', user_id)
    dict_target_document = target_document.get().to_dict()

    if dict_target_document is None:
        data = {
            'user_id': user_id,
            'language': 'ja',
            'restaurant_range': 2
        }
        target_document = upsert(target_document, data)
        dict_target_document = target_document.get().to_dict()

    return dict_target_document

def get_document_reference(collection_name, document_id):
    target_collection = database.FIRESTORE_DB.collection(collection_name)
    return target_collection.document(document_id)

def upsert(document, data):
    escaped_data = {}
    for key, value in data.items():
        escaped_data[key] = __escape_query(value)

    # 今回の更新に含まれない保存済み設定を消さないよう、ドキュメント全体は置き換えない。
    document.set(escaped_data, merge=True)
    return document

"""
escape query str
"""
def __escape_query(query):
    if query is not str:
        return query

    escape_list = ['$', '#', '[', ']', '{', '}', '+', '""', "''"]
    for escape_str in escape_list:
        query = query.replace(escape_str, '')

    return query
