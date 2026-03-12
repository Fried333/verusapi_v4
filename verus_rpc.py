#!/usr/bin/env python3

"""
Verus RPC connection module

Handles RPC setup and communication with multiple chain daemons.
Supports VRSC, CHIPS, VARRR, and VDEX chains.

Features:
- Connection pooling via requests.Session (one per chain)
- Concurrency limiting via semaphore (max 5 concurrent calls)
- Async support via httpx.AsyncClient
- Retry logic for transient errors (timeouts, work queue depth, code -28)
- Cached RPC config per chain (env vars read once)
"""

import os
import sys
import json
import time
import logging
import threading
import asyncio
from typing import Any, Optional

import requests
from dotenv import load_dotenv

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

# Import currency mapping from the official dict.py
from dict import normalize_currency_name, get_ticker_by_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level initialization: load .env ONCE
# ---------------------------------------------------------------------------
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)
elif os.path.exists(".env"):
    load_dotenv(".env", override=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_PORTS: dict[str, str] = {
    "VRSC": "27486",
    "CHIPS": "22778",
    "VARRR": "20778",
    "VDEX": "21778",
}

_MAX_CONCURRENT_RPC = 5
_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds
_DEFAULT_TIMEOUT = 30  # seconds

# Transient error indicators (case-insensitive substring match on error messages)
_TRANSIENT_MESSAGES = [
    "work queue depth exceeded",
    "loading block index",
    "verifying blocks",
    "loading wallet",
]
_TRANSIENT_CODES = {-28}  # RPC in warm-up

# ---------------------------------------------------------------------------
# Concurrency limiter
# ---------------------------------------------------------------------------
_semaphore = threading.Semaphore(_MAX_CONCURRENT_RPC)
_async_semaphore: Optional[asyncio.Semaphore] = None


def _get_async_semaphore() -> asyncio.Semaphore:
    """Lazy-init an asyncio semaphore (must be created inside a running loop)."""
    global _async_semaphore
    if _async_semaphore is None:
        _async_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RPC)
    return _async_semaphore


# ---------------------------------------------------------------------------
# Config cache
# ---------------------------------------------------------------------------
_config_cache: dict[str, dict[str, Any]] = {}
_config_lock = threading.Lock()


def _get_chain_config(chain: str) -> dict[str, Any]:
    """Return cached RPC config for *chain*, reading env vars only once."""
    if chain in _config_cache:
        return _config_cache[chain]

    with _config_lock:
        # Double-check after acquiring lock
        if chain in _config_cache:
            return _config_cache[chain]

        if chain == "VRSC":
            prefix = "VERUS"
        else:
            prefix = chain

        host = os.getenv(f"{prefix}_RPC_HOST", "127.0.0.1")
        port = int(os.getenv(f"{prefix}_RPC_PORT", _DEFAULT_PORTS.get(chain, "27486")))
        user = os.getenv(f"{prefix}_RPC_USER", "user")
        password = os.getenv(f"{prefix}_RPC_PASSWORD", "password")

        cfg = {
            "url": f"http://{host}:{port}",
            "user": user,
            "password": password,
        }
        _config_cache[chain] = cfg
        return cfg


# ---------------------------------------------------------------------------
# Connection pool (requests.Session per chain)
# ---------------------------------------------------------------------------
_sessions: dict[str, requests.Session] = {}
_sessions_lock = threading.Lock()


def _get_session(chain: str) -> requests.Session:
    """Return a persistent requests.Session for *chain*."""
    if chain in _sessions:
        return _sessions[chain]

    with _sessions_lock:
        if chain in _sessions:
            return _sessions[chain]

        cfg = _get_chain_config(chain)
        session = requests.Session()
        session.auth = (cfg["user"], cfg["password"])
        session.headers.update({"content-type": "application/json"})
        _sessions[chain] = session
        return session


# ---------------------------------------------------------------------------
# Async client pool (httpx)
# ---------------------------------------------------------------------------
_async_clients: dict[str, "httpx.AsyncClient"] = {}
_async_clients_lock = asyncio.Lock() if _HAS_HTTPX else None  # type: ignore[assignment]


