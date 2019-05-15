from copy import deepcopy
from datetime import datetime
import json

from cryptotrader import typing
from cryptotrader.common import Serializer
from cryptotrader.models import Offer  # type: ignore
from cryptotrader.models import Order  # type: ignore

if typing.TYPE_CHECKING:
    # helps to avoid cycles import error
    from cryptotrader.exchange import Exchanges  # type: ignore  # Ignore PyFlakesBear


def cast_date(date: typing.Union[datetime, float, None]) -> typing.Union[datetime, float, None]:
    """Cast datetime to float and vice versa."""
    if isinstance(date, datetime):
        return date.timestamp()
    elif isinstance(date, float):
        return datetime.fromtimestamp(date)


class OrderSerializer(Serializer):

    def __init__(self, *, exchanges: 'Exchanges') -> None:
        # use an 'Exchange' string instead of an Exchange type, because of
        # raised an ImportError
        self.exchanges = exchanges

    def to_dict(self, order: Order) -> dict:
        return {
            'uuid': order.uuid,
            'created_at': cast_date(order.created_at),
            'executed_at': cast_date(order.executed_at),
            'expired_at': cast_date(order.expired_at),
            'status': order.status,
            'offer': {
                'exchange_name': order.offer.exchange_name,
                'pair': order.offer.pair,
                'price': order.offer.price,
                'price_type': order.offer.price_type,
                'quote': order.offer.quote.amount,
            },
        }

    def from_dict(self, raw_order: dict) -> Order:
        order_data = deepcopy(raw_order)
        order_data['created_at'] = cast_date(order_data['created_at'])
        order_data['executed_at'] = cast_date(order_data['executed_at'])
        order_data['expired_at'] = cast_date(order_data['expired_at'])
        offer_data = order_data.pop('offer')
        exchange = self.exchanges.get(offer_data.pop('exchange_name'))
        return Order(**order_data, offer=Offer(**offer_data, exchange=exchange))  # type: ignore

    def dumps(self, orders: typing.List[Order]) -> bytes:
        return json.dumps([self.to_dict(order) for order in orders]).encode()

    def loads(self, raw_order: bytes) -> typing.List[Order]:
        return [self.from_dict(order) for order in json.loads(raw_order)]
