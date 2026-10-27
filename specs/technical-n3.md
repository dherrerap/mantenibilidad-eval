# Technical specification — Level 3

You are going to build a **web application**.

## Mandatory stack
You must use the MERN stack:
- MongoDB as the database
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
  environment variable and the MongoDB connection URL from the
  `MONGODB_URI` environment variable.
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
between non-adjacent layers.

### 2. Dependencies and integration
Use Mongoose as the ODM for data access in MongoDB. Apply dependency
injection where appropriate, and avoid direct coupling between the
business logic and specific frameworks or libraries (for example, the
business logic must not depend directly on Express or Mongoose).

### 3. Cross-cutting quality
- Include automated unit tests for the business logic.
- Implement explicit error handling and input validation in each layer
  (backend and frontend).
- Avoid code duplication and functions or classes with excessive
  complexity.
- Briefly document, in the README, the design decisions adopted and
  their justification.

Deliver the complete, working project, ready to run locally.
