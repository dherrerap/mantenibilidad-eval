# Additional requirements

The following requirements are added to the application already built
for this project. They are in addition to those originally defined and
must be implemented on top of the existing code, without rewriting the
application from scratch.

Where "main catalog entity" is mentioned, it refers to the central
entity of this application's domain (for example, products or
movies/screenings, as applicable).

## Documentation versioning (R2)

All the documentation, models and diagrams of the project (for example,
the README, the entity-relationship/data model, architecture and
component diagrams, sequence diagrams and any other design artifact)
must be generated again from scratch to reflect the application after
these requirements, and delivered under the version label **R2**. The
previous versions must not be edited in place or reused as-is: the R2
set must be a new, complete and consistent set that covers Requirements
1 to 9.

The R2 set lives in the folder `docs/R2/` and must contain at least:

- `docs/R2/README.md`: installation, configuration (including the
  environment variables of these requirements) and run instructions,
  the project structure and the functional assumptions, updated for R2;
- `docs/R2/entity-relationship-model.md`: the entity-relationship model
  of the main PostgreSQL database after these requirements, with the
  same rules as the original one (a Mermaid `erDiagram` plus a brief
  description of each entity, matching exactly the implemented schema).
  The replicas of Requirement 1 are described in a separate section or
  file, not mixed into this diagram.
- `docs/R2/openapi.yaml`: the OpenAPI 3 contract of the whole HTTP API
  after these requirements, with the same rules as the original one
  (every implemented endpoint, the original ones and those of
  Requirements 1 to 9, with its parameters, request bodies and responses,
  errors included).

The original documents (`README.md` at the root,
`docs/entity-relationship-model.md` and `docs/openapi.yaml`) stay as they were; the only change
allowed in the root `README.md` is a line at the top that links to
`docs/R2/README.md`.

## Requirement 1 — Connectivity to additional databases

The application must extend its persistence layer to connect, in
addition to its main PostgreSQL database, to a second, independent
PostgreSQL instance (replica) and a SQL Server instance. The main
catalog entity of the domain must be replicated on these two
additional databases, in read-only mode and synchronized on every
write to the main database.

The application must expose a mechanism that allows reading that same
information interchangeably from the main PostgreSQL database, the
PostgreSQL replica or SQL Server: the query parameter `source` of the
catalog listing (`primary`, `replica` or `sqlserver`; `primary` when it
is absent), with the same response format whatever the source.

- The connection strings are read from the environment variables
  `REPLICA_DATABASE_URL` (PostgreSQL replica) and `SQLSERVER_URL` (SQL
  Server), next to the original `DATABASE_URL`.
- The `docker-compose.yml` at the root starts the three databases.
- The application must start and work with only `DATABASE_URL`: a
  replica that is not configured or not reachable does not stop the
  backend nor the writes on the main database; reading from it returns
  `503` with `error: "SOURCE_UNAVAILABLE"`. An unknown `source` returns
  `422` with `error: "SOURCE_INVALID"`.

## Requirement 2 — Auditing of database objects

An auditing mechanism must be implemented that records, for every
create, update or delete operation on the main entities of the domain:

- who made the change,
- when it was made,
- the values of the record before and after the change.

This requires:

- creating, through scripts or migrations, the corresponding audit
  tables or collections;
- modifying the DTOs and the business logic to capture and persist this
  information on every write operation;
- exposing a way to query the audit history of an entity.

## Requirement 3 — Logical deletion with traceability

Instead of physically deleting the records of the main entities,
deletions must be implemented as logical deletion: the record is marked
as inactive, kept in the database, and the date and the user who
performed the deletion are stored.

All existing query logic in the application (listings, searches,
reports) must exclude deleted records by default, without duplicating
this condition across different parts of the code.

This requires:

- modifying the database scripts (adding status and deletion-audit
  columns);
- modifying the DTOs;
- modifying the data access logic in a centralized way.

## Requirement 4 — Role-based access control

This requirement **replaces** the rule of the original specification
that all users have the same role.

