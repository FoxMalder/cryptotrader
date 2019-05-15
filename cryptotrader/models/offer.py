from collections import namedtuple

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.models import Money  # type: ignore
from cryptotrader.models import PairName  # type: ignore

if typing.TYPE_CHECKING:
    # helps to avoid cycles import error
    from cryptotrader.exchange import Exchange  # type: ignore  # Ignore PyFlakesBear


# Moved outside of offer model due to https://stackoverflow.com/a/4678982
OfferFrozenFields = namedtuple(
    'OfferFrozenFields',
    ['base', 'quote', 'price_type', 'price', 'exchange', 'timestamp'],
)


# @todo #474:60m Move all offer data checks to Offer.
#  is_fresh, is_possible and so on.
#  Currently this checks are performed `get_pair_offer_map` method.
class Offer:
    """
    Offer for buy/sell certain currency amount on certain exchange.

    You can find more info about `Offer` term on Glossary page.

    offer = "We can buy 1000 ETC for price $312 per unit on Okcoin exchange.
    offer.exchange_name == "Okcoin"
    offer.price_type == "bid"
    offer.base == 1000
    offer.price == 312
    offer.quote == $312000 - we spend this sum to buy 1000 ETC

    History why we decided to use this Offer structure. But not ticker or Order.
    Github comment (rus): https://goo.gl/UVwKub
    """

    FIELDS_FOR_SIMILARITY = ['pair', 'price_type', 'exchange_name']
    FIELDS_TO_CLONE = [
        'price_type', 'pair', 'price', 'quote', 'exchange', 'timestamp',
    ]

    def __init__(  # Ignore PyDocStyleBear
        self,
        price_type: str,
        pair: str,
        price: float,
        quote: float,
        exchange: 'Exchange',
        timestamp=0.0,
    ) -> None:
        """
        :param price_type: 'ask'/'bid'
        :param pair: 'ETCUSD'
        :param price: price for one ETC
        :param exchange:
        """
        # @todo #176:30m/DEV Rename Offer fields.
        #  - Offer.quote to Offer.quatity, that will be base currency quantity
        #  - Offer.base to Offer.total == Offer.quatity * Offer.price
        #  e.g. Offer(pair=ETCUSD, price=500, quatity=5) means
        #  you can buy 5 ETC for 2500 USD.

        self._pair_name = PairName(pair, exchange)
        if exchange:
            assert str(self._pair_name) in exchange.default_pairs

        self._immutable_fields = OfferFrozenFields(
            # save base+quote, but not save price.
            # Because each of base and quote contains currency
            # Order price (if pair is BTC-USD then price currency is USD)
            base=Money(round(quote * price, 5), self._pair_name.base),
            # Quantity of order assets, e.g. 1 BTC
            quote=Money(quote, self._pair_name.quote),
            price_type=price_type,
            price=price,
            exchange=exchange,
            timestamp=timestamp,
        )

    def __str__(self):
        return (
            f'<Offer: pair: {self.pair}, price type: {self.price_type}, '
            f'price: {self.price:.4f}, exchange: {self.exchange_name}, '
            f'base: {self.base}, quote: {self.quote}>'
        )

    def report_str(self) -> str:
        return (
            f'{self.price_type.upper()}:\n'
            f'- Exchange - {self.exchange.name}\n'
            f'- Price - {self.price}\n'
            f'- Quote Volume - {self.quote}\n'
            f'- Base Volume - {self.base}'
        )

    def clone(self, **kwargs) -> 'Offer':
        """Clone offer but set to it custom fields from kwargs."""
        def get_quote_amount() -> float:
            quote = kwargs.get('quote')
            if not quote:
                return self.quote.amount
            elif isinstance(quote, Money):
                return quote.amount
            elif isinstance(quote, float):
                return quote
            raise TypeError('quote arg should be one of Money of float types')

        for key in kwargs:
            assert key in self.FIELDS_TO_CLONE

        kwargs_of_clone = {}
        for field in self.FIELDS_TO_CLONE:
            if field != 'quote':
                kwargs_of_clone[field] = kwargs.get(field) or getattr(self, field)
            else:
                # "quote" field is special, because in the same time
                # it has float type of constructor param,
                # but Money field type
                kwargs_of_clone['quote'] = get_quote_amount()
        return Offer(**kwargs_of_clone)

    @property
    def pair(self) -> str:
        """Pair name string in exchange's format."""
        return str(self._pair_name)

    @property
    def base(self) -> Money:
        return self._immutable_fields.base

    @property
    def quote(self) -> Money:
        return self._immutable_fields.quote

    @property
    def price_type(self) -> str:
        return self._immutable_fields.price_type

    @property
    def price(self) -> float:
        return self._immutable_fields.price

    @property
    def total_price(self) -> float:
        """Price, calculated with exchange fee."""
        k = (
            1 if self.price_type == const.ASK
            else -1
        )
        return self.price * (1.0 + k * self.exchange.fee)

    @property
    def exchange(self) -> 'Exchange':
        return self._immutable_fields.exchange

    @property
    def exchange_name(self) -> str:
        return self._immutable_fields.exchange.name

    @property
    def timestamp(self) -> float:
        return self._immutable_fields.timestamp

    def reversed_price_type(self) -> str:
        return const.ASK if self.price_type == const.BID else const.BID

    def reversed(self) -> 'Offer':
        """Offer with the same data, but reversed price type."""
        return self.clone(price_type=self.reversed_price_type())

    async def refreshed(self) -> 'Offer':
        """
        The same offer, but with guaranteed fresh price.

        :param timeout: Offer becomes stale after this timeout in seconds.
        """
        pair_data = await self.exchange.get_fresh_pair(self.pair)
        return self.clone(
            price=pair_data[self.price_type],
            timestamp=pair_data['time']
        )

    def is_similar(
        self,
        other: 'Offer',
        fields_to_compare: list=None,
        **kwargs
    ) -> bool:
        """
        Compare `self` and `other` instances.

        :param other:
        :param fields_to_compare:
            if empty, compare `self` and `other` with default fields list:
            `Offer.FIELDS_FOR_SIMILARITY`
        :param kwargs:
            every additional kwarg is field-value map.
            It's substituted for comparing instead of getattr(other, field).
        :return:

        >>> offer_left = Offer(
        >>>     pair='BTCUSD',
        >>>     price_type=const.ASK,
        >>>     quote=2.0,
        >>>     price=8000.0,
        >>>     exchange=exchange
        >>> )
        >>> offer_right = Offer(
        >>>     pair='BTCUSD',
        >>>     price_type=const.BID,
        >>>     quote=2.0,
        >>>     price=8000.0,
        >>>     exchange=exchange
        >>> )
        >>>
        >>> assert offer_left.is_similar(offer_right, price_type=const.ASK)  # True
        >>> assert not offer_left.is_similar(offer_right)  # False
        """
        def get_value(field: str):
            return kwargs.get(field) or getattr(other, field)

        fields_to_compare = fields_to_compare or Offer.FIELDS_FOR_SIMILARITY
        return all([
            getattr(self, field) == get_value(field)
            for field in fields_to_compare
        ])

    def in_pair_limit(self, max_spend_part=1.0) -> bool:
        """
        Check if exchange balance and offer amount are in boundaries of pair_limits.

        When we create order from offer, we can lower quote (and base) amount.
        In other words:
        order = create_from(offer); (order.amount >= offer.amount) == True.
        But we can't set order.amount lower,
        then balances value for quote of base currency.
        That's why balances should be great-equal, then related pair_limit.

        See for additional notes:
        """
        funds_to_check: Money = (
            self.base
            if self.price_type == const.ASK
            else self.quote
        )
        price_factor: float = (
            self.price
            if self.price_type == const.ASK
            else 1
        )
        balance = self.exchange.get_balance(funds_to_check.currency)
        # pair_limit is always in quote currency
        pair_limit = self.exchange.get_pair_limit(str(self._pair_name))
        return (
            balance * max_spend_part >= pair_limit * price_factor
            and self.quote.amount * max_spend_part >= pair_limit
        )
