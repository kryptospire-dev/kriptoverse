import os
import redis
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

# Redis Configuration for Caching and Performance
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_DB = int(os.getenv('REDIS_DB', '0'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Performance Configuration
DATABASE_THREAD_POOL_SIZE = int(os.getenv('DATABASE_THREAD_POOL_SIZE', '20'))
CACHE_TTL_SECONDS = int(os.getenv('CACHE_TTL_SECONDS', '300'))  # 5 minutes
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '60'))  # 1 minute

# Initialize Redis connection
try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True
    )
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    print(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    print(f"⚠️ Redis not available: {e}")
    redis_client = None
    REDIS_AVAILABLE = False

# Validate required environment variables
REQUIRED_ENV_VARS = {
    'BOT_TOKEN': BOT_TOKEN,
    'FIREBASE_PROJECT_ID': FIREBASE_PROJECT_ID,
    'CUSTOMER_CARE_USERNAME': CUSTOMER_CARE_USERNAME
}

missing_vars = [var for var, value in REQUIRED_ENV_VARS.items() if not value]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

print(f"✅ Configuration loaded successfully")
print(f"🤖 Bot Username: {REFERRAL_BOT_USERNAME}")
print(f"🔥 Firebase Project: {FIREBASE_PROJECT_ID}")
print(f"🎁 Referral System: ENABLED")
print(f"⚡ Performance Mode: ENABLED")
print(f"🧵 Thread Pool Size: {DATABASE_THREAD_POOL_SIZE}")
