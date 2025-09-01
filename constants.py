"""
Constants file for Minati Vault Bot with Referral System
Contains all constant values used throughout the application
"""

import string
import random

# Bot Configuration Constants
DEFAULT_FIREBASE_PROJECT_ID = 'kriptospire'
DEFAULT_FIREBASE_SERVICE_ACCOUNT_PATH = './firebase-service-account.json'
DEFAULT_CUSTOMER_CARE_USERNAME = 'Minativerseofficial'

# Social Media Links
SOCIAL_LINKS = {
    'twitter': 'https://x.com/minatifi?t=wD6ywZfQ1fRdAvHW7x2Txw&s=08',
    'instagram': 'https://www.instagram.com/minativerse_edtech?igsh=MXE4cWx5ZjZydzUxZg==',
    'telegram': 'https://t.me/Minativerseofficial',
    'coinmarketcap': 'https://coinmarketcap.com/currencies/minati-coin/',
    'app_download': 'https://play.google.com/store/apps/details?id=com.app.minati_wallet',
    'website': 'https://minati.io',
    'support': 'https://t.me/Minatirewards',
}

# Referral System Constants
REFERRAL_CONFIG = {
    'bot_username': 'minatiVault_bot', # Update this with your actual bot username
    'referral_code_length': 8,
    'referral_code_prefix': 'REF',
    'normal_reward': 4, # MNTC for normal users
    'referred_reward': 4, # MNTC for referred users
    'referrer_bonus': 2, # MNTC bonus for referrers (you'll update manually) - UPDATED FROM 1 TO 2
}

def generate_referral_code():
    """Generate a unique referral code"""
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choice(chars) for _ in range(REFERRAL_CONFIG['referral_code_length']))
    return f"{REFERRAL_CONFIG['referral_code_prefix']}{code}"

# Referral Message Templates
REFERRAL_MESSAGES = {
    'referral_link_generated': """
🎉 **Congratulations!** 🎉

You have successfully completed all verification steps!

**🎁 Your Referral Link:**
`https://t.me/{bot_username}?start={referral_code}`

**💰 Referral Rewards:**
• You get **+2 MNTC** for each successful referral

**📊 Your Referral Stats:**
• Total Successful Referrals: **{total_referrals}**
• Total Referral Rewards: **{total_rewards} MNTC**

Share your referral link with friends to earn more rewards! 🚀

📞 **Support:** @Minatirewards
🌐 **Website:** {website}
""",

    'referral_success_notification': """
🎉 **New Referral Success!** 🎉

Someone you referred has completed all verification steps!

**📊 Your Updated Referral Stats:**
• Total Successful Referrals: **{total_referrals}**
• Total Referral Rewards: **{total_rewards} MNTC**

Keep sharing your referral link to earn more rewards! 💰

**🎁 Your Referral Link:**
`https://t.me/{bot_username}?start={referral_code}`
""",

    'referred_completion': """
🎉 **CONGRATULATIONS!** 🎉

You have successfully completed all steps!

**Your Submitted Information:**
🐦 Twitter: @{twitter}
📸 Instagram: @{instagram}
📊 CoinMarketCap: @{coinmarketcap}
🏦 BEP20 Address: `{bep20_short}`

**💰 Your Reward:** {mntc_earned} MNTC
*(You received {mntc_earned} MNTC as you were referred by another user)*

**What's Next?**
Our team will review your submission and contact you soon!

**🎁 Start Earning More! Get Your Referral Link:**
Use /start command to get your own referral link and start earning bonuses!

📞 **Support:** @Minatirewards
🌐 **Website:** {website}

Thank you for using Minati Vault Bot! 🚀
""",

    'normal_completion': """
🎉 **CONGRATULATIONS!** 🎉

You have successfully completed all steps!

**Your Submitted Information:**
🐦 Twitter: @{twitter}
📸 Instagram: @{instagram}
📊 CoinMarketCap: @{coinmarketcap}
🏦 BEP20 Address: `{bep20_short}`

**💰 Your Reward:** {mntc_earned} MNTC

**What's Next?**
Our team will review your submission and contact you soon!

**🎁 Your Referral Link:**
`https://t.me/{bot_username}?start={referral_code}`

**💰 Referral Rewards:**
• You get **+2 MNTC** for each successful referral

Share your referral link with friends to earn more rewards! 🚀

📞 **Support:** @Minatirewards
🌐 **Website:** {website}

Thank you for using Minati Vault Bot! 🚀
"""
}

