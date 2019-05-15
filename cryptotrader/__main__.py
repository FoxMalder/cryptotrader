#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys

import click
import yaml

from .commands import api_group
from .commands import execute_group

assert sys.version_info >= (3, 6)
logger = logging.getLogger(__name__)


@click.command(cls=click.CommandCollection, sources=[execute_group, api_group])  # type: ignore
@click.option('--debug', is_flag=True, default=False)
@click.option('--config',
              type=click.Path(readable=True, exists=True, dir_okay=False, resolve_path=True),
              default="config.yaml",
              required=True)
@click.pass_context
def cli(ctx: click.core.Context, debug: bool, config: str) -> None:
    with open(config) as file:
        ctx.obj['cfg'] = yaml.load(file.read())
    ctx.obj['debug'] = debug


if __name__ == '__main__':
    cli(obj={})
