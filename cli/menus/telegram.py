"""
Telegram notifications setup menu.
"""
from cli.utils import prompt


def menu_telegram_setup() -> None:
    """Setup Telegram notifications."""
    from core.telegram_notifier import TelegramConfig, TelegramNotifier
    
    print("\nTelegram Notifications Setup")
    print("\nHow to get Bot Token and Chat ID:")
    print("  1. Open Telegram and search for @BotFather")
    print("  2. Send /newbot and follow instructions to create a bot")
    print("  3. Copy the Bot Token (looks like: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz)")
    print("  4. Start a chat with your bot and send any message")
    print("  5. Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates")
    print("  6. Look for 'chat':{'id': 123456789} and copy the Chat ID")
    print("\nCurrent Configuration:")
    
    config = TelegramNotifier.load_config()
    if config:
        print(f"  Bot Token: {'*' * 20}{config.bot_token[-10:] if len(config.bot_token) > 10 else '***'}")
        print(f"  Chat ID: {config.chat_id}")
        print(f"  Enabled: {'Yes' if config.enabled else 'No'}")
        print(f"  Batch Interval: {config.batch_interval}s")
    else:
        print("  Not configured yet")
    
    print("\nOptions:")
    print("  1) Configure Bot Token and Chat ID")
    print("  2) Enable/Disable notifications")
    print("  3) Test notification")
    print("  4) Advanced settings")
    print("  0) Back")
    
    choice = prompt("Select: ").strip()
    
    if choice == "1":
        token = prompt("Enter Bot Token: ").strip()
        if not token:
            print("Token is required.")
            return
        chat_id = prompt("Enter Chat ID: ").strip()
        if not chat_id:
            print("Chat ID is required.")
            return
        
        new_config = TelegramConfig(
            bot_token=token,
            chat_id=chat_id,
            enabled=True
        )
        TelegramNotifier.save_config(new_config)
        print("✓ Telegram configuration saved!")
        
    elif choice == "2":
        if not config:
            print("Please configure Telegram first (option 1)")
            return
        enabled_str = prompt("Enable notifications? (yes/no): ").strip().lower()
        config.enabled = enabled_str in {"yes", "y"}
        TelegramNotifier.save_config(config)
        print(f"✓ Notifications {'enabled' if config.enabled else 'disabled'}")
        
    elif choice == "3":
        if not config or not config.enabled:
            print("Telegram is not configured or disabled")
            return
        print("Sending test notification...")
        try:
            notifier = TelegramNotifier(config)
            notifier.notify_success("✅ Test notification from Mini-Hummingbot!")
            notifier.flush()
            notifier.stop()
            print("✓ Test notification sent! Check your Telegram.")
        except Exception as e:
            print(f"✗ Failed to send: {e}")
            
    elif choice == "4":
        if not config:
            print("Please configure Telegram first (option 1)")
            return
        batch_str = prompt(f"Batch interval seconds [{config.batch_interval}]: ").strip()
        if batch_str:
            try:
                config.batch_interval = float(batch_str)
            except ValueError:
                print("Invalid number")
                return
        max_batch_str = prompt(f"Max batch size [{config.max_batch_size}]: ").strip()
        if max_batch_str:
            try:
                config.max_batch_size = int(max_batch_str)
            except ValueError:
                print("Invalid number")
                return
        TelegramNotifier.save_config(config)
        print("✓ Advanced settings saved!")

