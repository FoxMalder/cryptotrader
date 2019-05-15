r"""
Help module to operate exchange balances for stage testing.

It's temporary script with low code quality requirements.
Usage examples:
```
# alias dc=docker-compose
# dc run --rm bot python -m cryptotrader.cli <command>
dc run --rm bot python -m cryptotrader.cli balances
dc run --rm bot python -m cryptotrader.cli prepare_arbitrage
dc run --rm bot python -m cryptotrader.cli place \
  --exchange=hitbtc --side=sell --amount=0.2 --pair=LTCUSD
```
"""

import asyncio
import logging
import os
import time

import click
import yaml

from cryptotrader import const
from cryptotrader.commands.execute import App
from cryptotrader.models import Offer
from cryptotrader.models import Order
from cryptotrader.models import PairName

BALANCE_TOP_MARGIN = 30  # in USD
BALANCE_BOTTOM_MARGIN = 20  # in USD


class AppWithExchanges(App):
    """Process only exchanges, no strategies."""

    async def _schedule(self):
        await self.exchanges.schedule()


loop = asyncio.get_event_loop()
app: AppWithExchanges = None


def get_config():
    with open(os.getenv('HOST_CONFIG_PATH')) as file:
        return yaml.load(file.read())


async def init_app(log_level='WARNING'):
    config = get_config()
    config['logging']['loggers']['cryptotrader']['level'] = log_level
    app = AppWithExchanges(config=config, loop=loop)
    await app.init()
    return app


# Ignore PyDocStyleBear
async def place_order(
    exchange: str, side: str, amount: float, pair: str, price=0.0, with_output=True
) -> bool:
    """
    :param side: "buy" or "sell"
    :param amount: order amount in quote currency
    :param pair: currencies pair
    :param price:
    :param with_output: print output to stdout
    :return:
    """
    def get_safe_price(side: str):
        """
        Exchange should not take into account price value for orders of type `market`.

        But exchanges are often unpredictable, so we calc safe price:
        Very big amount for sell orders and very small amount for buy orders.
        :param side:
        :return:
        """
        return (
            const.MIN_SUM if side == const.BUY
            else const.MAX_SUM
        )

    assert isinstance(exchange, str)
    side = side.lower()

    exchange_obj = app.exchanges.get(exchange)
    await exchange_obj.fetch_balances()
    if with_output:
        print(f'Balances before:\n  {exchange_obj.balances_str}')
    order = Order(  # type: ignore
        type_=const.MARKET,
        offer=Offer(  # type: ignore
            # TODO - check bittrex with it's templates
            pair=pair,
            price_type=const.ORDER_OFFER_SIDES_MAP[side],
            quote=amount,
            price=price or get_safe_price(side),
            timestamp=time.time(),
            exchange=exchange_obj,
        ),
    )
    success, response = await order.trade()
    # configurable function is not good practice, but it's temporary script
    if with_output:
        if success:
            # balances fetched inside trade
            print(f'Success. Balances after:\n  {exchange_obj.balances_str}')
        else:
            print(f'Error. Exchange response:\n  {response}')
    return success