The application must incorporate at least two user roles:
administrator and regular user. The management operations on the main
catalog entities (create, edit or delete) must be restricted
exclusively to the administrator role; the remaining operations
(browsing the catalog, purchasing) remain available to both roles.

- `POST /api/auth/register` always creates a regular user; a role cannot
  be chosen at registration.
- At startup the backend ensures that an administrator exists with the
  credentials of the environment variables `ADMIN_EMAIL` and
  `ADMIN_PASSWORD` (when both are set), and an auditor (Requirement 5)
  with `AUDITOR_EMAIL` and `AUDITOR_PASSWORD`. No other mechanism to
  grant roles is required.

This requires:

- modifying the database scripts (adding the role attribute to the user
  or a roles table/collection);
- modifying the user and authentication DTOs;
- modifying the business logic to incorporate authorization checks in
  every restricted operation.

## Requirement 5 — Auditor role (read-only)

The application must incorporate an additional user role: auditor. An
auditor can view everything but cannot modify anything.

- **Read access**: the auditor can read all the information exposed by
  the application, including the catalog, the audit history of any
  entity (Requirement 2), logically deleted records (Requirement 3),
  and the orders or purchases of all users.
- **No writes**: the auditor cannot perform any operation that creates,
  modifies or deletes data, including management of the main catalog
  entities, purchases or checkout, seat locking, order status changes
  and any other write operation. Such attempts must be rejected with
  `403`, and the user interface must not offer those actions to the
  auditor.
- **Side-effect-free reads**: viewing information never alters the
  stored data.

This requires:

- modifying the database scripts (adding the auditor value to the role
  attribute or roles table/collection);
- modifying the user and authentication DTOs;
- modifying the business logic so that authorization checks are
  enforced centrally (for example, in a single middleware or policy
  that rejects every write operation for this role), rather than
  repeated operation by operation.

## HTTP interface of Requirements 1 to 5

These routes complete the minimum HTTP interface and are used to verify
the delivery automatically. Rejections use the error body of the
conventions below (`{ "error": "<CODE>", "message": "<text>" }`):
`401` without a valid session, `403` with `error: "FORBIDDEN"` when the
role is not allowed, `404` when the record does not exist or is
logically deleted.

The catalog of each domain is: **ecommerce** `/api/products` (the
product); **cinema** `/api/movies` (the movie; screenings keep their
original routes).

| Route | Description | Who | Response |
| ----- | ----------- | --- | -------- |
| `GET /api/auth/me` | The user of the session | any user | `200` with `{id, name, email, role}`, `role` in `user`, `admin`, `auditor` |
| `GET <catalog>?source=primary\|replica\|sqlserver` | Listing from the chosen database (Req. 1) | anyone | `200`, same format as the original listing |
| `POST <catalog>` | Creates a record of the catalog | admin | `201` with the record |
| `PUT <catalog>/:id` | Edits it | admin | `200` with the record |
| `DELETE <catalog>/:id` | Logical deletion (Req. 3) | admin | `204`; it disappears from every listing |
| `GET <catalog>?includeDeleted=true` | Listing including the deleted ones, with `deletedAt` and `deletedBy` | admin, auditor | `200`; `403` for a regular user |
| `GET /api/audit?entity=<name>&id=<id>` | Audit history of a record (Req. 2), oldest first | admin, auditor | `200`, array of `{action, entity, entityId, userId, at, before, after}`; `action` in `create`, `update`, `delete` |
| `GET /api/orders` | For the auditor, the orders or purchases of **all** users | auditor | `200`; regular users keep seeing only their own |

The names of `entity` are those of the catalog (`product` or `movie`),
`coupon` (Requirement 6) and `order` (cancellations, Requirement 7).
`before` is `null` for a creation and `after` keeps the record as it was
left by a deletion.

---

# Additional business-logic requirements

Requirements 6 to 9 extend the business rules of the application. Like
the previous ones, they must be implemented on top of the existing code,
without rewriting it, and they must keep working together with
Requirements 1 to 5.

## Conventions shared by Requirements 6 to 9

- **Existing rules keep working.** The rules and numeric examples of the
  original specification remain valid, except where a requirement below
  explicitly says that a value changes.
