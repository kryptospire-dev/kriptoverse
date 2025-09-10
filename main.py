# Optimized Main Bot Module with Full Async Support and Concurrency
import logging
import logging.config
import asyncio
import signal
import sys
import time
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut, Conflict
from database import Database
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

# Rate limiting and concurrency control
class RateLimiter:
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = {}
        self.lock = asyncio.Lock()

    async def is_allowed(self, user_id: int) -> bool:
        async with self.lock:
            current_time = time.time()
            
            # Clean old entries
            self.requests = {
                uid: times for uid, times in self.requests.items()
                if any(t > current_time - self.time_window for t in times)
            }
            
            # Get user's recent requests
            user_requests = self.requests.get(user_id, [])
            user_requests = [t for t in user_requests if t > current_time - self.time_window]
            
            if len(user_requests) >= self.max_requests:
                return False
            
            user_requests.append(current_time)
            self.requests[user_id] = user_requests
            return True

# Global rate limiter instances
start_rate_limiter = RateLimiter(max_requests=10, time_window=60)  # 10 /start per minute
global_rate_limiter = RateLimiter(max_requests=50, time_window=60)  # 50 operations per minute

async def initialize_services():
    """Initialize database and validators with proper error handling"""
    global db, validators
    try:
        # Initialize validators first (no external dependencies)
        validators = Validators()
        logger.info("✅ Validators initialized successfully")

        # Initialize database with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                db = Database()
                logger.info("✅ Database initialized successfully")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Database init attempt {attempt + 1} failed: {e}. Retrying...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"❌ Failed to initialize database after {max_retries} attempts: {e}")
                    raise

        return db, validators

    except Exception as e:
        logger.error(f"❌ Failed to initialize services: {e}")
        raise

