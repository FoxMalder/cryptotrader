import asyncio
from collections import defaultdict

import pytest
import yaml

from cryptotrader.tests import utils
from cryptotrader.tests.conftest import get_app


@pytest.mark.asyncio
async def test_place_success(order):
    """Mock exchange should correctly place valid order."""
    exchange = order.exchange
    async with utils.ScheduleManager([exchange]):
        await exchange.place(order)
        assert exchange.balances['BTC'] == 13.0
        assert exchange.balances['USD'] == 25000.0


@pytest.mark.asyncio
async def test_place_fail(order):
    """Mock exchange should raise exception on placing not valid order."""
    order.exchange.session.balances = {
        'USD': 24999.0,
        'BTC': 8.0,
    }

    exchange = order.exchange

    async with utils.ScheduleManager([exchange]):
        placed_order = await exchange.place(order)
        assert not placed_order.success
        assert exchange.balances['BTC'] == 8.0
        assert exchange.balances['USD'] == 24999.0
        # wait one second to cancel exchange future in correct way
        await asyncio.sleep(1.0)


@pytest.mark.asyncio
async def test_balances_difference(order):
    """Exchange should report about changed balances."""
    # to set initial state
    exchange = order.exchange
    async with utils.ScheduleManager([exchange]):
        exchange.calculate_balances_difference()
        await exchange.place(order)

    difference = exchange.calculate_balances_difference()
    assert 'USD' in difference
    assert 'BTC' in difference
    assert 'ETC' not in difference
    assert difference['USD'] == (50000, 25000)
    assert difference['BTC'] == (8.0, 13.0)


@pytest.mark.parametrize('input,expected', [
    (['BTCUSD', 'LTCUSD'], ['BTCUSD', 'LTCUSD']),
    ([], ['BTCUSD', 'LTCUSD']),
    (['BTCUSD'], ['BTCUSD']),
    (['BTCUSD', 'BADPAIR'], ['BTCUSD']),
    (['BADPAIR'], []),
])
def test_get_pair_offer_map(event_loop, input, expected):
    app = get_app(event_loop)

    async def run():
        async with app.context():
            pair_offers_map = app.exchanges.get_pair_offer_map(  # type: ignore
                pair_names=input
            )
            assert set(pair_offers_map) == set(expected)

    event_loop.run_until_complete(run())


@pytest.mark.asyncio
async def test_fetch_success(order):
    exchange = order.exchange

    result = await exchange.fetch_status(order)
    assert result.success
    assert isinstance(result.response, str)


@pytest.mark.asyncio
async def test_fetch_status_error(order):
    """Raise a ValueError if an Order has not id_on_exchange."""
    exchange = order.exchange
    order.id_on_exchange = None

    with pytest.raises(ValueError):
        await exchange.fetch_status(order)


@pytest.mark.asyncio
async def test_fetch_failed_status(order):
    """Return False, str(repsonse) on a session error."""
    exchange = order.exchange
    exchange.session.is_success = False

    result = await exchange.fetch_status(order)
    assert not result.success
    assert isinstance(result.response, str)


@pytest.mark.skip(reason='wait for test bitfinex keys')
def test_bitfinex_has_pairs_on_start(event_loop):
    # start app with full functionality.
    # And with real bitfinex exchange.
    # After app.exchanges.schedule() finishing
    # exchanges.pairs should contain all bitfinex's from config.

    # 1. construct bitfinex's real config for app
    bitfinex_config_str = """
bitfinex:
  fee: 0.01
  limit: 0
  interval: 1.0
  fetch_balances_interval: 0.5
  transport:
    websocket_base_url: 'wss://api.bitfinex.com/ws/2'
    http_base_url: https://api.bitfinex.com/v1
    key: dummy-key
    secret: dummy-key
"""
    bitfinex_config = yaml.load(bitfinex_config_str)

    # 2. start app with this real config
    app = get_app(
        event_loop,
        config={'exchanges': bitfinex_config}
    )
    event_loop.run_until_complete(app.exchanges.schedule())  # type: ignore
    pair_offer_map = app.exchanges.get_pair_offer_map()  # type: ignore
    event_loop.run_until_complete(app.exchanges.stop())  # type: ignore
    event_loop.run_until_complete(app.stop())

    # 3. exchanges.pair_offers_map should contain all pairs from config.
    for pair in ['BTCUSD', 'LTCUSD']:
        assert pair in pair_offer_map
        assert (
            o.pair == pair and o.exchange.name == 'bitfinex'
            for o in pair_offer_map['BTCUSD']
        )


