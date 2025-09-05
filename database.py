import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from typing import Optional, Dict, Any, List
import config
import os
import json
import logging
import time
import random
import asyncio
import concurrent.futures
from functools import wraps
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

def async_retry(max_retries: int = 3, base_delay: float = 0.1):
    """Async retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    if self._check_circuit_breaker():
                        logger.warning(f"Circuit breaker open - skipping {func.__name__}")
                        return None

                    result = await func(self, *args, **kwargs)
                    self._record_success()
                    return result

                except Exception as e:
                    logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}")
                    self._record_failure()

                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0.1, 0.3), 10.0)
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {func.__name__} attempts failed")
                        return None
            return None
        return wrapper
    return decorator

class Database:
    def __init__(self, max_workers: int = 20):
        """Initialize Firebase connection with async support"""
        try:
            firebase_admin.get_app()
            logger.info("Firebase app already initialized")
        except ValueError:
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

        # Thread pool for Firebase operations
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

        # Async semaphore to limit concurrent operations
        self.semaphore = asyncio.Semaphore(max_workers)

        # Enhanced error handling properties
        self._connection_failures = 0
        self._last_failure_time = None
        self._circuit_breaker_open = False

        # Batch operation settings
        self.batch_size = 500
        self.max_batch_operations = 500

        # Initialize bot stats if not exists
        asyncio.create_task(self._init_bot_stats_async())

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker should be open"""
        if not self._circuit_breaker_open:
            return False

        if (self._last_failure_time and
            time.time() - self._last_failure_time > 30):
            self._circuit_breaker_open = False
            self._connection_failures = 0
            logger.info("Circuit breaker reset - allowing database operations")
            return False

        return True

    def _record_failure(self):
        """Record a database operation failure"""
        self._connection_failures += 1
        self._last_failure_time = time.time()

        if self._connection_failures >= 5:
            self._circuit_breaker_open = True
            logger.error(f"Circuit breaker opened after {self._connection_failures} failures")

    def _record_success(self):
        """Record a successful database operation"""
        self._connection_failures = 0
        self._last_failure_time = None
        if self._circuit_breaker_open:
            self._circuit_breaker_open = False
            logger.info("Circuit breaker closed - database operations restored")

    async def _run_in_executor(self, func, *args):
        """Run synchronous Firebase operation in thread pool"""
        async with self.semaphore:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self.executor, func, *args)

    async def health_check(self) -> Dict[str, Any]:
        """Perform async database health check"""
        try:
            test_doc = await self._run_in_executor(
                lambda: self.stats_collection.document('health_check').get()
            )

            return {
                'status': 'healthy',
                'connection_failures': self._connection_failures,
                'circuit_breaker_open': self._circuit_breaker_open,
                'last_failure_time': self._last_failure_time,
                'timestamp': datetime.now()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'connection_failures': self._connection_failures,
                'circuit_breaker_open': self._circuit_breaker_open,
                'timestamp': datetime.now()
            }

    def _get_credentials(self):
        """Get Firebase credentials with comprehensive error handling and priority order"""
        logger.info("Attempting to get Firebase credentials...")

        # PRIORITY 1: Try the actual service account file first (most reliable)
        if hasattr(config, 'FIREBASE_SERVICE_ACCOUNT_PATH') and config.FIREBASE_SERVICE_ACCOUNT_PATH:
            if os.path.exists(config.FIREBASE_SERVICE_ACCOUNT_PATH):
                try:
                    logger.info(f"Using service account file: {config.FIREBASE_SERVICE_ACCOUNT_PATH}")
                    with open(config.FIREBASE_SERVICE_ACCOUNT_PATH, 'r') as f:
                        service_account_info = json.load(f)

                    if self._validate_service_account(service_account_info):
                        return credentials.Certificate(service_account_info)
                    else:
                        logger.warning("Service account file validation failed")
                except Exception as e:
                    logger.error(f"Error using service account file: {e}")
            else:
                logger.warning(f"Service account file not found: {config.FIREBASE_SERVICE_ACCOUNT_PATH}")

        # PRIORITY 2: Try environment variable with full JSON
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
            try:
                logger.info("Attempting to use FIREBASE_SERVICE_ACCOUNT_JSON...")
                service_account_info = self._parse_service_account_json(service_account_json)
                if service_account_info and self._validate_service_account(service_account_info):
                    return credentials.Certificate(service_account_info)
                else:
                    logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON validation failed")
            except Exception as e:
                logger.error(f"Error processing FIREBASE_SERVICE_ACCOUNT_JSON: {e}")

        # PRIORITY 3: Try individual environment variables
        logger.info("Attempting individual environment variables...")
        service_account_env = self._get_service_account_from_env()
        if service_account_env:
            try:
                logger.info("Using individual environment variables")
                if self._validate_service_account(service_account_env):
                    return credentials.Certificate(service_account_env)
                else:
                    logger.warning("Individual environment variables validation failed")
            except Exception as e:
                logger.error(f"Error using environment variables: {e}")

        # PRIORITY 4: Try default credentials (Google Cloud)
        try:
            logger.info("Trying default credentials (Google Cloud environment)")
            return credentials.ApplicationDefault()
        except Exception as e:
            logger.error(f"Error using default credentials: {e}")

        logger.error("All Firebase credential methods failed")
        return None

    def _parse_service_account_json(self, json_string):
        """Parse service account JSON with multiple fallback methods"""
        try:
            if json_string.startswith('{'):
                service_account_info = json.loads(json_string)
                logger.info("Parsed FIREBASE_SERVICE_ACCOUNT_JSON (direct)")
                return service_account_info
        except json.JSONDecodeError:
            pass

        try:
            import base64
            decoded_json = base64.b64decode(json_string).decode('utf-8')
            service_account_info = json.loads(decoded_json)
            logger.info("Parsed FIREBASE_SERVICE_ACCOUNT_JSON (base64)")
            return service_account_info
        except Exception:
            pass

        try:
            import urllib.parse
            decoded_json = urllib.parse.unquote(json_string)
            service_account_info = json.loads(decoded_json)
            logger.info("Parsed FIREBASE_SERVICE_ACCOUNT_JSON (URL decoded)")
            return service_account_info
        except Exception:
            pass

        logger.error("Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON with all methods")
        return None

    def _validate_service_account(self, service_account_info):
        """Validate and fix service account information"""
        if not service_account_info:
            return False

        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        missing_fields = [field for field in required_fields if not service_account_info.get(field)]

        if missing_fields:
            logger.error(f"Missing required fields: {missing_fields}")
            return False

        private_key = service_account_info.get('private_key', '')

        if '\\n' in private_key:
            private_key = private_key.replace('\\n', '\n')
            service_account_info['private_key'] = private_key
            logger.info("Fixed escaped newlines in private key")

        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            logger.error("Private key missing BEGIN marker")
            return False

        if not private_key.rstrip().endswith('-----END PRIVATE KEY-----'):
            logger.error("Private key missing END marker")
            return False

        expected_project = config.FIREBASE_PROJECT_ID
        actual_project = service_account_info.get('project_id')

        if expected_project and actual_project != expected_project:
            logger.warning(f"Project ID mismatch: expected {expected_project}, got {actual_project}")

        logger.info(f"Service account validation passed - Project: {actual_project}")
        return True

    def _get_service_account_from_env(self):
        """Build service account dict from individual environment variables"""
        service_account_info = {}
        missing_vars = []

        for key, env_var in FIREBASE_ENV_MAPPING.items():
            value = os.getenv(env_var)
            if value:
                if key == 'private_key' and '\\n' in value:
                    value = value.replace('\\n', '\n')
                service_account_info[key] = value
            elif key in FIREBASE_REQUIRED_VARS:
                missing_vars.append(env_var)

        if missing_vars:
            logger.warning(f"Missing required environment variables: {missing_vars}")
            return None

        for key, default_value in FIREBASE_DEFAULTS.items():
            service_account_info.setdefault(key, default_value)

        return service_account_info

    async def _init_bot_stats_async(self):
        """Initialize bot statistics document asynchronously"""
        try:
            stats_doc = await self._run_in_executor(
                lambda: self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            )

            if not stats_doc.exists:
                initial_stats = DEFAULT_BOT_STATS.copy()
                initial_stats.update({
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                })

                await self._run_in_executor(
                    lambda: self.stats_collection.document(DB_COLLECTIONS['main_stats']).set(initial_stats)
                )
                logger.info("Bot stats initialized")
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    @async_retry(max_retries=3)
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data from Firestore asynchronously"""
        logger.debug(f"Getting user {user_id}")

        user_doc = await self._run_in_executor(
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

    @async_retry(max_retries=3)
    async def create_user(self, user_id: int, username: str, first_name: str, referred_by: str = None) -> bool:
        """Create new user in Firestore asynchronously"""
        logger.debug(f"Creating user {user_id}")

        # Check if user already exists
        existing_check = await self._run_in_executor(
            lambda: self.users_collection.document(str(user_id)).get()
        )

        if existing_check.exists:
            logger.info(f"User {user_id} already exists - skipping creation")
            return True

        user_data = DEFAULT_USER_DATA.copy()
        referral_code = await self._generate_unique_referral_code()

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

        await self._run_in_executor(
            lambda: self.users_collection.document(str(user_id)).set(user_data)
        )

        await self._update_stats_async('user_created')
        logger.info(f"User {user_id} created successfully with referral code: {referral_code}")
        if referred_by:
            logger.info(f"User {user_id} was referred by: {referred_by}")
        return True

    async def _generate_unique_referral_code(self) -> str:
        """Generate a unique referral code asynchronously"""
        max_attempts = 10
        for _ in range(max_attempts):
            code = generate_referral_code()
            existing_user = await self._get_user_by_referral_code(code)
            if not existing_user:
                return code

        logger.warning("Could not generate unique referral code after maximum attempts")
        return generate_referral_code()

    async def _get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Get user by referral code asynchronously"""
        try:
            docs = await self._run_in_executor(
                lambda: list(self.users_collection.where('referral_code', '==', referral_code).limit(1).stream())
            )

            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                return user_data
            return None
        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            return None

    async def get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Public method to get user by referral code"""
        return await self._get_user_by_referral_code(referral_code)

    async def update_user_step(self, user_id: int, step: int, completed: bool = True) -> bool:
        """Update user's current step and completion status asynchronously"""
        try:
            from constants import TOTAL_STEPS

            update_data = {
                "current_step": step + 1 if completed else step,
                f"steps_completed.step_{step}": completed,
                "updated_at": datetime.now()
            }

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            if step == TOTAL_STEPS and completed:
                await self._update_stats_async('user_completed')

                user_data = await self.get_user(user_id)
                if user_data:
                    mntc_earned = await self._calculate_and_store_mntc_earned(user_data)

                    if user_data.get('referred_by'):
                        await self._handle_referral_completion(user_data['referred_by'], user_id)

            logger.info(f"User {user_id} step {step} updated: {completed}")
            return True

        except Exception as e:
            logger.error(f"Error updating user {user_id} step {step}: {e}")
            return False

    async def _calculate_and_store_mntc_earned(self, user_data: dict) -> int:
        """Calculate MNTC earned asynchronously"""
        try:
            user_id = user_data['user_id']
            is_referred = user_data.get('is_referred', False)

            if is_referred:
                mntc_earned = REFERRAL_CONFIG['referred_reward']
                logger.info(f"User {user_id} earned {mntc_earned} MNTC (referred user)")
            else:
                mntc_earned = REFERRAL_CONFIG['normal_reward']
                logger.info(f"User {user_id} earned {mntc_earned} MNTC (normal user)")

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

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            logger.info(f"Stored reward info for user {user_id}: {mntc_earned} MNTC ({completion_data['reward_type']})")
            return mntc_earned

        except Exception as e:
            logger.error(f"Error calculating/storing MNTC for user {user_data.get('user_id')}: {e}")
            return 0

    async def _handle_referral_completion(self, referrer_code: str, referred_user_id: int):
        """Handle referral completion asynchronously"""
        try:
            referrer = await self._get_user_by_referral_code(referrer_code)
            if referrer:
                referrer_id = referrer['user_id']
                current_referrals = referrer.get('referral_stats', {}).get('total_referrals', 0)

                update_data = {
                    "referral_stats.total_referrals": current_referrals + 1,
                    "updated_at": datetime.now()
                }

                await self._run_in_executor(
                    lambda: self.users_collection.document(str(referrer_id)).update(update_data)
                )

                logger.info(f"Updated referral stats for user {referrer_id}. Total referrals: {current_referrals + 1}")
                return referrer_id

        except Exception as e:
            logger.error(f"Error handling referral completion for {referrer_code}: {e}")
            return None

    async def save_social_username(self, user_id: int, platform: str, username: str) -> bool:
        """Save user's social media username asynchronously"""
        try:
            update_data = {
                f"social_usernames.{platform}": username,
                f"verification_status.{platform}": True,
                "updated_at": datetime.now()
            }

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )
            logger.info(f"User {user_id} {platform} username saved: {username}")
            return True

        except Exception as e:
            logger.error(f"Error saving {platform} username for user {user_id}: {e}")
            return False

    async def save_bep20_address(self, user_id: int, address: str) -> bool:
        """Save user's BEP20 address asynchronously"""
        try:
            update_data = {
                "bep20_address": address,
                "updated_at": datetime.now()
            }

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )
            logger.info(f"User {user_id} BEP20 address saved")
            return True

        except Exception as e:
            logger.error(f"Error saving BEP20 address for user {user_id}: {e}")
            return False

    async def add_screenshot(self, user_id: int, file_id: str, file_name: str) -> bool:
        """Add screenshot to user's record asynchronously"""
        try:
            screenshot_data = {
                "file_id": file_id,
                "file_name": file_name,
                "uploaded_at": datetime.now()
            }

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update({
                    "screenshots": firestore.ArrayUnion([screenshot_data]),
                    "updated_at": datetime.now()
                })
            )

            logger.info(f"Screenshot added for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error adding screenshot for user {user_id}: {e}")
            return False

    async def get_user_stats(self) -> Dict:
        """Get overall bot statistics asynchronously"""
        try:
            stats_doc = await self._run_in_executor(
                lambda: self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            )

            if stats_doc.exists:
                return stats_doc.to_dict()
            else:
                return DEFAULT_BOT_STATS.copy()
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return DEFAULT_BOT_STATS.copy()

    async def _update_stats_async(self, action: str):
        """Update bot statistics asynchronously"""
        try:
            stats_ref = self.stats_collection.document(DB_COLLECTIONS['main_stats'])
            if action == 'user_created':
                await self._run_in_executor(
                    lambda: stats_ref.update({
                        'total_users': firestore.Increment(1),
                        'updated_at': datetime.now()
                    })
                )
            elif action == 'user_completed':
                await self._run_in_executor(
                    lambda: stats_ref.update({
                        'completed_users': firestore.Increment(1),
                        'updated_at': datetime.now()
                    })
                )
        except Exception as e:
            logger.error(f"Error updating stats for action {action}: {e}")

    async def update_reward_status(self, user_id: int, status: str) -> bool:
        """Update user's reward payment status asynchronously"""
        try:
            update_data = {
                "reward_info.reward_status": status,
                "reward_info.status_updated_at": datetime.now(),
                "updated_at": datetime.now()
            }

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )
            logger.info(f"Updated reward status for user {user_id}: {status}")
            return True

        except Exception as e:
            logger.error(f"Error updating reward status for user {user_id}: {e}")
            return False

    async def get_pending_rewards(self) -> List[Dict]:
        """Get all users with pending reward payments asynchronously"""
        try:
            docs = await self._run_in_executor(
                lambda: list(self.users_collection.where('reward_info.reward_status', '==', 'pending').stream())
            )

            pending_users = []
            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                pending_users.append({
                    'user_id': user_data['user_id'],
                    'first_name': user_data.get('first_name', 'Unknown'),
                    'username': user_data.get('username', 'No username'),
                    'mntc_earned': user_data.get('reward_info', {}).get('mntc_earned', 0),
                    'reward_type': user_data.get('reward_info', {}).get('reward_type', 'unknown'),
                    'completion_date': user_data.get('reward_info', {}).get('completion_date'),
                    'bep20_address': user_data.get('bep20_address', 'Not provided'),
                    'social_usernames': user_data.get('social_usernames', {})
                })

            return pending_users

        except Exception as e:
            logger.error(f"Error getting pending rewards: {e}")
            return []

    async def get_paid_rewards(self) -> List[Dict]:
        """Get all users with paid rewards asynchronously"""
        try:
            docs = await self._run_in_executor(
                lambda: list(self.users_collection.where('reward_info.reward_status', '==', 'paid').stream())
            )

            paid_users = []
            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                paid_users.append({
                    'user_id': user_data['user_id'],
                    'first_name': user_data.get('first_name', 'Unknown'),
                    'username': user_data.get('username', 'No username'),
                    'mntc_earned': user_data.get('reward_info', {}).get('mntc_earned', 0),
                    'reward_type': user_data.get('reward_info', {}).get('reward_type', 'unknown'),
                    'completion_date': user_data.get('reward_info', {}).get('completion_date'),
                    'status_updated_at': user_data.get('reward_info', {}).get('status_updated_at'),
                    'bep20_address': user_data.get('bep20_address', 'Not provided')
                })

            return paid_users

        except Exception as e:
            logger.error(f"Error getting paid rewards: {e}")
            return []

    async def get_reward_summary(self) -> Dict:
        """Get summary of all rewards asynchronously"""
        try:
            docs = await self._run_in_executor(
                lambda: list(self.users_collection.where('current_step', '>', 6).stream())
            )

            total_users = 0
            total_mntc_pending = 0
            total_mntc_paid = 0
            referred_users = 0
            normal_users = 0

            for doc in docs:
                user_data = doc.to_dict()
                reward_info = user_data.get('reward_info', {})

                if reward_info:
                    total_users += 1
                    mntc_earned = reward_info.get('mntc_earned', 0)
                    reward_status = reward_info.get('reward_status', 'pending')
                    reward_type = reward_info.get('reward_type', 'normal')

                    if reward_status == 'pending':
                        total_mntc_pending += mntc_earned
                    elif reward_status == 'paid':
                        total_mntc_paid += mntc_earned

                    if reward_type == 'referred':
                        referred_users += 1
                    else:
                        normal_users += 1

            return {
                'total_completed_users': total_users,
                'normal_users': normal_users,
                'referred_users': referred_users,
                'total_mntc_pending': total_mntc_pending,
                'total_mntc_paid': total_mntc_paid,
                'total_mntc_issued': total_mntc_pending + total_mntc_paid
            }

        except Exception as e:
            logger.error(f"Error getting reward summary: {e}")
            return {}

    async def reset_user_progress(self, user_id: int, keep_referral_data: bool = True) -> bool:
        """Reset user's progress asynchronously"""
        try:
            if keep_referral_data:
                current_user = await self.get_user(user_id)
                if current_user:
                    reset_data = DEFAULT_USER_DATA.copy()
                    reset_data.update({
                        "referral_code": current_user.get('referral_code'),
                        "referred_by": current_user.get('referred_by'),
                        "is_referred": current_user.get('is_referred', False),
                        "referral_stats": current_user.get('referral_stats', {"total_referrals": 0, "total_rewards": 0}),
                        "user_id": current_user.get('user_id'),
                        "username": current_user.get('username'),
                        "first_name": current_user.get('first_name'),
                        "created_at": current_user.get('created_at'),
                        "updated_at": datetime.now()
                    })
                else:
                    reset_data = DEFAULT_USER_DATA.copy()
                    reset_data["updated_at"] = datetime.now()
            else:
                reset_data = DEFAULT_USER_DATA.copy()
                reset_data["updated_at"] = datetime.now()

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(reset_data)
            )
            logger.info(f"User {user_id} progress reset (keep_referral_data: {keep_referral_data})")
            return True

        except Exception as e:
            logger.error(f"Error resetting user {user_id} progress: {e}")
            return False

    async def update_referral_rewards(self, user_id: int, total_rewards: int) -> bool:
        """Update user's total referral rewards asynchronously"""
        try:
            update_data = {
                "referral_stats.total_rewards": total_rewards,
                "updated_at": datetime.now()
            }

            await self._run_in_executor(
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )
            logger.info(f"Updated referral rewards for user {user_id}: {total_rewards} MNTC")
            return True

        except Exception as e:
            logger.error(f"Error updating referral rewards for user {user_id}: {e}")
            return False

    async def get_referral_stats(self, user_id: int) -> Dict:
        """Get user's referral statistics asynchronously"""
        try:
            user_data = await self.get_user(user_id)
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

    async def get_all_users(self, limit: int = None) -> List[Dict]:
        """Get all users asynchronously with pagination support"""
        try:
            if limit is None:
                limit = RATE_LIMITS['max_users_query']

            docs = await self._run_in_executor(
                lambda: list(self.users_collection.limit(limit).stream())
            )

            users = []
            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                users.append(user_data)

            return users

        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    async def get_users_batch(self, user_ids: List[int]) -> Dict[int, Optional[Dict]]:
        """Get multiple users in batch asynchronously"""
        if not user_ids:
            return {}

        # Split into batches of 10 (Firestore limit for batch get)
        batch_size = 10
        all_results = {}

        for i in range(0, len(user_ids), batch_size):
            batch_ids = user_ids[i:i + batch_size]
            batch_refs = [self.users_collection.document(str(uid)) for uid in batch_ids]

            try:
                batch_docs = await self._run_in_executor(
                    lambda refs=batch_refs: self.db.get_all(refs)
                )

                for doc, user_id in zip(batch_docs, batch_ids):
                    if doc.exists:
                        user_data = doc.to_dict()
                        user_data['_id'] = user_id
                        all_results[user_id] = user_data
                    else:
                        all_results[user_id] = None

            except Exception as e:
                logger.error(f"Error in batch get for users {batch_ids}: {e}")
                # Fall back to individual gets for this batch
                for user_id in batch_ids:
                    try:
                        user_data = await self.get_user(user_id)
                        all_results[user_id] = user_data
                    except Exception as inner_e:
                        logger.error(f"Error getting user {user_id} individually: {inner_e}")
                        all_results[user_id] = None

        return all_results

    async def batch_update_users(self, updates: List[Dict]) -> bool:
        """Batch update multiple users asynchronously"""
        if not updates:
            return True

        try:
            # Split into batches of 500 (Firestore limit)
            batch_size = 500

            for i in range(0, len(updates), batch_size):
                batch_updates = updates[i:i + batch_size]
                batch = self.db.batch()

                for update in batch_updates:
                    user_id = update['user_id']
                    update_data = update['data']
                    update_data['updated_at'] = datetime.now()

                    doc_ref = self.users_collection.document(str(user_id))
                    batch.update(doc_ref, update_data)

                await self._run_in_executor(lambda b=batch: b.commit())
                logger.info(f"Batch updated {len(batch_updates)} users")

            return True

        except Exception as e:
            logger.error(f"Error in batch update: {e}")
            return False

    async def get_users_paginated(self, page_size: int = 1000, start_after_id: str = None) -> Dict:
        """Get users with pagination for large datasets"""
        try:
            query = self.users_collection.order_by('user_id').limit(page_size)

            if start_after_id:
                start_doc = await self._run_in_executor(
                    lambda: self.users_collection.document(start_after_id).get()
                )
                if start_doc.exists:
                    query = query.start_after(start_doc)

            docs = await self._run_in_executor(lambda: list(query.stream()))

            users = []
            last_doc_id = None

            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                users.append(user_data)
                last_doc_id = doc.id

            has_more = len(users) == page_size

            return {
                'users': users,
                'has_more': has_more,
                'last_doc_id': last_doc_id,
                'count': len(users)
            }

        except Exception as e:
            logger.error(f"Error in paginated get: {e}")
            return {'users': [], 'has_more': False, 'last_doc_id': None, 'count': 0}

    async def bulk_create_users(self, user_data_list: List[Dict]) -> Dict:
        """Bulk create multiple users asynchronously"""
        if not user_data_list:
            return {'success': 0, 'failed': 0, 'errors': []}

        results = {'success': 0, 'failed': 0, 'errors': []}

        # Process in chunks to avoid overwhelming the system
        chunk_size = 100

        for i in range(0, len(user_data_list), chunk_size):
            chunk = user_data_list[i:i + chunk_size]
            tasks = []

            for user_data in chunk:
                task = self.create_user(
                    user_data['user_id'],
                    user_data.get('username', ''),
                    user_data.get('first_name', ''),
                    user_data.get('referred_by')
                )
                tasks.append(task)

            # Execute chunk concurrently
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(chunk_results):
                if isinstance(result, Exception):
                    results['failed'] += 1
                    results['errors'].append({
                        'user_id': chunk[j]['user_id'],
                        'error': str(result)
                    })
                elif result:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'user_id': chunk[j]['user_id'],
                        'error': 'Unknown error'
                    })

            # Small delay between chunks to be nice to Firebase
            await asyncio.sleep(0.1)

        logger.info(f"Bulk create results: {results['success']} success, {results['failed']} failed")
        return results

    async def get_stats_summary(self) -> Dict:
        """Get comprehensive statistics summary asynchronously"""
        try:
            tasks = [
                self.get_user_stats(),
                self.get_reward_summary(),
                self._get_referral_summary()
            ]

            user_stats, reward_summary, referral_summary = await asyncio.gather(*tasks)

            return {
                'user_stats': user_stats,
                'reward_summary': reward_summary,
                'referral_summary': referral_summary,
                'generated_at': datetime.now()
            }

        except Exception as e:
            logger.error(f"Error getting stats summary: {e}")
            return {}

    async def _get_referral_summary(self) -> Dict:
        """Get referral statistics summary"""
        try:
            # Get users with referrals
            docs = await self._run_in_executor(
                lambda: list(self.users_collection.where('referral_stats.total_referrals', '>', 0).stream())
            )

            total_referrers = len(docs)
            total_referrals = sum(doc.to_dict().get('referral_stats', {}).get('total_referrals', 0) for doc in docs)

            # Get referred users count
            referred_docs = await self._run_in_executor(
                lambda: list(self.users_collection.where('is_referred', '==', True).stream())
            )

            total_referred_users = len(referred_docs)

            return {
                'total_referrers': total_referrers,
                'total_referrals': total_referrals,
                'total_referred_users': total_referred_users,
                'average_referrals_per_referrer': total_referrals / total_referrers if total_referrers > 0 else 0
            }

        except Exception as e:
            logger.error(f"Error getting referral summary: {e}")
            return {}

    async def close_connection(self):
        """Close database connection and cleanup resources"""
        try:
            # Shutdown executor
            self.executor.shutdown(wait=True)
            logger.info("Database connection and resources closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    # Backward compatibility methods (sync versions that call async internally)
    def get_user_with_retry(self, user_id: int, max_retries: int = 3) -> Optional[Dict]:
        """Sync wrapper for get_user"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.get_user(user_id))
        finally:
            loop.close()

    def create_user_with_retry(self, user_id: int, username: str, first_name: str, referred_by: str = None, max_retries: int = 3) -> bool:
        """Sync wrapper for create_user"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.create_user(user_id, username, first_name, referred_by))
        finally:
            loop.close()

    def _init_bot_stats(self):
        """Sync wrapper for _init_bot_stats_async"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._init_bot_stats_async())
        finally:
            loop.close()

    def _update_stats(self, action: str):
        """Sync wrapper for _update_stats_async"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._update_stats_async(action))
        finally:
            loop.close()
