class CryptobotException(BaseException):
    def __init__(self, message=''):
        self.message = message

    def __str__(self, *args, **kwargs):
        return self.message


class ConfigError(CryptobotException):
    def __init__(self, message):
        self.message = message

    def __str__(self, *args, **kwargs):
        return (
            f'Config error. {self.message}.'
        )


class ExchangePlaceOrderException(CryptobotException):
    def __init__(self, extra):
        self.extra = extra


class NoSuchExchangeError(CryptobotException):
    def __init__(self, exchange_name):
        self.exchange_name = exchange_name

    def __str__(self, *args, **kwargs):
        return (
            f'Exchange "{self.exchange_name}" is not supported.'
            ' Check "exchanges" section in config file.'
        )


class WebsocketAuthError(CryptobotException):
    def __init__(self, base_url):
        # instead of exchange_name
        self.base_url = base_url

    def __str__(self, *args, **kwargs):
        return (
            'Auth via websocket failed. Connection lost.'
            f' base_url: {self.base_url}.'
        )


class QueueEmpty(CryptobotException):
    def __str__(self, *args, **kwargs):
        return (
            'Tried to pop from empty queue.'
        )


class InconsistentDBDataError(CryptobotException):
    pass


class FetchPairError(CryptobotException):
    def __init__(self, pair, response):
        # instead of exchange_name
        self.pair = pair
        self.response = response

    def __str__(self, *args, **kwargs):
        return (
            f'Failed to fetch pair {self.pair}. Exchange response {self.response}.'
        )
