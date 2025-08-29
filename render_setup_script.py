#!/usr/bin/env python3
"""
Enhanced Render Deployment Setup Script for Firebase
This script helps you prepare your Firebase credentials for Render deployment
"""

import json
import base64
import os
import sys
from pathlib import Path

def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_section(title):
    """Print a formatted section"""
    print(f"\n🔧 {title}")
    print("-" * 50)

def validate_service_account_file():
    """Validate that the service account JSON is properly formatted"""

    service_account_path = "firebase-service-account.json"

    if not os.path.exists(service_account_path):
        print(f"❌ Service account file not found: {service_account_path}")
        print("\n📝 To create this file:")
        print("1. Go to Firebase Console (https://console.firebase.google.com)")
        print("2. Select your project → Settings → Service Accounts")
        print("3. Click 'Generate new private key'")
        print("4. Save the downloaded file as 'firebase-service-account.json'")
        print("5. Place it in your project root folder")
        return False, None

    try:
        with open(service_account_path, 'r') as f:
            service_account = json.load(f)

        # Validate required fields
        required_fields = [
            'type', 'project_id', 'private_key_id', 'private_key',
            'client_email', 'client_id', 'auth_uri', 'token_uri'
        ]

        missing_fields = [field for field in required_fields if field not in service_account]

        if missing_fields:
            print(f"❌ Missing required fields in service account: {missing_fields}")
            return False, None

        # Validate private key format
        private_key = service_account.get('private_key', '')
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            print("❌ Invalid private key format in service account")
            return False, None

        print(f"✅ Service account file is valid")
        print(f"📧 Client Email: {service_account.get('client_email')}")
        print(f"🆔 Project ID: {service_account.get('project_id')}")

        return True, service_account

    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON format in service account file: {e}")
        return False, None
    except Exception as e:
        print(f"❌ Error reading service account file: {e}")
        return False, None

def generate_environment_variables(service_account):
    """Generate environment variables for Render deployment"""

    print_header("RENDER ENVIRONMENT VARIABLES")

    # Create a compact JSON string
    json_string = json.dumps(service_account, separators=(',', ':'))

    print_section("Method 1: Single JSON Variable (RECOMMENDED)")
    print("Add this environment variable to your Render dashboard:")
    print("\n🔧 Variable Name: FIREBASE_SERVICE_ACCOUNT_JSON")
    print("📄 Variable Value (copy exactly, no line breaks):")
    print("-" * 50)
    print(json_string)
    print("-" * 50)

    # Alternative: Base64 encoded
    print_section("Method 2: Base64 Encoded (If Method 1 fails)")
    json_bytes = json_string.encode('utf-8')
    base64_encoded = base64.b64encode(json_bytes).decode('utf-8')

    print("🔧 Variable Name: FIREBASE_SERVICE_ACCOUNT_JSON")
    print("📄 Variable Value (base64 encoded):")
    print("-" * 50)
    print(base64_encoded)
    print("-" * 50)

    # Individual variables as last resort
    print_section("Method 3: Individual Variables (Last Resort)")
    print("If both methods above fail, set these individual variables:")

    env_vars = {
        'FIREBASE_TYPE': service_account.get('type'),
        'FIREBASE_PROJECT_ID': service_account.get('project_id'),
        'FIREBASE_PRIVATE_KEY_ID': service_account.get('private_key_id'),
        'FIREBASE_PRIVATE_KEY': service_account.get('private_key'),
        'FIREBASE_CLIENT_EMAIL': service_account.get('client_email'),
        'FIREBASE_CLIENT_ID': service_account.get('client_id'),
        'FIREBASE_AUTH_URI': service_account.get('auth_uri'),
        'FIREBASE_TOKEN_URI': service_account.get('token_uri'),
        'FIREBASE_AUTH_PROVIDER_X509_CERT_URL': service_account.get('auth_provider_x509_cert_url'),
        'FIREBASE_CLIENT_X509_CERT_URL': service_account.get('client_x509_cert_url'),
        'FIREBASE_UNIVERSE_DOMAIN': service_account.get('universe_domain', 'googleapis.com')
    }

    for key, value in env_vars.items():
        if value:
            print(f"\n🔧 {key}")
            if key == 'FIREBASE_PRIVATE_KEY':
                # Show first and last few characters for security
                safe_key = value[:50] + '...[TRUNCATED]...' + value[-50:]
                print(f"📄 {safe_key}")
                print("   ⚠️  Copy the COMPLETE private key including -----BEGIN/END----- lines")
            else:
                print(f"📄 {value}")

    return json_string

