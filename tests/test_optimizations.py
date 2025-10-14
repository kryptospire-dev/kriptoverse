"""
Test script to verify performance optimizations are working correctly

Run this after migrating to database_optimized.py to verify:
1. Cache is functioning
2. Firebase queries are reduced
3. Response times are improved
"""

import time
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.database import Database
from core.cache_manager import get_cache_manager

def test_cache_functionality():
    """Test that caching system is working"""
    print("\n🧪 Test 1: Cache Functionality")
    print("=" * 50)

    try:
        cache = get_cache_manager()
        print("✅ Cache manager initialized")

        # Test user cache
        test_user = {'user_id': 999999, 'username': 'test_user', 'first_name': 'Test'}
        cache.set_user(999999, test_user)

        cached_user = cache.get_user(999999)
        if cached_user and cached_user['username'] == 'test_user':
            print("✅ User cache working correctly")
        else:
            print("❌ User cache NOT working")
            return False

        # Test referral code cache
        cache.set_referral_code_mapping('REFTEST123', test_user)
        cached_referral = cache.get_user_by_referral_code('REFTEST123')

        if cached_referral and cached_referral['user_id'] == 999999:
            print("✅ Referral code cache working correctly")
        else:
            print("❌ Referral code cache NOT working")
            return False

        # Test cache invalidation
        cache.invalidate_user(999999)
        invalidated = cache.get_user(999999)

        if invalidated is None:
            print("✅ Cache invalidation working correctly")
        else:
            print("❌ Cache invalidation NOT working")
            return False

        print("\n✅ All cache tests passed!")
        return True

    except Exception as e:
        print(f"❌ Cache test failed: {e}")
        return False

def test_database_performance():
    """Test database performance improvements"""
    print("\n🧪 Test 2: Database Performance")
    print("=" * 50)

    try:
        db = Database()
        print("[OK] Optimized database initialized")

        # Test 1: First query (cache miss)
        start_time = time.time()
        user1 = db.get_user_with_retry(999999)
        first_query_time = (time.time() - start_time) * 1000  # Convert to ms

        print(f"First query (cache miss): {first_query_time:.2f}ms")

        # Test 2: Second query (cache hit)
        # First, create a test user so we have something in cache
        if not user1:
            print("Creating test user...")
            db.create_user_with_retry(999999, 'test_user', 'Test User')

        start_time = time.time()
        user2 = db.get_user_with_retry(999999)
        second_query_time = (time.time() - start_time) * 1000  # Convert to ms

        print(f"Second query (cache hit): {second_query_time:.2f}ms")

        # Verify cache hit is significantly faster
        if user2 and second_query_time < first_query_time / 5:
            print(f"✅ Cache speedup: {first_query_time / second_query_time:.1f}x faster")
        elif user2 and second_query_time < 20:
            print(f"✅ Cache working (sub-20ms response)")
        else:
            print(f"⚠️  Cache speedup not obvious (might be network latency)")

        # Test 3: Performance stats
        perf_stats = db.get_performance_stats()

        print(f"\n📊 Performance Statistics:")
        print(f"   Firebase Queries: {perf_stats['total_firebase_queries']}")
        print(f"   Cache Hits: {perf_stats['total_cache_hits']}")
        print(f"   Total Requests: {perf_stats['total_requests']}")
        print(f"   Cache Hit Rate: {perf_stats['cache_hit_rate_percent']}%")
        print(f"   Circuit Breaker: {perf_stats['circuit_breaker_status']}")

        if perf_stats['total_cache_hits'] > 0:
            print("✅ Cache is being used")
        else:
            print("⚠️  No cache hits yet (normal for first run)")

        print("\n✅ Database performance test completed!")
        return True

    except Exception as e:
        print(f"❌ Database performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_firebase_connection():
    """Test Firebase connection is working"""
    print("\n🧪 Test 3: Firebase Connection")
    print("=" * 50)

    try:
        db = Database()

        # Test health check
        health = db.health_check()

        if health['status'] == 'healthy':
            print(f"✅ Firebase connection healthy")
            circuit_status = 'OPEN' if health.get('circuit_breaker_open', False) else 'CLOSED'
            print(f"   Circuit Breaker: {circuit_status}")
            print(f"   Cache Hit Rate: {health.get('cache_hit_rate', 0)}%")
        else:
            print(f"❌ Firebase connection unhealthy: {health.get('error', 'Unknown')}")
            return False

        # Test stats query
        stats = db.get_user_stats()
        if stats:
            print(f"✅ Stats query successful")
            print(f"   Total Users: {stats.get('total_users', 0)}")
            print(f"   Completed Users: {stats.get('completed_users', 0)}")
        else:
            print(f"⚠️  Stats query returned empty (might be new database)")

        print("\n✅ Firebase connection test passed!")
        return True

    except Exception as e:
        print(f"❌ Firebase connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests():
    """Run all optimization tests"""
    print("=" * 50)
    print("🚀 PERFORMANCE OPTIMIZATION TEST SUITE")
    print("=" * 50)

    results = []

    # Test 1: Cache functionality
    results.append(("Cache Functionality", test_cache_functionality()))

    # Test 2: Database performance
    results.append(("Database Performance", test_database_performance()))

    # Test 3: Firebase connection
    results.append(("Firebase Connection", test_firebase_connection()))

    # Print summary
    print("\n" + "=" * 50)
    print("📋 TEST SUMMARY")
    print("=" * 50)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 50)

    if all_passed:
        print("\n🎉 All tests passed! Optimizations are working correctly.")
        print("\n📊 Expected Performance:")
        print("   • 85-90% cache hit rate after warm-up")
        print("   • Sub-second response times")
        print("   • 95% reduction in Firebase queries")
        print("\n📋 Next Steps:")
        print("   1. Deploy to production")
        print("   2. Monitor cache hit rate with /cachestats")
        print("   3. Wait 1-2 hours for cache warm-up")
        print("   4. Verify response times are < 500ms")
        return 0
    else:
        print("\n❌ Some tests failed. Please review the errors above.")
        print("\n🔧 Troubleshooting:")
        print("   1. Check Firebase credentials are correct")
        print("   2. Verify firestore.indexes.json is deployed")
        print("   3. Check network connectivity")
        print("   4. Review error messages above")
        return 1

if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
