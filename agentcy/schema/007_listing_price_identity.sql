-- Market prices belong to tradable listings. One SEC issuer may have multiple share
-- classes, so the current-price partition includes provider_symbol as listing identity.
DROP VIEW v_current_market_price;

CREATE VIEW v_current_market_price AS
WITH promoted_run AS (
    SELECT refresh_run_id
      FROM market_price_refresh_run
     WHERE status = 'SUCCEEDED' AND promoted = 1
     ORDER BY scheduled_for DESC, attempt DESC, refresh_run_id DESC
     LIMIT 1
), ranked AS (
    SELECT observation.*,
           ROW_NUMBER() OVER (
               PARTITION BY observation.security_key, observation.provider_symbol
               ORDER BY observation.bar_date DESC, observation.fetched_at DESC,
                        observation.price_observation_id DESC
           ) AS recency_rank
      FROM market_price_observation observation
      JOIN promoted_run ON promoted_run.refresh_run_id = observation.refresh_run_id
)
SELECT * FROM ranked WHERE recency_rank = 1;
