import asyncio
from base64 import b64encode
import hashlib
import hmac
from json import dumps
import logging
import time

from cryptotrader import const
from cryptotrader import typing
from cryptotrader.exchange import HttpTransport  # type: ignore
from cryptotrader.exchange import Session  # type: ignore
from cryptotrader.exchange import WebsocketTransport  # type: ignore
from cryptotrader.models import Order


class BitfinexHttpTransport(HttpTransport):
    MAP_ORDER_TYPE = {
        const.LIMIT: 'exchange limit',
        const.MARKET: 'exchange market',
    }

    def sign(self, payload):
        return hmac.new(self.secret.encode(), payload, hashlib.sha384).hexdigest()

    async def request(self, session, endpoint, method, json=True, tbs=None, **kwargs):
        def cast_value(value) -> typing.Union[int, str]:
            if isinstance(value, int):
                return value
            return str(value)

        url = self.get_url(endpoint)
        kwargs = {
            'request': '/v1' + endpoint,
            # bitfinex replies with strange error for `10**6` multiplier.
            # `{'message': 'Nonce is too small.'}`.
            # Python example has no answer about right way:
            # https://github.com/scottjbarr/bitfinex/issues/9
            'nonce': f'{time.time() * 1e7:0.0f}',
            'exchange': 'bitfinex',
            **{key: cast_value(value) for key, value in kwargs.items()}
        }
        payload = b64encode(dumps(kwargs).encode())
        return await session.post(url, headers={
            'X-BFX-APIKEY': self.key,
            'X-BFX-PAYLOAD': payload.decode(),
            'X-BFX-SIGNATURE': self.sign(payload)
        })

    async def place(self, order: Order) -> typing.PlacedOrder:
        success, response = await self.post(
            '/order/new',
            api_key=self.key,
            symbol=order.pair,
            side=order.side,
            type=self.MAP_ORDER_TYPE[order.type],
            price=str(order.price),
            amount=str(order.quote.amount),
        )

        order_id = response.get('id', '')
        is_placed = success and order_id

        status = order.status
        if is_placed:
            status = self._get_order_status_from_response(response)

        return typing.PlacedOrder(
            success=is_placed,
            order_id=order_id,
            order_status=status,
            response=str(response)
        )

    async def cancel(self, order: Order) -> typing.CancelledOrder:
        success, response = await self.post(
            '/order/cancel',
            api_key=self.key,
            order_id=int(order.id_on_exchange),
        )
        is_cancelled = success and bool(response.get('is_cancelled', False))
        return typing.CancelledOrder(
            success=is_cancelled, response=str(response),
        )

    async def fetch_status(self, order: Order) -> typing.FetchedOrderStatus:
        success, response = await self.post(
            '/order/status',
            order_id=order.id_on_exchange,
        )

        status = ''
        if success:
            status = self._get_order_status_from_response(response)
            success = bool(status)

        return typing.FetchedOrderStatus(
            success=success,
            status=status,
            response=str(response)
        )

    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        # https://docs.bitfinex.com/v1/reference#rest-auth-wallet-balances
        success, response = await self.post('/balances')

        balances: dict = {}
        if success:
            balances = {
                balance['currency'].upper(): float(balance['available'])
                for balance in response
                if balance['type'] == 'exchange'
            }

        return typing.SessionFetchedBalances(
            success=success, balances=balances, response=str(response),
        )

    @staticmethod
    def _get_order_status_from_response(response: dict):
        if response.get('is_cancelled', False):
            return const.CANCELLED
        if float(response.get('remaining_amount', -1.0)) == 0.0:
            return const.FULFILLED
        if response.get('is_live', False):
            return const.PLACED
        if 'timestamp' in response:
            return const.CREATED


