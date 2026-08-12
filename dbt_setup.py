# This script sets up dbt models for the attribution pipeline
# Run: python dbt_setup.py

import os
import shutil

# Create directories
directories = [
    'dbt_project/models/staging',
    'dbt_project/models/marts',
    'dbt_project/tests',
    'dbt_project/macros'
]

for dir_path in directories:
    os.makedirs(dir_path, exist_ok=True)

# Staging model: clicks
with open('dbt_project/models/staging/stg_clicks.sql', 'w') as f:
    f.write('''
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
''')

# Staging model: purchases
with open('dbt_project/models/staging/stg_purchases.sql', 'w') as f:
    f.write('''
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
''')

# Attribution mart
with open('dbt_project/models/marts/mart_attribution.sql', 'w') as f:
    f.write('''
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
''')

print("✅ dbt project structure created!")
print("Run: cd dbt_project && dbt run")
