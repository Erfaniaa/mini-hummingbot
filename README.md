Mini-Hummingbot (PancakeSwap CLI)

Getting Started
- Create a Python 3.10+ venv: `python3 -m venv venv && source venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Run the CLI: `python -m cli.main`
- Add wallets via encrypted keystore
- Approve tokens for PancakeSwap (one-time setup)
- Select and configure a strategy
- Monitor live with detailed order tracking and P&L updates

Running Tests
```bash
# Quick test run
./run_tests.sh

# All tests with details
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v

# Specific test file
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_strategies.py -v

# Specific test
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_strategies.py::test_dex_simple_swap_sell_base_exact_amount -v
```

Test Coverage: strategy execution, resilience/network failures, MEV protection, corner cases, price calculations

Features
- Encrypted keystore (multiple wallets)
- Token registry (PancakeSwap lists; copy JSON files into `tokens/`)
- Connector abstraction and PancakeSwap connector wrapper
- CLI (wallet add/list/remove + strategies menu)
- PancakeSwap v2 and v3 support with automatic best-route selection
- Exact-output swaps for precise target amounts
- **MEV Protection** to prevent frontrunning and sandwich attacks

Strategies
- dex_simple_swap: one-time market swap
- dex_pure_market_making: symmetric levels with periodic refresh
- dex_batch_swap: one-sided ladder across price range
- dex_dca: interval-based allocation (uniform/random)

Order Management
- Pre-order validation (balance, gas, allowance checks) before submission
- Automatic retry mechanism (3 attempts with exponential backoff)
- Order tracking with internal IDs (e.g., `dex_batch_swap-wallet_1-1`)
- Detailed order information: base/quote, side (buy/sell), price, reason
- Per-order submission, fill, and failure notifications
- Orders clearly show which price level or DCA interval triggered them
- Comprehensive logging with wallet name, strategy, and timestamps

Reporting & Monitoring
- Initial balance snapshots
- Periodic P&L reporting (every 1 minute)
- Final comprehensive reports per wallet and aggregate
- Success/failure statistics for all orders
- Connection health monitoring
- **Telegram notifications** for critical events (optional):
  - Strategy start/stop
  - Order fills and failures
  - Balance updates
  - Configure via CLI menu or `telegram_config.json`

MEV Protection
- **What is MEV?** MEV (Maximal Extractable Value) is the profit that can be extracted by manipulating transaction ordering in a block. Common MEV attacks include:
  - **Frontrunning:** Placing transactions ahead of yours to profit from price changes
  - **Sandwich attacks:** Placing transactions before and after yours to extract value
  - **Back-running:** Placing transactions immediately after yours to exploit state changes
- **How it works:** Uses multiple defensive strategies to reduce MEV attack surface:
  - **Higher Gas Price:** 20% premium over market rate for faster inclusion and priority
  - **Tight Slippage:** Combined with existing slippage controls to limit sandwich attack profitability
  - **Smart Deadlines:** 90-second timeout (optimized for ~70s actual swap time from real testing)
- **Enable MEV Protection:** Set `use_mev_protection: true` in your strategy config
- **Supported Networks:** BSC Mainnet (56) and BSC Testnet (97)
- **Trade-offs:** Slightly higher gas costs but significantly reduced MEV risk
- **When to use:** Recommended for large trades or market-making strategies on mainnet
- **Note:** BSC doesn't have true private mempool solutions like Ethereum (Flashbots). These defensive strategies significantly reduce but don't eliminate MEV risk.

Network Resilience
- Automatic retry on network failures
- Exponential backoff for RPC calls
- Connection state monitoring
- Strategies continue running despite temporary network issues
- Individual order failures don't stop other orders

User Experience
- Consistent BASE/QUOTE price display (never inverted)
- Clean transaction links (BSC explorer only, no raw hashes)
- Strategy stops cleanly without orphan transactions
- Clear validation messages if orders can't be placed
- Reduced log spam with smart periodic updates
- "Please wait" notifications after order submission
- All monetary values clearly labeled with token symbol

Example Output
```
[wallet_1] [dex_batch_swap] Order dex_batch_swap-wallet_1-1 (SELL BTCB/USDT) created
[wallet_1] [dex_batch_swap]   Reason: Price level 1/11: 0.20000000
[wallet_1] [dex_batch_swap] Submitting order #dex_batch_swap-wallet_1-1 (Attempt 1/3)
[wallet_1] [dex_batch_swap]   Side: SELL BTCB/USDT
[wallet_1] [dex_batch_swap]   Amount: 1.818182 USDT
[wallet_1] [dex_batch_swap]   Price: 0.19630755 BTCB/USDT
[wallet_1] [dex_batch_swap] ✓ Order filled successfully!
[wallet_1] [dex_batch_swap]   Transaction: https://bscscan.com/tx/0x...

[wallet_1] [dex_batch_swap] === Balance Update ===
[wallet_1] [dex_batch_swap] BTCB: 143.616241 (-35.334038)
[wallet_1] [dex_batch_swap] USDT: 17.27 (+7.27)
[wallet_1] [dex_batch_swap] Current Price: 0.19641531 BTCB/USDT
[wallet_1] [dex_batch_swap] Portfolio Value: 45.48 USDT
[wallet_1] [dex_batch_swap] P&L: +0.35 USDT (+0.78%)
```

Technical Notes
- Supports both exact-input and exact-output swaps
- Automatic path finding between v2 and v3 routes
- Multi-hop routing via WBNB/USDC for optimal prices
- MEV protection available for all strategies with single config flag
- Atomic commits and clean git history
- Comprehensive test coverage for critical paths including MEV protection
- All reports include P&L in both absolute and percentage terms

Configuration Example (with MEV Protection)
```json
{
  "base": "LINK",
  "quote": "USDT",
  "amount": 100.0,
  "amount_is_base": false,
  "slippage_bps": 50,
  "chain_id": 56,
  "use_mev_protection": true
}
```