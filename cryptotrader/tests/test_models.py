from datetime import datetime

import pytest

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.exchange import Exchange
from cryptotrader.models import Offer
from cryptotrader.models import OfferFrozenFields
from cryptotrader.models import Order
from cryptotrader.models import OrderSerializer
from cryptotrader.tests import utils
from cryptotrader.tests.mock import MockSession


def test_set_immutable_offer_attributes(order):
    offer = order.offer
    for field in OfferFrozenFields._fields:
        with pytest.raises(AttributeError):
            setattr(offer, field, 0)


def test_offer_is_similar_with_kwargs(ask_offer_data, bid_offer_data, exchange_data):
    offer_left = Offer(  # type: ignore
        **ask_offer_data,
        exchange=Exchange(
            MockSession(balances={'USD': 10000.0, 'BTC': 4.0, 'ETC': 0.0}),
            'bittrex',
            **exchange_data,
        ),
    )
    offer_right = Offer(  # type: ignore
        **bid_offer_data,
        exchange=Exchange(
            MockSession(balances={'USD': 10000.0, 'BTC': 4.0, 'ETC': 0.0}),
            'bittrex',
            **exchange_data,
        ),
    )
    assert not offer_left.is_similar(offer_right)
    assert offer_left.is_similar(offer_right, price_type=const.ASK)


def test_offer_is_similar_custom_fields(ask_offer_data, bid_offer_data, exchange_data):
    offer_left = Offer(  # type: ignore
        **{**ask_offer_data, 'quote': 4.0},
        exchange=Exchange(
            MockSession(balances={'USD': 10000.0, 'BTC': 4.0, 'ETC': 0.0}),
            'bittrex',
            **exchange_data,
        ),
    )
    offer_right = Offer(  # type: ignore
        **bid_offer_data,
        exchange=Exchange(
            MockSession(balances={'USD': 10000.0, 'BTC': 4.0, 'ETC': 0.0}),
            'bittrex',
            **exchange_data,
        ),
    )
    assert offer_left.is_similar(
        offer_right,
        fields_to_compare=['pair', 'price']
    )
    assert not offer_left.is_similar(
        offer_right,
        fields_to_compare=['pair', 'quote']
    )


@pytest.mark.asyncio
async def test_offer_refreshed_success(ask_offer_data, exchange_data):
    stale_price, fresh_price = 100, 110
    # 1. create offer
    session = MockSession()
    offer = Offer(  # type: ignore
        **{**ask_offer_data, 'price': stale_price},
        exchange=Exchange(session, name='left', **exchange_data),
    )

    # 2. exchange will return new price
    async def fetch_fresh_pair(pair, limit=0.0):
        return typing.SessionFetchedPair(
            success=True,
            pair={'ask': fresh_price},
            response='ok',
        )

    session.fetch_pair = fetch_fresh_pair  # type: ignore

    # 3. fresh offer should receive fresh price
    fresh_offer = await offer.refreshed()
    assert fresh_offer.price == fresh_price


@pytest.mark.asyncio
async def test_offer_refreshed_fail(ask_offer_data, exchange_data):
    # 1. create offer
    session = MockSession()
    offer = Offer(  # type: ignore
        **{**ask_offer_data},
        exchange=Exchange(session, name='left', **exchange_data),
    )

    # 2. exchange will return new price
    async def fetch_fresh_pair(pair, limit=0.0):
        return typing.SessionFetchedPair(
            success=False,
            pair={},
            response='error',
        )

    session.fetch_pair = fetch_fresh_pair  # type: ignore

    # 3. fresh offer should receive fresh price
    with pytest.raises(exception.FetchPairError):
        await offer.refreshed()


@pytest.mark.asyncio
async def test_db_save_and_delete(db, order):
    """Db engine should be able to save and delete models."""
    order = order
    await order.save(db)
    assert order.uuid
    await order.save(db)
    await order.delete(db)
    assert not order.uuid


@pytest.mark.asyncio
async def test_db_order_fetch(db, order):
    """Db engine should be able to save and delete models."""
    order = order
    await order.save(db)

    table = db.tables['orders']
    async with db.acquire() as conn:
        result = await conn.execute(
            table.select().where(
                table.c.uuid == order.uuid
            )
        )
    data = await result.first()
    fetched_order = Order.from_data(data, order.exchange)

    # both datetime objects should be timezone-naive.
    # So, they should be comparable.
    assert fetched_order.executed_at < datetime.now()


