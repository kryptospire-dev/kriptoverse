"""
High-performance caching layer for Telegram bot
Reduces Firebase queries by caching frequently accessed data
"""

import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from cachetools import TTLCache, LRUCache
import hashlib

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Multi-tier caching system for bot performance optimization
    - User data cache (TTL: 5 minutes, max 10,000 users)
    - Referral code lookup cache (TTL: 10 minutes, max 5,000 codes)
    - Stats cache (TTL: 2 minutes, max 100 entries)
    """

    def __init__(self):
        # User data cache - most accessed data
        # TTL=300 seconds (5 min) to keep data fresh
        # maxsize=10000 to cache up to 10K active users in memory
        self.user_cache = TTLCache(maxsize=10000, ttl=300)

        # Referral code to user_id mapping cache
        # TTL=600 seconds (10 min) - referral codes don't change
        self.referral_code_cache = TTLCache(maxsize=5000, ttl=600)

        # Stats cache - least frequently changing
        # TTL=120 seconds (2 min)
        self.stats_cache = TTLCache(maxsize=100, ttl=120)

        # LRU cache for validation results (doesn't expire by time)
        self.validation_cache = LRUCache(maxsize=1000)

        # Cache statistics
        self.stats = {
            'user_hits': 0,
            'user_misses': 0,
            'referral_hits': 0,
            'referral_misses': 0,
            'stats_hits': 0,
            'stats_misses': 0
        }

        logger.info("✅ Cache Manager initialized with multi-tier caching")

    # ========== User Cache Operations ==========

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user from cache"""
        key = f"user:{user_id}"
        user_data = self.user_cache.get(key)

        if user_data:
            self.stats['user_hits'] += 1
            logger.debug(f"Cache HIT: user {user_id}")
        else:
            self.stats['user_misses'] += 1
            logger.debug(f"Cache MISS: user {user_id}")

        return user_data

    def set_user(self, user_id: int, user_data: Dict[str, Any]):
        """Store user in cache"""
        key = f"user:{user_id}"
        # Create a copy to prevent external modifications
        self.user_cache[key] = user_data.copy()
        logger.debug(f"Cache SET: user {user_id}")

    def invalidate_user(self, user_id: int):
        """Remove user from cache (after updates)"""
        key = f"user:{user_id}"
        if key in self.user_cache:
            del self.user_cache[key]
            logger.debug(f"Cache INVALIDATE: user {user_id}")

    def update_user_field(self, user_id: int, field_path: str, value: Any):
        """
        Update specific field in cached user data
        Avoids full cache invalidation for partial updates
        """
        key = f"user:{user_id}"
        user_data = self.user_cache.get(key)

        if user_data:
            # Support nested field updates (e.g., "social_usernames.twitter")
            parts = field_path.split('.')
            current = user_data

            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            current[parts[-1]] = value
            current['updated_at'] = datetime.now()

            self.user_cache[key] = user_data
            logger.debug(f"Cache UPDATE: user {user_id}, field {field_path}")

    # ========== Referral Code Cache Operations ==========

    def get_user_by_referral_code(self, referral_code: str) -> Optional[Dict[str, Any]]:
        """Get user by referral code from cache"""
        key = f"referral:{referral_code}"
        user_data = self.referral_code_cache.get(key)

        if user_data:
            self.stats['referral_hits'] += 1
            logger.debug(f"Cache HIT: referral {referral_code}")
        else:
            self.stats['referral_misses'] += 1
            logger.debug(f"Cache MISS: referral {referral_code}")

        return user_data

    def set_referral_code_mapping(self, referral_code: str, user_data: Dict[str, Any]):
        """Store referral code to user mapping"""
        key = f"referral:{referral_code}"
        self.referral_code_cache[key] = user_data.copy()
        logger.debug(f"Cache SET: referral {referral_code}")

    # ========== Stats Cache Operations ==========

    def get_stats(self, stats_key: str = 'main') -> Optional[Dict[str, Any]]:
        """Get bot statistics from cache"""
        key = f"stats:{stats_key}"
        stats_data = self.stats_cache.get(key)

        if stats_data:
            self.stats['stats_hits'] += 1
            logger.debug(f"Cache HIT: stats {stats_key}")
        else:
            self.stats['stats_misses'] += 1
            logger.debug(f"Cache MISS: stats {stats_key}")

        return stats_data

    def set_stats(self, stats_data: Dict[str, Any], stats_key: str = 'main'):
        """Store bot statistics in cache"""
        key = f"stats:{stats_key}"
        self.stats_cache[key] = stats_data.copy()
        logger.debug(f"Cache SET: stats {stats_key}")

    def invalidate_stats(self, stats_key: str = 'main'):
        """Invalidate stats cache (after user creation/completion)"""
        key = f"stats:{stats_key}"
        if key in self.stats_cache:
            del self.stats_cache[key]
            logger.debug(f"Cache INVALIDATE: stats {stats_key}")

    # ========== Validation Cache Operations ==========

    def get_validation(self, validation_type: str, value: str) -> Optional[bool]:
        """
        Get validation result from cache
        Useful for repeated validation of same values (e.g., same BEP20 address)
        """
        # Hash the value to create a fixed-size key
        value_hash = hashlib.md5(f"{validation_type}:{value}".encode()).hexdigest()
        key = f"validation:{value_hash}"
        return self.validation_cache.get(key)

    def set_validation(self, validation_type: str, value: str, is_valid: bool):
        """Store validation result"""
        value_hash = hashlib.md5(f"{validation_type}:{value}".encode()).hexdigest()
        key = f"validation:{value_hash}"
        self.validation_cache[key] = is_valid

    # ========== Cache Management ==========

    def clear_all(self):
        """Clear all caches (use cautiously)"""
        self.user_cache.clear()
        self.referral_code_cache.clear()
        self.stats_cache.clear()
        self.validation_cache.clear()
        logger.warning("All caches cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        total_requests = (
            self.stats['user_hits'] + self.stats['user_misses'] +
            self.stats['referral_hits'] + self.stats['referral_misses'] +
            self.stats['stats_hits'] + self.stats['stats_misses']
        )

        total_hits = (
            self.stats['user_hits'] +
            self.stats['referral_hits'] +
            self.stats['stats_hits']
        )

        hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'user_cache_size': len(self.user_cache),
            'referral_cache_size': len(self.referral_code_cache),
            'stats_cache_size': len(self.stats_cache),
            'validation_cache_size': len(self.validation_cache),
            'user_hits': self.stats['user_hits'],
            'user_misses': self.stats['user_misses'],
            'referral_hits': self.stats['referral_hits'],
            'referral_misses': self.stats['referral_misses'],
            'stats_hits': self.stats['stats_hits'],
            'stats_misses': self.stats['stats_misses'],
            'total_requests': total_requests,
            'total_hits': total_hits,
            'hit_rate_percent': round(hit_rate, 2)
        }

    def log_stats(self):
        """Log current cache statistics"""
        stats = self.get_cache_stats()
        logger.info(f"""
📊 Cache Statistics:
   User Cache: {stats['user_cache_size']}/10000 entries
   Referral Cache: {stats['referral_cache_size']}/5000 entries
   Stats Cache: {stats['stats_cache_size']}/100 entries
   Hit Rate: {stats['hit_rate_percent']}%
   Total Requests: {stats['total_requests']}
   Total Hits: {stats['total_hits']}
        """)


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None

def get_cache_manager() -> CacheManager:
    """Get or create global cache manager instance"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
