import asyncio
from copy import deepcopy
from datetime import timedelta
import logging.config

import aiopg.sa
from async_generator import asynccontextmanager
import click
import sqlalchemy as sa

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import exchange as crypto_exchange
from cryptotrader.common import make_schedule
from cryptotrader.models import Order
from cryptotrader.models import PostgresQueue
from cryptotrader.strategy import Arbitrage
from cryptotrader.strategy import Strategies


async def get_db(dsn: str, **engine_kwargs) -> aiopg.sa.Engine:
    engine = sa.create_engine(dsn)
    meta = sa.MetaData()
    order_table = sa.Table('orders', meta, autoload=True, autoload_with=engine)
    trade_history_table = sa.Table('trade_history', meta, autoload=True, autoload_with=engine)
    order_pairs = sa.Table('order_pairs', meta, autoload=True, autoload_with=engine)
    engine.dispose()

    async_engine = await aiopg.sa.create_engine(dsn=dsn, **engine_kwargs)

    async_engine.meta = meta
    async_engine.tables = {
        'orders': order_table,
        'trade_history': trade_history_table,
        'order_pairs': order_pairs,
    }

    return async_engine


class App:
    # @todo #268:60m Move App class constants to some config extension.
    STRATEGIES = [Arbitrage]
    DELAY_AFTER_INTERVAL = 5.0  # in seconds

    def __init__(self, config: dict, loop=None) -> None:
        self.config = config
        self.loop = loop = loop or asyncio.get_event_loop()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.is_running = asyncio.Event()
        self.db = None
        self.exchanges = None
        self.strategies = None
        self.scheduled_task = None

    # not good separated init after __init__ for client code
    # #455 will fix it.
    async def init(self):
        logging.config.dictConfig(self.config['logging'])
        self.db = await get_db(self.config['dsn'], loop=self.loop)
        self.exchanges = self._get_exchanges()
        self.strategies = self._get_strategies()

    def _get_exchanges(self):
        default_exchange_config = self.config['default_exchange']
        exchanges_config = deepcopy(self.config['exchanges'])
        strategy_config = self.config['strategies']['test']
        default_pairs = set(strategy_config['pairs'])
        return crypto_exchange.Exchanges(
            exchanges=[
                crypto_exchange.get_exchange_class(name)(  # type: ignore
                    session=crypto_exchange.get_session_class(name)(
                        **exchanges_config[name].pop('transport')
                    ),
                    db=self.db,
                    name=name,
                    loop=self.loop,
                    **{**default_exchange_config, **exchanges_config[name]},
                ) for name in exchanges_config
            ],
            default_pairs=default_pairs,
            loop=self.loop,
        )

    def _get_strategies(self):
        strategy_config = self.config['strategies']['test']
        if strategy_config['order_type'] not in const.ORDER_TYPES:
            raise exception.ConfigError(
                'Strategies "order_type" config value'
                f' should be in {const.ORDER_TYPES}.'
            )
        default_pairs = set(strategy_config['pairs'])

        # @todo #414:30m - unpack Arbitrage settings.
        #  Instead of them explicit forwarding.
        return Strategies(
            strategies=[
                Arbitrage(
                    db=self.db,
                    exchanges=self.exchanges,
                    loop=self.loop,
                    pairs=default_pairs,
                    to_reverse=PostgresQueue(self.db, self.exchanges),
                    window_direct_width=strategy_config['window_direct_width'],
                    window_reversed_width=strategy_config['window_reversed_width'],
                    max_spend_part=strategy_config['max_spend_part'],
                    fetch_order_interval=strategy_config['fetch_order_interval'],
                    order_timeout=strategy_config['order_timeout'],
                    autoreverse_order_delta=timedelta(
                        seconds=strategy_config['autoreverse_order_delta']
                    ),
                    order_type=strategy_config['order_type'],
                ),
            ],
        )

    # @todo #193 Create Orders class for orders batch processing
    async def _cancel_placed_orders(self):
        """If db contains placed orders, try to cancel them on exchanges."""
        self.logger.info(
            'Found placed orders in db'
            ' and try to cancel them on their exchanges.'
        )
        table = self.db.tables['orders']

        async with self.db.acquire() as conn:
            orders = conn.execute(
                table.select().where(
                    table.c.status == const.PLACED
                )
            )
            async for order in orders:
                try:
                    exchange = self.exchanges.get(order.exchange)
                except exception.NoSuchExchangeError:
                    self.logger.warning(
                        f'Skip an order cancelling on {order.exchange.title},'
                        f' because the exchange is not already supported.'
                        f' Order uuid: {order.uuid}.'
                    )
                    continue

                try:
                    success, _ = await exchange.cancel(
                        Order.from_data(order, exchange)
                    )
                except ValueError as e:
                    self.logger.warning(
                        f'Order with uuid={order.uuid} was not cancelled.'
                        f' Exception occured: {e}.'
                    )
                else:
                    if success:
                        await conn.execute(
                            table.update().where(
                                table.c.uuid == order.uuid
                            ).values(status=const.CANCELLED)
                        )

    async def _schedule(self):
        # strategies have guarantee,
        # that exchanges data is fresh
        await self.exchanges.schedule()
        await self.strategies.schedule()

    async def _warm_up(self):
        await self._cancel_placed_orders()
        await self._schedule()

    @asynccontextmanager
    async def context(self):
        # use `@asynccontextmanager` from third party
        # until python 3.7 coming.
        # https://docs.python.org/dev/whatsnew/3.7.html#contextlib
        # according to https://stackoverflow.com/a/48800772/6852582
        try:
            await self.run()
            yield
        finally:
            await self.stop()

    async def run(self):
        """Run app in loop on a schedule."""
        await self._warm_up()
        interval = self.config['app']['interval']
        scheduler = make_schedule(
            interval=interval,
            is_running=self.is_running,
            loop=self.loop,
            timeout=interval + self.DELAY_AFTER_INTERVAL,
        )
        scheduled_app = scheduler(self._schedule)
        self.is_running.set()
        self.scheduled_task = self.loop.create_task(scheduled_app())

    async def stop(self):
        self.is_running.clear()
        await self.exchanges.stop()
        await self.strategies.stop()
        self.db.close()
        await self.db.wait_closed()


@click.group()
def execute_group():
    pass


@execute_group.command()
@click.pass_context
def execute(ctx):
    loop = asyncio.get_event_loop()
    app = App(config=ctx.obj['cfg'], loop=loop)
    loop.run_until_complete(app.init())
    loop.create_task(app.run())
    loop.run_forever()