@pytest.mark.parametrize('pair_limits,pairs,expected', [
    (  # main case
        {'BTCUSD': 0.5, 'ETHUSD': 1.0},  # limits
        {'BTCUSD': {'ask': 8000.0}},  # pairs
        {'BTC': 0.5, 'USD': 4000.0, 'ETH': 1.0},  # currency_limits
    ),
    (  # calc only with ask price
        {'BTCUSD': 0.5},  # limits
        {'BTCUSD': {'ask': 0.0, 'bid': 8000}},  # pairs
        {'BTC': 0.5, 'USD': 0.0},  # currency_limits
    ),
    (  # zero limits
        {'BTCUSD': 0.0},  # limits
        {'BTCUSD': {'ask': 8000.0}},  # pairs
        {'BTC': 0.0, 'USD': 0.0},  # currency_limits
    ),
    (  # zero prices
        {'BTCUSD': 0.5},  # limits
        {'BTCUSD': {'ask': 0.0}},  # pairs
        {'BTC': 0.5, 'USD': 0.0},  # currency_limits
    ),
    (  # quote repeats
        {'BTCUSD': 0.5, 'BTCETH': 1.0},  # limits
        {'BTCUSD': {'ask': 8000.0}, 'BTCETH': {'ask': 200.0}},  # pairs
        {'BTC': 1.0, 'USD': 4000.0, 'ETH': 200.0},  # currency_limits
    ),
    (  # base repeats
        {'BTCUSD': 0.001, 'ETHUSD': 1.0},  # limits
        {'BTCUSD': {'ask': 8000.0}, 'ETHUSD': {'ask': 40.0}},  # pairs
        {'BTC': 0.001, 'USD': 40.0, 'ETH': 1.0},  # currency_limits
    ),
    (  # base after quote
        {'BTCUSD': 0.5, 'ETHBTC': 1000.0},  # limits
        {'BTCUSD': {'ask': 8000.0}, 'ETHBTC': {'ask': 0.005}},  # pairs
        {'BTC': 5.0, 'USD': 4000.0, 'ETH': 1000.0},  # currency_limits
    ),
])
def test_currency_limits(event_loop, pair_limits, pairs, expected):
    """`currency_limits` should be generated from `pair_limits` in correct way."""
    app = get_app(
        event_loop,
        config={
            'exchanges': {
                'left': {'pair_limits': pair_limits, 'transport': {}}
            }
        }
    )

    async def run():
        async with app.context():
            exchange = app.exchanges.get('left')  # type: ignore
            exchange.pairs = defaultdict(
                lambda: defaultdict(float), pairs
            )
            assert exchange.get_currency_limits() == expected

    event_loop.run_until_complete(run())


def test_default_config(event_loop):
    """Exchange should correctly inherit default config."""
    custom_fee = 1.0
    app = get_app(
        event_loop,
        config={'exchanges': {'left': {'fee': custom_fee, 'transport': {}}}}
    )

    async def run():
        async with app.context():
            exchange = app.exchanges.get('left')  # type: ignore
            assert exchange.fee == custom_fee
    event_loop.run_until_complete(run())


def test_default_limit(event_loop):
    """Exchange inherit default limit of pair."""
    exchange = get_app(event_loop).exchanges.get('left')  # type: ignore
    assert exchange.get_pair_limit('does not exist') == 1.0
