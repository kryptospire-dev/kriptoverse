import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from typing import Optional, Dict, Any, List
import asyncio
import json
import logging
import time
import random
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import config
import os

from constants import (
    FIREBASE_ENV_MAPPING,
    FIREBASE_DEFAULTS,
    FIREBASE_REQUIRED_VARS,
    DB_COLLECTIONS,
    DEFAULT_USER_DATA,
    DEFAULT_BOT_STATS,
    RATE_LIMITS,
    generate_referral_code,
    REFERRAL_CONFIG
)

logger = logging.getLogger(__name__)

def cache_result(cache_key_prefix: str, ttl: int = None):
    """Decorator for caching database results"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not config.REDIS_AVAILABLE:
                return await func(*args, **kwargs)

            # Generate cache key
            cache_key = f"{cache_key_prefix}:{hash(str(args[1:]) + str(kwargs))}"  # Skip self

            try:
                # Try to get from cache
                cached_result = config.redis_client.get(cache_key)
                if cached_result:
                    return json.loads(cached_result)
            except Exception as e:
                logger.warning(f"Cache read error: {e}")

            # Execute function and cache result
            result = await func(*args, **kwargs)

            try:
                if result is not None:
                    cache_ttl = ttl or config.CACHE_TTL_SECONDS
                    config.redis_client.setex(cache_key, cache_ttl, json.dumps(result, default=str))
            except Exception as e:
                logger.warning(f"Cache write error: {e}")

            return result
        return wrapper
    return decorator

def invalidate_cache(cache_key_prefix: str, identifier: str):
    """Invalidate cache entries for a specific identifier"""
    if not config.REDIS_AVAILABLE:
        return

    try:
        pattern = f"{cache_key_prefix}:*{identifier}*"
        keys = config.redis_client.keys(pattern)
        if keys:
            config.redis_client.delete(*keys)
    except Exception as e:
        logger.warning(f"Cache invalidation error: {e}")

class AsyncDatabase:
    def __init__(self):
        """Initialize Firebase connection with async support and thread pool"""
        try:
            # Check if Firebase is already initialized
            firebase_admin.get_app()
            logger.info("Firebase app already initialized")
        except ValueError:
            # Initialize Firebase
            cred = self._get_credentials()
            if cred is None:
                raise Exception("Failed to get Firebase credentials")
            firebase_admin.initialize_app(cred, {
                'projectId': config.FIREBASE_PROJECT_ID
            })
            logger.info(f"Firebase initialized for project: {config.FIREBASE_PROJECT_ID}")

        self.db = firestore.client()
        self.users_collection = self.db.collection(DB_COLLECTIONS['users'])
        self.stats_collection = self.db.collection(DB_COLLECTIONS['bot_stats'])

        # Thread pool for database operations
        self.executor = ThreadPoolExecutor(
            max_workers=config.DATABASE_THREAD_POOL_SIZE,
            thread_name_prefix="db_worker"
        )

        # Enhanced error handling properties
        self._connection_failures = 0
        self._last_failure_time = None
        self._circuit_breaker_open = False

        # Batch operation queue
        self._batch_queue = []
        self._batch_lock = asyncio.Lock()

        # Initialize bot stats if not exists
        asyncio.create_task(self._init_bot_stats_async())

        logger.info("✅ Async Database initialized with thread pool")

    def _get_credentials(self):
        """Simplified and secure credential loading"""
        logger.info("Attempting to get Firebase credentials...")

        # PRIORITY 1: Service account file (most secure)
        if hasattr(config, 'FIREBASE_SERVICE_ACCOUNT_PATH') and config.FIREBASE_SERVICE_ACCOUNT_PATH:
            if os.path.exists(config.FIREBASE_SERVICE_ACCOUNT_PATH):
                try:
                    logger.info(f"Using service account file: {config.FIREBASE_SERVICE_ACCOUNT_PATH}")
                    return credentials.Certificate(config.FIREBASE_SERVICE_ACCOUNT_PATH)
                except Exception as e:
                    logger.error(f"Error using service account file: {e}")

        # PRIORITY 2: Environment variable JSON only
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
            try:
                logger.info("Using FIREBASE_SERVICE_ACCOUNT_JSON...")
                service_account_info = json.loads(service_account_json)
                if self._validate_service_account(service_account_info):
                    return credentials.Certificate(service_account_info)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in service account: {e}")

        # PRIORITY 3: Default credentials (Google Cloud)
        try:
            logger.info("Trying default credentials (Google Cloud environment)")
            return credentials.ApplicationDefault()
        except Exception as e:
            logger.error(f"Error using default credentials: {e}")

        raise Exception("No valid Firebase credentials found")

    def _validate_service_account(self, service_account_info):
        """Validate service account information"""
        if not service_account_info:
            return False

        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        missing_fields = [field for field in required_fields if not service_account_info.get(field)]

        if missing_fields:
            logger.error(f"Missing required fields: {missing_fields}")
            return False

        # Fix private key formatting
        private_key = service_account_info.get('private_key', '')
        if '\\n' in private_key:
            private_key = private_key.replace('\\n', '\n')
            service_account_info['private_key'] = private_key

        return True

    async def _init_bot_stats_async(self):
        """Initialize bot statistics document asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            stats_doc = await loop.run_in_executor(
                self.executor,
                lambda: self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            )

            if not stats_doc.exists:
                initial_stats = DEFAULT_BOT_STATS.copy()
                initial_stats.update({
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                })
                await loop.run_in_executor(
                    self.executor,
                    lambda: self.stats_collection.document(DB_COLLECTIONS['main_stats']).set(initial_stats)
                )
                logger.info("Bot stats initialized")
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    @cache_result("user", 300)  # Cache for 5 minutes
    async def get_user_async(self, user_id: int) -> Optional[Dict]:
        """Get user data asynchronously with caching"""
        try:
            loop = asyncio.get_event_loop()
            user_doc = await loop.run_in_executor(
                self.executor,
                lambda: self.users_collection.document(str(user_id)).get()
            )

            if user_doc.exists:
                user_data = user_doc.to_dict()
                user_data['_id'] = user_id
                logger.debug(f"Successfully retrieved user {user_id}")
                return user_data
            else:
                logger.debug(f"User {user_id} does not exist")
                return None

        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None

    async def create_user_async(self, user_id: int, username: str, first_name: str, referred_by: str = None) -> bool:
        """Create user asynchronously with atomic operations"""
        try:
            loop = asyncio.get_event_loop()

            # Check if user already exists
            existing_user = await self.get_user_async(user_id)
            if existing_user:
                logger.info(f"User {user_id} already exists")
                return True

            # Generate unique referral code
            referral_code = await self._generate_unique_referral_code_async()

            user_data = DEFAULT_USER_DATA.copy()
            user_data.update({
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "referral_code": referral_code,
                "referred_by": referred_by,
                "is_referred": bool(referred_by),
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })

            # Create user in database
            await loop.run_in_executor(
                self.executor,
                lambda: self.users_collection.document(str(user_id)).set(user_data)
            )

            # Update stats
            await self._update_stats_async('user_created')

            # Invalidate cache
            invalidate_cache("user", str(user_id))

            logger.info(f"User {user_id} created successfully with referral code: {referral_code}")
            return True

        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False

    async def _generate_unique_referral_code_async(self) -> str:
        """Generate unique referral code asynchronously"""
        for _ in range(10):  # Max 10 attempts
            code = generate_referral_code()
            existing_user = await self.get_user_by_referral_code_async(code)
            if not existing_user:
                return code

        logger.warning("Could not generate unique referral code after maximum attempts")
        return generate_referral_code()

    @cache_result("referral", 600)  # Cache for 10 minutes
    async def get_user_by_referral_code_async(self, referral_code: str) -> Optional[Dict]:
        """Get user by referral code asynchronously"""
        try:
            loop = asyncio.get_event_loop()

            def query_referral():
                query = self.users_collection.where('referral_code', '==', referral_code).limit(1)
                docs = list(query.stream())
                for doc in docs:
                    user_data = doc.to_dict()
                    user_data['_id'] = doc.id
                    return user_data
                return None

            result = await loop.run_in_executor(self.executor, query_referral)
            return result

        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            return None

    async def update_user_step_async(self, user_id: int, step: int, completed: bool = True) -> bool:
        """Update user step asynchronously"""
        try:
            loop = asyncio.get_event_loop()

            from constants import TOTAL_STEPS

            update_data = {
                "current_step": step + 1 if completed else step,
                f"steps_completed.step_{step}": completed,
                "updated_at": datetime.now()
            }

            await loop.run_in_executor(
                self.executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Handle completion
            if step == TOTAL_STEPS and completed:
                await self._update_stats_async('user_completed')

                # Calculate and store MNTC earned
                user_data = await self.get_user_async(user_id)
                if user_data:
                    await self._calculate_and_store_mntc_earned_async(user_data)

                    # Handle referral completion
                    if user_data.get('referred_by'):
                        await self._handle_referral_completion_async(user_data['referred_by'], user_id)

            # Invalidate cache
            invalidate_cache("user", str(user_id))

            logger.info(f"User {user_id} step {step} updated: {completed}")
            return True

        except Exception as e:
            logger.error(f"Error updating user {user_id} step {step}: {e}")
            return False

    async def _calculate_and_store_mntc_earned_async(self, user_data: dict) -> int:
        """Calculate and store MNTC earned asynchronously"""
        try:
            user_id = user_data['user_id']
            is_referred = user_data.get('is_referred', False)

            # Calculate MNTC based on referral status
            if is_referred:
                mntc_earned = REFERRAL_CONFIG['referred_reward']
                logger.info(f"User {user_id} earned {mntc_earned} MNTC (referred user)")
            else:
                mntc_earned = REFERRAL_CONFIG['normal_reward']
                logger.info(f"User {user_id} earned {mntc_earned} MNTC (normal user)")

            # Store completion data
            completion_data = {
                "mntc_earned": mntc_earned,
                "reward_type": "referred" if is_referred else "normal",
                "completion_date": datetime.now(),
                "reward_status": "pending"
            }

            update_data = {
                "reward_info": completion_data,
                "updated_at": datetime.now()
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Invalidate cache
            invalidate_cache("user", str(user_id))

            logger.info(f"Stored reward info for user {user_id}: {mntc_earned} MNTC")
            return mntc_earned

        except Exception as e:
            logger.error(f"Error calculating/storing MNTC for user {user_data.get('user_id')}: {e}")
            return 0

    async def _handle_referral_completion_async(self, referrer_code: str, referred_user_id: int):
        """Handle referral completion asynchronously"""
        try:
            referrer = await self.get_user_by_referral_code_async(referrer_code)
            if referrer:
                referrer_id = referrer['user_id']

                # Update referrer's referral count
                current_referrals = referrer.get('referral_stats', {}).get('total_referrals', 0)
                update_data = {
                    "referral_stats.total_referrals": current_referrals + 1,
                    "updated_at": datetime.now()
                }

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self.executor,
                    lambda: self.users_collection.document(str(referrer_id)).update(update_data)
                )

                # Invalidate cache
                invalidate_cache("user", str(referrer_id))
                invalidate_cache("referral", referrer_code)

                logger.info(f"Updated referral stats for user {referrer_id}. Total referrals: {current_referrals + 1}")
                return referrer_id

        except Exception as e:
            logger.error(f"Error handling referral completion for {referrer_code}: {e}")
            return None

    async def save_social_username_async(self, user_id: int, platform: str, username: str) -> bool:
        """Save social media username asynchronously"""
        try:
            update_data = {
                f"social_usernames.{platform}": username,
                f"verification_status.{platform}": True,
                "updated_at": datetime.now()
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Invalidate cache
            invalidate_cache("user", str(user_id))

            logger.info(f"User {user_id} {platform} username saved: {username}")
            return True

        except Exception as e:
            logger.error(f"Error saving {platform} username for user {user_id}: {e}")
            return False

    async def save_bep20_address_async(self, user_id: int, address: str) -> bool:
        """Save BEP20 address asynchronously"""
        try:
            update_data = {
                "bep20_address": address,
                "updated_at": datetime.now()
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Invalidate cache
            invalidate_cache("user", str(user_id))

            logger.info(f"User {user_id} BEP20 address saved")
            return True

        except Exception as e:
            logger.error(f"Error saving BEP20 address for user {user_id}: {e}")
            return False

    async def _update_stats_async(self, action: str):
        """Update bot statistics asynchronously"""
        try:
            loop = asyncio.get_event_loop()

            def update_stats():
                stats_ref = self.stats_collection.document(DB_COLLECTIONS['main_stats'])
                if action == 'user_created':
                    stats_ref.update({
                        'total_users': firestore.Increment(1),
                        'updated_at': datetime.now()
                    })
                elif action == 'user_completed':
                    stats_ref.update({
                        'completed_users': firestore.Increment(1),
                        'updated_at': datetime.now()
                    })

            await loop.run_in_executor(self.executor, update_stats)

        except Exception as e:
            logger.error(f"Error updating stats for action {action}: {e}")

    @cache_result("stats", 60)  # Cache for 1 minute
    async def get_user_stats_async(self) -> Dict:
        """Get bot statistics asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            stats_doc = await loop.run_in_executor(
                self.executor,
                lambda: self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            )

            if stats_doc.exists:
                return stats_doc.to_dict()
            else:
                return DEFAULT_BOT_STATS.copy()

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return DEFAULT_BOT_STATS.copy()

    async def health_check_async(self) -> Dict[str, Any]:
        """Perform database health check asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            test_doc = await loop.run_in_executor(
                self.executor,
                lambda: self.stats_collection.document('health_check').get()
            )

            return {
                'status': 'healthy',
                'connection_failures': self._connection_failures,
                'circuit_breaker_open': self._circuit_breaker_open,
                'timestamp': datetime.now(),
                'thread_pool_size': config.DATABASE_THREAD_POOL_SIZE,
                'redis_available': config.REDIS_AVAILABLE
            }

        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'connection_failures': self._connection_failures,
                'circuit_breaker_open': self._circuit_breaker_open,
                'timestamp': datetime.now()
            }

    async def get_referral_stats_async(self, user_id: int) -> Dict:
        """Get user's referral statistics asynchronously"""
        try:
            user_data = await self.get_user_async(user_id)
            if user_data:
                return {
                    "referral_code": user_data.get('referral_code'),
                    "total_referrals": user_data.get('referral_stats', {}).get('total_referrals', 0),
                    "total_rewards": user_data.get('referral_stats', {}).get('total_rewards', 0),
                    "is_referred": user_data.get('is_referred', False),
                    "referred_by": user_data.get('referred_by')
                }
            return None

        except Exception as e:
            logger.error(f"Error getting referral stats for user {user_id}: {e}")
            return None

    async def batch_update_users_async(self, updates: List[Dict]) -> bool:
        """Batch update multiple users for better performance"""
        try:
            loop = asyncio.get_event_loop()

            def batch_update():
                batch = self.db.batch()
                for update in updates:
                    doc_ref = self.users_collection.document(str(update['user_id']))
                    batch.update(doc_ref, update['data'])
                batch.commit()
                return True

            result = await loop.run_in_executor(self.executor, batch_update)

            # Invalidate cache for all updated users
            for update in updates:
                invalidate_cache("user", str(update['user_id']))

            logger.info(f"Batch updated {len(updates)} users")
            return result

        except Exception as e:
            logger.error(f"Error in batch update: {e}")
            return False

    def close_connection(self):
        """Close database connection and cleanup"""
        try:
            self.executor.shutdown(wait=True)
            logger.info("✅ Database connection and thread pool closed")
        except Exception as e:
            logger.warning(f"⚠️ Database close warning: {e}")

# Legacy Database class for backward compatibility
class Database(AsyncDatabase):
    """Legacy synchronous database class - now wraps async operations"""

    def get_user_with_retry(self, user_id: int, max_retries: int = 3):
        """Legacy sync method - now runs async operation"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.get_user_async(user_id))
        except RuntimeError:
            # If no event loop is running, create one
            return asyncio.run(self.get_user_async(user_id))

    def get_user(self, user_id: int):
        """Legacy sync method"""
        return self.get_user_with_retry(user_id)

    def create_user_with_retry(self, user_id: int, username: str, first_name: str, referred_by: str = None, max_retries: int = 3):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.create_user_async(user_id, username, first_name, referred_by))
        except RuntimeError:
            return asyncio.run(self.create_user_async(user_id, username, first_name, referred_by))

    def create_user(self, user_id: int, username: str, first_name: str, referred_by: str = None):
        """Legacy sync method"""
        return self.create_user_with_retry(user_id, username, first_name, referred_by)

    def get_user_by_referral_code(self, referral_code: str):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.get_user_by_referral_code_async(referral_code))
        except RuntimeError:
            return asyncio.run(self.get_user_by_referral_code_async(referral_code))

    def update_user_step(self, user_id: int, step: int, completed: bool = True):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.update_user_step_async(user_id, step, completed))
        except RuntimeError:
            return asyncio.run(self.update_user_step_async(user_id, step, completed))

    def save_social_username(self, user_id: int, platform: str, username: str):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.save_social_username_async(user_id, platform, username))
        except RuntimeError:
            return asyncio.run(self.save_social_username_async(user_id, platform, username))

    def save_bep20_address(self, user_id: int, address: str):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.save_bep20_address_async(user_id, address))
        except RuntimeError:
            return asyncio.run(self.save_bep20_address_async(user_id, address))

    def get_user_stats(self):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.get_user_stats_async())
        except RuntimeError:
            return asyncio.run(self.get_user_stats_async())

    def health_check(self):
        """Legacy sync method"""
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.health_check_async())
        except RuntimeError:
            return asyncio.run(self.health_check_async())
