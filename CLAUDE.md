# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **enterprise-grade Telegram bot** for MNTC (Minati Coin) rewards with a referral-based verification system. The bot is optimized for **100,000+ concurrent users** with Redis caching, webhook support, Prometheus monitoring, and circuit breakers.

## Development Commands

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials: BOT_TOKEN, FIREBASE_DB_URL, FIREBASE_CREDENTIALS
```

### Running the Bot
```bash
# Development mode (polling)
python bot.py

# Production with Redis
REDIS_ENABLED=true REDIS_URL=redis://localhost:6379 python bot.py

# Production with webhooks
WEBHOOK_ENABLED=true WEBHOOK_URL=https://yourdomain.com python bot.py
```

### Testing
```bash
# Test Redis connection
python test_redis.py

# Test bot locally with polling mode
WEBHOOK_ENABLED=false python bot.py
```

### Monitoring
```bash
# Prometheus metrics
curl http://localhost:8000/metrics

# Health check (webhook mode only)
curl http://localhost:8443/health
```

## Architecture

### High-Performance Design

**Dual-Mode Operation**:
- **Polling Mode**: For development and low-traffic scenarios (< 10K users)
- **Webhook Mode**: For production with high traffic (10K+ users)

**Distributed Caching**: Redis + in-memory fallback for:
- Membership verification results (5-minute TTL)
- Rate limiting with sliding window algorithm
- General cache with automatic fallback to memory

**Connection Pooling**:
- Configurable pool size (default: 32 connections)
- Concurrent update processing (default: 100 simultaneous)
- Automatic retry with exponential backoff

**Circuit Breakers**: Using tenacity library:
- 3 retry attempts with exponential backoff
- Automatic handling of rate limits (RetryAfter)
- Graceful degradation on failures

### State Machine Flow

Users progress through 3 sequential steps:
- **Step 0 → Step 1**: Download & review Minati Vault app (self-reported)
- **Step 1 → Step 2**: Join Telegram channel (API verified with caching)
- **Step 2 → Step 3**: Submit BEP20 wallet (validated + duplicate prevention)

**Important**: Referral codes unlock only after completing all 3 steps.

### Code Organization

**Single-file architecture** (bot.py, ~1200 lines):
- **Lines 1-86**: Configuration and environment loading
- **Lines 87-104**: Prometheus metrics initialization
- **Lines 105-133**: Firebase initialization
- **Lines 134-168**: Redis client setup
- **Lines 169-247**: `CacheManager` - Three-tier cache (Redis + in-memory)
- **Lines 248-279**: Retry logic with exponential backoff
- **Lines 280-339**: `RateLimiter` - Distributed rate limiting with sliding window
- **Lines 340-451**: Database helper functions (user CRUD, transactions)
- **Lines 452-494**: Membership verification with caching
- **Lines 495-533**: `credit_reward()` - Atomic balance updates
- **Lines 534-562**: Referral count management (cached, O(1) lookup)
- **Lines 563-612**: Wallet validation and atomic registration
- **Lines 613-1011**: Command handlers (`/start`, step progression, button callbacks)
- **Lines 1012-1106**: `/balance` and `/referral` commands
- **Lines 1107-1147**: `/help` command and error handler
- **Lines 1148-1178**: Health check endpoint
- **Lines 1179-1268**: Application setup (webhook/polling mode, shutdown hooks)

**Key functions:**
- `check_membership(user_id, force_refresh)` - Cached channel verification (bot.py:452)
- `credit_reward(user_id, amount, reason)` - Atomic balance updates (bot.py:496)
- `increment_referral_count(referrer_id)` - O(1) cached counter (bot.py:535)
- `register_wallet_atomic(user_id, wallet)` - Duplicate prevention (bot.py:586)

**Other files:**
- `test_redis.py` - Redis connection testing utility
- `requirements.txt` - Python dependencies
- `render.yaml` - Render.com deployment configuration
- `.env.example` - Environment variable template

### Firebase Database Structure

```
users/{userId}
  - userId, username, step (0-3), balance
  - referralCode, referredBy
  - referralCount (CACHED - optimized O(1) lookup)
  - completedSteps: {step1, step2, step3}
  - walletAddress
  - joinedAt, lastActive

