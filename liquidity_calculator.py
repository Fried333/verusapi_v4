#!/usr/bin/env python3
"""
Liquidity Calculator Module
Implements pair liquidity calculation using proven working code from Deploy.
Formula: Pair Liquidity = Total Converter Liquidity x (Weight of Currency A + Weight of Currency B)
"""

import logging
from typing import Dict
import sys
import os

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from verus_rpc import make_rpc_call
from dict import get_ticker_by_id
from currency_price_cache import get_vrsc_usd_price

logger = logging.getLogger(__name__)

# Per-refresh-cycle cache for converter liquidity results
# Cleared by calling clear_converter_liquidity_cache() at start of each refresh
_converter_liquidity_cache: Dict[str, float] = {}


def clear_converter_liquidity_cache():
    """Clear the converter liquidity cache. Call at the start of each refresh cycle."""
    global _converter_liquidity_cache
    _converter_liquidity_cache.clear()


def get_chain_to_vrsc_rate(chain: str) -> float:
    """
    Get conversion rate from any chain's native currency to VRSC via bridge.

    Args:
        chain: Chain name (CHIPS, VARRR, VDEX, etc.)

    Returns:
        Conversion rate (native currency to VRSC)
    """
    try:
        bridge_map = {
            'CHIPS': 'Bridge.CHIPS',
            'VARRR': 'Bridge.vARRR',
            'VDEX': 'Bridge.vDEX',
        }
        bridge_name = bridge_map.get(chain, f'Bridge.{chain}')

        conversion_params = {'currency': chain, 'convertto': 'VRSC', 'amount': 1, 'via': bridge_name}
        conversion_result = make_rpc_call(chain, 'estimateconversion', [conversion_params])

        if conversion_result and 'estimatedcurrencyout' in conversion_result:
            rate = float(conversion_result['estimatedcurrencyout'])
            logger.info(f"Got {chain}->VRSC rate via {bridge_name}: {rate}")
            return rate

        logger.error(f"Failed to get {chain}->VRSC conversion via {bridge_name}")
        return 0.0

    except Exception as e:
        logger.error(f"Error getting {chain}->VRSC conversion: {e}")
        return 0.0


def get_chain_usd_price(chain: str) -> float:
    """
    Get USD price for any chain's native currency.
    Multi-step conversion: Chain -> VRSC -> USD.

    Args:
        chain: Chain name (CHIPS, VARRR, VDEX, etc.)

    Returns:
        USD price per native currency unit
    """
    try:
        chain_to_vrsc_rate = get_chain_to_vrsc_rate(chain)
        if chain_to_vrsc_rate <= 0:
            return 0.0

        vrsc_usd_price = get_vrsc_usd_price()
        if vrsc_usd_price <= 0:
            return 0.0

        chain_usd_price = chain_to_vrsc_rate * vrsc_usd_price
        logger.info(f"Calculated {chain} USD price: {chain_usd_price} (rate: {chain_to_vrsc_rate} x VRSC: {vrsc_usd_price})")
        return chain_usd_price

    except Exception as e:
        logger.error(f"Error calculating {chain} USD price: {e}")
        return 0.0


def get_converter_liquidity(converter_name: str, converters_data: Dict, min_liquidity_threshold: float = 1000.0) -> float:
    """
    Calculate total liquidity for a converter in USD.
    Results are cached per converter name for the duration of a refresh cycle.

    Args:
        converter_name: Name of the converter
        converters_data: Converter discovery data
        min_liquidity_threshold: Minimum supply threshold in native currency (default: 1000)

    Returns:
        Total liquidity in USD (0 if below threshold)
    """
    # Check per-cycle cache first
    if converter_name in _converter_liquidity_cache:
        return _converter_liquidity_cache[converter_name]

    result = _calculate_converter_liquidity(converter_name, converters_data, min_liquidity_threshold)

    # Cache the result (even 0.0, to avoid repeated failed lookups)
    _converter_liquidity_cache[converter_name] = result
    return result


