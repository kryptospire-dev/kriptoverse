import asyncio
import re
import random
import string
import logging
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import TelegramError, Forbidden, BadRequest, RetryAfter, NetworkError
import firebase_admin
from firebase_admin import credentials, db
from functools import wraps
import time
import tempfile
from cachetools import TTLCache
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
from prometheus_client import Counter, Histogram, Gauge, start_http_server
import redis.asyncio as redis
from aiohttp import web

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv()

# Configure logging with detailed format
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Load environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
FIREBASE_DB_URL = os.getenv('FIREBASE_DB_URL')
MINATI_CHANNEL = os.getenv('MINATI_CHANNEL', '@Minatirewards')
MINATI_CHANNEL_ID = int(os.getenv('MINATI_CHANNEL_ID', '-1002975509146'))

# Webhook configuration
WEBHOOK_ENABLED = os.getenv('WEBHOOK_ENABLED', 'false').lower() == 'true'
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')  # e.g., https://yourdomain.com
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH', '/webhook')
WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', '8443'))
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', ''.join(random.choices(string.ascii_letters + string.digits, k=32)))

# Redis configuration
REDIS_ENABLED = os.getenv('REDIS_ENABLED', 'true').lower() == 'true'
REDIS_URL = os.getenv('REDIS_URL', 'redis://default:RMnshw5pEDAvMNfabY4HloLlCjTm20kr@redis-11548.crce182.ap-south-1-1.ec2.redns.redis-cloud.com:11548')

# Performance configuration
CONNECTION_POOL_SIZE = int(os.getenv('CONNECTION_POOL_SIZE', '32'))
MAX_CONCURRENT_UPDATES = int(os.getenv('MAX_CONCURRENT_UPDATES', '100'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))
CACHE_TTL = int(os.getenv('CACHE_TTL', '300'))  # 5 minutes

# Metrics port
METRICS_PORT = int(os.getenv('METRICS_PORT', '8000'))

# Validate required environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set")
if not FIREBASE_DB_URL:
    raise ValueError("FIREBASE_DB_URL environment variable not set")
if WEBHOOK_ENABLED and not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL must be set when WEBHOOK_ENABLED=true")

# ============================================================================
# PROMETHEUS METRICS
# ============================================================================

# Counters
requests_total = Counter('bot_requests_total', 'Total requests', ['command', 'status'])
db_operations_total = Counter('bot_db_operations_total', 'Total database operations', ['operation', 'status'])
cache_hits_total = Counter('bot_cache_hits_total', 'Cache hits', ['cache_type'])
cache_misses_total = Counter('bot_cache_misses_total', 'Cache misses', ['cache_type'])
errors_total = Counter('bot_errors_total', 'Total errors', ['error_type'])

# Histograms
request_duration = Histogram('bot_request_duration_seconds', 'Request duration', ['command'])
db_operation_duration = Histogram('bot_db_operation_duration_seconds', 'DB operation duration', ['operation'])

# Gauges
active_users_gauge = Gauge('bot_active_users', 'Currently active users')
cache_size_gauge = Gauge('bot_cache_size', 'Cache size', ['cache_type'])

# ============================================================================
# FIREBASE INITIALIZATION
# ============================================================================

FIREBASE_CREDENTIALS = os.getenv('FIREBASE_CREDENTIALS')
if FIREBASE_CREDENTIALS:
    try:
        cred_dict = json.loads(FIREBASE_CREDENTIALS)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(cred_dict, f)
            FIREBASE_CRED_PATH = f.name
        logger.info("Using Firebase credentials from environment variable")
    except Exception as e:
        logger.error(f"Failed to parse FIREBASE_CREDENTIALS: {e}")
        raise
else:
    FIREBASE_CRED_PATH = os.getenv('FIREBASE_CRED_PATH', 'firebase-credentials.json')
    logger.info("Using Firebase credentials from file")

try:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {e}")
    raise

# ============================================================================
# REDIS CLIENT
# ============================================================================

redis_client: Optional[redis.Redis] = None

async def init_redis():
    """Initialize Redis connection"""
    global redis_client
    if REDIS_ENABLED:
        try:
            redis_client = await redis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_connect_timeout=5,
                socket_keepalive=True
            )
            await redis_client.ping()
            logger.info("✅ Redis connected successfully")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            redis_client = None
    else:
        logger.info("Redis disabled, using in-memory cache only")

async def close_redis():
    """Close Redis connection"""
    global redis_client
    if redis_client:
        await redis_client.aclose()
        logger.info("Redis connection closed")

# ============================================================================
# CACHING LAYER
# ============================================================================

# In-memory cache as fallback
memory_cache = TTLCache(maxsize=10000, ttl=CACHE_TTL)
membership_cache = TTLCache(maxsize=50000, ttl=CACHE_TTL)