def test_order_serializer(order):
    order_list = [order]
    serializer = OrderSerializer(exchanges={  # type: ignore
        order.exchange.name: order.exchange
    })

    raw_orders = serializer.dumps(order_list)
    assert isinstance(raw_orders, bytes)

    loaded_orders = serializer.loads(raw_orders)
    assert isinstance(loaded_orders, list)

    def test_fields(fixture, test, fields):
        for field in fields:
            assert getattr(fixture, field) == getattr(test, field)

    def test_money_fields(fixture, test):
        money_fields = fixture.base.__dict__
        test_fields(fixture.base, test.base, money_fields)
        test_fields(fixture.quote, test.quote, money_fields)

    for fixture_order, test_order in zip(order_list, loaded_orders):
        test_fields(
            fixture_order,
            test_order,
            ['uuid', 'executed_at', 'created_at', 'expired_at', 'status'],
        )

        test_fields(
            fixture_order.offer,
            test_order.offer,
            ['exchange_name', 'pair', 'price_type']
        )

        test_money_fields(fixture_order, test_order)
        test_money_fields(fixture_order.offer, test_order.offer)


@pytest.mark.parametrize(
    'session_data,expected',
    [
        ({'status_to_place': const.PLACED}, True),
        ({'status_to_place': const.FULFILLED}, True),
        ({'status_to_place': const.CANCELLED}, False),
        ({'status_to_place': const.CREATED}, False),
        ({'status_to_place': const.REJECTED}, False),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_place_order_result(order, expected):
    async with utils.ScheduleManager([order.exchange]):
        success, response = await order.place()
        assert success == expected, response


@pytest.mark.parametrize(
    'session_data,expected',
    [
        ({'status_to_place': const.PLACED}, const.PLACED),
        ({'status_to_place': const.FULFILLED}, const.FULFILLED),
        # other states will be default
        ({'status_to_place': const.CANCELLED}, const.CANCELLED),
        ({'status_to_place': const.CREATED}, const.CREATED),
        ({'status_to_place': const.REJECTED}, const.REJECTED),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_place_order_change_status(order, expected):
    async with utils.ScheduleManager([order.exchange]):
        await order.place()
        assert order.status == expected


@pytest.mark.parametrize('session_data', [{'order_id': 'uuid'}], indirect=['session_data'])
@pytest.mark.asyncio
async def test_place_order_set_exchange_id(order):
    async with utils.ScheduleManager([order.exchange]):
        await order.place()
        assert order.id_on_exchange == 'uuid'


@pytest.mark.parametrize(
    'session_data,expected',
    [
        ({'status': const.PLACED}, [const.PLACED]),
        ({'status': const.CANCELLED}, [const.CANCELLED]),
        ({'status': const.FULFILLED}, [const.PLACED, const.CANCELLED, const.FULFILLED]),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_subscribe_success(order, expected):
    """Perform successfully if an order status is matched in an exchange."""
    success, _ = await order.wait_status(
        expected, timeout=0.1, fetch_order_interval=0.0,
    )
    assert success


@pytest.mark.parametrize(
    'session_data,expected',
    [
        ({'status': const.PLACED}, [const.PLACED]),
        ({'status': const.CANCELLED}, [const.CANCELLED]),
        ({'status': const.FULFILLED}, [const.PLACED, const.CANCELLED, const.FULFILLED]),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_subscribe_sync_state(order, expected):
    """Sync an order's state with an exchange."""
    success, _ = await order.wait_status(
        expected, timeout=0.1, fetch_order_interval=0.0,
    )
    assert order.status in expected


@pytest.mark.asyncio
async def test_subscribe_timeout(order):
    """Fail and cancel an order if timeout is reached."""
    success, _ = await order.wait_status(
        [const.CANCELLED], timeout=0.1, fetch_order_interval=0.05,
    )
    assert not success


@pytest.mark.parametrize('order_data', [{'id_on_exchange': ''}], indirect=['order_data'])
@pytest.mark.asyncio
async def test_subscribe_error(order):
    """Raise a ValueError if an order has no id_on_exchange."""
    with pytest.raises(ValueError):
        await order.wait_status(
            [const.FULFILLED], timeout=0.1, fetch_order_interval=0.0,
        )


@pytest.mark.parametrize('offer,pair_limits,balances,max_spend_part,expected', [
    # expect True with no pair limits
    ({'price_type': const.ASK}, {}, {'USD': 26000.0}, 1.0, True),
    ({'price_type': const.ASK}, {}, {'USD': 24000.0}, 1.0, True),
    ({'price_type': const.BID}, {}, {'BTC': 6.0}, 1.0, True),
    ({'price_type': const.BID}, {}, {'BTC': 4.0}, 1.0, True),
    # expect False with balances less then pair limits
    ({'price_type': const.ASK}, {'BTCUSD': 5.5}, {'USD': 25500.0}, 1.0, False),
    ({'price_type': const.BID}, {'BTCUSD': 5.5}, {'BTC': 6.0}, 1.0, False),
    # expect True with balances enough for pair limits
    ({'price_type': const.ASK}, {'BTCUSD': 5.0}, {'USD': 26000.0}, 1.0, True),
    # expect False with max_spend_part do balances less then pair limits
    ({'price_type': const.ASK}, {'BTCUSD': 5.0}, {'USD': 30000.0}, 0.8, False),
    ({'price_type': const.ASK}, {'BTCUSD': 4.5}, {'BTC': 5.0}, 0.8, False),
])
@pytest.mark.asyncio
async def test_offer_in_pair_limit(
    ask_offer_data, exchange_data,
    offer, pair_limits, balances, max_spend_part, expected
):
    pair_limits_kwargs = (
        {'pair_limits': pair_limits} if pair_limits else {}
    )
    exchange = Exchange(
        MockSession(balances=balances),
        'left_exchange',
        **{**exchange_data, **pair_limits_kwargs},
    )
    await exchange.fetch_balances()
    offer = Offer(  # type: ignore
        **{**ask_offer_data, **offer},
        exchange=exchange
    )
    assert offer.in_pair_limit(max_spend_part) == expected


@pytest.mark.parametrize(
    'expected_result,expected_order_status,session_data',
    [
        # trade is successed, because a placed order will be fulfilled
        (True, const.FULFILLED, {'status': const.FULFILLED, 'status_to_place': const.PLACED}),
        # trade is successed, because placing of an order is fulfilled
        (True, const.FULFILLED, {'status': const.FULFILLED, 'status_to_place': const.FULFILLED}),
        # trade is failed, because placing of an order is rejected
        (False, const.REJECTED, {'status_to_place': const.REJECTED}),
        # trade is failed, because waiting status of an order reachs timeout
        (False, const.CANCELLED, {'status': const.PLACED, 'status_to_place': const.PLACED}),
        # trade is failed, because an order is cancelled
        (False, const.CANCELLED, {'status': const.CANCELLED, 'status_to_place': const.PLACED}),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_order_trade(order, expected_result, expected_order_status):
    # fill the balance of exchange
    await order.exchange.fetch_balances()

    success, _ = await order.trade(
        timeout=0.5,
        fetch_order_interval=0.1,
        sleep_after_placed=0.0,
    )

    assert success == expected_result
    assert order.status == expected_order_status


@pytest.mark.parametrize(
    'expected,session_data',
    [
        # order cancelled
        (True, {'is_success': True}),
        # order not cancelled
        (False, {'is_success': False}),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_order_cancel(order, expected):
    success, response = await order.cancel()

    assert success == expected
    assert isinstance(response, str)
    assert (order.status == const.CANCELLED) == expected


@pytest.mark.parametrize(
    'expected,session_data',
    [
        # status of an order updated
        (True, {'is_success': True, 'status': const.FULFILLED}),
        # status of an order not updated, because invalid status
        (False, {'is_success': True, 'status': ''}),
        # status of an order not updated
        (False, {'is_success': False}),
    ],
    indirect=['session_data']
)
@pytest.mark.asyncio
async def test_order_update_status(order, expected):
    success, response = await order.update_status()

    assert success == expected
    assert isinstance(response, str)
    assert (order.status == order.exchange.session.status) == expected
