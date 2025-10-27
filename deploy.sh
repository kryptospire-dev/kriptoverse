#!/bin/bash
# Deployment helper script for MNTC Rewards Bot

echo "🚀 MNTC Rewards Bot - Deployment Helper"
echo "========================================"
echo ""

# Check if git is initialized
if [ ! -d .git ]; then
    echo "❌ Git not initialized. Run: git init"
    exit 1
fi

# Stage all files
echo "📦 Staging files..."
git add .

# Show status
echo ""
echo "📋 Files to commit:"
git status --short

# Commit
echo ""
read -p "Enter commit message (or press Enter for default): " commit_msg
if [ -z "$commit_msg" ]; then
    commit_msg="Deploy optimized bot with Redis, Prometheus, and 100K+ user support"
fi

git commit -m "$commit_msg"

# Check if remote exists
if ! git remote | grep -q origin; then
    echo ""
    echo "📝 Git remote not configured."
    echo "Please create a GitHub repository first, then run:"
    echo ""
    echo "git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git"
    echo "git push -u origin main"
    echo ""
    exit 0
fi

# Push
echo ""
echo "🚀 Pushing to GitHub..."
git branch -M main
git push -u origin main

echo ""
echo "✅ Deployment to GitHub complete!"
echo ""
echo "📖 Next steps:"
echo "1. Go to https://render.com"
echo "2. Create a new Web Service"
echo "3. Connect your GitHub repository"
echo "4. Set environment variables (see DEPLOYMENT.md)"
echo "5. Deploy!"
echo ""
echo "📚 Full guide: See DEPLOYMENT.md"
