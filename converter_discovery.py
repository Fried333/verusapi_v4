#!/usr/bin/env python3
"""
Converter Discovery Module
Discovers all active converters while respecting exclusion rules
"""

import json
from verus_rpc import make_rpc_call
from dict import get_ticker_by_id, get_min_native_tokens
from block_height import get_session_block_height, get_current_session_id

# Define excluded converters that should be filtered out
excluded_chains = ["Bridge.CHIPS", "Bridge.vDEX", "Bridge.vARRR", "whales"]

def get_all_converters(system_id=None, chain="VRSC"):
    """
    Get all converters for a specific system using RPC
    
    Args:
        system_id (str): System ID to query (if None, uses chain's native currency)
        chain (str): Chain to query on (default: "VRSC")
    
    Returns:
        List of converter data or None if failed
    """
    try:
        # Use chain's native currency as system_id if not specified
        if system_id is None:
            system_id = chain
        
        print(f"🔄 Fetching all converters for system: {system_id} on chain: {chain}")
        
        # Get session block height for consistency
        block_height = get_session_block_height()
        print(f"🔄 Using cached session block height: {block_height} (session: {get_current_session_id()})")
        
        # Make RPC call to get currency converters using the chain's native currency
        result = make_rpc_call(chain, "getcurrencyconverters", [system_id])
        
        if result is None:
            print(f"❌ Failed to get converters for {system_id} on {chain}")
            return None
        
        if isinstance(result, list) and len(result) > 0:
            print(f"✅ Successfully fetched {len(result)} converters for {system_id} on {chain} at block {block_height}")
            return result
        else:
            print(f"⚠️ No converters found for {system_id} on {chain}")
            return []
            
    except Exception as e:
        print(f"❌ Error fetching converters for {system_id} on {chain}: {e}")
        return None

def filter_converters(converters_data):
    """
    Filter converters to exclude problematic ones based on exclusion rules
    
    Args:
        converters_data (list): Raw converter data from RPC call
        
    Returns:
        tuple: (filtered_converters, excluded_converters)
    """
    if not converters_data:
        return [], []
    
    filtered_converters = []
    excluded_converters = []
    
    print(f"🔄 Filtering converters (excluding: {excluded_chains})")
    
    for converter in converters_data:
        if 'fullyqualifiedname' in converter:
            converter_name = converter['fullyqualifiedname']
            
            # Check if this converter should be excluded
            if converter_name in excluded_chains:
                excluded_converters.append(converter)
                print(f"❌ Excluded converter: {converter_name}")
            else:
                filtered_converters.append(converter)
                print(f"✅ Included converter: {converter_name}")
        else:
            print(f"⚠️  Converter missing fullyqualifiedname: {converter}")
    
    print(f"🎯 Filter results: {len(filtered_converters)} included, {len(excluded_converters)} excluded")
    return filtered_converters, excluded_converters

def filter_bridge_converters_by_chain(converters_data, chain):
    """
    Filter out bridge converters that should be sourced from other chains to avoid double-counting
    
    Args:
        converters_data (list): List of raw converter data
        chain (str): Current chain being processed
        
    Returns:
        list: Filtered converters (excludes bridge converters from wrong chains)
    """
    try:
        print(f"🔄 Filtering bridge converters for {chain} chain")
        
        filtered_converters = []
        excluded_count = 0
        
        # Define which bridge converters belong to which chains
        bridge_converter_chains = {
            'Bridge.CHIPS': 'CHIPS',
            'Bridge.vARRR': 'VARRR', 
            'Bridge.vDEX': 'VDEX',
            'Bridge.vETH': 'VRSC'  # vETH bridge is hosted on VRSC
        }
        
        for converter in converters_data:
            converter_name = converter.get('fullyqualifiedname', '')
            
            # Check if this is a bridge converter
            if converter_name.startswith('Bridge.'):
                # Get the chain this bridge converter should be sourced from
                expected_chain = bridge_converter_chains.get(converter_name)
                
                if expected_chain == chain:
                    # This bridge converter belongs to this chain - include it
                    filtered_converters.append(converter)
                    print(f"✅ Included bridge converter: {converter_name} (belongs to {chain})")
                else:
                    # This bridge converter should be sourced from another chain - exclude it
                    excluded_count += 1
                    print(f"❌ Excluded bridge converter: {converter_name} (belongs to {expected_chain}, not {chain})")
            else:
                # Not a bridge converter - include all native converters
                filtered_converters.append(converter)
                print(f"✅ Included native converter: {converter_name}")
        
        print(f"🎯 Bridge filter results for {chain}: {len(filtered_converters)} included, {excluded_count} excluded")
        return filtered_converters
        
    except Exception as e:
        print(f"❌ Error filtering bridge converters for {chain}: {e}")
        return converters_data

