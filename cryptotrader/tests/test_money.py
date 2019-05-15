from cryptotrader.exchange import Exchange
from cryptotrader.models import PairName
from cryptotrader.tests.mock import MockSession


def test_pair_name_convert(exchange_data):
    left_exchange = Exchange(
        name='left_exchange',
        pair_name_template='{quote}{base}',
        session=MockSession(),
        **exchange_data
    )
    right_exchange = Exchange(
        name='right_exchange',
        pair_name_template='{quote}{base}',
        session=MockSession(),
        **exchange_data
    )
    left_pair_name = PairName('ETCUSD', left_exchange)
    right_pair_name = left_pair_name.convert(right_exchange)
    assert str(right_pair_name) == 'ETCUSD'
