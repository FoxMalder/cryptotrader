# @todo #156 Implement the Poloniex transport layer as in Bitfinex.

# import asyncio
# import hashlib
# import hmac
# import json
# import time
# from cryptotrader import typing
# from urllib.parse import urlencode

# import aiohttp

# from cryptotrader import const
# from cryptotrader.common.compress import deflate
# from cryptotrader.exchange import Exchange  # type: ignore


# class Poloniex(Exchange):
#     title = 'Poloniex'
#     name = 'poloniex'
#     protocol = const.WEBSOCKET

#     def __init__(self, *args, rest_public, rest_trading, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.rest_public = rest_public
#         self.rest_trading = rest_trading

#     async def run_websocket(self):
#         return await super().run_websocket(subprotocols=['wamp.2.json'])

#     async def recv(self):
#         await self.ws.recv()

#     async def send(self, payload):
#         self.logger.debug(f'{self} send {payload}')
#         data = deflate(json.dumps(payload))
#         data = await self.ws.send(data)

#     async def consumer(self, message: dict):
#         if isinstance(message, dict):
#             event_name = message.pop('event')
#             fn = getattr(self, f'consume_{event_name}', None)
#             if not fn:
#                 self.logger.info(f'Skip read event {message}')
#                 return
#             await fn(self.ws, **message)
#         elif isinstance(message, list) and len(message) == 2 and len(message[1]) == 10:
#             chanId = message[0]
#             fn = self.channels.get(chanId, None)
#             if not fn:
#                 self.logger.info(f'Skip read channel update {message}')
#                 return
#             await fn(self.ws, *message[1:])
#         elif isinstance(message, list) and len(message) == 2 and message[1] == 'hb':
#             return
#         elif isinstance(message, list) and len(message) == 3:
#             return
#         else:
#             self.logger.info(f'Skip read message {message}')

#     def gen_update_pair_fn(self, pair: str):
#         """
#         Update state of pairs.

#         BID float   Price of last highest bid
#         BID_SIZE    float   Size of the last highest bid
#         ASK float   Price of last lowest ask
#         ASK_SIZE    float   Size of the last lowest ask
#         DAILY_CHANGE    float   Amount that the last price has changed since yesterday
#         DAILY_CHANGE_PERC   float   Amount that the price has changed expressed in percentage terms  # Ignore PycodestyleBear (E501)
#         LAST_PRICE  float   Price of the last trade.
#         VOLUME  float   Daily volume
#         HIGH    float   Daily high
#         LOW float
#         """
#         async def fn(ticker: list):
#             bid, _, ask, _, _, _, _, _, _, _ = ticker
#             self.pairs[pair] = {'bid': bid, 'ask': ask, 'time': time.time()}
#             self.logger.debug(f'Update pair: {pair} — bid: {bid}, ask: {ask}')
#         return fn

#     async def consume_subscribed(self, chanId: int, pair: str, **kw):
#         self.channels[chanId] = self.gen_update_pair_fn(pair)

#     async def subscribe_on_pairs(self):
#         async def subscribe(pair):
#             await self.send({
#                 'event': 'subscribe',
#                 'channel': 'ticker',
#                 'pair': pair
#             })
#         await asyncio.gather(*[subscribe(pair) for pair in self.default_pairs])

#     async def authorization(self):
#         self.logger.info('auth')
#         nonce = str(int(time.time() * 1000000))
#         auth_string = 'AUTH' + nonce
#         auth_sig = hmac.new(
#             self.secret.encode(), auth_string.encode(), hashlib.sha384
#         ).hexdigest()

#         # result = json.loads(await self.recv())
#         # if result['version'] != 2:
#         #     raise NotImplemented

#         await self.send({
#             'event': 'auth',
#             'apiKey': self.key,
#             'authSig': auth_sig,
#             'authPayload': auth_string,
#             'authNonce': nonce
#         })

#         result = json.loads(await self.recv())
#         if result['status'] == 'FAILED':
#             self.logger.info(
#                 f'auth error codeId is {result["code"]}, msg is {result["msg"]}'
#             )
#             return False
#         self.channels: typing.Dict[int, typing.Callable] = {}
#         return True

#     def sign(self, data: dict) -> str:  # type: ignore
#         data['nonce'] = str(int(time.time()))
#         sign = hmac.new(
#             key=self.key.encode('utf-8'),
#             msg=urlencode(data).encode('utf-8'),
#             digestmod=hashlib.sha512,
#         )
#         return sign.hexdigest()

#     async def fetch_balances(self):
#         # https://poloniex.com/support/api/ + ctrl-f "returnBalances"
#         with aiohttp.ClientSession() as session:
#             data = {
#                 'command': 'returnBalances',
#             }
#             endpoint = self.rest_trading
#             headers = {
#                 'Key': self.key,
#                 'Sign': self.sign(self.key, data)
#             }
#             async with session.post(
#                 endpoint,
#                 data=urlencode(data),
#                 headers=headers,
#             ) as response:
#                 response_data = await response.json()
#                 if response.status == 200:
#                     self.balances = {
#                         k: float(v) for k, v in response_data.items()
#                     }
#                 else:
#                     self.logger.warning(
#                         f'Api error. Request url: "{endpoint}".'
#                         f'Response data: "{response_data}"'
#                     )
