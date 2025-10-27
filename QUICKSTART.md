# Quick Start Guide

Get your optimized MNTC Rewards Bot running in 5 minutes!

## 🚀 Fast Track (Local Development)

### Step 1: Install Dependencies (30 seconds)
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment (2 minutes)
```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your credentials:
# - BOT_TOKEN (from @BotFather)
# - FIREBASE_DB_URL (from Firebase Console)
# - FIREBASE_CREDENTIALS or FIREBASE_CRED_PATH
```

**Minimal `.env` for testing:**
```env
BOT_TOKEN=your_bot_token_here
FIREBASE_DB_URL=https://your-project.firebaseio.com
FIREBASE_CRED_PATH=firebase-credentials.json
MINATI_CHANNEL=@Minatirewards
MINATI_CHANNEL_ID=-1002975509146
```

### Step 3: Run the Bot (10 seconds)
```bash
python bot.py
```

You should see:
```
🤖 MNTC Rewards Bot Starting...
✅ Webhook Mode: False
✅ Redis: False
✅ Connection Pool Size: 32
✅ Max Concurrent Updates: 100
✅ Cache TTL: 300s
🚀 Bot is optimized for 100K+ concurrent users
📊 Metrics server started on port 8000
✅ Starting in polling mode
```

### Step 4: Test the Bot
1. Open Telegram
2. Search for your bot
3. Send `/start`
4. Complete the verification steps

## 📊 View Metrics (Optional)

Open your browser and visit:
```
http://localhost:8000/metrics
```

You'll see Prometheus metrics showing bot performance in real-time!

## 🚀 Production Deployment

### Option A: Render.com (Recommended)

1. **Push to GitHub:**
```bash
git init
git add .
git commit -m "Initial commit"
git push origin main
```

2. **Create Render Service:**
- Go to [render.com](https://render.com)
- Click "New +" → "Web Service"
- Connect your GitHub repository
- Render will auto-detect `render.yaml`

3. **Set Environment Variables:**
In Render dashboard, add:
- `BOT_TOKEN`
- `FIREBASE_DB_URL`
- `FIREBASE_CREDENTIALS` (paste the entire JSON)

4. **Optional - Enable Redis:**
- Create a Redis instance in Render
- Copy the Redis URL
- Add `REDIS_ENABLED=true` and `REDIS_URL=<your-redis-url>`

5. **Deploy:**
- Click "Create Web Service"
- Wait for deployment (~2 minutes)
- Bot is now running 24/7!

### Option B: Docker

```bash
# Build image
docker build -t mntc-bot .

# Run container
docker run -d \
  --name mntc-bot \
  --env-file .env \
  -p 8000:8000 \
  -p 8443:8443 \
  mntc-bot
```

### Option C: VPS/Cloud Server

```bash
# Install Python 3.11+
sudo apt update
sudo apt install python3.11 python3-pip

# Clone repository
git clone <your-repo-url>
cd new_bot

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Edit with your values

# Run with systemd (stays running)
sudo nano /etc/systemd/system/mntc-bot.service
```

**systemd service file:**
```ini
[Unit]
Description=MNTC Rewards Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable mntc-bot
sudo systemctl start mntc-bot

# Check status
sudo systemctl status mntc-bot

# View logs
sudo journalctl -u mntc-bot -f
```

## 🔧 Enable Production Features

### Enable Webhooks (5x faster)
```bash
# In .env or environment variables:
WEBHOOK_ENABLED=true
WEBHOOK_URL=https://your-domain.com
WEBHOOK_PORT=8443
```

### Enable Redis (distributed caching)
```bash
# Install Redis
sudo apt install redis-server

# Or use managed Redis (Render, AWS, etc.)

# In .env:
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379
```

### Increase Performance
```bash
# For 50K+ users:
CONNECTION_POOL_SIZE=32
MAX_CONCURRENT_UPDATES=100

# For 100K+ users:
CONNECTION_POOL_SIZE=64
MAX_CONCURRENT_UPDATES=200

# For 200K+ users:
CONNECTION_POOL_SIZE=100
MAX_CONCURRENT_UPDATES=500
```

## 🐛 Troubleshooting

### Bot not starting?
```bash
# Check Python version (must be 3.9+)
python --version

# Install dependencies again
pip install -r requirements.txt --upgrade

# Check environment variables
cat .env
```

### Can't connect to Firebase?
```bash
# Verify credentials file exists
ls -l firebase-credentials.json

# Or check FIREBASE_CREDENTIALS is valid JSON
echo $FIREBASE_CREDENTIALS | python -m json.tool
```

### Bot not responding to commands?
1. Check bot is running: `ps aux | grep bot.py`
2. Check Telegram token is correct
3. Verify bot is not blocked by user
4. Check logs for errors

### Membership verification failing?
1. Add bot as **admin** to channel
2. Give bot "View Members" permission
3. Verify `MINATI_CHANNEL_ID` is correct (use @username_to_id_bot)

### High memory usage?
```bash
# Enable Redis to offload memory
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379

# Reduce cache TTL
CACHE_TTL=180  # 3 minutes instead of 5
```

## 📊 Verify Everything Works

### 1. Check Bot is Running
```bash
curl http://localhost:8000/metrics | grep bot_requests_total
```

### 2. Check Health Status
```bash
curl http://localhost:8443/health
```

Should return:
```json
{
  "status": "healthy",
  "redis": "healthy",
  "firebase": "healthy"
}
```

### 3. Test Commands
In Telegram:
- `/start` - Should create new user
- `/balance` - Should show balance
- `/referral` - Should ask to complete steps
- `/help` - Should show help

### 4. Monitor Metrics
Visit `http://localhost:8000/metrics` and look for:
- `bot_requests_total` - Should increase with each command
- `bot_cache_hits_total` - Should increase with repeated membership checks
- `bot_errors_total` - Should stay at 0

## 🎯 Performance Checklist

For production deployment, ensure:

- [x] Dependencies installed
- [x] Environment variables configured
- [x] Bot running and responding
- [ ] Webhooks enabled (recommended)
- [ ] Redis enabled (recommended)
- [ ] Health checks configured
- [ ] Metrics being collected
- [ ] Bot is admin in channel
- [ ] Firebase Blaze plan (for >10K users)
- [ ] Auto-restart configured (systemd/Docker)

## 💡 Quick Tips

1. **Start simple** - Use polling mode first, enable webhooks later
2. **Monitor early** - Watch Prometheus metrics from day 1
3. **Enable Redis soon** - Even for small deployments
4. **Scale gradually** - Increase pool size based on actual load
5. **Test locally** - Always test changes locally before deploying

## 🆘 Need Help?

1. Check [README.md](README.md) for detailed documentation
2. Review [CLAUDE.md](CLAUDE.md) for architecture details
3. See [PERFORMANCE_IMPROVEMENTS.md](PERFORMANCE_IMPROVEMENTS.md) for what changed
4. Check logs: `sudo journalctl -u mntc-bot -f`
5. View metrics: `http://localhost:8000/metrics`

## 🎉 You're Ready!

Your bot is now:
- ✅ Running and responding
- ✅ Optimized for 100K+ users
- ✅ Monitored with Prometheus
- ✅ Production-ready

**Next**: Enable webhooks and Redis for maximum performance! 🚀
