# Exchanges module

## Orders with fixed ask/bid
Here we'll see how exchanges process orders with fixed ask/bid.

If `REAL_BID >= ORDER_BID` and `REAL_ASK <= ORDER_ASK` order will be executed on ORDER_ASK and ORDER_BID, else `REAL_BID < ORDER_BID` or `REAL_ASK > ORDER_ASK`, order willn't executed
