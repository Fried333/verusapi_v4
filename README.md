# Verus Ticker API v4

**Version:** 4.0 | **Port:** 8765

A standalone API serving Verus blockchain trading pair data to volume aggregators (CoinGecko, CoinMarketCap, CoinPaprika). Built as an optimized rewrite of v3 with identical output.

## v3 vs v4: What Changed

v4 produces **byte-identical output** to v3 across all 4 endpoints. The calculation logic, price inversion, volume extraction, and USD conversion methodology are completely unchanged. The difference is purely in how efficiently the data is gathered.

### RPC Call Reduction: 286 → ~40 per refresh (86% fewer)

| Optimization | v3 Behaviour | v4 Behaviour | Calls Saved |
|---|---|---|---|
| Block heights | `getinfo` called per-currency per-converter | Fetched once per chain at start of cycle | ~200 |
| Converter liquidity | `estimateconversion` + `getinfo` per-pair | Computed once per converter, weight math done inline | ~40 |
| `.env` loading | `load_dotenv()` on every RPC call | Loaded once at module init | N/A (CPU) |
| Converter discovery | `converter_discovery.json` read from disk every cycle | Cached in memory with mtime check | N/A (I/O) |
| VRSC USD price | Separate cache module with own refresh | Same module, but no duplicate implementations | ~2 |

### Performance Improvement

| Metric | v3 | v4 |
|---|---|---|
| Cached endpoint response | ~280ms | ~21ms |
| RPC calls per 60s refresh | ~286 | ~40 |
| Log lines per refresh | ~9,600 | ~360 |

### What Was NOT Changed

- **Price inversion logic** — blockchain internal rates inverted via `1/price` with high/low swap
- **Volume extraction** — `getcurrencystate` with per-chain block ranges and `volumepairs` parsing
- **USD conversion chain** — VRSC→vETH→ETH USD (CoinGecko/Binance fallback)
- **PBaaS USD pricing** — Chain→VRSC via bridge→USD
- **Liquidity formula** — `(weight_A + weight_B) / total_weight * converter_liquidity`
- **Pair generation** — all N*(N-1) directional pairs per converter
- **Volume-weighted price aggregation** — quote volume weighting for multi-converter pairs
- **Stablecoin handling** — hardcoded at $1.00
- **Exchange format output** — all field names, decimal precision, filtering rules identical
- **bid/ask** — set to `last_price` (no order book on AMM)

### Validated Match (2026-03-11)

| Endpoint | Items | Fields Checked | Mismatches |
|---|---|---|---|
| `/coingecko` | 105 | 1,365 | 0 (liquidity differs ~0.015% due to refresh timing) |
| `/coinpaprika` | 60 tickers | all | 0 (only `time` ms differs) |
| `/coinmarketcap` | 62 | 558 | 0 |
| `/coinmarketcap_iaddress` | 75 | 675 | 0 |

### Code Changes

- **`verus_rpc.py`** — Connection pooling (`requests.Session` per chain), `threading.Semaphore(5)` concurrency limiter, retry with exponential backoff on transient errors, `httpx.AsyncClient` support, cached RPC config
- **`data_integration.py`** — Per-chain block height fetched once, converter liquidity computed once per converter with inline weight math, in-memory converter discovery cache
- **`liquidity_calculator.py`** — Per-refresh-cycle cache, deduplicated USD price source (single `currency_price_cache` module), extracted `_get_native_ratio()` helper
- **`block_height.py`** — Thread-safe with `threading.Lock()`
- **`dict.py`** — Module-level `.env` loading instead of per-call

## API Endpoints

### Production (60s cache)

| Endpoint | Format | Description |
|---|---|---|
| `/coingecko` | JSON array | CoinGecko DEX ticker format |
| `/coinmarketcap` | JSON object | CMC DEX format with ERC20 contract addresses |
| `/coinmarketcap_iaddress` | JSON object | CMC format with Verus i-addresses |
| `/coinpaprika` | JSON object | CoinPaprika allTickers format |

### Other

| Endpoint | Description |
|---|---|
| `/health` | Server status, RPC connection, cache info |
| `/stats` | HTML page with USD volumes and currency prices |
| `/verussupply` | VRSC supply information |

## Setup

### Requirements

- Python 3.8+
- Verus daemon(s) running with RPC access
- `pip install -r requirements.txt` (fastapi, uvicorn, requests, httpx, python-dotenv)

### Configuration

Create `.env`:

```env
VERUS_RPC_HOST=127.0.0.1
VERUS_RPC_PORT=27486
VERUS_RPC_USER=your_user
VERUS_RPC_PASSWORD=your_password

# PBaaS chains (optional)
CHIPS_RPC_HOST=127.0.0.1
CHIPS_RPC_PORT=22778
CHIPS_RPC_USER=your_user
CHIPS_RPC_PASSWORD=your_password

VARRR_RPC_HOST=127.0.0.1
VARRR_RPC_PORT=20778
VARRR_RPC_USER=your_user
VARRR_RPC_PASSWORD=your_password

VDEX_RPC_HOST=127.0.0.1
VDEX_RPC_PORT=21778
VDEX_RPC_USER=your_user
VDEX_RPC_PASSWORD=your_password

# Chain block times
VRSC_BLOCKS_PER_DAY=1440
CHIPS_BLOCKS_PER_DAY=1440
VARRR_BLOCKS_PER_DAY=720
VDEX_BLOCKS_PER_DAY=1440
```

### Run

```bash
python3 main.py
```

Runs on port 8765 (drop-in replacement for v3). Background cache refresh every 60 seconds.

## Calculation Methodology

### Price Derivation

1. `getcurrencystate(converter, blockRange, volumeCurrency)` returns `volumepairs` with OHLC per currency pair
2. Blockchain returns internal AMM rates — these are inverted (`1/price`) to get market convention prices
3. High/low are swapped during inversion (`new_high = 1/old_low`)

### Volume

- `base_volume`: from `getcurrencystate` call with `volumeCurrency = base_currency`
- `target_volume`: from `getcurrencystate` call with `volumeCurrency = target_currency`
- Both directions (A-B and B-A) are generated as separate pairs

### USD Pricing

- **VRSC**: `estimateconversion(VRSC→vETH via NATI)` * ETH USD price (CoinGecko, Binance fallback)
- **Stablecoins** (DAI, USDC, USDT, etc.): hardcoded $1.00
- **PBaaS chains** (CHIPS, vARRR, vDEX): `estimateconversion(chain→VRSC via bridge)` * VRSC USD
- **Other currencies**: `estimateconversion(currency→VRSC via converter)` * VRSC USD
- **USD volume**: `base_volume * base_currency_usd_rate`

### Liquidity

- Converter total liquidity: `supply * native_ratio * native_usd_price`
- Pair liquidity: `(weight_A + weight_B) / total_weight * converter_liquidity`
