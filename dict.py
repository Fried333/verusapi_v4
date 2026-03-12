import os
import json
from dotenv import load_dotenv


# Load env once at module level
load_dotenv(".env", override=True)

def get_min_native_tokens(chain):
    """
    Get minimum native token threshold for a specific chain from environment variables

    Args:
        chain (str): Chain name (VRSC, CHIPS, VARRR, VDEX)

    Returns:
        float: Minimum native token threshold for the chain
    """
    # Try chain-specific threshold first
    env_key = f"{chain}_MIN_NATIVE_TOKENS"
    threshold = os.getenv(env_key)
    
    if threshold is not None:
        return float(threshold)
    
    # Fall back to global default
    global_default = os.getenv("DEFAULT_MIN_NATIVE_TOKENS", "100")
    return float(global_default)

# Global variable to cache the currency mapping
_currency_mapping_cache = None

def load_currency_mappings():
    """Load currency mappings from JSON configuration file
    
    Returns:
        dict: Currency contract mapping data
    """
    global _currency_mapping_cache
    
    if _currency_mapping_cache is not None:
        return _currency_mapping_cache
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'currency_mappings.json')
        with open(config_path, 'r') as f:
            data = json.load(f)
            _currency_mapping_cache = data.get('currency_contract_mapping', {})
            return _currency_mapping_cache
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load currency mappings: {e}")
        _currency_mapping_cache = {}
        return _currency_mapping_cache

# Required helper functions for currency name normalization
def normalize_currency_name(name):
    """Normalize currency name - DISABLED for now to use actual currency names
    
    Args:
        name (str): Currency name to normalize
        
    Returns:
        str: Currency name unchanged (normalization disabled)
    """
    # Normalization disabled - return actual currency names
    return name

def get_ticker_by_id(currency_id):
    """Get ticker symbol from currency ID using currency_contract_mapping
    
    Args:
        currency_id (str): Currency ID to look up
        
    Returns:
        str: Ticker symbol if found, otherwise the original ID
    """
    # Load currency mappings dynamically
    currency_contract_mapping = load_currency_mappings()
    
    # First try to look up in our currency_contract_mapping
    contract_info = currency_contract_mapping.get(currency_id)
    if contract_info and isinstance(contract_info, dict):
        # Use VRSC symbol as the default ticker
        return contract_info.get('vrsc_symbol')
    
    # If not found, extract from the ID name if possible
    if '.' in currency_id:
        return currency_id  # Use full currency ID, no short names
    
    # Default: return original ID
    return currency_id

def get_mapped_eth_address(currency_id):
    """Get Ethereum contract address for a currency ID from mapping
    
    Args:
        currency_id (str): Currency ID to look up
        
    Returns:
        str: Ethereum contract address or None if not found
    """
    currency_contract_mapping = load_currency_mappings()
    contract_info = currency_contract_mapping.get(currency_id)
    if contract_info and isinstance(contract_info, dict):
        return contract_info.get('address')
    return None

def get_currency_id_by_name(currency_name):
    """Get currency ID from currency name using vrsc_symbol mapping
    
    Args:
        currency_name (str): Currency name to look up
        
    Returns:
        str: Currency ID or None if not found
    """
    currency_contract_mapping = load_currency_mappings()
    for currency_id, contract_info in currency_contract_mapping.items():
        if isinstance(contract_info, dict):
            vrsc_symbol = contract_info.get('vrsc_symbol')
            if vrsc_symbol == currency_name:
                return currency_id
    return None

def get_mapped_eth_symbol(currency_name):
    """Get Ethereum symbol for a currency name from mapping
    
    Args:
        currency_name (str): Currency name to look up
        
    Returns:
        str: ETH symbol or None if not found
    """
    # First get the currency ID from the name
    currency_id = get_currency_id_by_name(currency_name)
    if not currency_id:
        return None
        
    currency_contract_mapping = load_currency_mappings()
    contract_info = currency_contract_mapping.get(currency_id)
    if contract_info and isinstance(contract_info, dict):
        return contract_info.get('eth_symbol')
    return None

