import asyncio
from collections import defaultdict
from copy import copy
import logging
import sys
import time

from aiopg.sa import Engine

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.common import Debounced
from cryptotrader.common import floor_with_precision
from cryptotrader.common import Schedulable
from cryptotrader.exchange.base.session import Session
from cryptotrader.models import Order
from cryptotrader.models import PairName


class Exchange(Schedulable):

    NOT_ENOUGH_FUNDS = (
        'Order validation error. '
        'Not enough {money.currency} on {exchange_name} balance. '
        'Required {money.amount} {money.currency}.\n'
        'Available {balance} {money.currency}.\n'
        'Diff: {final_balance} {money.currency}.\n'
    )

    # Ignore PyDocStyleBear
    def __init__(
        self,
        session: Session,
        name: str,
        pairs: typing.List[str],
        fee: float,
        limit: float,
        pair_limits: typing.Balances,
        db: Engine,
        *,
        pair_name_template='{quote}{base}',
        currencies_map=None,
        fetch_balances_interval=1.0,
        update_tickers_interval=10.0,
        update_tickers_timeout=8.0,
        subscribe_on_pairs_delay=1.0,
        interval=10.0,
        loop=None,
    ) -> None:
        """
        :param subscribe_on_pairs_delay: delay between subscription calls on different pairs.
        For example Hitbtc requires it to prevent rate limit.
        """
        super().__init__()

        # system integration fields group
        self.logger = logging.getLogger(f'cryptotrader.exchange.{name}')
        self.tg = logging.getLogger('tg')
        self.loop = loop or asyncio.get_event_loop()
        self.db = db

        # exchange essential fields group
        self.session = session
        self.name = name
        # all pair names, supported by exchange
        self.default_pairs = pairs
        self.fee = fee
        self.limit = limit
        self.pair_limits = pair_limits
        self.pair_name_template = pair_name_template

        # time options fields group
        self.fetch_balances_debouncer = Debounced(fetch_balances_interval, self.loop)
        self.update_tickers_interval = update_tickers_interval
        # not used right now. Will be used at #412
        self.update_tickers_timeout = update_tickers_timeout
        self.subscribe_on_pairs_delay = subscribe_on_pairs_delay
        self.interval = interval

        # mutable data structures fields group
        # @todo #113:60m Rename `trade_history` table to `pairs_history`
        self.table = self.db.tables['trade_history']
        self.balances: typing.Balances = defaultdict(float)
        self._balances_cache: typing.Balances = defaultdict(float)
        self.pairs: typing.PairsData = defaultdict(lambda: defaultdict(float))
        self.currencies_map = currencies_map or {}

        self.is_running = asyncio.Event()

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, Exchange) and self.name == other.name

    def __ne__(self, other):
        return self.name != other.name

    @property
    def title(self):
        return self.name.capitalize()

    async def schedule(self):
        was_running = self.is_running.is_set()
        self.is_running.set()
        try:
            await self.session.schedule()
            if not was_running:
                # subscribe_on_pairs requires `self.is_running` to be set
                await self.subscribe_on_pairs()
            # fetch_balances depends on session predefined state
            await self.fetch_balances()
        except Exception as error:
            self.logger.exception(f'Schedule error: {error}')

    async def stop(self):
        self.is_running.clear()
        await self.session.stop()
        await super().stop()

    @property
    def balances_str(self):
        """
        Friendly looked string with balances.

        e.g. `bitfinex: ETC 0.0052, USD 79.85854617`
        """
        balances_str = ', '.join(
            f'{currency} {balance}'
            for currency, balance in self.balances.items()
            if balance > 0
        ) or 'no funds'
        return f'{self.name}: {balances_str}'

    # @todo #113:60m `Exchange.update_ticker` should not receive pair.
    #  Exchange has it's own pairs list - `default_pairs` field.
    #  So, let's use this pairs list in `Exchange.update_tickers`.
    async def update_tickers(self, pair: str) -> typing.Balances:
        """
        Fetch a relevant currency pair.

        The pair should be updated recently in a certain time interval,
        otherwise going to wait for the pair update.
        """
        def is_ready_to_fetch(period):
            return self.pairs[pair].get('time', -sys.maxsize) > period

        period = time.time() - self.interval
        while not is_ready_to_fetch(period):
            await asyncio.sleep(0.25)
        return self.pairs[pair]

    def calculate_balances_difference(self) -> typing.Dict[str, typing.Tuple[float, float]]:
        """Return difference in balances after last this function call."""
        difference = {}
        if self._balances_cache:
            for currency, amount in self.balances.items():
                cached_amount = self._balances_cache.get(currency, amount)
                if floor_with_precision(cached_amount - amount, precision=4) != 0:
                    difference[currency] = (cached_amount, amount)
        self._balances_cache = copy(self.balances)
        return difference

    def get_currency_limits(self) -> typing.Dict[str, float]:
        """
        Map currencies with it's min amount for order creation.

        :returns defaultdict(float)
        """
        def get_fresh_limit(currency, limit) -> float:
            old_limit = currency_limits[currency]
            return max(limit, old_limit)

        currency_limits: dict = defaultdict(float)
        for pair, limit in self.pair_limits.items():
            pair_name = PairName(pair)

            currency_limits[pair_name.quote] = get_fresh_limit(
                currency=pair_name.quote,
                limit=limit
            )

            # we take max possible value for limit for safety.
            # So, we use ask, not bid.
            price = self.pairs[pair]['ask']
            currency_limits[pair_name.base] = get_fresh_limit(
                currency=pair_name.base,
                limit=limit * price
            )

        return currency_limits

    async def report_balances(self):
        """Check balances and report if they was changed."""
        difference = self.calculate_balances_difference()
        not_enough_message = ''
        currency_limits = self.get_currency_limits()
        for currency in difference:
            if self.balances[currency] < currency_limits[currency]:
                not_enough_message += (
                    f'{currency} balance became not enough for order creation.\n'
                )

        # check if new balances less, then amount in pairs
        if difference:
            message = ', '.join(
                f'{amount:.4f} {currency} ({amount - cached_amount:.4f})'
                for currency, (cached_amount, amount) in difference.items()
            )
            self.logger.info(
                f'Exchange {self.title} balances changed:\n{message}\n{not_enough_message}\n'
            )
            self.tg.info(
                f'*Exchange {self.title} balances changed:*\n\n{message}\n{not_enough_message}\n',
            )

    async def on_ticker_update(
        self, pair_name: str, pair_data: typing.SessionFetchedPair
    ):
        # pair: str, bid_size: float, ask_size: float, bid: float, ask: float

        # @todo #382:60m Research for clear data type asserting at runtime.
        #  Create centralized, clear data types asserting
        #  for data structures such as `typing.SessionFetchedPair`.
        #  [Attrs lib](https://github.com/python-attrs/attrs) maybe good approach
        #  [first var](http://www.attrs.org/en/stable/examples.html#validators)
        #  and [second var](http://www.attrs.org/en/stable/examples.html#types)
        #  to decide it with attrs lib.
        for key in ['bid_size', 'ask_size', 'bid', 'ask']:
            assert isinstance(pair_data.pair[key], float), pair_data.pair[key]
        await self.set_pair(pair_name, pair_data)

    async def subscribe_on_pairs(self):
        # @todo #195 Try to reduce complexity of `subscribe_on_pairs`,
        #  using documentation or sharing of responsibility
        #  (e.g. separate subscribe_on_pair and subscribe_on_pairs methods).
        async def subscribe(pair: str):
            self.logger.debug(f'Subscribe on pair: {pair}')
            while self.is_running.is_set():
                try:
                    result = await self.session.fetch_pair(
                        pair, self.get_pair_limit(pair),
                    )
                    if result.success:
                        await self.on_ticker_update(
                            pair_name=pair,
                            pair_data=result
                        )
                    else:
                        self.logger.warning(
                            f'{pair} pair\'s data is not updated.'
                            f' Response: {result.response}'
                        )
                except Exception as error:
                    self.logger.exception(
                        f'Catch update pairs error: {error}'
                    )
                finally:
                    await asyncio.sleep(self.update_tickers_interval)
        for pair in self.default_pairs:
            self.ensure_future(subscribe(pair))
            await asyncio.sleep(self.subscribe_on_pairs_delay)

    async def fetch_balances(self) -> None:
        async with self.fetch_balances_debouncer:
            result = await self.session.fetch_balances()
            response = result.response
            if not result.success:
                self.logger.warning(
                    f'Fetch balances error. Response from exchange: {response}'
                )
            else:
                self.balances = result.balances

    async def fetch_status(self, order: Order) -> typing.FetchedOrderStatus:
        """
        Fetch status and set it to received order.

        :param order:
        :return: response data from exchange
        """
        if not order.id_on_exchange:
            raise ValueError(
                f'Order doesn\'t have exchange ID. {order}'
            )
        result = await self.session.fetch_status(order)
        self.logger.debug(
            'Fetch order status from exchange.'
            f' order.id_on_exchange={order.id_on_exchange}.'
            f' Response={result}.'
        )
        if result.success:
            if not result.status:
                self.logger.error(
                    'Exchange session returned empty order status.'
                )
                return typing.FetchedOrderStatus(response=result.response)
        else:
            self.logger.warning(
                f'Unknown order status. Response data: {result.response}\n'
            )
        return result

    async def place(self, order: Order) -> typing.PlacedOrder:
        assert not order.is_closed

        if not await self.validate(order):
            return typing.PlacedOrder(order_status=order.status)

        if order.status == const.PLACED:
            self.logger.warning(
                f'Order was already placed.'
                ' Skip order placing on exchange api call.'
            )
            self._log_place_order(False, order, '')
            return typing.PlacedOrder(
                order_id=order.id_on_exchange,
                order_status=order.status
            )

        place_result = await self.session.place(order)
        is_placed = place_result.order_status in [const.PLACED, const.FULFILLED]
        is_success = place_result.success and is_placed

        self._log_place_order(is_success, order, place_result.response)
        return typing.PlacedOrder(
            success=is_success,
            order_status=place_result.order_status,
            order_id=place_result.order_id,
            response=place_result.response,
        )

    def _log_place_order(self, is_success: bool, order: Order, response: str):
        self.logger.info(
            f'Place order result: success={is_success}, {order}, {response}.'
            f' {order.pair} data snapshot: {self.pairs[order.pair]}.'
        )

    # @todo #293 Add Exchange.cancel_by_id method.
    #  It's convenient for orders handy tests.
    async def cancel(self, order: Order) -> typing.CancelledOrder:
        if order.is_closed:
            message = 'Can not cancel closed order.'
            self.logger.warning(f'{message}\n{order}\n')
            return typing.CancelledOrder(response=message)

        if not order.id_on_exchange:
            raise ValueError(
                f'Order doesn\'t have exchange ID. {order}'
            )

        result = await self.session.cancel(order)
        if result.success:
            self.logger.info(f'Order cancelled. Order: {order}. Response: {result.response}')
        else:
            # exchange can refuse order cancelling by it's inner reasons.
            # For example order can be partially executed.
            # That's why "INFO" is good log level.
            self.logger.info(
                f'Can not cancel order {order}.'
                f' Exchange\'s response: {result.response}.'
            )
        return result

    async def validate(self, order: Order) -> bool:
        """Order sell currency should not exceed our exchange balance."""
        is_too_small = order.quote.amount < self.get_pair_limit(order.pair)
        if is_too_small:
            self.logger.info(
                'Order quantity is too small. Check `pairs` config section.'
                f' quantity={order.quote.amount:.4f}, {order}.'
            )
            return False

        quote_balance = self.get_balance(order.quote.currency)
        base_balance = self.get_balance(order.base.currency)

        final_quote_balance = quote_balance - const.get_factor(order.side) * order.quote.amount
        final_base_balance = base_balance + const.get_factor(order.side) * order.base.amount

        await asyncio.sleep(0)

        validation_log_message = (
            f'Validate order: {order}.\n'
            f'Quote balance: {quote_balance:.4f}.\n'
            f'Base balance: {base_balance:.4f}.\n'
            f'Final quote balance: {final_quote_balance:.4f}.\n'
            f'Final base balance: {final_base_balance:.4f}.\n'
        )
        self.logger.info(validation_log_message)
        is_quote_enough = floor_with_precision(final_quote_balance, 8) >= 0
        is_base_enough = floor_with_precision(final_base_balance, 8) >= 0

        if not is_quote_enough:
            self.logger.warning(
                self.NOT_ENOUGH_FUNDS.format(
                    money=order.quote,
                    exchange_name=order.exchange.name,
                    balance=quote_balance,
                    final_balance=final_quote_balance,
                )
            )
        if not is_base_enough:
            self.logger.warning(
                self.NOT_ENOUGH_FUNDS.format(
                    money=order.quote,
                    exchange_name=order.exchange.name,
                    balance=quote_balance,
                    final_balance=final_quote_balance,
                )
            )

        return is_quote_enough and is_base_enough

    def get_balance(self, currency: str) -> float:
        return self.balances.get(currency.upper(), 0.0)

    def get_pair_limit(self, pair: str) -> float:
        limit = self.pair_limits.get(
            pair, self.pair_limits.get(const.DEFAULT_PAIR, None),
        )
        if limit is None:
            self.logger.warning('Default limit value does not defined')
            limit = 0.0
        return limit

    def get_limit(self) -> float:
        return self.limit

    def get_pair_data(self, pair: str) -> typing.PairData:
        return self.pairs[pair]

    def is_pair_expired(self, pair: str) -> bool:
        return time.time() > self.pairs[pair]['time'] + self.interval

    async def get_fresh_pair(self, pair: str) -> typing.PairData:
        """Return guaranteed fresh pair data."""
        if self.is_pair_expired(pair):
            pair_data = await self.session.fetch_pair(pair, 0.0)
            if not pair_data.success:
                raise exception.FetchPairError(pair, pair_data.response)
            await self.set_pair(pair, pair_data)
        return self.pairs[pair]

    async def set_pair(self, pair_name: str, pair_data: typing.SessionFetchedPair):
        self.pairs[pair_name] = {**pair_data.pair, 'time': time.time()}

        async with self.db.acquire() as conn:
            insert = self.table.insert().values(
                exchange=self.name, pair=pair_name, **pair_data.pair
            )
            await conn.execute(insert)
