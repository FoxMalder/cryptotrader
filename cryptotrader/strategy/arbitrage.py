# @todo #68 Describe Arbitrage's algorithms in more detail.

import asyncio
from datetime import datetime
from datetime import timedelta
import time

from aiopg.sa import Engine

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.exchange import Exchanges  # type: ignore
from cryptotrader.models import Money
from cryptotrader.models import Offer
from cryptotrader.models import Order
from cryptotrader.models import Queue
from cryptotrader.strategy import Strategy  # type: ignore

# @todo #394:30m Schedule daily csv report.
#  Take requirements from #372 (attached pdf file).

WINDOW_DETECTED = (
    '\nArbitrage window detected:\n'
    '{min_ask_offer}\n'
    '{max_bid_offer}\n'
)
NOT_ENOUGH_FUNDS = (
    '\nNot enough funds to proceed window.\n'
    '{ask_offer.exchange.name} balances: {ask_offer.exchange.balances}\n'
    '{bid_offer.exchange.name} balances: {bid_offer.exchange.balances}\n'
)
PLACE_ORDER_DECLINED = (
    '\nBot declined order with inner validation.'
    ' So, order placing cancelled:\n'
    '{order} - is not valid\n'
)
PLACE_ORDERS_ATTEMPT = (
    '\nSubmit orders on exchanges.\n'
    '{buy_order}\n'
    '{sell_order}\n'
)
PLACE_ORDERS_SUCCESS = (
    '\nArbitrage orders submitted successfully.\n'
    '{buy_order}\n'
    '{sell_order}\n'
)
REVERSE_ORDERS_ATTEMPT = (
    'Reversed orders found. Placing them:'
    ' {buy_order} {sell_order}.'
)
PLACE_ORDER_FAIL = (
    '\nArbitrage order submit failed.\n'
    '{order}\n'
    'Exchange {order.exchange.name}\'s response: {exchange_response_data}\n'
)
PLACE_REVERSED_ORDER_FAIL = (
    '\nArbitrage reversed order submit failed.\n'
    '{order}\n'
    'Exchange {order.exchange.name}\'s response: {exchange_response_data}\n'
)
SUBMIT_REVERSED_ORDER_AFTER_FAIL = (
    '\n**WARNING**\n'
    'Arbitrage placed order {order}. But it **can\'t reverse** it.'
    ' Please create reversed order {reversed_order} manually.'
    ' Otherwise, arbitrage is not able to continue working with exchange **{order.exchange.name}**.'
)
REVERSE_ORDERS_SUCCESS = (
    '\nArbitrage reverse orders submitted successfully:\n'
    '{buy_order}\n'
    '{sell_order}\n'
)