async def _prepare_arbitrage(
    balance_bottom_margin: int, balance_top_margin: int
):
    async with app.context():
        print(f'Balances before:\n  {app.exchanges.balances_str}')
        for exchange in app.exchanges.exchanges:
            for currency, balance in exchange.balances.items():
                #   - if some contains more then 20 USD, try to sale redundant crypto
                pair = f'{currency}USD'
                pair_data = exchange.get_pair_data(pair)
                ask_price, bid_price = pair_data['ask'], pair_data['bid']
                if balance * ask_price > balance_top_margin:
                    #  - add `max(quote_to_sell, quote_limit)`
                    #  - refresh all quote limits with hands
                    quote_to_sell = balance - balance_top_margin / bid_price
                    quote_limit = exchange.get_pair_limit(pair)
                    if quote_to_sell > quote_limit:
                        # don't do any if-order-success checks here. If smth went wrong,
                        # we should fix it with hands with `place` cli command
                        await place_order(
                            exchange=exchange.name,
                            side=const.SELL,
                            amount=quote_to_sell,
                            pair=pair,
                            price=bid_price,
                            with_output=False
                        )

            arbitrage = app.strategies.strategies[0]
            pairs_to_check = set(exchange.default_pairs).intersection(set(arbitrage.pairs))
            for pair in pairs_to_check:
                if 'USD' not in pair:
                    continue
                pair_name = PairName(pair)
                pair_data = exchange.get_pair_data(pair)
                ask_price, bid_price = pair_data['ask'], pair_data['bid']
                balance = exchange.get_balance(pair_name.quote)
                if balance * ask_price < balance_bottom_margin:
                    quote_diff = balance_bottom_margin / ask_price - balance
                    quote_limit = exchange.get_pair_limit(str(pair_name))
                    quote_to_buy = max(quote_diff, quote_limit)
                    # don't do any if-order-success checks here. If smth went wrong,
                    # we should fix it with hands with `place` cli command
                    await place_order(
                        exchange=exchange.name,
                        side=const.BUY,
                        amount=quote_to_buy,
                        pair=pair,
                        price=ask_price,
                        with_output=False
                    )

        print(f'Balances after:\n  {app.exchanges.balances_str}')


@click.group()
@click.option('-l', '--log_level', type=click.Choice(logging._nameToLevel.keys()), help='default to WARNING')
def cli(log_level):
    # not good technique. We should use smth like click contexts instead.
    # But it fast and easy. We have low code quality requirements.
    global app
    app = loop.run_until_complete(init_app(log_level))


@cli.command()
def balances():
    """All non zero balances on every exchange."""
    loop.run_until_complete(app.exchanges.fetch_balances())
    print(app.exchanges.balances_str)


@cli.command()
@click.option('-e', '--exchange', help='"bitfinex" for example')
@click.option('-s', '--side', type=click.Choice(const.ORDER_SIDES))
@click.option('-a', '--amount', type=click.FLOAT)
@click.option('-p', '--pair', help='currencies pair: "ETCUSD" for example')
@click.option('--price', default=0.0)
def place(exchange: str, side: str, amount: float, pair: str, price: float):
    """Immediately place order to exchange. Order will have type='market'."""
    loop.run_until_complete(place_order(exchange, side, amount, pair, price))


@cli.command()
@click.option('--min', type=click.INT, help='min funds on every coin balance')
@click.option('--max', type=click.INT, help='max funds on every coin balance')
def prepare_arbitrage(min, max):
    """
    Prepare exchange accounts for arbitrage. Works with only USD as base currency.

    Every exchange should contain enough cryptocoins for arbitrage currency for every watched pair.
    This command prepares exchanges in such way.
    Algorithm goes throw two steps:
    - command accumulates the exchange's bot funds on one USD balance;
    - command buys min amount of every coin (currency), needed for arbitrage processing.

    Let's see example.
    Suppose we have this data:
    ```
    # exchanges
    bitfinex: 2.0 LTC, 10 USD
    hitbtc: 1.0 ETC, 100.0 USD

    # arbitrage
    pairs: LTCUSD, ETCUSD

    # pairs_data
    1 LTC = ~200 USD
    1 ETC = ~20 USD
    ```
    Suppose prices ask=bid for simplicity.

    To be able to do arbitrage both exchanges
    should contain some min amount for LTC and for ETC coins.

    After this command processed we'll see this exchange balances:
    ```
    bitfinex: 1.0 ETC, 0.2 LTC, 150.0 USD
    hitbtc: 1.0 ETC, 0.1 ETC, 80.0 USD
    ```
    Now both this exchanges are ready for `LTCUSD, ETCUSD` arbitrage.
    """
    min = min or BALANCE_BOTTOM_MARGIN
    max = max or BALANCE_TOP_MARGIN
    loop.run_until_complete(_prepare_arbitrage(min, max))


if __name__ == '__main__':
    cli()
