import logging

import pytest


@pytest.mark.asyncio
async def test_app_execution(app):
    """The app execute without errors."""
    await app.run()
    await app.stop()


@pytest.mark.asyncio
async def test_combat_execution(combat_app, caplog):
    """The app execute without errors and logging messages with level greater than warning."""
    with caplog.at_level(logging.NOTSET):
        await combat_app.run()
        await combat_app.stop()
        for log in caplog.records:
            assert log.levelno < logging.WARNING
