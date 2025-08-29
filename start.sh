#!/bin/bash
echo "🚀 Starting Minati Vault Bot on Render..."
echo "✅ Environment: Production"
echo "✅ Python Version: $(python --version)"
echo "✅ Installing dependencies..."
pip install -r requirements.txt
echo "✅ Starting bot..."
python main.py