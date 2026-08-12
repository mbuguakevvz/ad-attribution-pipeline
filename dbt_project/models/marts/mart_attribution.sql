
{{ config(materialized='table') }}

WITH user_journey AS (
    SELECT 
        p.order_id,
        p.user_id,
        p.revenue_usd,
        p.purchase_timestamp,
        p.order_tier,
        c.event_id as click_event_id,
        c.campaign_id,
        c.publisher,
        c.cost_usd,
        c.click_timestamp,
        c.hour_of_day,
        ROW_NUMBER() OVER (
            PARTITION BY p.order_id 
            ORDER BY c.click_timestamp DESC
        ) as click_rank,
        ROW_NUMBER() OVER (
            PARTITION BY p.order_id 
            ORDER BY c.click_timestamp ASC
        ) as first_click_rank
    FROM {{ ref('stg_purchases') }} p
    LEFT JOIN {{ ref('stg_clicks') }} c 
        ON p.user_id = c.user_id
        AND c.click_timestamp <= p.purchase_timestamp
        AND c.click_timestamp >= p.purchase_timestamp - INTERVAL '30 DAYS'
)

SELECT 
    order_id,
    user_id,
    revenue_usd,
    purchase_timestamp,
    order_tier,
    CASE 
        WHEN click_rank = 1 THEN campaign_id 
        ELSE 'organic' 
    END as last_click_campaign,
    CASE 
        WHEN click_rank = 1 THEN publisher 
        ELSE 'organic' 
    END as last_click_publisher,
    CASE 
        WHEN first_click_rank = 1 THEN campaign_id 
        ELSE 'organic' 
    END as first_click_campaign,
    CASE 
        WHEN first_click_rank = 1 THEN publisher 
        ELSE 'organic' 
    END as first_click_publisher,
    cost_usd as attributed_cost,
    hour_of_day,
    click_timestamp as last_click_time,
    COUNT(*) OVER (PARTITION BY order_id) as total_touchpoints
FROM user_journey
WHERE click_rank = 1 OR click_rank IS NULL
