import logging

from cryptotrader import const
from cryptotrader.report import TelegramReporter


class EMOJIFormatter(logging.Formatter):

    level_emoji_map = {
        logging.DEBUG: const.EMOJI.WHITE_CIRCLE,
        logging.INFO: const.EMOJI.BLUE_CIRCLE,
    }

    def format(self, record):
        emoji = self.level_emoji_map.get(record.levelno, const.EMOJI.RED_CIRCLE)
        record.msg = f'{emoji} {record.msg}'
        return super().format(record)


class TelegramHandler(logging.Handler):

    def __init__(self, channel, token, **kwargs) -> None:
        self.reporter = TelegramReporter(channel, token)
        super(TelegramHandler, self).__init__(**kwargs)

    def emit(self, record):
        self.reporter.report(self.format(record))
