# Ignore PyDocStyleBear
"""
Hitbtc api doc here: https://api.hitbtc.com/api/2/explore/.
Hitbtc inner terms described here: https://hitbtc.com/fix.
"""
from collections import defaultdict
import time
from urllib.parse import urlencode

import aiohttp

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.exchange import HttpTransport  # type: ignore
from cryptotrader.exchange import Session  # type: ignore
from cryptotrader.models import Order


class HitbtcHttpTransport(HttpTransport):

    # 0 - Day (or session)
    # 1 - Good Till Cancel (GTC)
    # 2 = Immediate or Cancel (IOC)
    # 4 = Fill or Kill (FOK)
    # 6 - Good Till Date (GTD)
    ORDER_TIME_IN_FORCE = 'IOC'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exchange_currency_pairs: typing.Dict[str, dict] = {}
        self.exchange_order_status_map = defaultdict(
            lambda: const.PLACED, {
                'new': const.CREATED, 'filled': const.FULFILLED,
                'canceled': const.CANCELLED, 'expired': const.REJECTED,
            }
        )

    def sign(self, payload=None):
        # this auth method is official hitbtc's v2 right now:
        # https://github.com/hitbtc-com/hitbtc-api/blob/master/APIv2.md#authentication
        return aiohttp.BasicAuth(self.key, self.secret)

    def get_url(self, endpoint):
        nonce = str(int(time.time() * 1000))
        return f'{self.base_url}{endpoint}?apikey={self.key}&nonce={nonce}'

    async def request(self, session, endpoint, method='get', **post_kwargs):
        request_params = {'url': self.get_url(endpoint), 'auth': self.sign()}
        if method == 'post':
            call = session.post(**request_params, data=urlencode(post_kwargs))
        elif method == 'get':
            call = session.get(**request_params)
        elif method == 'delete':
            call = session.delete(**request_params)
        else:
            raise ValueError('Request method is not correct')
        return await call

    async def handle_response(self, response):
        success, result = await super().handle_response(response)
        return success and 'error' not in result, result

    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        # https://api.hitbtc.com/#trading-balance
        success, response = await self.get('/trading/balance')

        balances: dict = {}
        if success:
            balances = {
                el['currency'].upper(): float(el['available'])
                for el in response
            }

        return typing.SessionFetchedBalances(
            success=success,
            balances=balances,
            response=str(response),
        )

    async def place(self, order: Order) -> typing.PlacedOrder:
        success, response = await self.post(
            '/order',
            symbol=order.pair,
            timeInForce=self.ORDER_TIME_IN_FORCE,
            side=order.side,
            price=order.price,  # don't affect for `type='market'`
            type=order.type,
            quantity=order.quote.amount,
        )
        order_id = ''
        status = order.status
        if success:
            order_id = response['clientOrderId']
            status = self.exchange_order_status_map[response['status']]

        return typing.PlacedOrder(
            success=success,
            order_id=order_id,
            order_status=status,
            response=str(response),
        )

    async def cancel(self, order: Order) -> typing.CancelledOrder:
        success, response = await self.rest_call(f'/order/{order.id_on_exchange}', method='delete')
        return typing.CancelledOrder(success=success, response=str(response))

    async def fetch_status(self, order: Order) -> typing.FetchedOrderStatus:
        success, response = await self.get(f'/order/{order.id_on_exchange}')

        status = ''
        if success:
            status = self.exchange_order_status_map[response['status']]

        return typing.FetchedOrderStatus(
            success=success,
            status=status,
            response=str(response),
        )

    def _handle_pair(self, pair, min_size, ask_offers, bid_offers) -> typing.Dict[str, float]:
        def prepare(price):
            return {
                scalar_name: float(scalar)
                for scalar_name, scalar in price.items()
            }

        def filter_size(price):
            return price['size'] > min_size

        ask = next(filter(filter_size, map(prepare, ask_offers)), None)
        bid = next(filter(filter_size, map(prepare, bid_offers)), None)

        if not (bid and ask):
            return {}

        return {
            'ask': float(ask['price']),
            'ask_size': float(ask['size']),
            'bid': float(bid['price']),
            'bid_size': float(bid['size']),
        }

    async def fetch_pair(
        self, pair: str, pair_limits=0.0
    ) -> typing.SessionFetchedPair:
        success, response = await self.get(f'/public/orderbook/{pair}')

        handled_pair: dict = {}
        if success:
            handled_pair = self._handle_pair(
                pair=pair,
                min_size=pair_limits,
                ask_offers=response['ask'],
                bid_offers=response['bid'],
            )

        return typing.SessionFetchedPair(
            success=bool(handled_pair), pair=handled_pair, response=str(response),
        )

    async def schedule(self):
        if self.exchange_currency_pairs:
            return
        success, response = await self.get('/public/symbol')
        if success and 'error' not in response:
            self.exchange_currency_pairs = {el['id']: el for el in response}


class HitbtcSession(Session):
    name = 'hitbtc'

    def __init__(
        self, key, secret, http_base_url,
        *,
        rate_limit: dict = None, loop=None
    ) -> None:
        self.http_transport = HitbtcHttpTransport(
            key=key, secret=secret, base_url=http_base_url,
            rate_limit=typing.RateLimit(**(rate_limit or {})),
            loop=loop,
        )
        super().__init__(transports=[self.http_transport])

    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        return await self.http_transport.fetch_balances()

    async def fetch_pair(self, *args, **kwargs) -> typing.SessionFetchedPair:
        return await self.http_transport.fetch_pair(*args, **kwargs)

    async def place(self, *args, **kwargs) -> typing.PlacedOrder:
        return await self.http_transport.place(*args, **kwargs)

    async def cancel(self, *args, **kwargs) -> typing.CancelledOrder:
        return await self.http_transport.cancel(*args, **kwargs)

    async def fetch_status(self, *args, **kwargs) -> typing.FetchedOrderStatus:
        return await self.http_transport.fetch_status(*args, **kwargs)
