# Functional requirements — E-commerce

E-commerce web application.

## Main features

- Product catalog: image, name, price, description and available stock.
- Shopping cart: add, remove and change quantities. The cart lives on
  the client until checkout.
- User registration and login. All users have the same role (there are
  no administrators).
- Checkout that simulates a purchase (no real payment gateway needed).
- Persistence of products, users and orders in PostgreSQL.
- On startup, the application must ensure the database schema exists
  (by whatever mechanism the technical specification allows) and, if
  there are no products, insert the initial data.
- Viewing of the user's own orders with their current status.

## Initial data

If the products table is empty, the backend must insert these products on
startup:

| Name    | Price | Stock |
| ------- | ----: | ----: |
| T-shirt | 10.00 |    20 |
| Mug     |  5.00 |     2 |
| Book    | 20.00 |    50 |

Each product also carries an arbitrary description and image URL.

## Mandatory business logic

- **Volume discount**: if a user adds 3 or more units of the same
  product to the cart, a 10% discount applies to that order line (on
  the line total, not just on the additional units). The calculation
  must be reflected in the cart before checkout. Amounts are rounded to
  2 decimals.
  - 2 × T-shirt → line of 20.00
  - 3 × T-shirt → line of 27.00 (30.00 − 10%)
  - 5 × T-shirt → line of 45.00 (50.00 − 10%)
  - 3 × T-shirt + 1 × Book → total of 47.00
- **Stock validation**: a checkout cannot be completed if the requested
  quantity of any product exceeds the stock available at that moment.
  If any product falls short, no stock is deducted for any of them.
  When the purchase is confirmed, the product's stock must be deducted.
  - With Mug at stock 2: buying 2 Mug is valid and leaves the stock at
    0; buying 3 Mug is rejected and the stock stays at 2.
- **Order statuses**: each order is created in status `pending` and can
  only advance `pending → paid → shipped`, one step at a time and
  without going back. Any authenticated user can advance the status of
  their own orders (it is a simulation). The user must be able to see
  the current status of their previous orders and cannot see other
  users' orders.

## Minimum HTTP interface of the backend

In addition to whatever your user interface needs, the backend must
expose these routes under `/api`, with JSON bodies and responses. They
are used to verify the delivery automatically.

Monetary amounts (`price`, `unitPrice`, `lineTotal`, `total`) are
returned in JSON as numbers, not strings. Identifiers (`id`,
`productId`) may be integers or UUIDs; clients must treat them as opaque
values.

| Route                                                          | Description                                    | Response                                                                   |
| -------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------- |
| `POST /api/auth/register` with `{name, email, password}`       | Registers a user                               | `201`; `409` if the email already exists                                   |
| `POST /api/auth/login` with `{email, password}`                | Logs in                                        | `200` with `{token}`; `401` if the credentials are invalid                 |
| `GET /api/products`                                            | Lists the catalog                              | `200`, array of `{id, name, price, description, imageUrl, stock}`          |
| `POST /api/cart/quote` with `{items: [{productId, quantity}]}` | Computes the cart with the volume discount     | `200` with `{lines: [{productId, quantity, unitPrice, lineTotal}], total}` |
| `POST /api/checkout` with `{items: [{productId, quantity}]}`   | Confirms the purchase (requires a session)     | `201` with `{id, status, total}`; `409` if stock is insufficient           |
| `GET /api/orders`                                              | Lists the user's orders (requires a session)   | `200`, array of `{id, status, total}`                                      |
| `PATCH /api/orders/:id/status` with `{status}`                 | Advances the order status (requires a session) | `200`; `409` if the transition is not valid                                |

Protected routes receive the header `Authorization: Bearer <token>`
and respond `401` if a valid token is not sent.

Deliver the complete, working project, ready to run locally.
