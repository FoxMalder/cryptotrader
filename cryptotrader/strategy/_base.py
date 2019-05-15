import abc
import asyncio
import logging

from aiopg.sa import Engine

from cryptotrader import typing
from cryptotrader.common import Schedulable
from cryptotrader.exchange import Exchanges  # type: ignore
from cryptotrader.models import Offer


class Strategy(Schedulable, metaclass=abc.ABCMeta):

    def __init__(self, exchanges: Exchanges, db: Engine, *, loop=None) -> None:
        super().__init__()
        self.loop = loop or asyncio.get_event_loop()
        self.logger = logging.getLogger(f'{__name__}.{self.__class__.__name__}')
        self.tg = logging.getLogger('tg')

        self.db = db
        self.exchanges = exchanges

    @abc.abstractmethod
    async def schedule(self):
        """
        Iterate a strategy lifecycle.

        Should contain `self.enter` and `self.exit` methods execution.
        """

    @abc.abstractmethod
    async def enter(self):
        """Detect the conditions that must be met for a trade entry and handle it."""

    @abc.abstractmethod
    async def exit(self):
        """Detect the conditions that must be met for exit to occur and handle it."""

    @abc.abstractmethod
    def get_pair_offer_map(self) -> typing.Dict[str, typing.List[Offer]]:
        """Filter Exchanges pair_offer_map for strategy."""


class Strategies(Schedulable):

    def __init__(self, strategies: typing.List[Strategy], *, loop=None) -> None:
        super().__init__()
        self.loop = loop or asyncio.get_event_loop()
        self.logger = logging.getLogger(f'{__name__}.{self.__class__.__name__}')

        self.strategies = strategies

    async def schedule(self):
        await asyncio.gather(*[
            strategy.schedule() for strategy in self.strategies
        ])
