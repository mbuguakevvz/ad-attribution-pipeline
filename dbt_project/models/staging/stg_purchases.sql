
{{ config(materialized='table') }}

SELECT 
    order_id,
    user_id,
    session_id,
    revenue_usd,
    product_sku,
    purchase_timestamp,
    DATE(purchase_timestamp) as purchase_date,
    click_event_id,
    CASE 
        WHEN revenue_usd > 150 THEN 'high_value'
        WHEN revenue_usd > 100 THEN 'medium_value'
        ELSE 'standard'
    END as order_tier
FROM raw_purchases
WHERE order_id IS NOT NULL
