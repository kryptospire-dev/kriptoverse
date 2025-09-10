# Optimized Database Module with Full Async Support and Concurrency
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
import aiofiles
import weakref
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

# Async retry decorator for database operations
def async_retry(max_retries: int = 3, base_delay: float = 0.1):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(self, *args, **kwargs)
                except Exception as e:
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), 10.0)
                        jitter = random.uniform(0.1, 0.3) * delay
                        logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}")
                        await asyncio.sleep(delay + jitter)
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}: {e}")
                        raise
        return wrapper
    return decorator

# Memory-efficient cache for referral codes
class ReferralCache:
    def __init__(self, max_size: int = 1000):
        self._cache = {}
        self._access_order = []
        self.max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, referral_code: str) -> Optional[Dict]:
        async with self._lock:
            if referral_code in self._cache:
                # Move to end (most recently used)
                self._access_order.remove(referral_code)
                self._access_order.append(referral_code)
                return self._cache[referral_code]
            return None

    async def set(self, referral_code: str, user_data: Dict):
        async with self._lock:
            if referral_code in self._cache:
                self._access_order.remove(referral_code)
            elif len(self._cache) >= self.max_size:
                # Remove least recently used
                oldest = self._access_order.pop(0)
                del self._cache[oldest]
            
            self._cache[referral_code] = user_data
            self._access_order.append(referral_code)

    async def clear(self):
        async with self._lock:
            self._cache.clear()
            self._access_order.clear()

