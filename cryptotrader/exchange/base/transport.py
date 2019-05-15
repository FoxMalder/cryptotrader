import abc
import asyncio
import json
import logging
from urllib.parse import urlencode

import aiohttp
import websockets

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.common import Limited
from cryptotrader.common import Schedulable


class WebsocketTransport(Schedulable, metaclass=abc.ABCMeta):

    def __init__(self, key, secret, base_url, *, loop=None) -> None:
        super().__init__()
        self.logger = logging.getLogger(f'cryptotrader.transport.{self.__class__.__name__}')
        self.loop = loop or asyncio.get_event_loop()

        self.key = key
        self.secret = secret
        self.base_url = base_url

        self.is_running = asyncio.Event()
        self.ws = None
        self.ws_settings: dict = {}
        self.channels: typing.Dict[str, typing.Callable] = {}
        self.subscribed_pairs: typing.Dict[str, typing.List[float]] = {}

    async def wait_ws(self):
        if self.ws:
            return
        while not self.ws:
            await asyncio.sleep(0.1)

    async def ws_recv(self):
        await self.wait_ws()
        data = await self.ws.recv()
        return json.loads(data)

    async def ws_send(self, data):
        await self.wait_ws()
        return await self.ws.send(json.dumps(data))

    async def ws_recv_forever(self):
        try:
            while self.is_running.is_set():
                recv = await asyncio.wait_for(
                    self.ws_recv(),
                    timeout=const.FOREVER_TASK_TIMEOUT
                )
                await self.consumer(recv)
        except asyncio.TimeoutError:
            self.logger.warning(
                'Bot received no messages via websocket'
                f' for last {const.FOREVER_TASK_TIMEOUT} seconds. '
                ' Stop websocket connection.'
            )
        except Exception as error:
            self.logger.exception(f'Catch error: {error}')
        finally:
            await self.stop()

    async def consumer(self, message):
        self.logger.warning(f'Skip consume with message: {message}')

    async def auth(self) -> bool:
        self.logger.warning('Skip websocket authorization')
        return True

    async def auth_wrapped(self) -> None:
        """
        Wrap `self.auth` method.

        with exceptions raising and corner cases handling.
        """
        auth_success = await self.auth()
        if not auth_success:
            await self.stop()
            raise exception.WebsocketAuthError(self.base_url)

    async def ping(self):
        await self.wait_ws()
        await self.ws.ping()

    async def connect(self):
        self.logger.info(f'Connect to exchange via websocket')

        async with websockets.connect(self.base_url, **self.ws_settings) as ws:
            self.ws = ws
            try:
                if await self.auth():
                    self.is_running.set()
                    await self.ws_recv_forever()
            except Exception as error:
                self.logger.exception(f'Catch error: {error}')
            finally:
                self.is_running.clear()
                self.ws = None
                self.channels = {}
                self.subscribed_pairs = {}

    async def schedule(self):
        if not self.is_running.is_set():
            self.logger.info(f'Connect to exchange via websocket.')
            self.ws = await websockets.connect(self.base_url, **self.ws_settings)
            if self.ws:
                self.logger.debug(
                    f'Websocket connection is established: {self.ws}'
                )
            await self.auth_wrapped()
            self.is_running.set()
            self.ensure_future(self.ws_recv_forever())
        else:
            await self.ping()

    async def stop(self):
        if self.is_running.is_set():
            self.is_running.clear()
            await super().stop()
            await self.ws.close()
            self.channels = {}
            self.subscribed_pairs = {}


class HttpTransport(Schedulable, metaclass=abc.ABCMeta):

    def __init__(
        self,
        key,
        secret,
        base_url,
        *,
        rate_limit=typing.RateLimit(),
        loop=None,
    ) -> None:
        super().__init__()
        self.logger = logging.getLogger(f'cryptotrader.transport.{self.__class__.__name__}')
        self.loop = loop or asyncio.get_event_loop()
        self.limiter = Limited(*rate_limit, loop=loop)  # type: ignore

        self.key = key
        self.secret = secret
        self.base_url = base_url

    def get(self, endpoint, **kwargs):
        return self.rest_call(endpoint, method='get', **kwargs)

    def post(self, endpoint, **kwargs):
        return self.rest_call(endpoint, method='post', **kwargs)

    @abc.abstractmethod
    def sign(self, payload):
        """Sign the request's payload."""

    def get_url(self, endpoint):
        return self.base_url + endpoint

    async def rest_call(self, *args, **kwargs):
        async with self.limiter:
            async with aiohttp.ClientSession() as session:
                return await self.handle_response(
                    await self.request(session, *args, **kwargs)
                )

    async def request(self, session, endpoint, method, json=True, tbs=None, headers=None, **kwargs):
        if tbs:
            kwargs = self.sign(tbs, kwargs)
        if not headers:
            headers = {}

        url = self.get_url(endpoint)
        if method.lower() == 'get':
            qs = urlencode(kwargs)
            url = url + '?' + qs
            self.logger.debug(f'Http request to {url}')
            call = session.get(url, headers=headers)
        elif json:
            self.logger.debug(f'Http json request to {url} with data: {kwargs}')
            call = session.post(url, data=kwargs, headers=headers)
        else:
            qs = urlencode(kwargs)
            self.logger.debug(f'http request {url} {qs}')
            # send data as form, see https://goo.gl/PDVwEC
            headers.update({'Content-Type': 'application/x-www-form-urlencoded'})
            call = session.post(url, data=qs, headers=headers)
        return await call

    async def handle_response(self, response) -> typing.Tuple[bool, typing.Union[str, dict]]:
        content_type = response.headers.get('Content-Type', '')
        response_data = ''

        try:
            if 'application/json' in content_type:
                response_data = await response.json()
            elif 'text/' in content_type:
                response_data = await response.text()
            else:
                self.logger.warning(f'Unsupported content type: "{content_type}"')
        except Exception as error:
            self.logger.exception(f'Response parse error. Response data: {response}')
            raise error

        if response.status not in range(200, 400):
            self.logger.warning(
                f'Api error. Request url: "{response.request_info.url}".'
                f'Response data: "{response_data}"'
            )
            return False, response_data
        return True, response_data

    async def schedule(self):
        assert self.base_url