# Bot Messages and Steps - UPDATED with formatted Twitter step
WELCOME_MESSAGE = """
🚀 Welcome to Minati Vault Bot!

To complete the process, follow these steps:

1️⃣ Download vault and review
2️⃣ Follow us on Twitter (X)
3️⃣ Follow us on Instagram
4️⃣ Follow us on CoinMarketCap
5️⃣ Send your Minati Vault BEP20 address
6️⃣ Submit final verification

Let's start! 🎯
"""

WELCOME_MESSAGE_REFERRED = """
🚀 Welcome to Minati Vault Bot!

Someone shared this amazing opportunity with you! 🎁

To complete the process, follow these steps:

1️⃣ Download vault and review
2️⃣ Follow us on Twitter (X)
3️⃣ Follow us on Instagram
4️⃣ Follow us on CoinMarketCap
5️⃣ Send your Minati Vault BEP20 address
6️⃣ Submit final verification

Let's start! 🎯
"""

# UPDATED STEPS with properly formatted Twitter step
STEPS = {
    1: "📥 Please download and review the Minati Vault app first.\n\n🔗 **Download Link:** [Minati Vault App](https://play.google.com/store/apps/details?id=com.app.minati_wallet)\n\nAfter downloading and reviewing, click the button below.",
    2: "🐦 **Twitter Tasks:**\n\n1. Follow us: [@minatifi](https://x.com/minatifi?t=wD6ywZfQ1fRdAvHW7x2Txw&s=08)\n2. Like our latest post\n3. Retweet with comment\n\n📝 **Send your Twitter username** (without @) after completing all tasks.",
    3: "📸 **Instagram Tasks:**\n\n1. Follow us: [@minativerse_edtech](https://www.instagram.com/minativerse_edtech?igsh=MXE4cWx5ZjZydzUxZg==)\n2. Like our latest post\n3. Share to your story (optional)\n\n📝 **Send your Instagram username** (without @) after completing all tasks.",
    4: "📊 **CoinMarketCap Tasks:**\n\n1. Visit our page: [CoinMarketCap](https://coinmarketcap.com/currencies/minati-coin/)\n2. Follow our project\n3. Add to your watchlist\n\n📝 **Send your CoinMarketCap User ID** after completing all tasks.",
    5: "🏦 **BEP20 Address Submission:**\n\nPlease send your Minati Vault BEP20 address for rewards.\n\n⚠️ **Important:** Make sure it's a valid BEP20 address starting with 0x",
    6: "🎉 **Final Verification:**\n\nReview your information and confirm all tasks are completed.\n\n📞 **Support:** [Contact Support](https://t.me/Minatirewards)"
}

# Step Configuration
TOTAL_STEPS = 6
MIN_STEP = 1
MAX_STEP = 6

# Database Collections
DB_COLLECTIONS = {
    'users': 'users',
    'bot_stats': 'bot_stats',
    'main_stats': 'main'
}

# User Data Structure Constants
DEFAULT_USER_DATA = {
    "current_step": 1,
    "steps_completed": {},
    "bep20_address": None,
    "social_usernames": {
        "twitter": None,
        "instagram": None,
        "coinmarketcap": None
    },
    "screenshots": [],
    "verification_status": {
        "twitter": False,
        "instagram": False,
        "coinmarketcap": False
    },
    # Referral System Fields
    "referral_code": None, # User's unique referral code
    "referred_by": None, # Who referred this user (referral_code of referrer)
    "referral_stats": {
        "total_referrals": 0, # Number of successful referrals
        "total_rewards": 0 # Total MNTC earned through referrals (manual update)
    },
    "is_referred": False, # Whether this user was referred by someone
    # NEW: Reward tracking for admin
    "reward_info": {
        "mntc_earned": 0, # MNTC earned after completion
        "reward_type": None, # "normal" or "referred"
        "completion_date": None, # When user completed all steps
        "reward_status": "not_completed" # "not_completed", "pending", "paid"
    }
}

# DEFAULT BOT STATS
DEFAULT_BOT_STATS = {
    "total_users": 0,
    "completed_users": 0,
    "completion_rate": 0
}

# Validation Constants
VALIDATION_LIMITS = {
    'username_min_length': 2,
    'username_max_length': 30,
    'message_max_length': 4096,
    'filename_max_length': 100,
    'file_max_size': 10 * 1024 * 1024, # 10MB
    'file_min_size': 1024, # 1KB
    'bep20_address_length': 42,
    'coinmarketcap_userid_min_length': 3,
    'coinmarketcap_userid_max_length': 50,
    'referral_code_min_length': 5,
    'referral_code_max_length': 15,
}

