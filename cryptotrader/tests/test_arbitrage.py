import asyncio
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
import time
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.exchange import Exchange
from cryptotrader.exchange import Exchanges
from cryptotrader.models import Offer
from cryptotrader.models import Order
from cryptotrader.strategy.arbitrage import Arbitrage
from cryptotrader.strategy.arbitrage import ArbitrageWindow
from cryptotrader.strategy.arbitrage import get_max_spend
from cryptotrader.tests import mock
from cryptotrader.tests import utils


@pytest.fixture(scope='function')
def patched_exchanges(event_loop, exchange_data):
    return Exchanges(
        exchanges=[
            Exchange(
                session=mock.MockSession(
                    pairs={
                        'ETCUSD': {
                            'ask': 290.0,
                            'bid': 280.0,
                            'ask_size': float(const.MAX_SUM),
                            'bid_size': float(const.MAX_SUM),
                        },
                    },
                ),
                name='left',
                **exchange_data
            ),
            Exchange(
                session=mock.MockSession(
                    pairs={
                        'ETCUSD': {
                            'ask': 330.0,
                            'bid': 312.0,
                            'ask_size': float(const.MAX_SUM),
                            'bid_size': float(const.MAX_SUM),
                        },
                    },
                ),
                name='right',
                **exchange_data
            ),
        ],
        loop=event_loop,
        default_pairs={'ETCUSD', 'BTCUSD'},
    )


@pytest.fixture
def patched_arbitrage(event_loop, db, patched_exchanges):
    return Arbitrage(  # type: ignore
        exchanges=patched_exchanges,
        to_reverse=mock.MockQueue(),
        pairs={'BTCUSD', 'ETCUSD'},
        db=db,
        fetch_order_interval=0.1,
        order_placement_interval=0.0,
        sleep_after_placed=0.0,
        order_timeout=0.5,
        loop=event_loop,
    )


@pytest.fixture
async def arbitrage_with_offers(request, patched_arbitrage):
    """
    Create arbitrage object and pair of exchange objects.

    Prepare arbitrage object, so its state contains `to_reverse` Orders pair.
    Use only hardcoded values for initial balances and tickers.
    So, client code magically knows this hardcoded values.
    :return:
        arbitrage object
    """
    patched_exchanges = patched_arbitrage.exchanges
    exchange_left, exchange_right = patched_exchanges.exchanges

    # 1. Update exchange balances: USD 300 / ETC 1.0
    exchange_left.session.balances = {'USD': 300.0, 'ETC': 1.0}
    exchange_right.session.balances = {'USD': 300.0, 'ETC': 1.0}

    # 2. Fill Exchange from Session
    schedulable = utils.ScheduleManager([
        patched_arbitrage.exchanges,
        patched_arbitrage,
    ])

    exchanges_pair_data = getattr(request, 'param', {})

    def fetch_fresh_pair_fn(pair_data):
        async def fetch_fresh_pair(pair, limit=0.0):
            return typing.SessionFetchedPair(
                success=True,
                pair=pair_data,
                response='ok',
            )
        return fetch_fresh_pair

    async with schedulable:
        # 3. Assert balances: 2 ETC / 10 USD || 0 ETC / 612 USD
        assert exchange_left.balances['ETC'] == 2.0
        assert exchange_left.balances['USD'] == 10.0
        assert exchange_right.balances['ETC'] == 0.0
        assert exchange_right.balances['USD'] == 612.0

        if exchanges_pair_data:
            exchange_left.session.fetch_pair = fetch_fresh_pair_fn(
                defaultdict(float, exchanges_pair_data['left'])
            )
            exchange_right.session.fetch_pair = fetch_fresh_pair_fn(
                defaultdict(float, exchanges_pair_data['right'])
            )

        # make pairs not actual to launch fetch pair mech
        exchange_left.is_pair_expired = Mock(return_value=True)
        exchange_right.is_pair_expired = Mock(return_value=True)

        yield patched_arbitrage


def test_arbitrage_window_success(arbitrage_with_offers):
    window = arbitrage_with_offers.locate_window()
    assert window.exists and window.is_opened