transactions/{userId}
  - push entries: {amount, reason, timestamp, newBalance}

referralCodeIndex/{referralCode} → userId
referralIndex/{referrerId}/{referredId} → true
walletIndex/{walletAddress} → userId
```

**Key Optimization**: `referralCount` is now cached in the user document and atomically incremented, eliminating the expensive O(N) loop that previously scanned all referred users.

### Caching Architecture

**Three-Tier Caching**:
1. **Redis** (primary): Distributed cache for multi-instance deployments
2. **TTLCache** (fallback): In-memory cache (10K general + 50K membership entries)
3. **Automatic Degradation**: Falls back to memory if Redis unavailable

**Cache Manager** (bot.py:177-247):
- `CacheManager.get()`: Try Redis → fallback to memory
- `CacheManager.set()`: Write to both Redis and memory
- `CacheManager.delete()`: Remove from both layers
- `CacheManager.increment()`: Atomic counter in Redis

### Rate Limiting

**Distributed Rate Limiter** (bot.py:281-339):
- Uses Redis sorted sets for sliding window algorithm
- Per-user limits: /start (10/min), /balance, /referral (5/min)
- Automatically cleans old entries
- Fails open (allows request) if Redis unavailable

### Monitoring & Observability

**Prometheus Metrics** (bot.py:91-104):
- **Counters**: requests_total, db_operations_total, cache_hits/misses, errors_total
- **Histograms**: request_duration, db_operation_duration
- **Gauges**: active_users, cache_size

**Health Check Endpoint** (bot.py:1148-1178):
- Available at `/health` when webhook enabled
- Checks Redis connectivity
- Checks Firebase connectivity
- Returns cache statistics

### Critical Optimizations

**1. Cached Referral Counts** (bot.py:535-562):
```python
# OLD: O(N) - scanned all referrals every time
# NEW: O(1) - atomic increment + cached read
def increment_referral_count(referrer_id: int)
def get_referral_count(user_id: int)
```

**2. Retry Logic** (bot.py:262-275):
- Exponential backoff for Telegram API requests
- Automatic handling of RetryAfter errors
- 3 attempts with 2-10 second waits

**3. Atomic Transactions**:
- `credit_reward()`: Prevents race conditions in balance updates (bot.py:496-533)
- `register_wallet_atomic()`: Prevents duplicate wallet registration (bot.py:586-606)
- `increment_referral_count()`: Thread-safe counter updates (bot.py:535-551)

**4. Membership Check Optimization** (bot.py:452-494):
- Cached results (5-minute TTL)
- Distributed cache for multi-instance deployments
- Automatic retry with circuit breaker

## Environment Variables

### Required
- `BOT_TOKEN`: Telegram bot token
- `FIREBASE_DB_URL`: Firebase Realtime Database URL
- `FIREBASE_CREDENTIALS`: JSON string (production) OR `FIREBASE_CRED_PATH` (local file)

### Performance Tuning
- `CONNECTION_POOL_SIZE`: Default 32 (increase for higher load)
- `MAX_CONCURRENT_UPDATES`: Default 100 (increase for more throughput)
- `REQUEST_TIMEOUT`: Default 30 seconds
- `CACHE_TTL`: Default 300 seconds (5 minutes)

### Webhook Configuration
- `WEBHOOK_ENABLED`: true/false (default: false)
- `WEBHOOK_URL`: Your public URL (required if webhook enabled)
- `WEBHOOK_PATH`: Endpoint path (default: /webhook)
- `WEBHOOK_PORT`: Port number (default: 8443)

### Redis Configuration
- `REDIS_ENABLED`: true/false (default: false)
- `REDIS_URL`: Redis connection URL (default: redis://localhost:6379)

## Dependencies

**Core libraries** (requirements.txt):
- `python-telegram-bot[webhooks,job-queue]>=22.5` - Telegram Bot API wrapper
- `firebase-admin==6.4.0` - Firebase Realtime Database
- `redis==5.0.1` + `hiredis==2.3.2` - Distributed caching (optional)
- `cachetools==5.3.2` - In-memory TTL cache (fallback)
- `tenacity==8.2.3` - Retry logic with exponential backoff
- `prometheus-client==0.19.0` - Metrics and monitoring
- `aiohttp==3.9.3` + `aiodns==3.1.1` - Async HTTP for webhooks
- `python-dotenv==1.0.1` - Environment variable management

## Scalability Configuration

| User Count | Mode | Redis | Pool Size | Instances |
|------------|------|-------|-----------|-----------|
| 1K-10K | Polling | Optional | 8 | 1 |
| 10K-50K | Webhook | Required | 16 | 1 |
| 50K-200K | Webhook | Required | 32 | 2-3 + LB |
| 200K+ | Webhook | Cluster | 64 | 5-10 (auto-scale) |

## Deployment

### Render.com (render.yaml)
```bash
# The bot auto-detects webhook URL from environment
# Health check endpoint: /health
# Metrics endpoint: http://localhost:8000/metrics
```

### Local Development
```bash
# 1. Copy .env.example to .env
# 2. Fill in BOT_TOKEN and FIREBASE credentials
# 3. Run the bot
python bot.py
```

### Production Checklist
- [ ] Enable webhooks (WEBHOOK_ENABLED=true)
- [ ] Enable Redis (REDIS_ENABLED=true)
- [ ] Set appropriate CONNECTION_POOL_SIZE
- [ ] Configure health checks in load balancer
- [ ] Set up Prometheus monitoring
- [ ] Use Firebase Blaze plan for high throughput
- [ ] Add bot as admin to channel with "View Members" permission

## Making Code Changes

### Adding a New Command

1. **Create command handler** (add around bot.py:1107):
```python
async def mycommand_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Response")
```

2. **Register handler** (in `main()` around bot.py:1240):
```python
app.add_handler(CommandHandler('mycommand', mycommand_command))
```

3. **Add rate limiting** (update bot.py:295):
```python
RATE_LIMIT_COMMANDS = {
    '/start': (10, 60),
    '/mycommand': (5, 60),  # 5 requests per 60 seconds
}
```

4. **Add Prometheus tracking** (wrap with `@track_command` decorator)

### Adding a New Verification Step

1. **Update Firebase structure**: Add `step4` field to `users/{userId}/completedSteps`
2. **Modify step progression** in `button_callback_handler` (bot.py:730-1011)
3. **Update reward logic** in step completion (look for `credit_reward` calls)
4. **Add new button** to keyboard in `start_command` (bot.py:613)

### Modifying Rewards

**Change reward amounts** (bot.py constants):
```python
STEP_COMPLETION_REWARD = 2  # Default: 2 MNTC for completing all steps
REFERRAL_REWARD = 1         # Default: 1 MNTC per referral
```

**Add conditional rewards** (modify `credit_reward()` logic at bot.py:496)

### Adding Custom Cache

```python
# Add new cache type (bot.py:174-175)
custom_cache = TTLCache(maxsize=1000, ttl=CACHE_TTL)

