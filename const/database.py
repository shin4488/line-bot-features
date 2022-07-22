"""
const database
"""

from const import env
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

__SECRET_KEY = {
  'type': 'service_account',
  'project_id': env.FIREBASE_PROJECT_ID,
  'private_key_id': env.FIREBASE_PRIVATE_KEY_ID,
  'private_key': env.FIREBASE_PRIVATE_KEY.replace('\\n', '\n'),
  'client_email': env.FIREBASE_CLIENT_EMAIL,
  'client_id': env.FIREBASE_CLIENT_ID,
  'auth_uri': env.FIREBASE_AUTH_URI,
  'token_uri': env.FIREBASE_TOKEN_URI,
  'auth_provider_x509_cert_url': env.FIREBASE_AUTH_PROVIDER_X509_CERT_URL,
  'client_x509_cert_url': env.FIREBASE_CLIENT_X509_CERT_URL
}
__CREDENTIAL = credentials.Certificate(__SECRET_KEY)
firebase_admin.initialize_app(__CREDENTIAL, {'projectId': env.FIREBASE_PROJECT_ID})
FIRESTORE_DB = firestore.client()
