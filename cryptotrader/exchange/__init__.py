from cryptotrader import exception

from .base import *
from .bitfinex import *
from .bittrex import *
from .hitbtc import *
# Uncomment these imports, when we implement transport classes for them.
# from .kraken import *
# from .okcoin import *
# from .poloniex import *


def get_exchange_class(exchange_name: str):
    return Exchange


def get_session_class(exchange_name: str):
    for class_ in globals().values():
        is_right_class = (
            Session in getattr(class_, '__bases__', [])
            and class_.name == exchange_name
        )
        if is_right_class:
            return class_
    raise exception.NoSuchExchangeError(exchange_name)
