import asyncio
from collections import defaultdict
import logging

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.common import Schedulable
from cryptotrader.exchange.base import Exchange  # type: ignore
from cryptotrader.models import Offer


class Exchanges(Schedulable):

    def __init__(
        self,
        exchanges: typing.List[Exchange],
        # @todo #169 rename Exchanges.exchanges: List[Exchanges] field to Exchanges.map: Dict[str, Exchange].  # Ignore PycodestyleBear (E501)
        #  Where a key will be an exchange name and a value exchange.
        default_pairs: typing.Set[str],
        *,
        update_tickers_timeout=8.0,
        loop=None
    ) -> None:
        super().__init__()
        self.loop = loop or asyncio.get_event_loop()
        self.logger = logging.getLogger(f'cryptotrader.exchanges.{self.__class__.__name__}')
        self.tg = logging.getLogger('tg')

        self.exchanges = exchanges
        self.exchanges_map = {exchange.name: exchange for exchange in exchanges}
        self.default_pairs = default_pairs
        self.pairs: typing.Dict[str, typing.Dict[Exchange, dict]] = defaultdict(dict)
        self.update_tickers_timeout = update_tickers_timeout

    def get(self, name: str):
        try:
            return self.exchanges_map[name]
        except KeyError:
            raise exception.NoSuchExchangeError(name)

    async def schedule(self):
        await asyncio.gather(*[
            exchange.schedule() for exchange in self.exchanges
        ])
        await asyncio.gather(self.update_tickers(), self.report_balances())

    async def stop(self):
        await asyncio.gather(*[
            exchange.stop() for exchange in self.exchanges
        ])
        await super().stop()

    async def fetch_balances(self):
        await asyncio.gather(*[
            exchange.fetch_balances() for exchange in self.exchanges
        ])

    @property
    def balances_str(self):
        """
        Friendly looked string with balances.

        e.g. ```
        hitbtc: ETC 0.001, USD 20.001
        bitfinex: ETC 0.0052, USD 79.85854617
        ```
        """
        return '\n'.join(
            exchange.balances_str
            for exchange in self.exchanges
        )

    async def update_tickers(self):
        async def get_updated(
            exchange, pair
        ) -> typing.Union[typing.Tuple[Exchange, str, dict], None]:
            # @todo #409:30m  Remove timeout logic from `Exchanges.update_ticker`.
            #  Just return from `Exchange.update_ticker` stale pair value with warning.
            try:
                result = await asyncio.wait_for(
                    exchange.update_tickers(pair),
                    timeout=self.update_tickers_timeout
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    f'{exchange.title}.update_tickers task timed out with '
                    f'pair: {pair} ...'
                )
                return None
            return exchange, pair, result

        results = filter(None, await asyncio.gather(*[
            get_updated(exchange, pair)
            for pair in self.default_pairs
            for exchange in self.exchanges
        ]))

        pairs: typing.Dict[str, typing.Dict[Exchange, dict]] = defaultdict(dict)
        for exchange, pair, result in results:
            pairs[pair][exchange] = result
        self.pairs = pairs

    def calculate_balances_difference(self) -> typing.BalancesDifference:
        """Return difference in balances after last this function call."""
        result_diff: typing.BalancesDifference = {}
        for exchange in self.exchanges:
            exchange_diff = exchange.calculate_balances_difference()
            for currency, currency_diff in exchange_diff.items():
                result_diff[currency] = (
                    result_diff[currency][0] + currency_diff[0],
                    result_diff[currency][1] + currency_diff[1]
                )
        return result_diff

    async def report_balances(self):
        """Check balances and report if they was changed."""
        await asyncio.gather(*[
            exchange.report_balances()
            for exchange in self.exchanges
        ])

        difference = self.calculate_balances_difference()
        message = ', '.join(
            f'{amount:.4f} {currency} ({amount - cached_amount:.4f})'
            for currency, (cached_amount, amount) in difference.items()
        )

        if message:
            self.logger.info(f'Total balance of exchanges changed:\n{message}')
            self.tg.info(
                f'*Total balance of exchanges changed:*\n\n{message}',
            )

    # @todo #367:60m Write test for `Exchanges.get_pair_offer_map` method.
    #  Dangerous case: one item in `pairs` arg.
    def get_pair_offer_map(
        self, pair_names: typing.List[str] = None
    ) -> typing.Dict[str, typing.List[Offer]]:
        """Not plain list for performance."""
        offers: typing.Dict[str, typing.List[Offer]] = defaultdict(list)

        if pair_names:
            # evaluate to list for reach of the same type for pair_items
            pair_items = list(filter(
                lambda pair: pair[0] in pair_names,  # type: ignore
                self.pairs.items(),
            ))
        else:
            pair_items = list(self.pairs.items())

        for pair, exchange_price_map in pair_items:
            for exchange, price in exchange_price_map.items():
                offers[pair].append(Offer(
                    price_type=const.ASK,
                    pair=pair,
                    price=price[const.ASK],
                    quote=price['ask_size'],
                    exchange=exchange,
                    timestamp=price['time'],
                ))
                offers[pair].append(Offer(
                    price_type=const.BID,
                    pair=pair,
                    price=price[const.BID],
                    quote=price['bid_size'],
                    exchange=exchange,
                    timestamp=price['time'],
                ))
        if not offers:
            self.logger.warning('Offers list is empty')
        return offers