def filter_converters_by_native_holdings(converters_data):
    """
    Filter converters based on minimum native token holdings per chain
    
    Args:
        converters_data (list): List of raw converter data with source_chain info
        
    Returns:
        tuple: (included_converters, excluded_converters)
    """
    try:
        print(f"🔄 Filtering converters by native token holdings")
        
        included_converters = []
        excluded_converters = []
        
        for converter in converters_data:
            converter_name = converter.get('currencyname', 'Unknown')
            source_chain = converter.get('source_chain', 'VRSC')
            
            # Get minimum native token threshold for this chain
            min_threshold = get_min_native_tokens(source_chain)
            
            # Get native token holdings from reserve currencies
            native_holdings = get_native_token_holdings(converter, source_chain)
            
            if native_holdings >= min_threshold:
                print(f"✅ Included converter: {converter_name} ({native_holdings:.0f} {source_chain} >= {min_threshold})")
                included_converters.append(converter)
            else:
                print(f"❌ Excluded converter: {converter_name} ({native_holdings:.0f} {source_chain} < {min_threshold})")
                excluded_converters.append(converter)
        
        print(f"🎯 Filter results: {len(included_converters)} included, {len(excluded_converters)} excluded")
        
        return included_converters, excluded_converters
        
    except Exception as e:
        print(f"❌ Error filtering converters: {e}")
        return converters_data, []

def get_native_token_holdings(converter, chain):
    """
    Get the amount of native tokens held by a converter
    
    Args:
        converter (dict): Converter data (either raw RPC data or processed data)
        chain (str): Chain name (VRSC, CHIPS, etc.)
        
    Returns:
        float: Amount of native tokens held
    """
    try:
        # Check if this is processed converter data with reserve_currencies
        if 'reserve_currencies' in converter:
            reserve_currencies = converter['reserve_currencies']
            for reserve in reserve_currencies:
                ticker = reserve.get('ticker', '')
                if ticker == chain:  # VRSC, CHIPS, VARRR, VDEX
                    return float(reserve.get('reserves', 0))
        
        # Check if this is raw RPC data - look in lastnotarization.currencystate.reservecurrencies
        elif 'lastnotarization' in converter:
            currency_state = converter.get('lastnotarization', {}).get('currencystate', {})
            reserve_currencies = currency_state.get('reservecurrencies', [])
            
            # Map chain names to their currency IDs
            chain_currency_ids = {
                'VRSC': 'i5w5MuNik5NtLcYmNzcvaoixooEebB6MGV',
                'CHIPS': 'iJ3WZocnjG9ufv7GKUA4LijQno5gTMb7tP',  # CHIPS currency ID
                'VARRR': 'iExBJfZYK7KREDpuhj6PzZBzqMAKaFg7d2',  # VARRR currency ID  
                'VDEX': 'iHog9UCTrn95qpUBFCZ7kKz7qWdMA8MQ6N'   # VDEX currency ID
            }
            
            target_currency_id = chain_currency_ids.get(chain)
            if target_currency_id:
                for reserve in reserve_currencies:
                    if reserve.get('currencyid') == target_currency_id:
                        return float(reserve.get('reserves', 0))
            
            # Fallback: also check by chain name directly
            for reserve in reserve_currencies:
                currency_id = reserve.get('currencyid', '')
                if currency_id == chain:
                    return float(reserve.get('reserves', 0))
        
        # Check if this is raw RPC data with reserves field (older format)
        elif 'reserves' in converter:
            reserves = converter.get('reserves', {})
            
            # Look for the native currency in reserves
            native_currency = chain  # VRSC, CHIPS, VARRR, VDEX
            
            if native_currency in reserves:
                return float(reserves[native_currency])
            
            # Also check for the chain name in different formats
            for currency_id, amount in reserves.items():
                if currency_id == native_currency:
                    return float(amount)
        
        # If no native currency found, return 0
        return 0.0
        
    except Exception as e:
        print(f"❌ Error getting native token holdings for {converter.get('currencyname', converter.get('name', converter.get('fullyqualifiedname', 'Unknown')))}: {e}")
        return 0.0

