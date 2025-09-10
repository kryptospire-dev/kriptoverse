# Optimized Database Class - database.py
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
from concurrent.futures import ThreadPoolExecutor
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

class OptimizedDatabase:
    def __init__(self):
        """Initialize Firebase connection with optimization"""
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

        # Optimizations
        self._executor = ThreadPoolExecutor(max_workers=10)  # Connection pooling simulation
        self._connection_failures = 0
        self._last_failure_time = None
        self._circuit_breaker_open = False
        self._circuit_breaker_threshold = 15  # Increased from 5
        self._circuit_breaker_timeout = 60    # Increased from 30
        
        # In-memory cache (without Redis)
        self._user_cache = {}
        self._cache_ttl = {}
        self._cache_max_size = 1000
        self._cache_duration = 300  # 5 minutes

        self._init_bot_stats()

    def _get_credentials(self):
        """Get Firebase credentials with comprehensive error handling"""
        logger.info("Attempting to get Firebase credentials...")

        # PRIORITY 1: Service account file
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

        # PRIORITY 2: Environment variable JSON
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
            try:
                logger.info("Using FIREBASE_SERVICE_ACCOUNT_JSON...")
                service_account_info = self._parse_service_account_json(service_account_json)
                if service_account_info and self._validate_service_account(service_account_info):
                    return credentials.Certificate(service_account_info)
            except Exception as e:
                logger.error(f"Error processing FIREBASE_SERVICE_ACCOUNT_JSON: {e}")

        # PRIORITY 3: Individual environment variables
        logger.info("Attempting individual environment variables...")
        service_account_env = self._get_service_account_from_env()
        if service_account_env:
            try:
                if self._validate_service_account(service_account_env):
                    return credentials.Certificate(service_account_env)
            except Exception as e:
                logger.error(f"Error using environment variables: {e}")

        # PRIORITY 4: Default credentials
        try:
            logger.info("Trying default credentials")
            return credentials.ApplicationDefault()
        except Exception as e:
            logger.error(f"Error using default credentials: {e}")

        logger.error("All Firebase credential methods failed")
        return None

    def _parse_service_account_json(self, json_string):
        """Parse service account JSON with multiple fallback methods"""
        try:
            if json_string.startswith('{'):
                return json.loads(json_string)
        except json.JSONDecodeError:
            pass

        try:
            import base64
            decoded_json = base64.b64decode(json_string).decode('utf-8')
            return json.loads(decoded_json)
        except Exception:
            pass

        try:
            import urllib.parse
            decoded_json = urllib.parse.unquote(json_string)
            return json.loads(decoded_json)
        except Exception:
            pass

        return None

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

        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            logger.error("Private key missing BEGIN marker")
            return False

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
            return None

        for key, default_value in FIREBASE_DEFAULTS.items():
            service_account_info.setdefault(key, default_value)

        return service_account_info

    def _init_bot_stats(self):
        """Initialize bot statistics document"""
        try:
            stats_doc = self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            if not stats_doc.exists:
                initial_stats = DEFAULT_BOT_STATS.copy()
                initial_stats.update({
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                })
                self.stats_collection.document(DB_COLLECTIONS['main_stats']).set(initial_stats)
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    # ========== CACHE METHODS ==========
    def _cache_key(self, user_id: int) -> str:
        """Generate cache key for user"""
        return f"user:{user_id}"

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache entry is still valid"""
        if key not in self._cache_ttl:
            return False
        return time.time() < self._cache_ttl[key]

    def _cache_user(self, user_id: int, user_data: dict):
        """Cache user data in memory"""
        key = self._cache_key(user_id)
        
        # Implement LRU cache by removing oldest entries
        if len(self._user_cache) >= self._cache_max_size:
            oldest_key = min(self._cache_ttl.keys(), key=lambda k: self._cache_ttl[k])
            del self._user_cache[oldest_key]
            del self._cache_ttl[oldest_key]
        
        self._user_cache[key] = user_data.copy()
        self._cache_ttl[key] = time.time() + self._cache_duration

    def _get_cached_user(self, user_id: int) -> Optional[dict]:
        """Get user from cache"""
        key = self._cache_key(user_id)
        if key in self._user_cache and self._is_cache_valid(key):
            return self._user_cache[key].copy()
        
        # Remove expired entry
        if key in self._user_cache:
            del self._user_cache[key]
            del self._cache_ttl[key]
        
        return None

    def _invalidate_user_cache(self, user_id: int):
        """Remove user from cache"""
        key = self._cache_key(user_id)
        if key in self._user_cache:
            del self._user_cache[key]
            del self._cache_ttl[key]

    # ========== OPTIMIZED DATABASE METHODS ==========
    async def get_user_with_retry(self, user_id: int, max_retries: int = 2) -> Optional[Dict]:
        """Enhanced get_user with caching and reduced retries"""
        # Check cache first
        cached_user = self._get_cached_user(user_id)
        if cached_user:
            return cached_user

        if self._circuit_breaker_open:
            if time.time() - self._last_failure_time > self._circuit_breaker_timeout:
                self._circuit_breaker_open = False
                self._connection_failures = 0
            else:
                logger.warning(f"Circuit breaker open - returning None for user {user_id}")
                return None

        for attempt in range(max_retries):
            try:
                # Use thread executor for non-blocking database operations
                loop = asyncio.get_event_loop()
                user_doc = await loop.run_in_executor(
                    self._executor,
                    lambda: self.users_collection.document(str(user_id)).get()
                )
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    user_data['_id'] = user_id
                    
                    # Cache the result
                    self._cache_user(user_id, user_data)
                    
                    self._connection_failures = 0
                    return user_data
                else:
                    self._connection_failures = 0
                    return None

            except Exception as e:
                logger.warning(f"get_user attempt {attempt + 1} failed for user {user_id}: {e}")
                self._connection_failures += 1
                
                if self._connection_failures >= self._circuit_breaker_threshold:
                    self._circuit_breaker_open = True
                    self._last_failure_time = time.time()
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Reduced delay

        return None

    async def create_user_with_retry(self, user_id: int, username: str, first_name: str, referred_by: str = None, max_retries: int = 2) -> bool:
        """Optimized create_user with reduced retries"""
        if self._circuit_breaker_open:
            return False

        for attempt in range(max_retries):
            try:
                # Check cache first
                existing_user = self._get_cached_user(user_id)
                if existing_user:
                    return True

                # Quick existence check
                loop = asyncio.get_event_loop()
                existing_check = await loop.run_in_executor(
                    self._executor,
                    lambda: self.users_collection.document(str(user_id)).get()
                )
                
                if existing_check.exists:
                    # Cache the existing user
                    existing_data = existing_check.to_dict()
                    existing_data['_id'] = user_id
                    self._cache_user(user_id, existing_data)
                    return True

                # Create new user
                user_data = DEFAULT_USER_DATA.copy()
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

                # Create user document
                await loop.run_in_executor(
                    self._executor,
                    lambda: self.users_collection.document(str(user_id)).set(user_data)
                )

                # Cache the new user
                self._cache_user(user_id, user_data)
                
                # Update stats asynchronously
                asyncio.create_task(self._update_stats_async('user_created'))
                
                self._connection_failures = 0
                return True

            except Exception as e:
                logger.warning(f"create_user attempt {attempt + 1} failed for user {user_id}: {e}")
                self._connection_failures += 1
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))

        return False

    def _generate_unique_referral_code(self) -> str:
        """Generate referral code (simplified for performance)"""
        return generate_referral_code()

    async def update_user_step(self, user_id: int, step: int, completed: bool = True) -> bool:
        """Optimized update_user_step"""
        try:
            from constants import TOTAL_STEPS
            
            update_data = {
                "current_step": step + 1 if completed else step,
                f"steps_completed.step_{step}": completed,
                "updated_at": datetime.now()
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Invalidate cache
            self._invalidate_user_cache(user_id)

            # Handle completion logic
            if step == TOTAL_STEPS and completed:
                asyncio.create_task(self._handle_completion_async(user_id))

            return True

        except Exception as e:
            logger.error(f"Error updating user {user_id} step {step}: {e}")
            return False

    async def _handle_completion_async(self, user_id: int):
        """Handle completion logic asynchronously"""
        try:
            user_data = await self.get_user_with_retry(user_id)
            if user_data:
                # Calculate MNTC
                mntc_earned = self._calculate_mntc_earned(user_data)
                
                # Store completion data
                completion_data = {
                    "mntc_earned": mntc_earned,
                    "reward_type": "referred" if user_data.get('is_referred') else "normal",
                    "completion_date": datetime.now(),
                    "reward_status": "pending"
                }

                update_data = {
                    "reward_info": completion_data,
                    "updated_at": datetime.now()
                }

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    lambda: self.users_collection.document(str(user_id)).update(update_data)
                )

                # Update stats
                await self._update_stats_async('user_completed')
                
                # Handle referral
                if user_data.get('referred_by'):
                    await self._handle_referral_completion_async(user_data['referred_by'], user_id)

        except Exception as e:
            logger.error(f"Error handling completion for user {user_id}: {e}")

    def _calculate_mntc_earned(self, user_data: dict) -> int:
        """Calculate MNTC earned"""
        is_referred = user_data.get('is_referred', False)
        return REFERRAL_CONFIG['referred_reward'] if is_referred else REFERRAL_CONFIG['normal_reward']

    async def _handle_referral_completion_async(self, referrer_code: str, referred_user_id: int):
        """Handle referral completion asynchronously"""
        try:
            referrer = await self.get_user_by_referral_code_async(referrer_code)
            if referrer:
                referrer_id = referrer['user_id']
                current_referrals = referrer.get('referral_stats', {}).get('total_referrals', 0)
                
                update_data = {
                    "referral_stats.total_referrals": current_referrals + 1,
                    "updated_at": datetime.now()
                }

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    lambda: self.users_collection.document(str(referrer_id)).update(update_data)
                )
                
                # Invalidate referrer cache
                self._invalidate_user_cache(referrer_id)

        except Exception as e:
            logger.error(f"Error handling referral completion: {e}")

    async def get_user_by_referral_code_async(self, referral_code: str) -> Optional[Dict]:
        """Async version of get_user_by_referral_code"""
        try:
            loop = asyncio.get_event_loop()
            query = self.users_collection.where('referral_code', '==', referral_code).limit(1)
            docs = await loop.run_in_executor(self._executor, lambda: list(query.stream()))
            
            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                return user_data
            
            return None
        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            return None

    async def save_social_username(self, user_id: int, platform: str, username: str) -> bool:
        """Optimized save_social_username"""
        try:
            update_data = {
                f"social_usernames.{platform}": username,
                f"verification_status.{platform}": True,
                "updated_at": datetime.now()
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Invalidate cache
            self._invalidate_user_cache(user_id)
            return True

        except Exception as e:
            logger.error(f"Error saving {platform} username for user {user_id}: {e}")
            return False

    async def save_bep20_address(self, user_id: int, address: str) -> bool:
        """Optimized save_bep20_address"""
        try:
            update_data = {
                "bep20_address": address,
                "updated_at": datetime.now()
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                lambda: self.users_collection.document(str(user_id)).update(update_data)
            )

            # Invalidate cache
            self._invalidate_user_cache(user_id)
            return True

        except Exception as e:
            logger.error(f"Error saving BEP20 address for user {user_id}: {e}")
            return False

    async def _update_stats_async(self, action: str):
        """Update bot statistics asynchronously"""
        try:
            stats_ref = self.stats_collection.document(DB_COLLECTIONS['main_stats'])
            loop = asyncio.get_event_loop()
            
            if action == 'user_created':
                await loop.run_in_executor(
                    self._executor,
                    lambda: stats_ref.update({
                        'total_users': firestore.Increment(1),
                        'updated_at': datetime.now()
                    })
                )
            elif action == 'user_completed':
                await loop.run_in_executor(
                    self._executor,
                    lambda: stats_ref.update({
                        'completed_users': firestore.Increment(1),
                        'updated_at': datetime.now()
                    })
                )

        except Exception as e:
            logger.error(f"Error updating stats for action {action}: {e}")

    def get_user_stats(self) -> Dict:
        """Get bot statistics (synchronous for compatibility)"""
        try:
            stats_doc = self.stats_collection.document(DB_COLLECTIONS['main_stats']).get()
            if stats_doc.exists:
                return stats_doc.to_dict()
            else:
                return DEFAULT_BOT_STATS.copy()
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return DEFAULT_BOT_STATS.copy()

    def get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Synchronous version for compatibility"""
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

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Synchronous wrapper for compatibility"""
        # Check cache first
        cached_user = self._get_cached_user(user_id)
        if cached_user:
            return cached_user

        try:
            user_doc = self.users_collection.document(str(user_id)).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                user_data['_id'] = user_id
                self._cache_user(user_id, user_data)
                return user_data
            return None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None

    def create_user(self, user_id: int, username: str, first_name: str, referred_by: str = None) -> bool:
        """Synchronous wrapper for compatibility"""
        try:
            # Quick check
            existing_user = self._get_cached_user(user_id)
            if existing_user:
                return True

            existing_check = self.users_collection.document(str(user_id)).get()
            if existing_check.exists:
                existing_data = existing_check.to_dict()
                existing_data['_id'] = user_id
                self._cache_user(user_id, existing_data)
                return True

            # Create new user
            user_data = DEFAULT_USER_DATA.copy()
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

            self.users_collection.document(str(user_id)).set(user_data)
            self._cache_user(user_id, user_data)
            
            return True

        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False

    def close_connection(self):
        """Close database connection"""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)
        logger.info("Database connection closed")

# For backward compatibility
Database = OptimizedDatabase
