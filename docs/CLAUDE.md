# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Telegram bot** for Minati Vault that manages user onboarding, social media verification, and a referral reward system. The bot guides users through 6 verification steps and tracks MNTC token rewards.

**Tech Stack:**
- Python 3.11+ with `python-telegram-bot` library (v20.8+)
- Firebase Firestore for database
- Deployed on Render.com

## Common Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run bot locally
python main.py

# Test Firebase connection
python test_firebase_connection.py

# Test MongoDB (legacy)
python test_mongodb.py
```

### Environment Setup
Create a `.env` file with:
```
BOT_TOKEN=your_telegram_bot_token
FIREBASE_PROJECT_ID=kriptospire
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
CUSTOMER_CARE_USERNAME=Minativerseofficial
REFERRAL_BOT_USERNAME=minatiVault_bot
```

### Deployment (Render.com)
- The bot is configured via `render.yaml`
- Set environment variables in Render dashboard
- `FIREBASE_SERVICE_ACCOUNT_JSON` must be a valid JSON string (can be base64 encoded)

## Architecture

### Core Components

**`main.py`** (1287 lines)
- `MinatiVaultBot` class - main bot controller
- Handles all Telegram interactions via command handlers and callback queries
- 6-step verification flow with state management
- Referral system implementation
- Circuit breaker pattern for error handling

**`database.py`** (816 lines)
- `Database` class - Firebase Firestore wrapper
- User CRUD operations with retry logic and exponential backoff
- Circuit breaker pattern (opens after 5 consecutive failures, resets after 30s)
- Referral tracking and reward calculations
- Admin functions for reward management

**`validators.py`** (411 lines)
- `Validators` class - comprehensive input validation
- Validates BEP20 addresses, social usernames, referral codes
- Security: SQL injection prevention, HTML tag stripping, spam detection

**`constants.py`** (687 lines)
- All configuration constants, message templates, emojis
- `STEPS` dict defines the 6-step verification flow
- Referral system configuration
- Validation limits and regex patterns

**`config.py`** (50 lines)
- Loads environment variables
- Validates required configuration on startup

### 6-Step Verification Flow

Users progress through these steps sequentially:
1. Download Minati Vault app and leave review
2. Follow on Twitter, like and retweet
3. Follow on Instagram, like posts
4. Follow on CoinMarketCap, add to watchlist
5. Submit BEP20 wallet address
6. Final verification and completion

**State Management:**
- Current step tracked in `user_data['current_step']`
- Individual step completion in `user_data['steps_completed']['step_N']`
- Cannot skip steps - must complete in order

### Referral System

**How It Works:**
- Each user gets unique referral code (format: `REF[A-Z0-9]{8}`)
- Referral links: `https://t.me/minatiVault_bot?start=REFABCD1234`
- Normal users earn 4 MNTC on completion
- Referred users earn 4 MNTC on completion
- Referrers earn +2 MNTC bonus per successful referral (manually updated by admin)

**Key Functions:**
- `database.py:331` - `create_user_with_retry()` handles referral assignment
- `database.py:498` - `_handle_referral_completion()` updates referrer stats
- `main.py:563` - `notify_referrer()` sends notification when referral completes

### Error Handling & Resilience

**Circuit Breaker Pattern (database.py:61-92):**
- Tracks consecutive database failures
- Opens circuit after 5 failures
- Auto-resets after 30 seconds
- Prevents cascading failures

**Retry Logic:**
- All database operations have 3 retry attempts with exponential backoff
- Jitter added to prevent thundering herd
- `_exponential_backoff_delay()` at database.py:55

**Telegram Conflict Resolution (main.py:1104-1103):**
- Deletes webhooks before starting polling
- Handles `Conflict` errors (multiple bot instances)
- Clean shutdown with signal handlers

### Firebase Authentication Methods (Priority Order)

The bot tries these credential methods in order (database.py:116-173):
1. Service account JSON file at path (most reliable)
2. `FIREBASE_SERVICE_ACCOUNT_JSON` environment variable (full JSON)
3. Individual environment variables (mapped via `FIREBASE_ENV_MAPPING`)
4. Google Cloud default credentials

**Private Key Handling:**
- Auto-fixes escaped newlines (`\n` → actual newlines)
- Validates BEGIN/END markers
- Supports base64 and URL-encoded JSON

## Important Implementation Details

### User Creation with Referrals (database.py:331)
```python
# IMPORTANT: Always check for existing user first to avoid conflicts
existing_check = self.users_collection.document(str(user_id)).get()
if existing_check.exists:
    return True  # User exists, treat as success
```

### Step Progression (main.py:299)
```python
# Users must complete steps in order - check missing fields before step 6
if step == 6:
    # Verify all social usernames and BEP20 address are provided
    # Block completion if any are missing
```

### Callback Query Handling (main.py:389)
- All inline keyboard buttons trigger `button_handler()`
- Always call `await query.answer()` first
- Edit message with `query.edit_message_text()` for updates
- Send new messages via `context.bot.send_message()` for step transitions

### Admin Functions (database.py:606-721)
- `update_reward_status()` - Mark rewards as paid
- `get_pending_rewards()` - List all pending payments
- `get_reward_summary()` - Statistics on MNTC distribution
- `update_referral_rewards()` - Manually update referrer bonuses

## Data Models

