import enum

# @todo #326:60m/DEV Create arch for custom typing.

# Balances str key is pair name. Every exchange has it's own pair format.
# "BTCUSD" - for Bitfinex, and it's bot common format too.
# "USD-BTC" - for Bittrex.
# Right now Balances dict stores pair names in exchange inner format.
FOREVER_TASK_TIMEOUT = 8.0  # in seconds
# price can not totally change (over 20%) until this timeout
PRICE_LONG_CHANGE_TIMEOUT = 60.0

WEBSOCKET = 'websocket'
REST = 'rest'
SUBSCRIBE_PAIR = 'subscribe_pair'

DEFAULT_PAIR = 'DEFAULT'

MAX_SUM = 10**32  # in any currency. For easy comparing
# min amount in any currency.
# Temporary decision until #331 finished.
MIN_SUM = MIN_AMOUNT = 1e-4

# offer sides
ASK = 'ask'
BID = 'bid'
OFFER_SIDES = [ASK, BID]

# order sides
BUY = 'buy'
SELL = 'sell'
ORDER_SIDES = [BUY, SELL]
# factor for balance precalculation
ORDER_SIDE_FACTOR_MAP = {
    BUY: -1,
    SELL: 1,
}
get_factor = ORDER_SIDE_FACTOR_MAP.get

# order types
MARKET = 'market'
LIMIT = 'limit'
ORDER_TYPES = [MARKET, LIMIT]

# @todo #70 - Use enum instead of simple consts

# order statuses
CREATED = 'created'
PLACED = 'placed'
REJECTED = 'rejected'  # order rejected by exchange
CANCELLED = 'cancelled'  # order cancelled by our bot request
FULFILLED = 'fulfilled'

OFFER_ORDER_SIDES_MAP = {ASK: BUY, BID: SELL}
ORDER_OFFER_SIDES_MAP = {BUY: ASK, SELL: BID}

PING = 'ping'
ORDER_NEW = 'order_new'
ORDER_ADD_OK = 'order_add_ok'
ORDER_EXPIRED = 'order_expired'
ORDER_ADD_ERROR = 'order_add_error'
BALANCE_CHANGED = 'balance_changed'
START = 'start'
FETCH_BALANCES_ERROR = 'fetch_balances_error'


EXTRA_MESSAGE = '\nExtra data from exchange: {message}'


class EMOJI(str, enum.Enum):
    WHITE_CIRCLE = b'\xE2\x9A\xAA'.decode()
    BLUE_CIRCLE = b'\xF0\x9F\x94\xB5'.decode()
    RED_CIRCLE = b'\xF0\x9F\x94\xB4'.decode()
    WARNING_SIGN = b'\xE2\x9A\xA0'.decode()
    CHECK_MARK = b'\xE2\x9C\x85'.decode()
    SOS = b'\xF0\x9F\x86\x98'.decode()
    MEGAPHONE = b'\xF0\x9F\x93\xA3'.decode()


TELEGRAM_REVERSE_ORDER_NEW = (
    '*Strategy {name} Report*\n'
    '\n'
    'Reversed *order local id*: {order.uuid}\n'
    'Order *side*: {order.side}\n'
    'Reversed *order local id*: {order.uuid}\n'
    '*Info*: ticker pair *{order.pair}*\n'
    '*Volume*: {order.quote.amount:.4f}/{order.base.amount:.4f}.\n'
    '*Price*: ({order.price}) on {order.exchange.name},'
)

TELEGRAM_REVERSE_ORDERS_SUCCESS = (
    '*Strategy {name} Report*\n'
    '\n'
    'New reversed orders pair.\n'
    'Original *buy_order local id*: {buy_order.uuid}\n'
    'Original *sell_order local id*: {sell_order.uuid}\n'
    'Reversed *buy_order local id*: {buy_order.uuid}\n'
    'Reversed *sell_order local id*: {sell_order.uuid}\n'
    '*Info*: ticker pair *{buy_order.pair}*\n'
    '*Final profit*: {profit:.4f}% ({bonus:.4f} per coin)\n'
    '*Volume*: {quote:.4f}/{base_avg:.4f}.\n'
    '*Price* for reversed orders:'
    'bid ({sell_order.price}) on {sell_order.exchange.name},'
    ' ask ({sell_order.price}) on {sell_order.exchange.name}.\n'
)

TELEGRAM_ARBITRAGE_ORDER_ERROR = (
    '*Strategy {name} Report*\n'
    '\n'
    '*Local order id*: {local_order_id}\n'
    '*Info*: place order error — {pair}/{side}\n'
    '*Exchange*: {exchange}\n'
    '*Volume*: {quote}\n'
    '*Price*: {price}\n'
)

TELEGRAM_ARBITRAGE_ORDER_OK = (
    '*Strategy {name} Report*\n'
    '\n'
    '*Local order id*: {local_order_id}\n'
    '*Info*: order {local_order_id} successful placed — {pair}/{side}\n'
    '*Exchange*: {exchange}\n'
    '*Volume*: {quote}\n'
    '*Price*: {price}\n'
)
