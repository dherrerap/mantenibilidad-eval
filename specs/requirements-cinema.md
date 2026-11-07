# Functional requirements — Cinema ticket sales

Web application for selling tickets to movie theater screenings.

## Main features

- Movie listings: movies currently showing, with their screenings
  (date, time, room).
- Seat selection: seat map per screening, where the user picks one or
  more available seats. The seat selection lives on the client until
  checkout.
- User registration and login. All users have the same role (there are
  no administrators).
- Checkout that simulates a purchase (no real payment gateway needed).
- Persistence of movies, screenings, seats, users and purchases in
  PostgreSQL.
- On startup, the application must ensure the database schema exists
  (by whatever mechanism the technical specification allows) and, if
  there are no movies, insert the initial data.
- Viewing of the user's own purchases.

## Initial data

If the movies table is empty, the backend must insert these movies and
screenings on startup. Screening dates are relative to the startup date
(tomorrow); only the time of day is fixed.

| Movie     | Room | Time  |
| --------- | ---- | ----: |
| Movie One | 1    | 14:00 |
| Movie One | 1    | 20:00 |
| Movie Two | 2    | 16:30 |
| Movie Two | 2    | 21:00 |

Each room has 20 seats, laid out in rows `A` to `D` with seats `1` to `5`
(`A1` … `D5`). Each movie also carries an arbitrary description and
poster image URL.

## Mandatory business logic

- **Seat locking**: a seat selected by a user must be temporarily
  locked for 5 minutes, so that other users cannot select it while the
  checkout is being completed. If the checkout is not completed within
  that time, the seat becomes available again. A user can only lock
  seats that are currently available; a seat locked by another user
  that has not expired is not available.
  - User A locks `A1` → user B trying to lock `A1` is rejected.
  - User A locks `A1` and 5 minutes pass without checkout → user B can
    lock `A1`.
- **Dynamic price per screening**: the ticket price depends on the
  screening start time. Screenings starting before 17:00 cost 6.00 per
  seat; screenings starting at 17:00 or later cost 9.00 per seat. The
  total must reflect this rule automatically and be rounded to 2
  decimals.
  - 2 seats at 14:00 → total of 12.00
  - 2 seats at 20:00 → total of 18.00
  - 3 seats at 16:30 → total of 18.00
- **Availability validation**: a checkout cannot be completed if any of
  the selected seats has already been confirmed by another purchase for
  that same screening, or is locked by another user. If any seat is
  unavailable, no seat is confirmed. When the purchase is confirmed, the
  seats become permanently sold and the user's locks on them are
  released.
  - After a purchase of `A1` and `A2` for a screening, a new checkout
    for `A2` and `A3` on the same screening is rejected and `A3` stays
    available.
  - Seats sold for one screening do not affect the same seats in another
    screening.

## Minimum HTTP interface of the backend

In addition to whatever your user interface needs, the backend must
expose these routes under `/api`, with JSON bodies and responses. They
are used to verify the delivery automatically.

Monetary amounts (`price`, `unitPrice`, `total`) are returned in JSON as
numbers, not strings. Identifiers (`id`, `movieId`, `showtimeId`,
`seatId`) may be integers or UUIDs; clients must treat them as opaque
values. Dates are returned as ISO 8601 strings.

| Route                                                             | Description                                            | Response                                                                               |
| ----------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `POST /api/auth/register` with `{name, email, password}`          | Registers a user                                       | `201`; `409` if the email already exists                                               |
| `POST /api/auth/login` with `{email, password}`                   | Logs in                                                | `200` with `{token}`; `401` if the credentials are invalid                             |
| `GET /api/movies`                                                 | Lists the movies                                       | `200`, array of `{id, title, description, imageUrl}`                                   |
| `GET /api/showtimes`                                              | Lists the screenings                                   | `200`, array of `{id, movieId, startsAt, room, price}`                                 |
| `GET /api/showtimes/:id/seats`                                    | Seat map of a screening                                | `200`, array of `{id, label, status}` with `status` in `available`, `locked`, `sold`   |
| `POST /api/showtimes/:id/quote` with `{seatIds}`                  | Computes the total with the dynamic price              | `200` with `{unitPrice, seats: n, total}`                                              |
| `POST /api/showtimes/:id/lock` with `{seatIds}`                   | Locks seats for 5 minutes (requires a session)         | `200` with `{seatIds, expiresAt}`; `409` if any seat is not available                  |
| `POST /api/checkout` with `{showtimeId, seatIds}`                 | Confirms the purchase (requires a session)             | `201` with `{id, showtimeId, seatIds, total}`; `409` if any seat is unavailable        |
| `GET /api/orders`                                                 | Lists the user's purchases (requires a session)        | `200`, array of `{id, showtimeId, seatIds, total}`                                     |

Protected routes receive the header `Authorization: Bearer <token>`
and respond `401` if a valid token is not sent.

Deliver the complete, working project, ready to run locally.
