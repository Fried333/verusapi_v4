#!/usr/bin/env python3
"""
Native Market Format Module
Formats cached pairs data into a structured response for any consumer.
Returns raw converter/pair/currency data — no normalization or deduplication.
Reuses the 60s cached price data from currency_price_cache and liquidity_calculator.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def format_native_market_data(cached_pairs_data: Dict, filter_basket_pairs: bool = True) -> Dict[str, Any]:
    """
    Transform cached pairs data + converter discovery into a native market response.

    Args:
        cached_pairs_data: Result from get_cached_pairs_data_only()
        filter_basket_pairs: If True, exclude pairs where either side is a basket/converter
                             token (needed for CoinGecko etc). If False, include all pairs
                             (native Verus market endpoint).

    Returns:
        Structured dict ready for JSON serialization
    """
    from data_integration import load_converter_data
    from currency_price_cache import get_vrsc_usd_price, _vrsc_usd_price
    from liquidity_calculator import get_chain_usd_price

    pairs_list: List[Dict] = cached_pairs_data.get('pairs', [])
    chain_heights: Dict[str, int] = cached_pairs_data.get('chain_heights', {})

    # Use already-cached VRSC/USD price (populated by the 60s background refresh).
    vrsc_usd = _vrsc_usd_price if _vrsc_usd_price > 0 else get_vrsc_usd_price()

    # ETH/USD — use Binance directly (fast, ~0.3s) since vETH != ETH in unit price.
    eth_usd = 0.0
    try:
        from currency_price_cache import get_binance_eth_price
        eth_usd = get_binance_eth_price()
    except Exception:
        pass

    # Load converter discovery for reserve/supply info (cached in memory)
    discovery_converters = load_converter_data(multi_chain=True)

    # Group pairs by converter name
    pairs_by_converter: Dict[str, List[Dict]] = {}
    for p in pairs_list:
        conv_name = p.get('converter', '')
        if conv_name:
            pairs_by_converter.setdefault(conv_name, []).append(p)

    # Build set of converter currency IDs to filter out basket token pairs
    converter_currency_ids = set()
    if filter_basket_pairs:
        for dc in discovery_converters:
            cid = dc.get('currency_id', '')
            if cid:
                converter_currency_ids.add(cid)

    # Build converters list
    converters_out: List[Dict] = []
    for dc in discovery_converters:
        conv_name = dc.get('name', '')
        if not conv_name:
            continue

        raw_pairs = pairs_by_converter.get(conv_name, [])

        # Filter out pairs where either side is a converter/basket token
        # (skipped when filter_basket_pairs=False for native market endpoint)
        reserve_pairs = []
        for p in raw_pairs:
            base_id = p.get('base_currency_id', '')
            target_id = p.get('target_currency_id', '')
            if base_id not in converter_currency_ids and target_id not in converter_currency_ids:
                reserve_pairs.append(p)

        # Build reserves
        reserves_out: List[Dict] = []
        for rc in dc.get('reserve_currencies', []):
            reserves_out.append({
                'currencyId': rc.get('currency_id', ''),
                'name': rc.get('ticker', ''),
                'weight': rc.get('weight', 0),
                'reserves': rc.get('reserves', 0),
            })

        # Build pairs — pass through raw data, no dedup or normalization.
        # OHLC values have been through universal inversion (1/raw_rate).
        pairs_out: List[Dict] = []
        for p in reserve_pairs:
            pairs_out.append({
                'base': p.get('base_currency', ''),
                'quote': p.get('target_currency', ''),
                'baseCurrencyId': p.get('base_currency_id', ''),
                'quoteCurrencyId': p.get('target_currency_id', ''),
                'lastPrice': p.get('last', 0),
                'open': p.get('open', 0),
                'high': p.get('high', 0),
                'low': p.get('low', 0),
                'baseVolume': p.get('base_volume', 0),
                'quoteVolume': p.get('target_volume', 0),
                'liquidityUsd': p.get('pair_liquidity_usd', 0),
            })

        # Total converter liquidity
        total_liq = 0.0
        if pairs_out:
            total_liq = max(p.get('liquidityUsd', 0) for p in pairs_out)
            for p in raw_pairs:
                if p.get('pair_liquidity_usd', 0) > total_liq:
                    total_liq = p['pair_liquidity_usd']

        chain = dc.get('chain', dc.get('source_chain', 'VRSC'))
        chain_display = {
            'VRSC': 'VRSC', 'CHIPS': 'CHIPS', 'VARRR': 'vARRR', 'VDEX': 'vDEX',
        }.get(chain, chain)

        converters_out.append({
            'name': conv_name,
            'currencyId': dc.get('currency_id', ''),
            'chain': chain_display,
            'supply': dc.get('supply', 0),
            'totalLiquidityUsd': total_liq,
            'reserves': reserves_out,
            'pairs': pairs_out,
        })

    # Build currencies list with USD prices
    currency_set: Dict[str, Dict] = {}

    # Add all currencies from converter reserves (skip unresolved i-addresses)
    for dc in discovery_converters:
        for rc in dc.get('reserve_currencies', []):
            ticker = rc.get('ticker', '')
            cid = rc.get('currency_id', '')
            if ticker and ticker not in currency_set and not (ticker.startswith('i') and len(ticker) > 20):
                currency_set[ticker] = {'name': ticker, 'currencyId': cid, 'priceUsd': 0}

    # Compute USD prices
    stablecoins = {
        'DAI', 'USDC', 'USDT', 'CRVUSD', 'TUSD', 'BUSD', 'FRAX',
        'DAI.vETH', 'USDC.vETH', 'USDT.vETH', 'TUSD.vETH', 'BUSD.vETH',
        'FRAX.vETH', 'scrvUSD.vETH', 'EURC', 'EURC.vETH',
    }
    chain_native_map = {
        'CHIPS': 'CHIPS',
        'vARRR': 'VARRR',
        'vDEX': 'VDEX',
    }

    # Set known prices first
    for name, data in currency_set.items():
        if name == 'VRSC':
            data['priceUsd'] = vrsc_usd
        elif name in stablecoins:
            data['priceUsd'] = 1.0
        elif name == 'WETH':
            data['priceUsd'] = eth_usd
        elif name in chain_native_map:
            data['priceUsd'] = get_chain_usd_price(chain_native_map[name])

    # Derive remaining prices via VRSC pairs.
    # The 'last' field has been through universal inversion (1/raw_close).
    # Raw OHLC close for base/target = "target units per 1 base unit".
    # After inversion: last = 1/raw = "base units per 1 target unit".
    #
    # For base=X, target=VRSC: raw = VRSC/X, last = 1/(VRSC/X) = X/VRSC
    #   → X_usd = last * vrsc_usd
    # For base=VRSC, target=X: raw = X/VRSC, last = 1/(X/VRSC) = VRSC/X
    #   → X_usd = vrsc_usd / last
    for name, data in currency_set.items():
        if data['priceUsd'] > 0:
            continue
        for p in pairs_list:
            base = p.get('base_currency', '')
            target = p.get('target_currency', '')
            last = p.get('last', 0)
            if last <= 0:
                continue
            if base == name and target == 'VRSC':
                # last = inverted rate; X_usd = last * vrsc_usd
                data['priceUsd'] = last * vrsc_usd
                break
            elif base == 'VRSC' and target == name:
                # last = inverted rate; X_usd = vrsc_usd / last
                data['priceUsd'] = vrsc_usd / last
                break

    currencies_out = sorted(currency_set.values(), key=lambda c: c['name'])

    # Normalize chain height keys for display
    block_heights = {}
    for k, v in chain_heights.items():
        display = {'VRSC': 'VRSC', 'CHIPS': 'CHIPS', 'VARRR': 'vARRR', 'VDEX': 'vDEX'}.get(k, k)
        block_heights[display] = v

    return {
        'vrscUsdPrice': vrsc_usd,
        'ethUsdPrice': eth_usd,
        'blockHeights': block_heights,
        'converters': converters_out,
        'currencies': currencies_out,
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }
