# @todo #156 Implement the OKCoin transport layer as in Bitfinex.

# """Okcoin api doc is here: https://www.okcoin.com/rest_api.html."""
# import asyncio
# import hashlib
# import json
# from cryptotrader import typing

# from cryptotrader import const
# from cryptotrader.common.compress import inflate
# from cryptotrader.exchange import Exchange  # type: ignore
# from cryptotrader.models import Order


# class OKCoinMixin:

#     def pair_local2okcoin(self, name):
#         """BTCUSD -> btc_usd."""
#         fsym, tsym = name[0:3], name[3:]
#         return f'{tsym}_{fsym}'.lower()

#     def pair_okcoin2local(self, name):
#         """ok_sub_spotbtc_usd_trade -> BTCUSD."""
#         fsym = name.replace('_', '')[9:12]
#         tsym = name.replace('_', '')[12:15]
#         return f'{tsym}{fsym}'.upper()


# class OKCoin(Exchange, OKCoinMixin):
#     title = 'OKCoin'
#     name = 'okcoin'
#     protocol = const.WEBSOCKET
#     signature_key = 'sign'

#     async def ws_recv(self):
#         data = await self.ws.recv()
#         try:
#             return json.loads(data)
#         except Exception:
#             return json.loads(inflate(data))

#     async def ws_consumer(self):
#         while self.loop.is_running():
#             messages = await self.ws_recv()
#             if not isinstance(messages, list):
#                 messages = [messages]
#             for message in messages:
#                 asyncio.ensure_future(self.consumer(message))

#     async def consumer(self, message: dict):
#         assert isinstance(message, dict), message
#         if 'channel' not in message:
#             return
#         channel_name = message.pop('channel')

#         fn = getattr(self, f'consume_{channel_name}', None)
#         if fn:
#             await fn(**message['data'])
#             return
#         fn = self.channels.get(channel_name, None)
#         if fn:
#             await fn(message['data'])
#             return
#         self.logger.info(f'Skip read channel_name {channel_name}')

#     async def produce_ping(self):
#         self.logger.debug('ping')
#         await self.ws_send({
#             'event': 'ping',
#         })

#     async def schedule(self):
#         await super().schedule()
#         await self.produce_ping()

#     def gen_update_pair_fn(self, pair: str):
#         async def fn(data: list):
#             bid = self.pairs[pair].get('bid')
#             ask = self.pairs[pair].get('ask')
#             min_size = self.pair_limits.get(pair, 2)
#             bid_size = 0
#             ask_size = 0
#             for item in data:
#                 if float(item[2]) < min_size:
#                     continue
#                 if item[-1] == 'bid':
#                     _, bid, bid_size, _, _ = item
#                 else:
#                     _, ask, ask_size, _, _ = item
#             if not (bid and ask):
#                 return
#             await self.on_ticker_update(
#                 pair=pair,
#                 bid_size=float(bid_size), bid=float(bid),
#                 ask_size=float(ask_size), ask=float(ask),
#             )
#         return fn

#     async def consume_addChannel(self, result: bool, channel: str, **kw):
#         pair = self.pair_okcoin2local(channel)
#         self.channels[channel] = self.gen_update_pair_fn(pair)

#     async def subscribe_on_pairs(self):
#         async def subscribe(pair):
#             pair = self.pair_local2okcoin(pair)
#             await self.ws_send({
#                 'event': 'addChannel',
#                 'channel': f'ok_sub_spot{pair}_trades',
#                 'binary': 'true'
#             })
#         await asyncio.gather(*[subscribe(pair) for pair in self.default_pairs])

#     def sign(self, tbs, kwargs):
#         arguments = kwargs.copy()
#         arguments['api_key'] = self.key
#         secret_key = f'&secret_key={self.secret}'
#         qs = '&'.join(f'{key}={arguments[key]}' for key in sorted(tbs or [])) + secret_key
#         signature = hashlib.md5(qs.encode()).hexdigest().upper()
#         arguments[self.signature_key] = signature
#         return arguments

#     async def place(self, order: Order) -> typing.Tuple[bool, dict]:
#         if not self.validate(order):
#             return False, {}

#         pair = self.pair_local2okcoin(order.pair)
#         tbs = ['api_key', 'symbol', 'type', 'price', 'amount']

#         result = await self.post(
#             '/trade.do',
#             tbs=tbs,
#             api_key=self.key,
#             symbol=pair,
#             type=f'{order.side}_market',
#             price=order.price,
#             json=False,
#             amount=order.quote,
#         )
#         result = json.loads(result)
#         if 'error_code' in result:
#             self.logger.error(
#                 f'Error make order — {pair}/{order.side} for {order.quote} * '
#                 f'{order.price or "auto"} (extra: {result})'
#             )
#             return False, result
#         order_id = result['order_id']
#         self.logger.info(
#             f'Succesful place order {order_id} — {pair}/{order.side} for '
#             f'{order.quote} * {order.price or "auto"}'
#         )
#         return True, result

#     async def authorization(self) -> bool:
#         self.logger.info('skip auth')
#         self.channels: typing.Dict[str, typing.Callable] = {}
#         return True

#     async def fetch_balances(self) -> None:
#         json_data = await self.post('/userinfo.do', json=False, tbs=['api_key'])
#         data = json.loads(json_data)
#         if not data.get('result', False):
#             self.logger.warning(f'Get balance error. Response: {json_data}')
#         self.balances = data['info']['funds']['free']

#     def get_balance(self, currency: str) -> float:
#         currency = currency.lower()
#         balance = self.balances.get(currency, None)
#         if balance is None:
#             self.logger.warning(f'We have no acc with currency "{currency}"')
#         return float(balance or 0.0)