class CacheManager:
    """Unified cache manager supporting Redis and in-memory fallback"""

    @staticmethod
    async def get(key: str, cache_type: str = 'general') -> Optional[str]:
        """Get value from cache"""
        try:
            # Try Redis first
            if redis_client:
                value = await redis_client.get(f"bot:{cache_type}:{key}")
                if value:
                    cache_hits_total.labels(cache_type=cache_type).inc()
                    return value

            # Fallback to memory cache
            if cache_type == 'membership':
                value = membership_cache.get(key)
            else:
                value = memory_cache.get(key)

            if value:
                cache_hits_total.labels(cache_type=cache_type).inc()
                return value

            cache_misses_total.labels(cache_type=cache_type).inc()
            return None
        except Exception as e:
            logger.error(f"Cache get error for {key}: {e}")
            cache_misses_total.labels(cache_type=cache_type).inc()
            return None

    @staticmethod
    async def set(key: str, value: str, ttl: int = CACHE_TTL, cache_type: str = 'general'):
        """Set value in cache"""
        try:
            # Set in Redis
            if redis_client:
                await redis_client.setex(f"bot:{cache_type}:{key}", ttl, value)

            # Also set in memory cache as backup
            if cache_type == 'membership':
                membership_cache[key] = value
            else:
                memory_cache[key] = value
        except Exception as e:
            logger.error(f"Cache set error for {key}: {e}")

    @staticmethod
    async def delete(key: str, cache_type: str = 'general'):
        """Delete value from cache"""
        try:
            if redis_client:
                await redis_client.delete(f"bot:{cache_type}:{key}")

            if cache_type == 'membership':
                membership_cache.pop(key, None)
            else:
                memory_cache.pop(key, None)
        except Exception as e:
            logger.error(f"Cache delete error for {key}: {e}")

    @staticmethod
    async def increment(key: str, amount: int = 1, cache_type: str = 'general') -> int:
        """Increment counter in cache"""
        try:
            if redis_client:
                return await redis_client.incrby(f"bot:{cache_type}:{key}", amount)
            return 0
        except Exception as e:
            logger.error(f"Cache increment error for {key}: {e}")
            return 0

# ============================================================================
# REWARDS
# ============================================================================

REWARDS = {
    'COMPLETION': 2,
    'REFERRAL': 1
}

# ============================================================================
# RETRY DECORATOR WITH CIRCUIT BREAKER
# ============================================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((NetworkError, RetryAfter)),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
async def retry_telegram_request(func, *args, **kwargs):
    """Retry wrapper for Telegram API requests with exponential backoff"""
    try:
        return await func(*args, **kwargs)
    except RetryAfter as e:
        logger.warning(f"Rate limited, waiting {e.retry_after} seconds")
        await asyncio.sleep(e.retry_after)
        return await func(*args, **kwargs)

# ============================================================================
# RATE LIMITING WITH REDIS
# ============================================================================

class RateLimiter:
    """Distributed rate limiter using Redis"""

    @staticmethod
    async def check_rate_limit(user_id: int, max_calls: int = 30, period: int = 60) -> bool:
        """Check if user is within rate limit"""
        try:
            key = f"rate_limit:{user_id}"

            if redis_client:
                # Use Redis sliding window
                now = time.time()
                pipe = redis_client.pipeline()

                # Remove old entries
                pipe.zremrangebyscore(key, 0, now - period)
                # Add current request
                pipe.zadd(key, {str(now): now})
                # Count requests in window
                pipe.zcard(key)
                # Set expiry
                pipe.expire(key, period)

                results = await pipe.execute()
                count = results[2]

                if count > max_calls:
                    logger.warning(f"Rate limit exceeded for user {user_id}: {count}/{max_calls}")
                    return False

                return True
            else:
                # Fallback: allow all requests if Redis not available
                return True

        except Exception as e:
            logger.error(f"Rate limit check error for user {user_id}: {e}")
            # On error, allow request (fail open)
            return True

def rate_limit(max_calls: int = 30, period: int = 60):
    """Rate limiting decorator"""
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id

            if not await RateLimiter.check_rate_limit(user_id, max_calls, period):
                await update.message.reply_text(
                    "⚠️ Too many requests. Please slow down and try again in a minute.",
                    parse_mode='Markdown'
                )
                return

            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def escape_markdown(text: str) -> str:
    """Escape special characters for MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def sanitize_username(username: Optional[str]) -> str:
    """Sanitize username to prevent injection"""
    if not username:
        return 'Unknown'
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', username)
    return sanitized[:32] if sanitized else 'Unknown'

def generate_referral_code(user_id: int) -> str:
    """Generate unique referral code for user"""
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"MNTC{user_id}{random_str}"

# ============================================================================
# DATABASE OPERATIONS WITH RETRY AND MONITORING
# ============================================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def get_user_data(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user data from Firebase with retry logic"""
    start_time = time.time()
    try:
        ref = db.reference(f'users/{user_id}')
        data = ref.get()

        db_operations_total.labels(operation='get_user', status='success').inc()
        db_operation_duration.labels(operation='get_user').observe(time.time() - start_time)

        return data
    except Exception as e:
        db_operations_total.labels(operation='get_user', status='error').inc()
        logger.error(f"Error getting user data for {user_id}: {e}")
        raise

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def save_user_data(user_id: int, data: Dict[str, Any]) -> bool:
    """Update user data in Firebase with retry logic"""
    start_time = time.time()
    try:
        ref = db.reference(f'users/{user_id}')
        ref.update(data)

        db_operations_total.labels(operation='save_user', status='success').inc()
        db_operation_duration.labels(operation='save_user').observe(time.time() - start_time)

        return True
    except Exception as e:
        db_operations_total.labels(operation='save_user', status='error').inc()
        logger.error(f"Error saving user data for {user_id}: {e}")
        raise

