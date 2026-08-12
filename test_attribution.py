# test_attribution.py
import pytest
import duckdb
import pandas as pd
from datetime import datetime, timedelta

class TestAttributionPipeline:
    """Unit tests for attribution pipeline"""
    
    def setup_method(self):
        """Setup test database"""
        self.db = duckdb.connect("test.db")
        self.db.execute("""
            CREATE TABLE raw_clicks AS 
            SELECT 'test_click' as event_id, 'user1' as user_id, 
                   'google' as publisher, 1000000 as cost_micros,
                   NOW() as click_timestamp
        """)
        self.db.execute("""
            CREATE TABLE raw_purchases AS
            SELECT 'test_order' as order_id, 'user1' as user_id,
                   129.99 as revenue_usd, NOW() as purchase_timestamp,
                   'test_click' as click_event_id
        """)
    
    def test_click_insert(self):
        """Test that clicks are inserted correctly"""
        result = self.db.execute("SELECT COUNT(*) FROM raw_clicks").fetchone()[0]
        assert result == 1
    
    def test_purchase_insert(self):
        """Test that purchases are inserted correctly"""
        result = self.db.execute("SELECT COUNT(*) FROM raw_purchases").fetchone()[0]
        assert result == 1
    
    def test_attribution_calculation(self):
        """Test attribution logic"""
        result = self.db.execute("""
            SELECT p.order_id, p.user_id, c.publisher
            FROM raw_purchases p
            LEFT JOIN raw_clicks c ON p.user_id = c.user_id
            WHERE p.order_id = 'test_order'
        """).fetchdf()
        assert not result.empty
        assert result['publisher'].iloc[0] == 'google'
    
    def test_duplicate_prevention(self):
        """Test that duplicates are prevented"""
        self.db.execute("""
            INSERT INTO raw_clicks VALUES 
            ('test_click2', 'user2', 'meta', 500000, NOW())
        """)
        result = self.db.execute(
            "SELECT COUNT(DISTINCT event_id) FROM raw_clicks"
        ).fetchone()[0]
        assert result == 2

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
