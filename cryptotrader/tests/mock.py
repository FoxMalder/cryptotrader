import asyncio
from collections import defaultdict
import uuid

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.commands.execute import App
from cryptotrader.exchange import Session
from cryptotrader.models import Order
from cryptotrader.models import Queue
from cryptotrader.strategy import Arbitrage
from cryptotrader.strategy import Strategy


class MockSession(Session):
    name = 'mock'

    def __init__(
        self,
        is_success=True,
        balances=None,
        pairs=None,
        status_to_place=const.PLACED,
        status=const.FULFILLED,
        order_id='',
    ):
        """:param status_to_place: Order will get this status after placing."""
        self.is_success = is_success
        self.balances = defaultdict(float, balances or {})
        self.pairs = defaultdict(
            lambda: {'bid_size': 0.0, 'ask_size': 0.0, 'bid': 0.0, 'ask': 0.0},
            pairs or {},
        )
        self.status_to_place = status_to_place
        self.status = status
        self.order_id = order_id or str(uuid.uuid4())
        self.is_running = asyncio.Event()
        super().__init__(transports=[])

    async def schedule(self):
        self.is_running.set()

    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        return typing.SessionFetchedBalances(
            success=self.is_success, balances=self.balances, response='ok',
        )

    async def fetch_pair(self, pair, pair_limits) -> typing.SessionFetchedPair:
        return typing.SessionFetchedPair(
            success=self.is_success, pair=self.pairs[pair], response='ok',
        )

    async def place(
        self, order: Order, timeout=30.0, fetch_order_interval=1.0
    ) -> typing.PlacedOrder:
        self.balances[order.base.currency] += (
            const.get_factor(order.side) * order.base.amount
        )
        self.balances[order.quote.currency] -= (
            const.get_factor(order.side) * order.quote.amount
        )
        return typing.PlacedOrder(
            success=self.is_success,
            order_id=self.order_id,
            order_status=self.status_to_place,
            response='ok'
        )

    async def cancel(self, order: Order) -> typing.CancelledOrder:
        return typing.CancelledOrder(
            success=self.is_success, response='ok',
        )

    async def fetch_status(self, order: Order) -> typing.FetchedOrderStatus:
        return typing.FetchedOrderStatus(
            success=self.is_success, status=self.status, response='ok',
        )


class MockQueue(Queue, asyncio.Queue):

    async def pop(self):
        return await self.get()

    async def push(self, data):
        return await self.put(data)

    async def length(self):
        return self.qsize()


# @todo #268:120m Use App instance broadly in tests.
#  App should instantiate exchanges, strategies and other data.
#  With custom config for every tests.
#  Good config customization is opened problem.


class MockApp(App):
    STRATEGIES = [Arbitrage]

    async def run(self):
        await super().run()
        # For test purposes wait one fully iteration
        await self._schedule()


class MockStrategy(Strategy):

    def get_pair_offer_map(self):
        pass

    async def schedule(self):
        pass

    async def enter(self):
        pass

    async def exit(self):
        pass