class Database:
    def __init__(self):
        """Initialize Firebase connection with comprehensive error handling and optimizations"""
        try:
            # Check if Firebase is already initialized
            firebase_admin.get_app()
            logger.info("Firebase app already initialized")
        except ValueError:
            # Initialize Firebase with multiple auth methods
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

        # Enhanced error handling properties
        self._connection_failures = 0
        self._last_failure_time = None
        self._circuit_breaker_open = False
        
        # Memory optimization and caching
        self._referral_cache = ReferralCache(max_size=1000)
        self._user_cache = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_timestamps = {}
        
        # Connection pooling settings (Firestore handles this internally)
        self._max_concurrent_operations = 100
        self._operation_semaphore = asyncio.Semaphore(self._max_concurrent_operations)
        
        # Performance metrics
        self._performance_metrics = {
            'total_operations': 0,
            'failed_operations': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'avg_response_time': 0.0
        }

        # Initialize bot stats if not exists
        asyncio.create_task(self._init_bot_stats_async())

    def _exponential_backoff_delay(self, attempt: int, base_delay: float = 0.1) -> float:
        """Calculate exponential backoff delay with jitter"""
        delay = min(base_delay * (2 ** attempt), 10.0)  # Cap at 10 seconds
        jitter = random.uniform(0.1, 0.3) * delay
        return delay + jitter

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker should be open"""
        if not self._circuit_breaker_open:
            return False
        
        # Reset circuit breaker after 30 seconds
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
        self._performance_metrics['failed_operations'] += 1
        
        # Open circuit breaker after 5 consecutive failures
        if self._connection_failures >= 5:
            self._circuit_breaker_open = True
            logger.error(f"Circuit breaker opened after {self._connection_failures} failures")

    def _record_success(self):
        """Record a successful database operation"""
        self._connection_failures = 0
        self._last_failure_time = None
        self._performance_metrics['total_operations'] += 1
        
        if self._circuit_breaker_open:
            self._circuit_breaker_open = False
            logger.info("Circuit breaker closed - database operations restored")

    async def health_check(self) -> Dict[str, Any]:
        """Perform database health check with async operations"""
        try:
            async with self._operation_semaphore:
                # Simple read operation to test connection
                test_doc = await asyncio.to_thread(
                    self.stats_collection.document('health_check').get
                )
                return {
                    'status': 'healthy',
                    'connection_failures': self._connection_failures,
                    'circuit_breaker_open': self._circuit_breaker_open,
                    'last_failure_time': self._last_failure_time,
                    'timestamp': datetime.now(),
                    'performance_metrics': self._performance_metrics.copy(),
                    'cache_size': len(self._referral_cache._cache),
                    'concurrent_operations': self._max_concurrent_operations - self._operation_semaphore._value
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
                    
                    # Validate and fix the service account info
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
                # Handle different JSON formats
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
            # Method 1: Direct JSON parsing
            if json_string.startswith('{'):
                service_account_info = json.loads(json_string)
                logger.info("Parsed FIREBASE_SERVICE_ACCOUNT_JSON (direct)")
                return service_account_info
        except json.JSONDecodeError:
            pass

        try:
            # Method 2: Base64 decoding
            import base64
            decoded_json = base64.b64decode(json_string).decode('utf-8')
            service_account_info = json.loads(decoded_json)
            logger.info("Parsed FIREBASE_SERVICE_ACCOUNT_JSON (base64)")
            return service_account_info
        except Exception:
            pass

        try:
            # Method 3: URL decoding
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

        # Check required fields
        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        missing_fields = [field for field in required_fields if not service_account_info.get(field)]

        if missing_fields:
            logger.error(f"Missing required fields: {missing_fields}")
            return False

        # Fix private key formatting
        private_key = service_account_info.get('private_key', '')
        # Handle escaped newlines
        if '\\n' in private_key:
            private_key = private_key.replace('\\n', '\n')
            service_account_info['private_key'] = private_key
            logger.info("Fixed escaped newlines in private key")

        # Validate private key format
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            logger.error("Private key missing BEGIN marker")
            return False

        if not private_key.rstrip().endswith('-----END PRIVATE KEY-----'):
            logger.error("Private key missing END marker")
            return False

        # Validate project ID
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
                # Fix private key formatting if needed
                if key == 'private_key' and '\\n' in value:
                    value = value.replace('\\n', '\n')
                service_account_info[key] = value
            elif key in FIREBASE_REQUIRED_VARS:
                missing_vars.append(env_var)

        if missing_vars:
            logger.warning(f"Missing required environment variables: {missing_vars}")
            return None

        # Set defaults for optional fields
        for key, default_value in FIREBASE_DEFAULTS.items():
            service_account_info.setdefault(key, default_value)

        return service_account_info

    async def _init_bot_stats_async(self):
        """Initialize bot statistics document asynchronously"""
        try:
            async with self._operation_semaphore:
                stats_doc = await asyncio.to_thread(
                    self.stats_collection.document(DB_COLLECTIONS['main_stats']).get
                )
                if not stats_doc.exists:
                    initial_stats = DEFAULT_BOT_STATS.copy()
                    initial_stats.update({
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    })
                    await asyncio.to_thread(
                        self.stats_collection.document(DB_COLLECTIONS['main_stats']).set,
                        initial_stats
                    )
                    logger.info("Bot stats initialized")
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    def _init_bot_stats(self):
        """Initialize bot statistics document (sync version for backward compatibility)"""
        try:
            stats_doc = self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            if not stats_doc.exists:
                initial_stats = DEFAULT_BOT_STATS.copy()
                initial_stats.update({
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                })
                self.stats_collection.document(DB_COLLECTIONS['main_stats']).set(initial_stats)
                logger.info("Bot stats initialized")
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    @async_retry(max_retries=3, base_delay=0.1)
    async def get_user_with_retry(self, user_id: int, use_cache: bool = True) -> Optional[Dict]:
        """Enhanced get_user with retry logic, caching, and circuit breaker"""
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping get_user for {user_id}")
            return None

        # Check cache first
        if use_cache:
            cache_key = f"user_{user_id}"
            if cache_key in self._cache_timestamps:
                if time.time() - self._cache_timestamps[cache_key] < self._cache_ttl:
                    if user_id in self._user_cache:
                        self._performance_metrics['cache_hits'] += 1
                        logger.debug(f"Cache hit for user {user_id}")
                        return self._user_cache[user_id]
                else:
                    # Cache expired
                    del self._cache_timestamps[cache_key]
                    if user_id in self._user_cache:
                        del self._user_cache[user_id]

        start_time = time.time()
        try:
            async with self._operation_semaphore:
                logger.debug(f"Getting user {user_id} from database")
                user_doc = await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).get
                )
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    user_data['_id'] = user_id
                    
                    # Update cache
                    if use_cache:
                        self._user_cache[user_id] = user_data
                        self._cache_timestamps[f"user_{user_id}"] = time.time()
                    
                    self._record_success()
                    self._performance_metrics['cache_misses'] += 1
                    
                    # Update performance metrics
                    response_time = time.time() - start_time
                    self._update_avg_response_time(response_time)
                    
                    logger.debug(f"Successfully retrieved user {user_id}")
                    return user_data
                else:
                    # User doesn't exist - this is not an error
                    self._record_success()
                    logger.debug(f"User {user_id} does not exist")
                    return None
                    
        except Exception as e:
            logger.warning(f"Database operation failed for user {user_id}: {e}")
            self._record_failure()
            raise

    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data from Firestore - compatibility method"""
        return await self.get_user_with_retry(user_id)

    @async_retry(max_retries=3, base_delay=0.1)
    async def create_user_with_retry(self, user_id: int, username: str, first_name: str, 
                                   referred_by: str = None) -> bool:
        """Enhanced create_user with retry logic and better error handling"""
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping create_user for {user_id}")
            return False

        start_time = time.time()
        try:
            async with self._operation_semaphore:
                logger.debug(f"Creating user {user_id}")
                
                # First check if user already exists to avoid conflicts
                existing_check = await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).get
                )
                if existing_check.exists:
                    logger.info(f"User {user_id} already exists - skipping creation")
                    self._record_success()
                    return True  # User exists, so "creation" is successful

                user_data = DEFAULT_USER_DATA.copy()
                
                # Generate unique referral code for new user
                referral_code = await asyncio.to_thread(self._generate_unique_referral_code)
                
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

                # Create the user
                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).set,
                    user_data
                )
                
                await asyncio.to_thread(self._update_stats, 'user_created')
                
                # Update cache
                self._user_cache[user_id] = user_data
                self._cache_timestamps[f"user_{user_id}"] = time.time()
                
                self._record_success()
                
                # Update performance metrics
                response_time = time.time() - start_time
                self._update_avg_response_time(response_time)
                
                logger.info(f"User {user_id} created successfully with referral code: {referral_code}")
                
                if referred_by:
                    logger.info(f"User {user_id} was referred by: {referred_by}")
                
                return True

        except Exception as e:
            logger.warning(f"Database operation failed for user {user_id}: {e}")
            self._record_failure()
            
            # Check if it's a "user already exists" type error
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                logger.info(f"User {user_id} creation conflict - user likely exists")
                return True  # Treat as success since user exists
                
            raise

    async def create_user(self, user_id: int, username: str, first_name: str, 
                         referred_by: str = None) -> bool:
        """Create new user in Firestore with referral support - compatibility method"""
        return await self.create_user_with_retry(user_id, username, first_name, referred_by)

    def _generate_unique_referral_code(self) -> str:
        """Generate a unique referral code that doesn't exist in database"""
        max_attempts = 10
        for _ in range(max_attempts):
            code = generate_referral_code()
            # Check if code already exists
            existing_user = self._get_user_by_referral_code(code)
            if not existing_user:
                return code
        
        # If we couldn't generate unique code after max attempts
        logger.warning("Could not generate unique referral code after maximum attempts")
        return generate_referral_code()  # Return anyway, let database handle duplicate

    def _get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Get user by referral code (sync method for internal use)"""
        try:
            query = self.users_collection.where('referral_code', '==', referral_code).limit(1)
            docs = query.stream()
            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                return user_data
            return None
        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            return None

    async def get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Get user by referral code with caching"""
        # Check cache first
        cached_user = await self._referral_cache.get(referral_code)
        if cached_user:
            self._performance_metrics['cache_hits'] += 1
            return cached_user

        try:
            async with self._operation_semaphore:
                user_data = await asyncio.to_thread(self._get_user_by_referral_code, referral_code)
                if user_data:
                    # Cache the result
                    await self._referral_cache.set(referral_code, user_data)
                
                self._performance_metrics['cache_misses'] += 1
                return user_data
        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            return None

    @async_retry(max_retries=3, base_delay=0.1)
    async def update_user_step(self, user_id: int, step: int, completed: bool = True) -> bool:
        """Update user's current step and completion status"""
        try:
            async with self._operation_semaphore:
                update_data = {
                    "current_step": step + 1 if completed else step,
                    f"steps_completed.step_{step}": completed,
                    "updated_at": datetime.now()
                }

                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    update_data
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    self._user_cache[user_id].update(update_data)
                    self._user_cache[user_id]["current_step"] = step + 1 if completed else step
                    if "steps_completed" not in self._user_cache[user_id]:
                        self._user_cache[user_id]["steps_completed"] = {}
                    self._user_cache[user_id]["steps_completed"][f"step_{step}"] = completed

                # Update stats and handle referral completion if user completed all steps
                if step == config.TOTAL_STEPS and completed:
                    await asyncio.to_thread(self._update_stats, 'user_completed')
                    
                    # Calculate and store MNTC earned
                    user_data = await self.get_user_with_retry(user_id)
                    if user_data:
                        mntc_earned = await asyncio.to_thread(self._calculate_and_store_mntc_earned, user_data)
                        
                        # Check if user was referred and update referrer stats
                        if user_data.get('referred_by'):
                            await asyncio.to_thread(self._handle_referral_completion, user_data['referred_by'], user_id)

                logger.info(f"User {user_id} step {step} updated: {completed}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating user {user_id} step {step}: {e}")
            return False

    def _calculate_and_store_mntc_earned(self, user_data: dict) -> int:
        """Calculate MNTC earned based on referral status and store it"""
        try:
            user_id = user_data['user_id']
            is_referred = user_data.get('is_referred', False)
            
            # Calculate MNTC based on referral status
            if is_referred:
                mntc_earned = REFERRAL_CONFIG['referred_reward']  # 4 MNTC for referred users
                logger.info(f"User {user_id} earned {mntc_earned} MNTC (referred user)")
            else:
                mntc_earned = REFERRAL_CONFIG['normal_reward']  # 4 MNTC for normal users  
                logger.info(f"User {user_id} earned {mntc_earned} MNTC (normal user)")

            # Store the earned MNTC and completion details
            completion_data = {
                "mntc_earned": mntc_earned,
                "reward_type": "referred" if is_referred else "normal",
                "completion_date": datetime.now(),
                "reward_status": "pending"  # Admin can change this to "paid" later
            }

            update_data = {
                "reward_info": completion_data,
                "updated_at": datetime.now()
            }

            self.users_collection.document(str(user_id)).update(update_data)

            logger.info(f"Stored reward info for user {user_id}: {mntc_earned} MNTC ({completion_data['reward_type']})")
            return mntc_earned
            
        except Exception as e:
            logger.error(f"Error calculating/storing MNTC for user {user_data.get('user_id')}: {e}")
            return 0

    def _handle_referral_completion(self, referrer_code: str, referred_user_id: int):
        """Handle referral completion - update referrer stats"""
        try:
            referrer = self._get_user_by_referral_code(referrer_code)
            if referrer:
                referrer_id = referrer['user_id']
                
                # Update referrer's referral count
                current_referrals = referrer.get('referral_stats', {}).get('total_referrals', 0)
                update_data = {
                    "referral_stats.total_referrals": current_referrals + 1,
                    "updated_at": datetime.now()
                }

                self.users_collection.document(str(referrer_id)).update(update_data)

                logger.info(f"Updated referral stats for user {referrer_id}. Total referrals: {current_referrals + 1}")
                return referrer_id
                
        except Exception as e:
            logger.error(f"Error handling referral completion for {referrer_code}: {e}")
            return None

    @async_retry(max_retries=3, base_delay=0.1)
    async def save_social_username(self, user_id: int, platform: str, username: str) -> bool:
        """Save user's social media username"""
        try:
            async with self._operation_semaphore:
                update_data = {
                    f"social_usernames.{platform}": username,
                    f"verification_status.{platform}": True,
                    "updated_at": datetime.now()
                }

                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    update_data
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    if "social_usernames" not in self._user_cache[user_id]:
                        self._user_cache[user_id]["social_usernames"] = {}
                    if "verification_status" not in self._user_cache[user_id]:
                        self._user_cache[user_id]["verification_status"] = {}
                    
                    self._user_cache[user_id]["social_usernames"][platform] = username
                    self._user_cache[user_id]["verification_status"][platform] = True
                    self._user_cache[user_id]["updated_at"] = datetime.now()

                logger.info(f"User {user_id} {platform} username saved: {username}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving {platform} username for user {user_id}: {e}")
            return False

    @async_retry(max_retries=3, base_delay=0.1)
    async def save_bep20_address(self, user_id: int, address: str) -> bool:
        """Save user's BEP20 address"""
        try:
            async with self._operation_semaphore:
                update_data = {
                    "bep20_address": address,
                    "updated_at": datetime.now()
                }

                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    update_data
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    self._user_cache[user_id]["bep20_address"] = address
                    self._user_cache[user_id]["updated_at"] = datetime.now()

                logger.info(f"User {user_id} BEP20 address saved")
                return True
                
        except Exception as e:
            logger.error(f"Error saving BEP20 address for user {user_id}: {e}")
            return False

    @async_retry(max_retries=3, base_delay=0.1)
    async def add_screenshot(self, user_id: int, file_id: str, file_name: str) -> bool:
        """Add screenshot to user's record"""
        try:
            async with self._operation_semaphore:
                screenshot_data = {
                    "file_id": file_id,
                    "file_name": file_name,
                    "uploaded_at": datetime.now()
                }

                # Use array union to add new screenshot
                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    {
                        "screenshots": firestore.ArrayUnion([screenshot_data]),
                        "updated_at": datetime.now()
                    }
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    if "screenshots" not in self._user_cache[user_id]:
                        self._user_cache[user_id]["screenshots"] = []
                    self._user_cache[user_id]["screenshots"].append(screenshot_data)
                    self._user_cache[user_id]["updated_at"] = datetime.now()

                logger.info(f"Screenshot added for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error adding screenshot for user {user_id}: {e}")
            return False

    async def get_user_stats(self) -> Dict:
        """Get overall bot statistics"""
        try:
            async with self._operation_semaphore:
                stats_doc = await asyncio.to_thread(
                    self.stats_collection.document(DB_COLLECTIONS['main_stats']).get
                )
                if stats_doc.exists:
                    return stats_doc.to_dict()
                else:
                    return DEFAULT_BOT_STATS.copy()
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return DEFAULT_BOT_STATS.copy()

    def _update_stats(self, action: str):
        """Update bot statistics"""
        try:
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
        except Exception as e:
            logger.error(f"Error updating stats for action {action}: {e}")

    @async_retry(max_retries=3, base_delay=0.1)
    async def update_reward_status(self, user_id: int, status: str) -> bool:
        """Update user's reward payment status (admin function)"""
        try:
            async with self._operation_semaphore:
                update_data = {
                    "reward_info.reward_status": status,
                    "reward_info.status_updated_at": datetime.now(),
                    "updated_at": datetime.now()
                }

                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    update_data
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    if "reward_info" not in self._user_cache[user_id]:
                        self._user_cache[user_id]["reward_info"] = {}
                    self._user_cache[user_id]["reward_info"]["reward_status"] = status
                    self._user_cache[user_id]["reward_info"]["status_updated_at"] = datetime.now()
                    self._user_cache[user_id]["updated_at"] = datetime.now()

                logger.info(f"Updated reward status for user {user_id}: {status}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating reward status for user {user_id}: {e}")
            return False

    async def get_pending_rewards(self) -> List[Dict]:
        """Get all users with pending reward payments (admin function)"""
        try:
            async with self._operation_semaphore:
                query = self.users_collection.where('reward_info.reward_status', '==', 'pending')
                docs = await asyncio.to_thread(query.stream)
                
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
        """Get all users with paid rewards (admin function)"""
        try:
            async with self._operation_semaphore:
                query = self.users_collection.where('reward_info.reward_status', '==', 'paid')
                docs = await asyncio.to_thread(query.stream)
                
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
        """Get summary of all rewards (admin function)"""
        try:
            async with self._operation_semaphore:
                # Get all completed users
                query = self.users_collection.where('current_step', '>', 6)
                docs = await asyncio.to_thread(query.stream)
                
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

    @async_retry(max_retries=3, base_delay=0.1)
    async def reset_user_progress(self, user_id: int, keep_referral_data: bool = True) -> bool:
        """Reset user's progress completely with option to keep referral data"""
        try:
            async with self._operation_semaphore:
                if keep_referral_data:
                    # Get current referral data before reset
                    current_user = await self.get_user_with_retry(user_id)
                    if current_user:
                        reset_data = DEFAULT_USER_DATA.copy()
                        # Preserve referral information
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
                    # Complete reset
                    reset_data = DEFAULT_USER_DATA.copy()
                    reset_data["updated_at"] = datetime.now()

                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    reset_data
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    self._user_cache[user_id] = reset_data

                logger.info(f"User {user_id} progress reset (keep_referral_data: {keep_referral_data})")
                return True
                
        except Exception as e:
            logger.error(f"Error resetting user {user_id} progress: {e}")
            return False

    @async_retry(max_retries=3, base_delay=0.1)
    async def update_referral_rewards(self, user_id: int, total_rewards: int) -> bool:
        """Update user's total referral rewards (admin function)"""
        try:
            async with self._operation_semaphore:
                update_data = {
                    "referral_stats.total_rewards": total_rewards,
                    "updated_at": datetime.now()
                }

                await asyncio.to_thread(
                    self.users_collection.document(str(user_id)).update,
                    update_data
                )

                # Update cache if exists
                if user_id in self._user_cache:
                    if "referral_stats" not in self._user_cache[user_id]:
                        self._user_cache[user_id]["referral_stats"] = {}
                    self._user_cache[user_id]["referral_stats"]["total_rewards"] = total_rewards
                    self._user_cache[user_id]["updated_at"] = datetime.now()

                logger.info(f"Updated referral rewards for user {user_id}: {total_rewards} MNTC")
                return True
                
        except Exception as e:
            logger.error(f"Error updating referral rewards for user {user_id}: {e}")
            return False

    async def get_referral_stats(self, user_id: int) -> Dict:
        """Get user's referral statistics"""
        try:
            user_data = await self.get_user_with_retry(user_id)
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
        """Get all users (for admin purposes) with pagination"""
        try:
            async with self._operation_semaphore:
                if limit is None:
                    limit = RATE_LIMITS['max_users_query']
                
                users = []
                docs = await asyncio.to_thread(self.users_collection.limit(limit).stream)
                
                for doc in docs:
                    user_data = doc.to_dict()
                    user_data['_id'] = doc.id
                    users.append(user_data)
                
                return users
                
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    def _update_avg_response_time(self, response_time: float):
        """Update average response time metric"""
        current_avg = self._performance_metrics['avg_response_time']
        total_ops = self._performance_metrics['total_operations']
        
        if total_ops == 0:
            self._performance_metrics['avg_response_time'] = response_time
        else:
            # Running average calculation
            self._performance_metrics['avg_response_time'] = (
                (current_avg * (total_ops - 1) + response_time) / total_ops
            )

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get database performance metrics"""
        return {
            'performance_metrics': self._performance_metrics.copy(),
            'cache_size': len(self._referral_cache._cache),
            'user_cache_size': len(self._user_cache),
            'circuit_breaker_open': self._circuit_breaker_open,
            'connection_failures': self._connection_failures,
            'max_concurrent_operations': self._max_concurrent_operations,
            'current_concurrent_operations': self._max_concurrent_operations - self._operation_semaphore._value
        }

    async def clear_cache(self):
        """Clear all caches"""
        await self._referral_cache.clear()
        self._user_cache.clear()
        self._cache_timestamps.clear()
        logger.info("All caches cleared")

    async def optimize_cache(self):
        """Optimize cache by removing expired entries"""
        current_time = time.time()
        expired_keys = []
        
        for key, timestamp in self._cache_timestamps.items():
            if current_time - timestamp > self._cache_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache_timestamps[key]
            user_id = int(key.split('_')[1])
            if user_id in self._user_cache:
                del self._user_cache[user_id]
        
        if expired_keys:
            logger.info(f"Removed {len(expired_keys)} expired cache entries")

    def close_connection(self):
        """Close database connection and cleanup resources"""
        asyncio.create_task(self.clear_cache())
        logger.info("Database connection closed and caches cleared")

