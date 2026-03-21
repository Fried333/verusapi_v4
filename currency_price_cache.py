#!/usr/bin/env python3
"""
Currency Price Cache Manager
Handles global caching of specific conversion USD prices, similar to other cached data
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from verus_rpc import make_rpc_call

# Global cache for currency USD prices
_currency_price_cache: Dict[str, float] = {}
_cache_timestamp: Optional[datetime] = None
_cache_ttl_seconds = 60  # Cache for 60 seconds like other data

# VRSC USD price cache
_vrsc_usd_price: float = 0.0
_vrsc_cache_timestamp: Optional[datetime] = None
_vrsc_cache_ttl_seconds = 60  # Cache VRSC price for 60 seconds

def load_currency_config() -> Dict:
    """Load currency configuration from JSON file"""
    config_path = os.path.join(os.path.dirname(__file__), 'currency_config.json')
    
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_currency_config(config: Dict) -> bool:
    """Save currency configuration to JSON file"""
    config_path = os.path.join(os.path.dirname(__file__), 'currency_config.json')
    
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False

def get_coingecko_eth_price() -> float:
    """Get current ETH price from CoinGecko"""
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd", timeout=10)
        data = response.json()
        return data['ethereum']['usd']
    except Exception:
        return 0.0

def get_binance_eth_price() -> float:
    """Get current ETH price from Binance as fallback"""
    try:
        response = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=10)
        data = response.json()
        return float(data['price'])
    except Exception:
        return 0.0

def get_eth_price_with_fallback() -> float:
    """Get ETH price with CoinGecko primary and Binance fallback"""
    # Try CoinGecko first
    eth_price = get_coingecko_eth_price()
    if eth_price > 0:
        return eth_price
    
    # Fallback to Binance
    eth_price = get_binance_eth_price()
    if eth_price > 0:
        return eth_price
    
    return 0.0

def is_vrsc_cache_valid() -> bool:
    """Check if the VRSC USD price cache is still valid"""
    if not _vrsc_cache_timestamp:
        return False
    
    return datetime.now() - _vrsc_cache_timestamp < timedelta(seconds=_vrsc_cache_ttl_seconds)

def refresh_vrsc_usd_price() -> float:
    """Refresh VRSC USD price and update cache"""
    global _vrsc_usd_price, _vrsc_cache_timestamp
    
    try:
        # Step 1: Convert VRSC to vETH via NATI🦉
        conversion_params = {'currency': 'VRSC', 'convertto': 'vETH', 'amount': 1, 'via': 'NATI🦉'}
        result = make_rpc_call('VRSC', 'estimateconversion', [conversion_params])
        
        if not result or 'estimatedcurrencyout' not in result:
            return 0.0
            
        vrsc_veth_rate = float(result['estimatedcurrencyout'])
        
        # Step 2: Get ETH price with fallback
        eth_usd_price = get_eth_price_with_fallback()
        
        if eth_usd_price <= 0:
            return 0.0
            
        # Step 3: Calculate VRSC USD price
        vrsc_usd_price = vrsc_veth_rate * eth_usd_price
        
        # Update cache
        _vrsc_usd_price = vrsc_usd_price
        _vrsc_cache_timestamp = datetime.now()
        
        return vrsc_usd_price
        
    except Exception:
        return 0.0

def get_vrsc_usd_price() -> float:
    """Get VRSC to USD price via vETH conversion + CoinGecko ETH price (cached for 60 seconds)"""
    global _vrsc_usd_price
    
    # Check if cache is valid
    if not is_vrsc_cache_valid():
        refresh_vrsc_usd_price()
    
    return _vrsc_usd_price

def calculate_specific_currency_usd_price(currency: str, amount: float, via_converter: str, vrsc_usd_price: float) -> float:
    """Calculate USD price for a specific currency using its conversion parameters"""
    try:
        conversion_params = {
            'currency': currency,
            'convertto': 'VRSC',
            'amount': amount,
            'via': via_converter
        }
        
        conversion_result = make_rpc_call('VRSC', 'estimateconversion', [conversion_params])
        
        if conversion_result and 'estimatedcurrencyout' in conversion_result:
            vrsc_out = float(conversion_result['estimatedcurrencyout'])
            
            if vrsc_out > 0 and amount > 0:
                vrsc_per_unit = vrsc_out / amount
                usd_per_unit = vrsc_per_unit * vrsc_usd_price
                return usd_per_unit
        
        return 0.0
    except Exception:
        return 0.0

def is_cache_valid() -> bool:
    """Check if the current cache is still valid"""
    if not _cache_timestamp:
        return False
    
    return datetime.now() - _cache_timestamp < timedelta(seconds=_cache_ttl_seconds)

def refresh_currency_prices() -> Dict[str, float]:
    """Refresh all specific conversion currency USD prices"""
    global _currency_price_cache, _cache_timestamp
    
    config = load_currency_config()
    specific_conversions = config.get('specific_conversions', {})
    
    if not specific_conversions:
        return {}
    
    # Get VRSC USD price first
    vrsc_usd_price = get_vrsc_usd_price()
    if vrsc_usd_price <= 0:
        return {}
    
    # Calculate USD prices for all specific conversion currencies
    new_prices = {}
    
    for currency, params in specific_conversions.items():
        amount = params.get('amount', 1.0)
        via = params.get('via', '')
        
        if via:
            usd_price = calculate_specific_currency_usd_price(currency, amount, via, vrsc_usd_price)
            new_prices[currency] = usd_price
        else:
            new_prices[currency] = 0.0
    
    # Update global cache only (no file persistence)
    _currency_price_cache = new_prices.copy()
    _cache_timestamp = datetime.now()
    
    return new_prices

def get_currency_usd_price(currency: str) -> float:
    """Get USD price for a currency, using cache if valid or refreshing if needed"""
    global _currency_price_cache
    
    # Check if cache is valid
    if not is_cache_valid() or currency not in _currency_price_cache:
        refresh_currency_prices()
    
    return _currency_price_cache.get(currency, 0.0)

def get_all_currency_prices() -> Dict[str, float]:
    """Get all cached currency USD prices"""
    global _currency_price_cache
    
    # Check if cache is valid
    if not is_cache_valid():
        refresh_currency_prices()
    
    return _currency_price_cache.copy()

def initialize_currency_price_cache():
    """Initialize the currency price cache on program startup"""
    print("🔄 Initializing currency price cache...")
    
    # Always refresh prices on startup (no file caching)
    new_prices = refresh_currency_prices()
    if new_prices:
        print(f"✅ Initialized {len(new_prices)} currency USD prices")
    else:
        print("❌ Failed to initialize currency prices")

if __name__ == "__main__":
    # Test the cache system
    initialize_currency_price_cache()
    prices = get_all_currency_prices()
    
    print("\n💰 Cached Currency USD Prices:")
    for currency, price in prices.items():
        print(f"   {currency}: ${price:.6f} USD")
