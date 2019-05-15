import asyncio

import telepot.aio

from cryptotrader.common import Reporter


class TelegramReporter(Reporter):

    def __init__(self, channel, token):
        self.channel = channel
        self.bot = telepot.aio.Bot(token)

    def report(self, message):
        message = message.replace('_', '\_')
        asyncio.ensure_future(self.bot.sendMessage(
            self.channel,
            message,
            parse_mode='Markdown',
        ))
