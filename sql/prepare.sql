-- Operates only on the dedicated perf_lab schema. Explicit --reset-data is required.
CREATE SCHEMA IF NOT EXISTS perf_lab;
DROP TABLE IF EXISTS perf_lab.orders;
CREATE TABLE perf_lab.orders (
    id BIGINT PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    created_at DATE NOT NULL,
    amount_cents INTEGER NOT NULL,
    payload TEXT NOT NULL
);
INSERT INTO perf_lab.orders (id, customer_id, created_at, amount_cents, payload)
SELECT
    i,
    1 + (i % :customers)::INTEGER,
    DATE '2025-01-01' + (i % 365)::INTEGER,
    100 + (i * 37 % 100000)::INTEGER,
    repeat(md5(i::TEXT), 4)
FROM generate_series(1::BIGINT, :rows::BIGINT) AS i;
VACUUM (ANALYZE) perf_lab.orders;