class MinatiVaultBot:
    def __init__(self):
        self.db = None
        self.validators = None
        self.application = None
        self.running = False

        # Rate limiting for start command - optimized with async
        self._start_requests = {}
        self._start_lock = asyncio.Lock()

        # Performance metrics
        self._performance_metrics = {
            'total_requests': 0,
            'failed_requests': 0,
            'avg_response_time': 0.0,
            'rate_limited_requests': 0
        }

        # Concurrent operation limits
        self._max_concurrent_operations = 50
        self._operation_semaphore = asyncio.Semaphore(self._max_concurrent_operations)

    async def initialize_services_async(self):
        """Initialize services asynchronously"""
        try:
            self.db, self.validators = await initialize_services()
            logger.info("✅ All services initialized successfully")
        except Exception as e:
            logger.error(f"❌ Service initialization failed: {e}")
            raise

    async def _check_start_rate_limit(self, user_id: int) -> bool:
        """Optimized async rate limiting for start command"""
        if not await start_rate_limiter.is_allowed(user_id):
            logger.warning(f"Rate limited /start from user {user_id}")
            return False
        return True

    async def _check_global_rate_limit(self, user_id: int) -> bool:
        """Global rate limiting for all operations"""
        if not await global_rate_limiter.is_allowed(user_id):
            logger.warning(f"Global rate limit exceeded for user {user_id}")
            self._performance_metrics['rate_limited_requests'] += 1
            return False
        return True

    async def _update_performance_metrics(self, response_time: float, success: bool = True):
        """Update performance metrics"""
        self._performance_metrics['total_requests'] += 1
        if not success:
            self._performance_metrics['failed_requests'] += 1

        # Update average response time
        current_avg = self._performance_metrics['avg_response_time']
        total_requests = self._performance_metrics['total_requests']
        self._performance_metrics['avg_response_time'] = (
            (current_avg * (total_requests - 1) + response_time) / total_requests
        )

    async def verify_social_follow(self, platform: str, username: str) -> bool:
        """Verify if user actually follows on social media with async validation"""
        # For now, we'll do basic username validation with async sleep to simulate API call
        # In production, you'd integrate with Twitter/Instagram APIs
        await asyncio.sleep(0.1)  # Simulate API call delay
        
        if platform == 'coinmarketcap':
            is_valid, _ = self.validators.validate_coinmarketcap_userid(username)
        else:
            is_valid, _ = self.validators.validate_username(username)
        return is_valid

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler with referral support and enhanced error handling"""
        start_time = time.time()
        user = update.effective_user
        user_id = user.id
        username = user.username or "No username"
        first_name = user.first_name or "User"

        try:
            async with self._operation_semaphore:
                # Rate limiting checks
                if not await self._check_start_rate_limit(user_id):
                    return

                if not await self._check_global_rate_limit(user_id):
                    await update.message.reply_text(
                        f"{EMOJIS['warning']} Too many requests. Please wait a moment and try again.",
                        parse_mode='Markdown'
                    )
                    return

                # Extract referral code from deep link if present
                referral_code = None
                if context.args and len(context.args) > 0:
                    potential_referral = context.args[0]
                    if self.validators.is_valid_referral_link_param(potential_referral):
                        referral_code = self.validators.extract_referral_code_from_start_param(potential_referral)
                        if referral_code:
                            logger.info(f"User {user_id} accessed via referral code: {referral_code}")

                logger.info(f"User {user_id} ({first_name}) started the bot")

                # Enhanced user existence check with async retries
                existing_user = None
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        existing_user = await self.db.get_user_with_retry(user_id)
                        break  # Success, exit retry loop
                    except Exception as e:
                        logger.warning(f"Database get_user attempt {attempt + 1} failed for user {user_id}: {e}")
                        if attempt == max_retries - 1:
                            # Final attempt failed
                            await update.message.reply_text(
                                f"{EMOJIS['warning']} Database connection issue. Please try again in a moment.\n\n"
                                f"If this persists, contact support: @Minatirewards",
                                parse_mode='Markdown'
                            )
                            await self._update_performance_metrics(time.time() - start_time, success=False)
                            return

                        await asyncio.sleep(1)  # Async wait before retry

                if not existing_user:
                    # NEW USER - Apply referral logic
                    logger.info(f"Creating new user {user_id}")
                    referred_by = None
                    if referral_code:
                        # Validate referral code exists and get referrer
                        try:
                            referrer = await self.db.get_user_by_referral_code(referral_code)
                            if referrer:
                                if referrer['user_id'] == user_id:
                                    # User trying to use their own referral code
                                    await update.message.reply_text(
                                        f"{EMOJIS['cross']} {MESSAGE_TEMPLATES['referral_self_use']}"
                                    )
                                    return

                                referred_by = referral_code
                                logger.info(f"User {user_id} will be created with referral by: {referred_by}")
                            else:
                                # Invalid referral code
                                await update.message.reply_text(
                                    f"{EMOJIS['cross']} {MESSAGE_TEMPLATES['referral_not_found']}"
                                )
                                return
                        except Exception as e:
                            logger.error(f"Error validating referral code {referral_code}: {e}")
                            await update.message.reply_text(
                                f"{EMOJIS['warning']} Unable to process referral code. Starting without referral."
                            )

                    # Attempt to create user with enhanced error handling
                    try:
                        creation_success = await self.db.create_user_with_retry(user_id, username, first_name, referred_by)
                        if creation_success:
                            welcome_msg = WELCOME_MESSAGE_REFERRED if referred_by else WELCOME_MESSAGE
                            await update.message.reply_text(
                                f"Welcome {first_name}! {EMOJIS['party']}\n\n{welcome_msg}"
                            )
                            await self.show_step(update, context, 1)
                        else:
                            # User creation failed - check if user now exists (race condition)
                            try:
                                recheck_user = await self.db.get_user_with_retry(user_id)
                                if recheck_user:
                                    # User was created by another process, continue normally
                                    logger.info(f"User {user_id} was created by another process")
                                    current_step = recheck_user.get('current_step', 1)
                                    await update.message.reply_text(
                                        f"Welcome back {first_name}! {EMOJIS['fire']}\n\n"
                                        f"You're currently on step {current_step}."
                                    )

                                    if current_step > TOTAL_STEPS:
                                        await self.show_completion_with_referral(update, recheck_user)
                                    else:
                                        await self.show_step(update, context, current_step)
                                else:
                                    # Genuine creation failure
                                    logger.error(f"Failed to create user {user_id} - database error")
                                    await update.message.reply_text(
                                        f"{EMOJIS['cross']} We're experiencing technical difficulties. "
                                        f"Please try again in a few minutes.\n\n"
                                        f"If this persists, contact support: @Minatirewards"
                                    )
                            except Exception as inner_e:
                                logger.error(f"Error during user creation recheck for {user_id}: {inner_e}")
                                await update.message.reply_text(
                                    f"{EMOJIS['cross']} Technical issue occurred. Please contact support: @Minatirewards"
                                )

                    except Exception as e:
                        logger.error(f"Exception during user creation for {user_id}: {e}")
                        await update.message.reply_text(
                            f"{EMOJIS['warning']} Service temporarily unavailable. Please try again later.\n\n"
                            f"Support: @Minatirewards"
                        )
                        await self._update_performance_metrics(time.time() - start_time, success=False)

                else:
                    # EXISTING USER - Enhanced handling
                    logger.info(f"Existing user {user_id} accessed bot")
                    try:
                        current_step = existing_user.get('current_step', 1)
                        # If user clicked referral link but already exists, ignore referral and show message
                        if referral_code:
                            await update.message.reply_text(
                                f"Welcome back {first_name}! {EMOJIS['fire']}\n\n"
                                f"ℹ️ Referral links can only be used by new users. "
                                f"You already have an account, so continuing with your existing progress.\n\n"
                                f"You're currently on step {current_step}."
                            )
                        else:
                            # Normal existing user return
                            await update.message.reply_text(
                                f"Welcome back {first_name}! {EMOJIS['fire']}\n\n"
                                f"You're currently on step {current_step}."
                            )

                        if current_step > TOTAL_STEPS:
                            # User already completed
                            await self.show_completion_with_referral(update, existing_user)
                        else:
                            # Show current step
                            await self.show_step(update, context, current_step)

                    except Exception as e:
                        logger.error(f"Error handling existing user {user_id}: {e}")
                        await update.message.reply_text(
                            f"{EMOJIS['warning']} Welcome back! Use /status to check your progress."
                        )
                        await self._update_performance_metrics(time.time() - start_time, success=False)

                # Update performance metrics on success
                await self._update_performance_metrics(time.time() - start_time, success=True)

        except Exception as e:
            logger.error(f"Critical error in start handler for user {user_id}: {e}")
            await update.message.reply_text(
                f"{EMOJIS['cross']} Critical error occurred. Please contact support: @Minatirewards"
            )
            await self._update_performance_metrics(time.time() - start_time, success=False)

    async def show_completion_with_referral(self, update: Update, user_data: dict):
        """Show completion message with referral link for completed users"""
        user_id = user_data['user_id']
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['stats']} View Status", callback_data=CALLBACK_DATA['show_status'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        completion_text = f"""
{EMOJIS['party']} **Congratulations!** {EMOJIS['party']}

You have already completed all steps!

**🎁 Your Referral Link:**
`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={user_data.get('referral_code')}`

**📊 Your Referral Stats:**
• Total Successful Referrals: **{referral_stats['total_referrals']}**
• Total Referral Rewards: **{referral_stats['total_referrals']*2} MNTC**
• Total Received Referral Rewards: **{referral_stats['total_rewards']*2} MNTC**

✅ To be eligible for rewards, please make sure you have joined our official community: @Minatirewards

Share your referral link to earn more rewards! 💰

