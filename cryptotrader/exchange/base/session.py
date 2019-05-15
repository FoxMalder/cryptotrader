import abc
import asyncio

from cryptotrader import typing
from cryptotrader.common import Schedulable
from cryptotrader.exchange.base.transport import HttpTransport
from cryptotrader.exchange.base.transport import WebsocketTransport
from cryptotrader.models import Order

Transport = typing.Union[WebsocketTransport, HttpTransport]


class Session(Schedulable, metaclass=abc.ABCMeta):

    def __init__(self, transports: typing.List[Transport]) -> None:
        super().__init__()
        self.transports = transports

    async def schedule(self):
        await asyncio.gather(*[
            transport.schedule()
            for transport in self.transports
        ])

    async def stop(self):
        for transport in self.transports:
            await transport.stop()
        await super().stop()

    @property
    @abc.abstractmethod
    def name(self):
        """Exchange name."""

    @abc.abstractmethod
    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        """Fetch balances from an exchange."""

    @abc.abstractmethod
    async def fetch_pair(self, pair, pair_limits) -> typing.SessionFetchedPair:
        """Fetch pair's ticker from an exchange."""

    @abc.abstractmethod
    async def place(
        self, order: Order, timeout=30.0, fetch_order_interval=1.0
    ) -> typing.PlacedOrder:
        """Create the new order in an exchange."""

    @abc.abstractmethod
    async def cancel(self, order: Order) -> typing.CancelledOrder:
        """Cancel the order in an exchange."""

    @abc.abstractmethod
    async def fetch_status(self, order: Order) -> typing.FetchedOrderStatus:
        """Fetch the order's status from an exchange."""
