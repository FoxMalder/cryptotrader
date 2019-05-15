import logging
from unittest.mock import Mock

import pytest

from cryptotrader.logging import TelegramHandler


@pytest.fixture()
def loggers(request):
    logger = logging.getLogger(__name__)
    tg = logging.getLogger('tg')
    stream_handler = logging.StreamHandler()
    tg_handler = TelegramHandler('', '')

    stream_handler.emit = Mock(return_value=None)  # type: ignore
    tg_handler.reporter.report = Mock(return_value=None)  # type: ignore

    tg.addHandler(tg_handler)
    logger.addHandler(stream_handler)

    def finalize():
        """Help to avoid the logger global state and cleanup handlers."""
        tg.handlers = []
        logger.handlers = []
    request.addfinalizer(finalize)
    return tg, logger


def test_stream_emit(loggers, caplog):
    msg = 'test'
    tg, logger = loggers
    tg_handler = tg.handlers[0]
    stream_handler = logger.handlers[0]

    logger.info(msg)

    assert len(caplog.records) == 1
    assert stream_handler.emit.called
    assert not tg_handler.reporter.report.called


def test_report_emit(loggers, caplog):
    msg = 'test'
    tg, logger = loggers
    tg_handler = tg.handlers[0]
    stream_handler = logger.handlers[0]

    tg.info(msg)

    assert len(caplog.records) == 1
    assert not stream_handler.emit.called
    assert tg_handler.reporter.report.called
    for record in caplog.records:
        assert record.msg == msg
