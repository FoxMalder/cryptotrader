"""Cryptobot custom typing module inherited from standard typing."""
from typing import *

Balances = Dict[str, float]
BalancesDifference = Dict[str, Tuple[float, float]]

PairData = Dict[str, float]
PairsData = Dict[str, PairData]


class SessionFetchedBalances(NamedTuple):
    success: bool = False
    balances: Dict[str, float] = {}
    response: str = ''


class SessionFetchedPair(NamedTuple):
    success: bool = False
    pair: Dict[str, float] = {}
    response: str = ''


class PlacedOrder(NamedTuple):
    success: bool = False
    order_id: str = ''
    order_status: str = ''
    response: str = ''


class CancelledOrder(NamedTuple):
    success: bool = False
    response: str = ''


class FetchedOrderStatus(NamedTuple):
    success: bool = False
    status: str = ''
    response: str = ''


class RateLimit(NamedTuple):
    limit: int = 0
    period: float = 0.0
