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
    REFERRAL_CONFIG,
)

# Configure logging
logging.config.dictConfig(config.LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# Rate limiting
class RateLimiter:
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = {}
        self.lock = asyncio.Lock()

    async def is_allowed(self, user_id: int) -> bool:
        async with self.lock:
            now = time.time()
            # clean up
            self.requests = {
                uid: [t for t in times if t > now - self.time_window]
                for uid, times in self.requests.items()
            }
            times = self.requests.get(user_id, [])
            if len(times) >= self.max_requests:
                return False
            times.append(now)
            self.requests[user_id] = times
            return True

start_rate_limiter = RateLimiter(max_requests=10, time_window=60)
global_rate_limiter = RateLimiter(max_requests=50, time_window=60)

async def initialize_services():
    global db, validators
    validators = Validators()
    db = Database()
    return db, validators

class MinatiVaultBot:
    def __init__(self):
        self.db = None
        self.validators = None
        self.application = None
        self.running = False
        self._max_concurrent_operations = 50
        self._operation_semaphore = asyncio.Semaphore(self._max_concurrent_operations)
        self._performance_metrics = {
            'total_requests': 0,
            'failed_requests': 0,
            'avg_response_time': 0.0,
            'rate_limited_requests': 0
        }

    async def initialize_services_async(self):
        self.db, self.validators = await initialize_services()

    async def _check_start_rate_limit(self, user_id: int) -> bool:
        if not await start_rate_limiter.is_allowed(user_id):
            logger.warning(f"Rate limited /start from user {user_id}")
            return False
        return True

    async def _check_global_rate_limit(self, user_id: int) -> bool:
        if not await global_rate_limiter.is_allowed(user_id):
            logger.warning(f"Global rate limit exceeded for {user_id}")
            self._performance_metrics['rate_limited_requests'] += 1
            return False
        return True

    async def _update_perf(self, rt: float, success: bool):
        pm = self._performance_metrics
        pm['total_requests'] += 1
        if not success:
            pm['failed_requests'] += 1
        pm['avg_response_time'] = ((pm['avg_response_time'] * (pm['total_requests'] - 1)) + rt) / pm['total_requests']

    async def verify_social_follow(self, platform: str, username: str) -> bool:
        await asyncio.sleep(0.1)
        if platform == 'coinmarketcap':
            valid, _ = self.validators.validate_coinmarketcap_userid(username)
        else:
            valid, _ = self.validators.validate_username(username)
        return valid

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        start_time = time.time()
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name or "User"

        async with self._operation_semaphore:
            if not await self._check_start_rate_limit(user_id):
                return
            if not await self._check_global_rate_limit(user_id):
                await update.message.reply_text(
                    f"{EMOJIS['warning']} Too many requests. Try again later.",
                    parse_mode='Markdown'
                )
                return

            # referral extraction
            referral_code = None
            if context.args:
                arg = context.args[0]
                if self.validators.is_valid_referral_link_param(arg):
                    referral_code = self.validators.extract_referral_code_from_start_param(arg)

            existing_user = None
            for _ in range(3):
                existing_user = await self.db.get_user_with_retry(user_id)
                if existing_user is not None:
                    break
                await asyncio.sleep(1)

            if not existing_user:
                referred_by = None
                if referral_code:
                    ref = await self.db.get_user_by_referral_code(referral_code)
                    if ref and ref['user_id'] != user_id:
                        referred_by = referral_code
                    elif ref and ref['user_id'] == user_id:
                        await update.message.reply_text(f"{EMOJIS['cross']} You cannot use your own referral code!")
                        await self._update_perf(time.time() - start_time, False)
                        return
                    else:
                        await update.message.reply_text(f"{EMOJIS['cross']} Invalid referral code.")
                        await self._update_perf(time.time() - start_time, False)
                        return

                created = await self.db.create_user_with_retry(user_id, user.username or "NoUsername", first_name, referred_by)
                if created:
                    msg = WELCOME_MESSAGE_REFERRED if referred_by else WELCOME_MESSAGE
                    await update.message.reply_text(f"Welcome {first_name}! {EMOJIS['party']}\n\n{msg}")
                    await self.show_step(update, context, 1)
                    await self._update_perf(time.time() - start_time, True)
                else:
                    await update.message.reply_text(f"{EMOJIS['cross']} Technical issue. Try again later.")
                    await self._update_perf(time.time() - start_time, False)
            else:
                step = existing_user.get('current_step', 1)
                await update.message.reply_text(f"Welcome back {first_name}! You're on step {step}.")
                if step > TOTAL_STEPS:
                    await self.show_completion_with_referral(update, existing_user)
                else:
                    await self.show_step(update, context, step)
                await self._update_perf(time.time() - start_time, True)

    async def show_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE, step: int):
        if step > TOTAL_STEPS:
            user = await self.db.get_user_with_retry(update.effective_user.id)
            return await self.show_completion_with_referral(update, user)

        text = STEPS[step] if step != 6 else STEPS[6].format("Minativerseofficial")
        buttons = []
        if step == 1:
            buttons = [
                [InlineKeyboardButton("📥 Download App", url=SOCIAL_LINKS['app_download'])],
                [InlineKeyboardButton("✅ Downloaded", callback_data=CALLBACK_DATA['verify_step_1'])]
            ]
        elif step == 2:
            buttons = [
                [InlineKeyboardButton("🐦 Follow on Twitter", url=SOCIAL_LINKS['twitter'])],
                [InlineKeyboardButton("ℹ️ Send Username", callback_data=CALLBACK_DATA['twitter_info'])]
            ]
        elif step == 3:
            buttons = [
                [InlineKeyboardButton("📸 Follow on Instagram", url=SOCIAL_LINKS['instagram'])],
                [InlineKeyboardButton("ℹ️ Send Username", callback_data=CALLBACK_DATA['instagram_info'])]
            ]
        elif step == 4:
            buttons = [
                [InlineKeyboardButton("📊 Visit CMC", url=SOCIAL_LINKS['coinmarketcap'])],
                [InlineKeyboardButton("ℹ️ Send UserID", callback_data=CALLBACK_DATA['coinmarketcap_info'])]
            ]
        elif step == 5:
            buttons = [[InlineKeyboardButton("ℹ️ Send BEP20 Address", callback_data=CALLBACK_DATA['bep20_info'])]]
        elif step == 6:
            user = await self.db.get_user_with_retry(update.effective_user.id)
            missing = []
            su = user.get('social_usernames', {})
            if not su.get('twitter'): missing.append("Twitter")
            if not su.get('instagram'): missing.append("Instagram")
            if not su.get('coinmarketcap'): missing.append("CMC")
            if not user.get('bep20_address'): missing.append("BEP20")
            if not missing:
                buttons = [[InlineKeyboardButton("🎉 Complete", callback_data=CALLBACK_DATA['complete_process'])]]
            else:
                text += "\n\n⚠️ Missing: " + ", ".join(missing)
        buttons.append([InlineKeyboardButton("❓ Help", callback_data=CALLBACK_DATA['help'])])
        await update.message.reply_text(f"Step {step}/{TOTAL_STEPS}\n\n{text}",
                                        reply_markup=InlineKeyboardMarkup(buttons),
                                        parse_mode='Markdown')

    async def show_completion_with_referral(self, update: Update, user: dict):
        stats = user.get('referral_stats', {})
        text = (
            f"🎉 **Congratulations!** 🎉\n\n"
            f"Your Referral Link:\n"
            f"`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={user['referral_code']}`\n\n"
            f"Referrals: {stats.get('total_referrals',0)}\n"
            f"Rewards: {stats.get('total_referrals',0)*2} MNTC"
        )
        kb = [[InlineKeyboardButton("📊 Status", callback_data=CALLBACK_DATA['show_status'])]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = query.data

        async with self._operation_semaphore:
            if not await self._check_global_rate_limit(user_id):
                return await query.edit_message_text("Too many requests.")

            user = await self.db.get_user_with_retry(user_id)
            if not user:
                return await query.edit_message_text(MESSAGE_TEMPLATES['user_not_found'])

            step = user.get('current_step', 1)

            if data == CALLBACK_DATA['verify_step_1'] and step == 1:
                await self.db.update_user_step(user_id,1,True)
                await query.edit_message_text("✅ Download confirmed.")
                await self.show_step(update, context,2)

            elif data == CALLBACK_DATA['complete_process'] and step >= 6:
                await self.db.update_user_step(user_id,6,True)
                await self.send_completion_message(query, await self.db.get_user_with_retry(user_id))

            elif data in (CALLBACK_DATA['twitter_info'],
                          CALLBACK_DATA['instagram_info'],
                          CALLBACK_DATA['coinmarketcap_info'],
                          CALLBACK_DATA['bep20_info']):
                instr = {
                    CALLBACK_DATA['twitter_info']: HELP_TEMPLATES['instructions']['twitter'],
                    CALLBACK_DATA['instagram_info']: HELP_TEMPLATES['instructions']['instagram'],
                    CALLBACK_DATA['coinmarketcap_info']: HELP_TEMPLATES['instructions']['coinmarketcap'],
                    CALLBACK_DATA['bep20_info']: HELP_TEMPLATES['instructions']['bep20']
                }
                await query.edit_message_text(instr[data])

            elif data == CALLBACK_DATA['show_status']:
                await self.show_status_callback(query, user)

            elif data == CALLBACK_DATA['show_referral']:
                await self.show_referral_stats_callback(query, user)

            elif data == CALLBACK_DATA['help']:
                kb = [
                    [InlineKeyboardButton("📞 Support", url=SOCIAL_LINKS['support'])],
                    [InlineKeyboardButton("🌐 Website", url=SOCIAL_LINKS['website'])]
                ]
                await query.edit_message_text(HELP_TEMPLATES['help_button'],
                                              reply_markup=InlineKeyboardMarkup(kb),
                                              parse_mode='Markdown')

    async def send_completion_message(self, query, user: dict):
        su = user.get('social_usernames',{})
        m = user.get('bep20_address','')
        ri = user.get('reward_info',{})
        earned = ri.get('mntc_earned',0) or (4 if user.get('is_referred') else 4)
        text = (
            "🎉 **CONGRATULATIONS!** 🎉\n\n"
            f"🐦 Twitter: @{su.get('twitter','N/A')}\n"
            f"📸 Instagram: @{su.get('instagram','N/A')}\n"
            f"📊 CMC: @{su.get('coinmarketcap','N/A')}\n"
            f"🏦 BEP20: {m[:10]}...{m[-6:] if m else 'N/A'}\n\n"
            f"💰 Reward: {earned} MNTC\n\n"
            f"🎁 Referral:" 
            f"`https://t.me/{REFERRAL_CONFIG['bot_username']}?start={user['referral_code']}`\n\n"
            "Share to earn +2 MNTC each!"
        )
        await query.edit_message_text(text, parse_mode='Markdown')

    async def show_status_callback(self, query, user: dict):
        sc = user.get('steps_completed',{})
        su = user.get('social_usernames',{})
        ba = user.get('bep20_address','N/A')
        rs = user.get('referral_stats',{})
        ri = user.get('reward_info',{})
        isref = user.get('is_referred',False)
        text = STATUS_TEMPLATE.format(
            user.get('current_step',1), TOTAL_STEPS,
            len(sc), TOTAL_STEPS,
            STATUS_ICONS['completed'] if sc.get('step_1') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if sc.get('step_2') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if sc.get('step_3') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if sc.get('step_4') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if sc.get('step_5') else STATUS_ICONS['not_completed'],
            STATUS_ICONS['completed'] if sc.get('step_6') else STATUS_ICONS['not_completed'],
            su.get('twitter','N/A'),
            su.get('instagram','N/A'),
            su.get('coinmarketcap','N/A'),
            STATUS_ICONS['provided'] if ba!='N/A' else STATUS_ICONS['not_provided'],
            STATUS_ICONS['referred'] if isref else STATUS_ICONS['normal'],
            rs.get('total_referrals',0),
            rs.get('total_rewards',0),
            ri.get('mntc_earned',0),
            STATUS_ICONS.get(ri.get('reward_status','pending'),'⏳ Pending'),
            MESSAGE_TEMPLATES['all_completed'] if user.get('current_step')>TOTAL_STEPS else f"Continue with Step {user.get('current_step',1)}"
        )
        await query.edit_message_text(text, parse_mode='Markdown')

    async def show_referral_stats_callback(self, query, user: dict):
        rs = user.get('referral_stats',{})
        text = REFERRAL_STATS_TEMPLATE.format(
            total_referrals=rs.get('total_referrals',0),
            total_rewards=rs.get('total_rewards',0),
            bot_username=REFERRAL_CONFIG['bot_username'],
            referral_code=user.get('referral_code','X'),
            website=SOCIAL_LINKS['website']
        )
        kb = [[InlineKeyboardButton("📊 Status", callback_data=CALLBACK_DATA['show_status'])]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        start_time = time.time()
        uid = update.effective_user.id
        msg = update.message.text.strip()

        async with self._operation_semaphore:
            if not await self._check_global_rate_limit(uid):
                return await update.message.reply_text("Too many requests.")
            user = await self.db.get_user_with_retry(uid)
            if not user:
                return await update.message.reply_text("❌ Please /start first.")

            step = user.get('current_step',1)
            if step==2:
                un = msg.lstrip('@')
                valid, err = self.validators.validate_username(un)
                if valid:
                    if await self.verify_social_follow('twitter',un):
                        await self.db.save_social_username(uid,'twitter',un)
                        await self.db.update_user_step(uid,2,True)
                        await update.message.reply_text(f"✅ Twitter @{un} verified.")
                        await self.show_step(update,context,3)
                    else:
                        await update.message.reply_text("⚠️ Not verified. Try again.")
                else:
                    await update.message.reply_text(f"❌ {err}")
                return

            if step==3:
                un = msg.lstrip('@')
                valid, err = self.validators.validate_username(un)
                if valid:
                    if await self.verify_social_follow('instagram',un):
                        await self.db.save_social_username(uid,'instagram',un)
                        await self.db.update_user_step(uid,3,True)
                        await update.message.reply_text(f"✅ Instagram @{un} verified.")
                        await self.show_step(update,context,4)
                    else:
                        await update.message.reply_text("⚠️ Not verified.")
                else:
                    await update.message.reply_text(f"❌ {err}")
                return

            if step==4:
                cmc = msg
                valid, err = self.validators.validate_coinmarketcap_userid(cmc)
                if valid:
                    if await self.verify_social_follow('coinmarketcap',cmc):
                        await self.db.save_social_username(uid,'coinmarketcap',cmc)
                        await self.db.update_user_step(uid,4,True)
                        await update.message.reply_text(f"✅ CMC {cmc} verified.")
                        await self.show_step(update,context,5)
                    else:
                        await update.message.reply_text("⚠️ Not verified.")
                else:
                    await update.message.reply_text(f"❌ {err}")
                return

            if step==5:
                valid, err = self.validators.validate_bep20_address(msg)
                if valid:
                    await self.db.save_bep20_address(uid,msg)
                    await self.db.update_user_step(uid,5,True)
                    await update.message.reply_text(f"✅ Address {msg} saved.")
                    await self.show_step(update,context,6)
                else:
                    await update.message.reply_text(f"❌ {err}")
                return

            await update.message.reply_text("Use the buttons or /help for assistance.")

    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid=update.effective_user.id
        user=await self.db.get_user_with_retry(uid)
        if not user:
            return await update.message.reply_text("❌ Not found.")
        rs=user.get('referral_stats',{})
        text=REFERRAL_STATS_TEMPLATE.format(
            total_referrals=rs.get('total_referrals',0),
            total_rewards=rs.get('total_rewards',0),
            bot_username=REFERRAL_CONFIG['bot_username'],
            referral_code=user['referral_code'],
            website=SOCIAL_LINKS['website']
        )
        kb=[[InlineKeyboardButton("📊 Status",callback_data=CALLBACK_DATA['show_status'])]]
        await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup(kb),parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats=await self.db.get_user_stats()
        tu=stats.get('total_users',0)
        cu=stats.get('completed_users',0)
        rate=(cu/tu*100) if tu>0 else 0
        text=STATS_TEMPLATE.format(tu,cu,rate,datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        await update.message.reply_text(text,parse_mode='Markdown')

    async def performance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid=update.effective_user.id
        ADMINS=[123456789]
        if uid not in ADMINS:
            return await update.message.reply_text("❌ Unauthorized")
        pm=self._performance_metrics
        text=(
            f"📊 Total reqs: {pm['total_requests']}\n"
            f"❌ Failed: {pm['failed_requests']}\n"
            f"⏱ Avg RT: {pm['avg_response_time']:.3f}s\n"
            f"🚫 Rate limited: {pm['rate_limited_requests']}"
        )
        await update.message.reply_text(text)

    async def health_check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid=update.effective_user.id
        ADMINS=[123456789]
        if uid not in ADMINS:
            return await update.message.reply_text("❌ Unauthorized")
        h=await self.db.health_check()
        emoji="✅" if h['status']=='healthy' else "❌"
        cb="🔴" if h['circuit_breaker_open'] else "🟢"
        text=(
            f"{emoji} Status: {h['status']}\n"
            f"Circuit: {cb}\n"
            f"Failures: {h['connection_failures']}\n"
        )
        await update.message.reply_text(text)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} error {context.error}")

    def setup_handlers(self):
        app=self.application
        app.add_handler(CommandHandler("start",self.start))
        app.add_handler(CommandHandler("help",lambda u,c: u.message.reply_text(HELP_TEMPLATES['help_button'],parse_mode='Markdown')))
        app.add_handler(CommandHandler("status",self.show_status_callback))
        app.add_handler(CommandHandler("stats",self.stats_command))
        app.add_handler(CommandHandler("referral",self.referral_command))
        app.add_handler(CommandHandler("health",self.health_check_command))
        app.add_handler(CommandHandler("performance",self.performance_command))
        app.add_handler(CallbackQueryHandler(self.button_handler))
        app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,self.handle_message))
        app.add_error_handler(self.error_handler)

    async def cleanup_telegram_bot(self):
        try:
            temp=Application.builder().token(config.BOT_TOKEN).build()
            await temp.initialize()
            try:
                await temp.bot.delete_webhook(drop_pending_updates=True)
            except:
                pass
            await temp.shutdown()
        except:
            pass

    async def start_bot(self):
        await self.initialize_services_async()
        # Reset circuit breaker
        if self.db._circuit_breaker_open:
            self.db._circuit_breaker_open=False
            self.db._connection_failures=0
            self.db._last_failure_time=None
            logger.info("Circuit breaker reset after init")
        # Ensure stats
        await self.db._init_bot_stats_async()
        await self.cleanup_telegram_bot()
        self.application=(
            Application.builder()
            .token(config.BOT_TOKEN)
            .concurrent_updates(100)
            .build()
        )
        self.setup_handlers()
        self.running=True
        # init/start
        for i in range(3):
            try:
                await self.application.initialize()
                await self.application.start()
                break
            except Conflict:
                await asyncio.sleep(5)
                await self.cleanup_telegram_bot()
        await self.application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        # background tasks
        asyncio.create_task(self.performance_monitor())
        while self.running:
            await asyncio.sleep(1)

    async def performance_monitor(self):
        while self.running:
            await asyncio.sleep(300)
            pm=self._performance_metrics
            success=pm['total_requests']-pm['failed_requests']
            rate=(success/pm['total_requests']*100) if pm['total_requests']>0 else 0
            logger.info(f"Perf: reqs={pm['total_requests']} success_rate={rate:.1f}% avg_rt={pm['avg_response_time']:.3f}s rate_limited={pm['rate_limited_requests']}")

    async def stop_bot(self):
        self.running=False
        try:
            if self.application.updater.running:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        except:
            pass

async def main():
    if not config.BOT_TOKEN or not config.FIREBASE_PROJECT_ID:
        print("Missing BOT_TOKEN or FIREBASE_PROJECT_ID")
        sys.exit(1)
    bot=MinatiVaultBot()
    def sig(sig,frm):
        bot.running=False
    signal.signal(signal.SIGINT,sig)
    signal.signal(signal.SIGTERM,sig)
    await bot.start_bot()

if __name__=='__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