def _calculate_converter_liquidity(converter_name: str, converters_data: Dict, min_liquidity_threshold: float) -> float:
    """Internal: compute converter liquidity without caching."""
    try:
        # Find the converter in the data
        converter_info = None
        for conv in converters_data:
            if conv.get('name') == converter_name:
                converter_info = conv
                break

        if not converter_info:
            logger.error(f"Converter {converter_name} not found in data")
            return 0.0

        converter_id = converter_info.get('currency_id')
        supply = float(converter_info.get('supply', 0))

        if not converter_id or supply <= 0:
            logger.error(f"Invalid converter ID or supply for {converter_name}")
            return 0.0

        # Apply minimum liquidity threshold early
        if supply < min_liquidity_threshold:
            logger.info(f"Converter {converter_name} below threshold: {supply} < {min_liquidity_threshold}")
            return 0.0

        # Step 1: Get converter to native chain currency conversion ratio
        source_chain = converter_info.get('source_chain', 'VRSC')
        native_ratio = _get_native_ratio(converter_name, converter_id, source_chain)

        if native_ratio <= 0:
            logger.error(f"Could not get valid native currency ratio for {converter_name}")
            return 0.0

        # Step 2: Get native currency to USD price
        if source_chain == 'VRSC':
            native_usd_price = get_vrsc_usd_price()
        else:
            native_usd_price = get_chain_usd_price(source_chain)

        if native_usd_price <= 0:
            logger.error(f"Could not get valid {source_chain}->USD price")
            return 0.0

        # Step 3: Calculate total liquidity = supply x native_ratio x native_USD_price
        total_liquidity = supply * native_ratio * native_usd_price

        logger.info(f"Liquidity for {converter_name} (Chain: {source_chain}): "
                     f"supply={supply}, ratio={native_ratio}, usd={native_usd_price}, total=${total_liquidity:.2f}")

        return total_liquidity

    except Exception as e:
        logger.error(f"Error calculating converter liquidity for {converter_name}: {e}")
        return 0.0


def _get_native_ratio(converter_name: str, converter_id: str, source_chain: str) -> float:
    """Get the conversion ratio from converter currency to the chain's native currency."""
    try:
        if source_chain == 'VRSC':
            convert_to = 'VRSC'
        else:
            convert_to = source_chain

        conversion_params = {'currency': converter_id, 'convertto': convert_to, 'amount': 1}
        conversion_result = make_rpc_call(source_chain, 'estimateconversion', [conversion_params])

        if conversion_result and 'estimatedcurrencyout' in conversion_result:
            ratio = float(conversion_result['estimatedcurrencyout'])
            logger.info(f"Got {converter_name} to {convert_to} ratio: {ratio}")
            return ratio

        return 0.0
    except Exception as e:
        logger.error(f"Error getting {converter_name} to native conversion: {e}")
        return 0.0


def get_pair_liquidity(converter_name: str, base_currency: str, target_currency: str, converters_data: Dict) -> float:
    """
    Calculate the liquidity for a specific trading pair in a converter.
    Formula: (weight1 + weight2) / total_weight * total_liquidity

    Args:
        converter_name: Name of the converter
        base_currency: Base currency of the pair
        target_currency: Target currency of the pair
        converters_data: Converter discovery data

    Returns:
        Pair liquidity in USD
    """
    try:
        total_liquidity = get_converter_liquidity(converter_name, converters_data)
        if total_liquidity <= 0:
            return 0.0

        # Find the converter in the data
        converter_info = None
        for conv in converters_data:
            if conv.get('name') == converter_name:
                converter_info = conv
                break

        if not converter_info:
            logger.error(f"Converter {converter_name} not found in data")
            return 0.0

        # Get weights for the currencies
        base_weight = 0
        target_weight = 0
        total_weight = 0

        reserve_currencies = converter_info.get('reserve_currencies', [])
        for rc in reserve_currencies:
            weight = float(rc.get('weight', 0))
            total_weight += weight

            currency_ticker = rc.get('ticker', '')
            if currency_ticker == base_currency:
                base_weight = weight
            if currency_ticker == target_currency:
                target_weight = weight

        # Check if converter currency is one of the pair currencies (special case)
        base_is_converter = (base_currency == converter_name)
        target_is_converter = (target_currency == converter_name)

        if base_is_converter or target_is_converter:
            non_converter_weight = target_weight if base_is_converter else base_weight
            if non_converter_weight > 0 and total_weight > 0:
                weight_fraction = non_converter_weight / total_weight
                return (weight_fraction * total_liquidity) * 2
            return 0.0
        else:
            if base_weight > 0 and target_weight > 0 and total_weight > 0:
                combined_weight_fraction = (base_weight + target_weight) / total_weight
                return combined_weight_fraction * total_liquidity
            return 0.0

    except Exception as e:
        logger.error(f"Error calculating pair liquidity for {base_currency}-{target_currency} in {converter_name}: {e}")
        return 0.0


if __name__ == "__main__":
    from data_integration import load_converter_data

    print("Testing Liquidity Calculator")
    print("=" * 50)

    converters_data = load_converter_data()
    if not converters_data:
        print("No converter data available")
    else:
        converter_name = "Bridge.vETH"
        total_liquidity = get_converter_liquidity(converter_name, converters_data)
        print(f"Total {converter_name} liquidity: ${total_liquidity:.2f}")

        pair_liquidity = get_pair_liquidity(converter_name, "VRSC", "DAI.vETH", converters_data)
        print(f"VRSC-DAI.vETH pair liquidity: ${pair_liquidity:.2f}")

        print("\nLiquidity calculator test completed!")