def get_mapped_vrsc_symbol(currency_id):
    """Get VRSC symbol for a currency ID from mapping
    
    Args:
        currency_id (str): Currency ID to look up
        
    Returns:
        str: VRSC symbol or None if not found
    """
    currency_contract_mapping = load_currency_mappings()
    contract_info = currency_contract_mapping.get(currency_id)
    if contract_info and isinstance(contract_info, dict):
        return contract_info.get('vrsc_symbol')
    return None

def get_symbol_for_currency(currency_id):
    """Get appropriate symbol for a currency ID (ETH for exported, VRSC for native)
    
    Args:
        currency_id (str): Currency ID to look up
        
    Returns:
        str: ETH symbol if currency is exported to Ethereum, VRSC symbol otherwise, or None if not found
    """
    currency_contract_mapping = load_currency_mappings()
    contract_info = currency_contract_mapping.get(currency_id)
    if contract_info and isinstance(contract_info, dict):
        # If currency has an Ethereum contract address, use ETH symbol
        if contract_info.get('address'):
            return contract_info.get('eth_symbol')
        # Otherwise use VRSC symbol
        else:
            return contract_info.get('vrsc_symbol')
    return None

def is_currency_exported_to_ethereum(currency_id):
    """Check if currency is exported to Ethereum (has contract address)
    
    Args:
        currency_id (str): Currency ID to check
        
    Returns:
        bool: True if currency has Ethereum contract address
    """
    currency_contract_mapping = load_currency_mappings()
    return currency_id in currency_contract_mapping

# Excluded currency IDs - these should not appear in CoinGecko/CoinMarketCap endpoints
# Filtering is done by currency ID
excluded_currency_ids = [
    "i3f7tSctFkiPpiedY8QR5Tep9p4qDVebDx",  # Bridge.vETH
    "iG1jouaqSJayNb9LCqPzb3yFYD3kUpY2P2",  # whales
    "iHnYAmrS45Hb8GVgyzy7nVQtZ5vttJ9N3X",  # SUPERVRSC
    "iFrFn9b6ctse7XBzcWkRbpYMAHoKjbYKqG",  # SUPER🛒
    "i4Xr5TAMrDTD99H69EemhjDxJ4ktNskUtc",  # Switch
    "i9kVWKU2VwARALpbXn4RS9zvrhvNRaUibb",  # Kaiju
    "iH37kRsdfoHtHK5TottP1Yfq8hBSHz9btw",  # NATI🦉
    "iHax5qYQGbcMGqJKKrPorpzUBX2oFFXGnY",  # Pure
    "iAik7rePReFq2t7LZMZhHCJ52fT5pisJ5C",  # vYIELD
    "iRt7tpLewArQnRddBVFARGKJStK6w5pDmC",  # NATI
    "i3nokiCTVevZMLpR3VmZ7YDfCqA5juUqqH",  # Bridge.CHIPS
    "iNLBYPcNM3c5mzRdtfjd9Hk86WPijQfZhW",  # Highroller.CHIPS
    "iDetLA1snrDVhCCk42rdWfqmJcYCMcEFry",  # Bankroll.CHIPS
    "iD5WRg7jdQM1uuoVHsBCAEKfJCKGs1U3TB",  # Bridge.VARRR
    "i6j1rzjgrDhSmUYiTtp21J8Msiudv5hgt9",  # Bridge.VDEX




]

def is_converter_currency(currency_id):
    """
    Check if a currency ID is a converter currency
    
    Args:
        currency_id (str): Currency ID to check
        
    Returns:
        bool: True if currency is a converter, False otherwise
    """
    return currency_id in excluded_currency_ids

def get_currency_info_by_id(currency_id):
    """Get complete currency information from currency ID
    
    Args:
        currency_id (str): Currency ID to look up
        
    Returns:
        dict: Currency info with ticker and contract address if available
    """
    # Get ticker from currency_names
    ticker = get_ticker_by_id(currency_id)
    
    # Get contract address if available
    contract_address = get_mapped_eth_address(currency_id)
    
    return {
        "currencyid": currency_id,
        "ticker": ticker,
        "mappedethaddress": contract_address
    }
