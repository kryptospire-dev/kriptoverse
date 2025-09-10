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

# Performance Configuration
ENABLE_CACHING = os.getenv('ENABLE_CACHING', 'true').lower() == 'true'
CACHE_TTL = int(os.getenv('CACHE_TTL', '300'))  # 5 minutes default
CACHE_MAX_SIZE = int(os.getenv('CACHE_MAX_SIZE', '1000'))  # 1000 items default
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '5'))  # 5 connections default
TASK_QUEUE_WORKERS = int(os.getenv('TASK_QUEUE_WORKERS', '3'))  # 3 workers default

# Rate Limiting Configuration
RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', '5'))  # 5 requests per window
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '30'))  # 30 seconds window
COMMAND_RATE_LIMIT_REQUESTS = int(os.getenv('COMMAND_RATE_LIMIT_REQUESTS', '10'))  # 10 commands per minute
COMMAND_RATE_LIMIT_WINDOW = int(os.getenv('COMMAND_RATE_LIMIT_WINDOW', '60'))  # 60 seconds window

# Memory Management
ENABLE_GC_OPTIMIZATION = os.getenv('ENABLE_GC_OPTIMIZATION', 'true').lower() == 'true'
MEMORY_LIMIT_MB = int(os.getenv('MEMORY_LIMIT_MB', '450'))  # 450MB for Render $7 plan

# Monitoring Configuration
ENABLE_PERFORMANCE_MONITORING = os.getenv('ENABLE_PERFORMANCE_MONITORING', 'true').lower() == 'true'
LOG_PERFORMANCE_INTERVAL = int(os.getenv('LOG_PERFORMANCE_INTERVAL', '300'))  # 5 minutes

# Environment Detection
IS_RENDER = os.getenv('RENDER', 'false').lower() == 'true'
IS_PRODUCTION = os.getenv('ENVIRONMENT', 'development').lower() == 'production'

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

# Performance optimizations for different environments
if IS_RENDER:
    # Optimize for Render environment
    DB_POOL_SIZE = min(DB_POOL_SIZE, 3)  # Limit connections on Render
    CACHE_MAX_SIZE = min(CACHE_MAX_SIZE, 500)  # Smaller cache for memory constraints
    TASK_QUEUE_WORKERS = min(TASK_QUEUE_WORKERS, 2)  # Fewer workers
    
print(f"✅ Configuration loaded successfully")
print(f"🤖 Bot Username: {REFERRAL_BOT_USERNAME}")
print(f"🔥 Firebase Project: {FIREBASE_PROJECT_ID}")
print(f"🎁 Referral System: ENABLED")
print(f"⚡ Performance Optimizations: ENABLED")
print(f"💾 Caching: {'ENABLED' if ENABLE_CACHING else 'DISABLED'}")
print(f"🛡️ Rate Limiting: ENABLED ({RATE_LIMIT_REQUESTS} req/{RATE_LIMIT_WINDOW}s)")
print(f"🔗 DB Pool Size: {DB_POOL_SIZE}")
print(f"👷 Task Queue Workers: {TASK_QUEUE_WORKERS}")
if IS_RENDER:
    print(f"🌐 Environment: Render (Memory limit: {MEMORY_LIMIT_MB}MB)")
if IS_PRODUCTION:
    print(f"🚀 Mode: Production")
