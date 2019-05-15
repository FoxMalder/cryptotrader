import abc

import sqlalchemy as sa

from cryptotrader import const
from cryptotrader import exception
from cryptotrader import typing
from cryptotrader.common import Serializer
from cryptotrader.models import Order  # type: ignore


class Queue(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def pop(self):
        pass

    @abc.abstractmethod
    async def push(self, data):
        pass

    @abc.abstractmethod
    async def length(self):
        pass


class RedisQueue(Queue):

    def __init__(self, connection, name: str, serializer: Serializer) -> None:
        self.connection = connection
        self.name = name
        self.serializer = serializer

    async def pop(self):
        return self.serializer.loads(await self.connection.execute('LPOP', self.name))

    async def push(self, data: object):
        return await self.connection.execute('RPUSH', self.name, self.serializer.dumps(data))

    async def length(self):
        length = await self.connection.execute('LLEN', self.name)
        return int(length)


class PostgresQueue(Queue):

    def __init__(self, engine, exchanges) -> None:
        self.engine = engine
        self.exchanges = exchanges

    @property
    def table(self):
        return self.engine.tables['order_pairs']

    async def pop(self) -> typing.Tuple[Order, Order]:
        def get_order(data):
            return Order.from_data(data, self.exchanges.get(data.exchange))

        query = """
        WITH R as (
          DELETE FROM order_pairs
          WHERE uuid IN (SELECT uuid FROM order_pairs ORDER BY time LIMIT 1)
          RETURNING *
        )
        SELECT orders.* FROM orders
        JOIN R ON orders.uuid IN (R.left_order_uuid, R.right_order_uuid)
        ORDER BY orders.type;
        """
        async with self.engine.acquire() as conn:
            data = await conn.execute(query)
        orders_pair = await data.fetchall()
        if orders_pair:
            left_data, right_data = orders_pair
            if left_data.side != const.BUY:
                left_data, right_data = right_data, left_data
            return get_order(left_data), get_order(right_data)
        else:
            raise exception.QueueEmpty()

    async def push(self, orders_pair: typing.Tuple[Order, Order]):
        left, right = orders_pair
        async with self.engine.acquire() as conn:
            await conn.execute(
                self.table.insert().values(
                    # put as str, not bytes
                    left_order_uuid=str(left.uuid),
                    right_order_uuid=str(right.uuid),
                )
            )

    async def length(self) -> int:
        async with self.engine.acquire() as conn:
            length = await conn.scalar(
                sa.select([sa.func.count()]).select_from(self.table)
            )
        return length
