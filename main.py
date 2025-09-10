import logging
import logging.config
import asyncio
import signal
import sys
import time
import os
import psutil
import weakref
from datetime import datetime, timedelta
from collections import deque, defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut, Conflict
from database import OptimizedDatabase
from validators import Validators
import config
from constants import (
    TOTAL_STEPS,
    CALLBACK_DATA,
    MESSAGE_TEMPLATES,
    HELP_TEMPLATES,
    STATUS_TEMPLATE,
    STATS_TEMPLATE,
    STATUS_ICONS,
    EMOJIS,
    SOCIAL_LINKS,
    STEPS,
    WELCOME_MESSAGE,
    WELCOME_MESSAGE_REFERRED,
    REFERRAL_MESSAGES,
    REFERRAL_STATS_TEMPLATE,
    REFERRAL_CONFIG
)

# Configure logging
logging.config.dictConfig(config.LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# Global variables for cleanup
db = None
validators = None

class MessageCache:
    """Pre-built message cache to reduce memory usage"""
    def __init__(self):
        self.cached_steps = {}
        self.cached_keyboards = {}
        self._build_cache()
        
    def _build_cache(self):
        """Pre-build all step messages and keyboards"""
        for step in range(1, TOTAL_STEPS + 1):
            self.cached_steps[step] = self._build_step_message(step)
            self.cached_keyboards[step] = self._build_step_keyboard(step)
    
    def _build_step_message(self, step):
        step_message = STEPS.get(step, "Invalid step")
        if step == 6:
            step_message = step_message.format("Minativerseofficial")
        return f"**Step {step}/{TOTAL_STEPS}** {EMOJIS['target']}\n\n{step_message}"
    
    def _build_step_keyboard(self, step):
        keyboard = []
        if step == 1:
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['mobile']} Download App", url=SOCIAL_LINKS['app_download'])],
                [InlineKeyboardButton(f"{EMOJIS['checkmark']} Downloaded & Reviewed", callback_data=CALLBACK_DATA['verify_step_1'])]
            ]
        elif step == 2:
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['twitter']} Follow on Twitter", url=SOCIAL_LINKS['twitter'])],
                [InlineKeyboardButton(f"{EMOJIS['info']} Send Username After Following", callback_data=CALLBACK_DATA['twitter_info'])],
                [InlineKeyboardButton(f"{EMOJIS['question']} Need Help", callback_data=CALLBACK_DATA['help'])]
            ]
        elif step == 3:
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['instagram']} Follow on Instagram", url=SOCIAL_LINKS['instagram'])],
                [InlineKeyboardButton(f"{EMOJIS['info']} Send Username After Following", callback_data=CALLBACK_DATA['instagram_info'])]
            ]
        elif step == 4:
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} Visit CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])],
                [InlineKeyboardButton(f"{EMOJIS['info']} Send User ID After Following", callback_data=CALLBACK_DATA['coinmarketcap_info'])]
            ]
        elif step == 5:
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['info']} Send BEP20 Address", callback_data=CALLBACK_DATA['bep20_info'])]
            ]
        elif step == 6:
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['party']} Complete Process", callback_data=CALLBACK_DATA['complete_process'])]
            ]
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['question']} Need Help", callback_data=CALLBACK_DATA['help'])])
        return InlineKeyboardMarkup(keyboard)
    
    def get_step_content(self, step):
        return self.cached_steps.get(step), self.cached_keyboards.get(step)

class CompressedUserState:
    """Lightweight user state for emergency situations"""
    __slots__ = ['user_id', 'step', 'data', 'timestamp']
    
    def __init__(self, user_id, step=1):
        self.user_id = user_id
        self.step = step
        self.data = {}
        self.timestamp = time.time()
    
    def is_expired(self, timeout=1800):  # 30 minutes
        return time.time() - self.timestamp > timeout
    
    def update_timestamp(self):
        self.timestamp = time.time()

class EmergencyQueue:
    """High-performance request queue for traffic spikes"""
    def __init__(self, max_queue_size=1000):
        self.queue = deque(maxlen=max_queue_size)
        self.processing = False
        self.max_concurrent_workers = 50
        self.processed_count = 0
        
    async def add_request(self, request_type, user_id, update, context):
        current_time = time.time()
        
        if len(self.queue) >= 950:  # 95% full - emergency mode
            if hasattr(update, 'message') and update.message:
                try:
                    await update.message.reply_text(
                        "🔥 **High Traffic Alert!**\n\n"
                        "Our servers are experiencing high load. Please try again in 2-3 minutes.\n\n"
                        "💡 **Tip**: Join @Minatirewards for real-time updates!\n\n"
                        "⚡ Your progress is saved automatically.",
                        parse_mode='Markdown'
                    )
                except Exception:
                    pass  # Ignore if we can't send message
            return False
        
        self.queue.append({
            'type': request_type,
            'user_id': user_id,
            'update': update,
            'context': context,
            'timestamp': current_time
        })
        
        if not self.processing:
            asyncio.create_task(self.process_queue())
        return True
    
    async def process_queue(self):
        if self.processing:
            return
            
        self.processing = True
        workers = []
        
        try:
            for _ in range(min(self.max_concurrent_workers, len(self.queue))):
                workers.append(asyncio.create_task(self.worker()))
            
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
        finally:
            self.processing = False
    
    async def worker(self):
        while self.queue:
            try:
                request = self.queue.popleft()
                
                # Drop requests older than 5 minutes
                if time.time() - request['timestamp'] > 300:
                    continue
                
                # Process the request
                await self.process_request(request)
                self.processed_count += 1
                
                # Small delay to prevent CPU hogging
                await asyncio.sleep(0.01)
                
            except IndexError:
                break
            except Exception as e:
                logger.error(f"Queue worker error: {e}")
    
    async def process_request(self, request):
        """This will be set by the bot instance"""
        pass

