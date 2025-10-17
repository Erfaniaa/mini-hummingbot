"""
Telegram notification system for trading strategies.

Sends important events and logs to a Telegram channel without spamming.
Uses intelligent batching and filtering to keep notifications relevant.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from threading import Thread, Lock
import queue


@dataclass
class TelegramConfig:
    """Configuration for Telegram notifications."""
    bot_token: str
    chat_id: str
    enabled: bool = True
    batch_interval: float = 30.0  # Send batched messages every 30 seconds
    max_batch_size: int = 10  # Max messages per batch


class TelegramNotifier:
    """
    Non-blocking Telegram notifier with intelligent batching.
    
    Features:
    - Async sending to not block trading
    - Batches multiple logs to avoid spam
    - Priority levels (critical, info, debug)
    - Auto-reconnect on failures
    """
    
    def __init__(self, config: TelegramConfig):
        self.config = config
        self._message_queue: queue.Queue = queue.Queue()
        self._batch: List[str] = []
        self._last_send_time: float = 0.0
        self._lock = Lock()
        self._running = False
        self._thread: Optional[Thread] = None
        self._bot = None
        
        if self.config.enabled:
            try:
                # Lazy import to avoid dependency if not used
                from telegram import Bot
                self._bot = Bot(token=self.config.bot_token)
                self._start_worker()
            except Exception as e:
                print(f"[Telegram] Failed to initialize bot: {e}")
                self.config.enabled = False
    
    def _start_worker(self):
        """Start background worker thread for sending messages."""
        if self._running:
            return
        self._running = True
        self._thread = Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
    
    def _worker_loop(self):
        """Background worker that batches and sends messages."""
        while self._running:
            try:
                # Try to get message (non-blocking with timeout)
                try:
                    msg = self._message_queue.get(timeout=1.0)
                    with self._lock:
                        self._batch.append(msg)
                except queue.Empty:
                    pass
                
                # Send batch if interval passed or batch is full
                now = time.time()
                with self._lock:
                    should_send = (
                        len(self._batch) >= self.config.max_batch_size or
                        (len(self._batch) > 0 and now - self._last_send_time >= self.config.batch_interval)
                    )
                    
                    if should_send:
                        batch_copy = self._batch.copy()
                        self._batch.clear()
                        self._last_send_time = now
                
                if should_send:
                    self._send_batch(batch_copy)
                    
            except Exception as e:
                print(f"[Telegram] Worker error: {e}")
                time.sleep(5)  # Back off on errors
    
    def _send_batch(self, messages: List[str]):
        """Send a batch of messages as a single Telegram message."""
        if not messages or not self._bot:
            return
        
        try:
            # Join messages with separators
            combined = "\n\n".join(messages)
            
            # Telegram has 4096 char limit, split if needed
            if len(combined) > 4000:
                # Run async send in a new event loop (we're in a thread)
                # Send first part
                asyncio.run(self._async_send(combined[:4000] + "..."))
                # Indicate there's more
                asyncio.run(self._async_send(f"... (+{len(combined) - 4000} chars truncated)"))
            else:
                # Run async send in a new event loop (we're in a thread)
                asyncio.run(self._async_send(combined))
                    
        except Exception as e:
            print(f"[Telegram] Send error: {e}")
    
    async def _async_send(self, text: str):
        """Send message asynchronously."""
        try:
            await self._bot.send_message(
                chat_id=self.config.chat_id,
                text=text,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"[Telegram] Async send error: {e}")
    
    def notify(self, message: str, level: str = "info"):
        """
        Queue a notification message.
        
        Args:
            message: The message text
            level: Priority level (critical, info, debug)
        """
        if not self.config.enabled:
            return
        
        # Skip empty messages
        if not message or not message.strip():
            return
        
        # Format message with timestamp and level
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Use emojis for visual clarity
        emoji_map = {
            "critical": "🔴",
            "warning": "⚠️",
            "success": "✅",
            "info": "ℹ️",
            "debug": "🔍"
        }
        emoji = emoji_map.get(level, "📝")
        
        formatted = f"{emoji} <b>[{timestamp}]</b> {message}"
        
        # Add to queue
        try:
            self._message_queue.put_nowait(formatted)
        except queue.Full:
            pass  # Silently drop if queue is full
    
    def notify_critical(self, message: str):
        """Send critical notification (strategy error, etc)."""
        self.notify(message, level="critical")
    
    def notify_success(self, message: str):
        """Send success notification (trade executed, etc)."""
        self.notify(message, level="success")
    
    def notify_warning(self, message: str):
        """Send warning notification."""
        self.notify(message, level="warning")
    
    def notify_info(self, message: str):
        """Send info notification."""
        self.notify(message, level="info")
    
    def flush(self):
        """Force send any pending messages immediately."""
        if not self.config.enabled:
            return
        
        with self._lock:
            if self._batch:
                batch_copy = self._batch.copy()
                self._batch.clear()
                self._last_send_time = time.time()
                self._send_batch(batch_copy)
    
    def stop(self):
        """Stop the notifier and flush pending messages."""
        if not self._running:
            return
        
        # Flush any pending messages
        self.flush()
        
        # Stop worker
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
    
    @staticmethod
    def load_config(config_path: str = "telegram_config.json") -> Optional[TelegramConfig]:
        """Load Telegram configuration from JSON file."""
        if not os.path.exists(config_path):
            return None
        
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            
            return TelegramConfig(
                bot_token=data.get("bot_token", ""),
                chat_id=data.get("chat_id", ""),
                enabled=data.get("enabled", True),
                batch_interval=data.get("batch_interval", 30.0),
                max_batch_size=data.get("max_batch_size", 10)
            )
        except Exception as e:
            print(f"[Telegram] Failed to load config: {e}")
            return None
    
    @staticmethod
    def save_config(config: TelegramConfig, config_path: str = "telegram_config.json"):
        """Save Telegram configuration to JSON file."""
        try:
            data = {
                "bot_token": config.bot_token,
                "chat_id": config.chat_id,
                "enabled": config.enabled,
                "batch_interval": config.batch_interval,
                "max_batch_size": config.max_batch_size
            }
            
            with open(config_path, "w") as f:
                json.dump(data, f, indent=2)
            
            print(f"[Telegram] Config saved to {config_path}")
        except Exception as e:
            print(f"[Telegram] Failed to save config: {e}")


# Global notifier instance
_global_notifier: Optional[TelegramNotifier] = None
_notifier_lock = Lock()


def get_notifier() -> Optional[TelegramNotifier]:
    """Get or create the global Telegram notifier instance."""
    global _global_notifier
    
    with _notifier_lock:
        if _global_notifier is None:
            config = TelegramNotifier.load_config()
            if config and config.enabled:
                _global_notifier = TelegramNotifier(config)
        
        return _global_notifier


def notify(message: str, level: str = "info"):
    """Convenience function to send notification via global notifier."""
    notifier = get_notifier()
    if notifier:
        notifier.notify(message, level)

