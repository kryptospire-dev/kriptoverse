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
from collections import deque
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

class BatchProcessor:
    """Batch database operations for better performance"""
    def __init__(self, db_instance):
        self.db = db_instance
        self.pending_writes = deque()
        self.pending_updates = deque()
        self.batch_size = 25  # Firestore batch limit is 500, we use 25 for safety
        self.batch_timeout = 3.0  # seconds
        self.last_flush = time.time()
        self.processing = False
        
    async def queue_create(self, user_id, user_data):
        """Queue user creation for batch processing"""
        self.pending_writes.append(('create', user_id, user_data, time.time()))
        await self._check_flush()
    
    async def queue_update(self, user_id, update_data):
        """Queue user update for batch processing"""
        self.pending_updates.append(('update', user_id, update_data, time.time()))
        await self._check_flush()
    
    async def _check_flush(self):
        """Check if we should flush the batch"""
        current_time = time.time()
        should_flush = (
            len(self.pending_writes) + len(self.pending_updates) >= self.batch_size or
            current_time - self.last_flush > self.batch_timeout
        )
        
        if should_flush and not self.processing:
            asyncio.create_task(self.flush_batch())
    
    async def flush_batch(self):
        """Flush pending operations in batch"""
        if self.processing:
            return
            
        self.processing = True
        
        try:
            if not self.pending_writes and not self.pending_updates:
                return
            
            batch = self.db.db.batch()
            operations_count = 0
            current_time = time.time()
            
            # Process writes (creates)
            while self.pending_writes and operations_count < self.batch_size:
                try:
                    operation_type, user_id, user_data, timestamp = self.pending_writes.popleft()
                    
                    # Skip stale operations (older than 60 seconds)
                    if current_time - timestamp > 60:
                        continue
                    
                    doc_ref = self.db.users_collection.document(str(user_id))
                    batch.set(doc_ref, user_data)
                    operations_count += 1
                    
                except Exception as e:
                    logger.warning(f"Error preparing write batch operation: {e}")
                    continue
            
            # Process updates
            while self.pending_updates and operations_count < self.batch_size:
                try:
                    operation_type, user_id, update_data, timestamp = self.pending_updates.popleft()
                    
                    # Skip stale operations
                    if current_time - timestamp > 60:
                        continue
                    
                    doc_ref = self.db.users_collection.document(str(user_id))
                    batch.update(doc_ref, update_data)
                    operations_count += 1
                    
                except Exception as e:
                    logger.warning(f"Error preparing update batch operation: {e}")
                    continue
            
            # Commit batch if we have operations
            if operations_count > 0:
                await batch.commit()
                logger.debug(f"Batch committed: {operations_count} operations")
            
            self.last_flush = current_time
            
        except Exception as e:
            logger.error(f"Batch flush error: {e}")
            # Re-queue failed operations (up to a limit)
            # For simplicity, we'll just log the error
            
        finally:
            self.processing = False

