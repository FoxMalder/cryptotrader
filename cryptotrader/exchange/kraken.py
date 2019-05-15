# @todo #156 Implement the Kraken transport layer as in Bittrex.

# import asyncio
# from base64 import b64decode
# from base64 import b64encode
# import hashlib
# import hmac
# import time
# from cryptotrader import typing
# from urllib.parse import urlencode

# from cryptotrader import const
# from cryptotrader.exchange import Exchange  # type: ignore
# from cryptotrader.models import Order


# class KrakenMixin:

#     mapping_pair = (
#         ('BTCUSD', 'XXBTZUSD'),
#         ('LTCUSD', 'XLTCZUSD'),
#         ('ETHUSD', 'XETHZUSD'),
#         ('ETCUSD', 'XETCZUSD'),
#         ('ETHBTC', 'XETHXXBT'),
#         ('LTCBTC', 'XLTCXXBT'),
#         ('ZECUSD', 'XZECZUSD'),
#         ('XMRUSD', 'XXMRZUSD'),
#         ('DASHUSD', 'DASHUSD'),
#     )

#     local2kraken = {
#         l: r
#         for (l, r) in mapping_pair
#     }

#     kraken2local = {
#         l: r
#         for (l, r) in mapping_pair
#     }

#     def pair_local2kraken(self, name):
#         assert name in self.local2kraken, name
#         return self.local2kraken[name]

#     def pair_kraken2local(self, name):
#         assert name in self.kraken2local, name
#         return self.kraken2local[name]


# class Kraken(Exchange, KrakenMixin):
#     title = 'Kraken'
#     name = 'kraken'
#     protocol = const.REST

#     async def process_subscribe_pair(self, pair, value):
#         min_size = self.pair_limits.get(pair, 2)

#         bid = ask = bid_size = ask_size = 0.0
#         for item in value['asks']:
#             if float(item[1]) > min_size:
#                 ask = float(item[0])
#                 ask_size = float(item[1])
#                 break

#         for item in value['bids']:
#             if float(item[1]) > min_size:
#                 bid = float(item[0])
#                 bid_size = float(item[1])
#                 break

#         if (not bid or not ask):
#             return

#         await self.on_ticker_update(
#             pair=pair,
#             bid_size=bid_size, bid=bid,
#             ask_size=ask_size, ask=ask,
#         )

#     async def subscribe_on_pairs(self):
#         async def subscribe(pair: str):
#             while self.loop.is_running():
#                 try:
#                     remote_pair = self.pair_local2kraken(pair)
#                     result = await self.rest_call(
#                         '/public/Depth', 'GET',
#                         json=True,
#                         pair=remote_pair,
#                         tbs=['pair', 'nonce'],
#                     )
#                     assert result['result'], result
#                     await self.process_subscribe_pair(pair, result['result'][remote_pair])
#                 except Exception as error:
#                     self.logger.exception('Update error: {error}')
#                 finally:
#                     await asyncio.sleep(self.interval)
#         for pair in self.default_pairs:
#             asyncio.ensure_future(subscribe(pair))

#     def sign(self, tbs, url, kwargs):
#         """
#         Sign request's content.

#         Used an algorithm described in Kraken docs: https://goo.gl/9fBb4d
#         Message signature use HMAC-SHA512 of (URI path + SHA256(nonce + POST data))
#         and base64 decoded secret API key.
#         """
#         data = {}
#         for key in tbs:
#             data[key] = kwargs[key]
#         encoded = (str(data['nonce']) + urlencode(data)).encode()
#         message = url.encode() + hashlib.sha256(encoded).digest()
#         signature = hmac.new(b64decode(self.secret), message, hashlib.sha512)
#         return b64encode(signature.digest()).decode()

#     async def request(self, session, endpoint, method, json=False, tbs=None, **kwargs):
#         if not tbs:
#             tbs = []
#         url = self.base_url + endpoint
#         kwargs['nonce'] = int(time.time() * 1000)
#         headers = {
#             'API-Key': self.key,
#             'API-Sign': self.sign(tbs, url, kwargs),
#         }

#         return await super(Kraken, self).request(
#             session, endpoint, method, json=json, headers=headers, **kwargs
#         )

#     async def place(self, order: Order) -> typing.Tuple[bool, dict]:
#         if not self.validate(order):
#             return False, {}

#         pair = self.pair_local2kraken(order.pair)

#         result = await self.post(
#             '/private/AddOrder',
#             json=True,
#             type='buy' if order.side == const.BUY else 'sell',
#             ordertype='limit',
#             pair=pair,
#             price=order.price,
#             volume=order.quote,
#             tbs=['type', 'ordertype', 'pair', 'price', 'volume', 'nonce'],
#         )
#         if result['error']:
#             self.logger.error(
#                 f'Error make order — {pair}/{order.side} for {order.quote} * '
#                 f'{order.price if order.price else "auto"} (extra: {result})'
#             )
#             return False, result
#         order_id = result['order_id']
#         self.logger.info(
#             f'Succesful place order {order_id} — {pair}/{order.side} for '
#             f'{order.quote} * {order.price if order.price else "auto"}'
#         )
#         return True, result

#     async def cancel(self, order: Order) -> typing.Tuple[bool, dict]:
#         if not order.id_on_exchange:
#             raise ValueError('Order doesn\'t have exchange ID')
#         result = await self.post(
#             '/private/CancelOrder',
#             json=True,
#             txid=order.id_on_exchange,
#             tbs=['txid', 'nonce'],
#         )
#         if result['error']:
#             return False, result
#         return True, result

#     async def fetch_balances(self):
#         # https://www.kraken.com/help/api#private-user-data
#         response = await self.get('/private/Balance')
#         if response['error']:
#             self.tg.warning(
#                 const.TELEGRAM_EXCHANGE_FETCH_BALANCES_ERROR.format(
#                     exchange=self.name,
#                     path=self.__module__,
#                     method='/balances',
#                     response_data=response,
#                 ),
#             )

#         for currency, value in response['result'].items():
#             self.balances[currency] = value