# Common Invalid BEP20 Addresses
INVALID_BEP20_ADDRESSES = {
    '0x0000000000000000000000000000000000000000', # Zero address
    '0x000000000000000000000000000000000000dead', # Dead address
    '0xdead000000000000000000000000000000000000', # Dead address variant
    '0x0000000000000000000000000000000000000001', # Common test address
}

# Reserved/Invalid Usernames
INVALID_USERNAMES = {
    'admin', 'administrator', 'root', 'support', 'help', 'bot', 'api',
    'www', 'ftp', 'mail', 'email', 'test', 'demo', 'null', 'undefined',
    'telegram', 'instagram', 'twitter', 'facebook', 'youtube', 'tiktok',
    'coinmarketcap', 'cmc'
}

# File Format Constants
VALID_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff']
VALID_MIME_TYPES = [
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
    'image/bmp', 'image/webp', 'image/tiff'
]

# Regex Patterns
REGEX_PATTERNS = {
    'bep20_address': r'^[a-fA-F0-9]{40}$',
    'username': r'^[a-zA-Z0-9._]+$',
    'coinmarketcap_userid': r'^[a-zA-Z0-9._-]+$',
    'hexadecimal': r'^[a-fA-F0-9]+$',
    'url': r'https?://[^\s]+',
    'mention': r'@\w+',
    'hashtag': r'#\w+',
    'html_tags': r'<[^>]*>',
    'referral_code': r'^REF[A-Z0-9]{8}$',
    'spam_patterns': [
        r'^\d+[a-z]+\d+$', # Number-letter-number pattern
        r'^[a-z]+\d{4,}$', # Letters followed by many numbers
        r'^\w+_bot$', # Ends with _bot
        r'^\w+official$', # Ends with official
    ],
}

# Invalid Patterns for Usernames
USERNAME_INVALID_PATTERNS = ['__', '..', '._', '_.']
TWITTER_INVALID_PATTERNS = ['twitter', 'twtr']
INSTAGRAM_INVALID_PATTERNS = ['instagram', 'insta']
COINMARKETCAP_INVALID_PATTERNS = ['coinmarketcap', 'cmc', 'marketcap']

# Dangerous Characters for File Names
DANGEROUS_FILE_CHARS = ['..', '/', '\\', '<', '>', ':', '"', '|', '?', '*']

# SQL Injection Prevention
DANGEROUS_SQL_WORDS = ['DROP', 'DELETE', 'INSERT', 'UPDATE', 'SELECT', '--', ';']

# Logging Configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
        'detailed': {
            'format': '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'INFO',
            'propagate': False
        }
    }
}

# Firebase Environment Variable Mapping
FIREBASE_ENV_MAPPING = {
    'type': 'FIREBASE_TYPE',
    'project_id': 'FIREBASE_PROJECT_ID',
    'private_key_id': 'FIREBASE_PRIVATE_KEY_ID',
    'private_key': 'FIREBASE_PRIVATE_KEY',
    'client_email': 'FIREBASE_CLIENT_EMAIL',
    'client_id': 'FIREBASE_CLIENT_ID',
    'auth_uri': 'FIREBASE_AUTH_URI',
    'token_uri': 'FIREBASE_TOKEN_URI',
    'auth_provider_x509_cert_url': 'FIREBASE_AUTH_PROVIDER_X509_CERT_URL',
    'client_x509_cert_url': 'FIREBASE_CLIENT_X509_CERT_URL',
    'universe_domain': 'FIREBASE_UNIVERSE_DOMAIN'
}

# Firebase Default Values
FIREBASE_DEFAULTS = {
    'type': 'service_account',
    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
    'token_uri': 'https://oauth2.googleapis.com/token',
    'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
    'universe_domain': 'googleapis.com'
}

# Required Firebase Environment Variables
FIREBASE_REQUIRED_VARS = ['type', 'project_id', 'private_key', 'client_email']

# User ID Validation Limits
USER_ID_LIMITS = {
    'min_value': 1000,
    'max_value': 2**63 - 1
}

# Rate Limiting and Performance
RATE_LIMITS = {
    'max_users_query': 100,
    'verification_timeout': 30, # seconds
    'spam_threshold': 0.3 # 30% spam elements in message
}

# Button Callback Data
CALLBACK_DATA = {
    'verify_step_1': 'verify_step_1',
    'verify_coinmarketcap': 'verify_coinmarketcap',
    'complete_process': 'complete_process',
    'twitter_info': 'twitter_info',
    'instagram_info': 'instagram_info',
    'coinmarketcap_info': 'coinmarketcap_info',
    'bep20_info': 'bep20_info',
    'restart_process': 'restart_process',
    'show_status': 'show_status',
    'help': 'help',
    'show_referral': 'show_referral'
}

