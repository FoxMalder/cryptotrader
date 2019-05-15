import asyncio
import time

import pytest

from cryptotrader.common import Debounced
from cryptotrader.common import floor_with_precision
from cryptotrader.common import Limited


@pytest.mark.asyncio
async def test_debounce_deco(event_loop):
    @Debounced(0.1, event_loop)
    async def f():
        """Debounced dummy for tests."""

    now = time.time()

    # debounce futures
    await asyncio.gather(*[f() for _ in range(3)])
    # debounce await
    for _ in range(3):
        await f()

    # first call is not limited
    assert round(time.time() - now, 1) == 0.5


@pytest.mark.asyncio
async def test_debounce_manager(event_loop):
    async def f():
        """Debounced dummy for tests."""
        async with debouncer:
            pass

    now = time.time()
    debouncer = Debounced(0.1, event_loop)

    # debounce futures
    await asyncio.gather(*[f() for _ in range(3)])
    # debounce await
    for _ in range(3):
        await f()

    # first call is not limited
    assert round(time.time() - now, 1) == 0.5


@pytest.mark.parametrize('times,period,delay,expected', [
    # wait only delays, because the number of calls does not reach the limit
    (10, 0.1, 0.1, 0.1),
    # wait limit realising and delays
    (2, 0.2, 0.1, 0.3),
    # wait limit realising and delays
    (1, 0.2, 0.1, 0.5),
    # has no limits
    (0, 0.0, 0.1, 0.1),
])
@pytest.mark.asyncio
async def test_limited_futures(event_loop, times, period, delay, expected):
    async def f():
        """Limited dummy for tests."""
        async with limited:
            await asyncio.sleep(delay)

    now = time.time()
    limited = Limited(times, period, loop=event_loop)

    await asyncio.gather(*[f() for _ in range(3)])
    assert round(time.time() - now, 1) == expected


@pytest.mark.parametrize('times,period,delay,expected', [
    # wait only delays, because the number of calls does not reach the limit
    (10, 0.1, 0.1, 0.3),
    # wait only delays, because the limit period is small
    (1, 0.05, 0.1, 0.3),
    # wait limit realising and delay
    (1, 0.2, 0.1, 0.5),
    # has no limits
    (0, 0.0, 0.1, 0.3),
])
@pytest.mark.asyncio
async def test_limited_awaitables(event_loop, times, period, delay, expected):
    async def f():
        """Limited dummy for tests."""
        async with limited:
            await asyncio.sleep(delay)

    now = time.time()
    limited = Limited(times, period, loop=event_loop)

    for _ in range(3):
        await f()
    assert floor_with_precision(time.time() - now, 1) == expected
