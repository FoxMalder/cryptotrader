CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE trade_history (
  id          SERIAL            ,
  time        TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
  exchange    TEXT              NOT NULL,
  pair        TEXT              NOT NULL,
  bid         DOUBLE PRECISION  NULL,
  ask         DOUBLE PRECISION  NULL,
  bid_size    DOUBLE PRECISION  NULL,
  ask_size    DOUBLE PRECISION  NULL
);


SELECT create_hypertable('trade_history', 'time', 'exchange', 4);
-- http://docs.timescale.com/latest/using-timescaledb/schema-management#unique_indexes
ALTER TABLE trade_history ADD PRIMARY KEY (time, exchange, id);
CREATE INDEX ON trade_history (pair, time DESC);
CREATE INDEX ON trade_history (exchange, pair, time DESC);

CREATE TABLE orders (
  uuid           UUID              PRIMARY KEY DEFAULT uuid_generate_v4(),
  status         TEXT              NOT NULL,
  id_on_exchange TEXT              NULL,
  side           TEXT              NOT NULL,
  pair           TEXT              NOT NULL,
  price          DOUBLE PRECISION  NOT NULL,
  base           DOUBLE PRECISION  NOT NULL,
  quote          DOUBLE PRECISION  NOT NULL,
  exchange       TEXT              NOT NULL,
  strategy       TEXT              NULL,
  created_at     TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
  expired_at     TIMESTAMPTZ       NULL,
  executed_at    TIMESTAMPTZ       NULL
);

CREATE INDEX orders_side_idx ON orders (side);
CREATE INDEX orders_pair_idx ON orders (pair);
CREATE INDEX orders_order_id_idx ON orders (id_on_exchange);