# Message Templates
MESSAGE_TEMPLATES = {
    'user_not_found': "❌ User not found. Please use /start command.",
    'step_mismatch': "❌ You're not on step {}.",
    'error_saving': "❌ Error saving {}. Please try again.",
    'invalid_address': "❌ *Invalid BEP20 Address*\n\nError: {}\n\nPlease send a valid BEP20 address:",
    'invalid_username': "❌ *Invalid {} Username/ID*\n\nError: {}\n\nPlease send a valid {} username/ID.",
    'invalid_coinmarketcap_id': "❌ *Invalid CoinMarketCap User ID*\n\nError: {}\n\nPlease send a valid CoinMarketCap User ID:",
    'process_restarted': "🔄 Process restarted! Let's begin again.",
    'process_restarted_referral': "🔄 Process restarted with referral applied! Let's begin again. 🎁",
    'all_completed': "🎉 All steps completed!",
    'need_help': "Need help? Contact support or Follow @Minativerseofficial",
    'invalid_referral_code': "❌ Invalid referral code. Please check and try again.",
    'referral_self_use': "❌ You cannot use your own referral code!",
    'referral_not_found': "❌ Referral code not found. Please check and try again."
}

# Help Text Templates - UPDATED with consistent referral bonus
HELP_TEMPLATES = {
    'main_help': """
🆘 *Minati Vault Bot Help*

*Available Commands:*
• /start - Start or restart the bot
• /status - Check your current progress
• /help - Show this help message
• /stats - Bot statistics

*Verification Process:*
✅ Username collection for Twitter, Instagram & CoinMarketCap
🔐 Address validation for BEP20 wallet

*Referral System:*
💰 Earn +2 MNTC for each successful referral
🎁 Share your referral link after completing all steps

*Need Personal Assistance?*
👨‍💼 Support: @Minatirewards
📱 Follow: @Minativerseofficial

*Important Notes:*
• Social media usernames/IDs are collected for manual verification
• BEP20 addresses are validated for correct format
• Referral rewards are added manually by admin

*Quick Access Links:*
Use the buttons below for instant access to our platforms
""",

    'instructions': {
        'twitter': """
📝 *Twitter Instructions:*

1. Click 'Follow on Twitter' button above
2. Follow our Twitter account
3. Like and retweet our pinned post
4. Send your Twitter username here (without @)

Example: If your Twitter is @john_crypto, just send: john_crypto
""",

        'instagram': """
📝 *Instagram Instructions:*

1. Click 'Follow on Instagram' button above
2. Follow our Instagram account
3. Like our latest post
4. Send your Instagram username here (without @)

Example: If your Instagram is @john.crypto, just send: john.crypto
""",

        'coinmarketcap': """
📝 *CoinMarketCap Instructions:*

1. Click 'Visit CoinMarketCap' button above
2. Follow our project on CoinMarketCap
3. Add to your watchlist
4. Send your CoinMarketCap User ID here

Example: If your CoinMarketCap User ID is john_crypto_2024, just send: john_crypto_2024
""",

        'bep20': """
🏦 *BEP20 Address Instructions:*

Please send your BEP20 (Binance Smart Chain) wallet address.

*Requirements:*
• Must start with 0x
• Must be exactly 42 characters long
• Only contains letters (a-f) and numbers (0-9)

*Example:* 0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52
"""
    },

    'help_button': """
🆘 *Need Help?*

*Commands:*
• /start - Start or restart
• /status - Check progress
• /help - Show help
• /stats - Bot statistics

*Support:* @Minatirewards
*Follow:* @Minativerseofficial

*Quick Links:*
Use the buttons below to access our platforms
"""
}

# Status Message Template
STATUS_TEMPLATE = """
📊 *Your Progress Status*

*Current Step:* {}/6
*Completed Steps:* {}/6

*Step Details:*
{} Step 1: App Download & Review
{} Step 2: Twitter Follow
{} Step 3: Instagram Follow
{} Step 4: CoinMarketCap Follow
{} Step 5: BEP20 Address
{} Step 6: Final Verification

*Verification Status:*
🐦 Twitter: @{}
📸 Instagram: @{}
📊 CoinMarketCap: {}
🏦 BEP20: {}

*Referral Info:*
🎁 Referral Status: {}
📊 Total Referrals: {}
💰 Referral Rewards: {} MNTC

*Reward Info:*
💎 MNTC Earned: {} MNTC
📅 Status: {}

*Next Action:* {}
"""

