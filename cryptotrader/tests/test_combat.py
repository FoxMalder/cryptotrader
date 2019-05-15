import asyncio
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from cryptotrader import const
from cryptotrader.models import Offer
from cryptotrader.models import Order

# @todo #430:60m Fetch combat tested exchanges list only from parameters.
#  Remove hardcoded exchanges list from fixture parametrization.
#  To test new exchange, we should just add new exchange config to `combat.yaml`.
combat_test_parametrization = pytest.mark.parametrize(
    'combat_config', ['bitfinex', 'bittrex', 'hitbtc'], indirect=['combat_config'],
)

# @todo #176 Create a paid test to verify the correctness of an order processing logic.
#  It should has such scenario:
#  - place an order with real price
#  - wait until the order will be closed
#  - place a reversed order with real price
#  - wait until the order will be closed


async def wait_until(predicate, callback, timeout=50):
    async def worker():
        while not predicate():
            result = await callback()
            await asyncio.sleep(timeout / 10)
            print(f'Do until result {result}')
    try:
        await asyncio.wait_for(worker(), timeout=timeout)
    except asyncio.TimeoutError:
        print(f'Execution timed out. Callback: {callback}.')
        return False
    return True


@pytest.fixture
def combat_test_exchange(combat_app):
    assert len(combat_app.exchanges.exchanges) == 1
    return combat_app.exchanges.exchanges[0]


@pytest.fixture
def combat_test_order(combat_test_exchange):
    return Order(
        offer=Offer(
            price_type=const.ASK,
            pair='ETCUSD',
            price=18.0,
            quote=1.0,
            exchange=combat_test_exchange,
            timestamp=time.time(),
        ),
        type_=const.LIMIT,
    )


@combat_test_parametrization
@pytest.mark.combat_test
@pytest.mark.asyncio
async def test_exchange_update_ticker(combat_test_exchange):
    fetched_pair = await asyncio.wait_for(
        combat_test_exchange.session.fetch_pair(pair='ETCUSD'),
        timeout=10,
    )
    pair_data = fetched_pair.pair

    for key in ['ask', 'bid', 'ask_size', 'bid_size']:
        assert pair_data[key] and isinstance(pair_data[key], float)
        assert pair_data[key] > 0.0


@combat_test_parametrization
@pytest.mark.combat_test
@pytest.mark.asyncio
async def test_exchange_fetch_balances(combat_test_exchange):
    await asyncio.wait_for(
        combat_test_exchange.fetch_balances(),
        timeout=10,
    )
    currency = 'USD'
    balance = combat_test_exchange.get_balance(currency)
    assert balance > 0.0


@combat_test_parametrization
@pytest.mark.paid_test
@pytest.mark.asyncio
async def test_exchange_place_and_cancel(combat_test_order):
    """Place an order with impossible price and cancel it."""
    # took this mocker from opened PR#501: https://goo.gl/7b76Kj
    # We'll reuse it from some common place after this PR merge.
    def async_mocker(*args, **kwargs):
        async def mock_coro(*args, **kwargs):
            return m(*args, **kwargs)

        m = MagicMock(*args, **kwargs)
        mock_coro.mock = m  # type: ignore
        return mock_coro

    with patch(
        f'cryptotrader.exchange.Exchange.validate',
        new=async_mocker(return_value=True),
    ):
        # 1. place order
        place_success = await wait_until(
            lambda: combat_test_order.is_placed,
            callback=combat_test_order.place,
        )
        assert place_success, str(combat_test_order)

        # 2. some exchanges require delay between place and cancel
        await asyncio.sleep(1.0)

        # 3. cancel order
        cancel_success = await wait_until(
            lambda: combat_test_order.is_closed,
            callback=combat_test_order.cancel,
        )
        assert cancel_success, combat_test_order


@combat_test_parametrization
@pytest.mark.paid_test
@pytest.mark.asyncio
async def test_exchange_fetch_order_status(combat_test_order):
    # place the order
    place_success = await wait_until(
        lambda: combat_test_order.is_placed,
        callback=combat_test_order.place,
    )
    assert place_success, combat_test_order

    # try to update order status
    try:
        success, response = await asyncio.wait_for(
            combat_test_order.update_status(),
            timeout=10,
        )
    except asyncio.TimeoutError:
        success, response = False, 'Timeout is reached'

    # cancel the order
    cancel_success = await wait_until(
        lambda: combat_test_order.is_closed,
        callback=combat_test_order.cancel,
    )
    assert cancel_success, combat_test_order
    assert success, f'Order: {combat_test_order}. \nResponse: {response}'


@combat_test_parametrization
@pytest.mark.combat_test
@pytest.mark.paid_test
@pytest.mark.asyncio
async def test_order_trade(combat_app):
    await combat_app.exchanges.update_tickers()

    offers = combat_app.exchanges.get_pair_offer_map(['LTCUSD'])['LTCUSD']
    assert len(offers) == 2, offers
    ask_offer, bid_offer = offers
    assert ask_offer.price_type == const.ASK, ask_offer
    assert bid_offer.price_type == const.BID, ask_offer

    for offer in offers:
        order = Order(offer)
        success, response = await order.trade(timeout=30.0)
        assert success, response
        assert order.status == const.FULFILLED, str(order)
