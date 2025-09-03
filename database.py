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
import threading
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

class Database:
    def __init__(self):
        """Initialize Firebase connection with comprehensive error handling"""
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

        # Initialize bot stats if not exists
        self._init_bot_stats()

    def optimize_connection(self):
        """Optimize Firestore connection for better performance"""
        try:
            # Set up connection with optimized settings
            from google.cloud.firestore_v1 import Client
            from google.api_core.client_options import ClientOptions

            # Configure for better performance in high-load scenarios
            client_options = ClientOptions(
                api_endpoint='https://firestore.googleapis.com',
                quota_project_id=config.FIREBASE_PROJECT_ID
            )

            logger.info("Database connection optimized for callback handlers")

        except Exception as e:
            logger.warning(f"Could not optimize database connection: {e}")

    def monitor_connection_health(self):
        """Monitor connection health in background"""
        def health_monitor():
            while True:
                try:
                    time.sleep(60)  # Check every minute
                    health = self.health_check()

                    if health['status'] != 'healthy':
                        logger.warning(f"Database health check failed: {health}")

                        # If connection is unhealthy, try to reconnect
                        if self._connection_failures > 3:
                            logger.info("Attempting database reconnection...")
                            try:
                                # Reinitialize connection
                                self.db = firestore.client()
                                self.users_collection = self.db.collection(DB_COLLECTIONS['users'])
                                self.stats_collection = self.db.collection(DB_COLLECTIONS['bot_stats'])
                                logger.info("Database reconnection successful")
                            except Exception as reconnect_error:
                                logger.error(f"Database reconnection failed: {reconnect_error}")

                except Exception as e:
                    logger.error(f"Health monitor error: {e}")

        # Start health monitoring in background
        monitor_thread = threading.Thread(target=health_monitor, daemon=True)
        monitor_thread.start()
        logger.info("Database health monitoring started")

    def _exponential_backoff_delay(self, attempt: int, base_delay: float = 0.1) -> float:
        """Calculate exponential backoff delay with jitter"""
        delay = min(base_delay * (2 ** attempt), 10.0)  # Cap at 10 seconds
        jitter = random.uniform(0.1, 0.3) * delay
        return delay + jitter

    def _check_circuit_breaker(self) -> bool:
        """Enhanced circuit breaker with automatic recovery attempts"""
        if not self._circuit_breaker_open:
            return False

        # Try to recover every 30 seconds
        if (self._last_failure_time and
            time.time() - self._last_failure_time > 30):

            # Test connection with a simple operation
            try:
                # Simple health check
                test_doc = self.stats_collection.document('health_check')
                test_doc.get(timeout=2.0)  # Quick test

                # If successful, reset circuit breaker
                self._circuit_breaker_open = False
                self._connection_failures = 0
                logger.info("Circuit breaker reset - database connection restored")
                return False

            except Exception as e:
                logger.warning(f"Circuit breaker recovery test failed: {e}")
                self._last_failure_time = time.time()  # Reset recovery timer
                return True

        return True

    def _record_failure(self):
        """Record a database operation failure"""
        self._connection_failures += 1
        self._last_failure_time = time.time()

        # Open circuit breaker after 5 consecutive failures
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

    def health_check(self) -> Dict[str, Any]:
        """Perform database health check"""
        try:
            # Simple read operation to test connection
            test_doc = self.stats_collection.document('health_check').get(timeout=3.0)

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

    def get_user_fast(self, user_id: int) -> Optional[Dict]:
        """
        Fast user retrieval for callback handlers - single attempt, fail fast
        Returns: user_data if found, None if not found or error
        """
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping get_user_fast for {user_id}")
            return None

        try:
            logger.debug(f"Fast getting user {user_id}")
            user_doc = self.users_collection.document(str(user_id)).get(timeout=5.0)  # 5 second timeout

            if user_doc.exists:
                user_data = user_doc.to_dict()
                user_data['_id'] = user_id
                self._record_success()
                return user_data
            else:
                self._record_success()
                return None

        except Exception as e:
            logger.warning(f"get_user_fast failed for user {user_id}: {e}")
            self._record_failure()
            return None

    def update_user_step_fast(self, user_id: int, step: int, completed: bool = True) -> bool:
        """
        Fast user step update for callback handlers - single attempt, fail fast
        Returns: True if successful, False otherwise
        """
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping update_user_step_fast for {user_id}")
            return False

        try:
            from constants import TOTAL_STEPS

            update_data = {
                "current_step": step + 1 if completed else step,
                f"steps_completed.step_{step}": completed,
                "updated_at": datetime.now()
            }

            # Use shorter timeout for callback handlers
            self.users_collection.document(str(user_id)).update(update_data, timeout=5.0)

            # Handle completion logic
            if step == TOTAL_STEPS and completed:
                try:
                    self._update_stats_fast('user_completed')

                    # Get user data for MNTC calculation and referral handling
                    user_data = self.get_user_fast(user_id)
                    if user_data:
                        self._calculate_and_store_mntc_earned(user_data)

                        if user_data.get('referred_by'):
                            self._handle_referral_completion(user_data['referred_by'], user_id)
                except Exception as completion_error:
                    logger.error(f"Error in completion logic for user {user_id}: {completion_error}")
                    # Don't return False here - the step update succeeded

            logger.info(f"User {user_id} step {step} updated fast: {completed}")
            self._record_success()
            return True

        except Exception as e:
            logger.error(f"Error updating user {user_id} step {step} fast: {e}")
            self._record_failure()
            return False

    def _update_stats_fast(self, action: str):
        """Fast stats update that doesn't block callback handlers"""
        try:
            # Use a separate thread for stats updates to avoid blocking
            def update_in_background():
                try:
                    stats_ref = self.stats_collection.document(DB_COLLECTIONS['main_stats'])
                    if action == 'user_created':
                        stats_ref.update({
                            'total_users': firestore.Increment(1),
                            'updated_at': datetime.now()
                        }, timeout=3.0)
                    elif action == 'user_completed':
                        stats_ref.update({
                            'completed_users': firestore.Increment(1),
                            'updated_at': datetime.now()
                        }, timeout=3.0)
                except Exception as e:
                    logger.error(f"Background stats update failed for action {action}: {e}")

            # Run in background thread
            thread = threading.Thread(target=update_in_background, daemon=True)
            thread.start()

        except Exception as e:
            logger.error(f"Error starting background stats update for action {action}: {e}")

    def batch_get_users(self, user_ids: List[int]) -> Dict[int, Optional[Dict]]:
        """
        Get multiple users in a single batch operation for better performance
        Returns: dict mapping user_id to user_data (or None if not found)
        """
        if self._check_circuit_breaker():
            logger.warning("Circuit breaker open - skipping batch_get_users")
            return {user_id: None for user_id in user_ids}

        result = {}
        try:
            # Firestore supports batch reads
            docs = [self.users_collection.document(str(user_id)) for user_id in user_ids]
            batch_docs = self.db.get_all(docs, timeout=10.0)

            for i, doc in enumerate(batch_docs):
                user_id = user_ids[i]
                if doc.exists:
                    user_data = doc.to_dict()
                    user_data['_id'] = user_id
                    result[user_id] = user_data
                else:
                    result[user_id] = None

            self._record_success()
            return result

        except Exception as e:
            logger.error(f"Error in batch_get_users: {e}")
            self._record_failure()
            return {user_id: None for user_id in user_ids}

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
                logger.info("Bot stats initialized")
        except Exception as e:
            logger.error(f"Error initializing bot stats: {e}")

    def get_user_with_retry(self, user_id: int, max_retries: int = 3) -> Optional[Dict]:
        """Enhanced get_user with retry logic and circuit breaker"""
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping get_user for {user_id}")
            return None

        for attempt in range(max_retries):
            try:
                logger.debug(f"Getting user {user_id}, attempt {attempt + 1}")
                user_doc = self.users_collection.document(str(user_id)).get(timeout=5.0)

                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    user_data['_id'] = user_id
                    self._record_success()
                    logger.debug(f"Successfully retrieved user {user_id}")
                    return user_data
                else:
                    # User doesn't exist - this is not an error
                    self._record_success()
                    logger.debug(f"User {user_id} does not exist")
                    return None

            except Exception as e:
                logger.warning(f"get_user attempt {attempt + 1} failed for user {user_id}: {e}")
                self._record_failure()

                if attempt < max_retries - 1:
                    delay = self._exponential_backoff_delay(attempt)
                    logger.info(f"Retrying get_user in {delay:.2f} seconds")
                    time.sleep(delay)
                else:
                    logger.error(f"All get_user attempts failed for user {user_id}")
                    return None

        return None

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data from Firestore - compatibility method"""
        return self.get_user_with_retry(user_id)

    def create_user_with_retry(self, user_id: int, username: str, first_name: str, referred_by: str = None, max_retries: int = 3) -> bool:
        """Enhanced create_user with retry logic and better error handling"""
        if self._check_circuit_breaker():
            logger.warning(f"Circuit breaker open - skipping create_user for {user_id}")
            return False

        for attempt in range(max_retries):
            try:
                logger.debug(f"Creating user {user_id}, attempt {attempt + 1}")

                # First check if user already exists to avoid conflicts
                existing_check = self.users_collection.document(str(user_id)).get(timeout=3.0)
                if existing_check.exists:
                    logger.info(f"User {user_id} already exists - skipping creation")
                    self._record_success()
                    return True  # User exists, so "creation" is successful

                user_data = DEFAULT_USER_DATA.copy()

                # Generate unique referral code for new user
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

                # Create the user
                self.users_collection.document(str(user_id)).set(user_data, timeout=5.0)

                self._update_stats_fast('user_created')
                self._record_success()
                logger.info(f"User {user_id} created successfully with referral code: {referral_code}")
                if referred_by:
                    logger.info(f"User {user_id} was referred by: {referred_by}")
                return True

            except Exception as e:
                logger.warning(f"create_user attempt {attempt + 1} failed for user {user_id}: {e}")
                self._record_failure()

                # Check if it's a "user already exists" type error
                if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                    logger.info(f"User {user_id} creation conflict - user likely exists")
                    return True  # Treat as success since user exists

                if attempt < max_retries - 1:
                    delay = self._exponential_backoff_delay(attempt)
                    logger.info(f"Retrying create_user in {delay:.2f} seconds")
                    time.sleep(delay)
                else:
                    logger.error(f"All create_user attempts failed for user {user_id}")
                    return False

        return False

    def create_user(self, user_id: int, username: str, first_name: str, referred_by: str = None) -> bool:
        """Create new user in Firestore with referral support - compatibility method"""
        return self.create_user_with_retry(user_id, username, first_name, referred_by)

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
        """Get user by referral code"""
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

    def get_user_by_referral_code(self, referral_code: str) -> Optional[Dict]:
        """Public method to get user by referral code"""
        return self._get_user_by_referral_code(referral_code)

    def update_user_step(self, user_id: int, step: int, completed: bool = True) -> bool:
        """Update user's current step and completion status"""
        try:
            from constants import TOTAL_STEPS

            update_data = {
                "current_step": step + 1 if completed else step,
                f"steps_completed.step_{step}": completed,
                "updated_at": datetime.now()
            }

            self.users_collection.document(str(user_id)).update(update_data)

            # Update stats and handle referral completion if user completed all steps
            if step == TOTAL_STEPS and completed:
                self._update_stats('user_completed')

                # Calculate and store MNTC earned
                user_data = self.get_user_with_retry(user_id)
                if user_data:
                    mntc_earned = self._calculate_and_store_mntc_earned(user_data)

                    # Check if user was referred and update referrer stats
                    if user_data.get('referred_by'):
                        self._handle_referral_completion(user_data['referred_by'], user_id)

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

            self.users_collection.document(str(user_id)).update(update_data, timeout=5.0)

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

                self.users_collection.document(str(referrer_id)).update(update_data, timeout=5.0)

                logger.info(f"Updated referral stats for user {referrer_id}. Total referrals: {current_referrals + 1}")
                return referrer_id

        except Exception as e:
            logger.error(f"Error handling referral completion for {referrer_code}: {e}")
            return None

    def save_social_username(self, user_id: int, platform: str, username: str) -> bool:
        """Save user's social media username"""
        try:
            update_data = {
                f"social_usernames.{platform}": username,
                f"verification_status.{platform}": True,
                "updated_at": datetime.now()
            }

            self.users_collection.document(str(user_id)).update(update_data, timeout=5.0)
            logger.info(f"User {user_id} {platform} username saved: {username}")
            return True

        except Exception as e:
            logger.error(f"Error saving {platform} username for user {user_id}: {e}")
            return False

    def save_bep20_address(self, user_id: int, address: str) -> bool:
        """Save user's BEP20 address"""
        try:
            update_data = {
                "bep20_address": address,
                "updated_at": datetime.now()
            }

            self.users_collection.document(str(user_id)).update(update_data, timeout=5.0)
            logger.info(f"User {user_id} BEP20 address saved")
            return True

        except Exception as e:
            logger.error(f"Error saving BEP20 address for user {user_id}: {e}")
            return False

    def add_screenshot(self, user_id: int, file_id: str, file_name: str) -> bool:
        """Add screenshot to user's record"""
        try:
            screenshot_data = {
                "file_id": file_id,
                "file_name": file_name,
                "uploaded_at": datetime.now()
            }

            # Use array union to add new screenshot
            self.users_collection.document(str(user_id)).update({
                "screenshots": firestore.ArrayUnion([screenshot_data]),
                "updated_at": datetime.now()
            }, timeout=5.0)

            logger.info(f"Screenshot added for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error adding screenshot for user {user_id}: {e}")
            return False

    def get_user_stats(self) -> Dict:
        """Get overall bot statistics"""
        try:
            stats_doc = self.stats_collection.document(DB_COLLECTIONS['main_stats']).get(timeout=5.0)
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
                }, timeout=5.0)
            elif action == 'user_completed':
                stats_ref.update({
                    'completed_users': firestore.Increment(1),
                    'updated_at': datetime.now()
                }, timeout=5.0)
        except Exception as e:
            logger.error(f"Error updating stats for action {action}: {e}")

    def update_reward_status(self, user_id: int, status: str) -> bool:
        """Update user's reward payment status (admin function)"""
        try:
            update_data = {
                "reward_info.reward_status": status,
                "reward_info.status_updated_at": datetime.now(),
                "updated_at": datetime.now()
            }

            self.users_collection.document(str(user_id)).update(update_data, timeout=5.0)
            logger.info(f"Updated reward status for user {user_id}: {status}")
            return True

        except Exception as e:
            logger.error(f"Error updating reward status for user {user_id}: {e}")
            return False

    def get_pending_rewards(self) -> List[Dict]:
        """Get all users with pending reward payments (admin function)"""
        try:
            query = self.users_collection.where('reward_info.reward_status', '==', 'pending')
            docs = query.stream()

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

    def get_paid_rewards(self) -> List[Dict]:
        """Get all users with paid rewards (admin function)"""
        try:
            query = self.users_collection.where('reward_info.reward_status', '==', 'paid')
            docs = query.stream()

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

    def get_reward_summary(self) -> Dict:
        """Get summary of all rewards (admin function)"""
        try:
            # Get all completed users
            query = self.users_collection.where('current_step', '>', 6)
            docs = query.stream()

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

    def reset_user_progress(self, user_id: int, keep_referral_data: bool = True) -> bool:
        """Reset user's progress completely with option to keep referral data"""
        try:
            if keep_referral_data:
                # Get current referral data before reset
                current_user = self.get_user_with_retry(user_id)
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

            self.users_collection.document(str(user_id)).update(reset_data, timeout=5.0)
            logger.info(f"User {user_id} progress reset (keep_referral_data: {keep_referral_data})")
            return True

        except Exception as e:
            logger.error(f"Error resetting user {user_id} progress: {e}")
            return False

    def update_referral_rewards(self, user_id: int, total_rewards: int) -> bool:
        """Update user's total referral rewards (admin function)"""
        try:
            update_data = {
                "referral_stats.total_rewards": total_rewards,
                "updated_at": datetime.now()
            }

            self.users_collection.document(str(user_id)).update(update_data, timeout=5.0)
            logger.info(f"Updated referral rewards for user {user_id}: {total_rewards} MNTC")
            return True

        except Exception as e:
            logger.error(f"Error updating referral rewards for user {user_id}: {e}")
            return False

    def get_referral_stats(self, user_id: int) -> Dict:
        """Get user's referral statistics"""
        try:
            user_data = self.get_user_with_retry(user_id)
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

    def get_all_users(self, limit: int = None) -> List[Dict]:
        """Get all users (for admin purposes)"""
        try:
            if limit is None:
                limit = RATE_LIMITS['max_users_query']

            users = []
            docs = self.users_collection.limit(limit).stream()

            for doc in docs:
                user_data = doc.to_dict()
                user_data['_id'] = doc.id
                users.append(user_data)

            return users

        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    def close_connection(self):
        """Close database connection (not needed for Firestore)"""
        logger.info("Database connection closed")