def extract_converter_info(converter):
    """
    Extract key information from a converter
    
    Args:
        converter (dict): Single converter data from RPC response
        
    Returns:
        dict: Extracted converter information
    """
    info = {
        'name': None,
        'currency_id': None,
        'supply': None,
        'reserve_currencies': [],
        'source_chain': converter.get('source_chain', 'VRSC'),
        'chain': converter.get('source_chain', 'VRSC'),  # Add chain field for API compatibility
        'currencies': [],  # Add currencies field for API compatibility
        'total_liquidity_usd': 0.0,  # Add liquidity field for API compatibility
        'raw_data': converter
    }
    
    try:
        # Get basic info
        if 'fullyqualifiedname' in converter:
            info['name'] = converter['fullyqualifiedname']
        
        # Extract currency ID from the converter keys
        for key in converter.keys():
            if key not in ['fullyqualifiedname', 'height', 'output', 'lastnotarization']:
                info['currency_id'] = key
                break
        
        # Extract detailed info from lastnotarization
        if 'lastnotarization' in converter and 'currencystate' in converter['lastnotarization']:
            currency_state = converter['lastnotarization']['currencystate']
            
            # Get supply
            if 'supply' in currency_state:
                info['supply'] = float(currency_state['supply'])
            
            # Get reserve currencies
            if 'reservecurrencies' in currency_state:
                for rc in currency_state['reservecurrencies']:
                    ticker = get_ticker_by_id(rc.get('currencyid', ''))
                    reserve_info = {
                        'currency_id': rc.get('currencyid', ''),
                        'ticker': ticker,
                        'weight': float(rc.get('weight', 0)),
                        'reserves': float(rc.get('reserves', 0)),
                        'price_in_reserve': float(rc.get('priceinreserve', 0))
                    }
                    info['reserve_currencies'].append(reserve_info)
                    
                    # Add to currencies list for API compatibility
                    if ticker:
                        info['currencies'].append(ticker)
        
    except Exception as e:
        print(f"⚠️  Error extracting info from converter {info.get('name', 'unknown')}: {e}")
    
    return info