class TrafficMonitor:
    """Real-time traffic monitoring and alerts"""
    def __init__(self):
        self.requests_per_minute = deque(maxlen=60)
        self.active_users = {}
        self.start_time = time.time()
        self.total_requests = 0
        
    def log_request(self, user_id):
        current_time = time.time()
        current_minute = int(current_time / 60)
        
        self.requests_per_minute.append(current_minute)
        self.active_users[user_id] = current_time
        self.total_requests += 1
        
        # Clean old users (>5 minutes inactive)
        cutoff_time = current_time - 300
        self.active_users = {uid: timestamp for uid, timestamp in self.active_users.items() 
                           if timestamp > cutoff_time}
    
    def get_traffic_stats(self):
        current_time = time.time()
        rpm = len([r for r in self.requests_per_minute if current_time - r * 60 < 60])
        
        try:
            memory_info = psutil.Process().memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            memory_percent = psutil.virtual_memory().percent
        except:
            memory_mb = 0
            memory_percent = 0
        
        return {
            'requests_per_minute': rpm,
            'active_users': len(self.active_users),
            'total_requests': self.total_requests,
            'uptime_hours': (current_time - self.start_time) / 3600,
            'memory_usage_mb': memory_mb,
            'memory_percent': memory_percent,
            'queue_size': getattr(self, 'queue_size', 0)
        }
    
    def should_upgrade_plan(self):
        stats = self.get_traffic_stats()
        
        if stats['requests_per_minute'] > 200:
            return "Standard Plan ($25) - High traffic detected"
        if stats['active_users'] > 300:
            return "Pro Plan ($85) - Too many concurrent users"
        if stats['memory_percent'] > 85:
            return "Standard Plan ($25) - Memory pressure"
        
        return None

class OptimizedMinatiVaultBot:
    def __init__(self):
        self.db = None
        self.validators = None
        self.application = None
        self.running = False
        
        # Emergency optimizations
        self.emergency_mode = False
        self.message_cache = MessageCache()
        self.emergency_queue = EmergencyQueue()
        self.traffic_monitor = TrafficMonitor()
        
        # Memory-efficient session management
        self.active_sessions = weakref.WeakValueDictionary()
        self.processing_semaphore = asyncio.BoundedSemaphore(200)
        self.user_rate_limits = defaultdict(list)
        self.compressed_states = {}
        
        # Rate limiting
        self._last_start_time = None
        self._last_start_user = None
        self._global_rate_limit = deque(maxlen=100)
        
        # Set up queue processor
        self.emergency_queue.process_request = self.process_queued_request

    async def initialize_services_async(self):
        """Initialize services asynchronously"""
        try:
            # Initialize validators first (no external dependencies)
            self.validators = Validators()
            logger.info("✅ Validators initialized successfully")
            
            # Initialize optimized database
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.db = OptimizedDatabase()
                    logger.info("✅ Optimized Database initialized successfully")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Database init attempt {attempt + 1} failed: {e}. Retrying...")
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"❌ Failed to initialize database after {max_retries} attempts: {e}")
                        raise
            
            # Start background monitoring
            asyncio.create_task(self.background_monitor())
            
        except Exception as e:
            logger.error(f"❌ Service initialization failed: {e}")
            raise

    async def background_monitor(self):
        """Background monitoring and cleanup"""
        while self.running:
            try:
                # Memory monitoring
                stats = self.traffic_monitor.get_traffic_stats()
                self.traffic_monitor.queue_size = len(self.emergency_queue.queue)
                
                if stats['memory_percent'] > 85:
                    self.emergency_mode = True
                    logger.warning(f"🚨 EMERGENCY MODE: Memory at {stats['memory_percent']}%")
                elif stats['memory_percent'] < 70:
                    self.emergency_mode = False
                
                # Cleanup compressed states
                self.cleanup_compressed_states()
                
                # Log stats every minute
                if int(time.time()) % 60 == 0:
                    logger.info(f"📊 Stats: {stats['active_users']} users, "
                              f"{stats['requests_per_minute']} req/min, "
                              f"{stats['memory_usage_mb']:.1f}MB memory")
                
                # Check for upgrade recommendation
                upgrade_rec = self.traffic_monitor.should_upgrade_plan()
                if upgrade_rec:
                    logger.warning(f"💡 UPGRADE RECOMMENDED: {upgrade_rec}")
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Background monitor error: {e}")
                await asyncio.sleep(60)

    def cleanup_compressed_states(self):
        """Clean up expired compressed states"""
        expired = [uid for uid, state in self.compressed_states.items() if state.is_expired()]
        for uid in expired:
            del self.compressed_states[uid]
        
        # Limit total states
        if len(self.compressed_states) > 1000:
            # Remove oldest states
            sorted_states = sorted(self.compressed_states.items(), key=lambda x: x[1].timestamp)
            for uid, _ in sorted_states[:200]:  # Remove oldest 200
                del self.compressed_states[uid]

    async def get_user_state(self, user_id):
        """Get compressed user state for emergency situations"""
        if user_id not in self.compressed_states:
            self.compressed_states[user_id] = CompressedUserState(user_id)
        
        state = self.compressed_states[user_id]
        state.update_timestamp()
        return state

    async def emergency_memory_check(self):
        """Emergency memory protection"""
        try:
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > 90:
                # Emergency: Clear all non-essential data
                self.compressed_states.clear()
                self.user_rate_limits.clear()
                logger.error(f"🚨 CRITICAL MEMORY: {memory_percent}% - Emergency cleanup performed")
                return True
        except:
            pass
        return False

    async def rate_limit_check(self, user_id):
        """Enhanced rate limiting"""
        current_time = time.time()
        
        # Global rate limiting
        self._global_rate_limit.append(current_time)
        recent_requests = [t for t in self._global_rate_limit if current_time - t < 60]
        
        if len(recent_requests) > 500:  # Max 500 requests per minute globally
            return False, "🔥 System overloaded. Please try again in 1 minute."
        
        # Per-user rate limiting
        user_requests = self.user_rate_limits[user_id]
        user_requests[:] = [t for t in user_requests if current_time - t < 2]
        
        if len(user_requests) >= 1:
            return False, "⏱️ Please wait 2 seconds between actions."
        
        user_requests.append(current_time)
        return True, None

    async def process_queued_request(self, request):
        """Process requests from the emergency queue"""
        try:
            request_type = request['type']
            user_id = request['user_id']
            update = request['update']
            context = request['context']
            
            # Rate limiting
            allowed, message = await self.rate_limit_check(user_id)
            if not allowed:
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(message)
                return
            
            # Route to appropriate handler
            if request_type == 'start':
                await self._handle_start_internal(update, context)
            elif request_type == 'message':
                await self._handle_message_internal(update, context)
            elif request_type == 'callback':
                await self._handle_callback_internal(update, context)
                
        except Exception as e:
            logger.error(f"Error processing queued request: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Optimized start command with queue system"""
        user_id = update.effective_user.id
        
        # Emergency memory check
        if await self.emergency_memory_check():
            await update.message.reply_text(
                "🚨 **System Maintenance**\n\n"
                "We're experiencing high traffic. Please try again in 5 minutes.\n\n"
                "Join @Minatirewards for updates."
            )
            return
        
        # Log traffic
        self.traffic_monitor.log_request(user_id)
        
        # Queue the request
        success = await self.emergency_queue.add_request('start', user_id, update, context)
        if not success:
            return  # User already notified by queue system

    async def _handle_start_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Internal start handler - optimized version"""
        user = update.effective_user
        user_id = user.id
        username = user.username or "No username"
        first_name = user.first_name or "User"
        
        # Rate limiting for start command
        current_time = datetime.now()
        if (self._last_start_time and self._last_start_user == user_id and 
            (current_time - self._last_start_time).total_seconds() < 3):
            return
        
        self._last_start_time = current_time
        self._last_start_user = user_id

        # Extract referral code
        referral_code = None
        if context.args and len(context.args) > 0:
            potential_referral = context.args[0]
            if self.validators.is_valid_referral_link_param(potential_referral):
                referral_code = self.validators.extract_referral_code_from_start_param(potential_referral)

        logger.info(f"User {user_id} ({first_name}) started the bot")

        # Use semaphore to limit concurrent processing
        async with self.processing_semaphore:
            # Quick user check with single retry
            existing_user = await self.db.get_user_with_retry(user_id, max_retries=1)

            if not existing_user:
                # Handle new user creation
                await self._handle_new_user(user_id, username, first_name, referral_code, update)
            else:
                # Handle existing user
                await self._handle_existing_user(existing_user, first_name, referral_code, update, context)

    async def _handle_new_user(self, user_id, username, first_name, referral_code, update):
        """Handle new user creation - optimized"""
        referred_by = None
        if referral_code:
            try:
                referrer = await self.db.get_user_by_referral_code(referral_code)
                if referrer:
                    if referrer['user_id'] == user_id:
                        await update.message.reply_text(f"{EMOJIS['cross']} You cannot use your own referral code!")
                        return
                    referred_by = referral_code
                else:
                    await update.message.reply_text(f"{EMOJIS['cross']} Invalid referral code.")
                    return
            except Exception as e:
                logger.error(f"Error validating referral code: {e}")
                await update.message.reply_text(f"{EMOJIS['warning']} Unable to process referral code.")

        # Attempt user creation with single retry
        try:
            creation_success = await self.db.create_user_with_retry(user_id, username, first_name, referred_by, max_retries=1)
            
            if creation_success:
                welcome_msg = WELCOME_MESSAGE_REFERRED if referred_by else WELCOME_MESSAGE
                await update.message.reply_text(f"Welcome {first_name}! {EMOJIS['party']}\n\n{welcome_msg}")
                await self.show_step_optimized(update, 1)
            else:
                await update.message.reply_text(
                    f"{EMOJIS['cross']} Registration temporarily unavailable. Please try again in 1 minute."
                )
        except Exception as e:
            logger.error(f"User creation failed for {user_id}: {e}")
            await update.message.reply_text(
                f"{EMOJIS['warning']} Service temporarily busy. Please try again in 2 minutes."
            )

    async def _handle_existing_user(self, existing_user, first_name, referral_code, update, context):
        """Handle existing user - optimized"""
        user_id = existing_user['user_id']
        current_step = existing_user.get('current_step', 1)
        
        if referral_code:
            await update.message.reply_text(
                f"Welcome back {first_name}! {EMOJIS['fire']}\n\n"
                f"ℹ️ Referral links can only be used by new users. "
                f"Continuing with your existing progress.\n\n"
                f"Current step: {current_step}/{TOTAL_STEPS}"
            )
        else:
            await update.message.reply_text(
                f"Welcome back {first_name}! {EMOJIS['fire']}\n\n"
                f"Current step: {current_step}/{TOTAL_STEPS}"
            )

        if current_step > TOTAL_STEPS:
            await self.show_completion_with_referral_optimized(update, existing_user)
        else:
            await self.show_step_optimized(update, current_step)

    async def show_step_optimized(self, update, step):
        """Optimized step display using cached messages"""
        if step > TOTAL_STEPS:
            try:
                user_data = await self.db.get_user_with_retry(update.effective_user.id, max_retries=1)
                if user_data:
                    await self.show_completion_with_referral_optimized(update, user_data)
                else:
                    await update.message.reply_text(
                        f"{EMOJIS['party']} Congratulations! All steps completed!\n\n"
                        f"Support: @Minatirewards",
                        parse_mode='Markdown'
                    )
            except Exception as e:
                logger.error(f"Error showing completion: {e}")
            return

        # Use cached message and keyboard
        message, keyboard = self.message_cache.get_step_content(step)
        
        if step == 6:
            # Check completion requirements for step 6
            try:
                user_data = await self.db.get_user_with_retry(update.effective_user.id, max_retries=1)
                if user_data:
                    can_complete, missing_fields = self._check_completion_requirements(user_data)
                    if not can_complete:
                        message += f"\n\n⚠️ **Missing Information:**\n"
                        for field in missing_fields:
                            message += f"• {field}\n"
                        message += f"\nPlease complete all previous steps first."
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"{EMOJIS['refresh']} Check Status", callback_data=CALLBACK_DATA['show_status'])]
                        ])
            except Exception as e:
                logger.error(f"Error checking completion requirements: {e}")

        try:
            await update.message.reply_text(
                message,
                reply_markup=keyboard,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Error sending step message: {e}")
            # Fallback simple message
            await update.message.reply_text(f"Step {step}/{TOTAL_STEPS} - Use /status to check progress")

    def _check_completion_requirements(self, user_data):
        """Check if user can complete the process"""
        social_usernames = user_data.get('social_usernames', {})
        bep20_address = user_data.get('bep20_address')
        missing_fields = []
        
        if not social_usernames.get('twitter'):
            missing_fields.append('Twitter username')
        if not social_usernames.get('instagram'):
            missing_fields.append('Instagram username')
        if not social_usernames.get('coinmarketcap'):
            missing_fields.append('CoinMarketCap User ID')
        if not bep20_address:
            missing_fields.append('BEP20 address')
            
        return len(missing_fields) == 0, missing_fields

    async def show_completion_with_referral_optimized(self, update, user_data):
        """Optimized completion message"""
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['stats']} View Status", callback_data=CALLBACK_DATA['show_status'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        completion_text = f"""
{EMOJIS['party']} **Congratulations!** {EMOJIS['party']}

You have completed all steps!

**🎁 Your Referral Link:**
`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={user_data.get('referral_code')}`

**📊 Referral Stats:**
• Successful Referrals: **{referral_stats['total_referrals']}**
• Referral Rewards: **{referral_stats['total_referrals']*2} MNTC**

✅ Join our community: @Minatirewards

{EMOJIS['phone']} Support: @Minatirewards
"""

        try:
            await update.message.reply_text(
                completion_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending completion message: {e}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Optimized message handler with queue system"""
        user_id = update.effective_user.id
        self.traffic_monitor.log_request(user_id)
        
        # Queue the request
        success = await self.emergency_queue.add_request('message', user_id, update, context)
        if not success:
            return

    async def _handle_message_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Internal message handler - optimized"""
        user_id = update.effective_user.id
        message_text = update.message.text.strip()
        
        async with self.processing_semaphore:
            try:
                # Quick user data fetch
                user_data = await self.db.get_user_with_retry(user_id, max_retries=1)
                
                if not user_data:
                    await update.message.reply_text(f"{EMOJIS['cross']} Please use /start command first.")
                    return

                current_step = user_data.get('current_step', 1)
                
                # Process based on current step
                if current_step == 2:
                    await self._handle_twitter_username(update, user_id, message_text)
                elif current_step == 3:
                    await self._handle_instagram_username(update, user_id, message_text)
                elif current_step == 4:
                    await self._handle_coinmarketcap_userid(update, user_id, message_text)
                elif current_step == 5:
                    await self._handle_bep20_address(update, user_id, message_text)
                else:
                    await update.message.reply_text(
                        f"{EMOJIS['target']} Current step: {current_step}/{TOTAL_STEPS}\n\n"
                        f"Use /status to check your progress.",
                        parse_mode='Markdown'
                    )
                    
            except Exception as e:
                logger.error(f"Error handling message for user {user_id}: {e}")
                await update.message.reply_text(
                    f"{EMOJIS['warning']} Temporary error. Please try again in 30 seconds."
                )

    async def _handle_twitter_username(self, update, user_id, message_text):
        """Handle Twitter username submission"""
        username = message_text.lstrip('@').strip()
        is_valid, validation_message = self.validators.validate_username(username)

        if is_valid:
            # Simplified verification (always passes for demo)
            try:
                success = await self.db.save_social_username(user_id, 'twitter', username)
                if success:
                    await self.db.update_user_step(user_id, 2, True)
                    await update.message.reply_text(
                        f"{EMOJIS['checkmark']} *Twitter Verified!*\n\n"
                        f"Username: @{username}\n\n"
                        "Moving to next step...",
                        parse_mode='Markdown'
                    )
                    await self.show_step_optimized(update, 3)
                else:
                    await update.message.reply_text("❌ Error saving username. Please try again.")
            except Exception as e:
                logger.error(f"Error saving Twitter username: {e}")
                await update.message.reply_text("❌ Temporary error. Please try again.")
        else:
            await update.message.reply_text(f"❌ Invalid username: {validation_message}")

    async def _handle_instagram_username(self, update, user_id, message_text):
        """Handle Instagram username submission"""
        username = message_text.lstrip('@').strip()
        is_valid, validation_message = self.validators.validate_username(username)

        if is_valid:
            try:
                success = await self.db.save_social_username(user_id, 'instagram', username)
                if success:
                    await self.db.update_user_step(user_id, 3, True)
                    await update.message.reply_text(
                        f"{EMOJIS['checkmark']} *Instagram Verified!*\n\n"
                        f"Username: @{username}\n\n"
                        "Moving to next step...",
                        parse_mode='Markdown'
                    )
                    await self.show_step_optimized(update, 4)
                else:
                    await update.message.reply_text("❌ Error saving username. Please try again.")
            except Exception as e:
                logger.error(f"Error saving Instagram username: {e}")
                await update.message.reply_text("❌ Temporary error. Please try again.")
        else:
            await update.message.reply_text(f"❌ Invalid username: {validation_message}")

    async def _handle_coinmarketcap_userid(self, update, user_id, message_text):
        """Handle CoinMarketCap User ID submission"""
        userid = message_text.strip()
        is_valid, validation_message = self.validators.validate_coinmarketcap_userid(userid)

        if is_valid:
            try:
                success = await self.db.save_social_username(user_id, 'coinmarketcap', userid)
                if success:
                    await self.db.update_user_step(user_id, 4, True)
                    await update.message.reply_text(
                        f"{EMOJIS['checkmark']} *CoinMarketCap Verified!*\n\n"
                        f"User ID: {userid}\n\n"
                        "Moving to next step...",
                        parse_mode='Markdown'
                    )
                    await self.show_step_optimized(update, 5)
                else:
                    await update.message.reply_text("❌ Error saving User ID. Please try again.")
            except Exception as e:
                logger.error(f"Error saving CoinMarketCap userid: {e}")
                await update.message.reply_text("❌ Temporary error. Please try again.")
        else:
            await update.message.reply_text(f"❌ Invalid User ID: {validation_message}")

    async def _handle_bep20_address(self, update, user_id, message_text):
        """Handle BEP20 address submission"""
        is_valid, message = self.validators.validate_bep20_address(message_text)

        if is_valid:
            try:
                success = await self.db.save_bep20_address(user_id, message_text)
                if success:
                    await self.db.update_user_step(user_id, 5, True)
                    await update.message.reply_text(
                        f"{EMOJIS['checkmark']} *BEP20 Address Saved!*\n\n"
                        f"Address: `{message_text}`\n\n"
                        "Moving to final step...",
                        parse_mode='Markdown'
                    )
                    await self.show_step_optimized(update, 6)
                else:
                    await update.message.reply_text("❌ Error saving address. Please try again.")
            except Exception as e:
                logger.error(f"Error saving BEP20 address: {e}")
                await update.message.reply_text("❌ Temporary error. Please try again.")
        else:
            await update.message.reply_text(
                f"❌ Invalid BEP20 Address: {message}\n\n"
                "• Must start with 0x\n"
                "• Must be 42 characters long\n"
                "• Example: 0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52"
            )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Optimized button handler with queue system"""
        user_id = update.callback_query.from_user.id
        self.traffic_monitor.log_request(user_id)
        
        # Queue the request
        success = await self.emergency_queue.add_request('callback', user_id, update, context)
        if not success:
            try:
                await update.callback_query.answer("System busy, please try again in 1 minute.")
            except:
                pass
            return

    async def _handle_callback_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Internal callback handler - optimized"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        
        async with self.processing_semaphore:
            try:
                user_data = await self.db.get_user_with_retry(user_id, max_retries=1)

                if not user_data:
                    await query.edit_message_text("❌ User not found. Please use /start command.")
                    return

                current_step = user_data.get('current_step', 1)

                # Handle different button callbacks
                if query.data == CALLBACK_DATA['verify_step_1']:
                    await self._handle_step1_verification(query, user_id, current_step, context)
                elif query.data == CALLBACK_DATA['complete_process']:
                    await self._handle_process_completion(query, user_id, current_step)
                elif query.data in [CALLBACK_DATA['twitter_info'], CALLBACK_DATA['instagram_info'], 
                                  CALLBACK_DATA['coinmarketcap_info'], CALLBACK_DATA['bep20_info']]:
                    await self._handle_info_buttons(query)
                elif query.data == CALLBACK_DATA['show_status']:
                    await self._handle_status_callback(query, user_id)
                elif query.data == CALLBACK_DATA['help']:
                    await self._handle_help_callback(query)
                    
            except Exception as e:
                logger.error(f"Error handling callback for user {user_id}: {e}")
                try:
                    await query.edit_message_text("❌ Temporary error. Please try again.")
                except:
                    pass

    async def _handle_step1_verification(self, query, user_id, current_step, context):
        """Handle step 1 verification"""
        if current_step == 1:
            try:
                await self.db.update_user_step(user_id, 1, True)
                await query.edit_message_text(f"{EMOJIS['checkmark']} Great! App download confirmed.\n\nMoving to next step...")
                
                # Send Step 2 as a new message
                message, keyboard = self.message_cache.get_step_content(2)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=keyboard,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Error in step 1 verification: {e}")
                await query.edit_message_text("❌ Error processing verification. Please try again.")
        else:
            await query.edit_message_text(f"❌ You're not on step 1. Current step: {current_step}")

    async def _handle_process_completion(self, query, user_id, current_step):
        """Handle process completion"""
        if current_step == 6:
            try:
                await self.db.update_user_step(user_id, 6, True)
                fresh_user_data = await self.db.get_user_with_retry(user_id, max_retries=1)
                if fresh_user_data:
                    await self._send_completion_message_optimized(query, fresh_user_data)
                else:
                    await query.edit_message_text(f"{EMOJIS['party']} Congratulations! Process completed!")
            except Exception as e:
                logger.error(f"Error completing process: {e}")
                await query.edit_message_text("❌ Error completing process. Please contact support.")
        elif current_step > 6:
            try:
                user_data = await self.db.get_user_with_retry(user_id, max_retries=1)
                if user_data:
                    await self._send_completion_message_optimized(query, user_data)
                else:
                    await query.edit_message_text(f"{EMOJIS['party']} Already completed!")
            except Exception as e:
                logger.error(f"Error showing completion: {e}")
        else:
            await query.edit_message_text(
                f"❌ Complete all previous steps first.\n\nCurrent step: {current_step}/6\n\nUse /status to check progress."
            )

    async def _send_completion_message_optimized(self, query, user_data):
        """Send optimized completion message"""
        social_usernames = user_data.get('social_usernames', {})
        bep20_address = user_data.get('bep20_address', '')
        is_referred = user_data.get('is_referred', False)
        referral_code = user_data.get('referral_code', '')
        reward_info = user_data.get('reward_info', {})
        mntc_earned = reward_info.get('mntc_earned', 0)

        if mntc_earned == 0:
            mntc_earned = REFERRAL_CONFIG['referred_reward'] if is_referred else REFERRAL_CONFIG['normal_reward']

        try:
            completion_message = f"""
🎉 **CONGRATULATIONS!** 🎉

You have successfully completed all steps!

**Your Submitted Information:**
🐦 Twitter: @{social_usernames.get('twitter', 'Not provided')}
📸 Instagram: @{social_usernames.get('instagram', 'Not provided')}
📊 CoinMarketCap: @{social_usernames.get('coinmarketcap', 'Not provided')}
🏦 BEP20 Address: `{bep20_address[:10]}...{bep20_address[-6:] if bep20_address else 'Not provided'}`

**💰 Your Reward:** {mntc_earned} MNTC

**🎁 Your Referral Link:**
`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={referral_code}`

**💰 Referral Rewards:**
• You get **+2 MNTC** for each successful referral

✅ Join our community: @Minatirewards

📞 **Support:** @Minatirewards
🌐 **Website:** {SOCIAL_LINKS['website']}

Thank you for using Minati Vault Bot! 🚀
"""

            await query.edit_message_text(completion_message, parse_mode='Markdown')

            # Notify referrer if user was referred
            if is_referred and user_data.get('referred_by'):
                asyncio.create_task(self._notify_referrer_optimized(user_data.get('referred_by'), user_data['user_id']))

        except Exception as e:
            logger.error(f"Error sending completion message: {e}")
            await query.edit_message_text(f"{EMOJIS['party']} **CONGRATULATIONS!** Process completed! 🚀")

    async def _notify_referrer_optimized(self, referrer_code, completed_user_id):
        """Notify referrer about successful referral completion"""
        try:
            referrer = await self.db.get_user_by_referral_code(referrer_code)
            if not referrer:
                return

            referrer_id = referrer['user_id']
            referral_stats = referrer.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

            notification_message = f"""
🎉 **New Referral Success!** 🎉

Someone you referred has completed all verification steps!

**📊 Your Updated Referral Stats:**
• Total Successful Referrals: **{referral_stats['total_referrals']}**
• Total Referral Rewards: **{referral_stats['total_rewards']} MNTC**

Keep sharing your referral link to earn more rewards! 💰

**🎁 Your Referral Link:**
`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={referrer['referral_code']}`
"""

            await self.application.bot.send_message(
                chat_id=referrer_id,
                text=notification_message,
                parse_mode='Markdown'
            )

            logger.info(f"Notified referrer {referrer_id} about successful referral from user {completed_user_id}")

        except Exception as e:
            logger.error(f"Error notifying referrer {referrer_code}: {e}")

    async def _handle_info_buttons(self, query):
        """Handle info button callbacks"""
        info_messages = {
            CALLBACK_DATA['twitter_info']: HELP_TEMPLATES['instructions']['twitter'],
            CALLBACK_DATA['instagram_info']: HELP_TEMPLATES['instructions']['instagram'],
            CALLBACK_DATA['coinmarketcap_info']: HELP_TEMPLATES['instructions']['coinmarketcap'],
            CALLBACK_DATA['bep20_info']: HELP_TEMPLATES['instructions']['bep20']
        }
        
        message = info_messages.get(query.data, "Information not available.")
        await query.edit_message_text(message, parse_mode='Markdown')

    async def _handle_status_callback(self, query, user_id):
        """Handle status callback - simplified version"""
        try:
            user_data = await self.db.get_user_with_retry(user_id, max_retries=1)
            if not user_data:
                await query.edit_message_text("❌ User data not found.")
                return

            current_step = user_data.get('current_step', 1)
            steps_completed = user_data.get('steps_completed', {})
            completed_count = len(steps_completed)

            status_text = f"""
📊 **Your Progress Status**

**Current Step:** {current_step}/{TOTAL_STEPS}
**Completed Steps:** {completed_count}/{TOTAL_STEPS}

**Progress:**
{'✅' if steps_completed.get('step_1') else '❌'} Step 1: App Download
{'✅' if steps_completed.get('step_2') else '❌'} Step 2: Twitter Follow
{'✅' if steps_completed.get('step_3') else '❌'} Step 3: Instagram Follow
{'✅' if steps_completed.get('step_4') else '❌'} Step 4: CoinMarketCap
{'✅' if steps_completed.get('step_5') else '❌'} Step 5: BEP20 Address
{'✅' if steps_completed.get('step_6') else '❌'} Step 6: Final Verification

**Next Action:** {"All completed! 🎉" if current_step > TOTAL_STEPS else f"Continue with Step {current_step}"}
"""

            keyboard = [[InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(status_text, parse_mode='Markdown', reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error showing status: {e}")
            await query.edit_message_text("❌ Error retrieving status. Please try again.")

    async def _handle_help_callback(self, query):
        """Handle help callback"""
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['phone']} Support", url=SOCIAL_LINKS['support'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website']),
             InlineKeyboardButton(f"{EMOJIS['mobile']} Download App", url=SOCIAL_LINKS['app_download'])],
            [InlineKeyboardButton(f"{EMOJIS['twitter']} Twitter", url=SOCIAL_LINKS['twitter']),
             InlineKeyboardButton(f"{EMOJIS['instagram']} Instagram", url=SOCIAL_LINKS['instagram'])],
            [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        help_text = """
🆘 **Need Help?**

**Commands:**
• /start - Start or restart
• /status - Check progress  
• /help - Show help
• /stats - Bot statistics

**Support:** @Minatirewards
**Follow:** @Minativerseofficial

**Quick Links:**
Use the buttons below to access our platforms
"""

        await query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)

    # Simplified command handlers
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Simplified status command"""
        user_id = update.effective_user.id
        self.traffic_monitor.log_request(user_id)
        
        try:
            user_data = await self.db.get_user_with_retry(user_id, max_retries=1)
            if not user_data:
                await update.message.reply_text("❌ Please use /start command first.")
                return

            current_step = user_data.get('current_step', 1)
            steps_completed = user_data.get('steps_completed', {})
            
            status_text = f"""
📊 **Your Progress**

Current Step: **{current_step}/{TOTAL_STEPS}**
Completed: **{len(steps_completed)}/{TOTAL_STEPS}**

Use the buttons below for more details.
"""
            
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])],
                [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(status_text, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await update.message.reply_text("❌ Error retrieving status. Please try again.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Simplified help command"""
        self.traffic_monitor.log_request(update.effective_user.id)
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['phone']} Support", url=SOCIAL_LINKS['support']),
             InlineKeyboardButton(f"{EMOJIS['mobile']} Download App", url=SOCIAL_LINKS['app_download'])],
            [InlineKeyboardButton(f"{EMOJIS['twitter']} Twitter", url=SOCIAL_LINKS['twitter']),
             InlineKeyboardButton(f"{EMOJIS['instagram']} Instagram", url=SOCIAL_LINKS['instagram'])],
            [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        help_text = """
🆘 **Minati Vault Bot Help**

**Commands:**
• /start - Start or restart the bot
• /status - Check your progress
• /help - Show this help
• /stats - Bot statistics

**Referral System:**
💰 Earn +2 MNTC for each successful referral
🎁 Share your referral link after completing steps

**Support:** @Minatirewards

**Quick Access:**
Use the buttons below for instant access
"""

        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced stats command with traffic monitoring"""
        self.traffic_monitor.log_request(update.effective_user.id)
        
        try:
            # Get database stats
            db_stats = await self.db.get_user_stats()
            
            # Get traffic stats
            traffic_stats = self.traffic_monitor.get_traffic_stats()
            
            stats_text = f"""
📊 **Bot Statistics**

**Database:**
👥 Total Users: {db_stats.get('total_users', 0):,}
✅ Completed Users: {db_stats.get('completed_users', 0):,}
📈 Completion Rate: {(db_stats.get('completed_users', 0) / max(db_stats.get('total_users', 1), 1) * 100):.1f}%

**Current Traffic:**
🔥 Active Users: {traffic_stats['active_users']}
⚡ Requests/min: {traffic_stats['requests_per_minute']}
💾 Memory Usage: {traffic_stats['memory_usage_mb']:.1f}MB
📊 Queue Size: {traffic_stats['queue_size']}

**System:**
🕐 Uptime: {traffic_stats['uptime_hours']:.1f}h
💻 Memory: {traffic_stats['memory_percent']:.1f}%

🚀 **Minati Vault Bot**
Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

            await update.message.reply_text(stats_text, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await update.message.reply_text(f"{EMOJIS['cross']} Error retrieving statistics.")

    async def admin_traffic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command for detailed traffic monitoring"""
        user_id = update.effective_user.id
        
        # Admin check - replace with your admin user IDs
        ADMIN_USER_IDS = [123456789]  # Replace with actual admin user IDs
        
        if user_id not in ADMIN_USER_IDS:
            await update.message.reply_text("❌ Unauthorized")
            return
        
        try:
            stats = self.traffic_monitor.get_traffic_stats()
            
            admin_message = f"""
🔧 **Admin Traffic Report**

**Real-time Metrics:**
🔥 Active Concurrent Users: **{stats['active_users']}**
⚡ Requests per Minute: **{stats['requests_per_minute']}**
📦 Queue Size: **{stats['queue_size']}**
🔄 Processed Requests: **{self.emergency_queue.processed_count}**

**System Resources:**
💾 Memory Usage: **{stats['memory_usage_mb']:.1f}MB ({stats['memory_percent']:.1f}%)**
🚨 Emergency Mode: **{'ACTIVE' if self.emergency_mode else 'NORMAL'}**

**Performance:**
🕐 Uptime: **{stats['uptime_hours']:.1f} hours**
📊 Total Requests: **{stats['total_requests']:,}**

**Upgrade Recommendation:**
{self.traffic_monitor.should_upgrade_plan() or '✅ Current plan sufficient'}

**Status:** {'🔴 OVERLOADED' if stats['memory_percent'] > 85 else '🟢 HEALTHY'}
"""

            await update.message.reply_text(admin_message, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error retrieving admin stats: {e}")

    def setup_handlers(self):
        """Setup all command and message handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("admin_traffic", self.admin_traffic_command))

        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

        # Message handler
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Error handler
        self.application.add_error_handler(self.error_handler)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced error handler"""
        logger.error(f'Update {update} caused error {context.error}')

        # Handle specific error types
        if isinstance(context.error, Conflict):
            logger.error("❌ CONFLICT ERROR: Bot token is being used by another instance!")
            logger.error("💡 Solution: Stop other instances or delete webhook")
        elif isinstance(context.error, NetworkError):
            logger.warning("⚠️ Network error occurred, retrying...")
        elif isinstance(context.error, TimedOut):
            logger.warning("⏱️ Request timed out")
        elif isinstance(context.error, BadRequest):
            logger.warning(f"📝 Bad request: {context.error}")
        elif isinstance(context.error, Forbidden):
            logger.error(f"🚫 Forbidden: {context.error}")

    async def cleanup_telegram_bot(self):
        """Clean up Telegram bot connections and webhooks"""
        try:
            logger.info("🧹 Cleaning up Telegram bot connections...")
            
            temp_app = Application.builder().token(config.BOT_TOKEN).build()
            
            try:
                await temp_app.initialize()
                
                try:
                    await temp_app.bot.delete_webhook(drop_pending_updates=True)
                    logger.info("✅ Webhook deleted successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Webhook deletion failed (may not exist): {e}")
                
                bot_info = await temp_app.bot.get_me()
                logger.info(f"✅ Bot connection verified: @{bot_info.username}")
                
            except Conflict as e:
                logger.error(f"❌ CONFLICT: {e}")
                logger.error("💡 Another instance is using this bot token!")
                raise
            except Exception as e:
                logger.warning(f"⚠️ Bot cleanup warning: {e}")
            finally:
                try:
                    await temp_app.shutdown()
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"❌ Bot cleanup failed: {e}")
            raise

    async def start_bot(self):
        """Start the optimized bot"""
        try:
            logger.info(f"{EMOJIS['rocket']} Starting Optimized Minati Vault Bot...")

            # Initialize services first
            await self.initialize_services_async()

            # Clean up any existing connections
            await self.cleanup_telegram_bot()

            # Create application
            self.application = Application.builder().token(config.BOT_TOKEN).build()

            # Setup handlers
            self.setup_handlers()

            logger.info(f"{EMOJIS['checkmark']} Bot handlers configured")
            logger.info(f"{EMOJIS['fire']} Firebase connection: Ready")
            logger.info(f"{EMOJIS['stats']} Emergency optimizations: ACTIVE")
            logger.info(f"{EMOJIS['gift']} Traffic monitoring: ACTIVE")
            logger.info(f"{EMOJIS['target']} Starting polling...")

            self.running = True

            # Initialize the application
            await self.application.initialize()
            await self.application.start()

            # Start polling
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            logger.info(f"{EMOJIS['checkmark']} Optimized bot started successfully!")

            # Keep the bot running
            while self.running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"❌ Error starting optimized bot: {e}")
            raise

        finally:
            if self.application:
                await self.stop_bot()

    async def stop_bot(self):
        """Stop the bot gracefully"""
        try:
            logger.info(f"{EMOJIS['stop']} Stopping optimized bot...")
            self.running = False

            if self.application:
                try:
                    if self.application.updater and self.application.updater.running:
                        await self.application.updater.stop()
                        logger.info("✅ Updater stopped")
                except Exception as e:
                    logger.warning(f"⚠️ Updater stop warning: {e}")

                try:
                    await self.application.stop()
                    logger.info("✅ Application stopped")
                except Exception as e:
                    logger.warning(f"⚠️ Application stop warning: {e}")

                try:
                    await self.application.shutdown()
                    logger.info("✅ Application shutdown")
                except Exception as e:
                    logger.warning(f"⚠️ Application shutdown warning: {e}")

            # Close database connection
            if self.db:
                try:
                    await self.db.close_connection()
                    logger.info("✅ Database connection closed")
                except Exception as e:
                    logger.warning(f"⚠️ Database close warning: {e}")

            logger.info(f"{EMOJIS['checkmark']} Optimized bot stopped gracefully")

        except Exception as e:
            logger.error(f"❌ Error stopping bot: {e}")

# Main execution
async def main():
    """Main function to run the optimized bot"""
    
    # Enhanced configuration validation
    logger.info("🔍 Validating configuration...")
    
    if not config.BOT_TOKEN:
        logger.error(f"{EMOJIS['cross']} BOT_TOKEN not found in environment variables!")
        sys.exit(1)

    if not config.FIREBASE_PROJECT_ID:
        logger.error(f"{EMOJIS['cross']} FIREBASE_PROJECT_ID not found in environment variables!")
        sys.exit(1)

    logger.info("✅ Configuration validated successfully")

    # Create optimized bot instance
    bot = OptimizedMinatiVaultBot()

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"📡 Received signal {sig}, initiating shutdown...")
        bot.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await bot.start_bot()
    except KeyboardInterrupt:
        logger.info(f"{EMOJIS['fire']} Bot stopped by user (Ctrl+C)")
    except Conflict as e:
        logger.error(f"{EMOJIS['cross']} CONFLICT ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"{EMOJIS['cross']} Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    try:
        # Check for existing processes
        pid = os.getpid()
        logger.info(f"🚀 Starting Optimized Minati Vault Bot (PID: {pid})")
        
        # Run the optimized bot
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info(f"{EMOJIS['fire']} Bot interrupted by user")
    except Conflict as e:
        logger.error(f"{EMOJIS['cross']} TELEGRAM BOT CONFLICT: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"{EMOJIS['cross']} Fatal startup error: {e}")
        sys.exit(1)