# Statistics Template
STATS_TEMPLATE = """
📊 *Bot Statistics*

👥 *Total Users:* {:,}
✅ *Completed Users:* {:,}
📈 *Completion Rate:* {:.1f}%

🚀 *Minati Vault Bot*

Last updated: {}
"""

# Referral Statistics Template - UPDATED with +2 MNTC
REFERRAL_STATS_TEMPLATE = """
🎁 *Your Referral Statistics*

**📊 Referral Performance:**
• Total Successful Referrals: **{int(total_referrals/2)}**
• Total Referral Rewards: **{total_referrals} MNTC**
• Total Recieved Referral Rewards: **{total_rewards} MNTC**

**🔗 Your Referral Link:**
`https://t.me/{bot_username}?start={referral_code}`

**💰 How It Works:**
• Share your link with friends
• You earn **+2 MNTC** for each referral 

**📈 Keep sharing to earn more rewards!**

*Support:* @Minatirewards
*Website:* {website}
"""

# Admin Templates (NEW)
ADMIN_TEMPLATES = {
    'pending_rewards_summary': """
💼 *Admin: Pending Rewards Summary*

**📊 Total Statistics:**
• Total Completed Users: **{total_completed}**
• Normal Users (4 MNTC): **{normal_users}**
• Referred Users (4 MNTC): **{referred_users}**

**💰 MNTC Distribution:**
• Total MNTC Pending: **{total_pending} MNTC**
• Total MNTC Paid: **{total_paid} MNTC**
• Total MNTC Issued: **{total_issued} MNTC**

Use admin commands to manage payments.
""",

    'user_reward_details': """
👤 *User Reward Details*

**User Info:**
• ID: {user_id}
• Name: {first_name} (@{username})
• BEP20: `{bep20_address}`

**Reward Info:**
• MNTC Earned: **{mntc_earned} MNTC**
• Reward Type: {reward_type}
• Completion Date: {completion_date}
• Status: **{reward_status}**

**Social Verification:**
• Twitter: @{twitter}
• Instagram: @{instagram}
• CoinMarketCap: @{coinmarketcap}
"""
}

# Validation Summary for Documentation
VALIDATION_SUMMARY = {
    "bep20_address": {
        "format": "Must start with 0x, exactly 42 characters, hexadecimal only",
        "restrictions": "Cannot be zero address, dead address, or common test addresses",
        "example": "0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52"
    },
    "username": {
        "format": "2-30 characters, letters/numbers/dots/underscores only",
        "restrictions": "Must start/end with alphanumeric, no consecutive special chars",
        "example": "john_crypto123"
    },
    "coinmarketcap_userid": {
        "format": "3-50 characters, letters/numbers/dots/underscores/hyphens only",
        "restrictions": "Must start/end with alphanumeric, no consecutive special chars",
        "example": "john_crypto_2024"
    },
    "referral_code": {
        "format": "REF followed by 8 alphanumeric characters",
        "restrictions": "Must be unique, case-sensitive",
        "example": "REFABC12345"
    },
    "screenshot": {
        "size": "1KB - 10MB",
        "formats": "JPG, PNG, GIF, BMP, WEBP, TIFF",
        "restrictions": "No dangerous characters in filename"
    },
    "message": {
        "length": "Maximum 4096 characters",
        "restrictions": "Limited promotional content allowed",
        "sanitization": "HTML tags and SQL injection attempts removed"
    }
}

# Emoji Constants
EMOJIS = {
    'checkmark': '✅',
    'cross': '❌',
    'warning': '⚠️',
    'info': 'ℹ️',
    'fire': '🔥',
    'rocket': '🚀',
    'party': '🎉',
    'question': '❓',
    'refresh': '🔄',
    'stats': '📊',
    'phone': '📞',
    'globe': '🌐',
    'twitter': '🐦',
    'instagram': '📸',
    'telegram': '💬',
    'coinmarketcap': '📊',
    'wallet': '🏦',
    'download': '📥',
    'mobile': '📱',
    'target': '🎯',
    'stop': '🛑',
    'gift': '🎁',
    'money': '💰',
    'link': '🔗',
    'gem': '💎',
    'calendar': '📅',
    'briefcase': '💼'
}

# Status Icons
STATUS_ICONS = {
    'completed': '✅',
    'not_completed': '❌',
    'provided': '✅ Provided',
    'not_provided': '❌ Not provided',
    'referred': '🎁 Referred User',
    'normal': '👤 Normal User',
    'pending': '⏳ Pending Payment',
    'paid': '✅ Paid',
    'not_completed_reward': '❌ Not Completed'
}


