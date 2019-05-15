import asyncio
from collections.abc import Mapping
from copy import copy
from datetime import datetime

from aiopg.sa import Engine

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.models import Money  # type: ignore
from cryptotrader.models import Offer  # type: ignore

# https://stackoverflow.com/questions/39740632/python-type-hinting-without-cyclic-imports
if typing.TYPE_CHECKING:
    # helps to avoid cycles import error
    from cryptotrader.exchange import Exchange  # type: ignore  # Ignore PyFlakesBear


class Order:
    """
    Order for buy/sell special Offer on exchange.

    This distinction between Order and Offer is Order have clear base, date
    and state. You can find more info about `Order` term on Glossary page.

    >>> order = Order(
    >>>     offer=Offer(
    >>>         price_type='BID',
    >>>         pair='BTCUSD',
    >>>         price=80.0,
    >>>         quote=80000.0,
    >>>         exchange=exchange,
    >>>     ),
    >>>     commission=0.15,
    >>>     status='created',
    >>> )
    """

    # @todo #484:60m Create `Order.expire_type` field.
    #  `HitbtcHttpTransport.ORDER_TIME_IN_FORCE` contains examples of possible values.
    #  This field is required for `cryptotrader.tests.test_combat.test_exchange_place_and_cancel`.
    #  So, resurrect all paid tests too.

    def __init__(  # Ignore PyDocStyleBear
        self,
        offer: Offer,
        status=const.CREATED,  # created/cancelled/fulfilled
        strategy='',
        type_=const.LIMIT,
        created_at=None,
        expired_at=None,
        executed_at=None,
        commission=0.0,
        id_on_exchange=None,
        uuid=None,
    ) -> None:
        """
        :param type_: defines exchange's price calculation method:
        type_='limit' - exchange will place order exactly with this price.
        type_='market' - exchange will place order with the most good price at this moment.
        """
        assert type_ in const.ORDER_TYPES

        self.uuid = uuid
        self.id_on_exchange = id_on_exchange
        self.type = type_
        self.offer = copy(offer)
        self.status = status
        self.strategy = strategy
        self.created_at = created_at or datetime.utcnow()
        self.executed_at = executed_at
        self.expired_at = expired_at
        self.commission = commission

    @staticmethod
    def from_data(data: Mapping, exchange: 'Exchange'):
        """
        Create instance from some mapping. Used for fetching order from db.

        :param data: data mapping. Usually it fetched from db.
        :param exchange:
        :return:
        """
        date_fields = ['created_at', 'expired_at', 'executed_at']

        def cast_date_fields() -> dict:
            result = {}
            for field in date_fields:
                value = getattr(data, field, None)
                result[field] = value.replace(tzinfo=None) if value else value
            return result

        return Order(
            Offer(
                price_type=const.ORDER_OFFER_SIDES_MAP[data.side],  # type: ignore
                pair=data.pair,  # type: ignore
                price=data.price,  # type: ignore
                quote=data.quote,  # type: ignore
                exchange=exchange,  # type: ignore
            ),
            uuid=data.uuid,  # type: ignore
            id_on_exchange=data.id_on_exchange,  # type: ignore
            status=data.status,  # type: ignore
            **cast_date_fields(),  # type: ignore
        )

    def __str__(self):
        return (
            f'<Order: status: {self.status},'
            f' id_on_exchange: {self.id_on_exchange},'
            f' uuid: {self.uuid},'
            f' pair: {self.pair}, side: {self.side},'
            f' price: {self.price:.4f}, exchange: {self.exchange.name},'
            f' base: {self.base}, quote: {self.quote}'
            f' executed_at: {self.executed_at}>'
        )

    def report_str(self) -> str:
        return (
            f'{self.offer.report_str()}\n'
            f'Order DB id - {self.uuid}\n'
            f'Order exchange id - {self.id_on_exchange}'
        )

    def reversed(self, new_price: float=0.0) -> 'Order':
        return Order(
            Offer(
                price_type=self.offer.reversed_price_type(),
                pair=self.pair,
                price=new_price or self.price,
                quote=self.quote.amount,
                exchange=self.exchange,
                timestamp=self.offer.timestamp,
            ),
            status=const.CREATED,
            type_=const.MARKET,  # reversed order always should have market type
        )

    @property
    def side(self) -> str:
        """Return casted `self.offer.price_type` value."""
        return const.OFFER_ORDER_SIDES_MAP[self.price_type]

    @property
    def price_type(self) -> str:
        """Shortcut for `self.offer.price_type`."""
        return self.offer.price_type

    @property
    def quote(self) -> Money:
        """Shortcut for `self.offer.quote`."""
        return self.offer.quote

    @property
    def base(self) -> Money:
        """Shortcut for `self.offer.base`."""
        return self.offer.base

    @property
    def pair(self) -> str:
        """Shortcut for `self.offer.pair`."""
        return self.offer.pair

    @property
    def price(self) -> float:
        """Shortcut for `self.offer.price`."""
        return self.offer.price

    @property
    def exchange(self):
        """Shortcut for `self.offer.exchange`."""
        return self.offer.exchange

    @property
    def is_closed(self) -> bool:
        return self.status in [const.FULFILLED, const.CANCELLED]

    @property
    def is_placed(self) -> bool:
        return self.status in [const.PLACED, const.FULFILLED]

    def set_quote(self, quote: Money):
        """Set quote field. And recalculate base field with old price."""
        assert quote.currency == self.quote.currency

        self.offer = self.offer.clone(
            price=self.price,
            quote=quote.amount,
        )

    def set_base(self, base: Money):
        assert base.currency == self.base.currency
        new_quote_amount = round(base.amount / self.price, 10)
        self.offer = self.offer.clone(
            price=self.price,
            quote=new_quote_amount
        )

    async def save(self, db: Engine):
        """
        Create or update an order.

        If current order instance isn't created, then inserts new row,
        and sets it as self.uuid attribute value.
        Otherwise just updates row in database with order instance data.
        """
        table = db.tables['orders']
        data = {
            'id_on_exchange': self.id_on_exchange,
            'status': self.status,
            'pair': self.pair,
            'side': self.side,
            'price': self.price,
            'base': self.base.amount,
            'quote': self.quote.amount,
            'exchange': self.exchange.name,
            'strategy': self.strategy,
            'created_at': self.created_at,
            'expired_at': self.expired_at,
            'executed_at': self.executed_at,
        }
        async with db.acquire() as conn:
            if not self.uuid:
                self.uuid = await conn.scalar(
                    table.insert().values(**data)
                )
            else:
                await conn.execute(
                    table.update().where(
                        table.c.uuid == self.uuid
                    ).values(**data)
                )

    async def delete(self, db: Engine):
        """
        Delete current order from database.

        Throws exception if current order instance doesn't have database id.
        """
        if not self.uuid:
            raise ValueError(f'Invalid order UUID: {self.uuid}')

        table = db.tables['orders']

        async with db.acquire() as conn:
            await conn.execute(
                table.delete().where(
                    table.c.uuid == self.uuid
                )
            )
        self.uuid = None

    async def update_status(self) -> typing.Tuple[bool, str]:
        """Update an order status from an exchange."""
        result = await self.exchange.fetch_status(self)
        if result.success:
            self.status = result.status
        return result.success, result.response

    async def cancel(self) -> typing.Tuple[bool, str]:
        """Cancel an order and set the status."""
        result = await self.exchange.cancel(self)
        if result.success:
            self.status = const.CANCELLED
        return result.success, result.response

    async def validate(self) -> bool:
        return await self.exchange.validate(self)

    async def place(self) -> typing.Tuple[bool, str]:
        place_result = await self.exchange.place(self)
        self.status = place_result.order_status
        if place_result.success:
            self.id_on_exchange = place_result.order_id
            assert self.id_on_exchange and self.is_placed, self
        return place_result.success, place_result.response

    async def wait_status(
        self, statuses: typing.List[str], timeout=10.0, fetch_order_interval=1.0,
    ) -> typing.Tuple[bool, str]:
        async def run_fetching(fetch_order_interval):
            response = ''
            while self.status not in statuses:
                _, response = await self.update_status()
                await asyncio.sleep(fetch_order_interval)
            return response
        try:
            response = await asyncio.wait_for(
                run_fetching(fetch_order_interval),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return False, (
                'Timeout of waiting a specified order statuses'
                f'({", ".join(statuses)}) is reached for order: {self}'
            )
        return True, response

    async def trade(
        self,
        timeout=10.0,
        fetch_order_interval=1.0,
        sleep_after_placed=1.0,
    ) -> typing.Tuple[bool, str]:
        is_placed, place_response = await self.place()
        if not is_placed:
            return False, place_response
        assert self.id_on_exchange and self.is_placed, self

        # sleep before waiting the status.
        # Because some amazing exchanges
        # places order to list of opened after some delay.
        # Bittrex for example.
        await asyncio.sleep(sleep_after_placed)
        is_closed, status_response = await self.wait_status(
            [const.FULFILLED, const.CANCELLED],
            timeout,
            fetch_order_interval
        )
        if is_closed:
            assert self.is_closed, self
            self.executed_at = datetime.utcnow()
            if self.status == const.CANCELLED:
                return False, status_response
            # some delay for balances refresh inside exchanges
            await asyncio.sleep(0.5)
            await self.exchange.fetch_balances()
            return True, status_response
        else:
            await self.cancel()
            return False, status_response