def get_max_spend(*offers, max_spend_part=1.0) -> typing.Tuple[Money, Money]:
    """
    Calculate max quote amount and base amount for ask and bid offers accordingly.

    "Max" - because calculated sums is max to spend on exchanges.
    So, in fact we calculate min sums.
    Both amounts depend on:
     - our balance on exchanges
     - exchange limit, it's hand-set in config
    :param offers:
    :param max_spend_part: only this part of funds will be calculated to spend.
    :return:
    """
    # @todo #22 - calc arbitrage get_max_spend() with exchange's fee
    #  fee = bid_exchange_inst.config.get('fee', 0.95)

    # @todo #341:60m Refactor get_max_spend function.
    #  The function takes list of `*offers`, but we work with offer pair (ask/bid).
    #  get_max_offer_and_balance contains redundant `for-loop` and `if` branches.
    def get_max_offer_and_balance(price_type: str) -> typing.Tuple[float, float, Offer]:
        min_amount = const.MAX_SUM
        min_price = 0.0
        min_offer = None
        for offer in offers:
            if offer.price_type == price_type:
                offer_money = (
                    offer.price_type == const.ASK and offer.base
                    or offer.price_type == const.BID and offer.quote
                )
                balance = offer.exchange.get_balance(
                    offer_money.currency
                )
                amount = min(balance, offer_money.amount)
                if amount < min_amount:
                    min_amount, min_price, min_offer = amount, offer.price, offer
        assert min_offer, 'Min offer not found'
        return min_amount, min_price, min_offer

    base_currency = offers[0].base.currency
    quote_currency = offers[0].quote.currency
    for offer in offers:
        assert offer.base.currency == base_currency
        assert offer.quote.currency == quote_currency

    exchange_limit = min(
        [offer.exchange.get_limit() or const.MAX_SUM for offer in offers]
    )

    max_base_sum, max_base_price, ask_offer = get_max_offer_and_balance(const.ASK)
    max_quote_sum, max_quote_price, bid_offer = get_max_offer_and_balance(const.BID)

    # sync max_base and max_quote values
    # We use `max_base_price` in both cases,
    # because we require ask and bid quote money equality
    # as result of calculation.
    max_quote_sum = min(max_quote_sum, max_base_sum / max_base_price)
    max_base_sum = min(max_base_sum, max_quote_sum * max_base_price)

    # in theory one exchange.fee is enough.
    # But coefficient "2" was added for a while in stability purposes.
    max_base_sum = max_base_sum * (1.0 - 2 * ask_offer.exchange.fee)
    max_quote_sum = max_quote_sum * (1.0 - 2 * bid_offer.exchange.fee)

    max_base_sum = max_base_sum * max_spend_part
    max_quote_sum = max_quote_sum * max_spend_part

    max_quote_sum_or_limit = min(max_quote_sum, exchange_limit)

    return (
        Money(max_base_sum, base_currency),
        Money(max_quote_sum_or_limit, quote_currency)
    )


# @todo #337 Test ArbitrageWindow class.
class ArbitrageWindow:
    """
    Special prices state of ticker's pair.

    This two tickers have boundaries:
        - came from different exchanges;
        - represent the same currency pair;
        - have prices state, described below.
    We represent this ticker pair's state with two offers.

    Prices state definition is simple. With opened window should be able:
        - to buy some currency amount on one exchange,
        - then to immediately sell this amount on another exchange with profit.
    """

    def __init__(  # Ignore PyDocStyleBear
        self,
        ask_offer: Offer, bid_offer: Offer,
        direct_width=1.0, reversed_width=1.0
    ) -> None:
        """
        :param direct_width: measure for guaranteed profit.
        Used to define opened orders.
        For example:
        - direct_width = 1.2 - arbitrage works with profit from 20%
        - direct_width = 0.8 - arbitrage works with profit from -20%
        :param reversed_width: measure for guaranteed non profit.
        Used to define closed orders.
        Should be less or equal, then direct_width
        """
        self._assert_offers(ask_offer, bid_offer)
        self.ask_offer = ask_offer
        self.bid_offer = bid_offer
        self.direct_width = direct_width
        self.reversed_width = reversed_width

    def report_str(self) -> str:
        return (
            f'Pair - {self.ask_offer.pair}\n'
            f'{self.ask_offer.report_str()}\n'
            f'{self.bid_offer.report_str()}\n'
        )

    @staticmethod
    def _assert_offers(ask_offer: Offer, bid_offer: Offer):
        assert ask_offer.price_type == const.ASK
        assert bid_offer.price_type == const.BID
        assert ask_offer.pair == bid_offer.pair, [str(ask_offer), str(bid_offer)]

    @property
    def exists(self):
        return (
            self.ask_offer
            and self.bid_offer
            and self.ask_offer.exchange != self.bid_offer.exchange
        )

    @property
    def is_opened(self) -> bool:
        """
        When window is open, when direct orders pair is profitable.

        See algorithm description:
        ./arbitrage_bot_usage.md#window_direct_width
        """
        return (
            self.ask_offer.total_price * self.direct_width < self.bid_offer.total_price
        )

    @property
    def is_closed(self) -> bool:
        """
        When window is closed, reversed orders pair is profitable.

        See algorithm description:
        ./arbitrage_bot_usage.md#window_reverse_width
        """
        return self.ask_offer.price * self.reversed_width >= self.bid_offer.price


