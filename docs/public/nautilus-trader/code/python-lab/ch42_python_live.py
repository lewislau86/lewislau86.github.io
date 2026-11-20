"""Chapter 42 experiments: running a LiveNode from Python.

The nodes here have no venue clients: a strategy with a timer is enough to see the
lifecycle, signal ownership, hosting on asyncio and the one-node rule.

Run inside the nautilus_trader checkout's Python environment:
    uv run --project python --no-sync python /path/to/ch42_python_live.py [section ...]
"""

import asyncio
import gc
import os
import signal
import sys
import threading
import time
from datetime import timedelta

from nautilus_trader.common import Environment, LogLevel
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId
from nautilus_trader.trading import Strategy

T0 = time.perf_counter()


def ms() -> float:
    return (time.perf_counter() - T0) * 1000


class Ticker(Strategy):
    """Counts timer events every 10 ms."""

    def __init__(self) -> None:
        super().__init__()
        self.ticks = 0

    def on_start(self) -> None:
        print(f"  {ms():7.0f} ms  on_start")
        self.clock.set_timer("tick", timedelta(milliseconds=10))

    def on_time_event(self, event) -> None:
        self.ticks += 1

    def on_stop(self) -> None:
        print(f"  {ms():7.0f} ms  on_stop after {self.ticks} timer events")


def build_node(name: str = "LAB") -> LiveNode:
    return (
        LiveNode.builder(name, TraderId("LAB-001"), Environment.LIVE)
        .with_reconciliation(False)
        .with_delay_post_stop_secs(0)
        .with_logging(LoggerConfig(stdout_level=LogLevel.ERROR))
        .build()
    )


# region owned
def owned_run() -> None:
    """run() owns the calling thread and the SIGINT/SIGTERM handlers."""
    global T0
    T0 = time.perf_counter()
    node = build_node()
    node.add_strategy(Ticker())
    threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    print(f"  {ms():7.0f} ms  node.run() (SIGINT will arrive at ~1000 ms)")
    try:
        node.run()
        print(f"  {ms():7.0f} ms  node.run() returned normally")
    except KeyboardInterrupt:
        print(f"  {ms():7.0f} ms  KeyboardInterrupt reached Python")
    node.dispose()
# endregion owned


# region hosted
async def hosted_main() -> None:
    node = build_node()
    node.add_strategy(Ticker())
    cache, handle = node.cache, node.handle()  # capture before the run borrows the node

    host_ticks = 0

    async def host_work() -> None:
        nonlocal host_ticks
        while True:
            await asyncio.sleep(0.01)
            host_ticks += 1

    host = asyncio.create_task(host_work())
    run_task = asyncio.create_task(node.run_async())
    while not handle.is_running:
        await asyncio.sleep(0.01)
    print(f"  {ms():7.0f} ms  handle.is_running = True")

    try:
        node.cache
    except Exception as e:
        print(f"  {ms():7.0f} ms  node.cache during the run -> {type(e).__name__}: {e}")
    print(f"  {ms():7.0f} ms  captured cache still works: {len(cache.instruments())} instruments")
    node.dispose()
    print(f"  {ms():7.0f} ms  node.dispose() during the run returned (no-op)")

    await asyncio.sleep(1.0)
    handle.stop()
    print(f"  {ms():7.0f} ms  handle.stop() returned immediately")
    await run_task
    print(f"  {ms():7.0f} ms  run task finished; host task ticked {host_ticks} times meanwhile")
    host.cancel()
    node.dispose()


def hosted() -> None:
    global T0
    T0 = time.perf_counter()
    asyncio.run(hosted_main())
# endregion hosted


# region cancel
async def cancel_main() -> None:
    node = build_node()
    node.add_strategy(Ticker())
    handle = node.handle()
    task = asyncio.create_task(node.run_async())
    while not handle.is_running:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.5)
    print(f"  {ms():7.0f} ms  task.cancel()")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print(f"  {ms():7.0f} ms  CancelledError re-raised after shutdown; handle.is_running = {handle.is_running}")
    node.dispose()


def cancel() -> None:
    global T0
    T0 = time.perf_counter()
    asyncio.run(cancel_main())
# endregion cancel


# region one_node
def one_node() -> None:
    first = build_node("FIRST")
    try:
        build_node("SECOND")
    except Exception as e:
        print(f"  second build while the first exists -> {type(e).__name__}: {e}")
    first.dispose()
    try:
        build_node("SECOND")
    except Exception as e:
        print(f"  after first.dispose() only -> {type(e).__name__}")
    del first
    gc.collect()
    second = build_node("SECOND")
    print(f"  after del + gc.collect(): built {second.trader_id} again")
    second.dispose()
# endregion one_node


def main() -> None:
    sections = {"owned": owned_run, "hosted": hosted, "cancel": cancel, "one_node": one_node}
    for name in sys.argv[1:] or list(sections):
        print(f"== {name}")
        sections[name]()
        gc.collect()


if __name__ == "__main__":
    main()
