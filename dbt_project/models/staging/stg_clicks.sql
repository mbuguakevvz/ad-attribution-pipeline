
{{ config(materialized='table') }}

SELECT 
    event_id,
    user_id,
    session_id,
    campaign_id,
    publisher,
    cost_micros / 1000000.0 as cost_usd,
    click_timestamp,
    DATE(click_timestamp) as click_date,
    EXTRACT(HOUR FROM click_timestamp) as hour_of_day
FROM raw_clicks
WHERE event_id IS NOT NULL