def discover_active_converters(chains=None):
    """
    Main function to discover all active converters across multiple chains
    
    Args:
        chains (list): List of chains to discover converters on. Default is ["VRSC"]
    
    Returns:
        dict: {
            'active_converters': list of filtered converter info,
            'excluded_converters': list of excluded converter info,
            'total_count': total converters found,
            'active_count': active converters after filtering,
            'excluded_count': excluded converters count,
            'block_height': block height used for this discovery,
            'chains': dict of per-chain results
        }
    """
    if chains is None:
        chains = ["VRSC"]
    
    print(f"🔍 Starting multi-chain converter discovery process for: {chains}")
    
    # Get current block height for this session
    block_height = get_session_block_height()
    
    all_raw_converters = []
    chain_results = {}
    
    # Discover converters on each chain
    for chain in chains:
        print(f"\n🔄 Discovering converters on {chain}...")
        # Use each chain's native currency as the system_id
        raw_converters = get_all_converters(system_id=chain, chain=chain)
        
        if raw_converters:
            # Filter out bridge converters that should be sourced from other chains
            filtered_converters = filter_bridge_converters_by_chain(raw_converters, chain)
            
            # Add source_chain to each converter for tracking
            for converter in filtered_converters:
                converter['source_chain'] = chain
            
            all_raw_converters.extend(filtered_converters)
            chain_results[chain] = {
                'count': len(filtered_converters),
                'converters': filtered_converters,
                'total_found': len(raw_converters),
                'bridge_filtered': len(raw_converters) - len(filtered_converters)
            }
            print(f"✅ Found {len(raw_converters)} converters on {chain}, kept {len(filtered_converters)} after bridge filtering")
        else:
            chain_results[chain] = {
                'count': 0,
                'converters': [],
                'total_found': 0,
                'bridge_filtered': 0
            }
            print(f"❌ No converters found on {chain}")
    
    if not all_raw_converters:
        return {
            'active_converters': [],
            'excluded_converters': [],
            'total_count': 0,
            'active_count': 0,
            'excluded_count': 0,
            'block_height': block_height,
            'chains': chain_results,
            'error': 'Failed to fetch converters from any chain'
        }
    
    # Filter converters
    filtered_converters, excluded_converters = filter_converters_by_native_holdings(all_raw_converters)
    
    # Extract detailed info for active converters
    active_converter_info = []
    for converter in filtered_converters:
        info = extract_converter_info(converter)
        active_converter_info.append(info)
    
    # Extract info for excluded converters (for reference)
    excluded_converter_info = []
    for converter in excluded_converters:
        info = extract_converter_info(converter)
        excluded_converter_info.append(info)
    
    result = {
        'active_converters': active_converter_info,
        'excluded_converters': excluded_converter_info,
        'total_count': len(all_raw_converters),
        'active_count': len(active_converter_info),
        'excluded_count': len(excluded_converter_info),
        'block_height': block_height,
        'chains': chain_results
    }
    
    print(f"\n✅ Multi-chain converter discovery complete:")
    print(f"   Chains processed: {len(chains)}")
    print(f"   Total found: {result['total_count']}")
    print(f"   Active (included): {result['active_count']}")
    print(f"   Excluded: {result['excluded_count']}")
    print(f"   Block height: {result['block_height']}")
    
    # Show per-chain breakdown
    for chain, chain_data in chain_results.items():
        print(f"   {chain}: {chain_data['count']} converters")
    
    # Automatically save the results to JSON file
    save_success = save_converter_discovery(result)
    if save_success:
        print(f"💾 Results saved to converter_discovery.json")
    else:
        print(f"❌ Failed to save results to converter_discovery.json")
    
    return result

def save_converter_discovery(discovery_result, filename=None):
    """
    Save converter discovery results to a JSON file
    
    Args:
        discovery_result (dict): Result from discover_active_converters()
        filename (str): Output filename
    """
    try:
        # Use relative path if no filename provided
        if filename is None:
            import os
            filename = os.path.join(os.path.dirname(__file__), 'converter_discovery.json')
        
        with open(filename, 'w') as f:
            json.dump(discovery_result, f, indent=2, default=str)
        print(f"💾 Converter discovery saved to: {filename}")
        return True
    except Exception as e:
        print(f"❌ Error saving converter discovery: {e}")
        return False

if __name__ == "__main__":
    # Test the converter discovery functionality
    print("🧪 Testing Converter Discovery Module")
    print("=" * 50)
    
    # Import session management for testing
    from block_height import start_new_session, clear_session
    
    # Start a new session
    session_id = start_new_session()
    
    try:
        # Discover active converters
        discovery = discover_active_converters()
        
        # Display summary
        print(f"\n📊 Discovery Summary:")
        print(f"Block Height: {discovery['block_height']}")
        print(f"Total Converters: {discovery['total_count']}")
        print(f"Active Converters: {discovery['active_count']}")
        print(f"Excluded Converters: {discovery['excluded_count']}")
        
        # Display active converters
        print(f"\n✅ Active Converters:")
        for converter in discovery['active_converters']:
            print(f"  - {converter['name']} ({len(converter['reserve_currencies'])} reserves)")
        
        # Display excluded converters
        print(f"\n❌ Excluded Converters:")
        for converter in discovery['excluded_converters']:
            print(f"  - {converter['name']}")
        
        # Save results
        save_converter_discovery(discovery)
        
    finally:
        # Clear session
        clear_session()
    
    print("✅ Converter discovery test complete")
