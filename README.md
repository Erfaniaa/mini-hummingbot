# 🤖 Mini-Hummingbot

A lightweight, minimalist trading bot for PancakeSwap on BSC (Binance Smart Chain). Inspired by the popular [Hummingbot](https://hummingbot.org/) project, **mini-hummingbot** provides a simplified but powerful CLI for automated trading strategies.

---

## 🐦 What is Hummingbot?

[Hummingbot](https://github.com/hummingbot/hummingbot) is an open-source trading bot framework that allows users to run market-making and arbitrage strategies on centralized and decentralized exchanges. It's a comprehensive platform with support for 40+ exchanges, complex strategies, and enterprise-grade features.

## 🔄 Mini-Hummingbot vs Hummingbot

| Feature | Mini-Hummingbot | Hummingbot |
|---------|----------------|------------|
| **Focus** | PancakeSwap DEX on BSC | 40+ CEX/DEX exchanges |
| **Setup** | Simple pip install + CLI | Docker/Source installation |
| **Strategies** | 4 core strategies | 20+ strategy types |
| **Complexity** | Minimal (~3K LOC) | Enterprise-grade (~200K+ LOC) |
| **Learning Curve** | Minutes to get started | Hours to days |
| **Config** | Interactive CLI prompts | YAML/JSON config files |
| **Wallets** | Built-in encrypted keystore | External wallet connection |
| **MEV Protection** | ✅ Built-in | Varies by connector |
| **Best For** | Quick PancakeSwap trading | Professional trading operations |

### When to use Mini-Hummingbot?
- ✅ You want to trade on PancakeSwap quickly
- ✅ You prefer a simple, no-frills CLI experience
- ✅ You're learning about automated trading
- ✅ You need a lightweight solution for BSC

### When to use Hummingbot?
- ✅ You need multi-exchange support
- ✅ You want advanced strategies (arbitrage, cross-exchange MM)
- ✅ You need extensive customization options
- ✅ You're running production trading operations

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- BSC wallet with BNB for gas fees

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/mini-hummingbot.git
cd mini-hummingbot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the CLI
python -m cli.main
```

### First Steps
1. **Add wallets** via encrypted keystore
2. **Approve tokens** for PancakeSwap (one-time setup)
3. **Select and configure** a strategy
4. **Monitor** live with detailed order tracking and P&L updates

---

## 📊 Available Strategies

### 1. DEX Simple Swap
One-time market swap on PancakeSwap.

```
Use case: Quick token swaps with optimal routing
```

### 2. DEX Pure Market Making
Symmetric limit orders around mid price with periodic refresh.

```
Use case: Provide liquidity and capture spread
```

### 3. DEX Batch Swap
One-sided ladder of swaps across a price range.

```
Use case: Scale into/out of positions gradually
```

### 4. DEX DCA (Dollar-Cost Averaging)
Interval-based allocation with uniform or random distribution.

```
Use case: Reduce timing risk with scheduled buys/sells
```

---

## 🛡️ Features

### Security
- **Encrypted Keystore**: AES-256 encryption for private keys
- **MEV Protection**: Built-in defenses against frontrunning and sandwich attacks
- **No External Calls**: All transactions signed locally

### Trading
- **PancakeSwap v2 & v3**: Automatic best-route selection
- **Multi-hop Routing**: WBNB/USDC intermediaries for optimal prices
- **Exact-output Swaps**: Precise target amounts
- **Slippage Control**: Configurable tolerance (default 0.5%)

### Reliability
- **Automatic Retries**: 3 attempts with exponential backoff
- **Network Resilience**: Continues despite temporary RPC issues
- **Connection Monitoring**: Health checks and status alerts

### Notifications
- **Telegram Integration**: Real-time alerts for:
  - Strategy start/stop
  - Order fills and failures
  - Balance updates

---

## 🔒 MEV Protection

**MEV (Maximal Extractable Value)** attacks include:
- **Frontrunning**: Transactions placed ahead of yours
- **Sandwich attacks**: Transactions before AND after yours
- **Back-running**: Exploiting state changes from your tx

### Our Defense Strategy
| Technique | Description |
|-----------|-------------|
| Higher Gas Price | 20% premium for faster inclusion |
| Tight Slippage | Limits sandwich attack profitability |
| Smart Deadlines | 90-second timeout (optimized for BSC) |

Enable with: `use_mev_protection: true`

> **Note:** BSC lacks true private mempools like Ethereum's Flashbots. These techniques significantly reduce but don't eliminate MEV risk.

---

## 📈 Example Output

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

---

## 🧪 Running Tests

```bash
# Quick test run
./run_tests.sh

# All tests with details
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v

# Specific test file
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_strategies.py -v
```

**Test Coverage:**
- Strategy execution
- Network resilience/failures
- MEV protection
- Corner cases
- Price calculations

---

## 📁 Project Structure

```
mini-hummingbot/
├── cli/                    # Command-line interface
│   ├── main.py            # Entry point
│   ├── menus/             # Menu handlers
│   └── utils.py           # CLI utilities
├── connectors/            # Exchange connectors
│   ├── base.py            # Abstract connector
│   └── dex/
│       └── pancakeswap.py # PancakeSwap connector
├── core/                  # Core functionality
│   ├── keystore.py        # Encrypted wallet storage
│   ├── settings_store.py  # Settings persistence
│   ├── telegram_notifier.py
│   └── token_registry.py  # Token lookups
├── strategies/            # Trading strategies
│   ├── dex_simple_swap.py
│   ├── dex_pure_market_making.py
│   ├── dex_batch_swap.py
│   ├── dex_dca.py
│   ├── engine.py          # Strategy loop
│   ├── order_manager.py   # Order handling
│   └── resilience.py      # Network resilience
├── tests/                 # Test suite
├── tokens/                # Token lists
├── keystore/              # Encrypted keys (gitignored)
└── settings/              # User settings (gitignored)
```

---

## 📋 Roadmap & TODO

We welcome contributions! Here are areas where you can help:

### 🔴 High Priority

- [ ] **Add CEX Support**: Integrate centralized exchanges
  - [ ] Binance connector
  - [ ] KuCoin connector
  - [ ] Bybit connector
  - [ ] OKX connector
  
- [ ] **Additional DEX Support**
  - [ ] Uniswap (Ethereum, Arbitrum, Polygon)
  - [ ] SushiSwap (multi-chain)
  - [ ] TraderJoe (Avalanche)
  - [ ] SpookySwap (Fantom)
  - [ ] QuickSwap (Polygon)
  - [ ] GMX (Arbitrum)

### 🟡 Medium Priority

- [ ] **New Strategies**
  - [ ] Arbitrage between DEXes
  - [ ] Cross-exchange market making
  - [ ] Grid trading
  - [ ] TWAP (Time-Weighted Average Price)
  - [ ] Liquidity provision (LP) management
  
- [ ] **Advanced Features**
  - [ ] Web dashboard for monitoring
  - [ ] Backtesting framework
  - [ ] Paper trading mode
  - [ ] Multi-wallet orchestration
  - [ ] Risk management (stop-loss, take-profit)
  - [ ] Position sizing algorithms

### 🟢 Nice to Have

- [ ] **Infrastructure**
  - [ ] Docker support
  - [ ] Kubernetes deployment configs
  - [ ] Cloud-native logging (ELK, Datadog)
  
- [ ] **Analytics**
  - [ ] Historical trade analysis
  - [ ] Performance metrics dashboard
  - [ ] PnL visualization
  
- [ ] **Integrations**
  - [ ] Discord notifications
  - [ ] Slack notifications
  - [ ] Email alerts
  - [ ] Webhook support

### 🔵 Technical Debt

- [ ] Refactor `pancakeswap.py` (currently 1100+ lines)
- [ ] Add type hints throughout
- [ ] Improve test coverage to 90%+
- [ ] Add integration tests with testnet
- [ ] CI/CD pipeline with GitHub Actions
- [ ] Documentation site with Sphinx/MkDocs

---

## 🤝 Contributing

We love contributions! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Contribution Guidelines
- Follow existing code style
- Add tests for new features
- Update documentation as needed
- Keep PRs focused and atomic

---

## ⚠️ Disclaimer

This software is for educational purposes only. Use at your own risk.

- **Not financial advice**: Do your own research before trading
- **No guarantees**: Past performance doesn't indicate future results
- **Test first**: Always test with small amounts on testnet
- **Secure your keys**: Never share private keys or commit them to git

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

---

## 🙏 Acknowledgments

- [Hummingbot](https://hummingbot.org/) - The inspiration for this project
- [PancakeSwap](https://pancakeswap.finance/) - The DEX we support
- [Web3.py](https://web3py.readthedocs.io/) - Ethereum/BSC interaction

---

## 📬 Contact

Have questions or suggestions? Open an issue or reach out!

**Star ⭐ this repo if you find it useful!**
