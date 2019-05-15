#!/usr/bin/env python

import sys

from setuptools import setup

if sys.version_info < (3, 6):
    print('app need python version great than 3.6')
    sys.exit(1)

setup(
    name='cryptotrader',
    packages=['arbitrage', 'trading', 'crypto-currency'],
    version='0.1',
    description='Crypto-currency trading platform',
    author='Fidals team',
    author_email='duker33@gmail.com',
    url='https://github.com/fidals/cryptotrader',
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
)
