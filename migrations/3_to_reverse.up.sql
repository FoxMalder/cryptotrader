-- without indexes for queue speed
CREATE TABLE order_pairs (
  uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  left_order_uuid UUID NOT NULL REFERENCES orders (uuid),
  right_order_uuid UUID NOT NULL REFERENCES orders (uuid),
  time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