class OptimizedDatabase:
    def __init__(self):
        """Initialize Firebase connection with emergency optimizations"""
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

        # Emergency optimizations
        self.max_concurrent_operations = 500
        self.operation_semaphore = asyncio.BoundedSemaphore(500)
        
        # Aggressive circuit breaker for overload protection
        self._connection_failures = 0
        self._last_failure_time = None
        self._circuit_breaker_open = False
        self._max_failures = 3  # Reduced from 5 for faster protection
        self._circuit_timeout = 10  # Reduced from 30 seconds
        
        # Batch processor for high-volume operations
        self.batch_processor = BatchProcessor(self)
        
        # Cache frequently accessed data
        self._user_cache = {}
        self._cache_timeout = 300  # 5 minutes
        
        # Initialize bot stats if not exists
        asyncio.create_task(self._init_bot_stats_async())
        
        # Start batch processor
        asyncio.create_task(self._start_batch_processor())

    async def _start_batch_processor(self):
        """Start the batch processor background task"""
        while True:
            try:
                await asyncio.sleep(self.batch_processor.batch_timeout)
                if not self.batch_processor.processing:
                    await self.batch_processor.flush_batch()
            except Exception as e:
                logger.error(f"Batch processor error: {e}")
                await asyncio.sleep(5)

    def _exponential_backoff_delay(self, attempt: int, base_delay: float = 0.1) -> float:
        """Calculate exponential backoff delay with jitter"""
        delay = min(base_delay * (2 ** attempt), 5.0)  # Cap at 5 seconds for emergency
        jitter = random.uniform(0.1, 0.3) * delay
        return delay + jitter

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker should be open"""
        if not self._circuit_breaker_open:
            return False

        # Reset circuit breaker after timeout
        if (self._last_failure_time and
            time.time() - self._last_failure_time > self._circuit_timeout):
            self._circuit_breaker_open = False
            self._connection_failures = 0
            logger.info("Circuit breaker reset - allowing database operations")
            return False

        return True

    def _record_failure(self):
        """Record a database operation failure"""
        self._connection_failures += 1
        self._last_failure_time = time.time()

        # Open circuit breaker after max failures
        if self._connection_failures >= self._max_failures:
            self._circuit_breaker_open = True
            logger.error(f"Circuit breaker opened after {self._connection_failures} failures")

    def _record_success(self):
        """Record a successful database operation"""
        self._connection_failures = 0
        self._last_failure_time = None
        if self._circuit_breaker_open:
            self._circuit_breaker_open = False
            logger.info("Circuit breaker closed - database operations restored")

    def health_check(self) -> Dict[str, Any]:
        """Perform database health check"""
        try:
            # Simple read operation to test connection
            test_doc = self.stats_collection.document('health_check').get()

            return {
                'status': 'healthy',
                'connection_failures': self._connection_failures,
                'circuit_breaker_open': self._circuit_breaker_open,
                'last_failure_time': self._last_failure_time,
                'cache_size': len(self._user_cache),
                'pending_writes': len(self.batch_processor.pending_writes),
                'pending_updates': len(self.batch_processor.pending_updates),
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
        """Get Firebase credentials with comprehensive error handling"""
        logger.info("Attempting to get Firebase credentials...")

        # PRIORITY 1: Try service account file
        if hasattr(config, 'FIREBASE_SERVICE_ACCOUNT_PATH') and config.FIREBASE_SERVICE_ACCOUNT_PATH:
            if os.path.exists(config.FIREBASE_SERVICE_ACCOUNT_PATH):
                try:
                    logger.info(f"Using service account file: {config.FIREBASE_SERVICE_ACCOUNT_PATH}")
                    with open(config.FIREBASE_SERVICE_ACCOUNT_PATH, 'r') as f:
                        service_account_info = json.load(f)

                    if self._validate_service_account(service_account_info):
                        return credentials.Certificate(service_account_info)
                except Exception as e:
                    logger.error(f"Error using service account file: {e}")

        # PRIORITY 2: Try environment variable with full JSON
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
            try:
                logger.info("Attempting to use FIREBASE_SERVICE_ACCOUNT_JSON...")
                service_account_info = self._parse_service_account_json(service_account_json)
                if service_account_info and self._validate_service_account(service_account_info):
                    return credentials.Certificate(service_account_info)
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
            except Exception as e:
                logger.error(f"Error using environment variables: {e}")

        # PRIORITY 4: Try default credentials
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
            stats_doc = await self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            if not stats_doc.exists:
                initial_stats = DEFAULT_BOT_STATS.copy()
                initial_stats.update({
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                })
                await self.stats_collection.document(DB_COLLECTIONS['main_stats']).set(initial_stats)
                logger.info("Bot stats initialized")
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    def _get_from_cache(self, user_id: int) -> Optional[Dict]:
        """Get user from cache if available and not expired"""
        cache_key = str(user_id)
        if cache_key in self._user_cache:
            user_data, timestamp = self._user_cache[cache_key]
            if time.time() - timestamp < self._cache_timeout:
                return user_data
            else:
                # Remove expired cache entry
                del self._user_cache[cache_key]
        return None

    def _update_cache(self, user_id: int, user_data: Dict):
        """Update user cache"""
        # Limit cache size to prevent memory issues
        if len(self._user_cache) > 1000:
            # Remove oldest 200 entries
            oldest_keys = list(self._user_cache.keys())[:200]
            for key in oldest_keys:
                del self._user_cache[key]
        
        self._user_cache[str(user_id)] = (user_data, time.time())

    def _clear_user_cache(self, user_id: int):
        """Clear specific user from cache"""
        cache_key = str(user_id)
        if cache_key in self._user_cache:
            del self._user_cache[cache_key]

    async def get_user_with_retry(self, user_id: int, max_retries: int = 2) -> Optional[Dict]:
        """Emergency optimized get_user with caching and reduced retries"""
        # Check circuit breaker
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping get_user for {user_id}")
            return None

        # Try cache first
        cached_user = self._get_from_cache(user_id)
        if cached_user:
            return cached_user

        # Use semaphore to limit concurrent operations
        async with self.operation_semaphore:
            for attempt in range(max_retries):
                try:
                    logger.debug(f"Getting user {user_id}, attempt {attempt + 1}")
                    user_doc = await self.users_collection.document(str(user_id)).get()

                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_data['_id'] = user_id
                        
                        # Update cache
                        self._update_cache(user_id, user_data)
                        
                        self._record_success()
                        logger.debug(f"Successfully retrieved user {user_id}")
                        return user_data
                    else:
                        # User doesn't exist - not an error
                        self._record_success()
                        logger.debug(f"User {user_id} does not exist")
                        return None

                except Exception as e:
                    logger.warning(f"get_user attempt {attempt + 1} failed for user {user_id}: {e}")
                    self._record_failure()

                    if attempt < max_retries - 1:
                        delay = self._exponential_backoff_delay(attempt)
                        logger.info(f"Retrying get_user in {delay:.2f} seconds")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All get_user attempts failed for user {user_id}")
                        return None

        return None

    async def create_user_with_retry(self, user_id: int, username: str, first_name: str, referred_by: str = None, max_retries: int = 2) -> bool:
        """Emergency optimized create_user with batch processing"""
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping create_user for {user_id}")
            return False

        # Use semaphore to limit concurrent operations
        async with self.operation_semaphore:
            for attempt in range(max_retries):
                try:
                    logger.debug(f"Creating user {user_id}, attempt {attempt + 1}")

                    # Quick existence check
                    existing_check = await self.users_collection.document(str(user_id)).get()
                    if existing_check.exists:
                        logger.info(f"User {user_id} already exists - skipping creation")
                        self._record_success()
                        return True

                    user_data = DEFAULT_USER_DATA.copy()

                    # Generate unique referral code
                    referral_code = self._generate_unique_referral_code()

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

                    # Use batch processor for high-volume scenarios
                    await self.batch_processor.queue_create(user_id, user_data)
                    
                    # Also update cache
                    self._update_cache(user_id, user_data)
                    
                    # Update stats (immediate for important metrics)
                    asyncio.create_task(self._update_stats_async('user_created'))
                    
                    self._record_success()
                    logger.info(f"User {user_id} queued for creation with referral code: {referral_code}")
                    if referred_by:
                        logger.info(f"User {user_id} was referred by: {referred_by}")
                    return True

                except Exception as e:
                    logger.warning(f"create_user attempt {attempt + 1} failed for user {user_id}: {e}")
                    self._record_failure()

                    if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                        logger.info(f"User {user_id} creation conflict - user likely exists")
                        return True

                    if attempt < max_retries - 1:
                        delay = self._exponential_backoff_delay(attempt)
                        logger.info(f"Retrying create_user in {delay:.2f} seconds")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All create_user attempts failed for user {user_id}")
                        return False

        return False

    def _generate_unique_referral_code(self) -> str:
        """Generate a unique referral code - simplified for emergency"""
        # In emergency mode, we'll generate and trust it's unique
        # Full uniqueness check is too expensive during high traffic
        return generate_referral_code()

    async def get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Get user by referral code with circuit breaker protection"""
        if self._check_circuit_breaker():
            return None
            
        try:
            async with self.operation_semaphore:
                query = self.users_collection.where('referral_code', '==', referral_code).limit(1)
                docs = query.stream()
                async for doc in docs:
                    user_data = doc.to_dict()
                    user_data['_id'] = doc.id
                    return user_data
                return None
        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            self._record_failure()
            return None

    async def update_user_step(self, user_id: int, step: int, completed: bool = True) -> bool:
        """Optimized user step update with batch processing"""
        try:
            from constants import TOTAL_STEPS

            update_data = {
                "current_step": step + 1 if completed else step,
                f"steps_completed.step_{step}": completed,
                "updated_at": datetime.now()
            }

            # Use batch processor for updates
            await self.batch_processor.queue_update(user_id, update_data)
            
            # Clear cache for this user
            self._clear_user_cache(user_id)

            # Handle completion
            if step == TOTAL_STEPS and completed:
                asyncio.create_task(self._update_stats_async('user_completed'))

                # Get user data for reward calculation (from cache if available)
                user_data = await self.get_user_with_retry(user_id, max_retries=1)
                if user_data:
                    asyncio.create_task(self._calculate_and_store_mntc_earned_async(user_data))

                    # Handle referral completion
                    if user_data.get('referred_by'):
                        asyncio.create_task(self._handle_referral_completion_async(user_data['referred_by'], user_id))

            logger.info(f"User {user_id} step {step} update queued: {completed}")
            return True

        except Exception as e:
            logger.error(f"Error updating user {user_id} step {step}: {e}")
            return False

    async def _calculate_and_store_mntc_earned_async(self, user_data: dict):
        """Calculate MNTC earned - async version"""
        try:
            user_id = user_data['user_id']
            is_referred = user_data.get('is_referred', False)

            mntc_earned = REFERRAL_CONFIG['referred_reward'] if is_referred else REFERRAL_CONFIG['normal_reward']

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

            # Use batch processor
            await self.batch_processor.queue_update(user_id, update_data)
            
            logger.info(f"Reward info queued for user {user_id}: {mntc_earned} MNTC ({completion_data['reward_type']})")

        except Exception as e:
            logger.error(f"Error calculating/storing MNTC for user {user_data.get('user_id')}: {e}")

    async def _handle_referral_completion_async(self, referrer_code: str, referred_user_id: int):
        """Handle referral completion - async version"""
        try:
            referrer = await self.get_user_by_referral_code(referrer_code)
            if referrer:
                referrer_id = referrer['user_id']
                current_referrals = referrer.get('referral_stats', {}).get('total_referrals', 0)

                update_data = {
                    "referral_stats.total_referrals": current_referrals + 1,
                    "updated_at": datetime.now()
                }

                # Use batch processor
                await self.batch_processor.queue_update(referrer_id, update_data)
                
                logger.info(f"Referral stats update queued for user {referrer_id}. Total referrals: {current_referrals + 1}")

        except Exception as e:
            logger.error(f"Error handling referral completion for {referrer_code}: {e}")

    async def save_social_username(self, user_id: int, platform: str, username: str) -> bool:
        """Optimized social username save with batch processing"""
        try:
            update_data = {
                f"social_usernames.{platform}": username,
                f"verification_status.{platform}": True,
                "updated_at": datetime.now()
            }

            # Use batch processor
            await self.batch_processor.queue_update(user_id, update_data)
            
            # Clear cache
            self._clear_user_cache(user_id)
            
            logger.info(f"User {user_id} {platform} username update queued: {username}")
            return True

        except Exception as e:
            logger.error(f"Error saving {platform} username for user {user_id}: {e}")
            return False

    async def save_bep20_address(self, user_id: int, address: str) -> bool:
        """Optimized BEP20 address save with batch processing"""
        try:
            update_data = {
                "bep20_address": address,
                "updated_at": datetime.now()
            }

            # Use batch processor
            await self.batch_processor.queue_update(user_id, update_data)
            
            # Clear cache
            self._clear_user_cache(user_id)
            
            logger.info(f"User {user_id} BEP20 address update queued")
            return True

        except Exception as e:
            logger.error(f"Error saving BEP20 address for user {user_id}: {e}")
            return False

    async def get_user_stats(self) -> Dict:
        """Get overall bot statistics with caching"""
        try:
            stats_doc = await self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
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
                await stats_ref.update({
                    'total_users': firestore.Increment(1),
                    'updated_at': datetime.now()
                })
            elif action == 'user_completed':
                await stats_ref.update({
                    'completed_users': firestore.Increment(1),
                    'updated_at': datetime.now()
                })
        except Exception as e:
            logger.error(f"Error updating stats for action {action}: {e}")

    async def emergency_user_operation(self, user_id, operation_data):
        """Emergency single-attempt operation during high load"""
        async with self.operation_semaphore:
            try:
                # Single attempt, no retries during emergency
                doc_ref = self.users_collection.document(str(user_id))
                await doc_ref.update(operation_data)
                return True
            except Exception as e:
                logger.warning(f"Emergency operation failed for {user_id}: {e}")
                return False

    async def close_connection(self):
        """Close database connection and flush pending operations"""
        try:
            # Flush any pending batch operations
            await self.batch_processor.flush_batch()
            
            # Clear cache
            self._user_cache.clear()
            
            logger.info("Optimized database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    # Compatibility methods for existing code
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Compatibility method - use get_user_with_retry instead"""
        return asyncio.create_task(self.get_user_with_retry(user_id))

    def create_user(self, user_id: int, username: str, first_name: str, referred_by: str = None) -> bool:
        """Compatibility method - use create_user_with_retry instead"""
        return asyncio.create_task(self.create_user_with_retry(user_id, username, first_name, referred_by))

    # Emergency fallback methods (simplified, reduced functionality for performance)
    async def emergency_get_user(self, user_id: int) -> Optional[Dict]:
        """Emergency get user - single attempt, no caching"""
        try:
            user_doc = await self.users_collection.document(str(user_id)).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                user_data['_id'] = user_id
                return user_data
            return None
        except Exception as e:
            logger.error(f"Emergency get user failed for {user_id}: {e}")
            return None

    async def emergency_create_user(self, user_id: int, username: str, first_name: str) -> bool:
        """Emergency create user - minimal data, single attempt"""
        try:
            minimal_user_data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "current_step": 1,
                "referral_code": generate_referral_code(),
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            }

            await self.users_collection.document(str(user_id)).set(minimal_user_data)
            logger.info(f"Emergency user creation successful for {user_id}")
            return True
        except Exception as e:
            logger.error(f"Emergency create user failed for {user_id}: {e}")
            return False

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""
        return {
            'cache_size': len(self._user_cache),
            'pending_writes': len(self.batch_processor.pending_writes),
            'pending_updates': len(self.batch_processor.pending_updates),
            'circuit_breaker_open': self._circuit_breaker_open,
            'connection_failures': self._connection_failures,
            'batch_processing': self.batch_processor.processing
        }
