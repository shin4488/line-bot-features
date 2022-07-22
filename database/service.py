"""
database process
"""

from const import database, env, message

def get_login_user_document(user_id):
    target_document = get_document_reference('user_settings', user_id)
    dict_target_document = target_document.get().to_dict()

    # if there is no document yet, make new document
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

    # to upsert, set merge=True
    document.set(escaped_data, merge=True)
    return document

"""
escape query str
"""
def __escape_query(query):
    # escape only string data
    if query is not str:
        return query

    escape_list = ['$', '#', '[', ']', '{', '}', '+', '""', "''"]
    for escape_str in escape_list:
        query = query.replace(escape_str, '')

    return query
