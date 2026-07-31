# Inventory reservation

`UNLIMITED` SKUs do not create stock reservations. `FINITE` and
`SERVICE_CAPACITY` SKUs use an inventory row containing capacity, reserved, sold,
safety-stock and controlled-oversell values.

Creation locks the inventory row with `SELECT … FOR UPDATE`, recalculates available
quantity, increments `reserved_quantity`, creates the reservation and writes a
movement in one transaction. This guarantees that two requests for the final unit
cannot both succeed.

Confirmation is idempotent: the first confirmation moves quantity from reserved to
sold, while later calls return the existing confirmed state. Release and expiry are
also idempotent. Confirmed reservations cannot use the normal release path. Celery
Beat expires active inventory and coupon reservations every minute.

Manual capacity changes require a reason and expected version. Capacity can never
fall below sold plus active reservations plus safety stock.
