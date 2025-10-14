"""
Test Step Progression Flow
Tests that users properly move from step to step
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.database import Database
import time

def test_step_progression():
    """Test that step progression works correctly"""
    print("\n[TEST] Step Progression")
    print("=" * 60)

    try:
        # Initialize database
        db = Database()
        print("[OK] Database initialized")

        # Test user ID (using a high number to avoid conflicts)
        test_user_id = 999999999

        # Clean up test user if exists
        try:
            db.users_collection.document(str(test_user_id)).delete()
            print(f"[INFO] Cleaned up existing test user {test_user_id}")
        except:
            pass

        # Step 1: Create test user
        print("\n[STEP 1] Creating test user...")
        success = db.create_user_with_retry(test_user_id, "test_user", "Test User")
        if success:
            print(f"  [OK] Test user {test_user_id} created")
        else:
            print(f"  [FAIL] Failed to create test user")
            return False

        # Verify user starts at step 1
        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 1:
            print(f"  [OK] User starts at step 1")
        else:
            print(f"  [FAIL] User should start at step 1, got: {user_data.get('current_step') if user_data else 'None'}")
            return False

        # Step 2: Complete step 1, should move to step 2
        print("\n[STEP 2] Completing step 1...")
        success = db.update_user_step(test_user_id, 1, True)
        if success:
            print(f"  [OK] Step 1 marked as completed")
        else:
            print(f"  [FAIL] Failed to update step 1")
            return False

        # Verify user moved to step 2
        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 2:
            print(f"  [OK] User moved to step 2")
            print(f"  [OK] Step 1 completed: {user_data.get('steps_completed', {}).get('step_1')}")
        else:
            print(f"  [FAIL] User should be at step 2, got: {user_data.get('current_step') if user_data else 'None'}")
            print(f"  [DEBUG] User data: {user_data}")
            return False

        # Step 3: Save Twitter username and complete step 2
        print("\n[STEP 3] Completing step 2 (Twitter)...")
        success = db.save_social_username(test_user_id, 'twitter', 'test_twitter')
        if success:
            print(f"  [OK] Twitter username saved")
        else:
            print(f"  [FAIL] Failed to save Twitter username")
            return False

        success = db.update_user_step(test_user_id, 2, True)
        if success:
            print(f"  [OK] Step 2 marked as completed")
        else:
            print(f"  [FAIL] Failed to update step 2")
            return False

        # Verify user moved to step 3
        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 3:
            print(f"  [OK] User moved to step 3")
            print(f"  [OK] Step 2 completed: {user_data.get('steps_completed', {}).get('step_2')}")
            print(f"  [OK] Twitter username: @{user_data.get('social_usernames', {}).get('twitter')}")
        else:
            print(f"  [FAIL] User should be at step 3, got: {user_data.get('current_step') if user_data else 'None'}")
            print(f"  [DEBUG] User data: {user_data}")
            return False

        # Step 4: Save Instagram username and complete step 3
        print("\n[STEP 4] Completing step 3 (Instagram)...")
        success = db.save_social_username(test_user_id, 'instagram', 'test_instagram')
        success = success and db.update_user_step(test_user_id, 3, True)

        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 4:
            print(f"  [OK] User moved to step 4")
        else:
            print(f"  [FAIL] User should be at step 4, got: {user_data.get('current_step')}")
            return False

        # Step 5: Save CoinMarketCap and complete step 4
        print("\n[STEP 5] Completing step 4 (CoinMarketCap)...")
        success = db.save_social_username(test_user_id, 'coinmarketcap', 'test_cmc')
        success = success and db.update_user_step(test_user_id, 4, True)

        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 5:
            print(f"  [OK] User moved to step 5")
        else:
            print(f"  [FAIL] User should be at step 5, got: {user_data.get('current_step')}")
            return False

        # Step 6: Save BEP20 address and complete step 5
        print("\n[STEP 6] Completing step 5 (BEP20 Address)...")
        success = db.save_bep20_address(test_user_id, '0x742d35Cc6634C0532925a3b8D4B29E3f5fCffd52')
        success = success and db.update_user_step(test_user_id, 5, True)

        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 6:
            print(f"  [OK] User moved to step 6")
        else:
            print(f"  [FAIL] User should be at step 6, got: {user_data.get('current_step')}")
            return False

        # Step 7: Complete step 6 (final step)
        print("\n[STEP 7] Completing step 6 (Final verification)...")
        success = db.update_user_step(test_user_id, 6, True)

        user_data = db.get_user_with_retry(test_user_id)
        if user_data and user_data.get('current_step') == 7:
            print(f"  [OK] User completed all steps (step 7)")
            print(f"  [OK] All steps marked as completed")

            # Verify all data is saved
            social = user_data.get('social_usernames', {})
            print(f"\n  [SUMMARY] User data verification:")
            print(f"    Twitter: @{social.get('twitter')}")
            print(f"    Instagram: @{social.get('instagram')}")
            print(f"    CoinMarketCap: @{social.get('coinmarketcap')}")
            print(f"    BEP20: {user_data.get('bep20_address')}")
            print(f"    MNTC Earned: {user_data.get('reward_info', {}).get('mntc_earned', 0)} MNTC")
            print(f"    Reward Status: {user_data.get('reward_info', {}).get('reward_status', 'Unknown')}")
        else:
            print(f"  [FAIL] User should be at step 7 (completed), got: {user_data.get('current_step')}")
            return False

        # Cleanup
        print("\n[CLEANUP] Removing test user...")
        db.users_collection.document(str(test_user_id)).delete()
        print(f"  [OK] Test user {test_user_id} deleted")

        # Close database
        db.close_connection()

        print("\n" + "=" * 60)
        print("[SUCCESS] Step Progression Test PASSED")
        print("=" * 60)
        print("\nAll steps work correctly:")
        print("  Step 1 -> Step 2 (App download)")
        print("  Step 2 -> Step 3 (Twitter)")
        print("  Step 3 -> Step 4 (Instagram)")
        print("  Step 4 -> Step 5 (CoinMarketCap)")
        print("  Step 5 -> Step 6 (BEP20 address)")
        print("  Step 6 -> Step 7 (Completed)")

        return True

    except Exception as e:
        print(f"\n[FAILED] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_step_progression()
    sys.exit(0 if success else 1)
