#!/usr/bin/env python3
"""
VRSC Supply Endpoint
Provides VRSC total supply, converter reserves, and circulating supply information
"""

import json
import os
from datetime import datetime
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache for complete VRSC supply response (10-minute TTL)
_supply_response_cache = {
    'response': None,
    'timestamp': 0,
    'ttl': 600  # 10 minutes in seconds
}

def get_vrsc_reserves_from_converters():
    """
    Extract total VRSC reserves from all converters in converter_discovery.json
    
    Returns:
        tuple: (total_vrsc_reserves, converter_details_list)
    """
    total_vrsc_reserves = 0.0
    converter_details = []
    
    try:
        # Use relative path that works on any server
        converter_discovery_file = os.path.join(os.path.dirname(__file__), 'converter_discovery.json')
        
        if not os.path.exists(converter_discovery_file):
            logger.warning(f"Converter discovery file not found: {converter_discovery_file}")
            return total_vrsc_reserves, converter_details
        
        with open(converter_discovery_file, 'r') as f:
            data = json.load(f)
        
        # Extract VRSC reserves from all active converters
        for converter in data.get('active_converters', []):
            converter_name = converter.get('name', 'Unknown')
            
            # Look through reserve currencies for VRSC
            for reserve_currency in converter.get('reserve_currencies', []):
                if reserve_currency.get('ticker') == 'VRSC':
                    vrsc_amount = float(reserve_currency.get('reserves', 0))
                    if vrsc_amount > 0:
                        total_vrsc_reserves += vrsc_amount
                        converter_details.append({
                            'converter': converter_name,
                            'vrsc_reserve': vrsc_amount,
                            'currency_id': reserve_currency.get('currency_id', ''),
                            'chain': converter.get('chain', 'Unknown')
                        })
                        logger.info(f"Found {vrsc_amount} VRSC in {converter_name} converter")
                    break
        
        logger.info(f"Total VRSC in converters: {total_vrsc_reserves} from {len(converter_details)} converters")
        return total_vrsc_reserves, converter_details
        
    except Exception as e:
        logger.error(f"Error reading converter discovery file: {e}")
        return total_vrsc_reserves, converter_details

# Custom JSON response for pretty formatting
class PrettyJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            jsonable_encoder(content),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            separators=(',', ': ')
        ).encode('utf-8')

def _is_supply_response_cache_valid():
    """Check if the cached supply response is still valid"""
    current_time = time.time()
    return (_supply_response_cache['response'] is not None and 
            current_time - _supply_response_cache['timestamp'] < _supply_response_cache['ttl'])

def _update_supply_response_cache(response):
    """Update the supply response cache with complete response"""
    _supply_response_cache['response'] = response
    _supply_response_cache['timestamp'] = time.time()
    logger.info(f" VRSC supply response cached for {_supply_response_cache['ttl']} seconds")

async def get_vrsc_supply():
    """
    Get VRSC supply information including total supply, VRSC in converters, and circulating supply
    Caches complete response for 10 minutes to reduce external API calls and file I/O
    """
    # Pause background refresh for 3 minutes when this endpoint is called
    try:
        from cache_manager import get_cache_manager
        cache_manager = get_cache_manager()
        cache_manager.pause_refresh_for_verussupply()
    except Exception as e:
        logger.warning(f"Failed to pause background refresh: {e}")
    
    # Check cache first
    if _is_supply_response_cache_valid():
        cache_age = time.time() - _supply_response_cache['timestamp']
        logger.info(f" Serving cached VRSC supply data (age: {cache_age:.1f}s)")
        return _supply_response_cache['response']
    
    logger.info(" Cache expired, generating fresh VRSC supply data...")
    
    try:
        from verus_rpc import make_rpc_call
        from cache_manager import get_cache_manager
        
        # Method 1: Try external Verus API for total supply using coinsupply
        total_supply = None
        try:
            logger.info("Attempting external Verus API (coinsupply)...")
            import requests
            
            api_url = "https://api.verus.services"
            payload = {
                "method": "coinsupply",
                "params": [],
                "id": 1
            }
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(api_url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and 'supply' in data['result']:
                    total_supply = float(data['result']['supply'])
                    logger.info(f"✅ Got total supply from external API: {total_supply:,.2f} VRSC")
                else:
                    logger.warning(f"External API response missing supply field: {data}")
            else:
                logger.warning(f"External API returned status {response.status_code}")
                
        except Exception as e:
            logger.warning(f"External API failed: {e}")
        
        # Method 2: Try gettxoutsetinfo RPC call (reliable fallback)
        if total_supply is None:
            try:
                logger.info("Attempting gettxoutsetinfo RPC call...")
                result = make_rpc_call('VRSC', 'gettxoutsetinfo', [])
                if result and 'total_amount' in result:
                    total_supply = float(result['total_amount'])
                    logger.info(f"✅ Found total_amount from gettxoutsetinfo: {total_supply:,.2f}")
                else:
                    logger.warning("No total_amount field in gettxoutsetinfo result")
            except Exception as e:
                logger.warning(f"Failed to get supply from gettxoutsetinfo: {e}")
        
        # Final fallback: Fail if all methods don't work
        if total_supply is None:
            logger.error("All supply methods failed:")
            logger.error("- External API (coinsupply)")
            logger.error("- Local gettxoutsetinfo")
            
            raise HTTPException(
                status_code=503,
                detail="Unable to retrieve VRSC total supply. All methods failed."
            )
        
        # Get VRSC reserves from converters using dedicated function
        vrsc_in_converters, converter_details = get_vrsc_reserves_from_converters()
        data_source = "converter_discovery_file"
        
        # Calculate circulating supply
        circulating_supply = total_supply - vrsc_in_converters
        
        # Prepare response with CMC-compliant structure
        response_data = {
            "total_supply": total_supply,
            "circulating_supply": circulating_supply,
            "locked_supply": {
                "vrsc_in_converters": vrsc_in_converters,
                "converter_count": len(converter_details),
                "converter_details": converter_details
            },
            "supply_methodology": {
                "total_supply_source": "External Verus API (api.verus.services)",
                "locked_supply_source": "Converter smart contracts",
                "calculation": "Circulating = Total - Locked in Converters",
                "cmc_compliance": "Excludes smart contract locked tokens per CMC standards",
                "update_frequency": "60 seconds (cache refresh cycle)"
            },
            "timestamp": datetime.now().isoformat(),
            "data_source": data_source
        }
        
        response = PrettyJSONResponse(content=response_data)
        
        # Cache the complete response for future requests
        _update_supply_response_cache(response)
        
        return response
        
    except Exception as e:
        logger.error(f"Error in verussupply endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get VRSC supply information: {str(e)}"
        )