{EMOJIS['phone']} Support: [Contact Us](https://t.me/Minatirewards)
"""

        await update.message.reply_text(
            completion_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def show_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE, step: int):
        """Show current step with proper validation buttons"""
        if step > TOTAL_STEPS:
            user_data = await self.db.get_user_with_retry(update.effective_user.id)
            if user_data:
                await self.show_completion_with_referral(update, user_data)
            else:
                await update.message.reply_text(
                    f"{EMOJIS['party']} Congratulations! All steps completed!\n\n"
                    f"Support: [Contact Us](https://t.me/Minatirewards)",
                    parse_mode='Markdown'
                )
            return

        step_message = STEPS.get(step, "Invalid step")
        if step == 6:
            step_message = step_message.format("Minativerseofficial")

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
            # Check if user has all required data before allowing completion
            user_data = await self.db.get_user_with_retry(update.effective_user.id)
            can_complete = True
            missing_fields = []

            if user_data:
                social_usernames = user_data.get('social_usernames', {})
                bep20_address = user_data.get('bep20_address')

                if not social_usernames.get('twitter'):
                    missing_fields.append('Twitter username')
                    can_complete = False
                if not social_usernames.get('instagram'):
                    missing_fields.append('Instagram username')
                    can_complete = False
                if not social_usernames.get('coinmarketcap'):
                    missing_fields.append('CoinMarketCap User ID')
                    can_complete = False
                if not bep20_address:
                    missing_fields.append('BEP20 address')
                    can_complete = False

                if can_complete:
                    keyboard = [
                        [InlineKeyboardButton(f"{EMOJIS['party']} Complete Process", callback_data=CALLBACK_DATA['complete_process'])]
                    ]
                else:
                    step_message += f"\n\n⚠️ **Missing Information:**\n"
                    for field in missing_fields:
                        step_message += f"• {field}\n"
                    step_message += f"\nPlease go back and complete all previous steps first."
                    keyboard = [
                        [InlineKeyboardButton(f"{EMOJIS['refresh']} Check Status", callback_data=CALLBACK_DATA['show_status'])]
                    ]

        keyboard.append([InlineKeyboardButton(f"{EMOJIS['question']} Need Help", callback_data=CALLBACK_DATA['help'])])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"**Step {step}/{TOTAL_STEPS}** {EMOJIS['target']}\n\n{step_message}",
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button clicks with validation and rate limiting"""
        start_time = time.time()
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        try:
            async with self._operation_semaphore:
                # Rate limiting
                if not await self._check_global_rate_limit(user_id):
                    await query.edit_message_text(
                        f"{EMOJIS['warning']} Too many requests. Please wait a moment and try again."
                    )
                    return

                user_data = await self.db.get_user_with_retry(user_id)
                if not user_data:
                    await query.edit_message_text(MESSAGE_TEMPLATES['user_not_found'])
                    return

                current_step = user_data.get('current_step', 1)

                # Step 1 verification
                if query.data == CALLBACK_DATA['verify_step_1']:
                    if current_step == 1:
                        await self.db.update_user_step(user_id, 1, True)
                        await query.edit_message_text(f"{EMOJIS['checkmark']} Great! App download confirmed.\n\nMoving to next step...")

                        # Send Step 2 as a new message
                        step_message = STEPS.get(2, "Invalid step")
                        keyboard = [
                            [InlineKeyboardButton(f"{EMOJIS['twitter']} Follow on Twitter", url=SOCIAL_LINKS['twitter'])],
                            [InlineKeyboardButton(f"{EMOJIS['info']} Send Username After Following", callback_data=CALLBACK_DATA['twitter_info'])],
                            [InlineKeyboardButton(f"{EMOJIS['question']} Need Help", callback_data=CALLBACK_DATA['help'])]
                        ]

                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"**Step 2/{TOTAL_STEPS}** {EMOJIS['target']}\n\n{step_message}",
                            reply_markup=reply_markup,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                    else:
                        await query.edit_message_text(MESSAGE_TEMPLATES['step_mismatch'].format(1))

                # Complete process
                elif query.data == CALLBACK_DATA['complete_process']:
                    logger.info(f"Complete process clicked by user {user_id}, current_step: {current_step}")
                    if current_step == 6:
                        logger.info(f"User {user_id} completing step 6")
                        await self.db.update_user_step(user_id, 6, True)
                        fresh_user_data = await self.db.get_user_with_retry(user_id)
                        await self.send_completion_message(query, fresh_user_data)
                    elif current_step > 6:
                        logger.info(f"User {user_id} already completed, showing completion again")
                        await self.send_completion_message(query, user_data)
                    else:
                        logger.warning(f"User {user_id} tried to complete from step {current_step}")
                        await query.edit_message_text(
                            f"❌ You must complete all previous steps first.\n\nYour current step: {current_step}/6\n\nUse /status to check your progress."
                        )

                # Info buttons
                elif query.data == CALLBACK_DATA['twitter_info']:
                    await query.edit_message_text(HELP_TEMPLATES['instructions']['twitter'])
                elif query.data == CALLBACK_DATA['instagram_info']:
                    await query.edit_message_text(HELP_TEMPLATES['instructions']['instagram'])
                elif query.data == CALLBACK_DATA['coinmarketcap_info']:
                    await query.edit_message_text(HELP_TEMPLATES['instructions']['coinmarketcap'])
                elif query.data == CALLBACK_DATA['bep20_info']:
                    await query.edit_message_text(HELP_TEMPLATES['instructions']['bep20'])

                # Show status
                elif query.data == CALLBACK_DATA['show_status']:
                    fresh_user_data = await self.db.get_user_with_retry(user_id)
                    await self.show_status_callback(query, fresh_user_data)

                # Show referral stats
                elif query.data == CALLBACK_DATA['show_referral']:
                    fresh_user_data = await self.db.get_user_with_retry(user_id)
                    await self.show_referral_stats_callback(query, fresh_user_data)

                # Help
                elif query.data == CALLBACK_DATA['help']:
                    keyboard = [
                        [InlineKeyboardButton(f"{EMOJIS['phone']} Support", url=SOCIAL_LINKS['support'])],
                        [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website']),
                         InlineKeyboardButton(f"{EMOJIS['mobile']} Download App", url=SOCIAL_LINKS['app_download'])],
                        [InlineKeyboardButton(f"{EMOJIS['twitter']} Twitter", url=SOCIAL_LINKS['twitter']),
                         InlineKeyboardButton(f"{EMOJIS['instagram']} Instagram", url=SOCIAL_LINKS['instagram'])],
                        [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])]
                    ]

                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        HELP_TEMPLATES['help_button'],
                        parse_mode='Markdown',
                        reply_markup=reply_markup
                    )

                # Update performance metrics
                await self._update_performance_metrics(time.time() - start_time, success=True)

        except Exception as e:
            logger.error(f"Error in button handler for user {user_id}: {e}")
            await query.edit_message_text(
                f"{EMOJIS['cross']} An error occurred. Please try again or contact support: @Minatirewards"
            )
            await self._update_performance_metrics(time.time() - start_time, success=False)

    async def send_completion_message(self, query, user_data):
        """Send unified completion message with referral link for ALL users"""
        social_usernames = user_data.get('social_usernames', {})
        bep20_address = user_data.get('bep20_address', '')
        is_referred = user_data.get('is_referred', False)
        referral_code = user_data.get('referral_code', '')

        # Get the actual MNTC earned from reward_info
        reward_info = user_data.get('reward_info', {})
        mntc_earned = reward_info.get('mntc_earned', 0)

        # If MNTC is 0, calculate it based on referral status (fallback)
        if mntc_earned == 0:
            mntc_earned = REFERRAL_CONFIG['referred_reward'] if is_referred else REFERRAL_CONFIG['normal_reward']

        try:
            # UNIFIED COMPLETION MESSAGE - Use same template for ALL users
            completion_message = f"""
🎉 **CONGRATULATIONS!** 🎉

You have successfully completed all steps!

**Your Submitted Information:**
🐦 Twitter: @{social_usernames.get('twitter', 'Not provided')}
📸 Instagram: @{social_usernames.get('instagram', 'Not provided')}
📊 CoinMarketCap: @{social_usernames.get('coinmarketcap', 'Not provided')}
🏦 BEP20 Address: `{bep20_address[:10]}...{bep20_address[-6:] if bep20_address else 'Not provided'}`

**💰 Your Reward:** {mntc_earned} MNTC

**What's Next?**
Our team will review your submission and contact you soon!

✅ To be eligible for rewards, please make sure you have joined our official community: @Minatirewards

**🎁 Your Referral Link:**
`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={referral_code}`

**💰 Referral Rewards:**
• You get **+2 MNTC** for each successful referral

Share your referral link with friends to earn more rewards! 🚀

📞 **Support:** @Minatirewards
🌐 **Website:** {SOCIAL_LINKS['website']}

Thank you for using Minati Vault Bot! 🚀
"""

            await query.edit_message_text(completion_message, parse_mode='Markdown')

            # Send notification to referrer if user was referred
            if is_referred:
                await self.notify_referrer(user_data.get('referred_by'), user_data['user_id'])

        except Exception as e:
            logger.error(f"Error sending completion message for user {user_data.get('user_id')}: {e}")
            # Fallback message if template formatting fails
            fallback_message = f"""
{EMOJIS['party']} **CONGRATULATIONS!** {EMOJIS['party']}

You have successfully completed all steps!

**💰 Your Reward:** {mntc_earned} MNTC

**🎁 Your Referral Link:**
`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={referral_code}`

✅ To be eligible for rewards, please make sure you have joined our official community: @Minatirewards

Our team will review your submission and contact you soon!

📞 **Support:** @Minatirewards
🌐 **Website:** {SOCIAL_LINKS['website']}

Thank you for using Minati Vault Bot! 🚀
"""

            await query.edit_message_text(fallback_message, parse_mode='Markdown')

    async def notify_referrer(self, referrer_code: str, completed_user_id: int):
        """Notify referrer about successful referral completion"""
        try:
            if not referrer_code:
                return

            referrer = await self.db.get_user_by_referral_code(referrer_code)
            if not referrer:
                return

            referrer_id = referrer['user_id']
            referral_stats = referrer.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

            notification_message = REFERRAL_MESSAGES['referral_success_notification'].format(
                total_referrals=referral_stats['total_referrals'],
                total_rewards=referral_stats['total_rewards'],
                bot_username=REFERRAL_CONFIG['bot_username'],
                referral_code=referrer['referral_code']
            )

            await self.application.bot.send_message(
                chat_id=referrer_id,
                text=notification_message,
                parse_mode='Markdown'
            )

            logger.info(f"Notified referrer {referrer_id} about successful referral from user {completed_user_id}")

        except Exception as e:
            logger.error(f"Error notifying referrer {referrer_code}: {e}")

    async def show_referral_stats_callback(self, query, user_data):
        """Show referral statistics via callback"""
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

        stats_text = REFERRAL_STATS_TEMPLATE.format(
            total_referrals=referral_stats['total_referrals'],
            total_rewards=referral_stats['total_rewards'],
            bot_username=REFERRAL_CONFIG['bot_username'],
            referral_code=user_data.get('referral_code', 'No code'),
            website=SOCIAL_LINKS['website']
        )

        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['stats']} View Status", callback_data=CALLBACK_DATA['show_status'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(stats_text, parse_mode='Markdown', reply_markup=reply_markup)

    async def show_status_callback(self, query, user_data):
        """Show user status via callback"""
        current_step = user_data.get('current_step', 1)
        steps_completed = user_data.get('steps_completed', {})
        bep20_address = user_data.get('bep20_address')
        social_usernames = user_data.get('social_usernames', {})
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})
        is_referred = user_data.get('is_referred', False)
        reward_info = user_data.get('reward_info', {})

        if current_step > TOTAL_STEPS:
            status_text = f"""
{EMOJIS['stats']} *Completion Status*

{EMOJIS['checkmark']} All steps completed successfully!

*Your Information:*
• Twitter: @{social_usernames.get('twitter', 'Not provided')}
• Instagram: @{social_usernames.get('instagram', 'Not provided')}
• CoinMarketCap: @{social_usernames.get('coinmarketcap', 'Not provided')}
• BEP20: {bep20_address[:10]}...{bep20_address[-6:] if bep20_address else 'Not provided'}

*Referral Information:*
• Status: {STATUS_ICONS['referred'] if is_referred else STATUS_ICONS['normal']}
• Your Referrals: {int(referral_stats['total_referrals'])}
• Total Referral Rewards: {referral_stats['total_referrals']*2} MNTC
• Total Received Referral Rewards: **{referral_stats['total_rewards']*2} MNTC**

*Reward Information:*
• MNTC Earned: {reward_info.get('mntc_earned', 0)} MNTC
• Reward Type: {reward_info.get('reward_type', 'Unknown').title()}
• Status: {STATUS_ICONS.get(reward_info.get('reward_status', 'pending'), '⏳ Pending')}

*Need Changes?* @Minatirewards
"""

            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]
            ]

        else:
            status_text = STATUS_TEMPLATE.format(
                current_step, TOTAL_STEPS,
                len(steps_completed), TOTAL_STEPS,
                STATUS_ICONS['completed'] if steps_completed.get('step_1') else STATUS_ICONS['not_completed'],
                STATUS_ICONS['completed'] if steps_completed.get('step_2') else STATUS_ICONS['not_completed'],
                STATUS_ICONS['completed'] if steps_completed.get('step_3') else STATUS_ICONS['not_completed'],
                STATUS_ICONS['completed'] if steps_completed.get('step_4') else STATUS_ICONS['not_completed'],
                STATUS_ICONS['completed'] if steps_completed.get('step_5') else STATUS_ICONS['not_completed'],
                STATUS_ICONS['completed'] if steps_completed.get('step_6') else STATUS_ICONS['not_completed'],
                social_usernames.get('twitter', 'Not provided'),
                social_usernames.get('instagram', 'Not provided'),
                social_usernames.get('coinmarketcap', 'Not provided'),
                STATUS_ICONS['provided'] if bep20_address else STATUS_ICONS['not_provided'],
                STATUS_ICONS['referred'] if is_referred else STATUS_ICONS['normal'],
                referral_stats['total_referrals'],
                referral_stats['total_rewards'],
                reward_info.get('mntc_earned', 0),
                STATUS_ICONS.get(reward_info.get('reward_status', 'not_completed_reward'), '❌ Not Completed'),
                MESSAGE_TEMPLATES['all_completed'] if current_step > TOTAL_STEPS else f"Continue with Step {current_step}"
            )

            keyboard = []

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            status_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages with enhanced validation and rate limiting"""
        start_time = time.time()
        user_id = update.effective_user.id
        message_text = update.message.text.strip()

        try:
            async with self._operation_semaphore:
                # Rate limiting
                if not await self._check_global_rate_limit(user_id):
                    await update.message.reply_text(
                        f"{EMOJIS['warning']} Too many requests. Please wait a moment and try again."
                    )
                    return

                user_data = await self.db.get_user_with_retry(user_id)
                if not user_data:
                    await update.message.reply_text(f"{EMOJIS['cross']} Please use /start command first.")
                    return

                current_step = user_data.get('current_step', 1)

                # Step 2: Handle Twitter username
                if current_step == 2:
                    username = message_text.lstrip('@').strip()
                    is_valid, validation_message = self.validators.validate_username(username)

                    if is_valid:
                        is_follower = await self.verify_social_follow('twitter', username)
                        if is_follower:
                            if await self.db.save_social_username(user_id, 'twitter', username):
                                await self.db.update_user_step(user_id, 2, True)
                                await update.message.reply_text(
                                    f"{EMOJIS['checkmark']} *Twitter Verified!*\n\n"
                                    f"Username: @{username}\n"
                                    f"Thank you for following us on Twitter! {EMOJIS['twitter']}\n\n"
                                    "Moving to next step...",
                                    parse_mode='Markdown'
                                )
                                await self.show_step(update, context, 3)
                            else:
                                await update.message.reply_text(MESSAGE_TEMPLATES['error_saving'].format('Twitter username'))
                        else:
                            await update.message.reply_text(
                                f"{EMOJIS['warning']} *Username received but not verified*\n\n"
                                f"Username: @{username}\n\n"
                                "*Please make sure you:*\n"
                                "1. Actually followed our Twitter account\n"
                                "2. Liked and retweeted our pinned post\n"
                                "3. Wait 30 seconds then try again\n\n"
                                f"Twitter: {SOCIAL_LINKS['twitter']}",
                                parse_mode='Markdown'
                            )
                    else:
                        await update.message.reply_text(
                            MESSAGE_TEMPLATES['invalid_username'].format('Twitter', validation_message, 'Twitter')
                        )
                    return

                # Step 3: Handle Instagram username
                elif current_step == 3:
                    username = message_text.lstrip('@').strip()
                    is_valid, validation_message = self.validators.validate_username(username)

                    if is_valid:
                        is_follower = await self.verify_social_follow('instagram', username)
                        if is_follower:
                            if await self.db.save_social_username(user_id, 'instagram', username):
                                await self.db.update_user_step(user_id, 3, True)
                                await update.message.reply_text(
                                    f"{EMOJIS['checkmark']} *Instagram Verified!*\n\n"
                                    f"Username: @{username}\n"
                                    f"Thank you for following us on Instagram! {EMOJIS['instagram']}\n\n"
                                    "Moving to next step...",
                                    parse_mode='Markdown'
                                )
                                await self.show_step(update, context, 4)
                            else:
                                await update.message.reply_text(MESSAGE_TEMPLATES['error_saving'].format('Instagram username'))
                        else:
                            await update.message.reply_text(
                                f"{EMOJIS['warning']} *Username received but not verified*\n\n"
                                f"Username: @{username}\n\n"
                                "*Please make sure you:*\n"
                                "1. Actually followed our Instagram account\n"
                                "2. Liked our latest post\n"
                                "3. Wait 30 seconds then try again\n\n"
                                f"Instagram: {SOCIAL_LINKS['instagram']}",
                                parse_mode='Markdown'
                            )
                    else:
                        await update.message.reply_text(
                            MESSAGE_TEMPLATES['invalid_username'].format('Instagram', validation_message, 'Instagram')
                        )
                    return

                # Step 4: Handle CoinMarketCap User ID
                elif current_step == 4:
                    userid = message_text.strip()
                    is_valid, validation_message = self.validators.validate_coinmarketcap_userid(userid)

                    if is_valid:
                        is_follower = await self.verify_social_follow('coinmarketcap', userid)
                        if is_follower:
                            if await self.db.save_social_username(user_id, 'coinmarketcap', userid):
                                await self.db.update_user_step(user_id, 4, True)
                                await update.message.reply_text(
                                    f"{EMOJIS['checkmark']} *CoinMarketCap Verified!*\n\n"
                                    f"User ID: {userid}\n"
                                    f"Thank you for following us on CoinMarketCap! {EMOJIS['coinmarketcap']}\n\n"
                                    "Moving to next step...",
                                    parse_mode='Markdown'
                                )
                                await self.show_step(update, context, 5)
                            else:
                                await update.message.reply_text(MESSAGE_TEMPLATES['error_saving'].format('CoinMarketCap User ID'))
                        else:
                            await update.message.reply_text(
                                f"{EMOJIS['warning']} *User ID received but not verified*\n\n"
                                f"User ID: {userid}\n\n"
                                "*Please make sure you:*\n"
                                "1. Actually followed our project on CoinMarketCap\n"
                                "2. Added to your watchlist\n"
                                "3. Wait 30 seconds then try again\n\n"
                                f"CoinMarketCap: {SOCIAL_LINKS['coinmarketcap']}",
                                parse_mode='Markdown'
                            )
                    else:
                        await update.message.reply_text(
                            MESSAGE_TEMPLATES['invalid_coinmarketcap_id'].format(validation_message)
                        )
                    return

                # Step 5: Handle BEP20 address
                elif current_step == 5:
                    is_valid, message = self.validators.validate_bep20_address(message_text)
                    if is_valid:
                        if await self.db.save_bep20_address(user_id, message_text):
                            await self.db.update_user_step(user_id, 5, True)
                            await update.message.reply_text(
                                f"{EMOJIS['checkmark']} *BEP20 Address Saved!*\n\n"
                                f"Address: `{message_text}`\n\n"
                                "Moving to final step...",
                                parse_mode='Markdown'
                            )
                            await self.show_step(update, context, 6)
                        else:
                            await update.message.reply_text(MESSAGE_TEMPLATES['error_saving'].format('address'))
                    else:
                        await update.message.reply_text(
                            MESSAGE_TEMPLATES['invalid_address'].format(message) +
                            "\n• Must start with 0x\n• Must be 42 characters long\n• Example: 0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52"
                        )
                    return

                # Default response
                await update.message.reply_text(
                    f"{EMOJIS['target']} *You're currently on step {current_step}*\n\n"
                    "Please follow the instructions above or use the buttons provided.\n\n" +
                    MESSAGE_TEMPLATES['need_help'],
                    parse_mode='Markdown'
                )

                # Update performance metrics
                await self._update_performance_metrics(time.time() - start_time, success=True)

        except Exception as e:
            logger.error(f"Error in message handler for user {user_id}: {e}")
            await update.message.reply_text(
                f"{EMOJIS['cross']} An error occurred. Please try again or contact support: @Minatirewards"
            )
            await self._update_performance_metrics(time.time() - start_time, success=False)

    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral statistics and link"""
        user_id = update.effective_user.id
        user_data = await self.db.get_user_with_retry(user_id)

        if not user_data:
            await update.message.reply_text(MESSAGE_TEMPLATES['user_not_found'])
            return

        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

        stats_text = REFERRAL_STATS_TEMPLATE.format(
            total_referrals=referral_stats['total_referrals'],
            total_rewards=referral_stats['total_rewards'],
            bot_username=REFERRAL_CONFIG['bot_username'],
            referral_code=user_data.get('referral_code', 'No code'),
            website=SOCIAL_LINKS['website']
        )

        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['stats']} View Status", callback_data=CALLBACK_DATA['show_status'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            stats_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Status command with verification info and referral stats"""
        user_id = update.effective_user.id
        user_data = await self.db.get_user_with_retry(user_id)

        if not user_data:
            await update.message.reply_text(MESSAGE_TEMPLATES['user_not_found'])
            return

        current_step = user_data.get('current_step', 1)
        steps_completed = user_data.get('steps_completed', {})
        bep20_address = user_data.get('bep20_address')
        social_usernames = user_data.get('social_usernames', {})
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})
        is_referred = user_data.get('is_referred', False)
        reward_info = user_data.get('reward_info', {})

        status_text = STATUS_TEMPLATE.format(
            current_step, TOTAL_STEPS,
            len(steps_completed), TOTAL_STEPS,
            STATUS_ICONS['completed'] if steps_completed.get('step_1') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if steps_completed.get('step_2') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if steps_completed.get('step_3') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if steps_completed.get('step_4') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if steps_completed.get('step_5') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if steps_completed.get('step_6') else STATUS_ICONS['not_completed'],
            social_usernames.get('twitter', 'Not provided'),
            social_usernames.get('instagram', 'Not provided'),
            social_usernames.get('coinmarketcap', 'Not provided'),
            STATUS_ICONS['provided'] if bep20_address else STATUS_ICONS['not_provided'],
            STATUS_ICONS['referred'] if is_referred else STATUS_ICONS['normal'],
            referral_stats['total_referrals'],
            referral_stats['total_rewards'],
            reward_info.get('mntc_earned', 0),
            STATUS_ICONS.get(reward_info.get('reward_status', 'not_completed_reward'), '❌ Not Completed'),
            MESSAGE_TEMPLATES['all_completed'] if current_step > TOTAL_STEPS else f"Continue with Step {current_step}"
        )

        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])],
            [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            status_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced help command"""
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['phone']} Support", url=SOCIAL_LINKS['support']),
             InlineKeyboardButton(f"{EMOJIS['mobile']} Download App", url=SOCIAL_LINKS['app_download'])],
            [InlineKeyboardButton(f"{EMOJIS['twitter']} Twitter", url=SOCIAL_LINKS['twitter']),
             InlineKeyboardButton(f"{EMOJIS['instagram']} Instagram", url=SOCIAL_LINKS['instagram'])],
            [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Updated help text with +2 MNTC referrer bonus
        help_text = f"""
🆘 *Minati Vault Bot Help*

*Available Commands:*
• /start - Start or restart the bot
• /status - Check your current progress
• /help - Show this help message
• /stats - Bot statistics
• /performance - Show performance metrics (admin)

*Verification Process:*
✅ Username collection for Twitter, Instagram & CoinMarketCap
🔐 Address validation for BEP20 wallet

*Referral System:*
💰 Earn +2 MNTC for each successful referral
🎁 Share your referral link after completing all steps

*Need Personal Assistance?*
👨💼 Support: @Minatirewards
📱 Follow: @Minativerseofficial

*Important Notes:*
• Social media usernames/IDs are collected for manual verification
• BEP20 addresses are validated for correct format
• Referral rewards are added manually by admin
• Referral links only work for new users

*Quick Access Links:*
Use the buttons below for instant access to our platforms
"""

        await update.message.reply_text(
            help_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics"""
        try:
            stats = await self.db.get_user_stats()
            total_users = stats.get('total_users', 0)
            completed_users = stats.get('completed_users', 0)
            completion_rate = (completed_users / total_users * 100) if total_users > 0 else 0

            stats_text = STATS_TEMPLATE.format(
                total_users,
                completed_users,
                completion_rate,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )

            await update.message.reply_text(stats_text, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await update.message.reply_text(f"{EMOJIS['cross']} Error retrieving statistics.")

    async def performance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show performance metrics (admin command)"""
        user_id = update.effective_user.id
        
        # Only allow admin users (add your admin user IDs)
        ADMIN_USER_IDS = [7310158785]  # Replace with actual admin user IDs
        if user_id not in ADMIN_USER_IDS:
            await update.message.reply_text("❌ Unauthorized")
            return

        try:
            db_metrics = await self.db.get_performance_metrics()
            bot_metrics = self._performance_metrics

            performance_text = f"""
📊 **Performance Metrics**

**Bot Performance:**
• Total Requests: {bot_metrics['total_requests']:,}
• Failed Requests: {bot_metrics['failed_requests']:,}
• Rate Limited: {bot_metrics['rate_limited_requests']:,}
• Avg Response Time: {bot_metrics['avg_response_time']:.3f}s
• Success Rate: {((bot_metrics['total_requests'] - bot_metrics['failed_requests']) / max(bot_metrics['total_requests'], 1) * 100):.1f}%

**Database Performance:**
• Cache Hits: {db_metrics['performance_metrics']['cache_hits']:,}
• Cache Misses: {db_metrics['performance_metrics']['cache_misses']:,}
• Cache Hit Rate: {(db_metrics['performance_metrics']['cache_hits'] / max(db_metrics['performance_metrics']['cache_hits'] + db_metrics['performance_metrics']['cache_misses'], 1) * 100):.1f}%
• Avg DB Response: {db_metrics['performance_metrics']['avg_response_time']:.3f}s

**Concurrency:**
• Max Concurrent Ops: {db_metrics['max_concurrent_operations']}
• Current Concurrent: {db_metrics['current_concurrent_operations']}
• Utilization: {(db_metrics['current_concurrent_operations'] / db_metrics['max_concurrent_operations'] * 100):.1f}%

**Cache Status:**
• User Cache Size: {db_metrics['user_cache_size']:,}
• Referral Cache Size: {db_metrics['cache_size']:,}
• Circuit Breaker: {"🔴 OPEN" if db_metrics['circuit_breaker_open'] else "🟢 CLOSED"}
• Connection Failures: {db_metrics['connection_failures']}

**Optimization Status:** ✅ ACTIVE
"""

            await update.message.reply_text(performance_text, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            await update.message.reply_text(f"❌ Error retrieving performance metrics: {e}")

    async def health_check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to check database health"""
        user_id = update.effective_user.id

        # Only allow admin users (add your admin user IDs)
        ADMIN_USER_IDS = [123456789]  # Replace with actual admin user IDs
        if user_id not in ADMIN_USER_IDS:
            await update.message.reply_text("❌ Unauthorized")
            return

        try:
            health = await self.db.health_check()
            status_emoji = "✅" if health['status'] == 'healthy' else "❌"
            circuit_status = "🔴 OPEN" if health.get('circuit_breaker_open') else "🟢 CLOSED"

            health_message = f"""
{status_emoji} **Database Health Check**

**Status:** {health['status'].upper()}
**Circuit Breaker:** {circuit_status}
**Connection Failures:** {health.get('connection_failures', 0)}
**Concurrent Operations:** {health.get('concurrent_operations', 0)}/{health.get('max_concurrent_operations', 100)}
**Cache Size:** {health.get('cache_size', 0)} items
**Last Check:** {health['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}
"""

            if health['status'] != 'healthy':
                health_message += f"\n**Error:** {health.get('error', 'Unknown')}"

            await update.message.reply_text(health_message, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"❌ Health check failed: {e}")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced error handler with conflict resolution and performance tracking"""
        logger.error(f'Update {update} caused error {context.error}')
        
        # Update error metrics
        self._performance_metrics['failed_requests'] += 1

        # Handle specific error types
        if isinstance(context.error, Conflict):
            logger.error("❌ CONFLICT ERROR: Bot token is being used by another instance!")
            logger.error("💡 Solution: Stop other instances or delete webhook")
        elif isinstance(context.error, NetworkError):
            logger.warning("⚠️ Network error occurred, will retry automatically...")
        elif isinstance(context.error, TimedOut):
            logger.warning("⏱️ Request timed out, this is normal under high load")
        elif isinstance(context.error, BadRequest):
            logger.warning(f"📝 Bad request: {context.error}")
        elif isinstance(context.error, Forbidden):
            logger.error(f"🚫 Forbidden: {context.error}")

    def setup_handlers(self):
        """Setup all command and message handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("referral", self.referral_command))
        self.application.add_handler(CommandHandler("health", self.health_check_command))
        self.application.add_handler(CommandHandler("performance", self.performance_command))

        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

        # Message handler
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Error handler
        self.application.add_error_handler(self.error_handler)

    async def cleanup_telegram_bot(self):
        """Clean up Telegram bot connections and webhooks"""
        try:
            logger.info("🧹 Cleaning up Telegram bot connections...")
            # Create temporary application for cleanup
            temp_app = Application.builder().token(config.BOT_TOKEN).build()

            try:
                # Initialize the application
                await temp_app.initialize()

                # Delete webhook if exists (this can cause conflicts with polling)
                try:
                    await temp_app.bot.delete_webhook(drop_pending_updates=True)
                    logger.info("✅ Webhook deleted successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Webhook deletion failed (may not exist): {e}")

                # Get bot info to verify connection
                bot_info = await temp_app.bot.get_me()
                logger.info(f"✅ Bot connection verified: @{bot_info.username}")

            except Conflict as e:
                logger.error(f"❌ CONFLICT: {e}")
                logger.error("💡 Another instance is using this bot token!")
                raise

            except Exception as e:
                logger.warning(f"⚠️ Bot cleanup warning: {e}")

            finally:
                # Always shutdown temp application
                try:
                    await temp_app.shutdown()
                except:
                    pass

        except Exception as e:
            logger.error(f"❌ Bot cleanup failed: {e}")
            raise

    
    async def start_bot(self):
        """Start the bot with enhanced conflict resolution and performance monitoring"""
        try:
            logger.info(f"{EMOJIS['rocket']} Starting Minati Vault Bot with Full Optimization...")

            # Initialize services first
            await self.initialize_services_async()

            # Clean up any existing connections
            await self.cleanup_telegram_bot()

            # Create application with optimized settings
            self.application = (
                Application.builder()
                .token(config.BOT_TOKEN)
                .concurrent_updates(100)  # Allow more concurrent updates
                .build()
            )

            # Setup handlers
            self.setup_handlers()

            logger.info(f"{EMOJIS['checkmark']} Bot handlers configured")
            logger.info(f"{EMOJIS['fire']} Firebase connection: Ready")
            logger.info(f"🆔 Firebase Project: {config.FIREBASE_PROJECT_ID}")
            logger.info(f"{EMOJIS['stats']} Enhanced validation features: ACTIVE")
            logger.info(f"{EMOJIS['gift']} Referral system: ACTIVE")
            logger.info(f"⚡ Async database operations: ACTIVE")
            logger.info(f"🚀 Rate limiting: ACTIVE")
            logger.info(f"💾 Memory caching: ACTIVE")
            logger.info(f"📊 Performance monitoring: ACTIVE")
            logger.info(f"🔧 Circuit breaker: ACTIVE")
            logger.info(f"{EMOJIS['target']} Starting polling...")

            self.running = True

            # Initialize the application with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await self.application.initialize()
                    await self.application.start()
                    break
                except Conflict as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Conflict on attempt {attempt + 1}, retrying in 5 seconds...")
                        await asyncio.sleep(5)
                        await self.cleanup_telegram_bot()
                    else:
                        raise

            # Start polling with enhanced error handling
            try:
                # Removed unsupported timeout parameters here:
                await self.application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True
                )

                logger.info(f"{EMOJIS['checkmark']} Bot started successfully!")
                logger.info(f"🚀 Ready to handle {self._max_concurrent_operations} concurrent operations")
                logger.info(f"⚡ Optimized for high-performance concurrent processing")

                # Start performance monitoring task
                asyncio.create_task(self.performance_monitor())
                # Start cache optimization task
                asyncio.create_task(self.cache_optimizer())

                # Keep the bot running
                while self.running:
                    await asyncio.sleep(1)

            except Conflict as e:
                logger.error(f"❌ POLLING CONFLICT: {e}")
                logger.error("💡 SOLUTION: Another instance is running or webhook is set!")
                logger.error("🔧 Try: 1) Stop other instances 2) Delete webhook manually")
                raise

        except Conflict as e:
            logger.error(f"❌ TELEGRAM CONFLICT ERROR: {e}")
            logger.error("=" * 60)
            logger.error("🚨 CONFLICT RESOLUTION STEPS:")
            logger.error("1. Check if another instance of this bot is running")
            logger.error("2. Check if webhook is set (conflicts with polling)")
            logger.error("3. Wait 1-2 minutes and try again")
            logger.error("4. Use BotFather to revoke and regenerate token if needed")
            logger.error("=" * 60)
            sys.exit(1)

        except Exception as e:
            logger.error(f"❌ Error starting bot: {e}")
            raise

        finally:
            if self.application:
                await self.stop_bot()


    async def performance_monitor(self):
        """Background task to monitor and log performance metrics"""
        while self.running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                if self._performance_metrics['total_requests'] > 0:
                    success_rate = ((self._performance_metrics['total_requests'] - self._performance_metrics['failed_requests']) / 
                                  self._performance_metrics['total_requests'] * 100)
                    
                    logger.info(
                        f"📊 Performance Report - "
                        f"Requests: {self._performance_metrics['total_requests']}, "
                        f"Success Rate: {success_rate:.1f}%, "
                        f"Avg Response: {self._performance_metrics['avg_response_time']:.3f}s, "
                        f"Rate Limited: {self._performance_metrics['rate_limited_requests']}"
                    )
                    
            except Exception as e:
                logger.error(f"Error in performance monitor: {e}")

    async def cache_optimizer(self):
        """Background task to optimize caches"""
        while self.running:
            try:
                await asyncio.sleep(600)  # Every 10 minutes
                await self.db.optimize_cache()
                logger.debug("Cache optimization completed")
                
            except Exception as e:
                logger.error(f"Error in cache optimizer: {e}")

    async def stop_bot(self):
        """Stop the bot gracefully with enhanced cleanup"""
        try:
            logger.info(f"{EMOJIS['stop']} Stopping bot gracefully...")
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
                    self.db.close_connection()
                    logger.info("✅ Database connection closed")
                except Exception as e:
                    logger.warning(f"⚠️ Database close warning: {e}")

            logger.info(f"{EMOJIS['checkmark']} Bot stopped gracefully")

        except Exception as e:
            logger.error(f"❌ Error stopping bot: {e}")

    def signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        logger.info(f"📡 Received signal {sig}, shutting down...")
        self.running = False