- **Error responses.** Every rejection caused by a rule in this section
  returns a JSON body `{ "error": "<CODE>", "message": "<text>" }`. The
  `CODE` values are fixed by each requirement and are used to verify the
  delivery automatically. Use `422` when the request itself is invalid
  and `409` when it conflicts with the current state of the data.
- **Amounts** are returned as JSON numbers and rounded to 2 decimals.
- **Date of the cinema screenings.** The weekend surcharge of
  Requirement 8 depends on the day, and the seed screenings are dated
  "tomorrow". The environment variable `SEED_DATE` (`YYYY-MM-DD`) fixes
  the date of the seed screenings when the database is seeded (default:
  tomorrow), so that the examples can be verified on any day. Examples
  without a day are on a weekday.
- **Calculation order.** Whenever more than one rule affects the total,
  the order is: base price → price rules of Requirement 8 → coupon of
  Requirement 6 → (ecommerce only) shipping of Requirement 8.
- **Interaction with Requirements 1 to 5.**
  - Coupons and cancellations are main entities of the domain for the
    purposes of auditing (Requirement 2): every create, update or delete
    on them must be audited.
  - Coupons are never physically deleted (Requirement 3).
  - Creating, editing or deleting coupons is restricted to the
    administrator (Requirement 4). Applying a coupon during a purchase
    and cancelling one's own order are available to the regular user.
  - The auditor (Requirement 5) can list coupons and see cancelled
    orders, but receives `403` when trying to apply a coupon in a
    checkout or to cancel an order.

## Requirement 6 — Discount coupons

The application must support discount coupons that a user can apply to a
purchase.

A coupon has:

- `code`: unique, case-insensitive (`SAVE10` and `save10` are the same
  coupon);
- `type`: `percent` or `fixed`;
- `value`: a percentage between 1 and 100 for `percent`, or an amount
  greater than 0 for `fixed`;
- `expiresAt`: ISO 8601 date after which the coupon is no longer valid;
- `maxUses`: maximum number of confirmed purchases that may use it;
- `usedCount`: number of confirmed purchases that have used it.

**Rules**

- A purchase can include at most one coupon, sent in the optional field
  `couponCode` of the quote and checkout requests. Without
  `couponCode`, the behavior is exactly the same as before.
- The coupon discount is computed on the subtotal that results from the
  price rules (see the calculation order above) and can never exceed 50%
  of that subtotal. If the computed discount is higher, it is reduced to
  that cap.
- Quoting never consumes a use of the coupon. A use is consumed only
  when a checkout is confirmed, in the same operation that confirms it.
  A rejected checkout consumes nothing.
- If an order is cancelled (Requirement 7), the use of the coupon that
  order consumed is returned.
- The order stores the coupon code and the discount amount applied.

**Rejections**

| Situation                              | Response | `error`             |
| -------------------------------------- | -------- | ------------------- |
| Unknown code                           | `422`    | `COUPON_INVALID`    |
| Coupon past its `expiresAt`            | `422`    | `COUPON_EXPIRED`    |
| `usedCount` already equals `maxUses`   | `409`    | `COUPON_EXHAUSTED`  |

**HTTP interface**

| Route                                    | Description                              | Response                                    |
| ---------------------------------------- | ---------------------------------------- | ------------------------------------------- |
| `POST /api/coupons` with `{code, type, value, expiresAt, maxUses}` | Creates a coupon (administrator) | `201` with the coupon; `409` if the code exists; `403` if not an administrator |
| `GET /api/coupons`                       | Lists the coupons (administrator, auditor) | `200`, array of coupons with `usedCount`  |
| `DELETE /api/coupons/:id`                | Deactivates a coupon (administrator)     | `204`; the coupon is kept but can no longer be applied (`COUPON_INVALID`) |

The quote and checkout responses add the fields `subtotal` and
`discount`. `total` is always the final amount to pay. Without a coupon,
`discount` is `0`.

**Ecommerce**

- `POST /api/cart/quote` and `POST /api/checkout` accept `couponCode`
  next to `items`. The quote response is
  `{lines, subtotal, discount, total}` and the checkout response is
  `{id, status, subtotal, discount, total}`. (The `shipping` field of
  Requirement 8 is added to both.)
