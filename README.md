# Crypto Trading Platform

| Exchange                                                           | Implemented | Tested | Note |
|--------------------------------------------------------------------|-------------|--------|------|
| <a href="https://www.bitfinex.com" target="_blank">Bitfinex</a>    | ✓           |        |      |
| <a href="https://bittrex.com" target="_blank">Bittrex</a>          | ✓           |        |      |
| <a href="https://hitbtc.com" target="_blank">Hitbtc</a>            | ✓           |        |      |
| <a href="https://www.okcoin.com" target="_blank">OKCoin</a>        |             |        |      |
| <a href="https://www.kraken.com" target="_blank">Kraken</a>        |             |        |      |
| <a href="https://www.bithumb.com" target="_blank">Bithumb</a>      |             |        |      |
| <a href="https://www.gdax.com" target="_blank">Gdax</a>            |             |        |      |
| <a href="https://coinone.co.kr" target="_blank">Coinone</a>        |             |        |      |
| <a href="https://www.huobi.pro" target="_blank">Huobi</a>          |             |        |      |
| <a href="https://www.bitstamp.net" target="_blank">Bitstamp</a>    |             |        |      |
| <a href="https://www.korbit.co.kr" target="_blank">Korbit</a>      |             |        |      |
| <a href="https://bitflyer.com/en-us/" target="_blank">Bitflyer</a> |             |        |      |


## Begginer's guide

### Run bot

**1. Create .env**

Copy `.env.dist` to `.env` and modify it's values if needed. 

**2. Build bot**

Only for the first time or if `Dockerfile` was changed.
```bash
docker-compose build bot
```

**3. Apply database migrations**

Will create a schema and set the current version of migration for database.
```bash
make migrate-up
```

**4. Run bot**

*On local stage*
```bash
make run
```

*On server*:
```bash
docker-compose up -d bot
```

### Run tests

```bash
make test
```

## Working with stage

If you test bot manually on stage, look at `cryptotrader.cli` module.
It contains useful staff to prepare exchanges for tests.

### Work with database migrations

We are using a [migrate](https://github.com/mattes/migrate) tool in `cryptotrader/migrate`
docker image, that helps us to apply migrations for database's schema.

`cryptotrader/migrate` has some rules:
- all migration files must be placed in the /usr/migrations container directory
- the container must have a config file with a specified `dsn` variable for
work with a database

Use the `make help` receipt to see a migrate reference.

## Glossary

It contains trading terms and their definitions and our projects inside terms.

List of terms that you can find here:
- [Arbitrage strategy](#arbitrage)
- [Arbitrage window](#arbitrage-window)
- [Ask price / Bid price](#ask-price--bid-price)
- [Pair name](#pair-name)
- [Pair](#pair)
- [Offer](#offer)
- [Order](#order)

### Pair name
String name of currency tickers pair.
`EURUSD` for example.

### Pair
Representation of one traded currency pair.
Every exchange has pairs list.
Pair = pair + ask/bid price + ask_size/bid_size -> `EURUSD 1.2/1.1 100/1000`

Example:
Pair `EURUSD 1.2/1.1 100/1000` means:
- we can buy 1 EUR for 1.2 USD, in other words is [ask](#ask-price--bid-price)
pair
- we can sell 1 EUR for 1.1 USD, in other words is [bid](#ask-price--bid-price)
pair
- we can buy 100 EUR with this pair
- we can sell 1000 EUR with this pair

[wiki link](https://en.wikipedia.org/wiki/Currency_pair)

### Ask price / Bid price
an ask is lower sale price (seller is exchange) and a bid is higher purchase
price (buyer is exchange).

Example:
`EURUSD 1.2/1.1 (ask/bid)` means that we can buy a EUR for 1.2 USD and sell a
EUR for 1.1 USD.

[wiki link ask](https://en.wikipedia.org/wiki/Ask_price),
[wiki link bid](https://en.wikipedia.org/wiki/Bid_price)

### Offer
Offer to sell or to buy on certain exchange and contains ask/bid pairs.

### Order
Offer that ready to be sent to exchange. The order can be pending, canceled or
completed.

### Arbitrage
The strategy can buy cheaper on one exchange and sell it more expensively on
another exchange. To earn a profit an [arbitrage window](#arbitrage-window)
is used. The strategy places related orders when a window is opened and places
reversed orders when the window is closed. For the detail you can look at
the Arbitrage class.

[wiki link](https://en.wikipedia.org/wiki/Arbitrage)

### Arbitrage window
the temporary exchange rate conditions in which ask price on one exchange is
less than bid price on another exchange.

Example:
An exchange A's aks/bid is 1.2/1.1 and an exchange B's ask/bid is 1.0/0.9, then
spread between the A and the B exchanges is: A.ask - B.bid = 1.1 - 1.0 = 0.1.
and it means, that now arbitrage window is opened.


### Pair limit
It's minimal order amount, set by exchange.
Every pair has it's own limit.
Exchange set it in this way: `BTCUSD: 0.001`. 
This example means, that bot can create order with amount greater then 0.001 BTC.
Bot must have enough BTC or USD balances in this case. 

Temporary note (22.04.18):
Currently we put this limits in config manually.
But the right way is to get this limits from exchanges api.
We'll implement it with #311 github issue.