# Main execution
async def main():
    """Main function to run the bot with enhanced error handling and optimization"""
    # Enhanced configuration validation
    logger.info("🔍 Validating configuration...")
    if not config.BOT_TOKEN:
        logger.error(f"{EMOJIS['cross']} BOT_TOKEN not found in environment variables!")
        logger.error("💡 Set BOT_TOKEN in your .env file or environment")
        sys.exit(1)

    if not config.FIREBASE_PROJECT_ID:
        logger.error(f"{EMOJIS['cross']} FIREBASE_PROJECT_ID not found in environment variables!")
        logger.error("💡 Set FIREBASE_PROJECT_ID in your .env file or environment")
        sys.exit(1)

    logger.info("✅ Configuration validated successfully")

    # Create optimized bot instance
    bot = MinatiVaultBot()

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
        logger.error("🔧 Please resolve the conflict and try again")
        sys.exit(1)
    except Exception as e:
        logger.error(f"{EMOJIS['cross']} Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    try:
        # Check for existing processes
        pid = os.getpid()
        logger.info(f"🚀 Starting Optimized Minati Vault Bot (PID: {pid})")
        logger.info("⚡ Full async support, concurrency optimization, and performance monitoring enabled")

        # Run the bot
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info(f"{EMOJIS['fire']} Bot interrupted by user")
    except Conflict as e:
        logger.error(f"{EMOJIS['cross']} TELEGRAM BOT CONFLICT: {e}")
        logger.error("🔧 RESOLUTION: Stop other instances or delete webhook")
        sys.exit(1)
    except Exception as e:
        logger.error(f"{EMOJIS['cross']} Fatal startup error: {e}")
        sys.exit(1)