- The coupon is applied on the sum of the order lines.
- Examples (before the shipping of Requirement 8):
  - 3 × T-shirt + 1 × Book (subtotal 47.00) with a 10% coupon →
    discount 4.70, total 42.30.
  - The same cart with a fixed coupon of 5.00 → discount 5.00, total
    42.00.
  - The same cart with a fixed coupon of 30.00 → discount capped at
    23.50, total 23.50.

**Cinema**

- `POST /api/showtimes/:id/quote` and `POST /api/checkout` accept
  `couponCode` next to `seatIds`. The quote response is
  `{unitPrice, seats, subtotal, discount, total}` and the checkout
  response is `{id, showtimeId, seatIds, subtotal, discount, total}`.
- The coupon is applied on the total of the seats.
- Examples:
  - 2 seats at 20:00 on a weekday (subtotal 18.00) with a 10% coupon → discount
    1.80, total 16.20.
  - 3 seats at 16:30 on a weekday (subtotal 18.00) with a fixed coupon of 12.00 →
    discount capped at 9.00, total 9.00.

## Requirement 7 — Order cancellation with inventory restitution

A user can cancel their own orders. Cancelling releases what the order
had reserved, atomically: either everything is restored or nothing is.

**Common rules**

- Only the owner of the order can cancel it. Cancelling an order that
  belongs to another user, or that does not exist, returns `404`.
- Cancelling an order that is already cancelled returns `409` with
  `error: "ORDER_ALREADY_CANCELLED"`.
- Cancelling consumes no extra resource: it returns the use of the
  coupon the order consumed (Requirement 6), if any.
- A cancelled order remains in the order list with the status
  `cancelled`, and its record is kept (Requirement 3).
- A cancelled order does not count for any limit of Requirement 9.

**Ecommerce**

- The order status machine is extended. The allowed transitions are now:
  `pending → paid`, `paid → shipped`, `pending → cancelled` and
  `paid → cancelled`. `shipped` and `cancelled` are final states.
  Everything else keeps being rejected with `409`.
- Cancelling is done with the existing route
  `PATCH /api/orders/:id/status` with `{status: "cancelled"}`.
  A `shipped` order cannot be cancelled: `409` with
  `error: "ORDER_NOT_CANCELLABLE"`.
- When an order is cancelled, the stock of every product in it is
  increased by the quantity of its line.
- Example: with Mug at stock 2, buying 2 Mug leaves stock 0; cancelling
  that order leaves stock 2; cancelling it again is rejected and the
  stock stays at 2.

**Cinema**

- New route: `POST /api/orders/:id/cancel` → `200` with
  `{id, showtimeId, seatIds, total, status}` and `status` equal to
  `cancelled`.
- `GET /api/orders` now returns `{id, showtimeId, seatIds, total,
  status}` where `status` is `confirmed` or `cancelled`.
- A purchase can be cancelled only until the cancellation window before
  the start of the screening. The window is 2 hours and must be
  configurable through the environment variable
  `CANCELLATION_WINDOW_HOURS` (default `2`). Outside the window the
  response is `409` with `error: "CANCELLATION_WINDOW_CLOSED"`.
- When a purchase is cancelled, its seats become `available` again for
  that screening and can be locked or bought by any user.
- Example: user A buys `A1` and `A2`; user B cannot lock `A1`. A cancels
  the purchase; B can now lock `A1`.

## Requirement 8 — Changes to the pricing rules

The pricing rules of the original specification are modified as
follows. The original examples must keep passing for the parts that do
not change.

**Ecommerce**

- **Tiered volume discount** (replaces the single 10% rule). The
  discount applies to the whole line total:
  - 1 to 2 units: no discount;
  - 3 to 9 units: 10%;
  - 10 or more units: 20%.
- **Shipping cost**. After the volume discount, if the order subtotal
  (sum of lines) is lower than 50.00, a shipping cost of 5.00 is added;
  otherwise shipping is 0. The coupon of Requirement 6 does not change
  whether shipping applies, and shipping is not discounted by it.
  Calculation: `total = subtotal − discount + shipping`.
