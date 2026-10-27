You are going to build an application following two documents as the
single source of truth, located in the current directory:

1. The technical specification in `technical-{LEVEL}.md`, which defines
   the stack, the architectural style, the delivery conditions and the
   guidelines you must follow.
2. The functional requirements in `requirements-ecommerce.md`, which
   define what the application must do.

Combine both documents: use the stack and the technical guidelines of
the first to implement the features and business logic described in the
second. If something is not explicitly covered in either document, make
the decision you consider most appropriate and note in the README the
functional assumptions you made.

## Cross-cutting constraints (always apply)

### Code comments

The code must be evaluable and maintainable by other people:

- Every module, class and public function has a documentation comment
  (JSDoc/TSDoc) stating its purpose, parameters, return value and the
  errors it can throw.
- Use inline comments only to explain the why: business rules (volume
  discount, stock validation, status transitions), assumptions and
  non-obvious decisions. Do not narrate what the code already expresses.
- Do not leave commented-out code in the delivery.
- If you deliberately leave a shortcut or known limitation, mark it with
  `TODO:` or `FIXME:` and a brief explanation.

### Entity-relationship model

Deliver the entity-relationship model of the database in
`docs/entity-relationship-model.md`, as a Mermaid diagram (`erDiagram`)
plus a brief description of each entity. It must include entities,
attributes with their types, primary and foreign keys, the cardinality
of each relationship and relevant constraints (uniqueness, nullability).
It must correspond exactly to the schema implemented in the code, and it
must be linked from the README.

Work autonomously: do not ask questions or wait for confirmation.
Generate all the project files inside the current directory.

Deliver the complete, working project, ready to run locally, including
installation and run instructions.
