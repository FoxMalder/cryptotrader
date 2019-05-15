import typing

import pytest

from cryptotrader import exception
from cryptotrader.models import Offer
from cryptotrader.models import Order
from cryptotrader.models import PostgresQueue


@pytest.fixture(scope='function')  # type: ignore
async def orders_pair(
    db, app, order_data, ask_offer_data, bid_offer_data
) -> typing.Tuple[Order, Order]:
    left = Order(
        offer=Offer(
            exchange=app.exchanges.get('left'),  # type: ignore
            **ask_offer_data
        ),
        **order_data
    )
    right = Order(
        offer=Offer(
            exchange=app.exchanges.get('right'),  # type: ignore
            **bid_offer_data
        ),
        **order_data
    )

    await left.save(db)
    await right.save(db)
    return left, right


@pytest.fixture(scope='function')
async def queue(
    db, app
) -> PostgresQueue:
    return PostgresQueue(engine=db, exchanges=app.exchanges)


@pytest.mark.asyncio
async def test_timescale_queue_push_pop(orders_pair, queue):
    left_order, right_order = orders_pair

    assert await queue.length() == 0
    await queue.push((left_order, right_order))
    assert await queue.length() == 1

    left_pop, right_pop = await queue.pop()
    assert isinstance(left_order, Order) and isinstance(right_order, Order)
    assert str(left_order.uuid) == str(left_pop.uuid)
    assert str(right_order.uuid) == str(right_pop.uuid)
    assert left_order.exchange == left_pop.exchange
    assert right_order.exchange == right_pop.exchange
    assert await queue.length() == 0


@pytest.mark.asyncio
async def test_timescale_queue_push_pop_from_empty(queue):
    with pytest.raises(exception.QueueEmpty):
        await queue.pop()