# Use CacheManager methods (bot.py:177-247)
await CacheManager.set(key, value, cache_type='custom')
value = await CacheManager.get(key, cache_type='custom')
```

### Adding Prometheus Metrics

```python
# Define metric (bot.py:91-104)
custom_counter = Counter('bot_custom_total', 'Description', ['label'])

# Use in code
custom_counter.labels(label='value').inc()
```

## Key Implementation Details

**Rate Limiting**: Uses Redis sorted sets for sliding window, not in-memory dicts (prevents memory leaks in multi-instance deployments).

**Membership Verification**: Results are cached for 5 minutes. Force refresh with `force_refresh=True` parameter.

**Wallet Validation**: BEP20 address must match `^0x[a-fA-F0-9]{40}$` and be unique across all users.

**Referral Rewards**: Only credited when referred user completes **all 3 steps**. Referrer is notified via DM.

**Error Handling**: All database operations have retry logic. API errors are logged to Prometheus.

**Circuit Breakers**: Telegram API requests retry 3 times with exponential backoff. Rate limits are handled automatically.

## Monitoring

### Prometheus Metrics
Access at `http://localhost:8000/metrics`:
- `bot_requests_total{command, status}`: Command execution counts
- `bot_db_operations_total{operation, status}`: Database operation counts
- `bot_cache_hits_total{cache_type}`: Cache hit counts
- `bot_cache_misses_total{cache_type}`: Cache miss counts
- `bot_errors_total{error_type}`: Error counts by type
- `bot_request_duration_seconds{command}`: Request latency histogram
- `bot_db_operation_duration_seconds{operation}`: DB latency histogram
- `bot_active_users`: Currently active users (gauge)

