import os
from dotenv import load_dotenv
from constants import (
    DEFAULT_FIREBASE_PROJECT_ID,
    DEFAULT_FIREBASE_SERVICE_ACCOUNT_PATH,
    DEFAULT_CUSTOMER_CARE_USERNAME,
    SOCIAL_LINKS,
    WELCOME_MESSAGE,
    WELCOME_MESSAGE_REFERRED,
    STEPS,
    LOGGING_CONFIG,
    REFERRAL_CONFIG
)

# Load environment variables
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', DEFAULT_FIREBASE_PROJECT_ID)
FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH', DEFAULT_FIREBASE_SERVICE_ACCOUNT_PATH)
CUSTOMER_CARE_USERNAME = os.getenv('CUSTOMER_CARE_USERNAME', DEFAULT_CUSTOMER_CARE_USERNAME)

# Referral Configuration (Update bot username in production)
REFERRAL_BOT_USERNAME = os.getenv('REFERRAL_BOT_USERNAME', REFERRAL_CONFIG['bot_username'])

# Validate required environment variables
REQUIRED_ENV_VARS = {
    'BOT_TOKEN': BOT_TOKEN,
    'FIREBASE_PROJECT_ID': FIREBASE_PROJECT_ID,
    'CUSTOMER_CARE_USERNAME': CUSTOMER_CARE_USERNAME
}

missing_vars = [var for var, value in REQUIRED_ENV_VARS.items() if not value]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# All other constants are now imported from constants.py:
# - SOCIAL_LINKS
# - WELCOME_MESSAGE
# - WELCOME_MESSAGE_REFERRED (NEW)
# - STEPS
# - LOGGING_CONFIG
# - REFERRAL_CONFIG (NEW)

print(f"✅ Configuration loaded successfully")
print(f"🤖 Bot Username: {REFERRAL_BOT_USERNAME}")
print(f"🔥 Firebase Project: {FIREBASE_PROJECT_ID}")
print(f"🎁 Referral System: ENABLED")
print(f"⚡ Optimizations: CALLBACK TIMEOUT PROTECTION ACTIVE")
