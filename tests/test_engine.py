from __future__ import annotations

import time

from strategies.engine import StrategyLoop, StrategyLoopConfig


def test_strategy_loop_runs_and_stops():
    ticks = {"n": 0}

    def on_tick():
        ticks["n"] += 1

    loop = StrategyLoop(StrategyLoopConfig(interval_seconds=0.01, on_tick=on_tick))
    loop.start()
    time.sleep(0.05)
    loop.stop()
    assert ticks["n"] >= 1