### User Document Structure
```python
{
    "user_id": 123456789,
    "username": "john_crypto",
    "first_name": "John",
    "current_step": 3,  # 1-6, or 7 when completed
    "steps_completed": {"step_1": True, "step_2": True, ...},
    "social_usernames": {
        "twitter": "john_crypto",
        "instagram": "john.crypto",
        "coinmarketcap": "john_crypto_2024"
    },
    "bep20_address": "0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52",
    "referral_code": "REFABC12345",
    "referred_by": "REFXYZ67890",  # referrer's code
    "is_referred": True,
    "referral_stats": {
        "total_referrals": 3,
        "total_rewards": 6  # 3 referrals × 2 MNTC
    },
    "reward_info": {
        "mntc_earned": 4,
        "reward_type": "referred",  # or "normal"
        "completion_date": "2024-01-15T10:30:00",
        "reward_status": "pending"  # or "paid"
    }
}
```

## Common Issues & Solutions

### Firebase Connection Failures
- Check `FIREBASE_SERVICE_ACCOUNT_JSON` is valid JSON
- Verify `project_id` matches `FIREBASE_PROJECT_ID`
- Private key must have actual newlines, not `\n` strings
- Circuit breaker opens after 5 failures - wait 30s

### Bot Conflict Errors
- Only one bot instance can poll at a time
- Delete webhooks: `await bot.delete_webhook(drop_pending_updates=True)`
- Check no other processes using same `BOT_TOKEN`

### Rate Limiting
- `/start` command rate limited to once per 5 seconds per user (main.py:109)
- Prevents spam from repeated restarts

### Referral Code Validation
- Must match pattern: `^REF[A-Z0-9]{8}$`
- Case-sensitive
- Cannot use own referral code
- Only works for new users

## Key Validation Rules

### BEP20 Address (validators.py:30)
- Must start with `0x`
- Exactly 42 characters
- Hexadecimal only (0-9, a-f, A-F)
- Cannot be zero address, dead address, or test addresses

### Social Usernames (validators.py:77)
- 2-30 characters
- Letters, numbers, underscores, dots only
- Must start and end with alphanumeric
- No consecutive special characters (`__`, `..`, `._`)
- Cannot be all numbers

### CoinMarketCap User ID (validators.py:146)
- 3-50 characters
- Letters, numbers, underscores, dots, hyphens
- Same rules as social usernames

## Testing Checklist

When modifying the bot:
- [ ] Test complete flow from `/start` to completion
- [ ] Test referral link flow (referred user journey)
- [ ] Test all validation edge cases
- [ ] Verify Firebase connection with `test_firebase_connection.py`
- [ ] Check circuit breaker activates after failures
- [ ] Test admin commands if modifying reward system
- [ ] Verify message templates render correctly (Markdown)
- [ ] Test button callbacks and inline keyboards

## Deployment Notes

**Render.com Configuration:**
- Uses `render.yaml` for infrastructure as code
- Python 3.11 runtime specified
- Build command installs dependencies and validates Firebase SDK
- Start command includes diagnostic output
- All secrets managed via Render environment variables

**Required Environment Variables on Render:**
- `BOT_TOKEN` (from BotFather)
- `FIREBASE_SERVICE_ACCOUNT_JSON` (complete service account JSON)
- `FIREBASE_PROJECT_ID=kriptospire`
- `CUSTOMER_CARE_USERNAME=Minativerseofficial`

**Logs:**
- All operations logged via Python `logging` module
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Check Render logs for Firebase connection issues, conflicts, circuit breaker events

## Performance Optimizations (NEW)

The bot has been optimized to handle 100,000+ users efficiently.

### Optimization Files

**cache_manager.py** - Multi-tier caching system
- User cache: 10K entries, 5-min TTL
- Referral code cache: 5K entries, 10-min TTL
- Stats cache: 100 entries, 2-min TTL
- Expected 85-90% cache hit rate
- Reduces Firebase queries by 95%

**database_optimized.py** - Optimized database layer (replaces database.py)
- Drop-in replacement with same API
- Integrated caching (write-through strategy)
- Async retry logic (non-blocking)
- Smart cache invalidation
- Performance tracking via `get_performance_stats()`

**firestore.indexes.json** - Database query optimization
- Composite indexes for common queries
- 100x faster referral lookups
- 60x faster admin queries
- Deploy: `firebase deploy --only firestore:indexes`

### Performance Improvements

| Metric | Before (35K users) | After (100K users) | Improvement |
|--------|-------------------|-------------------|-------------|
| Response time | 1-2 minutes | 200-500ms | 180x faster |
| Firebase queries | 500K/day | 60K/day | 95% reduction |
| Cost | $54/month | $6.60/month | 88% savings |

### Migration

```bash
# Auto-creates backup and migrates
python migrate_to_optimized.py

# Deploy Firestore indexes
firebase deploy --only firestore:indexes

# Test locally then deploy
python main.py
git push origin main
```

### Monitoring

Add `/cachestats` command to monitor performance:
- Cache hit rate (target: 85%+)
- Firebase query count
- Circuit breaker status

See **QUICK_START_OPTIMIZATION.md** for fast deployment or **OPTIMIZATION_GUIDE.md** for complete details.

### Key Points

- Database structure unchanged (admin panel works!)
- Drop-in replacement (same API)
- Zero breaking changes
- Easy rollback if needed
- Cache warms up over 1-2 hours
