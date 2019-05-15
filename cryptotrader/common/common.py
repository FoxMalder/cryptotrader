import abc
import asyncio
from functools import wraps
import logging
import math
import time

from cryptotrader import const
from cryptotrader import typing


def floor_with_precision(value, precision=4):
    """Similar to math.floor, but with precision."""
    base = 10**precision
    return math.floor(value * base) / base


def singleton(cls):
    instance = None

    @wraps(cls)
    def inner(*args, **kwargs):
        nonlocal instance
        if instance is None:
            instance = cls(*args, **kwargs)
        return instance

    return inner


def make_schedule(*, interval, is_running: asyncio.Event, logger=None, loop=None, timeout=30.0):
    # @todo #176 Make the make_schedule function part of the App class.
    def wrapped(fn):
        @wraps(fn)
        async def schedule(*args, **kwargs):
            schedule_loop = loop or asyncio.get_event_loop()
            schedule_logger = logger or logging.getLogger(__name__)
            while schedule_loop.is_running() and is_running.is_set():
                try:
                    await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
                except NotImplementedError:
                    pass
                except asyncio.TimeoutError:
                    schedule_logger.error(f'{fn} task timed out...')
                except Exception as error:
                    schedule_logger.exception(f'Error in {fn}: {error}')
                await asyncio.sleep(interval)
        return schedule
    return wrapped


class Limited:
    """
    Limit the frequency of code invocation.

    Guarantee code invocation with frequency less, than given `limit`
    count in time `period`.
    """

    def __init__(self, limit, period, loop=None):
        self.is_calling = asyncio.Lock(loop=loop)
        self.limited: asyncio.Queue = asyncio.Queue(maxsize=limit, loop=loop)
        self.period = period

    async def __aenter__(self):
        async with self.is_calling:
            if self.limited.full():
                last_called_period = time.time() - await self.limited.get()
                if last_called_period < self.period:
                    await asyncio.sleep(self.period - last_called_period)
            await self.limited.put(time.time())

    async def __aexit__(self, *args, **kwargs):
        """Required for `async with` statement."""


class Debounced:
    """
    Guarantee code invocation with frequency less, than given `interval`.

    You may use it as decorator or context manager.
    """

    def __init__(self, interval, loop=None):
        self.interval = interval
        self.is_calling = asyncio.Lock(loop=loop)
        self.last_call_time = 0.0
        self.coro = None

    def __call__(self, coro):
        self.coro = coro
        return self._wrapped

    async def _wrapped(self, *args, **kwargs):
        async with self:
            await self.coro(*args, **kwargs)

    async def __aenter__(self):
        await self.is_calling.acquire()
        delay = self.interval - (time.time() - self.last_call_time)
        await asyncio.sleep(delay if delay >= 0 else 0.0)

    async def __aexit__(self, *args, **kwargs):
        self.last_call_time = time.time()
        self.is_calling.release()


class Schedulable(metaclass=abc.ABCMeta):

    def __init__(self):
        self.scheduled: typing.List[asyncio.Future] = []

    def ensure_future(self, coro_or_future):
        fut = asyncio.ensure_future(coro_or_future)
        self.scheduled.append(fut)
        return fut

    async def cancel_futures(self):
        """Gracefully cancel futures."""
        futures_to_done = [
            future for future in filter(
                lambda fut: not fut.done(), self.scheduled
            )
        ]
        # @todo #374:120m Redesign Schedulable-Runnable system.
        #  Schedulable.cancel_futures has semantic binding
        #  to Runnable.is_running event.
        if futures_to_done:
            _, futures_to_cancel = await asyncio.wait(
                futures_to_done,
                # 0.1 - some additional small timeout to finish inner tasks processing
                timeout=const.FOREVER_TASK_TIMEOUT + 0.1,
            )
            for future in futures_to_cancel:
                future.cancel()
        self.scheduled = []

    @abc.abstractmethod
    async def schedule(self):
        """Will be run as periodic task."""

    async def stop(self):
        await self.cancel_futures()


class Serializer(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def dumps(self, data: typing.Any) -> bytes:
        pass

    @abc.abstractmethod
    def loads(self, raw: bytes) -> object:
        pass


class Reporter(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def report(self, message: str) -> None:
        pass
