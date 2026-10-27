# Technical specification — Level 3

You are going to build a **web application**.

## Mandatory stack

You must use the PERN stack:

- PostgreSQL as the relational database
- Express.js for the backend
- React for the frontend
- Node.js as the server runtime

You may use JavaScript or TypeScript, at your discretion.

## Architectural style

The application must be a **monolith organized in layers** (microservices,
serverless architectures and native mobile applications are not
accepted).

## Delivery conditions

- At the project root there must be `backend/` and `frontend/` folders,
  each with its own `package.json`.
- Each folder must be installable with `npm install` and runnable with
  `npm start`.
- The backend must take the port it listens on from the `PORT`
  environment variable and the PostgreSQL connection string from the
  `DATABASE_URL` environment variable.
- At the root there must be a `docker-compose.yml` that starts the
  PostgreSQL instance needed to run the application.
- At the root there must be a `README.md` with the installation and run
  instructions and the project structure.

## Expected quality attributes

It is important that the project be easy to maintain in the future:

- It must be possible to quickly understand what each part of the code does.
- It must be possible to modify a feature without breaking others.
- It must be possible to add automated tests over the business logic.

Avoid concentrating too much logic in a single file or module, and
clearly separate the system's responsibilities (for example, business
logic from data persistence and from the user interface).

## Architectural guidelines

### 1. Structure and modularity

Implement the presentation, business logic and data access layers with
strict separation of responsibilities. Each module must have a single
responsibility (SOLID's single responsibility principle) and a clear
communication interface toward the other layers, with no direct jumps
between non-adjacent layers. Apply these patterns:

- **Controller – Service – Repository** in the backend. Controllers only
  translate HTTP. Services (Service Layer) concentrate the business
  logic. Repositories are the only point of data access.
- **DTO and Mapper**: the layers communicate through transfer objects;
  ORM entities must not leave the repository layer.
- **Express middleware chain** for authentication, input validation and
  centralized error handling.
- In the frontend, separate presentation components from logic (custom
  hooks), centralize HTTP calls in a single API client and manage the
  cart state with Context.

### 2. Dependencies and integration

- Use a relational ORM (Sequelize) and manage the schema through
  versioned migrations.
- **Repository with contract**: the business layer defines the
  repository interface and the data layer implements it. Wire the
  dependencies through constructor injection from a single composition
  root.
- **Unit of Work**: the checkout (validate stock, deduct it and create
  the order) runs in a single transaction, managed through an abstraction
  of your own.
- The business logic must not depend directly on Express, on the ORM or
  on `pg`.

### 3. Domain rules

- **State**: model the order statuses as an explicit state machine, with
  the valid transitions defined in a single place.
- **Strategy**: encapsulate the volume discount as an interchangeable
  pricing policy.

### 4. Use of design patterns that facilitate code maintainability

Apply design patterns as a means to make the code easier to maintain,
not as an end in themselves:

- Use a pattern only where it solves a concrete maintainability problem
  (for example: isolating a rule that is likely to change, decoupling
  the business logic from an external library, or making a module
  testable in isolation).
- Prefer the simplest pattern that solves the problem. Do not introduce
  patterns that add indirection without a benefit for understanding,
  modification or testing.
- Each pattern must have a recognizable role in the code: the module or
  class that implements it must be easy to locate and its intent must be
  documented in its documentation comment.
- In the README, include a table with the pattern applied, the module
  where it lives and the maintainability problem it solves.

### 5. Cross-cutting quality

- Include automated unit tests for the business logic, using mock
  repositories (no database).
- Implement explicit error handling and input validation in each layer
  (backend and frontend).
- Avoid code duplication and functions or classes with excessive
  complexity.
- Briefly document, in the README, the design decisions adopted and
  their justification.

Deliver the complete, working project, ready to run locally.