def test_arbitrage_window_fail(patched_arbitrage):
    patched_exchanges = patched_arbitrage.exchanges
    exchange_left, exchange_right = patched_exchanges.exchanges
    patched_exchanges.pairs = {
        # okcoin.ask > bitfinex.bid for both pairs. So, we have no opened window
        'BTCUSD': {
            exchange_left: {
                'ask': 295.0,
                'bid': 290.0,
                'ask_size': 10**8,
                'bid_size': 10**4,
                'time': time.time(),
            },
            exchange_right: {
                'ask': 296.0,
                'bid': 291.0,
                'ask_size': 10**8,
                'bid_size': 10**4,
                'time': time.time(),
            },
        },
        'ETCUSD': {
            exchange_left: {
                'ask': 295.0,
                'bid': 290.0,
                'ask_size': 10**8,
                'bid_size': 10**4,
                'time': time.time(),
            },
            exchange_right: {
                'ask': 296.0,
                'bid': 291.0,
                'ask_size': 10**8,
                'bid_size': 10**4,
                'time': time.time(),
            },
        },
    }
    window = patched_arbitrage.locate_window()
    assert not window


@pytest.mark.parametrize('ask_offer,bid_offer,left_exchange,right_exchange,expected', [
    ({}, {}, '', '', True),
    ({}, {'price_type': const.ASK}, '', '', False),  # similar price_type
    ({}, {}, 'left', 'left', False),  # similar exchanges
])
def test_arbitrage_window_rare_offers(
    arbitrage_with_offers,
    ask_offer, bid_offer,
    left_exchange, right_exchange,
    expected
):
    """Method raises no error for pair_offer_map corner cases for offer lists."""
    def get_exchange(name):
        return arbitrage_with_offers.exchanges.get(name)

    ask_offer_data = {
        'pair': 'BTCUSD',
        'price_type': const.ASK,
        'quote': 1.0,
        'price': 290.0,
        'timestamp': time.time(),
        **ask_offer,
        'exchange': get_exchange(left_exchange or 'left'),
    }
    bid_offer_data = {
        'pair': 'BTCUSD',
        'price_type': const.BID,
        'quote': 1.0,
        'price': 312.0,
        'timestamp': time.time(),
        **bid_offer,
        'exchange': get_exchange(right_exchange or 'right'),
    }

    pair_offer_map_bad = {
        'BTCUSD': [Offer(**ask_offer_data), Offer(**bid_offer_data)],
    }
    arbitrage_with_offers.get_pair_offer_map = MagicMock(
        return_value=pair_offer_map_bad
    )
    window = arbitrage_with_offers.locate_window()
    assert bool(window) == expected


@pytest.mark.asyncio
async def test_process_window_success(ask_offer_data, bid_offer_data, patched_arbitrage):
    """Arbitrage should successfully place correct orders on exchanges."""
    exchange_left, exchange_right = patched_arbitrage.exchanges.exchanges
    ask_offer = Offer(**ask_offer_data, exchange=exchange_left)  # type: ignore
    bid_offer = Offer(**{
        **bid_offer_data,
        'exchange': exchange_right,
        'price': 10000.0,
    })

    window = ArbitrageWindow(ask_offer, bid_offer)
    exchange_left.session.balances = {
        'USD': 50000.0,
        'BTC': 8.0,
        'ETC': 0.0,
    }
    exchange_right.session.balances = {
        'USD': 10000.0,
        'BTC': 4.0,
        'ETC': 0.0,
    }

    schedulable = utils.ScheduleManager([
        patched_arbitrage.exchanges,
    ])

    async with schedulable:
        await patched_arbitrage.process_window(window)

        # is orders placed and processed on exchange

        assert exchange_left.balances['USD'] == 30000.0
        assert exchange_left.balances['BTC'] == 12.0
        assert exchange_right.balances['USD'] == 50000.0
        assert exchange_right.balances['BTC'] == 0.0


