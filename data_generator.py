import json
import random
import time
from datetime import datetime, timedelta
from faker import Faker
import hashlib
from queue import Queue
import threading

fake = Faker()
Faker.seed(42)

CAMPAIGNS = [
    {"id": "cmp_meta_brand", "publisher": "meta", "cost_per_click": 0.85},
    {"id": "cmp_google_shoes", "publisher": "google", "cost_per_click": 1.20},
    {"id": "cmp_tiktok_ua", "publisher": "tiktok", "cost_per_click": 0.45},
    {"id": "cmp_google_retarget", "publisher": "google", "cost_per_click": 2.10},
]
PRODUCTS = [("RUN-101", 129.99), ("LIFT-50", 89.50), ("FLEX-22", 159.00)]

def hash_ip(ip): 
    return hashlib.sha256(ip.encode()).hexdigest()[:16]

def generate_click(base_time):
    camp = random.choice(CAMPAIGNS)
    return {
        "event_id": f"evt_{base_time.strftime('%y%m%d%H%M')}_{random.randint(1000,9999)}",
        "user_id": f"u_{random.randint(1000, 9999)}",
        "session_id": f"s_{fake.lexify('???????')}",
        "ip_hash": hash_ip(fake.ipv4()),
        "user_agent": fake.user_agent(),
        "campaign_id": camp["id"],
        "publisher": camp["publisher"],
        "cost_micros": int(camp["cost_per_click"] * 1_000_000),
        "click_timestamp": base_time.isoformat() + "Z",
        "landing_page": f"/products/{random.choice(['run-101', 'lift-50', 'flex-22'])}?utm_source={camp['publisher']}"
    }

def generate_purchase(click, base_time):
    sku, price = random.choice(PRODUCTS)
    purchase_time = base_time + timedelta(minutes=random.randint(5, 30))
    return {
        "order_id": f"ord_{fake.lexify('?????')}{random.randint(100,999)}",
        "user_id": click["user_id"],
        "session_id": click["session_id"],
        "revenue_usd": price,
        "product_sku": sku,
        "purchase_timestamp": purchase_time.isoformat() + "Z",
        "click_event_id": click["event_id"]
    }

def start_data_stream(output_queue, stop_event, clicks_per_batch=50):
    minute_counter = 0
    while not stop_event.is_set():
        base = datetime.utcnow() + timedelta(minutes=minute_counter)
        batch_clicks = [generate_click(base + timedelta(seconds=i)) for i in range(clicks_per_batch)]
        purchasers = random.sample(batch_clicks, k=max(1, int(len(batch_clicks) * random.uniform(0.08, 0.12))))
        batch_purchases = [generate_purchase(c, base) for c in purchasers]
        
        for event in batch_clicks + batch_purchases:
            output_queue.put(json.dumps(event) + "\n")
        
        minute_counter += 1
        time.sleep(5)

if __name__ == "__main__":
    q = Queue()
    stop = threading.Event()
    print("Starting test producer. Press Ctrl+C to stop.")
    t = threading.Thread(target=start_data_stream, args=(q, stop, 10))
    t.start()
    try:
        for _ in range(5):
            print(q.get(timeout=2))
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        t.join()
