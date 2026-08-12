import json
import time
import duckdb
import pandas as pd
from datetime import datetime, timedelta
from queue import Queue, Empty
import threading
from collections import defaultdict

class AttributionProcessor:
    def __init__(self, window_seconds=60):
        self.window_seconds = window_seconds
        self.click_buffer = []
        self.purchase_buffer = []
        self.db = duckdb.connect("attribution.db")
        self._init_tables()
        
    def _init_tables(self):
        """Create tables if they don't exist"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS raw_clicks (
                event_id VARCHAR,
                user_id VARCHAR,
                session_id VARCHAR,
                ip_hash VARCHAR,
                user_agent VARCHAR,
                campaign_id VARCHAR,
                publisher VARCHAR,
                cost_micros INTEGER,
                click_timestamp TIMESTAMP,
                landing_page VARCHAR,
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS raw_purchases (
                order_id VARCHAR,
                user_id VARCHAR,
                session_id VARCHAR,
                revenue_usd FLOAT,
                product_sku VARCHAR,
                purchase_timestamp TIMESTAMP,
                click_event_id VARCHAR,
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS attributed_sales (
                order_id VARCHAR,
                click_event_id VARCHAR,
                campaign_id VARCHAR,
                publisher VARCHAR,
                revenue_usd FLOAT,
                cost_micros INTEGER,
                attribution_type VARCHAR,
                attribution_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Database tables ready")
    
    def process_event(self, event_json):
        """Process a single event (click or purchase)"""
        try:
            data = json.loads(event_json.strip())
            
            # Check if it's a click (has 'campaign_id' and no 'order_id')
            if 'campaign_id' in data and 'order_id' not in data:
                self.click_buffer.append(data)
                print(f"  📥 Click buffered: {data['event_id']} from {data['publisher']}")
            
            # Check if it's a purchase (has 'order_id')
            elif 'order_id' in data:
                self.purchase_buffer.append(data)
                print(f"  🛒 Purchase buffered: {data['order_id']} - ${data['revenue_usd']}")
                
        except json.JSONDecodeError as e:
            print(f"  ⚠️ Skipping invalid JSON: {e}")
    
    def process_window(self):
        """Process the current micro-batch window"""
        if not self.click_buffer and not self.purchase_buffer:
            return
        
        print(f"\n⏰ Processing window with {len(self.click_buffer)} clicks and {len(self.purchase_buffer)} purchases")
        
        # Convert to DataFrames
        clicks_df = pd.DataFrame(self.click_buffer)
        purchases_df = pd.DataFrame(self.purchase_buffer)
        
        if not clicks_df.empty:
            # Store raw clicks - explicitly name columns to match table
            clicks_df['click_timestamp'] = pd.to_datetime(clicks_df['click_timestamp'])
            
            # Insert only the columns that match the table (exclude ingested_at since it auto-generates)
            self.db.register('clicks_view', clicks_df)
            self.db.execute("""
                INSERT INTO raw_clicks (
                    event_id, user_id, session_id, ip_hash, user_agent, 
                    campaign_id, publisher, cost_micros, click_timestamp, landing_page
                )
                SELECT 
                    event_id, user_id, session_id, ip_hash, user_agent, 
                    campaign_id, publisher, cost_micros, click_timestamp, landing_page
                FROM clicks_view
            """)
            print(f"  ✅ Stored {len(clicks_df)} clicks to database")
        
        if not purchases_df.empty:
            # Store raw purchases
            purchases_df['purchase_timestamp'] = pd.to_datetime(purchases_df['purchase_timestamp'])
            self.db.register('purchases_view', purchases_df)
            self.db.execute("""
                INSERT INTO raw_purchases (
                    order_id, user_id, session_id, revenue_usd, product_sku, 
                    purchase_timestamp, click_event_id
                )
                SELECT 
                    order_id, user_id, session_id, revenue_usd, product_sku, 
                    purchase_timestamp, click_event_id
                FROM purchases_view
            """)
            print(f"  ✅ Stored {len(purchases_df)} purchases to database")
        
        # ---- ATTRIBUTION LOGIC (Last-Click) ----
        if not purchases_df.empty and not clicks_df.empty:
            self._calculate_last_click_attribution(clicks_df, purchases_df)
        
        # Clear buffers
        self.click_buffer = []
        self.purchase_buffer = []
    
    def _calculate_last_click_attribution(self, clicks_df, purchases_df):
        """Last-click attribution: credit goes to the last click before purchase"""
        print("  🔍 Calculating Last-Click Attribution...")
        
        # Sort clicks by timestamp for each user
        clicks_df = clicks_df.sort_values('click_timestamp')
        
        # For each purchase, find the last click from the same user before the purchase
        attributed = []
        
        for _, purchase in purchases_df.iterrows():
            # Find all clicks from same user before purchase
            user_clicks = clicks_df[
                (clicks_df['user_id'] == purchase['user_id']) &
                (clicks_df['click_timestamp'] <= purchase['purchase_timestamp'])
            ]
            
            if not user_clicks.empty:
                # Take the most recent click (Last-Click)
                last_click = user_clicks.iloc[-1]  # Last row after sorting
                
                attributed.append({
                    'order_id': purchase['order_id'],
                    'click_event_id': last_click['event_id'],
                    'campaign_id': last_click['campaign_id'],
                    'publisher': last_click['publisher'],
                    'revenue_usd': purchase['revenue_usd'],
                    'cost_micros': last_click['cost_micros'],
                    'attribution_type': 'last_click'
                })
                print(f"    ✅ Attributed {purchase['order_id']} to {last_click['publisher']} (Last-Click)")
            else:
                print(f"    ⚠️ No click found for purchase {purchase['order_id']} (Organic/Unknown)")
                attributed.append({
                    'order_id': purchase['order_id'],
                    'click_event_id': 'unknown',
                    'campaign_id': 'organic',
                    'publisher': 'organic',
                    'revenue_usd': purchase['revenue_usd'],
                    'cost_micros': 0,
                    'attribution_type': 'unknown'
                })
        
        # Store attributed sales
        if attributed:
            attr_df = pd.DataFrame(attributed)
            self.db.register('attributed_view', attr_df)
            self.db.execute("""
                INSERT INTO attributed_sales (
                    order_id, click_event_id, campaign_id, publisher, 
                    revenue_usd, cost_micros, attribution_type
                )
                SELECT 
                    order_id, click_event_id, campaign_id, publisher, 
                    revenue_usd, cost_micros, attribution_type
                FROM attributed_view
            """)
            print(f"  ✅ Stored {len(attributed)} attributed sales")
    
    def get_metrics(self):
        """Get current business metrics"""
        try:
            metrics = self.db.execute("""
                SELECT 
                    COUNT(DISTINCT order_id) as total_orders,
                    SUM(revenue_usd) as total_revenue,
                    SUM(CASE WHEN publisher != 'organic' THEN cost_micros ELSE 0 END) / 1000000.0 as total_cost_usd,
                    SUM(revenue_usd) / NULLIF(SUM(CASE WHEN publisher != 'organic' THEN cost_micros ELSE 0 END) / 1000000.0, 0) as roas,
                    publisher,
                    COUNT(*) as conversions
                FROM attributed_sales
                GROUP BY publisher
                ORDER BY conversions DESC
            """).fetchdf()
            return metrics
        except:
            return pd.DataFrame()

def run_stream_consumer():
    """Main consumer loop"""
    # Initialize processor
    processor = AttributionProcessor(window_seconds=60)
    
    # Connect to the queue (from the producer)
    q = Queue()
    stop_event = threading.Event()
    
    # Import and start the producer in a background thread
    from data_generator import start_data_stream
    
    print("🚀 Starting data stream...")
    producer_thread = threading.Thread(target=start_data_stream, args=(q, stop_event, 20))
    producer_thread.daemon = True
    producer_thread.start()
    
    # Consume events
    last_window_time = datetime.now()
    
    try:
        print("\n📡 Listening for events... (Press Ctrl+C to stop)")
        print("-" * 50)
        
        while True:
            try:
                # Try to get an event with 1-second timeout
                event = q.get(timeout=1)
                processor.process_event(event)
                
                # Process window every 60 seconds
                if (datetime.now() - last_window_time).seconds >= 60:
                    processor.process_window()
                    last_window_time = datetime.now()
                    
                    # Show live metrics
                    metrics = processor.get_metrics()
                    if not metrics.empty:
                        print("\n📊 LIVE METRICS:")
                        print(metrics.to_string(index=False))
                        print("-" * 50)
                    
            except Empty:
                # No events, just wait
                continue
                
    except KeyboardInterrupt:
        print("\n🛑 Stopping consumer...")
        # Process any remaining events
        processor.process_window()
        
        # Final metrics
        print("\n📊 FINAL METRICS:")
        final_metrics = processor.get_metrics()
        if not final_metrics.empty:
            print(final_metrics.to_string(index=False))
        else:
            print("No data processed yet.")
        
    finally:
        stop_event.set()
        producer_thread.join(timeout=2)
        print("👋 Done!")

if __name__ == "__main__":
    run_stream_consumer()
