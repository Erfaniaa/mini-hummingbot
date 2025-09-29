Mini-Hummingbot (PancakeSwap CLI)

Getting started
- Create a Python 3.10+ venv
- Install deps: `pip install -r requirements.txt`
- Run the CLI: `python -m cli.main`

Features
- Encrypted keystore (multiple wallets)
- Token registry (PancakeSwap lists; copy JSON files into `tokens/`)
- Connector abstraction and PancakeSwap connector wrapper
- CLI (wallet add/list/remove + strategies menu)
- PancakeSwap v2 and v3 support with automatic best-route selection
- Exact-output swaps for precise target amounts

Strategies
- dex_simple_swap: one-time market swap
- dex_pure_market_making: symmetric levels with periodic refresh
- dex_batch_swap: one-sided ladder across price range
- dex_dca: interval-based allocation (uniform/random)

Order Management
- Pre-order validation (balance, gas, allowance checks)
- Automatic retry mechanism (3 attempts with exponential backoff)
- Order tracking with internal IDs and detailed status
- Comprehensive logging with wallet name, strategy, and timestamps

Reporting & Monitoring
- Initial balance snapshots
- Periodic P&L reporting (every 1 minute)
- Final comprehensive reports per wallet and aggregate
- Success/failure statistics for all orders
- Connection health monitoring

Network Resilience
- Automatic retry on network failures
- Exponential backoff for RPC calls
- Connection state monitoring
- Strategies continue running despite temporary network issues
- Individual order failures don't stop other orders

Notes
- Shows BSC explorer link for all transactions
- Robust error handling prevents strategy crashes
- All reports include P&L in both absolute and percentage terms