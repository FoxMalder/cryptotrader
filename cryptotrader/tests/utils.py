import asyncio

from cryptotrader import typing
from cryptotrader.common import Schedulable


class ScheduleManager:

    def __init__(self, schedulable: typing.List[Schedulable]) -> None:
        self.schedulable = schedulable

    async def __aenter__(self):
        for coro in self.schedulable:
            await coro.schedule()

    async def __aexit__(self, exc_type, exc, tb):
        for coro in self.schedulable:
            await coro.stop()


class RollbackAcquireManager:
    """
    Acquire only one connection from pool and begin a transaction.

    On exit rollback the transaction.
    """

    def __init__(self, engine):
        self.engine = engine
        self.conn = None
        self.transaction = None

    async def __aenter__(self):
        self.conn = await self.engine.acquire()
        self.transaction = await self.conn.begin_nested()
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        await self.transaction.rollback()
        await self.conn.close()


class SyncConnectionManager:
    """Allow to use only one connection as a pool in an asynchronous environment."""

    def __init__(self, conn):
        self.conn = conn
        self.is_executing = asyncio.Lock()

    def __await__(self):
        return self.conn

    async def __aenter__(self):
        await self.is_executing.acquire()
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        self.is_executing.release()
        if exc:
            raise exc