class ArbitrageOrdersPair:
    """
    Pair of direct/reversed orders.

    This pair opens/closes arbitrage strategy for specified window.
    """

    def __init__(
        self,
        window: ArbitrageWindow,
        max_spend_part: float,
        order_type: str,
        logger,
        tg,
    ) -> None:
        max_base, max_quote = get_max_spend(
            window.ask_offer, window.bid_offer,
            max_spend_part=max_spend_part
        )

        if max_base.amount and max_quote.amount:
            buy_order = Order(offer=window.ask_offer, type_=order_type)
            sell_order = Order(offer=window.bid_offer, type_=order_type)

            buy_order.set_base(max_base)
            sell_order.set_quote(max_quote)

            self.buy_order = buy_order
            self.sell_order = sell_order
            self.logger = logger
            self.tg = tg
        else:
            logger.debug(NOT_ENOUGH_FUNDS.format(
                ask_offer=window.ask_offer,
                bid_offer=window.bid_offer,
            ))

    @property
    def orders(self) -> typing.Tuple[Order, Order]:
        return getattr(self, 'buy_order', None), getattr(self, 'sell_order', None)

    async def is_valid(self) -> bool:
        if not all(self.orders):
            return False

        is_buy_order_valid = await self.buy_order.exchange.validate(self.buy_order)
        is_sell_order_valid = await self.sell_order.exchange.validate(self.sell_order)
        is_valid_result = is_buy_order_valid and is_sell_order_valid

        if not is_buy_order_valid:
            self.logger.debug(PLACE_ORDER_DECLINED.format(order=self.buy_order))
        if not is_sell_order_valid:
            self.logger.debug(PLACE_ORDER_DECLINED.format(order=self.sell_order))

        if not is_valid_result:
            def not_enough_message(order_):
                return f'Not enough funds on {order_.exchange.name}\n'
            self.tg.error(
                f'{const.EMOJI.SOS} **Orders place error**\n'
                f'{not_enough_message(self.buy_order) if not is_buy_order_valid else ""}'
                f'{not_enough_message(self.sell_order) if not is_sell_order_valid else ""}'
                f'Pair - {self.buy_order.pair}\n'
                f'{self.buy_order.report_str()}\n'
                f'{self.sell_order.report_str()}\n'
                f'{const.EMOJI.RED_CIRCLE} **Please add funds**',
            )

        return is_valid_result

    async def save(self, db: Engine):
        await asyncio.gather(
            self.buy_order.save(db),
            self.sell_order.save(db)
        )

    async def delete(self, db: Engine):
        await asyncio.gather(
            self.buy_order.delete(db),
            self.sell_order.delete(db)
        )


