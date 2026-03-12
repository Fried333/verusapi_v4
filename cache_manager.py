#!/usr/bin/env python3
"""
Unified Cache Manager for Verus Ticker API
Implements intelligent caching to reduce RPC calls and improve performance
"""

import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CacheManager:
    """
    Unified cache manager that handles data caching for all API endpoints
    
    Features:
    - Single data pull shared across all cached endpoints
    - Configurable cache TTL (time-to-live)
    - Thread-safe operations
    - Automatic cache refresh
    - Cache invalidation strategies
    """
    
    def __init__(self, cache_ttl_seconds: int = 60, enable_background_refresh: bool = True):  # 1 minute default
        """
        Initialize the cache manager
        
        Args:
            cache_ttl_seconds: Cache time-to-live in seconds (default: 1 minute)
            enable_background_refresh: Enable proactive background refresh (default: True)
        """
        self.cache_ttl = cache_ttl_seconds
        self.cache_data = {}
        self.cache_timestamp = None
        self.cache_block_height = None
        self.cache_lock = threading.RLock()  # Reentrant lock for thread safety
        self.is_refreshing = False
        self.enable_background_refresh = enable_background_refresh
        self.background_timer = None
        self.is_shutdown = False
        
        # Verussupply pause mechanism
        self.verussupply_pause_until = None
        self.verussupply_pause_duration = 120  # 2 minutes in seconds
        
        logger.info(f"🚀 Cache Manager initialized with {cache_ttl_seconds}s TTL")
        
        # Start background refresh if enabled
        if self.enable_background_refresh:
            # Trigger immediate initial refresh
            self._trigger_initial_refresh()
            self._start_background_refresh()
            logger.info(f"⚡ Proactive background refresh enabled (every {cache_ttl_seconds}s)")
    
    def is_cache_valid(self) -> bool:
        """
        Check if the current cache is still valid
        
        Returns:
            bool: True if cache is valid, False if expired or empty
        """
        with self.cache_lock:
            if not self.cache_data or not self.cache_timestamp:
                return False
            
            # Check if cache has expired
            cache_age = time.time() - self.cache_timestamp
            is_valid = cache_age < self.cache_ttl
            
            if not is_valid:
                logger.info(f"📅 Cache expired (age: {cache_age:.1f}s, TTL: {self.cache_ttl}s)")
            
            return is_valid
    
    def get_cached_data(self) -> Optional[Dict]:
        """
        Get cached data if valid, otherwise return None
        
        Returns:
            Dict or None: Cached data if valid, None if expired or empty
        """
        with self.cache_lock:
            if self.is_cache_valid():
                cache_age = time.time() - self.cache_timestamp
                logger.info(f"✅ Serving cached data (age: {cache_age:.1f}s, block: {self.cache_block_height})")
                return self.cache_data.copy()  # Return a copy to prevent modification
            
            return None
    
    def get_cached_data_only(self) -> Optional[Dict]:
        """
        Get cached data ONLY if it exists, never trigger RPC calls
        Used by cached endpoints to avoid triggering data fetches
        
        Returns:
            Dict or None: Cached data if exists (even if expired), None if no cache
        """
        with self.cache_lock:
            if self.cache_data and self.cache_timestamp:
                cache_age = time.time() - self.cache_timestamp
                logger.info(f"📦 Serving cached data (age: {cache_age:.1f}s, block: {self.cache_block_height}) - NO RPC CALLS")
                return self.cache_data.copy()
            
            logger.warning("⚠️ No cached data available for cached endpoint")
            return None
    
    def set_cached_data(self, data: Dict, block_height: int) -> None:
        """
        Store data in cache with timestamp and block height
        
        Args:
            data: Data to cache
            block_height: Current block height when data was fetched
        """
        with self.cache_lock:
            self.cache_data = data.copy()  # Store a copy to prevent external modification
            self.cache_timestamp = time.time()
            self.cache_block_height = block_height
            self.is_refreshing = False
            
            logger.info(f"💾 Data cached successfully (block: {block_height}, pairs: {len(data.get('pairs', []))})")
    
    def invalidate_cache(self) -> None:
        """
        Manually invalidate the cache (force refresh on next request)
        """
        with self.cache_lock:
            self.cache_data = {}
            self.cache_timestamp = None
            self.cache_block_height = None
            self.is_refreshing = False
            
            logger.info("🗑️ Cache manually invalidated")
    
    def get_cache_info(self) -> Dict:
        """
        Get information about the current cache state
        
        Returns:
            Dict: Cache information including age, validity, block height
        """
        with self.cache_lock:
            if not self.cache_timestamp:
                return {
                    "cached": False,
                    "age_seconds": 0,
                    "ttl_seconds": self.cache_ttl,
                    "block_height": None,
                    "pairs_count": 0,
                    "valid": False
                }
            
            cache_age = time.time() - self.cache_timestamp
            is_valid = self.is_cache_valid()
            
            return {
                "cached": True,
                "age_seconds": round(cache_age, 1),
                "ttl_seconds": self.cache_ttl,
                "block_height": self.cache_block_height,
                "pairs_count": len(self.cache_data.get('pairs', [])),
                "valid": is_valid,
                "expires_in": max(0, self.cache_ttl - cache_age),
                "cached_at": datetime.fromtimestamp(self.cache_timestamp).isoformat()
            }
    
    def should_refresh_cache(self) -> bool:
        """
        Determine if cache should be refreshed
        
        Returns:
            bool: True if cache needs refresh, False otherwise
        """
        with self.cache_lock:
            # Don't refresh if already refreshing
            if self.is_refreshing:
                return False
            
            # Refresh if cache is invalid
            return not self.is_cache_valid()
    
    def mark_refreshing(self) -> None:
        """
        Mark cache as currently being refreshed to prevent concurrent refreshes
        """
        with self.cache_lock:
            self.is_refreshing = True
            logger.info("🔄 Cache refresh started")
    
    def get_or_refresh_data(self, refresh_function) -> Dict:
        """
        Get cached data or refresh if needed using the provided function
        
        Args:
            refresh_function: Function to call for data refresh (should return dict with 'pairs' key)
        
        Returns:
            Dict: Either cached data or freshly fetched data
        """
        # Try to get cached data first
        cached_data = self.get_cached_data()
        if cached_data:
            return cached_data
        
        # Need to refresh - check if already refreshing
        if not self.should_refresh_cache():
            # Another thread is refreshing, wait briefly and try cache again
            time.sleep(0.1)
            cached_data = self.get_cached_data()
            if cached_data:
                return cached_data
        
        # Mark as refreshing and fetch new data
        self.mark_refreshing()
        
        try:
            logger.info("🔄 Fetching fresh data from RPC...")
            start_time = time.time()
            
            # Call the refresh function to get new data
            fresh_data = refresh_function()
            
            fetch_time = time.time() - start_time
            logger.info(f"✅ Fresh data fetched in {fetch_time:.2f}s")
            
            # Cache the new data
            if 'error' not in fresh_data:
                block_height = fresh_data.get('block_range', {}).get('current', 0)
                self.set_cached_data(fresh_data, block_height)
                return fresh_data
            else:
                # Error occurred, don't cache but return the error
                self.is_refreshing = False
                return fresh_data
                
        except Exception as e:
            logger.error(f"❌ Error refreshing cache: {e}")
            self.is_refreshing = False
            return {
                'error': f'Cache refresh failed: {str(e)}',
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def _trigger_initial_refresh(self):
        """
        Trigger immediate cache refresh on startup
        """
        def initial_refresh():
            try:
                logger.info("🚀 Triggering initial cache population...")
                from data_integration import extract_all_pairs_data
                
                fresh_data = extract_all_pairs_data()
                
                if fresh_data and 'error' not in fresh_data:
                    block_height = fresh_data.get('block_range', {}).get('current', 0)
                    self.set_cached_data(fresh_data, block_height)
                    logger.info(f"✅ Initial cache population completed (Block: {block_height})")
                else:
                    logger.warning("⚠️ Initial cache population failed")
                    
            except Exception as e:
                logger.error(f"❌ Initial cache population error: {e}")
        
        # Run initial refresh in background thread
        initial_thread = threading.Thread(target=initial_refresh, daemon=True)
        initial_thread.start()

    def pause_refresh_for_verussupply(self):
        """
        Pause background refresh for 3 minutes when verussupply endpoint is called
        """
        self.verussupply_pause_until = time.time() + self.verussupply_pause_duration
        logger.info(f"⏸️  Background refresh paused for {self.verussupply_pause_duration}s due to verussupply call")
    
    def _is_paused_for_verussupply(self) -> bool:
        """
        Check if refresh is currently paused for verussupply
        """
        if self.verussupply_pause_until is None:
            return False
        
        if time.time() < self.verussupply_pause_until:
            return True
        else:
            # Clear the pause
            self.verussupply_pause_until = None
            return False
    
    def _start_background_refresh(self):
        """
        Start the background refresh timer
        """
        if not self.is_shutdown:
            self.background_timer = threading.Timer(self.cache_ttl, self._background_refresh_task)
            self.background_timer.daemon = True  # Dies when main thread dies
            self.background_timer.start()
            logger.info(f"🔄 Background refresh timer started ({self.cache_ttl}s interval)")
    
    def _background_refresh_task(self):
        """
        Background task that refreshes the cache proactively
        """
        try:
            if not self.is_shutdown:
                # Check if paused for verussupply
                if self._is_paused_for_verussupply():
                    remaining = int(self.verussupply_pause_until - time.time())
                    logger.info(f"⏸️  Background refresh skipped - paused for verussupply ({remaining}s remaining)")
                    # Schedule next refresh
                    self._start_background_refresh()
                    return
                
                logger.info("⚡ Proactive cache refresh triggered by background timer")
                
                # Import here to avoid circular imports
                from data_integration import extract_all_pairs_data
                
                # Refresh the cache with fresh data
                fresh_data = extract_all_pairs_data()
                
                if fresh_data and 'error' not in fresh_data:
                    block_height = fresh_data.get('block_range', {}).get('current', 0)
                    self.set_cached_data(fresh_data, block_height)
                    logger.info(f"✅ Proactive refresh completed (Block: {block_height})")
                else:
                    logger.warning("⚠️  Proactive refresh failed - keeping existing cache")
                
                # Schedule next refresh
                self._start_background_refresh()
                
        except Exception as e:
            logger.error(f"❌ Background refresh error: {e}")
            # Try to restart the timer even if refresh failed
            if not self.is_shutdown:
                self._start_background_refresh()
    
    def stop_background_refresh(self):
        """
        Stop the background refresh timer (for cleanup)
        """
        self.is_shutdown = True
        if self.background_timer:
            self.background_timer.cancel()
            logger.info("🛑 Background refresh timer stopped")
    
    def __del__(self):
        """
        Cleanup when cache manager is destroyed
        """
        self.stop_background_refresh()

# Global cache manager instance
_cache_manager = None

def get_cache_manager(cache_ttl_seconds: int = 60) -> CacheManager:
    """
    Get the global cache manager instance (singleton pattern)
    
    Args:
        cache_ttl_seconds: Cache TTL in seconds (only used on first call)
    
    Returns:
        CacheManager: Global cache manager instance
    """
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(cache_ttl_seconds)
    return _cache_manager

def get_cached_pairs_data():
    """
    Get pairs data using the cache manager
    This function replaces direct calls to extract_all_pairs_data() for cached endpoints
    
    Returns:
        Dict: Cached or fresh pairs data
    """
    cache_manager = get_cache_manager()
    
    # Define the refresh function that fetches fresh data
    def refresh_data():
        from data_integration import extract_all_pairs_data
        return extract_all_pairs_data()
    
    return cache_manager.get_or_refresh_data(refresh_data)

def get_cached_pairs_data_only():
    """
    Get pairs data ONLY from cache, never trigger RPC calls
    Used by cached endpoints to avoid triggering data fetches
    
    Returns:
        Dict: Cached pairs data or empty dict if no cache
    """
    cache_manager = get_cache_manager()
    cached_data = cache_manager.get_cached_data_only()
    
    if cached_data:
        return cached_data
    else:
        return {
            'error': 'No cached data available',
            'pairs': [],
            'message': 'Cache is empty. Try calling a non-cached endpoint first to populate the cache.'
        }

def get_cache_status() -> Dict:
    """
    Get current cache status information
    
    Returns:
        Dict: Cache status information
    """
    cache_manager = get_cache_manager()
    return cache_manager.get_cache_info()

def invalidate_cache() -> None:
    """
    Manually invalidate the cache (force refresh on next request)
    """
    cache_manager = get_cache_manager()
    cache_manager.invalidate_cache()

def configure_cache(ttl_seconds: int) -> None:
    """
    Configure cache TTL (creates new cache manager if needed)
    
    Args:
        ttl_seconds: New cache TTL in seconds
    """
    global _cache_manager
    _cache_manager = CacheManager(ttl_seconds)
    logger.info(f"🔧 Cache reconfigured with {ttl_seconds}s TTL")
