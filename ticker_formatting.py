#!/usr/bin/env python3
"""
Ticker Formatting Module
Formats raw pair data into CoinGecko and VerusStatistics API formats
Uses proven working code from Manual_Backup
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
import sys
import os

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dict import normalize_currency_name, get_ticker_by_id, get_mapped_eth_symbol, get_mapped_vrsc_symbol, is_currency_exported_to_ethereum
from data_integration import load_converter_data
from liquidity_calculator import get_pair_liquidity

logger = logging.getLogger(__name__)

def format_coingecko_ticker(pair_data: Dict, use_cache: bool = False) -> Dict:
    """
    Format a single pair into CoinGecko ticker format
    Based on correct Deploy/coingecko_tickers.json format
    
    Args:
        pair_data: Raw pair data from data integration
    
    Returns:
        Dict in CoinGecko ticker format
    """
    try:
        # Debug: Check if pair_data is the expected type
        if not isinstance(pair_data, dict):
            logger.error(f"Expected dict, got {type(pair_data)}: {pair_data}")
            return {}
            
        base_currency = pair_data.get('base_currency', '')
        target_currency = pair_data.get('target_currency', '')
        base_currency_id = pair_data.get('base_currency_id', '')
        target_currency_id = pair_data.get('target_currency_id', '')
        converter = pair_data.get('converter', '')
        
        # Get appropriate symbols using currency_contract_mapping (ETH symbols for exported currencies)
        from dict import get_symbol_for_currency
        base_symbol = get_symbol_for_currency(base_currency_id) or base_currency
        target_symbol = get_symbol_for_currency(target_currency_id) or target_currency
        
        # Create ticker_id with dash format using mapped symbols
        ticker_id = f"{base_symbol}-{target_symbol}"
        
        # Get converter currency_id for pool_id
        # Load converter discovery data to get currency_id
        converter_data = load_converter_data()
        pool_id = converter
        if converter_data:
            # converter_data is a list of converter dictionaries
            for conv in converter_data:
                if conv.get('name') == converter:
                    pool_id = conv.get('currency_id', converter)
                    break
        
        # Format all numbers to 8 decimal places as strings
        last_price = f"{float(pair_data.get('last', 0)):.8f}"
        base_volume = f"{float(pair_data.get('base_volume', 0)):.8f}"
        target_volume = f"{float(pair_data.get('target_volume', 0)):.8f}"
        high_price = f"{float(pair_data.get('high', 0)):.8f}"
        low_price = f"{float(pair_data.get('low', 0)):.8f}"
        open_price = f"{float(pair_data.get('open', 0)):.8f}"
        
        # Use last price for bid/ask (formatted to 8 decimals)
        bid_price = last_price
        ask_price = last_price
        
        # Calculate liquidity - use cache or calculate fresh
        if use_cache:
            # Use pre-calculated liquidity from cached data
            pair_liquidity_usd = pair_data.get('pair_liquidity_usd', 0.0)
        else:
            # Calculate actual pair liquidity using the formula
            pair_liquidity_usd = get_pair_liquidity(converter, base_currency, target_currency, converter_data)
        
        liquidity_usd_formatted = f"{pair_liquidity_usd:.8f}"
        
        # For DEX format, include pool_id and liquidity_in_usd (required by CoinGecko DEX spec)
        result = {
            "ticker_id": ticker_id,
            "base_currency": base_symbol,
            "target_currency": target_symbol,
            "last_price": last_price,
            "base_volume": base_volume,
            "target_volume": target_volume,
            "bid": bid_price,
            "ask": ask_price,
            "high": high_price,
            "low": low_price,
            "open": open_price,
            "pool_id": pool_id,
            "liquidity_in_usd": liquidity_usd_formatted
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Error formatting CoinGecko ticker: {e}")
        return {}

def generate_coingecko_tickers(pairs_data: List[Dict], use_cache: bool = False) -> List[Dict]:
    """
    Generate CoinGecko format tickers from pairs data
    Excludes pairs containing converter currencies (multi-currency baskets)
    
    Args:
        pairs_data: List of pair data from data integration
        use_cache: If True, use cache-only data sources and pre-calculated values
    
    Returns:
        List of CoinGecko formatted tickers (excluding converter currency pairs)
    """
    try:
        from dict import is_converter_currency
        
        tickers = []
        excluded_count = 0
        
        logger.info(f"🚀 Processing {len(pairs_data)} pairs for CoinGecko format (cache={use_cache})")
        
        for i, pair in enumerate(pairs_data):
            if isinstance(pair, dict):
                # Get currency IDs for filtering
                base_currency_id = pair.get('base_currency_id', '')
                target_currency_id = pair.get('target_currency_id', '')
                
                # Skip pairs that include converter currencies
                if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
                    excluded_count += 1
                    logger.debug(f"🚫 Excluding converter pair: {pair.get('base_currency', '')}-{pair.get('target_currency', '')}")
                    continue
                
                ticker = format_coingecko_ticker(pair, use_cache)
                if ticker:  # Only add valid tickers
                    tickers.append(ticker)
            else:
                logger.error(f"Pair {i} is not a dict: {type(pair)} - {pair}")
        
        logger.info(f"✅ Generated {len(tickers)} CoinGecko tickers from {len(pairs_data)} pairs (cache={use_cache}, excluded {excluded_count} converter pairs)")
        return tickers
        
    except Exception as e:
        logger.error(f"Error generating CoinGecko tickers: {e}")
        return []

def get_erc20_symbol(currency_id: str, fallback_symbol: str) -> str:
    """
    Get ERC20 symbol for a currency, with fallback to VRSC symbol
    
    Args:
        currency_id: The currency ID to look up
        fallback_symbol: Fallback symbol if no ERC20 mapping exists
        
    Returns:
        ERC20 symbol or fallback symbol
    """
    try:
        from dict import load_currency_mappings
        
        currency_contract_mapping = load_currency_mappings()
        
        if currency_id in currency_contract_mapping:
            return currency_contract_mapping[currency_id]["eth_symbol"]
        
        # For currencies without ERC20 mapping, use the fallback
        return fallback_symbol
        
    except Exception as e:
        logger.warning(f"Error getting ERC20 symbol for {currency_id}: {e}")
        return fallback_symbol

def should_exclude_pair_alltickers(base_currency_id: str, target_currency_id: str, base_symbol: str, target_symbol: str) -> bool:
    """
    Check if a pair should be excluded based on converter IDs and excluded chains
    
    Args:
        base_currency_id: Base currency ID
        target_currency_id: Target currency ID  
        base_symbol: Base currency symbol
        target_symbol: Target currency symbol
        
    Returns:
        True if pair should be excluded, False otherwise
    """
    try:
        from dict import is_converter_currency
        
        # Exclude if either currency is a converter currency
        if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
            return True
            
        return False
        
    except Exception as e:
        logger.warning(f"Error checking exclusion for {base_symbol}-{target_symbol}: {e}")
        return False

def generate_coinpaprika_tickers(pairs_data: List[Dict], use_cache: bool = False) -> List[Dict]:
    """
    Generate Coinpaprika format tickers from pairs data
    Uses same-pair aggregation (NO inverse aggregation) and ERC20 symbols
    
    Args:
        pairs_data: List of pair data from data integration
        use_cache: If True, use cache-only data sources (parameter for consistency)
    
    Returns:
        List of Coinpaprika formatted tickers
    """
    try:
        from collections import defaultdict
        
        pair_aggregation = defaultdict(lambda: {
            'base_volume': 0.0,
            'target_volume': 0.0,
            'price_sum': 0.0,
            'price_weight': 0.0,
            'high_price': 0.0,
            'low_price': float('inf'),
            'base_symbol': '',
            'target_symbol': '',
            'count': 0,
            'valid_prices': False
        })
        
        excluded_count = 0
        processed_count = 0
        
        for pair_data in pairs_data:
            base_currency_id = pair_data.get('base_currency_id', '')
            target_currency_id = pair_data.get('target_currency_id', '')
            base_currency = pair_data.get('base_currency', '')
            target_currency = pair_data.get('target_currency', '')
            
            # Check if pair should be excluded
            if should_exclude_pair_alltickers(base_currency_id, target_currency_id, base_currency, target_currency):
                excluded_count += 1
                continue
            
            # Get ERC20 symbols
            base_erc_symbol = get_erc20_symbol(base_currency_id, base_currency)
            target_erc_symbol = get_erc20_symbol(target_currency_id, target_currency)
            
            # Create pair key (same-pair aggregation, no inverse)
            pair_key = f"{base_erc_symbol}_{target_erc_symbol}"
            
            base_volume = float(pair_data.get('base_volume', 0))
            target_volume = float(pair_data.get('target_volume', 0))
            last_price = float(pair_data.get('last_price', 0))
            high_price = float(pair_data.get('high', 0))
            low_price = float(pair_data.get('low', 0))
            
            if base_volume <= 0:
                continue
            
            processed_count += 1
            agg = pair_aggregation[pair_key]
            
            # Set symbols on first encounter
            if not agg['base_symbol']:
                agg['base_symbol'] = base_erc_symbol
                agg['target_symbol'] = target_erc_symbol
            
            # Aggregate volumes
            agg['base_volume'] += base_volume
            agg['target_volume'] += target_volume
            
            # Handle price aggregation with fallback
            effective_price = last_price
            if last_price <= 0 and high_price > 0 and low_price > 0:
                effective_price = (high_price + low_price) / 2
            
            if effective_price > 0:
                weight = target_volume  # Use quote volume as weight (same as Enhanced CMC)
                agg['price_sum'] += effective_price * weight
                agg['price_weight'] += weight
                agg['valid_prices'] = True
            
            # Track high/low prices
            if high_price > 0:
                agg['high_price'] = max(agg['high_price'], high_price)
            if low_price > 0:
                if agg['low_price'] == float('inf'):
                    agg['low_price'] = low_price
                else:
                    agg['low_price'] = min(agg['low_price'], low_price)
            
            agg['count'] += 1
        
        # Generate final tickers
        final_tickers = []
        
        for pair_key, agg in pair_aggregation.items():
            if agg['base_volume'] > 0:
                # Calculate weighted average price
                if agg['price_weight'] > 0 and agg['valid_prices']:
                    weighted_avg_price = agg['price_sum'] / agg['price_weight']
                else:
                    weighted_avg_price = 0.0
                
                # Handle infinite low price
                if agg['low_price'] == float('inf'):
                    agg['low_price'] = weighted_avg_price
                
                # Create ticker in allTickers format
                ticker = {
                    'symbol': f"{agg['base_symbol']}-{agg['target_symbol']}",
                    'symbolName': f"{agg['base_symbol']}-{agg['target_symbol']}",
                    'volume': f"{agg['base_volume']:.8f}",
                    'last': f"{weighted_avg_price:.8f}",
                    'high': f"{agg['high_price']:.8f}",
                    'low': f"{agg['low_price']:.8f}",
                    'open': f"{agg['high_price']:.8f}"  # Using high as open (same as original)
                }
                
                final_tickers.append(ticker)
        
        # Sort by volume (descending)
        final_tickers.sort(key=lambda x: float(x['volume']), reverse=True)
        
        logger.info(f"✅ Coinpaprika: processed {processed_count} pairs, generated {len(final_tickers)} tickers (excluded {excluded_count} pairs)")
        return final_tickers
        
    except Exception as e:
        logger.error(f"Error generating coinpaprika tickers: {e}")
        return []

def aggregate_pairs_for_iaddress_cmc(pairs_data: List[Dict]) -> Dict:
    """
    Aggregate pairs for i-address CoinMarketCap format using i-addresses as keys
    Similar to CoinMarketCap aggregation but uses currency IDs instead of contract addresses
    """
    try:
        from dict import is_converter_currency
        
        pair_aggregation = {}
        
        excluded_count = 0
        processed_count = 0
        
        for pair_data in pairs_data:
            # Debug: Check data type
            if not isinstance(pair_data, dict):
                logger.error(f"Invalid pair_data type: {type(pair_data)}, value: {pair_data}")
                continue
                
            base_currency_id = pair_data.get('base_currency_id', '')
            target_currency_id = pair_data.get('target_currency_id', '')
            
            # I-address endpoint includes all currencies (no filtering for bridge currencies)
            # This endpoint uses currency IDs, not ERC20 addresses, so bridge currencies are valid
            
            base_currency = pair_data.get('base_currency', '')
            target_currency = pair_data.get('target_currency', '')
            
            # Create composite key using i-addresses
            pair_key = f"{base_currency_id}_{target_currency_id}"
            
            base_volume = float(pair_data.get('base_volume', 0))
            target_volume = float(pair_data.get('target_volume', 0))
            last_price = float(pair_data.get('last', 0))  # Use 'last' field like Enhanced CMC
            
            # Only include pairs with volume
            if base_volume <= 0:
                continue
            
            processed_count += 1
            
            if pair_key in pair_aggregation:
                # Aggregate with existing data (same logic as Enhanced CMC)
                existing = pair_aggregation[pair_key]
                
                # Sum volumes
                existing_base_vol = float(existing['base_volume'])
                existing_quote_vol = float(existing['quote_volume'])
                new_base_vol = base_volume
                new_quote_vol = target_volume
                
                total_base_vol = existing_base_vol + new_base_vol
                total_quote_vol = existing_quote_vol + new_quote_vol
                
                # Volume-weighted average price (using quote volume as weight - same as Enhanced CMC)
                existing_price = float(existing['last_price'])
                new_price = last_price
                
                if existing_quote_vol + new_quote_vol > 0:
                    weighted_price = (existing_price * existing_quote_vol + new_price * new_quote_vol) / (existing_quote_vol + new_quote_vol)
                else:
                    weighted_price = new_price  # Fallback to new price
                
                # Update aggregated data
                pair_aggregation[pair_key].update({
                    'last_price': f"{weighted_price:.8f}",
                    'base_volume': f"{total_base_vol:.8f}",
                    'quote_volume': f"{total_quote_vol:.8f}"
                })
                
                logger.debug(f"📊 Aggregated {pair_key}: quote volumes {existing_quote_vol:.2f}+{new_quote_vol:.2f}={total_quote_vol:.2f}")
            else:
                # First occurrence of this pair
                ticker = {
                    'base_id': base_currency_id,
                    'base_name': base_currency,  # Verus native symbol
                    'base_symbol': base_currency,  # Verus native symbol
                    'quote_id': target_currency_id,
                    'quote_name': target_currency,  # Verus native symbol
                    'quote_symbol': target_currency,  # Verus native symbol
                    'last_price': f"{last_price:.8f}",
                    'base_volume': f"{base_volume:.8f}",
                    'quote_volume': f"{target_volume:.8f}"
                }
                pair_aggregation[pair_key] = ticker
        
        logger.info(f"I-Address CMC aggregation: {excluded_count} excluded, {processed_count} processed, {len(pair_aggregation)} final pairs")
        return pair_aggregation
        
    except Exception as e:
        logger.error(f"Error in i-address CMC aggregation: {str(e)}")
        return {}

def format_iaddress_coinmarketcap_tickers(pairs_data: List[Dict], use_cache: bool = False) -> Dict:
    """
    Format tickers for i-address CoinMarketCap endpoint
    Uses i-addresses as identifiers instead of ERC20 contract addresses
    
    Args:
        pairs_data: List of pair data from data integration
        use_cache: If True, use cache-only data sources (parameter for consistency)
        
    Returns:
        Dict of i-address CoinMarketCap formatted tickers
    """
    try:
        if not pairs_data:
            logger.warning("No pairs data provided for i-address CMC formatting")
            return {}
        
        logger.info(f"Formatting {len(pairs_data)} pairs for i-address CoinMarketCap endpoint (cache={use_cache})")
        
        # Aggregate pairs using i-addresses
        aggregated_tickers = aggregate_pairs_for_iaddress_cmc(pairs_data)
        
        if not aggregated_tickers:
            logger.warning("No aggregated tickers generated for i-address CMC endpoint")
            return {}
        
        logger.info(f"Successfully formatted {len(aggregated_tickers)} i-address CMC tickers")
        return aggregated_tickers
        
    except Exception as e:
        logger.error(f"Error formatting i-address CMC tickers: {str(e)}")
        return {}

def get_symbol_for_currency(currency_id: str) -> str:
    """
    Get appropriate symbol for a currency using currency_contract_mapping
    Uses ETH symbol if currency has contract address, otherwise uses VRSC symbol
    
    Args:
        currency_id: Currency ID to look up
    
    Returns:
        Appropriate symbol (ETH or VRSC)
    """
    try:
        # Check if currency is exported to Ethereum (has contract address)
        if is_currency_exported_to_ethereum(currency_id):
            # Use ETH symbol for currencies with contract addresses
            eth_symbol = get_mapped_eth_symbol(currency_id)
            if eth_symbol:
                return eth_symbol
        
        # Use VRSC symbol for native currencies or fallback
        vrsc_symbol = get_mapped_vrsc_symbol(currency_id)
        if vrsc_symbol:
            return vrsc_symbol
            
        # Final fallback to ticker from currency_names
        return get_ticker_by_id(currency_id)
        
    except Exception as e:
        logger.error(f"Error getting symbol for currency {currency_id}: {e}")
        return get_ticker_by_id(currency_id)

def format_verus_statistics_ticker(pair_data: Dict) -> Dict:
    """
    Format a single pair into VerusStatistics ticker format (original version)
    Based on working Manual_Backup/verus_statistics_format.py
    
    Args:
        pair_data: Raw pair data from data integration
    
    Returns:
        Dict in VerusStatistics ticker format (original - no pool_id)
    """
    try:
        base_currency = pair_data.get('base_currency', '')
        target_currency = pair_data.get('target_currency', '')
        
        # Normalize currency names for display
        base_norm = normalize_currency_name(base_currency)
        target_norm = normalize_currency_name(target_currency)
        
        # Create symbol (dash-separated for VerusStatistics format)
        symbol = f"{base_norm}-{target_norm}"
        symbol_name = f"{base_norm}/{target_norm}"
        
        return {
            "symbol": symbol,
            "symbolName": symbol_name,
            "volume": f"{float(pair_data.get('base_volume', 0)):.8f}",
            "last": f"{float(pair_data.get('last', 0)):.8f}",
            "high": f"{float(pair_data.get('high', 0)):.8f}",
            "low": f"{float(pair_data.get('low', 0)):.8f}",
            "open": f"{float(pair_data.get('open', 0)):.8f}"
        }
        
    except Exception as e:
        logger.error(f"Error formatting VerusStatistics ticker: {e}")
        return {}

def format_verus_statistics_ticker_enhanced(pair_data: Dict) -> Dict:
    """
    Format a single pair into enhanced VerusStatistics ticker format
    Includes pool_id and 8-decimal formatting
    
    Args:
        pair_data: Raw pair data from data integration
    
    Returns:
        Dict in enhanced VerusStatistics ticker format with pool_id and 8 decimal formatting
    """
    try:
        base_currency = pair_data.get('base_currency', '')
        target_currency = pair_data.get('target_currency', '')
        converter = pair_data.get('converter', '')
        
        # Normalize currency names for display
        base_norm = normalize_currency_name(base_currency)
        target_norm = normalize_currency_name(target_currency)
        
        # Create symbol (dash-separated for VerusStatistics format)
        symbol = f"{base_norm}-{target_norm}"
        symbol_name = f"{base_norm}/{target_norm}"
        
        # Get pool_id from converter data
        pool_id = get_converter_pool_id(converter)
        
        return {
            "symbol": symbol,
            "symbolName": symbol_name,
            "volume": f"{float(pair_data.get('base_volume', 0)):.8f}",
            "last": f"{float(pair_data.get('last', 0)):.8f}",
            "high": f"{float(pair_data.get('high', 0)):.8f}",
            "low": f"{float(pair_data.get('low', 0)):.8f}",
            "open": f"{float(pair_data.get('open', 0)):.8f}",
            "pool_id": pool_id
        }
        
    except Exception as e:
        logger.error(f"Error formatting enhanced VerusStatistics ticker: {e}")
        return {}

def format_cmc_dex_ticker(pair_data: Dict) -> tuple:
    """
    Format a single pair into CoinMarketCap (CMC) DEX format
    Based on CMC DEX specification (Section C)
    
    Args:
        pair_data: Raw pair data from data integration
    
    Returns:
        Tuple of (composite_key, ticker_data) for DEX object format
    """
    try:
        base_currency = pair_data.get('base_currency', '')
        target_currency = pair_data.get('target_currency', '')
        converter = pair_data.get('converter', '')
        
        # Get currency IDs for base and quote currencies
        converter_data = load_converter_data()
        base_id = base_currency  # Default to currency name
        quote_id = target_currency  # Default to currency name
        
        if converter_data:
            for conv in converter_data:
                if conv.get('name') == converter:
                    # Use converter currency_id as base_id if base_currency matches converter
                    if base_currency == converter:
                        base_id = conv.get('currency_id', base_currency)
                    # Check reserve currencies for quote_id
                    for reserve in conv.get('reserve_currencies', []):
                        if reserve.get('ticker') == base_currency:
                            base_id = reserve.get('currency_id', base_currency)
                        if reserve.get('ticker') == target_currency:
                            quote_id = reserve.get('currency_id', target_currency)
                    break
        
        # Create composite key per CMC DEX specification (base_id_quote_id)
        # CMC DEX spec uses currency IDs as composite key components (like contract addresses)
        # Note: Sequential keys are used in generator to preserve all pool instances
        composite_key = f"{base_id}_{quote_id}"
        
        # Get currency full names (simplified for now)
        base_name = get_currency_full_name(base_currency)
        quote_name = get_currency_full_name(target_currency)
        
        # Use currency_contract_mapping for symbol selection (same logic as CoinGecko2)
        from dict import get_symbol_for_currency
        
        # Get proper symbols using currency_contract_mapping with fallback
        base_symbol = get_symbol_for_currency(base_id)
        if not base_symbol:
            # Fallback to ticker lookup or currency name
            base_symbol = get_ticker_by_id(base_id) or base_currency
        
        quote_symbol = get_symbol_for_currency(quote_id)
        if not quote_symbol:
            # Fallback to ticker lookup or currency name
            quote_symbol = get_ticker_by_id(quote_id) or target_currency
        
        # Get price and volumes as strings (DEX format uses strings)
        last_price = f"{float(pair_data.get('last', 0)):.8f}"
        base_volume = f"{float(pair_data.get('base_volume', 0)):.8f}"
        quote_volume = f"{float(pair_data.get('target_volume', 0)):.8f}"
        
        ticker_data = {
            "base_id": base_id,
            "base_name": base_name,
            "base_symbol": base_symbol,
            "quote_id": quote_id,
            "quote_name": quote_name,
            "quote_symbol": quote_symbol,
            "last_price": last_price,
            "base_volume": base_volume,
            "quote_volume": quote_volume
        }
        
        return composite_key, ticker_data
        
    except Exception as e:
        logger.error(f"Error formatting CMC DEX ticker: {e}")
        return None, {}

def format_cmc_enhanced_ticker(pair_data: Dict, use_cache: bool = False) -> tuple:
    """
    Format a single pair into Enhanced CoinMarketCap (CMC) DEX format
    Uses Ethereum contract symbols and addresses when available
    
    Args:
        pair_data: Raw pair data from data integration
        use_cache: If True, use cache-only data sources and pre-calculated values
    
    Returns:
        Tuple of (composite_key, ticker_data) for enhanced DEX object format
    """
    try:
        if use_cache:
            # Cache-only version - use pre-calculated data, avoid RPC calls
            from dict import normalize_currency_name, get_mapped_eth_symbol, get_mapped_eth_address, get_currency_id_by_name
            
            base_currency = pair_data.get('base_currency', '')
            target_currency = pair_data.get('target_currency', '')
            
            # Get normalized names and symbols
            base_normalized = normalize_currency_name(base_currency)
            target_normalized = normalize_currency_name(target_currency)
            
            base_symbol = get_mapped_eth_symbol(base_normalized)
            target_symbol = get_mapped_eth_symbol(target_normalized)
            
            # Skip pairs with missing symbol mappings
            if base_symbol is None or target_symbol is None:
                logger.debug(f"Skipping cached CMC pair with missing symbol mappings: {base_currency}-{target_currency}")
                return None, None
            
            # Get Ethereum contract addresses for base_id and quote_id
            base_currency_id = get_currency_id_by_name(base_normalized)
            target_currency_id = get_currency_id_by_name(target_normalized)
            
            base_id = get_mapped_eth_address(base_currency_id) if base_currency_id else ""
            quote_id = get_mapped_eth_address(target_currency_id) if target_currency_id else ""
            
            # Create composite key using contract addresses (same as live endpoint)
            composite_key = f"{base_id}_{quote_id}"
            
        else:
            # Live version - can make RPC calls
            from dict import get_symbol_for_currency, get_mapped_eth_address
            
            base_currency = pair_data.get('base_currency', '')
            target_currency = pair_data.get('target_currency', '')
            base_currency_id = pair_data.get('base_currency_id', '')
            target_currency_id = pair_data.get('target_currency_id', '')
            
            # Get proper symbols using currency_contract_mapping (same logic as CoinGecko2)
            base_symbol = get_symbol_for_currency(base_currency_id) or base_currency
            target_symbol = get_symbol_for_currency(target_currency_id) or target_currency
            
            # Use contract addresses as IDs if available, otherwise use currency IDs
            base_id = get_mapped_eth_address(base_currency_id) or base_currency_id or base_currency
            quote_id = get_mapped_eth_address(target_currency_id) or target_currency_id or target_currency
            
            # Create composite key using contract addresses when available
            composite_key = f"{base_id}_{quote_id}"
        
        # Common ticker data formatting
        ticker_data = {
            "base_id": base_id,
            "base_name": base_symbol,
            "base_symbol": base_symbol,
            "quote_id": quote_id,
            "quote_name": target_symbol,
            "quote_symbol": target_symbol,
            "last_price": f"{float(pair_data.get('last', 0)):.8f}",
            "base_volume": f"{float(pair_data.get('base_volume', 0)):.8f}",
            "quote_volume": f"{float(pair_data.get('target_volume', 0)):.8f}"
        }
        
        return composite_key, ticker_data
        
    except Exception as e:
        logger.error(f"Error formatting enhanced CMC ticker: {e}")
        return None, {}

def get_enhanced_currency_name(currency_info: Dict, fallback_symbol: str) -> str:
    """
    Get enhanced currency name using ERC20 token names from Etherscan when available
    
    Args:
        currency_info: Enhanced currency info from get_enhanced_currency_info
        fallback_symbol: Fallback Verus symbol
    
    Returns:
        Appropriate currency name for enhanced CMC format (ERC20 names for tokens, Verus names for native)
    """
    from dict import get_symbol_for_currency
    
    # Check if this currency has an Ethereum contract address and get the mapped symbol
    verus_id = currency_info.get('verus_id')
    if verus_id:
        # Use the symbol mapping logic to get appropriate symbol
        symbol = get_symbol_for_currency(verus_id)
        if symbol:
            return symbol
    
    # Fallback to Verus name mapping for native currencies or if lookup fails
    return get_currency_full_name(fallback_symbol)

def get_currency_full_name(currency_symbol: str) -> str:
    """
    Get appropriate name for a currency symbol (CMC DEX format)
    Per CMC spec, base_name should be short and descriptive, not verbose
    
    Args:
        currency_symbol: Currency symbol (e.g., 'VRSC', 'Bridge.vETH')
    
    Returns:
        Short, appropriate currency name for CMC DEX format
    """
    # Mapping of common Verus currencies to appropriate short names
    # Following CMC DEX spec pattern: base_name should be concise like "Wrapped BTC"
    name_mapping = {
        'VRSC': 'Verus',
        'Bridge.vETH': 'Bridge vETH',
        'DAI.vETH': 'DAI vETH',
        'tBTC.vETH': 'tBTC vETH',
        'USDC.vETH': 'USDC vETH',
        'USDT.vETH': 'USDT vETH',
        'vETH': 'vETH',
        'vARRR': 'vARRR',
        'CHIPS': 'CHIPS',
        'Pure': 'Pure',
        'NATI': 'NATI',
        'SUPERNET': 'SUPERNET',
        'NATI.vETH': 'NATI vETH',
        'scrvUSD.vETH': 'scrvUSD vETH'
    }
    
    return name_mapping.get(currency_symbol, currency_symbol)

def get_converter_pool_id(converter_name: str) -> str:
    """
    Get the pool_id (currency_id) for a given converter name
    
    Args:
        converter_name: Name of the converter (e.g., "Bridge.vETH")
    
    Returns:
        String containing the converter's currency_id (pool_id)
    """
    try:
        from data_integration import load_converter_data
        
        converters = load_converter_data()
        if not converters:
            return ''
        
        for converter in converters:
            if converter.get('name') == converter_name:
                return converter.get('currency_id', '')
        
        return ''
        
    except Exception as e:
        logger.error(f"Error getting pool_id for {converter_name}: {e}")
        return ''

def format_coingecko_response(pairs_data: List[Dict]) -> List[Dict]:
    """
    Format all pairs data into CoinGecko API response format
    Excludes pairs containing converter currencies (multi-currency baskets)
    
    Args:
        pairs_data: List of raw pair data
    
    Returns:
        List of CoinGecko formatted tickers (excluding converter currency pairs)
    """
    try:
        from dict import is_converter_currency
        
        tickers = []
        excluded_count = 0
        
        logger.info(f"Processing {len(pairs_data)} pairs for CoinGecko format")
        
        for i, pair in enumerate(pairs_data):
            logger.debug(f"Processing pair {i}: type={type(pair)}")
            if isinstance(pair, dict):
                # Get currency IDs for filtering
                base_currency_id = pair.get('base_currency_id', '')
                target_currency_id = pair.get('target_currency_id', '')
                
                # Skip pairs that include converter currencies
                if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
                    excluded_count += 1
                    logger.debug(f"🚫 Excluding converter pair: {pair.get('base_currency', '')}-{pair.get('target_currency', '')}")
                    continue
                
                ticker = format_coingecko_ticker(pair)
                if ticker:  # Only add valid tickers
                    tickers.append(ticker)
            else:
                logger.error(f"Pair {i} is not a dict: {type(pair)} - {pair}")
        
        logger.info(f"✅ CoinGecko formatting completed: {len(tickers)} tickers (excluded {excluded_count} converter pairs)")
        return tickers
        
    except Exception as e:
        logger.error(f"Error in format_coingecko_response: {e}")
        return []

def format_coingecko2_response(pairs_data: List[Dict]) -> List[Dict]:
    """
    Format all pairs data into CoinGecko2 API response format
    Uses currency_contract_mapping for proper ETH/VRSC symbol selection
    Excludes pairs containing converter currencies (multi-currency baskets)
    
    Args:
        pairs_data: List of raw pair data
    
    Returns:
        List of CoinGecko2 formatted tickers with proper symbol mapping (excluding converter currency pairs)
    """
    try:
        from dict import is_converter_currency
        
        formatted_tickers = []
        excluded_count = 0
        
        for pair_data in pairs_data:
            # Skip pairs containing converter currencies (multi-currency baskets)
            base_currency_id = pair_data.get('base_currency_id', '')
            target_currency_id = pair_data.get('target_currency_id', '')
            
            if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
                logger.debug(f"🚫 Excluding converter pair: {pair_data.get('base_currency', '')}-{pair_data.get('target_currency', '')}")
                excluded_count += 1
                continue
            
            formatted_ticker = format_coingecko2_ticker(pair_data)
            if formatted_ticker:  # Only add if formatting was successful
                formatted_tickers.append(formatted_ticker)
        
        logger.info(f"✅ CoinGecko2 formatting completed: {len(formatted_tickers)} tickers (excluded {excluded_count} converter pairs)")
        return formatted_tickers
        
    except Exception as e:
        logger.error(f"Error in format_coingecko2_response: {e}")
        return []

def format_verus_statistics_response(pairs_data: List[Dict]) -> Dict:
    """
    Format all pairs data into VerusStatistics API response format
    Based on working Manual_Backup structure
    Excludes pairs containing converter currencies (multi-currency baskets)
    
    Args:
        pairs_data: List of raw pair data
    
    Returns:
        Dict in VerusStatistics API format (excluding converter currency pairs)
    """
    try:
        from dict import is_converter_currency
        
        tickers = []
        excluded_count = 0
        
        for pair in pairs_data:
            # Get currency IDs for filtering
            base_currency_id = pair.get('base_currency_id', '')
            target_currency_id = pair.get('target_currency_id', '')
            
            # Skip pairs that include converter currencies
            if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
                excluded_count += 1
                logger.debug(f"🚫 Excluding converter pair: {pair.get('base_currency', '')}-{pair.get('target_currency', '')}")
                continue
            
            ticker = format_verus_statistics_ticker(pair)
            if ticker:  # Only add valid tickers
                tickers.append(ticker)
        
        # Create VerusStatistics API response structure
        response = {
            "code": "200000",
            "data": {
                "time": int(datetime.utcnow().timestamp() * 1000),  # Milliseconds
                "ticker": tickers
            }
        }
        
        logger.info(f"Formatted {len(tickers)} VerusStatistics tickers from {len(pairs_data)} pairs")
        return response
        
    except Exception as e:
        logger.error(f"Error formatting VerusStatistics response: {e}")
        return {
            "code": "500000",
            "data": {
                "time": int(datetime.utcnow().timestamp() * 1000),
                "ticker": []
            }
        }

def format_verus_statistics_response_enhanced(pairs_data: List[Dict]) -> Dict:
    """
    Format all pairs data into enhanced VerusStatistics API response format
    Includes pool_id and 8-decimal formatting
    
    Args:
        pairs_data: List of raw pair data
    
    Returns:
        Dict in enhanced VerusStatistics API format
    """
    try:
        tickers = []
        
        for pair in pairs_data:
            ticker = format_verus_statistics_ticker_enhanced(pair)
            if ticker:  # Only add valid tickers
                tickers.append(ticker)
        
        # Create VerusStatistics API response structure
        response = {
            "code": "200000",
            "data": {
                "time": int(datetime.utcnow().timestamp() * 1000),  # Milliseconds
                "ticker": tickers
            }
        }
        
        logger.info(f"Formatted {len(tickers)} enhanced VerusStatistics tickers from {len(pairs_data)} pairs")
        return response
        
    except Exception as e:
        logger.error(f"Error formatting enhanced VerusStatistics response: {e}")
        return {
            "code": "500000",
            "data": {
                "time": int(datetime.utcnow().timestamp() * 1000),
                "ticker": []
            }
        }

def format_cmc_dex_response(pairs_data: List[Dict]) -> Dict:
    """
    Format all pairs data into CMC DEX API response format
    
    Args:
        pairs_data: List of raw pair data
    
    Returns:
        Dict with composite keys and ticker data (DEX object format)
    """
    try:
        cmc_dex_data = {}
        
        for pair_data in pairs_data:
            composite_key, ticker_data = format_cmc_dex_ticker(pair_data)
            if composite_key and ticker_data:  # Only add if formatting succeeded
                cmc_dex_data[composite_key] = ticker_data
        
        logger.info(f" Formatted {len(cmc_dex_data)} CMC DEX tickers from {len(pairs_data)} pairs")
        return cmc_dex_data
        
    except Exception as e:
        logger.error(f"Error formatting CMC DEX response: {e}")
        return {}

def generate_coinmarketcap_tickers(pairs_data: List[Dict]) -> Dict:
    """
    Generate CoinMarketCap (CMC) DEX format tickers from pairs data
    Based on CMC DEX specification (Section C)
    Excludes pairs containing converter currencies (multi-currency baskets)
    
    Args:
        pairs_data: List of pair data from data integration
    
    Returns:
        Dictionary with sequential keys and ticker data (CMC DEX object format)
        Excludes converter currency pairs per filtering requirements
    """
    try:
        from dict import is_converter_currency
        
        cmc_tickers = {}
        key_counter = 1
        excluded_count = 0
        
        for pair_data in pairs_data:
            # Get currency IDs for filtering
            base_currency_id = pair_data.get('base_currency_id', '')
            target_currency_id = pair_data.get('target_currency_id', '')
            
            # Skip pairs that include converter currencies
            if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
                excluded_count += 1
                logger.debug(f"🚫 Excluding converter pair: {pair_data.get('base_currency', '')}-{pair_data.get('target_currency', '')}")
                continue
            
            composite_key, ticker_data = format_cmc_dex_ticker(pair_data)
            if composite_key and ticker_data:  # Only add if formatting succeeded
                # Use composite keys as per original format
                cmc_tickers[composite_key] = ticker_data
        
        logger.info(f"✅ Generated {len(cmc_tickers)} CMC DEX tickers with sequential keys (excluded {excluded_count} converter pairs)")
        return cmc_tickers
        
    except Exception as e:
        logger.error(f"Error generating CMC tickers: {e}")
        return {}

def generate_coinmarketcap_enhanced_tickers(pairs_data: List[Dict], use_cache: bool = False) -> Dict:
    """
    Generate Enhanced CoinMarketCap (CMC) DEX format tickers with Ethereum contract details
    Uses contract addresses and symbols (e.g., WETH instead of ETH) when available
    Excludes pairs containing converter currencies (multi-currency baskets)
    Aggregates data from multiple converters with the same trading pair per CMC DEX spec
    
    Args:
        pairs_data: List of pair data from data integration
    
    Returns:
        Dictionary with composite keys and aggregated ticker data (CMC DEX object format)
        Uses proper composite keys per CMC DEX specification (excluding converter pairs)
    """
    try:
        from dict import is_converter_currency
        
        # Temporary storage for aggregation
        pair_aggregation = {}
        excluded_count = 0
        
        for pair_data in pairs_data:
            # Get currency IDs for filtering
            base_currency_id = pair_data.get('base_currency_id', '')
            target_currency_id = pair_data.get('target_currency_id', '')
            
            # Skip pairs that include converter currencies
            if is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id):
                excluded_count += 1
                logger.debug(f"🚫 Excluding converter pair: {pair_data.get('base_currency', '')}-{pair_data.get('target_currency', '')}")
                continue
            
            composite_key, ticker_data = format_cmc_enhanced_ticker(pair_data, use_cache)
            if composite_key and ticker_data:
                if composite_key in pair_aggregation:
                    # Aggregate with existing data
                    existing = pair_aggregation[composite_key]
                    
                    # Sum volumes
                    existing_base_vol = float(existing['base_volume'])
                    existing_quote_vol = float(existing['quote_volume'])
                    new_base_vol = float(ticker_data['base_volume'])
                    new_quote_vol = float(ticker_data['quote_volume'])
                    
                    total_base_vol = existing_base_vol + new_base_vol
                    total_quote_vol = existing_quote_vol + new_quote_vol
                    
                    # Volume-weighted average price (using quote volume as weight)
                    existing_price = float(existing['last_price'])
                    new_price = float(ticker_data['last_price'])
                    
                    if existing_quote_vol + new_quote_vol > 0:
                        weighted_price = (existing_price * existing_quote_vol + new_price * new_quote_vol) / (existing_quote_vol + new_quote_vol)
                    else:
                        weighted_price = new_price  # Fallback to new price
                    
                    # Update aggregated data
                    pair_aggregation[composite_key].update({
                        'last_price': f"{weighted_price:.8f}",
                        'base_volume': f"{total_base_vol:.8f}",
                        'quote_volume': f"{total_quote_vol:.8f}"
                    })
                    
                    logger.debug(f"📊 Aggregated {composite_key}: volumes {existing_base_vol:.2f}+{new_base_vol:.2f}={total_base_vol:.2f}")
                else:
                    # First occurrence of this pair
                    pair_aggregation[composite_key] = ticker_data
        
        logger.info(f"✅ Generated {len(pair_aggregation)} enhanced CMC DEX tickers with aggregation (excluded {excluded_count} converter pairs)")
        return pair_aggregation
        
    except Exception as e:
        logger.error(f"Error generating enhanced CMC DEX tickers: {e}")
        return {}

def get_formatted_tickers(format_type: str = "coingecko") -> Dict:
    """
    Get formatted ticker data
    
    Args:
        format_type: "coingecko" or "verus_statistics"
    
    Returns:
        Dict containing formatted ticker data
    """
    try:
        # Import data integration functions
        from data_integration import extract_all_pairs_data, load_converter_data
        
        # Get raw ticker data
        raw_data = extract_all_pairs_data()
        
        if 'error' in raw_data:
            return {
                'error': raw_data['error'],
                'timestamp': datetime.utcnow().isoformat()
            }
        
        pairs_data = raw_data.get('pairs', [])
        
        if format_type == "coingecko":
            formatted_tickers = format_coingecko_response(pairs_data)
            return {
                'success': True,
                'format': 'coingecko',
                'timestamp': datetime.utcnow().isoformat(),
                'total_pairs': len(formatted_tickers),
                'tickers': formatted_tickers,
                'metadata': {
                    'block_range': raw_data.get('block_range', {}),
                    'total_converters': raw_data.get('total_converters', 0)
                }
            }
            
        elif format_type == "coingecko2":
            formatted_tickers = format_coingecko2_response(pairs_data)
            return {
                'success': True,
                'format': 'coingecko2',
                'timestamp': datetime.utcnow().isoformat(),
                'total_pairs': len(formatted_tickers),
                'tickers': formatted_tickers,
                'metadata': {
                    'block_range': raw_data.get('block_range', {}),
                    'total_converters': raw_data.get('total_converters', 0)
                }
            }
            
        elif format_type == "verus_statistics":
            formatted_response = format_verus_statistics_response(pairs_data)
            return formatted_response
            
        elif format_type == "verus_statistics_enhanced":
            formatted_response = format_verus_statistics_response_enhanced(pairs_data)
            return formatted_response
            
        elif format_type == "cmc":
            formatted_tickers = generate_coinmarketcap_tickers(pairs_data)
            return formatted_tickers  # CMC DEX with sequential keys to preserve all pairs
            
        else:
            return {
                'error': f'Unknown format type: {format_type}',
                'available_formats': ['coingecko', 'coingecko2', 'verus_statistics', 'verus_statistics_enhanced', 'cmc']
            }
            
    except Exception as e:
        logger.error(f"Error in get_formatted_tickers: {str(e)}")
        return {
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }

def test_ticker_formatting():
    """Test the ticker formatting module"""
    print("🧪 Testing Ticker Formatting Module")
    print("=" * 50)
    
    try:
        # Test CoinGecko format
        print("1. Testing CoinGecko format...")
        coingecko_data = get_formatted_tickers("coingecko")
        
        if 'error' in coingecko_data:
            print(f"   ❌ CoinGecko Error: {coingecko_data['error']}")
        else:
            tickers_count = len(coingecko_data.get('tickers', []))
            print(f"   ✅ CoinGecko: {tickers_count} tickers formatted")
            
            # Show sample ticker
            if tickers_count > 0:
                sample = coingecko_data['tickers'][0]
                print(f"   📊 Sample: {sample['ticker_id']} - Last: {sample['last_price']}")
        
        print()
        
        # Test VerusStatistics format
        print("2. Testing VerusStatistics format...")
        verus_data = get_formatted_tickers("verus_statistics")
        
        if verus_data.get('code') == "200000":
            tickers_count = len(verus_data['data'].get('ticker', []))
            print(f"   ✅ VerusStatistics: {tickers_count} tickers formatted")
            
            # Show sample ticker
            if tickers_count > 0:
                sample = verus_data['data']['ticker'][0]
                print(f"   📊 Sample: {sample['symbol']} - Last: {sample['last']}")
        else:
            print(f"   ❌ VerusStatistics Error: Code {verus_data.get('code')}")
        
        print("\n✅ Ticker formatting test completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Ticker formatting test failed: {str(e)}")
        return False

if __name__ == "__main__":
    test_ticker_formatting()
