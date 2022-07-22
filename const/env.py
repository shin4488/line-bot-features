"""
environmental valiable set for this app
initial __ means privately used const variables
"""

import os
import sys
from linebot import (
    LineBotApi, WebhookHandler
)

# entire app
PORT = int(os.getenv('PORT', 5000))

# LINE
CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', None)
__CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
if CHANNEL_SECRET is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if __CHANNEL_ACCESS_TOKEN is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)
LINE_BOT_API = LineBotApi(__CHANNEL_ACCESS_TOKEN)

# database
FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', None)
FIREBASE_PRIVATE_KEY_ID = os.getenv('FIREBASE_PRIVATE_KEY_ID', None)
FIREBASE_PRIVATE_KEY = os.getenv('FIREBASE_PRIVATE_KEY', None)
FIREBASE_CLIENT_EMAIL = os.getenv('FIREBASE_CLIENT_EMAIL', None)
FIREBASE_CLIENT_ID = os.getenv('FIREBASE_CLIENT_ID', None)
FIREBASE_AUTH_URI = os.getenv('FIREBASE_AUTH_URI', None)
FIREBASE_TOKEN_URI = os.getenv('FIREBASE_TOKEN_URI', None)
FIREBASE_AUTH_PROVIDER_X509_CERT_URL = os.getenv('FIREBASE_AUTH_PROVIDER_X509_CERT_URL', None)
FIREBASE_CLIENT_X509_CERT_URL = os.getenv('FIREBASE_CLIENT_X509_CERT_URL', None)

# api
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', None)
GAS_TRANSLATE_ENDPOINT = os.getenv('GOOGLE_APP_SCRIPTS_ENDPOINT', None)
