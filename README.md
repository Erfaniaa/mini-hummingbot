Mini-Hummingbot (PancakeSwap CLI)

Getting started
- Create a Python 3.10+ venv
- Install deps: `pip install -r requirements.txt`
- Run the CLI: `python -m cli.main`

Features (phase 1)
- Encrypted keystore (multiple wallets)
- Token registry (PancakeSwap lists; copy JSON files into `tokens/`)
- Connector abstraction and PancakeSwap connector wrapper
- CLI (wallet add/list/remove + strategies menu)

Strategies
- dex_simple_swap: one-time market swap
- dex_pure_market_making: symmetric levels with periodic refresh
- dex_batch_swap: one-sided ladder across price range
- dex_dca: interval-based allocation (uniform/random)

Notes
- Shows tx hash and BscScan link on executions
- Robust error handling and retries; strategies keep running on network issues