async def _get_async_client(chain: str) -> "httpx.AsyncClient":
    """Return a persistent httpx.AsyncClient for *chain*."""
    if not _HAS_HTTPX:
        raise RuntimeError("httpx is required for async RPC calls: pip install httpx")

    if chain in _async_clients:
        return _async_clients[chain]

    async with _async_clients_lock:  # type: ignore[union-attr]
        if chain in _async_clients:
            return _async_clients[chain]

        cfg = _get_chain_config(chain)
        client = httpx.AsyncClient(
            auth=(cfg["user"], cfg["password"]),
            headers={"content-type": "application/json"},
            timeout=httpx.Timeout(_DEFAULT_TIMEOUT),
        )
        _async_clients[chain] = client
        return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_transient_error(error: Any) -> bool:
    """Check whether an RPC error dict represents a transient failure."""
    if isinstance(error, dict):
        code = error.get("code")
        if code in _TRANSIENT_CODES:
            return True
        msg = str(error.get("message", "")).lower()
        return any(t in msg for t in _TRANSIENT_MESSAGES)
    return False


def _build_payload(method: str, params: list) -> dict:
    return {
        "method": method,
        "params": params,
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
    }


# ---------------------------------------------------------------------------
# Synchronous RPC
# ---------------------------------------------------------------------------

def make_rpc_call(
    chain: str,
    method: str,
    params: Optional[list] = None,
    config: Optional[dict] = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> Any:
    """
    Make a synchronous RPC call to the specified chain daemon.

    Retries up to _MAX_RETRIES times on transient errors with exponential
    backoff. Limits concurrency to _MAX_CONCURRENT_RPC via a semaphore.
    """
    if params is None:
        params = []

    cfg = _get_chain_config(chain)
    session = _get_session(chain)
    payload = _build_payload(method, params)

    last_error: Optional[str] = None

    for attempt in range(1, _MAX_RETRIES + 1):
        _semaphore.acquire()
        try:
            response = session.post(cfg["url"], json=payload, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            _semaphore.release()
            last_error = str(exc)
            if attempt < _MAX_RETRIES:
                backoff = _BASE_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    "RPC %s.%s attempt %d/%d failed (%s), retrying in %.1fs",
                    chain, method, attempt, _MAX_RETRIES, last_error, backoff,
                )
                time.sleep(backoff)
                continue
            logger.error("RPC %s.%s failed after %d attempts: %s", chain, method, _MAX_RETRIES, last_error)
            return None
        except Exception as exc:
            _semaphore.release()
            logger.error("RPC %s.%s unexpected error: %s", chain, method, exc)
            return None
        else:
            _semaphore.release()

        # HTTP-level error
        if response.status_code != 200:
            logger.error("RPC %s.%s HTTP %d: %s", chain, method, response.status_code, response.text[:200])
            return None

        result = response.json()

        # RPC-level error
        rpc_error = result.get("error")
        if rpc_error is not None:
            if _is_transient_error(rpc_error) and attempt < _MAX_RETRIES:
                backoff = _BASE_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    "RPC %s.%s transient error (attempt %d/%d): %s — retrying in %.1fs",
                    chain, method, attempt, _MAX_RETRIES, rpc_error, backoff,
                )
                time.sleep(backoff)
                continue
            logger.error("RPC %s.%s error: %s", chain, method, rpc_error)
            return None

        return result.get("result")

    # Exhausted retries
    logger.error("RPC %s.%s failed after %d attempts: %s", chain, method, _MAX_RETRIES, last_error)
    return None


# ---------------------------------------------------------------------------
# Async RPC
# ---------------------------------------------------------------------------

