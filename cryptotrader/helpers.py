"""Several common method for diagnostic reuse."""
import time

from cryptotrader import const
from cryptotrader.exchange import Exchange
from cryptotrader.models import Offer
from cryptotrader.models import Order


async def buy_or_sell(
    pair: str, price_type: str,
    amount: float, price: float,
    exchange: Exchange,
    id_on_exchange=None
) -> Order:
    assert price_type in [const.ASK, const.BID]

    order = Order(
        offer=Offer(
            pair=pair,
            price_type=price_type,
            price=price,
            quote=amount,
            exchange=exchange,
            timestamp=time.time(),
        ),
        id_on_exchange=id_on_exchange,
        status=const.CREATED,
    )
    await order.trade()
    return order