def create_user(user_id: int, username: Optional[str], referred_by: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Create new user in Firebase"""
    start_time = time.time()
    try:
        referral_code = generate_referral_code(user_id)
        username = sanitize_username(username)

        user_data = {
            'userId': user_id,
            'username': username,
            'step': 0,
            'balance': 0,
            'referralCode': referral_code,
            'referredBy': referred_by,
            'completedSteps': {
                'step1': False,
                'step2': False,
                'step3': False
            },
            'walletAddress': None,
            'referralCount': 0,  # Cached count
            'joinedAt': int(datetime.now().timestamp() * 1000),
            'lastActive': int(datetime.now().timestamp() * 1000)
        }

        ref = db.reference(f'users/{user_id}')
        ref.set(user_data)

        # Add to referral code index
        ref_code_index = db.reference(f'referralCodeIndex/{referral_code}')
        ref_code_index.set(user_id)

        db_operations_total.labels(operation='create_user', status='success').inc()
        db_operation_duration.labels(operation='create_user').observe(time.time() - start_time)

        logger.info(f"Created new user {user_id} (referred by: {referred_by})")
        return user_data
    except Exception as e:
        db_operations_total.labels(operation='create_user', status='error').inc()
        logger.error(f"Error creating user {user_id}: {e}")
        return None

async def check_channel_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int, force_refresh: bool = False) -> bool:
    """Check if user is member of the channel with distributed caching"""
    cache_key = f"{user_id}_{MINATI_CHANNEL_ID}"

    # Check cache first
    if not force_refresh:
        cached = await CacheManager.get(cache_key, cache_type='membership')
        if cached:
            return cached == 'true'

    try:
        # Check membership with retry
        member = await retry_telegram_request(
            context.bot.get_chat_member,
            MINATI_CHANNEL_ID,
            user_id
        )

        is_member = member.status in ['member', 'administrator', 'creator']

        # Cache result
        await CacheManager.set(cache_key, 'true' if is_member else 'false', ttl=CACHE_TTL, cache_type='membership')

        logger.info(f"User {user_id} membership: {member.status} (is_member: {is_member})")
        return is_member

    except Forbidden as e:
        logger.error(f"Bot lacks permission to check membership: {e}")
        errors_total.labels(error_type='forbidden').inc()
        await CacheManager.delete(cache_key, cache_type='membership')
        return False

    except BadRequest as e:
        logger.error(f"Bad request checking membership for user {user_id}: {e}")
        errors_total.labels(error_type='bad_request').inc()
        await CacheManager.delete(cache_key, cache_type='membership')
        return False

    except Exception as e:
        logger.error(f"Unexpected error checking membership for user {user_id}: {e}")
        errors_total.labels(error_type='membership_check').inc()
        await CacheManager.delete(cache_key, cache_type='membership')
        return False

def credit_reward(user_id: int, amount: int, reason: str) -> Optional[int]:
    """Credit reward to user with atomic transaction"""
    start_time = time.time()
    try:
        user_ref = db.reference(f'users/{user_id}')

        def update_balance(current_value):
            if current_value is None:
                return None
            current_balance = current_value.get('balance', 0)
            new_balance = current_balance + amount
            current_value['balance'] = new_balance
            return current_value

        user_ref.transaction(update_balance)

        # Get updated balance
        user_data = user_ref.get()
        new_balance = user_data.get('balance', 0) if user_data else 0

        # Log transaction
        trans_ref = db.reference(f'transactions/{user_id}')
        trans_ref.push({
            'amount': amount,
            'reason': reason,
            'timestamp': int(datetime.now().timestamp() * 1000),
            'newBalance': new_balance
        })

        db_operations_total.labels(operation='credit_reward', status='success').inc()
        db_operation_duration.labels(operation='credit_reward').observe(time.time() - start_time)

        logger.info(f"Credited {amount} MNTC to user {user_id} for {reason}")
        return new_balance
    except Exception as e:
        db_operations_total.labels(operation='credit_reward', status='error').inc()
        logger.error(f"Error crediting reward to user {user_id}: {e}")
        return None

def increment_referral_count(referrer_id: int) -> bool:
    """Increment cached referral count"""
    try:
        user_ref = db.reference(f'users/{referrer_id}')

        def increment_count(current_value):
            if current_value is None:
                return None
            current_count = current_value.get('referralCount', 0)
            current_value['referralCount'] = current_count + 1
            return current_value

        user_ref.transaction(increment_count)
        return True
    except Exception as e:
        logger.error(f"Error incrementing referral count for {referrer_id}: {e}")
        return False

def get_referral_count(user_id: int) -> int:
    """Get cached referral count (optimized)"""
    try:
        user_data = get_user_data(user_id)
        if user_data:
            return user_data.get('referralCount', 0)
        return 0
    except Exception as e:
        logger.error(f"Error getting referral count for user {user_id}: {e}")
        return 0

def find_user_by_referral_code(referral_code: str) -> Optional[Dict[str, Any]]:
    """Find user by their referral code using index"""
    try:
        ref_code_index = db.reference(f'referralCodeIndex/{referral_code}')
        user_id = ref_code_index.get()

        if user_id:
            return get_user_data(user_id)

        return None
    except Exception as e:
        logger.error(f"Error finding user by referral code {referral_code}: {e}")
        return None

def add_to_referral_index(referrer_id: int, referred_id: int):
    """Add referral relationship to index"""
    try:
        ref_index = db.reference(f'referralIndex/{referrer_id}/{referred_id}')
        ref_index.set(True)
    except Exception as e:
        logger.error(f"Error adding to referral index: {e}")

def register_wallet_atomic(wallet_address: str, user_id: int) -> bool:
    """Register wallet address atomically to prevent duplicates"""
    try:
        wallet_ref = db.reference(f'walletIndex/{wallet_address}')

        def register_wallet(current_value):
            if current_value is not None and current_value != user_id:
                return None
            return user_id

        result = wallet_ref.transaction(register_wallet)

        if result is None:
            logger.warning(f"Wallet {wallet_address} already registered")
            return False

        logger.info(f"Wallet {wallet_address} registered to user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error registering wallet atomically: {e}")
        return False

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

@rate_limit(max_calls=10, period=60)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    start_time = time.time()
    user_id = update.effective_user.id
    username = update.effective_user.username

    try:
        active_users_gauge.inc()

        referral_code = None
        if context.args:
            referral_code = context.args[0]

        user = get_user_data(user_id)

        if not user:
            referred_by = None

            if referral_code:
                referrer = find_user_by_referral_code(referral_code)
                if referrer and referrer.get('userId') != user_id:
                    referred_by = referrer.get('userId')

            user = create_user(user_id, username, referred_by)

            if not user:
                await update.message.reply_text(
                    "⚠️ *Database Connection Error*\n\n"
                    "Unable to connect to database. Please try again later.",
                    parse_mode='Markdown'
                )
                requests_total.labels(command='start', status='error').inc()
                return

            if referred_by:
                add_to_referral_index(referred_by, user_id)

            message = (
                f"🎉 *Welcome to MNTC Rewards Bot\\!*\n\n"
                f"Complete all verification steps to earn {REWARDS['COMPLETION']} MNTC\\!\n\n"
                f"💡 *Note:* You'll receive your referral code after completing all steps\\.\n\n"
                f"Let's start with Step 1\\.\\.\\."
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            await show_step1(update, context)

        else:
            save_user_data(user_id, {'lastActive': int(datetime.now().timestamp() * 1000)})

            if user['step'] == 3:
                bot_username = (await context.bot.get_me()).username
                referral_link = f"https://t.me/{bot_username}?start={user['referralCode']}"

                message = (
                    f"Welcome back\\! 👋\n\n"
                    f"✅ *All steps completed\\!*\n\n"
                    f"💰 Balance: *{user['balance']} MNTC*\n"
                    f"📝 Wallet: `{escape_markdown(user.get('walletAddress', 'Not set'))}`\n\n"
                    f"🎁 *Your Referral Code:* `{escape_markdown(user['referralCode'])}`\n"
                    f"🔗 *Your Referral Link:*\n"
                    f"{escape_markdown(referral_link)}\n\n"
                    f"📢 Share your referral link to earn {REWARDS['REFERRAL']} MNTC for each friend who completes verification\\!\n\n"
                    f"Use /referral to see your referral stats\\."
                )
                await update.message.reply_text(message, parse_mode='MarkdownV2')
            else:
                step = user['step']
                message = (
                    f"Welcome back\\! 👋\n\n"
                    f"💰 Balance: *{user['balance']} MNTC*\n"
                    f"📊 Current Step: *{step}/3*\n\n"
                    f"💡 Complete all steps to unlock your referral code\\!\n\n"
                    f"Let's continue from where you left off\\.\\.\\."
                )
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                await show_current_step(update, context, user)

        requests_total.labels(command='start', status='success').inc()
        request_duration.labels(command='start').observe(time.time() - start_time)

    except Exception as e:
        logger.error(f"Error in start_command for user {user_id}: {e}")
        errors_total.labels(error_type='start_command').inc()
        requests_total.labels(command='start', status='error').inc()
        await update.message.reply_text(
            "⚠️ *Unexpected Error*\n\n"
            "Something went wrong\\. Please try again later or contact support\\.",
            parse_mode='MarkdownV2'
        )
    finally:
        active_users_gauge.dec()

async def show_current_step(update: Update, context: ContextTypes.DEFAULT_TYPE, user: Dict[str, Any]):
    """Show current verification step"""
    step = user['step']

    if step == 0:
        await show_step1(update, context)
    elif step == 1:
        await show_step2(update, context)
    elif step == 2:
        await show_step3(update, context)

async def show_step1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Step 1: Download App"""
    keyboard = [
        [InlineKeyboardButton("📱 Download Minati Vault App", url="https://play.google.com/store/apps/details?id=com.app.minati_wallet")],
        [InlineKeyboardButton("✅ I have reviewed the app", callback_data="step1_complete")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "📋 *Step 1/3: Download \\& Review Minati Vault*\n\n"
        "1\\. Download the Minati Vault app\n"
        "2\\. Review the app features\n"
        "3\\. Click the button below when done\n\n"
        "Reward: Progress to Step 2"
    )

    await update.message.reply_text(message, parse_mode='MarkdownV2', reply_markup=reply_markup)

async def show_step2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Step 2: Join Channel"""
    channel_link = f"https://t.me/{MINATI_CHANNEL.replace('@', '')}"

    keyboard = [
        [InlineKeyboardButton("📢 Join Minati Channel", url=channel_link)],
        [InlineKeyboardButton("✅ Verify Membership", callback_data="step2_verify")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "📋 *Step 2/3: Join Minati Telegram Channel*\n\n"
        f"1\\. Join our official channel: {escape_markdown(MINATI_CHANNEL)}\n"
        "2\\. Click verify to check membership\n\n"
        "Reward: Progress to Step 3"
    )

    await update.message.reply_text(message, parse_mode='MarkdownV2', reply_markup=reply_markup)

async def show_step3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Step 3: Submit Wallet"""
    message = (
        "📋 *Step 3/3: Submit BEP20 Wallet Address*\n\n"
        "Please send your BEP20 Minati Vault wallet address\\.\n\n"
        "⚠️ Make sure it's a valid BEP20 address starting with '0x'\n"
        "⚠️ Each wallet can only be used once\n\n"
        f"Reward: {REWARDS['COMPLETION']} MNTC \\+ Your Referral Code\\!"
    )

    await update.message.reply_text(message, parse_mode='MarkdownV2')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    try:
        user = get_user_data(user_id)

        if not user:
            await query.answer('Please use /start first.', show_alert=True)
            return

        if data == 'step1_complete':
            if user['step'] != 0:
                await query.answer('✅ You already completed this step!', show_alert=True)
                return

            save_user_data(user_id, {
                'step': 1,
                'completedSteps': {**user.get('completedSteps', {}), 'step1': True},
                'lastStepChange': time.time()
            })

            await query.edit_message_text('✅ Step 1 completed! Moving to Step 2...')

            channel_link = f"https://t.me/{MINATI_CHANNEL.replace('@', '')}"
            keyboard = [
                [InlineKeyboardButton("📢 Join Minati Channel", url=channel_link)],
                [InlineKeyboardButton("✅ Verify Membership", callback_data="step2_verify")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = (
                "📋 *Step 2/3: Join Minati Telegram Channel*\n\n"
                f"1\\. Join our official channel: {escape_markdown(MINATI_CHANNEL)}\n"
                "2\\. Click verify to check membership\n\n"
                "Reward: Progress to Step 3"
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=message,
                parse_mode='MarkdownV2',
                reply_markup=reply_markup
            )

        elif data == 'step2_verify':
            if user['step'] != 1:
                if user['step'] > 1:
                    await query.answer('✅ You already completed this step!', show_alert=True)
                else:
                    await query.answer('❌ Please complete previous steps first!', show_alert=True)
                return

            await query.edit_message_text('🔄 Checking membership...')

            is_member = await check_channel_membership(context, user_id, force_refresh=True)

            if is_member:
                save_user_data(user_id, {
                    'step': 2,
                    'completedSteps': {**user.get('completedSteps', {}), 'step2': True},
                    'lastStepChange': time.time()
                })

                await query.edit_message_text('✅ Membership verified! Step 2 completed! Moving to Step 3...')

                message = (
                    "📋 *Step 3/3: Submit BEP20 Wallet Address*\n\n"
                    "Please send your BEP20 Minati Vault wallet address\\.\n\n"
                    "⚠️ Make sure it's a valid BEP20 address starting with '0x'\n"
                    "⚠️ Each wallet can only be used once\n\n"
                    f"Reward: {REWARDS['COMPLETION']} MNTC \\+ Your Referral Code\\!"
                )
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=message,
                    parse_mode='MarkdownV2'
                )
                save_user_data(user_id, {'awaitingWallet': True})
            else:
                channel_link = f"https://t.me/{MINATI_CHANNEL.replace('@', '')}"
                keyboard = [
                    [InlineKeyboardButton("📢 Join Minati Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Verify Membership", callback_data="step2_verify")],
                    [InlineKeyboardButton("🔍 Manual Verification", callback_data="step2_manual")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    f"❌ *Membership Not Detected*\n\n"
                    f"We couldn't verify your membership\\.\n\n"
                    f"*Please ensure:*\n"
                    f"1\\. You've joined {escape_markdown(MINATI_CHANNEL)}\n"
                    f"2\\. Your privacy settings allow the bot to check membership\n"
                    f"3\\. Wait a few seconds after joining\n\n"
                    f"Then click 'Verify Membership' again\\.\n\n"
                    f"*Still having issues?* Click 'Manual Verification' below\\.",
                    parse_mode='MarkdownV2',
                    reply_markup=reply_markup
                )

        elif data == 'step2_manual':
            if user['step'] != 1:
                await query.answer('This option is only for Step 2 verification.', show_alert=True)
                return

            await query.edit_message_text(
                f"🔍 *Manual Verification*\n\n"
                f"Please send your Telegram username \\(e\\.g\\., @yourusername\\) to verify manually\\.\n\n"
                f"Make sure you've joined {escape_markdown(MINATI_CHANNEL)} first\\!",
                parse_mode='MarkdownV2'
            )
            save_user_data(user_id, {'awaitingUsername': True})

    except Exception as e:
        logger.error(f"Error in button_callback for user {user_id}: {e}")
        errors_total.labels(error_type='button_callback').inc()
        await query.answer("⚠️ An error occurred. Please try again.", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        user = get_user_data(user_id)

        if not user:
            return

        # Handle username submission for Step 2
        if user.get('awaitingUsername'):
            if text.startswith('@'):
                save_user_data(user_id, {
                    'step': 2,
                    'completedSteps': {**user.get('completedSteps', {}), 'step2': True},
                    'awaitingUsername': False,
                    'manualVerification': text,
                    'lastStepChange': time.time()
                })

                await update.message.reply_text('✅ Username recorded\\! Step 2 completed\\! Moving to Step 3\\.\\.\\.')

                message = (
                    "📋 *Step 3/3: Submit BEP20 Wallet Address*\n\n"
                    "Please send your BEP20 Minati Vault wallet address\\.\n\n"
                    "⚠️ Make sure it's a valid BEP20 address starting with '0x'\n"
                    "⚠️ Each wallet can only be used once\n\n"
                    f"Reward: {REWARDS['COMPLETION']} MNTC \\+ Your Referral Code\\!"
                )
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                save_user_data(user_id, {'awaitingWallet': True})
            else:
                await update.message.reply_text('❌ Please send a valid username starting with @')
            return

        # Handle wallet address submission for Step 3
        if user.get('awaitingWallet') and user['step'] == 2:
            wallet_address = text.strip().lower()
            wallet_pattern = r'^0x[a-fA-F0-9]{40}$'

            if not re.match(wallet_pattern, wallet_address):
                await update.message.reply_text(
                    "❌ *Invalid Wallet Address Format\\!*\n\n"
                    "Please send a valid BEP20 address:\n"
                    "• Must start with '0x'\n"
                    "• Must be exactly 42 characters\n"
                    "• Contains only hexadecimal characters \\(0\\-9, a\\-f, A\\-F\\)\n\n"
                    "Example: `0x1234567890abcdef1234567890abcdef12345678`\n\n"
                    "Please try again\\.",
                    parse_mode='MarkdownV2'
                )
                return

            wallet_registered = register_wallet_atomic(wallet_address, user_id)

            if not wallet_registered:
                await update.message.reply_text(
                    "❌ *Wallet Address Already Registered\\!*\n\n"
                    "This BEP20 wallet address has already been registered by another user\\.\n\n"
                    "⚠️ *Each wallet can only be used once\\.*\n\n"
                    "Please provide a different BEP20 wallet address to continue\\.",
                    parse_mode='MarkdownV2'
                )
                logger.warning(f"User {user_id} attempted to use duplicate wallet: {wallet_address}")
                return

            save_user_data(user_id, {
                'step': 3,
                'completedSteps': {**user.get('completedSteps', {}), 'step3': True},
                'walletAddress': wallet_address,
                'awaitingWallet': False,
                'completedAt': int(datetime.now().timestamp() * 1000)
            })

            new_balance = credit_reward(user_id, REWARDS['COMPLETION'], 'Verification completed')

            # Credit referrer if exists
            if user.get('referredBy'):
                referrer_id = user['referredBy']
                credit_reward(referrer_id, REWARDS['REFERRAL'], 'Referral reward')
                increment_referral_count(referrer_id)

                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            f"🎉 Great news\\! Someone used your referral code\\!\n"
                            f"You've earned {REWARDS['REFERRAL']} MNTC\\! 🎁"
                        ),
                        parse_mode='MarkdownV2'
                    )
                except Exception as e:
                    logger.warning(f'Could not notify referrer {referrer_id}: {e}')

            user = get_user_data(user_id)
            bot_username = (await context.bot.get_me()).username
            referral_link = f"https://t.me/{bot_username}?start={user['referralCode']}"

            message = (
                f"🎉 *Congratulations\\!* 🎉\n\n"
                f"You've completed all verification steps\\!\n\n"
                f"💰 Balance: *{user['balance']} MNTC*\n"
                f"📝 Wallet: `{escape_markdown(wallet_address)}`\n\n"
                f"⚠️ *IMPORTANT NOTICE:*\n"
                f"*The rewards will be sent after 1st tier listing\\!* 🚀\n\n"
                f"🎁 *Your Referral Code:* `{escape_markdown(user['referralCode'])}`\n"
                f"🔗 *Your Referral Link:*\n"
                f"{escape_markdown(referral_link)}\n\n"
                f"📢 *Share your referral link to earn more\\!*\n"
                f"Earn {REWARDS['REFERRAL']} MNTC for each friend who completes verification\\! 🚀\n\n"
                f"Use /referral to track your referrals\\."
            )

            await update.message.reply_text(message, parse_mode='MarkdownV2')

    except Exception as e:
        logger.error(f"Error in handle_message for user {user_id}: {e}")
        errors_total.labels(error_type='handle_message').inc()
        await update.message.reply_text(
            "⚠️ *Unexpected Error*\n\n"
            "Something went wrong\\. Please try again later\\.",
            parse_mode='MarkdownV2'
        )

@rate_limit(max_calls=5, period=60)
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance command"""
    start_time = time.time()
    user_id = update.effective_user.id

    try:
        user = get_user_data(user_id)

        if not user:
            await update.message.reply_text('Please use /start first to register.')
            requests_total.labels(command='balance', status='error').inc()
            return

        wallet_text = user.get('walletAddress') or 'Not set'

        if user['step'] == 3:
            message = (
                f"💰 *Your MNTC Balance*\n\n"
                f"Balance: *{user['balance']} MNTC*\n"
                f"Wallet: `{escape_markdown(wallet_text)}`\n"
                f"Referral Code: `{escape_markdown(user['referralCode'])}`\n\n"
                f"⚠️ *IMPORTANT:*\n"
                f"*Rewards will be sent after 1st tier listing\\!* 🚀\n\n"
                f"Use /referral to see your referral stats\\!"
            )
        else:
            message = (
                f"💰 *Your MNTC Balance*\n\n"
                f"Balance: *{user['balance']} MNTC*\n"
                f"Wallet: `{escape_markdown(wallet_text)}`\n"
                f"Current Step: *{user['step']}/3*\n\n"
                f"Complete all steps to earn {REWARDS['COMPLETION']} MNTC and unlock your referral code\\!\n"
                f"Use /start to continue\\."
            )

        await update.message.reply_text(message, parse_mode='MarkdownV2')
        requests_total.labels(command='balance', status='success').inc()
        request_duration.labels(command='balance').observe(time.time() - start_time)

    except Exception as e:
        logger.error(f"Error in balance_command for user {user_id}: {e}")
        errors_total.labels(error_type='balance_command').inc()
        requests_total.labels(command='balance', status='error').inc()
        await update.message.reply_text("⚠️ An error occurred. Please try again.")

@rate_limit(max_calls=5, period=60)
async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referral command"""
    start_time = time.time()
    user_id = update.effective_user.id

    try:
        user = get_user_data(user_id)

        if not user:
            await update.message.reply_text('Please use /start first to register.')
            requests_total.labels(command='referral', status='error').inc()
            return

        if user['step'] < 3:
            await update.message.reply_text(
                '⚠️ *Referral Code Not Available Yet*\n\n'
                'You need to complete all verification steps first to unlock your referral code\\!\n\n'
                f'Current Step: *{user["step"]}/3*\n\n'
                'Complete verification to get your referral code and start earning\\!\n\n'
                'Use /start to continue\\.',
                parse_mode='MarkdownV2'
            )
            requests_total.labels(command='referral', status='error').inc()
            return

        referral_count = get_referral_count(user_id)
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user['referralCode']}"

        message = (
            f"🔗 *Your Referral Program*\n\n"
            f"🎁 Referral Code: `{escape_markdown(user['referralCode'])}`\n\n"
            f"🔎 Your Referral Link:\n"
            f"{escape_markdown(referral_link)}\n\n"
            f"📊 *Statistics:*\n"
            f"• Total Referrals: *{referral_count}*\n"
            f"• Earned from Referrals: *{referral_count * REWARDS['REFERRAL']} MNTC*\n\n"
            f"⚠️ *IMPORTANT:*\n"
            f"*Rewards will be sent after 1st tier listing\\!* 🚀\n\n"
            f"💡 *How it works:*\n"
            f"Share your link and earn {REWARDS['REFERRAL']} MNTC for each friend who completes all verification steps\\! 🚀"
        )

        await update.message.reply_text(message, parse_mode='MarkdownV2')
        requests_total.labels(command='referral', status='success').inc()
        request_duration.labels(command='referral').observe(time.time() - start_time)

    except Exception as e:
        logger.error(f"Error in referral_command for user {user_id}: {e}")
        errors_total.labels(error_type='referral_command').inc()
        requests_total.labels(command='referral', status='error').inc()
        await update.message.reply_text("⚠️ An error occurred. Please try again.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    message = (
        f"📖 *MNTC Rewards Bot Help*\n\n"
        f"*Available Commands:*\n"
        f"/start \\- Start or resume verification\n"
        f"/balance \\- Check your MNTC balance\n"
        f"/referral \\- View referral code \\& stats\n"
        f"/help \\- Show this help message\n\n"
        f"*Verification Steps:*\n"
        f"1️⃣ Download \\& review Minati Vault app\n"
        f"2️⃣ Join Minati Telegram channel\n"
        f"3️⃣ Submit BEP20 wallet address\n\n"
        f"*Rewards:*\n"
        f"✅ Complete all steps: {REWARDS['COMPLETION']} MNTC\n"
        f"👥 Each completed referral: {REWARDS['REFERRAL']} MNTC\n\n"
        f"💡 *Note:* Your referral code is unlocked after completing all steps\\!"
    )

    await update.message.reply_text(message, parse_mode='MarkdownV2')
    requests_total.labels(command='help', status='success').inc()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by updates"""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    errors_total.labels(error_type='general').inc()

    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ *An unexpected error occurred*\n\n"
                "Our team has been notified\\. Please try again in a few moments\\.",
                parse_mode='MarkdownV2'
            )
    except Exception as e:
        logger.error(f"Error sending error message to user: {e}")

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

async def health_check(request):
    """Health check endpoint for load balancers"""
    try:
        # Check Redis if enabled
        redis_status = "disabled"
        if redis_client:
            await redis_client.ping()
            redis_status = "healthy"

        # Check Firebase
        db.reference('/').get()

        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "redis": redis_status,
            "firebase": "healthy",
            "cache_size": {
                "memory": len(memory_cache),
                "membership": len(membership_cache)
            }
        }

        return web.json_response(health_data, status=200)

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return web.json_response({
            "status": "unhealthy",
            "error": str(e)
        }, status=503)

# ============================================================================
# MAIN APPLICATION
# ============================================================================

async def post_init(application: Application) -> None:
    """Initialize Redis after application starts"""
    await init_redis()
    logger.info("📊 Starting Prometheus metrics server...")

async def post_shutdown(application: Application) -> None:
    """Cleanup Redis on shutdown"""
    await close_redis()

def main():
    """Entry point"""
    try:
        # Start Prometheus metrics server
        start_http_server(METRICS_PORT)
        logger.info(f"📊 Metrics server started on port {METRICS_PORT}")

        # Create application with optimized settings
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .concurrent_updates(MAX_CONCURRENT_UPDATES)
            .connection_pool_size(CONNECTION_POOL_SIZE)
            .connect_timeout(REQUEST_TIMEOUT)
            .read_timeout(REQUEST_TIMEOUT)
            .write_timeout(REQUEST_TIMEOUT)
            .pool_timeout(REQUEST_TIMEOUT)
            .get_updates_connection_pool_size(CONNECTION_POOL_SIZE)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )

        # Add handlers
        application.add_handler(CommandHandler('start', start_command))
        application.add_handler(CommandHandler('balance', balance_command))
        application.add_handler(CommandHandler('referral', referral_command))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Add error handler
        application.add_error_handler(error_handler)

        # Log configuration
        logger.info('🤖 MNTC Rewards Bot Starting...')
        logger.info(f'✅ Webhook Mode: {WEBHOOK_ENABLED}')
        logger.info(f'✅ Redis: {REDIS_ENABLED}')
        logger.info(f'✅ Connection Pool Size: {CONNECTION_POOL_SIZE}')
        logger.info(f'✅ Max Concurrent Updates: {MAX_CONCURRENT_UPDATES}')
        logger.info(f'✅ Cache TTL: {CACHE_TTL}s')
        logger.info('🚀 Bot is optimized for 100K+ concurrent users')

        # Start bot (run_polling handles its own event loop in v22+)
        if WEBHOOK_ENABLED:
            logger.warning("⚠️ Webhook mode not fully implemented in this version")
            logger.info("✅ Falling back to polling mode")

        logger.info("✅ Starting in polling mode")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=e)
        raise

if __name__ == '__main__':
    main()
