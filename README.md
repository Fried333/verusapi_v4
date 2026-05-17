# Verus Ticker API v4

> **Status:** Currently the live ticker source for Verus volume-aggregator listings (CoinGecko, CoinMarketCap, CoinPaprika). The longer-term plan is for the [scan-verus-cx](https://github.com/Fried333/scan-verus-cx) explorer's market-worker to absorb this — until then, v4 is the standalone serving path.

Python/FastAPI service that aggregates Verus DEX trading-pair data from local `verusd` daemons (VRSC + PBaaS) and serves it in CoinGecko / CMC / Coinpaprika formats. Drop-in replacement for [v3](https://github.com/Fried333/verusapi_v3) with byte-identical output and ~7× less RPC load.

## Table of contents

- [What you get](#what-you-get)
- [What you provide](#what-you-provide)
- [Quick start](#quick-start)
- [API endpoints](#api-endpoints)
- [Calculation methodology](#calculation-methodology)
- [Configuration](#configuration)
- [v3 → v4 differences](#v3--v4-differences)
- [Operating in production](#operating-in-production)
- [License](#license)
- [Disclaimer](#disclaimer)

## What you get

- DEX ticker data (price, volume, liquidity) for every Verus converter on VRSC + PBaaS chains, served in three aggregator formats
- A native explorer endpoint (`/verus/market`) that exposes the full converter+pair+USD-price set without the aggregator filters (used by [scan.verus.cx](https://scan.verus.cx))
- 60-second cached endpoints (~21 ms response); ~40 RPC calls per refresh cycle
- Volume-weighted price aggregation across multiple converters trading the same pair
- USD pricing via on-chain conversion paths with CoinGecko/Binance fallback only for VRSC→USD anchor

## What you provide

- Python 3.8+
- A running local `verusd` for each chain you want to index (VRSC required; CHIPS, vARRR, vDEX optional)
- RPC credentials for each chain (read from `.env`)

## Quick start

```bash
git clone https://github.com/Fried333/verusapi_v4.git
cd verusapi_v4
pip install -r requirements.txt
cp env_format .env
$EDITOR .env                   # fill RPC creds for each chain

# One-time: build the converter list from current chain state
python3 converter_discovery.py

python3 main.py
# → http://localhost:8765
```

Sanity check:
```bash
curl http://localhost:8765/health
curl http://localhost:8765/coingecko | head -c 200
```

Re-run `converter_discovery.py` when new baskets appear on-chain.

## API endpoints

### Aggregator-facing (60 s cache)

| Endpoint | Format | Notes |
|---|---|---|
| `GET /coingecko` | JSON array | CoinGecko DEX ticker format |
| `GET /coinmarketcap` | JSON object | CMC DEX format with ERC20 contract addresses |
| `GET /coinmarketcap_iaddress` | JSON object | CMC format using Verus i-addresses instead of ERC20s |
| `GET /coinpaprika` | JSON object | Coinpaprika allTickers format |

### Explorer-native

| Endpoint | Description |
|---|---|
| `GET /verus/market` | All converters + pairs (including basket-token pairs, which the aggregator endpoints filter out) with USD prices. Consumed by [scan.verus.cx](https://scan.verus.cx)'s market UI. |

### Operational

| Endpoint | Description |
|---|---|
| `GET /health` | RPC connection, cache freshness, block heights |
| `GET /stats` | HTML page rendering USD volumes + currency prices |
| `GET /verussupply` | VRSC supply info |

## Calculation methodology

### Price derivation

1. `getcurrencystate(converter, blockRange, volumeCurrency)` returns `volumepairs` with OHLC per pair
2. Daemon emits **internal AMM rates** — v4 inverts them via `1/price` to get market convention prices
3. High/low are swapped during inversion (`new_high = 1/old_low`)

### Volume

- `base_volume`: from `getcurrencystate` called with `volumeCurrency = base_currency`
- `target_volume`: same call with `volumeCurrency = target_currency`
- Both directions (A→B and B→A) generated as separate pairs

### USD pricing chain

| Currency class | USD source |
|---|---|
| **VRSC** | `estimateconversion(VRSC→vETH via NATI)` × ETH USD (CoinGecko, Binance fallback) |
| **Stablecoins** (DAI, USDC, USDT) | hardcoded $1.00 |
| **PBaaS native** (CHIPS, vARRR, vDEX) | `estimateconversion(chain→VRSC via bridge)` × VRSC USD |
| **Other** | `estimateconversion(currency→VRSC via converter)` × VRSC USD |
| **USD volume** | `base_volume × base_currency_usd_rate` |

### Liquidity

- Converter total: `supply × native_ratio × native_usd_price`
- Per-pair: `(weight_A + weight_B) / total_weight × converter_liquidity`

### Stablecoin policy

Hardcoded $1.00 — the chain has no opinion on bridged stablecoin de-peg risk, and our oracle isn't qualified to second-guess external markets. Out-of-band events (depeg, bridge issue) would invalidate the values; this is documented behaviour, not a bug.

## Configuration

`.env` shape (one block per chain you index):

```env
# VRSC (required)
VERUS_RPC_HOST=127.0.0.1
VERUS_RPC_PORT=27486
VERUS_RPC_USER=your_user
VERUS_RPC_PASSWORD=your_password

# PBaaS — repeat for CHIPS, VARRR, VDEX (each block optional)
CHIPS_RPC_HOST=127.0.0.1
CHIPS_RPC_PORT=22778
CHIPS_RPC_USER=your_user
CHIPS_RPC_PASSWORD=your_password

# … same for VARRR_*, VDEX_*

# Chain block times (for volume window math)
VRSC_BLOCKS_PER_DAY=1440
CHIPS_BLOCKS_PER_DAY=1440
VARRR_BLOCKS_PER_DAY=720
VDEX_BLOCKS_PER_DAY=1440
```

See `env_format` in the repo for the full template.

## v3 → v4 differences

Output is byte-identical (validated 2026-03-11 across 105 CoinGecko items / 1,365 fields, 60 CoinPaprika tickers, 62 CMC items, 75 CMC-iaddress items — zero mismatches). Implementation is what got tightened:

### Performance

| Metric | v3 | v4 |
|---|---|---|
| Cached endpoint response | ~280 ms | ~21 ms |
| RPC calls / 60-s cycle | ~286 | ~40 |
| Log lines / cycle | ~9,600 | ~360 |

### What changed

| Area | v3 | v4 |
|---|---|---|
| Block heights | `getinfo` per-currency per-converter | Fetched once per chain per cycle (~200 calls saved) |
| Converter liquidity | `estimateconversion` + `getinfo` per-pair | Computed once per converter, weights inline (~40 saved) |
| `.env` loading | `load_dotenv()` on every RPC call | Loaded once at module init |
| Converter discovery | JSON re-read every cycle | In-memory cache with mtime check |
| VRSC USD price | Two duplicate implementations | Single shared module (~2 saved) |
| Concurrency | none | `requests.Session` pool per chain, `threading.Semaphore(5)` cap, retry with backoff |

### What did NOT change

Price inversion, volume extraction, USD chain, PBaaS bridging, liquidity formula, pair generation, volume-weighting, stablecoin policy, output field names/precision, bid/ask = last_price. **All output rules are byte-stable across the v3 → v4 boundary.**

## Operating in production

### Logs

stdout/stderr from `python3 main.py`. Quieter than v3 by ~26× (~360 lines/cycle vs ~9,600). Run under systemd for `journalctl -u verusapi_v4 -f`.

### Common errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` shows RPC disconnected | wrong creds, daemon down, wrong port | Verify with `verus -chain=<X> getinfo` using same creds |
| `converter_discovery.json: file not found` | first run hasn't generated it | `python3 converter_discovery.py` then restart |
| Pair missing from output | new basket on-chain | Re-run `converter_discovery.py`, restart |
| `/coingecko` returns empty `[]` | all converters discovery'd to unhealthy | Check chain sync state for the PBaaS daemons |
| USD prices way off | VRSC→USD anchor failing (CoinGecko + Binance both unreachable) | Check outbound DNS / TLS; cached value persists until next refresh |

### Upgrading

```bash
git pull
pip install -r requirements.txt    # in case deps changed
python3 converter_discovery.py     # in case the basket set changed
systemctl restart verusapi_v4
```

### Backup considerations

Stateless — nothing to back up. The only persistent artifact is `converter_discovery.json`, which can be regenerated at any time.

## License

MIT — see [LICENSE](./LICENSE) if present, or the standard MIT terms.

## Disclaimer

This software is provided **"AS IS"**, without warranty of any kind, express or implied. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability arising from the use of this software. Aggregators consuming this feed should run their own sanity checks before publishing USD-denominated values.
