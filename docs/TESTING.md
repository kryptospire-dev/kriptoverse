# Testing Guide for Minati Vault Bot

This document provides a comprehensive guide for testing all bot functionality.

## Table of Contents

1. [Quick Start Testing](#quick-start-testing)
2. [Environment Validation](#environment-validation)
3. [Step-by-Step Bot Flow](#step-by-step-bot-flow)
4. [Validation Tests](#validation-tests)
5. [Performance Tests](#performance-tests)
6. [Common Issues](#common-issues)

---

## Quick Start Testing

### Run All Tests

```bash
# Test Firebase connection
python tests/test_firebase_connection.py

# Test bot functionality (validators, steps, etc.)
python tests/test_bot_functionality.py

# Test optimizations (cache, performance)
python tests/test_optimizations.py
```

### Expected Results

All tests should pass with output showing:
- [OK] for successful tests
- [FAIL] for failed tests (investigate immediately)

---

## Environment Validation

### Required Environment Variables

Check your `.env` file has:

```bash
BOT_TOKEN=your_telegram_bot_token_here
FIREBASE_PROJECT_ID=kriptospire
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
CUSTOMER_CARE_USERNAME=Minativerseofficial
REFERRAL_BOT_USERNAME=minatiVault_bot
```

### Test Firebase Connection

```bash
python tests/test_firebase_connection.py
```

**Expected Output:**
```
============================================================
Firebase Connection Test
============================================================

1. Environment Variables Check:
   BOT_TOKEN: [OK] Set
   FIREBASE_PROJECT_ID: kriptospire
   FIREBASE_SERVICE_ACCOUNT_JSON: [OK] Set

2. Service Account File Check:
   Path: ./firebase-service-account.json
   Exists: [NO] (This is OK if using FIREBASE_SERVICE_ACCOUNT_JSON)

3. Firebase Connection Test:
   [OK] Firebase connection successful!
   [OK] Database query successful!
   Total users in database: XXXXX

4. Bot Token Test:
   [OK] Bot token format appears valid
```

---

## Step-by-Step Bot Flow

### Manual Testing Process

Test the complete user journey:

#### 1. Start Command (New User)

**Action:** Send `/start` to the bot

**Expected Response:**
```
Welcome to Minati Vault Bot!

To complete the process, follow these steps:

1. Download vault and review
2. Follow us on Twitter (X)
3. Follow us on Instagram
4. Follow us on CoinMarketCap
5. Send your Minati Vault BEP20 address
6. Submit final verification

Let's start!
```

**Buttons:** Should show "Start Step 1" button

---

#### 2. Step 1: App Download

**Action:** Click "Start Step 1" button

**Expected Response:**
- Instructions for downloading Minati Vault app
- Download link displayed
- Button: "I've Downloaded the App"

**Action:** Click "I've Downloaded the App"

**Expected:** Moves to Step 2

---

#### 3. Step 2: Twitter Follow

**Expected Response:**
- Instructions for Twitter tasks
- Link to Twitter profile
- Prompt to send Twitter username

**Action:** Send Twitter username (e.g., `john_crypto`)

**Valid Usernames:**
- `john_crypto` ✓
- `test_user` ✓
- `User123` ✓

**Invalid Usernames:**
- `a` (too short)
- `_test` (starts with underscore)
- `test_` (ends with underscore)
- `test..user` (consecutive dots)
- `123456` (all numbers)
- `admin` (reserved)

**Expected:** Username saved, moves to Step 3

---

#### 4. Step 3: Instagram Follow

**Expected Response:**
- Instructions for Instagram tasks
- Link to Instagram profile
- Prompt to send Instagram username

**Action:** Send Instagram username (e.g., `john.crypto`)

**Validation:** Same rules as Twitter

**Expected:** Username saved, moves to Step 4

---

#### 5. Step 4: CoinMarketCap Follow

**Expected Response:**
- Instructions for CoinMarketCap tasks
- Link to CoinMarketCap page
- Prompt to send CoinMarketCap User ID

**Action:** Send CoinMarketCap User ID (e.g., `john_crypto_2024`)

**Validation:**
- 3-50 characters
- Letters, numbers, dots, underscores, hyphens
- Must start/end with alphanumeric

**Expected:** User ID saved, moves to Step 5

---

#### 6. Step 5: BEP20 Address

**Expected Response:**
- Instructions for BEP20 address submission
- Prompt to send BEP20 address

**Action:** Send BEP20 address

**Valid Address Example:**
```
0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52
```

**Validation Rules:**
- Must start with `0x`
- Exactly 42 characters long
- Only hexadecimal characters (0-9, a-f, A-F)
- Cannot be zero address (0x0000...0000)
- Cannot be dead address (0x0000...dead)

**Invalid Addresses:**
- `0x742d35` (too short)
- `742d35...` (missing 0x)
- `0x0000...0000` (zero address)
- `0xGGGG...` (invalid characters)

**Expected:** Address saved, moves to Step 6

---

#### 7. Step 6: Final Verification

**Expected Response:**
- Review of all submitted information
- Button: "Complete Verification"

**Action:** Click "Complete Verification"

**Expected:**
- Congratulations message
- Shows earned MNTC (4 MNTC)
- Displays referral link
- Reward status: Pending

---

### Referral System Testing

#### Test Referral Link Flow

1. **Complete bot as User A**
   - Get referral link: `https://t.me/minatiVault_bot?start=REFABC12345`

2. **Start bot as User B with referral link**
   - Click the referral link
   - Expected: Welcome message mentions referral
   - Complete all steps

3. **Check User A notifications**
   - Expected: User A receives notification about successful referral
   - User A's stats show: Total Referrals +1

4. **Verify rewards**
   - User B: 4 MNTC (referred user)
   - User A: Will receive +2 MNTC bonus (manual update by admin)

---

## Validation Tests

### BEP20 Address Validation

```bash
cd src
python -c "from utils.validators import Validators; print(Validators.validate_bep20_address('0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52'))"
```

**Expected:** `(True, 'Valid BEP20 address')`

### Username Validation

```bash
cd src
python -c "from utils.validators import Validators; print(Validators.validate_username('john_crypto'))"
```

**Expected:** `(True, 'Valid username')`

### Referral Code Validation

```bash
cd src
python -c "from utils.validators import Validators; print(Validators.validate_referral_code('REFABC12345'))"
```

**Expected:** `(True, 'Valid referral code')`

---

## Performance Tests

### Test Cache Performance

```bash
python tests/test_optimizations.py
```

**Expected Metrics:**
- Cache hit rate: 85%+ (after warm-up)
- Response time: < 500ms
- Firebase queries: 95% reduction

### Monitor Production Performance

Use admin commands in Telegram:

```
/health       - Check Firebase connection and circuit breaker
/cachestats   - View cache performance metrics
```

**Expected /cachestats Output:**
```
Cache Statistics:

Total Requests: 1,500
Firebase Queries: 225 (15%)
Cache Hits: 1,275 (85%)
Cache Hit Rate: 85.0%

Cache Sizes:
User Cache: 8,543 / 10,000
Referral Cache: 3,821 / 5,000
Stats Cache: 45 / 100

Circuit Breaker: CLOSED
Average Response Time: 245ms
```

---

## Common Issues

### Issue 1: Firebase Connection Failed

**Symptoms:**
```
[FAILED] Firebase connection failed: Could not automatically determine credentials
```

**Solutions:**
1. Check `FIREBASE_SERVICE_ACCOUNT_JSON` is set in `.env`
2. Verify JSON is valid (use https://jsonlint.com)
3. Ensure `project_id` matches `FIREBASE_PROJECT_ID`
4. Check private key has proper newlines (not `\n` strings)

### Issue 2: Bot Not Responding

**Symptoms:** Bot doesn't reply to `/start`

**Solutions:**
1. Check bot is running: `python src/main.py`
2. Verify `BOT_TOKEN` is correct
3. Check for `Conflict` errors (multiple bot instances)
4. Delete webhook:
   ```python
   import telegram
   bot = telegram.Bot(token='YOUR_TOKEN')
   bot.delete_webhook(drop_pending_updates=True)
   ```

### Issue 3: Validation Errors

**Symptoms:** Valid inputs rejected

**Solutions:**
1. Check validation rules in `src/utils/validators.py`
2. Test validation directly:
   ```bash
   cd src
   python -c "from utils.validators import Validators; print(Validators.validate_username('your_username'))"
   ```
3. Review error message for specific requirement

### Issue 4: Referral Not Working

**Symptoms:** Referral link doesn't apply referral code

**Solutions:**
1. Verify referral code format: `REFXXXXXXXX` (REF + 8 characters)
2. Check user hasn't already started bot (referrals only for new users)
3. Cannot use own referral code
4. Check referrer has completed all steps

### Issue 5: Slow Performance

**Symptoms:** Bot takes > 2 seconds to respond

**Solutions:**
1. Check cache hit rate: `/cachestats`
2. Verify Firebase indexes deployed:
   ```bash
   firebase deploy --only firestore:indexes
   ```
3. Check circuit breaker status: `/health`
4. Review Firebase quota limits in console

### Issue 6: Unicode/Emoji Errors (Windows)

**Symptoms:**
```
UnicodeEncodeError: 'charmap' codec can't encode character
```

**Solutions:**
1. Set environment variable:
   ```bash
   set PYTHONIOENCODING=utf-8
   ```
2. Or run with encoding:
   ```bash
   python -X utf8 src/main.py
   ```
3. Test files avoid printing emojis directly

---

## Test Checklist

### Before Deployment

- [ ] All environment variables set
- [ ] Firebase connection test passes
- [ ] Bot functionality test passes
- [ ] Firebase indexes deployed (wait 15-30 min)
- [ ] Bot responds to `/start`
- [ ] Can complete all 6 steps
- [ ] BEP20 validation works
- [ ] Username validation works
- [ ] Referral system works
- [ ] Cache hit rate > 50% after 1 hour
- [ ] Response time < 1 second

### After Deployment

- [ ] Test complete user flow in production
- [ ] Test referral link flow
- [ ] Check `/health` shows healthy
- [ ] Check `/cachestats` shows good hit rate
- [ ] Monitor logs for errors
- [ ] Verify rewards tracking works
- [ ] Test admin commands (if admin)

---

## Performance Benchmarks

### Response Time Targets

| Action | Target | Excellent |
|--------|--------|-----------|
| `/start` command | < 1s | < 500ms |
| Step completion | < 1s | < 500ms |
| Username validation | < 500ms | < 200ms |
| Address validation | < 500ms | < 200ms |
| Status check | < 500ms | < 200ms |

### Cache Performance Targets

| Metric | Minimum | Target | Excellent |
|--------|---------|--------|-----------|
| Cache hit rate | 50% | 85% | 95% |
| User cache size | 5,000 | 10,000 | 10,000 (max) |
| Firebase queries | < 1,000/day | < 500/day | < 100/day |

### Capacity Targets

| Metric | Current | Target |
|--------|---------|--------|
| Concurrent users | 35,000 | 100,000+ |
| Daily active users | 10,000 | 30,000+ |
| Response time under load | 500ms | < 1s |

---

## Additional Resources

- **Firebase Console:** https://console.firebase.google.com/
- **Telegram Bot API:** https://core.telegram.org/bots/api
- **Performance Guide:** [OPTIMIZATION_GUIDE.md](OPTIMIZATION_GUIDE.md)
- **Claude AI Guide:** [CLAUDE.md](CLAUDE.md)

---

## Support

If you encounter issues not covered here:

1. Check logs: `tail -f logs/bot.log` (if logging to file)
2. Review error messages carefully
3. Test components individually
4. Contact: @Minatirewards on Telegram

---

**Last Updated:** 2025-10-15
**Bot Version:** 2.0.0 (Optimized)
