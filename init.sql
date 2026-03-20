-- =============================================================
-- Part 1: Metadata Schema (cortex-local's own tables)
-- =============================================================

CREATE TABLE IF NOT EXISTS semantic_models (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

INSERT INTO semantic_models (id, name, description)
VALUES (1, 'Default', 'Default semantic model')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS semantic_tables (
  id          SERIAL PRIMARY KEY,
  model_id    INTEGER NOT NULL REFERENCES semantic_models(id) ON DELETE CASCADE DEFAULT 1,
  table_name  TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE(model_id, table_name)
);

CREATE TABLE IF NOT EXISTS semantic_columns (
  id            SERIAL PRIMARY KEY,
  table_id      INTEGER REFERENCES semantic_tables(id) ON DELETE CASCADE,
  column_name   TEXT NOT NULL,
  data_type     TEXT,
  description   TEXT,
  is_pii        BOOLEAN DEFAULT false,
  is_visible    BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(table_id, column_name)
);

CREATE TABLE IF NOT EXISTS query_history (
  id          SERIAL PRIMARY KEY,
  question    TEXT NOT NULL,
  sql         TEXT NOT NULL,
  was_edited  BOOLEAN DEFAULT false,
  result_rows INTEGER,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- =============================================================
-- Part 2: Demo Data — e-commerce schema
-- =============================================================

CREATE TABLE IF NOT EXISTS customers (
  id         SERIAL PRIMARY KEY,
  email      TEXT,
  full_name  TEXT,
  country    TEXT,
  ltv_eur    NUMERIC(10,2),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
  id        SERIAL PRIMARY KEY,
  name      TEXT,
  category  TEXT,
  price_eur NUMERIC(10,2)
);

CREATE TABLE IF NOT EXISTS orders (
  id          SERIAL PRIMARY KEY,
  customer_id INTEGER REFERENCES customers(id),
  product_id  INTEGER REFERENCES products(id),
  total_eur   NUMERIC(10,2),
  status      TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Customers
INSERT INTO customers (email, full_name, country, ltv_eur) VALUES
  ('anna@example.com',    'Anna Müller',       'DE', 1240.00),
  ('jan@example.com',     'Jan de Vries',      'NL',  830.50),
  ('sophie@example.com',  'Sophie Dupont',     'FR',  450.00),
  ('carlos@example.com',  'Carlos García',     'ES', 2100.75),
  ('emma@example.com',    'Emma Johansson',    'SE',  190.00),
  ('liam@example.com',    'Liam O''Brien',     'IE',  675.25),
  ('giulia@example.com',  'Giulia Rossi',      'IT', 3200.00);

-- Products
INSERT INTO products (name, category, price_eur) VALUES
  ('Espresso Machine Pro',   'Appliances',   249.99),
  ('Ceramic Pour-Over Set',  'Accessories',   34.50),
  ('Single Origin Beans 1kg','Coffee',        18.90),
  ('Grinder Elite',          'Appliances',   179.00),
  ('Travel Mug Insulated',   'Accessories',   22.00),
  ('Cold Brew Kit',          'Accessories',   45.00);

-- Orders
INSERT INTO orders (customer_id, product_id, total_eur, status) VALUES
  (1, 1, 249.99, 'shipped'),
  (1, 3,  37.80, 'shipped'),
  (2, 2,  34.50, 'shipped'),
  (2, 5,  22.00, 'pending'),
  (3, 3,  18.90, 'shipped'),
  (4, 1, 249.99, 'shipped'),
  (4, 4, 179.00, 'shipped'),
  (4, 3,  56.70, 'shipped'),
  (5, 5,  22.00, 'returned'),
  (5, 3,  18.90, 'pending'),
  (6, 2,  34.50, 'shipped'),
  (6, 6,  45.00, 'shipped'),
  (7, 1, 249.99, 'shipped'),
  (7, 4, 179.00, 'shipped'),
  (7, 6,  45.00, 'shipped'),
  (7, 3,  75.60, 'pending'),
  (1, 4, 179.00, 'shipped'),
  (3, 6,  45.00, 'returned'),
  (4, 5,  44.00, 'shipped'),
  (2, 1, 249.99, 'shipped');
