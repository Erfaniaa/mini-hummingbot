Mini-Hummingbot (internal PancakeSwap CLI)

Getting started
- Create a Python 3.10+ venv
- Install deps: `pip install -r requirements.txt`
- Run the CLI: `python -m mini_hummingbot.cli.main`

Features (phase 1)
- Encrypted keystore (multiple wallets)
- Token registry (PancakeSwap lists; copy JSON files into `tokens/`)
- Connector abstraction and PancakeSwap connector wrapper
- CLI skeleton (wallet add/list/remove)

Roadmap
- Strategies: dex_simple_swap, dex_pure_market_making, dex_batch_swap, dex_dca
- Interactive flows per strategy (with input validation)
- BscScan transaction links and robust error handling / retries


