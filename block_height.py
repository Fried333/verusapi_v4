#!/usr/bin/env python3
"""
Session-Based Block Height Utility
Provides a single, consistent block height for all calculations within one API session.
This ensures all volume and liquidity calculations use the same blockchain state.
Thread-safe via threading lock.
"""

import time
import threading
from verus_rpc import make_verus_rpc

# Thread-safe global state
_lock = threading.Lock()
_session_block_height = None
_session_id = None


def start_new_session():
    """
    Start a new API session, clearing any cached block height.
    Should be called at the beginning of each API request.

    Returns:
        str: New session ID
    """
    global _session_block_height, _session_id

    with _lock:
        _session_block_height = None
        _session_id = f"session_{int(time.time() * 1000)}"
        sid = _session_id

    print(f"Started new API session: {sid}")
    return sid


def get_session_block_height(session_id=None):
    """
    Get the block height for the current session.
    If no block height is cached for this session, fetch a fresh one.

    Args:
        session_id (str): Optional session ID for validation

    Returns:
        int: Current block height for this session, or None if failed
    """
    global _session_block_height, _session_id

    with _lock:
        if session_id and session_id != _session_id:
            # Session mismatch — reset
            _session_block_height = None
            _session_id = f"session_{int(time.time() * 1000)}"

        if _session_block_height is not None:
            return _session_block_height

    # Fetch outside the lock to avoid holding it during RPC
    try:
        result = make_verus_rpc('getinfo', [])

        if result and 'blocks' in result:
            height = int(result['blocks'])
            with _lock:
                _session_block_height = height
            return height
        else:
            return None

    except Exception as e:
        print(f"Error fetching session block height: {e}")
        return None


def get_current_session_id():
    """
    Get the current session ID.

    Returns:
        str: Current session ID, or None if no session is active
    """
    with _lock:
        return _session_id


def clear_session():
    """
    Clear the current session and cached block height.
    Should be called at the end of each API request.
    """
    global _session_block_height, _session_id

    with _lock:
        old_session = _session_id
        _session_block_height = None
        _session_id = None

    print(f"Cleared session: {old_session}")


if __name__ == "__main__":
    print("Testing Session-Based Block Height Utility")
    print("=" * 50)

    session_id = start_new_session()
    print(f"Session ID: {session_id}")

    block_height = get_session_block_height()
    print(f"Block height: {block_height}")

    cached_height = get_session_block_height()
    print(f"Cached block height: {cached_height}")

    clear_session()
    print("Session-based block height utility test complete")
