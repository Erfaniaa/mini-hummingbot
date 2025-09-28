from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class StrategyLoopConfig:
    interval_seconds: float = 1.0
    on_tick: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[Exception], None]] = None


class StrategyLoop:
    """
    Simple stoppable loop to run a strategy tick function every interval.
    Handles exceptions and continues (does not terminate on network errors).
    """

    def __init__(self, cfg: StrategyLoopConfig) -> None:
        self.cfg = cfg
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_flag.is_set():
            t0 = time.time()
            try:
                if self.cfg.on_tick:
                    self.cfg.on_tick()
            except Exception as e:
                if self.cfg.on_error:
                    self.cfg.on_error(e)
            dt = time.time() - t0
            sleep_time = max(0.0, float(self.cfg.interval_seconds) - dt)
            self._stop_flag.wait(timeout=sleep_time)

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