@pytest.mark.asyncio
async def test_process_window_fail(ask_offer_data, bid_offer_data, patched_arbitrage):
    """Arbitrage should not successfully place incorrect orders on exchanges."""
    exchange_left, exchange_right = patched_arbitrage.exchanges.exchanges

    # bid price is lesser then ask price
    ask_offer = Offer(**{
        **ask_offer_data,
        'exchange': exchange_left,
        'price': 8000.0,
    })
    bid_offer = Offer(**bid_offer_data, exchange=exchange_right)  # type: ignore

    window = ArbitrageWindow(ask_offer, bid_offer)
    exchange_left.balances = {
        'USD': 48000.0,
        'BTC': 8.0,
        'ETC': 0.0,
    }
    exchange_right.balances = {
        'USD': 10000.0,
        'BTC': 4.0,
        'ETC': 0.0,
    }
    # create arbitrage instance

    await patched_arbitrage.process_window(window)

    # is orders placed and processed on exchange?
    # They wouldn't
    assert exchange_left.balances['USD'] == 48000.0
    assert exchange_left.balances['BTC'] == 8.0
    assert exchange_right.balances['USD'] == 10000.0
    assert exchange_right.balances['BTC'] == 4.0


@pytest.mark.parametrize(
    'arbitrage_with_offers',
    [({'left': {'ask': 666.0, 'bid': 305.0}, 'right': {'ask': 310.0, 'bid': 666.0}})],
    indirect=['arbitrage_with_offers']
)
@pytest.mark.asyncio
async def test_reverse_arbitrage(arbitrage_with_offers):
    # 1. Get arbitrage object with filled `to_reverse` field
    # Both exchange objects contain hardcoded balances.
    # They were filled special for this test.
    exchanges = arbitrage_with_offers.exchanges
    exchange_left, exchange_right = exchanges.exchanges

    # 2. arbitrage.pairs = ETCUSD (305/310) was set with parametrize

    await arbitrage_with_offers.enter()
    await arbitrage_with_offers.exit()
    # 3. Assert balances: 1 ETC / 315 USD || 1 ETC / 302 USD
    assert exchange_left.balances['ETC'] == 1.0
    assert exchange_left.balances['USD'] == 315.0
    assert exchange_right.balances['ETC'] == 1.0
    assert exchange_right.balances['USD'] == 302.0


@pytest.mark.parametrize(
    'arbitrage_with_offers',
    [({'left': {'ask': 666.0, 'bid': 305.0}, 'right': {'ask': 320.0, 'bid': 666.0}})],
    indirect=['arbitrage_with_offers']
)
@pytest.mark.asyncio
async def test_reverse_arbitrage_less_balances(arbitrage_with_offers):
    # 1. Get arbitrage object with filled `to_reverse` field.
    # Both exchange objects contain hardcoded balances.
    # They were filled special for this test.
    exchanges = arbitrage_with_offers.exchanges
    exchange_left, exchange_right = exchanges.exchanges

    # 2. arbitrage.pairs = ETCUSD (305/310) was set with parametrize
    await arbitrage_with_offers.exit()

    # 3. Assert balances: 1 ETC / 315 USD || 1 ETC / 304 USD
    assert exchange_left.balances['ETC'] == 1.0
    assert exchange_left.balances['USD'] == 315.0
    assert exchange_right.balances['ETC'] == 1.0
    assert exchange_right.balances['USD'] == 292.0


# @todo #495:60m Merge get_max_spend tests into one function.
#  Use pytest parametrize.

# @todo #495:60m Fix get_max_spend function.
#  get_max_spend function should take into account offer quote size.
#  Test below should pass.