async def make_rpc_call_async(
    chain: str,
    method: str,
    params: Optional[list] = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> Any:
    """
    Async variant of make_rpc_call using httpx.AsyncClient.

    Same retry / semaphore semantics as the sync version.
    """
    if not _HAS_HTTPX:
        raise RuntimeError("httpx is required for async RPC calls: pip install httpx")

    if params is None:
        params = []

    cfg = _get_chain_config(chain)
    client = await _get_async_client(chain)
    payload = _build_payload(method, params)
    sem = _get_async_semaphore()

    last_error: Optional[str] = None

    for attempt in range(1, _MAX_RETRIES + 1):
        async with sem:
            try:
                response = await client.post(
                    cfg["url"],
                    json=payload,
                    timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = str(exc)
                if attempt < _MAX_RETRIES:
                    backoff = _BASE_BACKOFF * (2 ** (attempt - 1))
                    logger.warning(
                        "Async RPC %s.%s attempt %d/%d failed (%s), retrying in %.1fs",
                        chain, method, attempt, _MAX_RETRIES, last_error, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error("Async RPC %s.%s failed after %d attempts: %s", chain, method, _MAX_RETRIES, last_error)
                return None
            except Exception as exc:
                logger.error("Async RPC %s.%s unexpected error: %s", chain, method, exc)
                return None

        if response.status_code != 200:
            logger.error("Async RPC %s.%s HTTP %d: %s", chain, method, response.status_code, response.text[:200])
            return None

        result = response.json()

        rpc_error = result.get("error")
        if rpc_error is not None:
            if _is_transient_error(rpc_error) and attempt < _MAX_RETRIES:
                backoff = _BASE_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    "Async RPC %s.%s transient error (attempt %d/%d): %s — retrying in %.1fs",
                    chain, method, attempt, _MAX_RETRIES, rpc_error, backoff,
                )
                await asyncio.sleep(backoff)
                continue
            logger.error("Async RPC %s.%s error: %s", chain, method, rpc_error)
            return None

        return result.get("result")

    logger.error("Async RPC %s.%s failed after %d attempts: %s", chain, method, _MAX_RETRIES, last_error)
    return None


# ---------------------------------------------------------------------------
# Convenience wrappers (sync — preserves original public API)
# ---------------------------------------------------------------------------

def make_verus_rpc(method: str, params: Optional[list] = None) -> Any:
    """Make an RPC call to the VRSC daemon."""
    return make_rpc_call("VRSC", method, params)


def get_latest_block() -> Optional[int]:
    """Get the latest block height for the VRSC chain."""
    try:
        response = make_rpc_call("VRSC", "getinfo", [])
        if response and "blocks" in response:
            return response["blocks"]
        logger.error("get_latest_block: invalid response")
        return None
    except Exception as e:
        logger.error("get_latest_block: %s", e)
        return None


def get_currency_name(currency_id: str) -> str:
    """Get currency name from ID using getcurrency RPC and normalize it."""
    try:
        ticker = get_ticker_by_id(currency_id)
        if ticker:
            return ticker

        currency_info = make_rpc_call("VRSC", "getcurrency", [currency_id])

        if currency_info and "fullyqualifiedname" in currency_info:
            return normalize_currency_name(currency_info["fullyqualifiedname"])
        elif currency_info and "name" in currency_info:
            return normalize_currency_name(currency_info["name"])
        else:
            return currency_id
    except Exception as e:
        logger.error("get_currency_name(%s): %s", currency_id, e)
        return currency_id


# ---------------------------------------------------------------------------
# Convenience wrappers (async)
# ---------------------------------------------------------------------------

async def make_verus_rpc_async(method: str, params: Optional[list] = None) -> Any:
    """Async variant of make_verus_rpc."""
    return await make_rpc_call_async("VRSC", method, params)


async def get_latest_block_async() -> Optional[int]:
    """Async variant of get_latest_block."""
    try:
        response = await make_rpc_call_async("VRSC", "getinfo", [])
        if response and "blocks" in response:
            return response["blocks"]
        logger.error("get_latest_block_async: invalid response")
        return None
    except Exception as e:
        logger.error("get_latest_block_async: %s", e)
        return None


async def get_currency_name_async(currency_id: str) -> str:
    """Async variant of get_currency_name."""
    try:
        ticker = get_ticker_by_id(currency_id)
        if ticker:
            return ticker

        currency_info = await make_rpc_call_async("VRSC", "getcurrency", [currency_id])

        if currency_info and "fullyqualifiedname" in currency_info:
            return normalize_currency_name(currency_info["fullyqualifiedname"])
        elif currency_info and "name" in currency_info:
            return normalize_currency_name(currency_info["name"])
        else:
            return currency_id
    except Exception as e:
        logger.error("get_currency_name_async(%s): %s", currency_id, e)
        return currency_id


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def close_sessions() -> None:
    """Close all persistent HTTP sessions. Call on shutdown."""
    for chain, session in _sessions.items():
        try:
            session.close()
        except Exception:
            pass
    _sessions.clear()


async def close_async_clients() -> None:
    """Close all persistent async HTTP clients. Call on shutdown."""
    for chain, client in _async_clients.items():
        try:
            await client.aclose()
        except Exception:
            pass
    _async_clients.clear()


# ---------------------------------------------------------------------------
# Module test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing sync RPC connection...")
    block = get_latest_block()
    if block:
        print(f"Current block height: {block}")
    else:
        print("Failed to get block height")

    if _HAS_HTTPX:
        print("\nTesting async RPC connection...")
        async def _test():
            b = await get_latest_block_async()
            if b:
                print(f"Async block height: {b}")
            else:
                print("Async: failed to get block height")
        asyncio.run(_test())
    else:
        print("\nhttpx not installed — skipping async test")
