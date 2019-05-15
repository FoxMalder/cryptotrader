"""Bittrex api doc is here: https://bittrex.com/home/api."""
import asyncio
import hashlib
import hmac
import time
from urllib.parse import urlencode

import aiohttp

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.exchange import HttpTransport  # type: ignore
from cryptotrader.exchange import Session  # type: ignore
from cryptotrader.models import Order


class BittrexMixin:

    def pair_local2bittrex(self, name):
        """BTCUSD -> BTC-USD."""
        def usd_to_usdt(sym):
            if sym == 'USD':
                return 'USDT'
            return sym
        fsym, tsym = usd_to_usdt(name[0:3]), usd_to_usdt(name[3:])
        return f'{tsym}-{fsym}'.upper()

    def pair_bittrex2local(self, name):
        """ok_sub_spotbtc_usd_trade -> BTCUSD."""
        def usd_to_usdt(sym):
            if sym == 'USD':
                return 'USDT'
        fsym = name.replace('_', '')[9:12]
        tsym = name.replace('_', '')[12:15]
        return f'{fsym}{tsym}'.upper()


class BittrexHttpTransport(HttpTransport, BittrexMixin):

    # @todo #113 Remove the BittrexMixin in prefer of dependency injection.

    def sign(self, payload):
        return hmac.new(
            self.secret.encode(), payload, hashlib.sha512
        ).hexdigest()

    def get_url(self, endpoint, query_params):
        nonce = str(int(time.time() * 1000))
        query_strings = urlencode(query_params)
        return f'{self.base_url}{endpoint}?apikey={self.key}&nonce={nonce}&{query_strings}'

    async def request(self, session, endpoint, method, json=True, tbs=None, **kwargs):
        url = self.get_url(endpoint, kwargs)
        return await session.get(
            url, headers={'apisign': self.sign(url.encode())},
        )

    def _process_subscribe_pair(self, pair, min_size, buy, sell) -> typing.Dict[str, float]:
        bid = ask = bid_size = ask_size = 0

        for item in buy or []:
            if item['Quantity'] < min_size:
                continue
            bid_size = item['Quantity']
            bid = item['Rate']
            break

        for item in sell or []:
            if item['Quantity'] < min_size:
                continue
            ask_size = item['Quantity']
            ask = item['Rate']
            break

        if not (bid and ask):
            return {}

        return {
            'bid_size': float(bid_size),
            'bid': float(bid),
            'ask_size': float(ask_size),
            'ask': float(ask),
        }

    async def fetch_pair(self, pair: str, min_size=0) -> typing.SessionFetchedPair:
        success, response = await self.rest_call(
            '/public/getorderbook', 'GET',
            tbs=None,
            type='both',
            market=self.pair_local2bittrex(pair)
        )
        is_fetched = success and response['success']

        pair_data: dict = {}
        if is_fetched:
            pair_data = self._process_subscribe_pair(pair, min_size, **response['result'])

        return typing.SessionFetchedPair(
            success=bool(pair_data),
            pair=pair_data,
            response=str(response),
        )

    async def fetch_status(self, order: Order) -> typing.FetchedOrderStatus:
        def get_order_status_by_data(order_data: dict):
            if order_data.get('QuantityRemaining', -1.0) == 0.0:
                return const.FULFILLED
            if order_data.get('Closed', None):
                return const.CANCELLED
            return const.CREATED

        success, response = await self.get(
            '/market/getopenorders',
            market=self.pair_local2bittrex(order.pair),
            tbs=['apikey', 'nonce', 'market']
        )

        if success and response.get('success', False):
            for order_data in response.get('result', []):
                if order_data['OrderUuid'] == order.id_on_exchange:
                    return typing.FetchedOrderStatus(
                        success=True,
                        status=get_order_status_by_data(order_data),
                        response=str(response),
                    )
            # orders list fetched with success,
            # but our `order` is not opened already.
            # So, it was fulfilled.
            self.logger.debug(
                f'Order not found in exchange\'s opened orders list.'
                f' So, it\'s successful by default. Response {response}.'
            )
            return typing.FetchedOrderStatus(
                success=True,
                status=const.FULFILLED,
                response=str(response),
            )

        self.logger.warning(
            f'Unknown order status.'
            f' Response data from exchange: {response}'
        )
        return typing.FetchedOrderStatus(
            success=False,
            status=order.status,
            response=str(response),
        )

    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        # list of balances. List structure looks like this:
        # https://bittrex.com/home/api, ctrl+f "/account/getbalances"
        success, response = await self.get('/account/getbalances')
        is_fetched = success and response['success']

        def prepare_currency(currency: str) -> str:
            upper_currency = currency.upper()
            if upper_currency == 'USDT':
                return 'USD'
            return upper_currency

        balances: dict = {}
        if is_fetched:
            balances = {
                prepare_currency(balance['Currency']): balance['Available']
                for balance in response['result']
            }

        return typing.SessionFetchedBalances(
            success=is_fetched,
            balances=balances,
            response=str(response)
        )

    async def place(self, order: Order) -> typing.PlacedOrder:
        pair = self.pair_local2bittrex(order.pair)
        if order.type == const.MARKET:
            self.logger.info(
                'Bittrex place market order as limit.'
                ' It supports only limit orders.'
            )
        success, response = await self.get(
            '/market/buylimit' if order.side == const.BUY else '/market/selllimit',
            market=pair,
            rate=order.price,
            quantity=order.quote.amount,
            tbs=['apikey', 'nonce', 'market', 'rate', 'quantity']
        )

        is_placed = success and response.get('success', False)

        order_id = ''
        status = order.status
        if is_placed:
            order_id = response['result']['uuid']
            status = const.PLACED

        return typing.PlacedOrder(
            success=is_placed,
            order_id=order_id,
            order_status=status,
            response=str(response)
        )

    async def cancel(self, order: Order) -> typing.CancelledOrder:
        success, response = await self.get(
            '/market/cancel',
            uuid=order.id_on_exchange,
            tbs=['apikey', 'uuid'],
        )
        return typing.CancelledOrder(
            success=success and bool(response['success']),
            response=str(response),
        )


class BittrexSession(Session):
    name = 'bittrex'

    def __init__(
        self,
        key, secret, http_base_url,
        *,
        rate_limit: dict = None, loop=None
    ) -> None:
        self.http_transport = BittrexHttpTransport(
            key=key,
            secret=secret,
            base_url=http_base_url,
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
