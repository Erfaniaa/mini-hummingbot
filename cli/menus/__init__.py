"""CLI menu modules."""
from .wallets import menu_wallets
from .approvals import menu_token_approvals
from .telegram import menu_telegram_setup

__all__ = ["menu_wallets", "menu_token_approvals", "menu_telegram_setup"]

