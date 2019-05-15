# -*- coding: utf-8 -*-
import asyncio
import logging

from attrdict import AttrDict
import click

logger = logging.getLogger(__name__)


@click.group()
def api_group():
    pass


@api_group.command()
@click.pass_context
def api(ctx, test):
    env = AttrDict()
    env.cfg = ctx.obj['cfg']
    loop = env.loop = asyncio.get_event_loop()
    loop.run_forever()
