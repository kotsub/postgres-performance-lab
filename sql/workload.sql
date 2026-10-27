\set wanted_customer random(1, :customers)
SELECT COALESCE(SUM(amount_cents), 0)
FROM perf_lab.orders
WHERE customer_id = :wanted_customer
  AND created_at >= DATE '2025-06-01';