class BitfinexWebsocketTransport(WebsocketTransport):

    async def auth(self) -> bool:
        self.logger.info('auth')
        nonce = str(int(time.time() * 1000000))
        auth_string = 'AUTH' + nonce
        auth_sig = hmac.new(
            self.secret.encode(), auth_string.encode(), hashlib.sha384
        ).hexdigest()

        result = await self.ws_recv()
        if result['version'] != 2:
            raise NotImplementedError

        await self.ws_send({
            'event': 'auth',
            'apiKey': self.key,
            'authSig': auth_sig,
            'authPayload': auth_string,
            'authNonce': nonce
        })

        result = await self.ws_recv()
        if result['status'] == 'FAILED':
            self.logger.info(
                f'auth error codeId is {result["code"]}, msg is {result["msg"]}'
            )
            return False

        self.channels: typing.Dict[int, typing.Callable] = {}
        return True

    async def consumer(self, message: dict):
        if isinstance(message, dict):
            # Try to handle event
            event_name = message.pop('event')
            fn = getattr(self, f'consume_{event_name}', None)
            if message.get('code') == 20051:
                self.logger.warning(
                    'Exchange immediately stopped connection.'
                    f' Exchange\'s message: {message}.'
                    f' Bot will reconnect automatically.'
                )
            if not fn:
                self.logger.info(f'Skip read event {message}')
                return
            await fn(**message)
        elif isinstance(message, list) and len(message) == 2 and len(message[1]) == 10:
            # Try to handle channel message
            chan_id = message[0]
            fn = self.channels.get(chan_id, None)
            if not fn:
                self.logger.info(f'Skip read channel update {message}')
                return
            await fn(*message[1:])
        elif isinstance(message, list) and len(message) == 2 and message[1] == 'hb':
            # Skip ping
            return
        elif isinstance(message, list) and len(message) == 3:
            # Skip info
            return
        else:
            # Skip unknown message and log
            self.logger.info(f'Skip read message {message}')

    async def consume_subscribed(self, chanId: int, pair: str, **kw):
        async def update_pair(ticker):
            self.subscribed_pairs[pair] = ticker
        self.channels[chanId] = update_pair

    def _get_ticker(self, pair: str, min_size: float):
        """
        Get ticker data.

        BID float   Price of last highest bid
        BID_SIZE    float   Size of the last highest bid
        ASK float   Price of last lowest ask
        ASK_SIZE    float   Size of the last lowest ask
        DAILY_CHANGE    float   Amount that the last price has changed since yesterday
        DAILY_CHANGE_PERC   float   Amount that the price has changed expressed in percentage terms
        LAST_PRICE  float   Price of the last trade.
        VOLUME  float   Daily volume
        HIGH    float   Daily high
        LOW float
        """
        ticker = self.subscribed_pairs[pair]
        if not ticker:
            return {}

        (bid, bid_size, ask, ask_size, _, _, _, _, _, _) = ticker
        if bid_size < min_size or ask_size < min_size:
            return {}

        return {
            'ask': float(ask),
            'ask_size': float(ask_size),
            'bid': float(bid),
            'bid_size': float(bid_size),
        }

    async def fetch_pair(
        self, pair: str, pair_limits=0.0
    ) -> typing.SessionFetchedPair:
        if pair not in self.subscribed_pairs:
            await self.ws_send({
                'event': 'subscribe',
                'channel': 'ticker',
                'pair': pair
            })
        while pair not in self.subscribed_pairs:
            await asyncio.sleep(0.2)
        ticker = self._get_ticker(
            pair, pair_limits,
        )
        return typing.SessionFetchedPair(
            success=bool(ticker),
            pair=ticker,
            response=str(ticker),
        )


class BitfinexSession(Session):
    name = 'bitfinex'

    def __init__(
        self, key, secret, websocket_base_url, http_base_url,
        *,
        rate_limit: dict = None, loop=None
    ) -> None:
        self.websocket_transport = BitfinexWebsocketTransport(
            key=key,
            secret=secret,
            base_url=websocket_base_url,
            loop=None,
        )
        self.http_transport = BitfinexHttpTransport(
            key=key,
            secret=secret,
            base_url=http_base_url,
            rate_limit=typing.RateLimit(**(rate_limit or {})),
            loop=None,
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        super().__init__(
            transports=[self.websocket_transport, self.http_transport]
        )

    async def fetch_balances(self) -> typing.SessionFetchedBalances:
        return await self.http_transport.fetch_balances()

    async def fetch_pair(self, *args, **kwargs) -> typing.SessionFetchedPair:
        return await self.websocket_transport.fetch_pair(*args, **kwargs)

    async def place(self, *args, **kwargs) -> typing.PlacedOrder:
        return await self.http_transport.place(*args, **kwargs)

    async def cancel(self, *args, **kwargs) -> typing.CancelledOrder:
        return await self.http_transport.cancel(*args, **kwargs)

    async def fetch_status(self, *args, **kwargs) -> typing.FetchedOrderStatus:
        return await self.http_transport.fetch_status(*args, **kwargs)