def get_additional_variables():
    """Get additional required environment variables"""

    additional_vars = {}

    # Try to read from .env file if it exists
    if os.path.exists('.env'):
        print("📖 Reading additional variables from .env file...")
        try:
            with open('.env', 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#') and line:
                        key, value = line.split('=', 1)
                        additional_vars[key.strip()] = value.strip()
        except Exception as e:
            print(f"⚠️  Error reading .env file: {e}")

    return additional_vars

def display_additional_variables(additional_vars):
    """Display additional required environment variables"""

    print_section("Additional Required Variables")

    required_vars = {
        'BOT_TOKEN': 'Your Telegram bot token from @BotFather',
        'CUSTOMER_CARE_USERNAME': 'Your customer care Telegram username',
        'FIREBASE_PROJECT_ID': 'Your Firebase project ID (usually kriptospire)'
    }

    for var_name, description in required_vars.items():
        value = additional_vars.get(var_name, 'YOUR_VALUE_HERE')
        print(f"\n🔧 {var_name}")
        print(f"📄 {value}")
        print(f"ℹ️  {description}")

def create_render_env_file(service_account_json, additional_vars):
    """Create a reference .env.render file"""

    try:
        with open('.env.render', 'w') as f:
            f.write("# Environment variables for Render deployment\n")
            f.write("# Copy these to your Render dashboard\n")
            f.write("# DO NOT commit this file to Git!\n\n")

            f.write("# Firebase Configuration\n")
            f.write(f'FIREBASE_SERVICE_ACCOUNT_JSON={service_account_json}\n')
            f.write(f'FIREBASE_PROJECT_ID={additional_vars.get("FIREBASE_PROJECT_ID", "kriptospire")}\n\n')

            f.write("# Bot Configuration\n")
            f.write(f'BOT_TOKEN={additional_vars.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")}\n')
            f.write(f'CUSTOMER_CARE_USERNAME={additional_vars.get("CUSTOMER_CARE_USERNAME", "YOUR_USERNAME_HERE")}\n\n')

            f.write("# Optional Configuration\n")
            f.write('PYTHON_VERSION=3.11\n')
            f.write('PYTHONUNBUFFERED=1\n')
            f.write('ENVIRONMENT=production\n')

        print("✅ Reference file created: .env.render")
        return True
    except Exception as e:
        print(f"❌ Error creating .env.render file: {e}")
        return False

def display_deployment_instructions():
    """Display step-by-step deployment instructions"""

    print_header("RENDER DEPLOYMENT INSTRUCTIONS")

    instructions = [
        "🌐 Go to your Render dashboard (https://dashboard.render.com)",
        "➕ Click 'New' → 'Web Service'",
        "🔗 Connect your GitHub repository",
        "📝 Select your bot repository",
        "⚙️  Configure service settings:",
        "   • Name: minati-vault-bot",
        "   • Environment: Python",
        "   • Build Command: python -m pip install -r requirements.txt",
        "   • Start Command: python main.py",
        "🔐 Go to 'Environment' tab and add all variables above",
        "🚀 Click 'Create Web Service'",
        "📊 Monitor build logs for success messages",
        "🧪 Test your bot with /start command"
    ]

    for i, instruction in enumerate(instructions, 1):
        print(f"{i:2d}. {instruction}")

def display_troubleshooting():
    """Display common issues and solutions"""

    print_header("TROUBLESHOOTING COMMON ISSUES")

    issues = {
        "❌ 'command not found' error": [
            "Use 'python main.py' not 'python3 main.py'",
            "Check that runtime.txt specifies Python 3.11",
            "Verify Procfile uses correct command"
        ],
        "❌ Firebase connection failed": [
            "Verify FIREBASE_SERVICE_ACCOUNT_JSON is set correctly",
            "Ensure JSON has no line breaks or extra spaces",
            "Try Method 2 (base64) or Method 3 (individual vars)",
            "Check Firebase project exists and is active"
        ],
        "❌ Bot token invalid": [
            "Verify BOT_TOKEN matches token from @BotFather",
            "Ensure no extra spaces in the token",
            "Check token hasn't been revoked"
        ],
        "❌ Module import errors": [
            "Verify all dependencies are in requirements.txt",
            "Check build logs for installation errors",
            "Ensure Python version matches runtime.txt"
        ]
    }

    for issue, solutions in issues.items():
        print(f"\n{issue}")
        for solution in solutions:
            print(f"  • {solution}")

def display_security_warnings():
    """Display important security warnings"""

    print_header("🔒 SECURITY WARNINGS")

    warnings = [
        "🚫 NEVER commit firebase-service-account.json to Git",
        "🚫 NEVER commit .env or .env.render files to Git",
        "🚫 NEVER share your bot token publicly",
        "🚫 NEVER share Firebase credentials publicly",
        "✅ Always use environment variables for secrets",
        "✅ Add sensitive files to .gitignore",
        "✅ Regularly rotate credentials",
        "✅ Monitor for unauthorized access"
    ]

    for warning in warnings:
        print(f"  {warning}")

def test_json_parsing(json_string):
    """Test if the generated JSON string can be parsed correctly"""

    print_section("Testing Generated JSON")

    try:
        # Test parsing
        parsed = json.loads(json_string)
        print("✅ JSON string is valid and parseable")

        # Test required fields
        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        missing = [field for field in required_fields if field not in parsed]

        if missing:
            print(f"⚠️  Missing fields in parsed JSON: {missing}")
            return False

        print("✅ All required fields present in parsed JSON")
        return True

    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error testing JSON: {e}")
        return False

def main():
    """Main function to run the setup script"""

    print_header("🔥 FIREBASE RENDER SETUP SCRIPT")
    print("This script will help you prepare environment variables for Render deployment.")

    try:
        # Step 1: Validate service account file
        print_section("Step 1: Validating Service Account File")
        is_valid, service_account = validate_service_account_file()

        if not is_valid:
            print("\n❌ Cannot proceed without valid service account file.")
            print("Please fix the issues above and run the script again.")
            return False

        # Step 2: Generate environment variables
        print_section("Step 2: Generating Environment Variables")
        json_string = generate_environment_variables(service_account)

        # Step 3: Test JSON parsing
        if not test_json_parsing(json_string):
            print("⚠️  JSON parsing test failed, but continuing...")

        # Step 4: Get additional variables
        additional_vars = get_additional_variables()

        # Step 5: Display additional variables
        display_additional_variables(additional_vars)

        # Step 6: Create reference file
        print_section("Step 6: Creating Reference File")
        create_render_env_file(json_string, additional_vars)

        # Step 7: Display instructions
        display_deployment_instructions()

        # Step 8: Display troubleshooting
        display_troubleshooting()

        # Step 9: Security warnings
        display_security_warnings()

        print_header("✅ SETUP COMPLETE")
        print("Your environment variables are ready for Render deployment!")
        print("\nNext steps:")
        print("1. Copy the environment variables to your Render dashboard")
        print("2. Deploy your service")
        print("3. Monitor the build logs")
        print("4. Test your bot")

        return True

    except KeyboardInterrupt:
        print("\n\n👋 Setup cancelled by user")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print(f"Error type: {type(e).__name__}")
        return False

def interactive_setup():
    """Interactive setup mode for guided configuration"""

    print_header("🎯 INTERACTIVE SETUP MODE")

    try:
        # Check if user wants to create .env file
        create_env = input("\n🤔 Would you like to create/update your .env file? (y/n): ").lower().strip()

        if create_env in ['y', 'yes']:
            print("\n📝 Let's create your .env file...")

            env_vars = {}

            # Get bot token
            bot_token = input("🤖 Enter your Bot Token (from @BotFather): ").strip()
            if bot_token:
                env_vars['BOT_TOKEN'] = bot_token

            # Get customer care username
            care_username = input("👤 Enter Customer Care Username (without @): ").strip()
            if care_username:
                env_vars['CUSTOMER_CARE_USERNAME'] = care_username

            # Get Firebase project ID
            project_id = input("🔥 Enter Firebase Project ID [kriptospire]: ").strip() or "kriptospire"
            env_vars['FIREBASE_PROJECT_ID'] = project_id

            # Create .env file
            try:
                with open('.env', 'w') as f:
                    f.write("# Telegram Bot Configuration\n")
                    for key, value in env_vars.items():
                        f.write(f"{key}={value}\n")

                    f.write("\n# Firebase Configuration (for local development)\n")
                    f.write("FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-service-account.json\n")

                print("✅ .env file created successfully!")

            except Exception as e:
                print(f"❌ Error creating .env file: {e}")

        # Run main setup
        print("\n🚀 Running main setup...")
        return main()

    except KeyboardInterrupt:
        print("\n👋 Interactive setup cancelled")
        return False

if __name__ == "__main__":
    print("🔥 Firebase Render Setup Script")
    print("=" * 40)

    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        success = interactive_setup()
    else:
        success = main()

        # Offer interactive mode if main setup had issues
        if not success:
            try_interactive = input("\n🤔 Would you like to try interactive setup? (y/n): ").lower().strip()
            if try_interactive in ['y', 'yes']:
                success = interactive_setup()

    # Final message
    if success:
        print("\n🎉 Setup completed successfully!")
        print("You can now deploy your bot to Render.")
    else:
        print("\n😞 Setup encountered issues.")
        print("Please review the errors above and try again.")
        print("\nFor help, check:")
        print("• Render documentation: https://render.com/docs")
        print("• Firebase documentation: https://firebase.google.com/docs")
    
    input("\nPress Enter to exit...")