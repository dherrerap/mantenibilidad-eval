# Technical specification — Level 1

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

## Additional guidelines
There are no additional guidelines on how to organize the internal
layers, nor on quality practices. Make the design, code organization and
project structure decisions you consider appropriate.

Deliver the complete, working project, ready to run locally.
