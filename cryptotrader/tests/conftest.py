from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from functools import wraps
import time
from unittest.mock import patch
import uuid

import aiopg.sa
import pytest
import yaml

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.commands.execute import App
from cryptotrader.commands.execute import get_db
from cryptotrader.exchange import Exchange
from cryptotrader.exchange import get_session_class
from cryptotrader.models import Offer
from cryptotrader.models import Order
from cryptotrader.tests import utils
from cryptotrader.tests.mock import MockApp
from cryptotrader.tests.mock import MockSession

UNIT_CONFIG_PATH = 'cryptotrader/tests/configs/unit.yaml'
COMBAT_CONFIG_PATH = 'cryptotrader/tests/configs/combat.yaml'


def pytest_runtest_setup(item):
    combat_option = item.config.getoption('--runcombat')
    paid_option = item.config.getoption('--runpaid')
    combat_marker = item.get_marker('combat_test')
    paid_marker = item.get_marker('paid_test')

    if combat_option and not combat_marker:
        pytest.skip(f'{item.name} does not run without "combat_test" marker.')
    elif not combat_option and combat_marker:
        pytest.skip(f'{item.name} does not run without --runcombat flag.')
    elif paid_option and not paid_marker:
        pytest.skip(f'{item.name} does not run without "paid_test" marker.')

    if not paid_option and paid_marker:
        pytest.skip(f'{item.name} does not run without --runpaid flag.')
    elif paid_option and paid_marker:
        capmanager = item.config.pluginmanager.getplugin('capturemanager')
        capmanager.stop_global_capturing()
        run = input(f'\nRun {item.name} payed test y/n?\n')
        capmanager.start_global_capturing()
        if not (run == 'y' or run == 'yes'):
            pytest.skip(f'{item.name} is not runned.')


def deep_copied(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        return deepcopy(f(*args, **kwargs))
    return wrap


@deep_copied
@lru_cache(maxsize=1)
# we can't turn this function to fixture, because get_app uses it.
def get_mock_config() -> typing.Dict:
    """YML file config as dict."""
    with open(UNIT_CONFIG_PATH) as file:
        return yaml.load(file)


# it's not so easy to turn this function to fixture,
# because it passes additional parameter.
# But we'll do it at #377
def get_app(event_loop, config: dict=None) -> App:
    """Config dict contains values to redeclare ones from yaml config."""
    with _get_session_patch():
        config = config or {}
        app = MockApp(config={**get_mock_config(), **config}, loop=event_loop)
        event_loop.run_until_complete(app.init())
    return app


def _get_session_patch():
    """
    Patch `cryptotrader.exchange.get_session_class` method.

    Return MockSession class
    in case if session not found by exchange name.
    It's convenient for mock tests.
    `get_session_class` returns one of real exchange's session.
    For example BittrexSession or BitfinexSession.
    But unit tests can't work with real session, only with mock one.
    """
    def get_session_class_custom(exchange_name):
        try:
            return get_session_class(exchange_name)
        except exception.NoSuchExchangeError:
            return MockSession

    return patch(
        'cryptotrader.exchange.get_session_class',
        get_session_class_custom
    )


@pytest.fixture(scope='function')
def combat_config(request) -> dict:
    with open(COMBAT_CONFIG_PATH) as file:
        config_data = yaml.load(file)
    exchange_name = getattr(request, 'param', '')
    if exchange_name:
        config_data['exchanges'] = {
            exchange_name: config_data['exchanges'][exchange_name]
        }
        config_data['strategies']['test']['exchanges'] = [exchange_name]
    return config_data


@pytest.fixture(scope='function')
async def app(event_loop, config=None):
    config = config or {}
    with _get_session_patch():
        app = MockApp(config={**get_mock_config(), **config}, loop=event_loop)
        await app.init()
    async with app.context():
        yield app


@pytest.fixture(scope='function')
async def combat_app(event_loop, combat_config):
    app = App(combat_config, loop=event_loop)
    await app.init()
    async with app.context():
        yield app


@pytest.fixture(scope='function')
async def db(event_loop) -> aiopg.sa.Engine:
    engine = await get_db(
        get_mock_config()['dsn'],
        maxsize=1,
        minsize=1,
        loop=event_loop,
    )

    async with utils.RollbackAcquireManager(engine) as conn:
        manager = utils.SyncConnectionManager(conn)
        engine.acquire = lambda: manager
        yield engine
        await manager.is_executing


@pytest.fixture
def session_data(request, event_loop, db):
    return {
        'balances': {
            'USD': 50000.0, 'BTC': 8.0, 'ETC': 0.0,
        },
        **getattr(request, 'param', {}),
    }


@pytest.fixture
def exchange_data(request, event_loop, db):
    return {
        'pairs': {'BTCUSD', 'ETCUSD'},
        'fee': 0.0,
        'limit': 0.0,
        'pair_limits': {'BTCUSD': 0.0, 'ETCUSD': 0.0},
        'db': db,
        'fetch_balances_interval': 0.0,
        'subscribe_on_pairs_delay': 0.0,
        'interval': 1.0,
        'loop': event_loop,
        **getattr(request, 'param', {}),
    }


@pytest.fixture
def ask_offer_data(request):
    return {
        'pair': 'BTCUSD',
        'price_type': const.ASK,
        'quote': 5.0,
        'price': 5000.0,
        'timestamp': time.time(),
        **getattr(request, 'param', {}),
    }


@pytest.fixture
def bid_offer_data(request):
    return {
        'pair': 'BTCUSD',
        'price_type': const.BID,
        'quote': 5.0,
        'price': 5000.0,
        'timestamp': time.time(),
        **getattr(request, 'param', {}),
    }


@pytest.fixture
def order_data(request):
    return {
        'id_on_exchange': str(uuid.uuid4()),
        'executed_at': datetime.now(),
        'status': const.CREATED,
        **getattr(request, 'param', {}),
    }


@pytest.fixture
def order(order_data, ask_offer_data, exchange_data, session_data):
    return Order(  # type: ignore
        **order_data,
        offer=Offer(  # type: ignore
            **ask_offer_data,
            exchange=Exchange(  # type: ignore
                **exchange_data,
                session=MockSession(**session_data),
                name='bittrex',
            ),
        ),
    )
