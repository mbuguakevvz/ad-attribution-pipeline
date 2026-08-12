"""
Deployment helper script for Streamlit Cloud
Ensures database exists and runs attribution before dashboard
"""

import duckdb
import subprocess
import sys
import os

def initialize_database():
    """Create database and run attribution models"""
    db = duckdb.connect("attribution.db")
    
    # Check if attribution_comparison table has data
    count = db.execute("SELECT COUNT(*) FROM attribution_comparison").fetchone()[0]
    
    if count == 0:
        print("⚠️ No attribution data found. Running attribution pipeline...")
        # Run the attribution script
        subprocess.run([sys.executable, "attribution.py"])
        print("✅ Attribution pipeline completed!")
    else:
        print(f"✅ Found {count} attribution records")

if __name__ == "__main__":
    initialize_database()
