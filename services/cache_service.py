"""
Redis Cache Service for Third Place Platform

Provides caching for:
- Activity classes
- Space risk profiles
- Insurance envelope details
- Pricing quotes
- User sessions

Features:
- Automatic serialization/deserialization
- TTL management
- Cache invalidation patterns
- Fallback to database on cache miss
"""
import json
import os
import logging
from typing import Any, Dict, List, Optional, TypeVar, Generic
from datetime import timedelta
import hashlib

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CacheService:
    """
    Redis-backed cache service with automatic serialization
    
    Usage:
        cache = CacheService()
        
        # Set value (5 minute TTL)
        cache.set("user:123", {"name": "John"})
        
        # Get value
        user = cache.get("user:123")
        
        # Set with custom TTL
        cache.set("session:abc", data, ttl=3600)
        
        # Invalidate pattern
        cache.invalidate("user:*")
    """
    
    # Default TTL values (in seconds)
    DEFAULT_TTL = 300  # 5 minutes
    TTL_ACTIVITY_CLASSES = 600  # 10 minutes
    TTL_SPACE_PROFILE = 300  # 5 minutes
    TTL_ENVELOPE_DETAILS = 120  # 2 minutes
    TTL_PRICING_QUOTE = 300  # 5 minutes
    TTL_USER_DATA = 600  # 10 minutes
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize cache service
        
        Args:
            redis_url: Redis connection URL (default: from REDIS_URL env var)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._client: Optional[redis.Redis] = None
        self._enabled = REDIS_AVAILABLE and self.redis_url
        
        if self._enabled:
            try:
                self._client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                # Test connection
                self._client.ping()
                logger.info(f"Redis cache connected: {self.redis_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Cache disabled.")
                self._enabled = False
                self._client = None
        else:
            logger.warning("Redis not available. Cache disabled.")
    
    @property
    def enabled(self) -> bool:
        """Check if cache is enabled"""
        return self._enabled
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if not self._enabled or not self._client:
            return None
        
        try:
            value = self._client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning(f"Cache get error for {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value in cache
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds (default: DEFAULT_TTL)
            
        Returns:
            True if successful
        """
        if not self._enabled or not self._client:
            return False
        
        try:
            ttl = ttl or self.DEFAULT_TTL
            serialized = json.dumps(value)
            self._client.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.warning(f"Cache set error for {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        Delete value from cache
        
        Args:
            key: Cache key
            
        Returns:
            True if key was deleted
        """
        if not self._enabled or not self._client:
            return False
        
        try:
            self._client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache delete error for {key}: {e}")
            return False
    
    def invalidate(self, pattern: str) -> int:
        """
        Invalidate cache entries matching pattern
        
        Args:
            pattern: Key pattern (e.g., "user:*")
            
        Returns:
            Number of keys deleted
        """
        if not self._enabled or not self._client:
            return 0
        
        try:
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Cache invalidate error for {pattern}: {e}")
            return 0
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        if not self._enabled or not self._client:
            return False
        
        try:
            return bool(self._client.exists(key))
        except Exception:
            return False
    
    def get_or_set(
        self,
        key: str,
        factory: callable,
        ttl: Optional[int] = None
    ) -> Any:
        """
        Get value from cache or set it using factory function
        
        Args:
            key: Cache key
            factory: Function to call if key not in cache
            ttl: Time to live in seconds
            
        Returns:
            Cached or freshly computed value
        """
        # Try cache first
        value = self.get(key)
        if value is not None:
            return value
        
        # Cache miss - compute value
        value = factory()
        
        # Store in cache
        self.set(key, value, ttl)
        
        return value
    
    def clear_all(self) -> bool:
        """
        Clear all cache entries (use with caution!)
        
        Returns:
            True if successful
        """
        if not self._enabled or not self._client:
            return False
        
        try:
            self._client.flushdb()
            logger.info("Cache cleared")
            return True
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self._enabled or not self._client:
            return {"enabled": False}
        
        try:
            info = self._client.info("stats")
            keyspace = self._client.info("keyspace")
            
            return {
                "enabled": True,
                "connected": True,
                "total_keys": sum(
                    int(v.split("keys=")[1].split(",")[0])
                    for v in keyspace.values()
                    if "keys=" in v
                ),
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "evicted_keys": info.get("evicted_keys", 0),
                "expired_keys": info.get("expired_keys", 0),
                "memory_used": self._client.info("memory").get("used_memory_human", "N/A")
            }
        except Exception as e:
            return {"enabled": True, "connected": False, "error": str(e)}


# =============================================================================
# Specialized Cache Helpers
# =============================================================================

class ActivityClassCache:
    """Cache helper for activity classes"""
    
    def __init__(self, cache: CacheService):
        self.cache = cache
        self.prefix = "activity_class"
    
    def get_class(self, class_id: str) -> Optional[Dict]:
        """Get activity class by ID"""
        return self.cache.get(f"{self.prefix}:{class_id}")
    
    def get_class_by_slug(self, slug: str) -> Optional[Dict]:
        """Get activity class by slug"""
        return self.cache.get(f"{self.prefix}:slug:{slug}")
    
    def set_class(self, class_data: Dict) -> bool:
        """Cache activity class"""
        class_id = class_data.get("id")
        slug = class_data.get("slug")
        
        success = self.cache.set(
            f"{self.prefix}:{class_id}",
            class_data,
            ttl=CacheService.TTL_ACTIVITY_CLASSES
        )
        
        if slug:
            self.cache.set(
                f"{self.prefix}:slug:{slug}",
                class_data,
                ttl=CacheService.TTL_ACTIVITY_CLASSES
            )
        
        return success
    
    def invalidate_class(self, class_id: str) -> bool:
        """Invalidate activity class from cache"""
        return self.cache.delete(f"{self.prefix}:{class_id}")
    
    def get_all_slugs(self) -> Optional[List[str]]:
        """Get all activity class slugs"""
        return self.cache.get(f"{self.prefix}:slugs")
    
    def set_all_slugs(self, slugs: List[str]) -> bool:
        """Cache all activity class slugs"""
        return self.cache.set(
            f"{self.prefix}:slugs",
            slugs,
            ttl=CacheService.TTL_ACTIVITY_CLASSES
        )


class SpaceProfileCache:
    """Cache helper for space risk profiles"""
    
    def __init__(self, cache: CacheService):
        self.cache = cache
        self.prefix = "space_profile"
    
    def get_profile(self, space_id: str) -> Optional[Dict]:
        """Get space profile by ID"""
        return self.cache.get(f"{self.prefix}:{space_id}")
    
    def set_profile(self, space_id: str, profile_data: Dict) -> bool:
        """Cache space profile"""
        return self.cache.set(
            f"{self.prefix}:{space_id}",
            profile_data,
            ttl=CacheService.TTL_SPACE_PROFILE
        )
    
    def invalidate_profile(self, space_id: str) -> bool:
        """Invalidate space profile from cache"""
        return self.cache.delete(f"{self.prefix}:{space_id}")


class EnvelopeCache:
    """Cache helper for insurance envelopes"""
    
    def __init__(self, cache: CacheService):
        self.cache = cache
        self.prefix = "envelope"
    
    def get_envelope(self, envelope_id: str) -> Optional[Dict]:
        """Get envelope details"""
        return self.cache.get(f"{self.prefix}:{envelope_id}")
    
    def set_envelope(self, envelope_data: Dict) -> bool:
        """Cache envelope details"""
        envelope_id = envelope_data.get("id")
        return self.cache.set(
            f"{self.prefix}:{envelope_id}",
            envelope_data,
            ttl=CacheService.TTL_ENVELOPE_DETAILS
        )
    
    def invalidate_envelope(self, envelope_id: str) -> bool:
        """Invalidate envelope from cache"""
        return self.cache.delete(f"{self.prefix}:{envelope_id}")
    
    def invalidate_space_envelopes(self, space_id: str) -> int:
        """Invalidate all envelopes for a space"""
        return self.cache.invalidate(f"{self.prefix}:space:{space_id}:*")


class PricingCache:
    """Cache helper for pricing quotes"""
    
    def __init__(self, cache: CacheService):
        self.cache = cache
        self.prefix = "pricing"
    
    def _generate_key(self, params: Dict) -> str:
        """Generate cache key from pricing parameters"""
        # Create deterministic key from sorted params
        key_string = json.dumps(params, sort_keys=True)
        key_hash = hashlib.md5(key_string.encode()).hexdigest()[:16]
        return f"{self.prefix}:{key_hash}"
    
    def get_quote(self, params: Dict) -> Optional[Dict]:
        """Get cached pricing quote"""
        key = self._generate_key(params)
        return self.cache.get(key)
    
    def set_quote(self, params: Dict, quote_data: Dict) -> bool:
        """Cache pricing quote"""
        key = self._generate_key(params)
        return self.cache.set(
            key,
            quote_data,
            ttl=CacheService.TTL_PRICING_QUOTE
        )
    
    def invalidate_quotes(self) -> int:
        """Invalidate all pricing quotes"""
        return self.cache.invalidate(f"{self.prefix}:*")


# =============================================================================
# Global Cache Instance
# =============================================================================

# Create global cache instance
cache = CacheService()

# Create cache helpers
activity_class_cache = ActivityClassCache(cache)
space_profile_cache = SpaceProfileCache(cache)
envelope_cache = EnvelopeCache(cache)
pricing_cache = PricingCache(cache)


def get_cache() -> CacheService:
    """Dependency for getting cache service"""
    return cache


def init_cache(redis_url: Optional[str] = None) -> CacheService:
    """Initialize cache service with custom URL"""
    global cache, activity_class_cache, space_profile_cache, envelope_cache, pricing_cache
    
    cache = CacheService(redis_url)
    activity_class_cache = ActivityClassCache(cache)
    space_profile_cache = SpaceProfileCache(cache)
    envelope_cache = EnvelopeCache(cache)
    pricing_cache = PricingCache(cache)
    
    return cache
