from functools import partial

from cryptotrader import typing


class PairName:
    """Parse and validate currency tickers from exchange trades data."""

    def __init__(self, pair: str, exchange=None) -> None:
        """
        Parse pair to quote and base.

        :param pair:
        :param exchange: `None` means this pair_name is used just by bot.
        """
        self.exchange = exchange
        # exchange contain pattern and currencies_map fields.
        # Exchange take it from config (see config example ahead).
        # Default values:
        #  exchange.pattern = '{quote}{base}' by default
        #  exchange.currencies_map = {}
        self.quote, self.base = self._parse_raw_pair(pair)

    def __str__(self):
        """Get pair name as str in bot's format by default."""
        return self.to_common_format()

    def to_exchange_format(self):
        """Convert to exchange's inner format by default."""
        return self.exchange.pair_name_template.format(
            quote=self.quote, base=self.base,
        )

    def to_common_format(self) -> str:
        """
        Get pair name as str in common format.

        "ETCUSD", for example.
        """
        return f'{self.quote}{self.base}'

    # @todo #113:60m Implement `PairName._parse_raw_pair` method.
    #  Class PairName has just two methods right now.
    #  But parse method promises to be big.
    #  Decide to move or not to move this methods to Offer class
    #  after _parse_raw_pair method implementing.
    def _parse_raw_pair(self, pair: str) -> typing.Tuple[str, str]:
        quote, base = pair[:3].upper(), pair[3:].upper()
        return quote, base

        # 1. Extract delimiter from `self.exchange.pattern`
        # 2. Cut this delimiter from `pair`
        # 3. Create all_currencies list
        # 4. Find starts_with currency
        # currency = find(pair.starts_with(c) for c in all_currencies)
        # 5. Cut currency from pair.
        # 6. Check if pair's right side in all_currencies
        # 7. Extract currencies: left, right = currency, pair_right_side
        # 8. base, quote = left, right if base_on_left(pattern) or right, left

        # Test cases
        # - Default: ETCUSD, '{quote}{base}' -> USD, ETC
        # - Delimiter: ETC-USD, '{quote}-{base}' -> USD, ETC
        # - Inverted: USDETC, '{base}{quote}' -> USD, ETC
        # - Custom currency: ETCUSDT, '{quote}{base}' -> USD, ETC
        # - Hardcore: USDTAU, '{base}{quote}' -> USD, TAU
        # Corner cases:
        # - empty pair
        # - Wrong custom: ETCUSD, '{quote}{base}', map: USD=USDT -> USD, ETC, warning

        # use `self.exchange.currencies_map`
        # and `self.exchange.pattern`
        # to extract self.quote, self.base

    def convert(self, exchange) -> 'PairName':
        return PairName(
            pair=exchange.pair_name_template.format(
                quote=self.quote,
                base=self.base,
            ),
            exchange=exchange,
        )


class Money:
    """See Glossary for `Money` term."""

    PRECISION = 2  # digits after point

    def __init__(self, amount: float, currency: str) -> None:
        self.amount = amount
        self.currency = currency
        super().__init__()

    def __str__(self):
        return f'{self.amount:.4f} {self.currency}'

    def __repr__(self):
        return f'cryptotrader.models.Money <{self.amount:.4f} {self.currency}>'

    def __eq__(self, other):
        round_ = partial(round, ndigits=self.PRECISION)
        return (
            self.currency == other.currency
            and round_(self.amount) == round_(other.amount)
        )
