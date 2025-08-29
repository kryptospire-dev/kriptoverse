import logging
import logging.config
import asyncio
import signal
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut
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

# Initialize database and validators
db = Database()
validators = Validators()

class MinatiVaultBot:
    def __init__(self):
        self.db = db
        self.validators = validators
        self.application = None
        self.running = False

    async def verify_social_follow(self, platform: str, username: str) -> bool:
        """Verify if user actually follows on social media"""
        # For now, we'll do basic username validation
        # In production, you'd integrate with Twitter/Instagram APIs
        if platform == 'coinmarketcap':
            is_valid, _ = self.validators.validate_coinmarketcap_userid(username)
        else:
            is_valid, _ = self.validators.validate_username(username)
        return is_valid

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler with referral support - MODIFIED to ignore referral for existing users"""
        user = update.effective_user
        user_id = user.id
        username = user.username or "No username"
        first_name = user.first_name or "User"

        # Extract referral code from deep link if present
        referral_code = None
        if context.args and len(context.args) > 0:
            potential_referral = context.args[0]
            if self.validators.is_valid_referral_link_param(potential_referral):
                referral_code = self.validators.extract_referral_code_from_start_param(potential_referral)
                if referral_code:
                    logger.info(f"User {user_id} accessed via referral code: {referral_code}")

        logger.info(f"User {user_id} ({first_name}) started the bot")

        # Check if user exists in database
        existing_user = self.db.get_user(user_id)

        if not existing_user:
            # NEW USER - Apply referral logic
            referred_by = None
            if referral_code:
                # Validate referral code exists and get referrer
                referrer = self.db.get_user_by_referral_code(referral_code)
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

            if self.db.create_user(user_id, username, first_name, referred_by):
                welcome_msg = WELCOME_MESSAGE_REFERRED if referred_by else WELCOME_MESSAGE
                await update.message.reply_text(
                    f"Welcome {first_name}! {EMOJIS['party']}\n\n{welcome_msg}"
                )
                await self.show_step(update, context, 1)
            else:
                await update.message.reply_text(
                    f"{EMOJIS['cross']} Error creating your profile. Please try again later."
                )
        else:
            # EXISTING USER - IGNORE REFERRAL
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
                    f"Welcome back {first_name}! {EMOJIS['fire']}\n\nYou're currently on step {current_step}."
                )

            if current_step > TOTAL_STEPS:
                # User already completed
                await self.show_completion_with_referral(update, existing_user)
            else:
                # Show current step
                await self.show_step(update, context, current_step)

    async def show_completion_with_referral(self, update: Update, user_data: dict):
        """Show completion message with referral link for completed users - MODIFIED to remove restart button"""
        user_id = user_data['user_id']
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})

        # MODIFIED - Removed restart process button
        keyboard = [
            # [InlineKeyboardButton(f"{EMOJIS['refresh']} Start Over", callback_data=CALLBACK_DATA['restart_process'])],  # COMMENTED OUT
            [InlineKeyboardButton(f"{EMOJIS['stats']} View Status", callback_data=CALLBACK_DATA['show_status'])],
            [InlineKeyboardButton(f"{EMOJIS['gift']} Referral Stats", callback_data=CALLBACK_DATA['show_referral'])],
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
• Total Referral Rewards: **{referral_stats['total_rewards']} MNTC**

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
            user_data = self.db.get_user(update.effective_user.id)
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
            # FIXED: Check if user has all required data before allowing completion
            user_data = self.db.get_user(update.effective_user.id)
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
        """Handle inline keyboard button clicks with validation - MODIFIED to remove restart process"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)

        if not user_data:
            await query.edit_message_text(MESSAGE_TEMPLATES['user_not_found'])
            return

        current_step = user_data.get('current_step', 1)

        # Step 1 verification - FIXED to properly show Step 2
        if query.data == CALLBACK_DATA['verify_step_1']:
            if current_step == 1:
                self.db.update_user_step(user_id, 1, True)
                await query.edit_message_text(f"{EMOJIS['checkmark']} Great! App download confirmed.\n\nMoving to Twitter step...")

                # Send Step 2 as a new message instead of trying to edit
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

        # CoinMarketCap verification
        elif query.data == CALLBACK_DATA['verify_coinmarketcap']:
            if current_step == 4:
                await query.edit_message_text(f"{EMOJIS['checkmark']} CoinMarketCap User ID received. Moving to next step...")
                await self.show_step_callback(query, context, 5)
            else:
                await query.edit_message_text(MESSAGE_TEMPLATES['step_mismatch'].format(4))

        # Complete process - FIXED LOGIC
        elif query.data == CALLBACK_DATA['complete_process']:
            logger.info(f"Complete process clicked by user {user_id}, current_step: {current_step}")

            # Check if user is on step 6 OR has already completed
            if current_step == 6:
                logger.info(f"User {user_id} completing step 6")
                # User is on step 6, complete the process
                self.db.update_user_step(user_id, 6, True)
                # Get fresh user data after completion
                fresh_user_data = self.db.get_user(user_id)
                await self.send_completion_message(query, fresh_user_data)
            elif current_step > 6:
                logger.info(f"User {user_id} already completed, showing completion again")
                # User already completed, show completion again
                await self.send_completion_message(query, user_data)
            else:
                logger.warning(f"User {user_id} tried to complete from step {current_step}")
                # User is not on step 6 yet
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

        # COMMENTED OUT - Restart process disabled
        # elif query.data == CALLBACK_DATA['restart_process']:
        #     try:
        #         self.db.reset_user_progress(user_id, keep_referral_data=True)
        #         await query.edit_message_text(MESSAGE_TEMPLATES['process_restarted'])
        #         await self.show_step_callback(query, context, 1)
        #     except Exception as e:
        #         await query.edit_message_text(f"{EMOJIS['cross']} Error restarting. Please try /start again.")

        # Show status
        elif query.data == CALLBACK_DATA['show_status']:
            # Get fresh user data for status
            fresh_user_data = self.db.get_user(user_id)
            await self.show_status_callback(query, fresh_user_data)

        # Show referral stats
        elif query.data == CALLBACK_DATA['show_referral']:
            # Get fresh user data for referral stats
            fresh_user_data = self.db.get_user(user_id)
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

    async def send_completion_message(self, query, user_data):
        """Send appropriate completion message based on referral status - FIXED"""
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
            if is_referred:
                # Referred user completion
                completion_message = REFERRAL_MESSAGES['referred_completion'].format(
                    twitter=social_usernames.get('twitter', 'Not provided'),
                    instagram=social_usernames.get('instagram', 'Not provided'),
                    coinmarketcap=social_usernames.get('coinmarketcap', 'Not provided'),
                    bep20_short=f"{bep20_address[:10]}...{bep20_address[-6:]}" if bep20_address else 'Not provided',
                    mntc_earned=mntc_earned,
                    website=SOCIAL_LINKS['website']
                )
            else:
                # Normal user completion with referral link
                completion_message = REFERRAL_MESSAGES['normal_completion'].format(
                    twitter=social_usernames.get('twitter', 'Not provided'),
                    instagram=social_usernames.get('instagram', 'Not provided'),
                    coinmarketcap=social_usernames.get('coinmarketcap', 'Not provided'),
                    bep20_short=f"{bep20_address[:10]}...{bep20_address[-6:]}" if bep20_address else 'Not provided',
                    mntc_earned=mntc_earned,
                    bot_username=REFERRAL_CONFIG['bot_username'],
                    referral_code=referral_code,
                    website=SOCIAL_LINKS['website']
                )

            await query.edit_message_text(completion_message, parse_mode='Markdown')

            # Send notification to referrer if user was referred
            if is_referred:
                await self.notify_referrer(user_data.get('referred_by'), user_data['user_id'])

        except Exception as e:
            logger.error(f"Error sending completion message for user {user_data.get('user_id')}: {e}")
            # Fallback message if template formatting fails
            fallback_message = f"""
🎉 **CONGRATULATIONS!** 🎉

You have successfully completed all steps!

**💰 Your Reward:** {mntc_earned} MNTC

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

            referrer = self.db.get_user_by_referral_code(referrer_code)
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
        """Show referral statistics via callback - MODIFIED to remove restart button"""
        referral_stats = user_data.get('referral_stats', {'total_referrals': 0, 'total_rewards': 0})
        stats_text = REFERRAL_STATS_TEMPLATE.format(
            total_referrals=referral_stats['total_referrals'],
            total_rewards=referral_stats['total_rewards'],
            bot_username=REFERRAL_CONFIG['bot_username'],
            referral_code=user_data.get('referral_code', 'No code'),
            website=SOCIAL_LINKS['website']
        )

        # MODIFIED - Removed restart process button
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['stats']} View Status", callback_data=CALLBACK_DATA['show_status'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])]
            # [InlineKeyboardButton(f"{EMOJIS['refresh']} Start Over", callback_data=CALLBACK_DATA['restart_process'])]  # COMMENTED OUT
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(stats_text, parse_mode='Markdown', reply_markup=reply_markup)

    async def show_status_callback(self, query, user_data):
        """Show user status via callback - MODIFIED to remove restart button"""
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
• Your Referrals: {referral_stats['total_referrals']}
• Referral Rewards: {referral_stats['total_rewards']} MNTC

*Reward Information:*
• MNTC Earned: {reward_info.get('mntc_earned', 0)} MNTC
• Reward Type: {reward_info.get('reward_type', 'Unknown').title()}
• Status: {STATUS_ICONS.get(reward_info.get('reward_status', 'pending'), '⏳ Pending')}

*Need Changes?* Contact support for assistance
"""

            # MODIFIED - Removed restart process button for completed users
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['gift']} Referral Stats", callback_data=CALLBACK_DATA['show_referral'])],
                # [InlineKeyboardButton(f"{EMOJIS['refresh']} Start Over", callback_data=CALLBACK_DATA['restart_process'])],  # COMMENTED OUT
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

            # MODIFIED - Removed restart process button for active users
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['gift']} Referral Stats", callback_data=CALLBACK_DATA['show_referral'])],
                # [InlineKeyboardButton(f"{EMOJIS['refresh']} Restart Process", callback_data=CALLBACK_DATA['restart_process'])]  # COMMENTED OUT
            ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            status_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def show_step_callback(self, query, context: ContextTypes.DEFAULT_TYPE, step: int):
        """Show step via callback query"""
        if step > TOTAL_STEPS:
            await context.bot.send_message(query.from_user.id, f"{EMOJIS['party']} All steps completed!")
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
                [InlineKeyboardButton(f"{EMOJIS['info']} Send Username After Following", callback_data=CALLBACK_DATA['twitter_info'])]
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
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=f"*Step {step}/{TOTAL_STEPS}* {EMOJIS['target']}\n\n{step_message}",
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

    # DEBUG METHODS - Remove in production
    async def debug_user_state(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Debug command to check user's current state"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)

        if not user_data:
            await update.message.reply_text("❌ No user data found")
            return

        debug_info = f"""
🔍 **DEBUG: User State Analysis**

**Basic Info:**
• User ID: {user_data['user_id']}
• Current Step: {user_data.get('current_step', 'Unknown')}
• Is Referred: {user_data.get('is_referred', False)}

**Steps Completed:**
• Step 1: {user_data.get('steps_completed', {}).get('step_1', False)}
• Step 2: {user_data.get('steps_completed', {}).get('step_2', False)}
• Step 3: {user_data.get('steps_completed', {}).get('step_3', False)}
• Step 4: {user_data.get('steps_completed', {}).get('step_4', False)}
• Step 5: {user_data.get('steps_completed', {}).get('step_5', False)}
• Step 6: {user_data.get('steps_completed', {}).get('step_6', False)}

**Social Usernames:**
• Twitter: {user_data.get('social_usernames', {}).get('twitter', 'Not provided')}
• Instagram: {user_data.get('social_usernames', {}).get('instagram', 'Not provided')}
• CoinMarketCap: {user_data.get('social_usernames', {}).get('coinmarketcap', 'Not provided')}

**Other Info:**
• BEP20 Address: {user_data.get('bep20_address', 'Not provided')}
• Referral Code: {user_data.get('referral_code', 'Not provided')}

**Reward Info:**
• MNTC Earned: {user_data.get('reward_info', {}).get('mntc_earned', 0)}
• Reward Type: {user_data.get('reward_info', {}).get('reward_type', 'Not set')}
• Reward Status: {user_data.get('reward_info', {}).get('reward_status', 'Not set')}
"""

        await update.message.reply_text(debug_info, parse_mode='Markdown')

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages with enhanced validation"""
        user_id = update.effective_user.id
        message_text = update.message.text.strip()
        user_data = self.db.get_user(user_id)

        if not user_data:
            await update.message.reply_text(f"{EMOJIS['cross']} Please use /start command first.")
            return

        current_step = user_data.get('current_step', 1)

        # Step 2: Handle Twitter username - FIXED to work exactly like Instagram/CoinMarketCap
        if current_step == 2:
            username = message_text.lstrip('@').strip()
            is_valid, validation_message = self.validators.validate_username(username)

            if is_valid:
                is_follower = await self.verify_social_follow('twitter', username)
                if is_follower:
                    if self.db.save_social_username(user_id, 'twitter', username):
                        self.db.update_user_step(user_id, 2, True)
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
                    if self.db.save_social_username(user_id, 'instagram', username):
                        self.db.update_user_step(user_id, 3, True)
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
                    if self.db.save_social_username(user_id, 'coinmarketcap', userid):
                        self.db.update_user_step(user_id, 4, True)
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
                if self.db.save_bep20_address(user_id, message_text):
                    self.db.update_user_step(user_id, 5, True)
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

    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral statistics and link"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)

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
        """Status command with verification info and referral stats - MODIFIED to remove restart button"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)

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

        # MODIFIED - Removed restart process button
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['gift']} Referral Stats", callback_data=CALLBACK_DATA['show_referral'])],
            [InlineKeyboardButton(f"{EMOJIS['globe']} Website", url=SOCIAL_LINKS['website'])],
            [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])],
            # [InlineKeyboardButton(f"{EMOJIS['refresh']} Restart Process", callback_data=CALLBACK_DATA['restart_process'])]  # COMMENTED OUT
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            status_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced help command - MODIFIED to remove reset command reference"""
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['phone']} Support", url=SOCIAL_LINKS['support']),
             InlineKeyboardButton(f"{EMOJIS['mobile']} Download App", url=SOCIAL_LINKS['app_download'])],
            [InlineKeyboardButton(f"{EMOJIS['twitter']} Twitter", url=SOCIAL_LINKS['twitter']),
             InlineKeyboardButton(f"{EMOJIS['instagram']} Instagram", url=SOCIAL_LINKS['instagram'])],
            [InlineKeyboardButton(f"{EMOJIS['coinmarketcap']} CoinMarketCap", url=SOCIAL_LINKS['coinmarketcap'])]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        # MODIFIED help text - removed /reset command reference
        help_text = f"""