class Arbitrage(Strategy):
    """
    See Glossary for Arbitrage term.

    Arbitrage algorithm in outline:
    - take all current exchanges offers
    - find arbitrage window (see class ArbitrageWindow)
    - create orders from window and place it
    - wait until window is closed
    - create reversed orders and place them
    - profit
    """

    title = 'Arbitrage'

    def __init__(
        self, exchanges: Exchanges, pairs: typing.Set, db: Engine,
        to_reverse: Queue, loop=None,
        *,
        window_direct_width=1.0, window_reversed_width=1.0,
        max_spend_part=1.0,
        interval=10.0,
        order_placement_interval=5.0,
        fetch_order_interval=5.0,
        sleep_after_placed=1.0,
        autoreverse_order_delta=timedelta(days=2),
        order_timeout=10.0,
        order_type=const.LIMIT,
    ) -> None:
        super().__init__(exchanges, db, loop=loop)
        if not all(pair in exchanges.default_pairs for pair in pairs):
            raise ValueError(
                'Exchanges can not handle Arbitrage\'s pairs. '
                f'Exchanges handled pairs: {", ".join(exchanges.default_pairs)}. '
                f'Arbitrage pairs: {", ".join(pairs)}'
            )
        self.pairs = pairs
        self.window_direct_width = window_direct_width
        self.window_reversed_width = window_reversed_width
        self.to_reverse = to_reverse
        self.max_spend_part = max_spend_part
        self.autoreverse_order_delta = autoreverse_order_delta
        self.interval = interval
        self.order_placement_interval = order_placement_interval
        self.order_type = order_type
        self.trade_timings = {
            'fetch_order_interval': fetch_order_interval,
            'sleep_after_placed': sleep_after_placed,
            'timeout': order_timeout,
        }

    async def schedule(self):
        await self.exit()
        await self.enter()

    async def enter(self):
        window = self.locate_window()
        if window:
            self.logger.info(
                WINDOW_DETECTED.format(
                    min_ask_offer=window.ask_offer,
                    max_bid_offer=window.bid_offer,
                )
            )
            # @todo #372:120m Test arbitrage report behavior.
            #  Report system is business level feature, it should be tested.
            #  We don't need to test messages content,
            #  but need to test theirs behavior.
            self.tg.info(
                f'{const.EMOJI.WARNING_SIGN} Arbitrage window detected\n'
                f'{window.report_str()}',
            )
            await self.process_window(window)
            await asyncio.sleep(self.order_placement_interval)

    async def exit(self):
        await self.reverse_orders()

    # @todo #220 Split huge Arbitrage.reverse_orders()
    async def reverse_orders(self):
        """
        Perform arbitrage reverse operation.

        Create arbitrage reverse orders and place them on exchange.
        Reverse operation is performed only for successfully placed orders pair.
        And only when their arbitrage window is closed.
        :return:
        """
        length = await self.to_reverse.length()

        # this cycle and whole method has terrible structure.
        # It'll be refactored at #278
        for _ in range(0, length):
            buy_order, sell_order = await self.to_reverse.pop()
            self.logger.debug(
                f'Non reversed orders from storage: {buy_order} {sell_order}'
            )

            assert buy_order.side == const.BUY, buy_order
            assert sell_order.side == const.SELL, sell_order

            try:
                new_ask_offer = await buy_order.offer.refreshed()
                new_bid_offer = await sell_order.offer.refreshed()
            except exception.FetchPairError as e:
                await self.to_reverse.push([buy_order, sell_order])
                prose_message = (
                    ' Can\'t get fresh offers to build reversed orders.'
                    ' Bot will try to reverse this orders lately.'
                )
                self.logger.warning(
                    f'{e.message}. {prose_message}'
                )
                self.logger.warning(prose_message)
                continue

            # @todo #336:60m Add ability to mark pair as stale.
            #  Improve `Exchange.pairs` structure
            #  to mark non fetched pairs as stale.
            #  miss stale pairs in `Arbitrage.reverse_order` iteration.
            #  And raise ValueError for missed pairs in offers list.
            if not (new_ask_offer and new_bid_offer):
                await self.to_reverse.push([buy_order, sell_order])
                continue

            fresh_window = ArbitrageWindow(
                new_ask_offer, new_bid_offer,
                self.window_direct_width,
                self.window_reversed_width,
            )

            expired = self.are_orders_expired([buy_order, sell_order])
            if not (fresh_window.is_closed or expired):
                # return orders group to queue
                await self.to_reverse.push([buy_order, sell_order])
                continue
            reversed_buy_order = await self.get_reversed_order(buy_order)
            reversed_sell_order = await self.get_reversed_order(sell_order)
            self.logger.debug(REVERSE_ORDERS_ATTEMPT.format(
                buy_order=reversed_buy_order,
                sell_order=reversed_sell_order,
            ))

            if expired:
                message = (
                    f'A pair of orders have expired {self.autoreverse_order_delta},'
                    ' so they will be reversed.'
                    f' Buy order: {buy_order}. Sell order: {sell_order}.'
                )
                self.logger.info(message)
                self.tg.info(
                    f'{const.EMOJI.WARNING_SIGN} **Pair of orders auto reverse**\n{message}',
                )

            self.logger.debug(REVERSE_ORDERS_ATTEMPT.format(
                buy_order=reversed_buy_order,
                sell_order=reversed_sell_order,
            ))
            self.tg.debug(
                f'{const.EMOJI.WARNING_SIGN} **Reversed pairs detected**\n'
                f'Pair - {reversed_buy_order.pair}\n'
                f'{reversed_buy_order.report_str()}\n'
                f'{reversed_sell_order.report_str()}',
            )

            is_buy_order_valid = await reversed_buy_order.exchange.validate(
                reversed_buy_order
            )
            is_sell_order_valid = await reversed_sell_order.exchange.validate(
                reversed_sell_order
            )

            if not (is_buy_order_valid and is_sell_order_valid):
                # return orders group to queue
                await self.to_reverse.push([buy_order, sell_order])
                continue

            buy_is_success, buy_response = (
                await reversed_buy_order.trade(**self.trade_timings)
            )
            sell_is_success, sell_response = (
                await reversed_sell_order.trade(
                    **self.trade_timings
                )
            )

            asyncio.ensure_future(reversed_buy_order.save(self.db))
            asyncio.ensure_future(reversed_sell_order.save(self.db))

            if not buy_is_success:
                self._log_place_reversed_order_fail(
                    order=reversed_buy_order,
                    exchange_response=buy_response,
                )
            if not sell_is_success:
                self._log_place_reversed_order_fail(
                    order=reversed_sell_order,
                    exchange_response=sell_response,
                )

            if buy_is_success and sell_is_success:
                self.logger.debug(REVERSE_ORDERS_SUCCESS.format(
                    buy_order=buy_order,
                    sell_order=sell_order,
                ))
                self.tg.info(
                    f'{const.EMOJI.CHECK_MARK} **Reversed orders placed successfully**\n'
                    f'Pair - {buy_order.pair}\n'
                    f'{reversed_buy_order.report_str()}\n'
                    f'{reversed_sell_order.report_str()}',
                )
            else:
                self.tg.info(
                    f'{const.EMOJI.SOS} **Reverse orders place error**\n'
                    f'Pair - {reversed_buy_order.pair}\n'
                    'Timeout\n'
                    f'{reversed_buy_order.report_str()}\n'
                    f'{reversed_sell_order.report_str()}',
                )

    def are_orders_expired(self, orders: typing.List[Order]) -> bool:
        expired_after = datetime.utcnow() - self.autoreverse_order_delta
        return all(
            order.executed_at < expired_after
            for order in orders
        )

    def _log_place_reversed_order_fail(self, order: Order, exchange_response: str):
        self.logger.debug(PLACE_REVERSED_ORDER_FAIL.format(
            order=order,
            exchange_response_data=exchange_response,
        ))

    # @todo #416:30m Move `Arbitrage.get_reversed_order` to `Order`.
    async def get_reversed_order(self, order: Order) -> typing.Union[Order, None]:
        """
        Get an order to reverse.

        :param order:
        :return:
            Order placing result structure:
                - bool result
                - dict with additional data
        """
        reversed_offer = order.offer.reversed()
        try:
            fresh_offer = await reversed_offer.refreshed()
        except exception.FetchPairError as e:
            # use stale offer as fresh for fault tolerance.
            # Reversed orders always have `exchange market` order type.
            # So, stale offer should not be distructive.
            fresh_offer = reversed_offer
            self.logger.warning(
                f'{e.message}. Bot use stale offer to build reversed order.'
            )

        return order.reversed(new_price=fresh_offer.price)

    async def reverse_order(self, order):
        reversed_order = await self.get_reversed_order(order)
        if reversed_order:
            await reversed_order.validate()
            await reversed_order.trade()

    def get_pair_offer_map(
        self, pair_names: typing.List[str] = None,
    ) -> typing.Dict[str, typing.List[Offer]]:
        pair_offer_map = self.exchanges.get_pair_offer_map(pair_names or self.pairs)
        expired_at = time.time() - self.interval
        return {
            pair_name: [
                offer for offer in offers
                if (
                    offer.in_pair_limit(max_spend_part=self.max_spend_part)
                    and offer.timestamp >= expired_at
                )
            ]
            for pair_name, offers in pair_offer_map.items()
        }

    def locate_window(self) -> typing.Union[ArbitrageWindow, None]:
        """
        Find most profitable pair.

        Scan all current exchange offers and find one, the most profitable
        pair of offers(arbitrage window).
        :return: opened arbitrage window
        """
        pair_offer_map = self.get_pair_offer_map()
        for pair in pair_offer_map:
            max_bid_offer, min_ask_offer = None, None
            for offer in pair_offer_map[pair]:
                if offer.price_type == const.BID:
                    if not max_bid_offer or max_bid_offer.price < offer.price:
                        max_bid_offer = offer
                if offer.price_type == const.ASK:
                    if not min_ask_offer or min_ask_offer.price > offer.price:
                        min_ask_offer = offer
            if min_ask_offer and max_bid_offer:
                window = ArbitrageWindow(
                    min_ask_offer, max_bid_offer,
                    self.window_direct_width,
                    self.window_reversed_width,
                )
                if window.exists and window.is_opened:
                    return window
        return None

    async def place(self, orders_pair: ArbitrageOrdersPair) -> bool:
        buy_order, sell_order = orders_pair.orders

        self._log_place_attempt(orders_pair)
        (buy_is_success, buy_response), (sell_is_success, sell_response) = await asyncio.gather(
            buy_order.trade(**self.trade_timings), sell_order.trade(**self.trade_timings),
        )

        if not buy_is_success:
            self._log_place_order_fail(buy_order, buy_response)
            if sell_is_success:
                await self.reverse_order(sell_order)

        if not sell_is_success:
            self._log_place_order_fail(sell_order, sell_response)
            if buy_is_success:
                await self.reverse_order(buy_order)

        # save orders_pair in blocking way
        # to continue working with them from db
        await orders_pair.save(self.db)

        if sell_is_success and buy_is_success:
            self._log_place_success(orders_pair)
        else:
            def error_message(order_):
                return f'Error on exchange {order_.exchange.name}\n'
            self.tg.error(
                f'{const.EMOJI.SOS} **Orders place error**\n'
                f'{error_message(buy_order) if not buy_is_success else ""}'
                f'{error_message(sell_order) if not sell_is_success else ""}'
                f'Pair - {buy_order.pair}\n'
                f'{buy_order.report_str()}\n'
                f'{sell_order.report_str()}',
            )

        return sell_is_success and buy_is_success

    def _log_place_attempt(self, orders_pair: ArbitrageOrdersPair):
        buy_order, sell_order = orders_pair.orders

        self.logger.debug(
            PLACE_ORDERS_ATTEMPT.format(
                buy_order=buy_order,
                sell_order=sell_order,
            )
        )

    def _log_place_success(self, orders_pair: ArbitrageOrdersPair):
        buy_order, sell_order = orders_pair.orders

        self.logger.debug(PLACE_ORDERS_SUCCESS.format(
            buy_order=buy_order,
            sell_order=sell_order,
        ))
        self.tg.info(
            f'{const.EMOJI.CHECK_MARK} **Orders placed successfully**\n'
            f'Pair - {buy_order.pair}\n'
            f'{buy_order.report_str()}\n'
            f'{sell_order.report_str()}',
        )

    def _log_place_order_fail(self, order: Order, exchange_response: str):
        self.logger.warning(PLACE_ORDER_FAIL.format(
            order=order,
            exchange_response_data=exchange_response,
        ))

    async def cancel(self, orders_pair: ArbitrageOrdersPair):
        self.logger.debug('Arbitrage.cancel method is not implemented yet')

    # @todo #220 Change place_orders method semantic
    #  Method have bad name and bad semantic, that's not clear separated.
    #  Research how we can regroup methods.
    #  If it's impossible - explain why in comment ant close task.
    async def process_window(self, window: ArbitrageWindow):
        """
        Create orders and place them on exchanges.

        Orders are created from arbitrage window, represented as offers pair.
        :param window:
        :return:
        """
        orders_pair = ArbitrageOrdersPair(
            window,
            max_spend_part=self.max_spend_part,
            logger=self.logger,
            order_type=self.order_type,
            tg=self.tg,
        )

        if await orders_pair.is_valid() and window.is_opened:
            place_is_success = await self.place(orders_pair)
            if place_is_success:
                await self.to_reverse.push(orders_pair.orders)
            else:
                await self.cancel(orders_pair)
