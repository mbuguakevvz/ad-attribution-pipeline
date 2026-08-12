import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import combinations

class AdvancedAttribution:
    def __init__(self, db_path="attribution.db"):
        self.db = duckdb.connect(db_path)
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create tables for advanced attribution if they don't exist"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS attribution_comparison (
                order_id VARCHAR,
                campaign_id VARCHAR,
                publisher VARCHAR,
                revenue_usd FLOAT,
                first_click_credit FLOAT,
                last_click_credit FLOAT,
                linear_credit FLOAT,
                time_decay_credit FLOAT,
                shapley_credit FLOAT,
                total_attributed_value FLOAT,
                calculation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Advanced attribution tables ready")
    
    def get_user_journey(self, user_id, days_back=7):
        """Get all clicks and purchases for a user"""
        query = f"""
            SELECT 
                c.event_id,
                c.user_id,
                c.campaign_id,
                c.publisher,
                c.cost_micros / 1000000.0 as cost_usd,
                c.click_timestamp,
                p.order_id,
                p.revenue_usd as revenue,
                p.purchase_timestamp
            FROM raw_clicks c
            LEFT JOIN raw_purchases p ON c.user_id = p.user_id 
                AND p.purchase_timestamp >= c.click_timestamp
                AND p.purchase_timestamp <= c.click_timestamp + INTERVAL '{days_back} DAYS'
            WHERE c.user_id = '{user_id}'
            ORDER BY c.click_timestamp
        """
        return self.db.execute(query).fetchdf()
    
    def calculate_attribution_weights(self, user_journey_df):
        """Calculate all attribution models for a single user's journey"""
        if user_journey_df.empty:
            return None
        
        # Sort by timestamp
        df = user_journey_df.sort_values('click_timestamp')
        
        # Get the actual purchase revenue (assuming one purchase per journey for simplicity)
        revenue = df['revenue'].iloc[-1] if not df['revenue'].isna().all() else 0
        
        if revenue == 0 or len(df) == 0:
            return None
        
        # --- 1. First-Click Attribution ---
        first_click = {}
        first_campaign = df.iloc[0]['campaign_id']
        first_click[first_campaign] = revenue
        
        # --- 2. Last-Click Attribution ---
        last_click = {}
        last_campaign = df.iloc[-1]['campaign_id']
        last_click[last_campaign] = revenue
        
        # --- 3. Linear Attribution ---
        linear = {}
        total_clicks = len(df)
        for _, row in df.iterrows():
            campaign = row['campaign_id']
            linear[campaign] = linear.get(campaign, 0) + (revenue / total_clicks)
        
        # --- 4. Time-Decay Attribution ---
        time_decay = {}
        max_time = df['click_timestamp'].max()
        min_time = df['click_timestamp'].min()
        time_range = (max_time - min_time).total_seconds() if max_time != min_time else 1
        
        for _, row in df.iterrows():
            campaign = row['campaign_id']
            # Calculate decay weight: later clicks get more weight
            time_diff = (max_time - row['click_timestamp']).total_seconds()
            decay_weight = 0.5 + (0.5 * (time_diff / time_range))  # Range: 0.5 to 1.0
            time_decay[campaign] = time_decay.get(campaign, 0) + (revenue * decay_weight / len(df))
        
        # --- 5. Shapley Value (Game Theory) ---
        shapley = self._calculate_shapley(df, revenue)
        
        return {
            'revenue': revenue,
            'first_click': first_click,
            'last_click': last_click,
            'linear': linear,
            'time_decay': time_decay,
            'shapley': shapley
        }
    
    def _calculate_shapley(self, df, revenue):
        """Calculate Shapley Value for channel attribution"""
        # Get unique campaigns
        campaigns = df['campaign_id'].unique()
        n = len(campaigns)
        
        if n == 0:
            return {}
        
        # Create a mapping of campaign to value
        campaign_values = {}
        
        for campaign in campaigns:
            total_marginal = 0
            # Get all subsets that don't include this campaign
            other_campaigns = [c for c in campaigns if c != campaign]
            
            for k in range(len(other_campaigns) + 1):
                # Generate all subsets of size k
                for subset in combinations(other_campaigns, k):
                    subset_size = len(subset)
                    # Calculate value of coalition without campaign
                    coalition_value = self._calculate_coalition_value(df, list(subset), revenue)
                    # Calculate value of coalition with campaign
                    coalition_with_campaign = self._calculate_coalition_value(df, list(subset) + [campaign], revenue)
                    
                    # Marginal contribution
                    marginal = coalition_with_campaign - coalition_value
                    
                    # Weighted by subset size
                    weight = 1 / (n * len(list(combinations(other_campaigns, k))))
                    total_marginal += weight * marginal
            
            campaign_values[campaign] = total_marginal
        
        return campaign_values
    
    def _calculate_coalition_value(self, df, subset_campaigns, revenue):
        """Calculate the value of a coalition of campaigns"""
        if not subset_campaigns:
            return 0
        
        # Filter to only clicks from campaigns in the coalition
        coalition_data = df[df['campaign_id'].isin(subset_campaigns)]
        
        if coalition_data.empty:
            return 0
        
        # Simple value: proportion of clicks in this coalition
        total_clicks = len(df)
        coalition_clicks = len(coalition_data)
        
        return revenue * (coalition_clicks / total_clicks) if total_clicks > 0 else 0
    
    def run_attribution_comparison(self):
        """Run attribution models on all users and store results"""
        print("\n🔍 Running Advanced Attribution Comparison...")
        
        # Get all users who made purchases
        users = self.db.execute("""
            SELECT DISTINCT user_id 
            FROM raw_purchases 
            WHERE user_id IN (SELECT DISTINCT user_id FROM raw_clicks)
        """).fetchdf()
        
        if users.empty:
            print("No users with complete journeys found")
            return
        
        print(f"Processing journeys for {len(users)} users...")
        
        results = []
        processed = 0
        
        for user_id in users['user_id']:
            journey = self.get_user_journey(user_id)
            
            if not journey.empty and journey['revenue'].notna().any():
                attribution = self.calculate_attribution_weights(journey)
                
                if attribution:
                    revenue = attribution['revenue']
                    
                    # Combine all models into a single row per campaign
                    all_campaigns = set()
                    for model in ['first_click', 'last_click', 'linear', 'time_decay', 'shapley']:
                        all_campaigns.update(attribution[model].keys())
                    
                    for campaign in all_campaigns:
                        result = {
                            'order_id': journey['order_id'].iloc[-1] if not journey['order_id'].isna().all() else f"ord_{user_id}",
                            'campaign_id': campaign,
                            'publisher': self.db.execute(f"SELECT publisher FROM raw_clicks WHERE campaign_id = '{campaign}' LIMIT 1").fetchone()[0] if campaign != 'organic' else 'organic',
                            'revenue_usd': revenue,
                            'first_click_credit': attribution['first_click'].get(campaign, 0),
                            'last_click_credit': attribution['last_click'].get(campaign, 0),
                            'linear_credit': attribution['linear'].get(campaign, 0),
                            'time_decay_credit': attribution['time_decay'].get(campaign, 0),
                            'shapley_credit': attribution['shapley'].get(campaign, 0),
                            'total_attributed_value': revenue
                        }
                        results.append(result)
                    
                    processed += 1
                    if processed % 10 == 0:
                        print(f"  Processed {processed} users...")
        
        # Store results
        if results:
            results_df = pd.DataFrame(results)
            self.db.register('comparison_view', results_df)
            self.db.execute("DELETE FROM attribution_comparison")  # Clear old data
            self.db.execute("""
                INSERT INTO attribution_comparison (
                    order_id, campaign_id, publisher, revenue_usd,
                    first_click_credit, last_click_credit, linear_credit,
                    time_decay_credit, shapley_credit, total_attributed_value
                )
                SELECT 
                    order_id, campaign_id, publisher, revenue_usd,
                    first_click_credit, last_click_credit, linear_credit,
                    time_decay_credit, shapley_credit, total_attributed_value
                FROM comparison_view
            """)
            print(f"✅ Stored attribution comparison for {len(results)} campaign contributions")
        
        return results
    
    def get_attribution_summary(self):
        """Get summary of all attribution models by channel"""
        summary = self.db.execute("""
            SELECT 
                publisher,
                COUNT(DISTINCT order_id) as orders,
                SUM(revenue_usd) as total_revenue,
                ROUND(AVG(first_click_credit), 2) as avg_first_click,
                ROUND(AVG(last_click_credit), 2) as avg_last_click,
                ROUND(AVG(linear_credit), 2) as avg_linear,
                ROUND(AVG(time_decay_credit), 2) as avg_time_decay,
                ROUND(AVG(shapley_credit), 2) as avg_shapley
            FROM attribution_comparison
            GROUP BY publisher
            ORDER BY avg_shapley DESC
        """).fetchdf()
        return summary
    
    def get_channel_recommendations(self):
        """Generate business recommendations based on attribution models"""
        summary = self.get_attribution_summary()
        
        if summary.empty:
            return "Not enough data for recommendations"
        
        recommendations = []
        
        for _, row in summary.iterrows():
            publisher = row['publisher']
            
            if publisher == 'organic':
                continue
                
            # Compare models
            first = row['avg_first_click']
            last = row['avg_last_click']
            linear = row['avg_linear']
            shapley = row['avg_shapley']
            
            # Check for undervalued channels
            if first > last * 1.3:
                recommendations.append(f"📢 {publisher}: Top-of-funnel channel. You're undervaluing it. Consider increasing awareness budgets.")
            elif last > first * 1.3:
                recommendations.append(f"🎯 {publisher}: Bottom-of-funnel channel. Great for conversions. Consider retargeting investments.")
            
            # Check if Shapley says something different
            if shapley > last:
                recommendations.append(f"💡 {publisher}: Shapley Value ({shapley:.2f}) is higher than Last-Click ({last:.2f}). This channel deserves more credit!")
            elif shapley < last:
                recommendations.append(f"⚠️ {publisher}: Last-Click overvalues this channel. Shapley ({shapley:.2f}) shows lower true impact.")
        
        return "\n".join(recommendations) if recommendations else "✅ All channels are fairly valued across models"

if __name__ == "__main__":
    # Test the advanced attribution
    attribution = AdvancedAttribution()
    attribution.run_attribution_comparison()
    
    print("\n" + "="*60)
    print("📊 ATTRIBUTION MODEL COMPARISON")
    print("="*60)
    summary = attribution.get_attribution_summary()
    print(summary.to_string(index=False))
    
    print("\n" + "="*60)
    print("💡 BUSINESS RECOMMENDATIONS")
    print("="*60)
    print(attribution.get_channel_recommendations())