🆘 *Minati Vault Bot Help*

*Available Commands:*

• /start - Start or restart the bot
• /status - Check your current progress
• /help - Show this help message
• /stats - Bot statistics
• /referral - Get your referral link and stats

*Verification Process:*

✅ Username collection for Twitter, Instagram & CoinMarketCap
🔐 Address validation for BEP20 wallet

*Referral System:*

💰 Earn +1 MNTC for each successful referral
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

    # COMMENTED OUT - Reset command method disabled
    # async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     """Reset user progress"""
    #     user_id = update.effective_user.id
    #     try:
    #         if self.db.reset_user_progress(user_id, keep_referral_data=True):
    #             await update.message.reply_text(
    #                 f"{EMOJIS['refresh']} **Your progress has been completely reset!**\n\n"
    #                 "All your previous data has been cleared.\n"
    #                 "Your referral information has been preserved.\n"
    #                 "Use /start to begin the process again from Step 1."
    #             )
    #         else:
    #             await update.message.reply_text(
    #                 f"{EMOJIS['cross']} No user data found to reset.\n"
    #                 "Use /start to create your profile first."
    #             )
    #     except Exception as e:
    #         logger.error(f"Error resetting user {user_id}: {e}")
    #         await update.message.reply_text(
    #             f"{EMOJIS['cross']} Error resetting your progress.\n"
    #             "Please try /start to continue."
    #         )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics"""
        try:
            stats = self.db.get_user_stats()
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

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Log errors caused by Updates"""
        logger.error(f'Update {update} caused error {context.error}')

        # Handle specific error types
        if isinstance(context.error, NetworkError):
            logger.warning("Network error occurred, retrying...")
        elif isinstance(context.error, TimedOut):
            logger.warning("Request timed out")
        elif isinstance(context.error, BadRequest):
            logger.warning(f"Bad request: {context.error}")

    def setup_handlers(self):
        """Setup all command and message handlers - MODIFIED to comment out reset command"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

        # COMMENTED OUT - Reset command disabled
        # self.application.add_handler(CommandHandler("reset", self.reset_command))

        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("referral", self.referral_command))

        # DEBUG COMMANDS - Remove these in production
        self.application.add_handler(CommandHandler("debug", self.debug_user_state))

        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

        # Message handler
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Error handler
        self.application.add_error_handler(self.error_handler)

    async def start_bot(self):
        """Start the bot with proper initialization"""
        try:
            logger.info(f"{EMOJIS['rocket']} Starting Minati Vault Bot with Referral System...")

            # Create application
            self.application = Application.builder().token(config.BOT_TOKEN).build()

            # Setup handlers
            self.setup_handlers()

            # Start bot
            logger.info(f"{EMOJIS['checkmark']} Bot handlers configured")
            logger.info(f"{EMOJIS['fire']} Firebase connection: Ready")
            logger.info(f"🆔 Firebase Project: {config.FIREBASE_PROJECT_ID}")
            logger.info(f"{EMOJIS['stats']} Enhanced validation features: ACTIVE")
            logger.info(f"{EMOJIS['gift']} Referral system: ACTIVE")
            logger.info(f"{EMOJIS['target']} Starting polling...")

            self.running = True

            # Initialize the application
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

            logger.info(f"{EMOJIS['checkmark']} Bot started successfully!")

            # Keep the bot running
            while self.running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
        finally:
            if self.application:
                await self.stop_bot()

    async def stop_bot(self):
        """Stop the bot gracefully"""
        try:
            logger.info(f"{EMOJIS['stop']} Stopping bot...")
            self.running = False

            if self.application and self.application.updater:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

            # Close database connection
            self.db.close_connection()

            logger.info(f"{EMOJIS['checkmark']} Bot stopped gracefully")

        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

    def signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {sig}, shutting down...")
        self.running = False

# Main execution
async def main():
    """Main function to run the bot"""
    # Validate configuration
    if not config.BOT_TOKEN:
        logger.error(f"{EMOJIS['cross']} BOT_TOKEN not found in environment variables!")
        sys.exit(1)

    if not config.FIREBASE_PROJECT_ID:
        logger.error(f"{EMOJIS['cross']} FIREBASE_PROJECT_ID not found in environment variables!")
        sys.exit(1)

    # Create bot instance
    bot = MinatiVaultBot()

    # Setup signal handlers
    signal.signal(signal.SIGINT, bot.signal_handler)
    signal.signal(signal.SIGTERM, bot.signal_handler)

    try:
        await bot.start_bot()
    except KeyboardInterrupt:
        logger.info(f"{EMOJIS['fire']} Bot stopped by user")
    except Exception as e:
        logger.error(f"{EMOJIS['cross']} Error running bot: {e}")
        sys.exit(1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info(f"{EMOJIS['fire']} Bot interrupted by user")
    except Exception as e:
        logger.error(f"{EMOJIS['cross']} Fatal error: {e}")
        sys.exit(1)