# main.py

import logging
import logging.config
import asyncio
import signal
import sys
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut, Conflict

from database import Database 
from validators import Validators

# from database_optimized import OptimizedDatabase as Database
# from validators_optimized import OptimizedValidators as Validators
import config
from constants import (
    TOTAL_STEPS,
    CALLBACK_DATA,
    MESSAGE_TEMPLATES,
    HELP_TEMPLATES,
    STATUS_TEMPLATE,
    STATS_TEMPLATE,
    REFERRAL_STATS_TEMPLATE,
    EMOJIS,
    STATUS_ICONS,
    SOCIAL_LINKS,
    STEPS,
    WELCOME_MESSAGE,
    WELCOME_MESSAGE_REFERRED,
    REFERRAL_CONFIG,
)

logging.config.dictConfig(config.LOGGING_CONFIG)
logger = logging.getLogger(__name__)

db: Database
validators: Validators

def initialize_services():
    global db, validators
    validators = Validators()
    db = Database()

class MinatiVaultBot:
    def __init__(self):
        self.application = None
        self.running = False
        self._last_start_time = None
        self._last_start_user = None

    async def initialize_services_async(self):
        initialize_services()

    async def verify_social_follow(self, platform: str, username: str) -> bool:
        if platform == "coinmarketcap":
            is_valid, _ = validators.validate_coinmarketcap_userid(username)
        else:
            is_valid, _ = validators.validate_username(username)
        return is_valid

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id
        username = user.username or "NoUsername"
        first_name = user.first_name or "User"

        now = datetime.now()
        if (
            self._last_start_time
            and self._last_start_user == user_id
            and (now - self._last_start_time).total_seconds() < 5
        ):
            return
        self._last_start_time = now
        self._last_start_user = user_id

        referral_code = None
        if context.args:
            param = context.args[0]
            if validators.is_valid_referral_link_param(param):
                referral_code = validators.extract_referral_code_from_start_param(param)

        existing = await db.get_user_with_retry(user_id)
        if not existing:
            referred_by = None
            if referral_code:
                referrer = await db.get_user_by_referral_code_async(referral_code)
                if not referrer:
                    await update.message.reply_text(
                        EMOJIS["cross"] + " Referral code not found."
                    )
                    return
                if referrer["user_id"] == user_id:
                    await update.message.reply_text(
                        EMOJIS["cross"] + " You cannot use your own referral code!"
                    )
                    return
                referred_by = referral_code

            created = await db.create_user_with_retry(
                user_id, username, first_name, referred_by
            )
            if created:
                welcome = (
                    WELCOME_MESSAGE_REFERRED if referred_by else WELCOME_MESSAGE
                )
                await update.message.reply_text(
                    f"Welcome {first_name}! {EMOJIS['party']}\n\n{welcome}"
                )
                await self.show_step(update, context, 1)
                return

        # existing flow
        current = existing.get("current_step", 1)
        await update.message.reply_text(
            f"Welcome back {first_name}! {EMOJIS['fire']}\nYou're on step {current}."
        )
        if current > TOTAL_STEPS:
            await self.show_completion(update, existing)
        else:
            await self.show_step(update, context, current)

    async def show_step(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, step: int
    ):
        if step > TOTAL_STEPS:
            data = await db.get_user_with_retry(update.effective_user.id)
            await self.show_completion(update, data)
            return

        text = STEPS.get(step, "Invalid step")
        keyboard = []
        if step == 1:
            keyboard = [
                [InlineKeyboardButton("📥 Download App", url=SOCIAL_LINKS["app_download"])],
                [
                    InlineKeyboardButton(
                        "✅ Downloaded & Reviewed", callback_data=CALLBACK_DATA["verify_step_1"]
                    )
                ],
            ]
        elif step == 2:
            keyboard = [
                [InlineKeyboardButton("🐦 Follow on Twitter", url=SOCIAL_LINKS["twitter"])],
                [
                    InlineKeyboardButton(
                        "ℹ️ Send Username", callback_data=CALLBACK_DATA["twitter_info"]
                    )
                ],
                [InlineKeyboardButton("❓ Need Help", callback_data=CALLBACK_DATA["help"])],
            ]
        elif step == 3:
            keyboard = [
                [InlineKeyboardButton("📸 Follow on Instagram", url=SOCIAL_LINKS["instagram"])],
                [
                    InlineKeyboardButton(
                        "ℹ️ Send Username", callback_data=CALLBACK_DATA["instagram_info"]
                    )
                ],
            ]
        elif step == 4:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📊 Visit CoinMarketCap", url=SOCIAL_LINKS["coinmarketcap"]
                    )
                ],
                [
                    InlineKeyboardButton(
                        "ℹ️ Send User ID", callback_data=CALLBACK_DATA["coinmarketcap_info"]
                    )
                ],
            ]
        elif step == 5:
            keyboard = [
                [InlineKeyboardButton("ℹ️ Send BEP20 Address", callback_data=CALLBACK_DATA["bep20_info"])]
            ]
        elif step == 6:
            data = await db.get_user_with_retry(update.effective_user.id)
            missing = []
            for field, key in [
                ("Twitter", "twitter"),
                ("Instagram", "instagram"),
                ("CoinMarketCap", "coinmarketcap"),
            ]:
                if not data["social_usernames"].get(key):
                    missing.append(field)
            if not data.get("bep20_address"):
                missing.append("BEP20 address")

            if not missing:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🎉 Complete Process", callback_data=CALLBACK_DATA["complete_process"]
                        )
                    ]
                ]
            else:
                text += "\n\n⚠️ Missing: " + ", ".join(missing)
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🔄 Check Status", callback_data=CALLBACK_DATA["show_status"]
                        )
                    ],
                    [InlineKeyboardButton("❓ Need Help", callback_data=CALLBACK_DATA["help"])],
                ]

        await update.message.reply_text(
            f"Step {step}/{TOTAL_STEPS}\n\n{text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None,
        )

    async def show_completion(self, update_or_query, data: dict):
        text = (
            f"🎉 Congratulations! 🎉\n\nYou have completed all steps!\n\n"
            f"🎁 Your Referral Link:\n"
            f"https://t.me/{REFERRAL_CONFIG['bot_username']}?start={data['referral_code']}\n\n"
            f"📊 Referrals: {data['referral_stats']['total_referrals']}\n"
            f"💰 Rewards: {data['referral_stats']['total_referrals'] * 2} MNTC\n"
            f"📞 Support: @Minatirewards"
        )
        buttons = [
            [InlineKeyboardButton("📊 View Status", callback_data=CALLBACK_DATA["show_status"])],
            [InlineKeyboardButton("🌐 Website", url=SOCIAL_LINKS["website"])],
        ]
        if isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=None)
        else:
            await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=None)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = await db.get_user_with_retry(user_id)
        if not data:
            await query.edit_message_text(MESSAGE_TEMPLATES["user_not_found"])
            return

        step = data.get("current_step", 1)
        if query.data == CALLBACK_DATA["verify_step_1"]:
            if step == 1:
                await db.update_user_step(user_id, 1, True)
                await query.edit_message_text("✅ App confirmed. Next...")
                await self.show_step(update, context, 2)
            else:
                await query.edit_message_text(MESSAGE_TEMPLATES["step_mismatch"].format(1))
        elif query.data == CALLBACK_DATA["complete_process"]:
            if step >= TOTAL_STEPS:
                await self.show_completion(query, data)
            else:
                await query.edit_message_text(
                    f"❌ You are on step {step}, complete all first."
                )
        elif query.data == CALLBACK_DATA["twitter_info"]:
            await query.edit_message_text(HELP_TEMPLATES["instructions"]["twitter"])
        elif query.data == CALLBACK_DATA["instagram_info"]:
            await query.edit_message_text(HELP_TEMPLATES["instructions"]["instagram"])
        elif query.data == CALLBACK_DATA["coinmarketcap_info"]:
            await query.edit_message_text(HELP_TEMPLATES["instructions"]["coinmarketcap"])
        elif query.data == CALLBACK_DATA["bep20_info"]:
            await query.edit_message_text(HELP_TEMPLATES["instructions"]["bep20"])
        elif query.data == CALLBACK_DATA["show_status"]:
            await self.status_callback(query, data)
        elif query.data == CALLBACK_DATA["show_referral"]:
            await self.referral_callback(query, data)
        elif query.data == CALLBACK_DATA["help"]:
            await query.edit_message_text(HELP_TEMPLATES["help_button"], parse_mode="Markdown")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text.strip()
        data = await db.get_user_with_retry(user_id)
        if not data:
            await update.message.reply_text("❌ Please /start first.")
            return

        step = data.get("current_step", 1)
        if step == 2:
            username = text.lstrip("@")
            valid, msg = validators.validate_username(username)
            if valid and await self.verify_social_follow("twitter", username):
                await db.save_social_username(user_id, "twitter", username)
                await db.update_user_step(user_id, 2, True)
                await update.message.reply_text("✅ Twitter ok. Next...")
                await self.show_step(update, context, 3)
            else:
                await update.message.reply_text(msg)
        elif step == 3:
            username = text.lstrip("@")
            valid, msg = validators.validate_username(username)
            if valid and await self.verify_social_follow("instagram", username):
                await db.save_social_username(user_id, "instagram", username)
                await db.update_user_step(user_id, 3, True)
                await update.message.reply_text("✅ Instagram ok. Next...")
                await self.show_step(update, context, 4)
            else:
                await update.message.reply_text(msg)
        elif step == 4:
            userid = text
            valid, msg = validators.validate_coinmarketcap_userid(userid)
            if valid and await self.verify_social_follow("coinmarketcap", userid):
                await db.save_social_username(user_id, "coinmarketcap", userid)
                await db.update_user_step(user_id, 4, True)
                await update.message.reply_text("✅ CMC ok. Next...")
                await self.show_step(update, context, 5)
            else:
                await update.message.reply_text(msg)
        elif step == 5:
            addr = text
            valid, msg = validators.validate_bep20_address(addr)
            if valid:
                await db.save_bep20_address(user_id, addr)
                await db.update_user_step(user_id, 5, True)
                await update.message.reply_text("✅ Address ok. Final...")
                await self.show_step(update, context, 6)
            else:
                await update.message.reply_text(msg)
        else:
            await update.message.reply_text(
                f"You're on step {step}. Use the buttons or /status."
            )

    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        data = await db.get_user_with_retry(user_id)
        if not data:
            await update.message.reply_text("❌ /start first.")
            return
        code = data["referral_code"]
        stats = data["referral_stats"]["total_referrals"]
        text = REFERRAL_STATS_TEMPLATE.format(
            total_referrals=stats,
            total_rewards=stats * 2,
            bot_username=REFERRAL_CONFIG["bot_username"],
            referral_code=code,
            website=SOCIAL_LINKS["website"],
        )
        await update.message.reply_text(text, parse_mode=None)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        data = await db.get_user_with_retry(user_id)
        if not data:
            await update.message.reply_text("❌ /start first.")
            return
        step = data.get("current_step", 1)
        completed = len(data["steps_completed"])
        text = STATUS_TEMPLATE.format(
            step,
            TOTAL_STEPS,
            completed,
            TOTAL_STEPS,
            *(STATUS_ICONS["completed"] if data["steps_completed"].get(f"step_{i}") else STATUS_ICONS["not_completed"] for i in range(1, 7)),
            data["social_usernames"]["twitter"] or "N/A",
            data["social_usernames"]["instagram"] or "N/A",
            data["social_usernames"]["coinmarketcap"] or "N/A",
            STATUS_ICONS["provided"] if data.get("bep20_address") else STATUS_ICONS["not_provided"],
            STATUS_ICONS["referred"] if data.get("is_referred") else STATUS_ICONS["normal"],
            data["referral_stats"]["total_referrals"],
            data["referral_stats"]["total_rewards"],
            data["reward_info"].get("mntc_earned", 0),
            data["reward_info"].get("reward_status", "not_completed_reward"),
            MESSAGE_TEMPLATES["all_completed"] if step > TOTAL_STEPS else f"Continue: Step {step}",
        )
        await update.message.reply_text(text, parse_mode=None)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = db.get_user_stats()
        total = stats["total_users"]
        done = stats["completed_users"]
        rate = (done / total * 100) if total else 0
        text = STATS_TEMPLATE.format(total, done, rate, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        await update.message.reply_text(text, parse_mode=None)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(HELP_TEMPLATES["help_button"], parse_mode="Markdown")

    async def health_check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        ADMIN_IDS = [123456789]
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ Unauthorized")
            return
        health = db.health_check()
        status = "✅ HEALTHY" if health["status"] == "healthy" else "❌ UNHEALTHY"
        cb = "🟢 CLOSED" if not health["circuit_breaker_open"] else "🔴 OPEN"
        text = (
            f"{status}\nCircuit: {cb}\nFailures: {health['connection_failures']}\n"
            f"Time: {health['timestamp']}"
        )
        await update.message.reply_text(text, parse_mode=None)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Error: {context.error}")
        if isinstance(context.error, Conflict):
            logger.error("Conflict: webhook or another instance active")
        elif isinstance(context.error, NetworkError):
            logger.warning("NetworkError retrying...")
        elif isinstance(context.error, TimedOut):
            logger.warning("TimedOut request")
        elif isinstance(context.error, BadRequest):
            logger.warning(f"BadRequest: {context.error}")
        elif isinstance(context.error, Forbidden):
            logger.warning(f"Forbidden: {context.error}")

    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("referral", self.referral_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("health", self.health_check_command))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        self.application.add_error_handler(self.error_handler)

    async def start_polling(self):
        await self.initialize_services_async()
        self.application = Application.builder().token(config.BOT_TOKEN).build()
        self.setup_handlers()
        await self.application.initialize()
        await self.application.start()
        self.running = True
        while self.running:
            await asyncio.sleep(1)
        await self.application.stop()
        await self.application.shutdown()
        db.close_connection()

async def main():
    bot = MinatiVaultBot()
    def sig(sig, frame):
        bot.running = False
    signal.signal(signal.SIGINT, sig)
    signal.signal(signal.SIGTERM, sig)
    await bot.start_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)
