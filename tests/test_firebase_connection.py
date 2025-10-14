#!/usr/bin/env python3
"""
Test script to verify Firebase connection and JWT token validation
Run this before starting your bot to ensure credentials are working correctly
"""

import os
import sys
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=" * 60)
print("Firebase Connection Test")
print("=" * 60)

# Check environment variables
print("\n1. Environment Variables Check:")
print(f"   BOT_TOKEN: {'[OK] Set' if os.getenv('BOT_TOKEN') else '[MISSING]'}")
print(f"   FIREBASE_PROJECT_ID: {os.getenv('FIREBASE_PROJECT_ID', '[MISSING]')}")
print(f"   FIREBASE_SERVICE_ACCOUNT_JSON: {'[OK] Set' if os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON') else '[MISSING]'}")
print(f"   FIREBASE_SERVICE_ACCOUNT_PATH: {os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH', '[MISSING]')}")

# Check service account file
firebase_file_path = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH', './firebase-service-account.json')
print(f"\n2. Service Account File Check:")
print(f"   Path: {firebase_file_path}")
print(f"   Exists: {'[OK] Yes' if os.path.exists(firebase_file_path) else '[NO]'}")

if os.path.exists(firebase_file_path):
    try:
        with open(firebase_file_path, 'r') as f:
            file_data = json.load(f)
        print(f"   Valid JSON: [OK] Yes")
        print(f"   Project ID: {file_data.get('project_id', 'Missing')}")
        print(f"   Client Email: {file_data.get('client_email', 'Missing')}")
        print(f"   Private Key ID: {file_data.get('private_key_id', 'Missing')}")

        private_key = file_data.get('private_key', '')
        if private_key:
            print(f"   Private Key: [OK] Present ({len(private_key)} chars)")
            print(f"   Key Format: {'[OK] Valid' if private_key.startswith('-----BEGIN PRIVATE KEY-----') else '[INVALID]'}")
        else:
            print(f"   Private Key: [MISSING]")
    except Exception as e:
        print(f"   Error reading file: {e}")

# Test Firebase connection
print(f"\n3. Firebase Connection Test:")
try:
    # Add parent directory to path for imports
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

    # Import after environment setup
    from core.database import Database

    print("   Creating Database instance...")
    db = Database()
    print("   [OK] Firebase connection successful!")

    # Test basic operations
    print("   Testing database operations...")
    stats = db.get_user_stats()
    print(f"   [OK] Database query successful!")
    print(f"   Total users in database: {stats.get('total_users', 0)}")

    # Close connection
    db.close_connection()
    print("   [OK] Connection closed successfully!")

except Exception as e:
    print(f"   [FAILED] Firebase connection failed: {e}")
    print("\n   Common Solutions:")
    print("   1. Use Option 1 from the fix guide (environment variables only)")
    print("   2. Use Option 2 from the fix guide (service account file only)")
    print("   3. Check that your credentials match between .env and .json files")
    print("   4. Ensure private key has proper newline formatting")
    sys.exit(1)

# Test bot token
print(f"\n4. Bot Token Test:")
bot_token = os.getenv('BOT_TOKEN')
if bot_token:
    if len(bot_token.split(':')) == 2 and len(bot_token) > 40:
        print("   [OK] Bot token format appears valid")
    else:
        print("   [INVALID] Bot token format appears invalid")
else:
    print("   [MISSING] Bot token missing")

print("\n" + "=" * 60)
print("Test completed! If all checks passed, you can run your bot.")
print("=" * 60)