### Health Check
Access at `http://localhost:8443/health` (webhook mode):
```json
{
  "status": "healthy",
  "redis": "healthy",
  "firebase": "healthy",
  "cache_size": {"memory": 1234, "membership": 5678}
}
```

## Debugging

### Common Issues

**Bot not starting:**
```bash
# Check required environment variables
echo $BOT_TOKEN
echo $FIREBASE_DB_URL

# Verify Firebase credentials
ls -la firebase-credentials.json  # or check FIREBASE_CREDENTIALS env var

# Test Firebase connection (check logs on bot startup)
python bot.py  # Look for "Firebase initialized successfully"
```

**Redis connection failing:**
```bash
# Test Redis separately
python test_redis.py

# Bot will automatically fallback to in-memory cache
# Look for log: "Redis connection failed" followed by "using in-memory cache only"
```

**Membership verification not working:**
- Ensure bot is admin in the channel (`@Minatirewards`)
- Bot needs "View Members" permission
- Check `MINATI_CHANNEL_ID` matches your channel (-1002975509146)
- Force cache refresh: `check_membership(user_id, force_refresh=True)` (bot.py:452)

**Rate limiting issues:**
- Check Prometheus metrics: `curl http://localhost:8000/metrics | grep bot_errors_total`
- Increase `CONNECTION_POOL_SIZE` if hitting connection limits
- Telegram API limit: 30 messages/second (handled automatically by retry logic, bot.py:262)

**Memory issues:**
- Enable Redis to offload cache: `REDIS_ENABLED=true`
- Reduce `CACHE_TTL` from 300 to 60 seconds
- Check cache size: `curl http://localhost:8443/health` (webhook mode)

### Viewing Logs

```bash
# Run with detailed logging
python bot.py 2>&1 | tee bot.log

# Filter for errors
grep -i error bot.log

# Check specific function
grep "check_membership" bot.log

# Monitor metrics in real-time
watch -n 1 'curl -s http://localhost:8000/metrics | grep bot_requests_total'
```

### Database Inspection

```python
# Direct Firebase queries (Python console)
from firebase_admin import db
ref = db.reference('users/123456789')
user_data = ref.get()
print(user_data)

# Check referral index
ref = db.reference('referralIndex/referrer_id')
referrals = ref.get()
print(f"Referral count: {len(referrals) if referrals else 0}")
```

## Important Notes

- Bot requires admin access to Telegram channel with "View Members" permission
- Redis is **optional** but **highly recommended** for production (multi-instance deployments)
- Webhook mode is **significantly faster** than polling for high-traffic scenarios
- Referral counts are cached (O(1) lookup) instead of calculated on-the-fly (O(N) loop)
- All critical operations use atomic transactions to prevent race conditions
- Bot gracefully degrades: if Redis fails, falls back to in-memory cache
- Logs include function names and line numbers for easy debugging (configured at bot.py:43)
