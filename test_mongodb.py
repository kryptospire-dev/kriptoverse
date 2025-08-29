# test_firebase.py - Test your Firebase connection

import os
import sys
from datetime import datetime

def test_firebase_connection():
    """Test Firebase connection with detailed error reporting"""
    
    print("🔥 Firebase Connection Test")
    print("=" * 40)
    
    # Check environment variables
    print("1. Checking environment variables...")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        bot_token = os.getenv('BOT_TOKEN')
        project_id = os.getenv('FIREBASE_PROJECT_ID')
        service_account_path = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH')
        
        print(f"   ├── BOT_TOKEN: {'✅ Set' if bot_token else '❌ Missing'}")
        print(f"   ├── FIREBASE_PROJECT_ID: {'✅ ' + project_id if project_id else '❌ Missing'}")
        print(f"   └── SERVICE_ACCOUNT_PATH: {'✅ ' + service_account_path if service_account_path else '❌ Missing'}")
        
        if not all([bot_token, project_id, service_account_path]):
            print("\n❌ Missing required environment variables!")
            return False
            
    except Exception as e:
        print(f"   ❌ Error loading environment: {e}")
        return False
    
    # Check service account file
    print("\n2. Checking service account file...")
    
    if not os.path.exists(service_account_path):
        print(f"   ❌ File not found: {service_account_path}")
        print("\n📝 To fix this:")
        print("   1. Go to Firebase Console → Project Settings → Service accounts")
        print("   2. Click 'Generate new private key'")
        print("   3. Download and save as 'firebase-service-account.json'")
        print("   4. Place it in your project folder")
        return False
    else:
        print(f"   ✅ Service account file found: {service_account_path}")
    
    # Test Firebase initialization
    print("\n3. Testing Firebase initialization...")
    
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        # Check if already initialized
        try:
            app = firebase_admin.get_app()
            print("   ℹ️  Firebase already initialized")
        except ValueError:
            # Initialize Firebase
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred, {
                'projectId': project_id
            })
            print("   ✅ Firebase initialized successfully")
        
        # Test Firestore connection
        print("\n4. Testing Firestore connection...")
        db = firestore.client()
        
        # Try to write a test document
        test_ref = db.collection('_test').document('connection_test')
        test_ref.set({
            'timestamp': datetime.utcnow(),
            'status': 'connected',
            'test': True
        })
        
        # Try to read it back
        doc = test_ref.get()
        if doc.exists:
            print("   ✅ Write/Read test successful")
            
            # Clean up test document
            test_ref.delete()
            print("   ✅ Test document cleaned up")
            
            return True
        else:
            print("   ❌ Could not read test document")
            return False
            
    except Exception as e:
        print(f"   ❌ Firebase error: {e}")
        print(f"\n🔍 Error details: {type(e).__name__}")
        
        if "DefaultCredentialsError" in str(e):
            print("\n💡 This usually means:")
            print("   - Service account file is missing or invalid")
            print("   - Incorrect file path in .env")
            print("   - File permissions issue")
            
        elif "Permission denied" in str(e):
            print("\n💡 This usually means:")
            print("   - Service account doesn't have proper permissions")
            print("   - Firestore rules are too restrictive")
            
        elif "Project not found" in str(e):
            print("\n💡 This usually means:")
            print("   - FIREBASE_PROJECT_ID is incorrect")
            print("   - Project doesn't exist or was deleted")
            
        return False

def test_database_class():
    """Test the Database class"""
    
    print("\n" + "=" * 40)
    print("🗄️  Testing Database Class")
    print("=" * 40)
    
    try:
        # Import your database class
        from database import Database
        
        print("1. Creating Database instance...")
        db = Database()
        print("   ✅ Database instance created")
        
        print("\n2. Testing user operations...")
        
        # Test creating a user
        test_user_id = 999999999  # Test user ID
        success = db.create_user(test_user_id, "testuser", "Test User")
        print(f"   ├── Create user: {'✅ Success' if success else '❌ Failed'}")
        
        if success:
            # Test getting the user
            user_data = db.get_user(test_user_id)
            print(f"   ├── Get user: {'✅ Success' if user_data else '❌ Failed'}")
            
            if user_data:
                print(f"   │   └── User: {user_data.get('first_name')} (Step {user_data.get('current_step')})")
            
            # Test updating user step
            step_success = db.update_user_step(test_user_id, 1, True)
            print(f"   ├── Update step: {'✅ Success' if step_success else '❌ Failed'}")
            
            # Test saving social username
            social_success = db.save_social_username(test_user_id, 'twitter', 'testuser123')
            print(f"   ├── Save social: {'✅ Success' if social_success else '❌ Failed'}")
            
            # Test saving BEP20 address
            bep20_success = db.save_bep20_address(test_user_id, '0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52')
            print(f"   ├── Save BEP20: {'✅ Success' if bep20_success else '❌ Failed'}")
            
            # Get final user data
            final_user = db.get_user(test_user_id)
            if final_user:
                print(f"   └── Final check: ✅ User at step {final_user.get('current_step')}")
            
            # Clean up test user
            try:
                db.users_collection.document(str(test_user_id)).delete()
                print("   🧹 Test user cleaned up")
            except:
                pass
        
        print("\n✅ Database class test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Database class error: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting Firebase Connection Tests...\n")
    
    # Test Firebase connection
    firebase_ok = test_firebase_connection()
    
    # Test Database class if Firebase is working
    if firebase_ok:
        database_ok = test_database_class()
        
        if firebase_ok and database_ok:
            print("\n" + "=" * 50)
            print("🎉 ALL TESTS PASSED!")
            print("✅ Your Firebase setup is working correctly!")
            print("🚀 You can now run: python main.py")
            print("=" * 50)
        else:
            print("\n❌ Some tests failed. Please fix the issues above.")
    else:
        print("\n❌ Firebase connection failed. Please fix the issues above.")
    
    input("\nPress Enter to exit...")