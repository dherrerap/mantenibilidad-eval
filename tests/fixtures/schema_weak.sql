-- Weak schema (fixture): table without primary key, implicit relation (user_id without FK), FLOAT money, nothing indexed, almost no constraints.
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255),
  name VARCHAR(100)
);
CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  user_id INTEGER,
  total FLOAT,
  status TEXT
);
CREATE TABLE audit_log (
  message TEXT,
  user_id INTEGER
);
