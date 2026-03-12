#!/usr/bin/env python3
"""
Price Inversion Logic - Universal OHLC Inversion
Converts blockchain internal rates to proper trading pair rates
Only inverts OHLC prices, leaves volumes and metadata unchanged
"""

def invert_price(price):
    """
    Invert price (1/price) and handle edge cases
    """
    if price == 0:
        return 0
    return 1.0 / price

def invert_ohlc_prices(raw_prices):
    """
    Invert OHLC prices with proper high/low swapping
    
    Args:
        raw_prices (dict): {'open': float, 'high': float, 'low': float, 'close': float}
    
    Returns:
        dict: Inverted OHLC prices with high/low properly swapped
    """
    if not raw_prices:
        return {'open': 0, 'high': 0, 'low': 0, 'close': 0}
    
    # Store original values for proper high/low swapping
    original_high = raw_prices.get('high', 0)
    original_low = raw_prices.get('low', 0)
    
    return {
        'open': invert_price(raw_prices.get('open', 0)),
        'high': invert_price(original_low),   # New high = 1/original_low
        'low': invert_price(original_high),   # New low = 1/original_high  
        'close': invert_price(raw_prices.get('close', 0))
    }

def apply_universal_price_inversion(pair_data):
    """
    Apply universal price inversion to pair data
    Only inverts OHLC prices, keeps volumes and metadata unchanged
    
    Args:
        pair_data (dict): Complete pair data with volumes and prices
    
    Returns:
        dict: Pair data with inverted OHLC prices (volumes unchanged)
    """
    # Create a copy to avoid modifying original data
    inverted_data = pair_data.copy()
    
    # Extract raw OHLC prices
    raw_prices = {
        'open': pair_data.get('open', 0),
        'high': pair_data.get('high', 0),
        'low': pair_data.get('low', 0),
        'close': pair_data.get('last', 0)  # 'last' is same as 'close'
    }
    
    # Apply inversion to OHLC prices
    inverted_prices = invert_ohlc_prices(raw_prices)
    
    # Update only the OHLC price fields
    inverted_data['open'] = inverted_prices['open']
    inverted_data['high'] = inverted_prices['high']
    inverted_data['low'] = inverted_prices['low']
    inverted_data['last'] = inverted_prices['close']
    
    # Keep all other fields unchanged:
    # - base_volume, target_volume (actual trading volumes)
    # - base_currency, target_currency (currency identifiers)
    # - converter, symbol (metadata)
    # - base_currency_id, target_currency_id (IDs)
    
    # Mark as inverted for debugging
    inverted_data['inverted'] = True
    
    return inverted_data

def test_price_inversion():
    """Test the price inversion logic with real VRSC-DAI data"""
    print("🧪 Testing Universal Price Inversion")
    print("=" * 50)
    
    # Test with real VRSC-DAI data from blockchain
    sample_pair = {
        'base_currency': 'VRSC',
        'target_currency': 'DAI',
        'symbol': 'VRSC-DAI',
        'base_volume': 15885.15408064,      # Keep unchanged
        'target_volume': 33975.69388561,    # Keep unchanged
        'open': 0.46185540,                 # Invert this
        'high': 0.47504551,                 # Invert this (becomes new low)
        'low': 0.46100902,                  # Invert this (becomes new high)
        'last': 0.46575393,                 # Invert this
        'converter': 'Bridge.vETH',         # Keep unchanged
        'base_currency_id': 'iJhCezBExJHvtyH3fGhNnt2NhU4Ztkf2yq'  # Keep unchanged
    }
    
    print("📊 Original VRSC-DAI pair data:")
    for key, value in sample_pair.items():
        print(f"  {key}: {value}")
    
    print("\n🔄 Applying universal price inversion...")
    inverted_pair = apply_universal_price_inversion(sample_pair)
    
    print("\n📊 After universal price inversion:")
    for key, value in inverted_pair.items():
        if key in ['open', 'high', 'low', 'last']:
            original_value = sample_pair.get(key, 0)
            print(f"  {key}: {value:.8f} (was {original_value})")
        else:
            print(f"  {key}: {value}")
    
    print("\n💡 Verification:")
    print(f"  Original VRSC->DAI last: {sample_pair['last']}")
    print(f"  Inverted VRSC-DAI last: {inverted_pair['last']:.8f}")
    print(f"  Expected (~2.15): {1/sample_pair['last']:.8f}")
    print(f"  ✅ Match: {abs(inverted_pair['last'] - (1/sample_pair['last'])) < 0.0001}")
    
    print(f"\n  Volume verification:")
    print(f"  Base volume unchanged: {sample_pair['base_volume']} = {inverted_pair['base_volume']}")
    print(f"  Target volume unchanged: {sample_pair['target_volume']} = {inverted_pair['target_volume']}")
    
    print("\n✅ Universal price inversion test complete!")

if __name__ == "__main__":
    test_price_inversion()
