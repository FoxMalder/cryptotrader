import urllib

import flask
import sqlalchemy as sa
import yaml


def get_db(dsn):
    engine = sa.create_engine(dsn)
    meta = sa.MetaData()
    engine.tables = {
        'orders': sa.Table('orders', meta, autoload=True, autoload_with=engine),
        'trade_history': sa.Table('trade_history', meta, autoload=True, autoload_with=engine),
    }
    engine.order_directions = {'asc': sa.asc, 'desc': sa.desc}
    return engine

app = flask.Flask(__name__)
with open('config.yaml') as file_:
    config_data = yaml.load(file_.read())
    app.config.update(**config_data)
db = get_db(app.config['dsn'])


@app.context_processor
def inject_front():
    return {
        'front': {
            'css': {
                'bootstrap': flask.url_for('static', filename='css/bootstrap.css'),
                'panel': flask.url_for('static', filename='css/panel.css'),
            },
            'js': {
                'jquery': flask.url_for('static', filename='js/jquery-3.3.1.min.js'),
                'panel': flask.url_for('static', filename='js/main.js'),
            },
        },
    }


@app.route('/')
def index():
    return flask.render_template('base.html')


@app.route('/orders')
def orders():
    table = db.tables['orders']
    orders = select_entities(table)
    return flask.render_template(
        'base.html',
        h1='Orders table',
        columns=table.c,
        table_meta=get_table_meta(table),
        items=orders,
    )


@app.route('/trades')
def trades():
    table = db.tables['trade_history']
    trades = select_entities(table)
    return flask.render_template(
        'base.html',
        h1='Trade history table',
        columns=table.c,
        table_meta=get_table_meta(table),
        items=trades,
    )


@app.route('/orders/table')
def orders_table():
    return flask.render_template(
        'table_body.html',
        items=select_entities(db.tables['orders']),
    )


@app.route('/trades/table')
def trades_table():
    return flask.render_template(
        'table_body.html',
        items=select_entities(db.tables['trade_history']),
    )


def get_table_meta(table):
    base_url = f'{flask.request.script_root}{flask.request.path}'

    def get_pagination_url(value_to):
        query = flask.request.args.to_dict()
        query.update(value_to)
        return f'{base_url}?{urllib.parse.urlencode(query)}'

    offset = int(flask.request.args.get('offset', 0))
    limit = int(flask.request.args.get('limit', 10))
    with db.connect() as conn:
        total_rows = conn.execute(
            sa.select([sa.func.count()]).select_from(table)
        ).scalar()

    if offset >= limit:
        prev_url = get_pagination_url({'offset': offset - limit})
    else:
        prev_url = None

    if offset + limit < total_rows:
        next_url = get_pagination_url({'offset': offset + limit})
    else:
        next_url = None

    def get_column_url(column):
        if order_by == column.name:
            direction = reverse_order_direction
        else:
            direction = order_direction
        return f'{base_url}?order_direction={direction}&order_by={column.name}'

    order_by = flask.request.args.get('order_by', None)
    order_direction = flask.request.args.get('order_direction', 'asc')
    reverse_order_direction = 'desc' if order_direction == 'asc' else 'asc'

    return {
        'prev_url': prev_url,
        'next_url': next_url,
        'column_urls': {
            column.name: get_column_url(column)
            for column in table.c
        },
    }


def select_entities(table):
    """Only for db usage example."""
    with db.connect() as conn:
        order_field = getattr(
            table.c,
            flask.request.args.get('order_by', list(table.c)[0].name)
        )
        order_fn = db.order_directions[flask.request.args.get('order_direction', 'asc')]
        order_by = order_fn(order_field)
        offset = int(flask.request.args.get('offset', 0))
        limit = int(flask.request.args.get('limit', 10))
        return conn.execute(
            sa.select([table])
            .limit(limit)
            .offset(offset)
            .order_by(order_by)
        ).fetchall()