def test_get_max_spend_in_offer_bounds(ask_offer_data, bid_offer_data, patched_exchanges):
    """get_max_spend function should take into account offer quote size."""
    ask_exchange, bid_exchange = patched_exchanges.exchanges

    # 50000.0 > 3.0 * 5000.0, so bound is on ask_offer quote amount
    ask_exchange.balances = {
        'USD': 50000.0,
        'BTC': 7.0,
    }
    bid_exchange.balances = {
        'USD': 30000.0,
        'BTC': 10.0,
    }

    ask_offer = Offer(  # type: ignore
        **{
            **ask_offer_data,
            'price': 5000.0,
            'quote': 3.0,
        },
        exchange=ask_exchange
    )
    bid_offer = Offer(  # type: ignore
        **{
            **bid_offer_data,
            'price': 5000.0,
            'quote': 5.0,
        },
        exchange=bid_exchange
    )

    max_base, max_quote = get_max_spend(ask_offer, bid_offer)
    assert max_base == ask_offer.base
    assert max_quote == ask_offer.quote


def test_get_max_spend_ask_enough(ask_offer_data, bid_offer_data, patched_exchanges):
    ask_exchange, bid_exchange = patched_exchanges.exchanges

    # 50000.0 > 10.0 * 4500.0, so bounds on exchange with bid side
    ask_exchange.balances = {
        'USD': 50000.0,
        'BTC': 7.0,
    }
    bid_exchange.balances = {
        'USD': 30000.0,
        'BTC': 10.0,
    }

    ask_offer = Offer(  # type: ignore
        **{
            **ask_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=ask_exchange
    )
    bid_offer = Offer(  # type: ignore
        **{
            **bid_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=bid_exchange
    )

    max_base, max_quote = get_max_spend(ask_offer, bid_offer)
    assert round(max_base.amount, 2) == round(ask_offer.price * bid_exchange.balances['BTC'], 2)
    assert round(max_quote.amount, 2) == bid_exchange.balances['BTC']


def test_get_max_spend_bid_enough(ask_offer_data, bid_offer_data, patched_exchanges):
    ask_exchange, bid_exchange = patched_exchanges.exchanges

    # 40000.0 < 10.0 * 4500.0, so bounds on exchange with ask side
    ask_exchange.balances = {
        'USD': 40000.0,
        'BTC': 7.0,
    }
    bid_exchange.balances = {
        'USD': 30000.0,
        'BTC': 10.0,
    }

    ask_offer = Offer(  # type: ignore
        **{
            **ask_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=ask_exchange
    )
    bid_offer = Offer(  # type: ignore
        **{
            **bid_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=bid_exchange
    )

    max_base, max_quote = get_max_spend(ask_offer, bid_offer)
    assert round(max_base.amount, 2) == ask_exchange.balances['USD']
    assert round(max_quote.amount, 2) == round(ask_exchange.balances['USD'] / ask_offer.price, 2)


def test_get_max_spend_with_fee(ask_offer_data, bid_offer_data, patched_exchanges):
    """
    get_max_spend should process take into account exchange's fee.

    :return:
    """
    ask_exchange, bid_exchange = patched_exchanges.exchanges
    ask_exchange.balances = {
        'USD': 40000.0,
        'BTC': 7.0,
    }
    ask_exchange.fee = 0.01

    bid_exchange.balances = {
        'USD': 30000.0,
        'BTC': 10.0,
    }
    bid_exchange.fee = 0.01

    ask_offer = Offer(  # type: ignore
        **{
            **ask_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=ask_exchange
    )
    bid_offer = Offer(  # type: ignore
        **{
            **bid_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=bid_exchange
    )

    max_base, max_quote = get_max_spend(ask_offer, bid_offer)
    assert round(max_base.amount, 2) == ask_exchange.balances['USD'] * 0.98
    assert round(max_quote.amount, 2) == round(
        ask_exchange.balances['USD'] / ask_offer.price * 0.98, 2)


def test_get_max_spend_with_zero_balance(ask_offer_data, bid_offer_data, patched_exchanges):
    ask_exchange, bid_exchange = patched_exchanges.exchanges
    ask_exchange.balances = {
        'USD': 40000.0,
        'BTC': 7.0,
    }
    ask_exchange.fee = 0.0

    bid_exchange.balances = {
        'USD': 0.0,
        'BTC': 0.0,
    }
    bid_exchange.fee = 0.0

    ask_offer = Offer(**{**ask_offer_data, 'price': 4500.0}, exchange=ask_exchange)  # type: ignore
    bid_offer = Offer(**bid_offer_data, exchange=bid_exchange)  # type: ignore

    max_base, max_quote = get_max_spend(ask_offer, bid_offer)
    assert max_base.amount == 0.0
    assert max_quote.amount == 0.0


def test_get_max_spend_with_max_spend_part(ask_offer_data, bid_offer_data, patched_exchanges):
    ask_exchange, bid_exchange = patched_exchanges.exchanges

    ask_exchange.balances = {
        'USD': 40000.0,
        'BTC': 7.0,
    }

    bid_exchange.balances = {
        'USD': 30000.0,
        'BTC': 10.0,
    }

    ask_offer = Offer(  # type: ignore
        **{
            **ask_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=ask_exchange
    )
    bid_offer = Offer(  # type: ignore
        **{
            **bid_offer_data,
            'price': 4500.0,
            'quote': 150.0,
        },
        exchange=bid_exchange
    )

    max_base, max_quote = get_max_spend(
        ask_offer, bid_offer, max_spend_part=0.5
    )

    assert round(max_base.amount, 2) == ask_exchange.balances['USD'] * 0.5
    assert round(max_quote.amount, 2) == round(
        ask_exchange.balances['USD'] / ask_offer.price * 0.5, 2)


@pytest.mark.asyncio
async def test_arbitrage_handle_certain_pairs(patched_arbitrage):
    patched_exchanges = patched_arbitrage.exchanges
    exchange_left, exchange_right = patched_exchanges.exchanges
    patched_exchanges.pairs = {
        # we have window
        'ETCUSD': {
            exchange_left: {
                'ask': 290.0,
                'bid': 280.0,
                'ask_size': const.MAX_SUM,
                'bid_size': const.MAX_SUM,
                'time': time.time(),
            },
            exchange_right: {
                'ask': 330.0,
                'bid': 312.0,
                'ask_size': const.MAX_SUM,
                'bid_size': const.MAX_SUM,
                'time': time.time(),
            },
        },
        'BTCUSD': {
            exchange_left: {
                'ask': 290.0,
                'bid': 280.0,
                'ask_size': const.MAX_SUM,
                'bid_size': const.MAX_SUM,
                'time': time.time(),
            },
            exchange_right: {
                'ask': 330.0,
                'bid': 312.0,
                'ask_size': const.MAX_SUM,
                'bid_size': const.MAX_SUM,
                'time': time.time(),
            },
        },
    }
    exchange_left.balances = {
        'USD': 4.69258078,
        'ETC': 2.34,
        'BTC': 6.0,
    }
    exchange_right.balances = {
        'USD': 10000.0,
        'ETC': 10.0,
        'BTC': 6.0,
    }

    # handle only ETCUSD
    test_pair = 'ETCUSD'
    patched_arbitrage.pairs = {test_pair}

    await patched_arbitrage.schedule()
    orders: typing.List[Order] = []
    assert not patched_arbitrage.to_reverse.empty()
    while not patched_arbitrage.to_reverse.empty():
        orders.extend(await patched_arbitrage.to_reverse.pop())

    for order in orders:
        assert order.pair == test_pair


def test_arbitrage_not_handle_pairs(db, patched_exchanges):
    """Arbitrage does not handle pairs that do not defined in Exchanges."""
    with pytest.raises(ValueError):
        Arbitrage(  # type: ignore
            exchanges=patched_exchanges,
            to_reverse=mock.MockQueue(),
            pairs={'EURUSD'},
            db=db,
        )


def test_window_exists(ask_offer_data, bid_offer_data, patched_exchanges):
    exchange_left, exchange_right = patched_exchanges.exchanges

    window = ArbitrageWindow(
        Offer(**ask_offer_data, exchange=exchange_left),  # type: ignore
        Offer(**bid_offer_data, exchange=exchange_right),  # type: ignore
    )

    assert window.exists


def test_window_state(ask_offer_data, bid_offer_data, patched_exchanges):
    """Window may be opened or closed."""
    exchange_left, exchange_right = patched_exchanges.exchanges

    ask = Offer(**ask_offer_data, exchange=exchange_left)  # type: ignore

    closed_window = ArbitrageWindow(
        ask, Offer(**bid_offer_data, exchange=exchange_right),  # type: ignore
    )

    opened_window = ArbitrageWindow(
        ask,
        Offer(**{
            **bid_offer_data,
            'price': 5001.0,
            'exchange': exchange_right,
        }),
    )

    assert opened_window.is_opened
    assert not closed_window.is_opened
    assert closed_window.is_closed
    assert not opened_window.is_closed


def test_window_state_with_width(ask_offer_data, bid_offer_data, patched_exchanges):
    """Window state depends on `(direct|reversed)_width` value."""
    exchange_left, exchange_right = patched_exchanges.exchanges

    window = ArbitrageWindow(
        Offer(  # type: ignore
            **{**ask_offer_data, **{'price': 100.0, 'price_type': const.ASK}},
            exchange=exchange_left
        ),
        Offer(  # type: ignore
            **{**bid_offer_data, **{'price': 105.0, 'price_type': const.BID}},
            exchange=exchange_right
        ),
    )

    window.direct_width = 1.0
    window.reversed_width = 1.06
    assert window.is_opened
    assert window.is_closed

    window.direct_width = 1.6
    window.reversed_width = 1.0
    assert not window.is_opened
    assert not window.is_closed


def test_incorrect_windows(ask_offer_data, bid_offer_data, patched_exchanges):
    """Window has several cases when it will be incorrect."""
    exchange_left, exchange_right = patched_exchanges.exchanges

    with pytest.raises(AssertionError):
        # case with incorrect price side
        ArbitrageWindow(
            Offer(**ask_offer_data, exchange=exchange_left),  # type: ignore
            Offer(**{**bid_offer_data, 'price_type': const.ASK, 'exchange': exchange_right}),
        )

    with pytest.raises(AssertionError):
        # case with incorrect pair
        ArbitrageWindow(
            Offer(**ask_offer_data, exchange=exchange_left),  # type: ignore
            Offer(**{**bid_offer_data, 'pair': 'EURUSD', 'exchange': exchange_right}),
        )


@pytest.mark.parametrize('delta,expected', [(0.25, True), (0.6, False)])
def test_get_pair_offer_map_stale_filter(patched_arbitrage, delta, expected):
    current_time = time.time() - delta
    exchange_left, exchange_right = patched_arbitrage.exchanges.exchanges
    pair_data = {
        'ask': 295.0,
        'bid': 290.0,
        'ask_size': 10**8,
        'bid_size': 10**4,
        'time': current_time,
    }

    patched_arbitrage.interval = 0.5  # freshness period of pairs
    patched_arbitrage.exchanges.pairs = {
        'BTCUSD': {
            exchange_left: pair_data,
            exchange_right: pair_data,
        },
        'ETCUSD': {
            exchange_left: pair_data,
            exchange_right: pair_data,
        },
    }

    result = patched_arbitrage.get_pair_offer_map()
    for pair in patched_arbitrage.exchanges.pairs:
        assert bool(result[pair]) == expected


@pytest.mark.parametrize(
    'arbitrage_with_offers,delay,expected',
    [
        (
            {'left': {'ask': 305.0, 'bid': 302.0}, 'right': {'ask': 310.0, 'bid': 308.0}},
            0.5, [{'ETC': 1.0, 'USD': 312.0}, {'ETC': 1.0, 'USD': 302.0}]
        ),
        (
            {'left': {'ask': 305.0, 'bid': 302.0}, 'right': {'ask': 310.0, 'bid': 308.0}},
            0.4, [{'ETC': 2.0, 'USD': 10.0}, {'ETC': 0.0, 'USD': 612.0}]
        )
    ],
    indirect=['arbitrage_with_offers']
)
@pytest.mark.asyncio
async def test_autoreverse(delay, expected, arbitrage_with_offers):
    # 1. Get arbitrage object with filled `to_reverse` field
    # Both exchange objects contain hardcoded balances.
    # They were filled special for this test.
    exchanges = arbitrage_with_offers.exchanges
    exchange_left, exchange_right = exchanges.exchanges
    # 2. Set arbitrage.pairs = ETCUSD (305/308) was set with parametrize.
    # Window is still opened and orders will be autoreversed by (310/302).

    # 3. Set arbitrage.autoreverse_order_delta = 1 second
    arbitrage_with_offers.autoreverse_order_delta = timedelta(seconds=0.5)
    # 4. Renew the executed_at of pair, because Arbitrage.enter has
    # some delay after pair was placed.
    for _ in range(await arbitrage_with_offers.to_reverse.length()):
        buy_order, sell_order = await arbitrage_with_offers.to_reverse.pop()
        buy_order.executed_at = sell_order.executed_at = datetime.utcnow()
        await arbitrage_with_offers.to_reverse.push([buy_order, sell_order])

    # 5. Wait and try to autoreverse them
    await asyncio.sleep(delay)
    await arbitrage_with_offers.exit()

    left_expected_balance, right_expected_balance = expected
    for currency in ['ETC', 'USD']:
        assert exchange_left.balances[currency] == left_expected_balance[currency]
        assert exchange_right.balances[currency] == right_expected_balance[currency]


@pytest.mark.parametrize('order_delta,expected', [(0.5, True), (0.25, False)])
def test_orders_expiration(
    order_delta,
    expected,
    ask_offer_data,
    bid_offer_data,
    patched_arbitrage,
):
    patched_arbitrage.autoreverse_order_delta = timedelta(seconds=0.5)
    orders_executed_time = datetime.utcnow() - timedelta(seconds=order_delta)
    orders = [
        Order(
            Offer(**ask_offer_data, exchange=None),  # type: ignore
            executed_at=orders_executed_time
        ),
        Order(
            Offer(**bid_offer_data, exchange=None),  # type: ignore
            executed_at=orders_executed_time
        ),
    ]

    assert patched_arbitrage.are_orders_expired(orders) == expected


@pytest.mark.asyncio
async def test_reverse_half_processed_window(ask_offer_data, bid_offer_data, patched_arbitrage):
    """
    See bug case below.

    - Bot processes arbitrage window with left and right exchange
    - Left exchange fulfill direct order
    - Right exchange - not fulfill direct order.
    - Left exchange should fulfill direct order.
    - Exchanges should have the same balances before start window processing.
    """
    # exchange_left will place with success, but exchange_right - not
    exchange_left, exchange_right = patched_arbitrage.exchanges.exchanges

    async def place_dummy(order):
        return typing.PlacedOrder(
            success=False,
            order_id='',
            order_status=const.CREATED,
            response='error'
        )
    exchange_right.session.place = place_dummy

    ask_offer = Offer(**ask_offer_data, exchange=exchange_left)  # type: ignore
    bid_offer = Offer(**{
        **bid_offer_data,
        'exchange': exchange_right,
        'price': 10000.0,
    })

    window = ArbitrageWindow(ask_offer, bid_offer)
    left_balances_on_start = {
        'USD': 50000.0,
        'BTC': 8.0,
        'ETC': 0.0,
    }
    right_balances_on_start = {
        'USD': 10000.0,
        'BTC': 4.0,
        'ETC': 0.0,
    }
    exchange_left.session.balances = left_balances_on_start
    exchange_right.session.balances = right_balances_on_start

    schedulable = utils.ScheduleManager([
        patched_arbitrage.exchanges,
    ])

    patched_arbitrage.reverse_order = Mock(wraps=patched_arbitrage.reverse_order)
    async with schedulable:
        await patched_arbitrage.process_window(window)
        patched_arbitrage.reverse_order.assert_called()
        # left exchange fulfilled direct order then fulfilled reversed reversed one.
        # So, it's balances did not change.
        assert exchange_left.balances == left_balances_on_start
        # right exchange failed to fulfill direct order.
        # So, it's balances did not change.
        assert exchange_right.balances == right_balances_on_start