- The quote and checkout responses add the field `shipping`, and the
  orders list returns `{id, status, total}` with `total` including
  shipping. The `lineTotal` of each line does not include shipping.
- Examples (no coupon):
  - 2 × T-shirt → line 20.00, shipping 5.00, total 25.00.
  - 3 × T-shirt → line 27.00, shipping 5.00, total 32.00.
  - 5 × T-shirt → line 45.00, shipping 5.00, total 50.00.
  - 10 × T-shirt → line 80.00 (100.00 − 20%), shipping 0, total 80.00.
  - 3 × T-shirt + 1 × Book → subtotal 47.00, shipping 5.00, total
    52.00.
  - 3 × T-shirt + 2 × Book → subtotal 67.00, shipping 0, total 67.00.

**Cinema**

- **Weekend surcharge**. Screenings that start on a Saturday or a Sunday
  (in the time zone of the server) add 1.00 per seat to the price of the
  original rule. `unitPrice` and the `price` of `GET /api/showtimes`
  include the surcharge.
- **Group discount**. Purchases of 4 or more seats get a 10% discount
  on the seats total (after the surcharge).
- Calculation: `subtotal = unitPrice × seats`; the group discount and
  then the coupon of Requirement 6 are applied to it. The quote response
  is `{unitPrice, seats, subtotal, discount, total}` where `discount`
  adds up the group discount and the coupon discount, and the field
  `groupDiscount` is also returned with the group part.
- Examples (no coupon):
  - 2 seats at 14:00 on a weekday → total 12.00 (unchanged).
  - 2 seats at 20:00 on a Saturday → unit price 10.00, total 20.00.
  - 4 seats at 20:00 on a weekday → subtotal 36.00, group discount
    3.60, total 32.40.
  - 4 seats at 16:30 on a Sunday → unit price 7.00, subtotal 28.00,
    group discount 2.80, total 25.20.

## Requirement 9 — Purchase limits and sales window

The application must enforce purchase limits. All of them must be
enforced in every operation they apply to, with the same behavior and
the same error codes.

**Ecommerce**

| Limit                                                                                                  | Applies to                 | Response | `error`                  |
| ------------------------------------------------------------------------------------------------------ | -------------------------- | -------- | ------------------------ |
| At most 20 units in total per order                                                                    | quote, checkout            | `422`    | `MAX_UNITS_PER_ORDER`    |
| At most 12 units of the same product per user within a rolling 24 hours, counting the orders that are not cancelled and the current order | checkout | `409`    | `PRODUCT_LIMIT_24H`      |

- The 24-hour window is measured from the creation time of each earlier
  order. Cancelled orders (Requirement 7) are not counted.
- Example: a user who bought 8 T-shirts in the last 24 hours can buy 4
  more, but not 5. If they cancel the first order, they can buy 12.

**Cinema**

| Limit                                                                                                   | Applies to              | Response | `error`                  |
| ------------------------------------------------------------------------------------------------------- | ----------------------- | -------- | ------------------------ |
| At most 6 seats per purchase                                                                            | quote, lock, checkout   | `422`    | `MAX_SEATS_PER_PURCHASE` |
| A user can hold at most 6 seats actively locked at the same time, counting all screenings and the seats of the current request | lock       | `409`    | `LOCK_LIMIT_EXCEEDED`    |
| Sales close 15 minutes before the start of the screening                                                | lock, checkout          | `409`    | `SALES_CLOSED`           |

- The sales cutoff must be configurable through the environment variable
  `SALES_CUTOFF_MINUTES` (default `15`), so that it can be verified
  without waiting for the real time. With `SALES_CUTOFF_MINUTES` large
  enough to cover the seed screenings, lock and checkout return
  `SALES_CLOSED` while the seat map and the quote keep working.
- An expired lock, a lock released by a checkout, and the seats of a
  cancelled purchase (Requirement 7) do not count toward the lock limit.
- Example: a user with 4 seats locked can lock 2 more, but not 3.
