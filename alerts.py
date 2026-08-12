"""
Smart Alerting System - Production Ready
Sends alerts via Slack, Email, and Console
"""

import os
import json
import duckdb
import pandas as pd
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv
import time

load_dotenv()

class SmartAlerts:
    """Smart alerting system for marketing attribution"""
    
    def __init__(self, db_path: str = "attribution.db"):
        self.db = duckdb.connect(db_path)
        self.alert_cooldown = {}  # Track last alert time per channel
        self.cooldown_seconds = 3600  # 1 hour cooldown
        self.slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
        self.email_enabled = bool(os.getenv('EMAIL_ENABLED', 'false').lower() == 'true')
    
    def check_channel_health(self) -> List[Dict]:
        """
        Check health of each marketing channel
        Returns list of alerts
        """
        alerts = []
        
        # Get last 24 hours of data
        health_data = self.db.execute("""
            WITH channel_health AS (
                SELECT 
                    publisher,
                    SUM(revenue_usd) as revenue,
                    SUM(cost_micros) / 1000000.0 as cost,
                    COUNT(DISTINCT order_id) as orders,
                    SUM(revenue_usd) / NULLIF(SUM(cost_micros) / 1000000.0, 0) as roas
                FROM attributed_sales
                WHERE attribution_timestamp > CURRENT_TIMESTAMP - INTERVAL '24 HOURS'
                    AND publisher != 'organic'
                GROUP BY publisher
            )
            SELECT 
                *,
                ROW_NUMBER() OVER (ORDER BY roas) as roas_rank
            FROM channel_health
        """).fetchdf()
        
        if health_data.empty:
            return [{'severity': 'ℹ️ INFO', 'message': 'No channel data in last 24 hours'}]
        
        # Check each channel
        for _, row in health_data.iterrows():
            channel = row['publisher']
            roas = row['roas']
            
            # Critical alerts
            if roas < 5:
                alerts.append({
                    'severity': '🔴 CRITICAL',
                    'message': f'🚨 {channel} ROAS is {roas:.1f}x! STOP SPEND IMMEDIATELY.',
                    'channel': channel,
                    'action': 'pause_campaign'
                })
            elif roas < 15:
                alerts.append({
                    'severity': '🟡 WARNING',
                    'message': f'⚠️ {channel} ROAS dropped to {roas:.1f}x. Review campaigns.',
                    'channel': channel,
                    'action': 'review_performance'
                })
            elif roas > 100:
                alerts.append({
                    'severity': '🟢 EXCELLENT',
                    'message': f'🎉 {channel} ROAS is {roas:.1f}x! Consider increasing budget.',
                    'channel': channel,
                    'action': 'increase_budget'
                })
            
            # Budget pacing (if cost > 70% of daily budget)
            daily_budget = 500  # Configurable
            cost = row['cost']
            hours_passed = datetime.now().hour
            expected_cost = (hours_passed / 24) * daily_budget
            
            if cost > expected_cost * 1.3 and expected_cost > 50:
                alerts.append({
                    'severity': '⚠️ PACING WARNING',
                    'message': f'📊 {channel} spent ${cost:.2f} vs expected ${expected_cost:.2f}. Overspending by ${cost - expected_cost:.2f}!',
                    'channel': channel,
                    'action': 'adjust_budget'
                })
        
        return alerts
    
    def check_anomalies(self) -> List[Dict]:
        """
        Detect anomalies in campaign performance
        """
        anomalies = []
        
        # Get 7-day average vs today
        anomaly_data = self.db.execute("""
            WITH daily_performance AS (
                SELECT 
                    publisher,
                    DATE(attribution_timestamp) as date,
                    SUM(revenue_usd) as daily_revenue,
                    SUM(cost_micros) / 1000000.0 as daily_cost
                FROM attributed_sales
                WHERE attribution_timestamp > CURRENT_TIMESTAMP - INTERVAL '7 DAYS'
                    AND publisher != 'organic'
                GROUP BY publisher, date
            ),
            channel_avg AS (
                SELECT 
                    publisher,
                    AVG(daily_revenue) as avg_revenue,
                    AVG(daily_cost) as avg_cost,
                    STDDEV(daily_revenue) as std_revenue,
                    STDDEV(daily_cost) as std_cost
                FROM daily_performance
                WHERE date < CURRENT_DATE
                GROUP BY publisher
            )
            SELECT 
                ca.publisher,
                ca.avg_revenue,
                dp.daily_revenue as today_revenue,
                ca.avg_cost,
                dp.daily_cost as today_cost,
                (dp.daily_revenue - ca.avg_revenue) / NULLIF(ca.std_revenue, 0) as z_score
            FROM channel_avg ca
            LEFT JOIN daily_performance dp 
                ON ca.publisher = dp.publisher AND dp.date = CURRENT_DATE
            WHERE dp.daily_revenue IS NOT NULL
        """).fetchdf()
        
        for _, row in anomaly_data.iterrows():
            if abs(row['z_score']) > 2:
                direction = "🚀 UP" if row['z_score'] > 0 else "📉 DOWN"
                anomalies.append({
                    'severity': '🔍 ANOMALY',
                    'message': f"{direction} {row['publisher']} revenue {abs(row['z_score']):.1f}x from average today!",
                    'channel': row['publisher'],
                    'action': 'investigate' if row['z_score'] < 0 else 'scale'
                })
        
        return anomalies
    
    def send_slack_alert(self, alert: Dict) -> bool:
        """
        Send alert to Slack
        
        Args:
            alert: Alert dictionary
        
        Returns:
            bool: Success/failure
        """
        if not self.slack_webhook:
            print("ℹ️ Slack webhook not configured. Printing alert to console.")
            print(f"{alert['severity']}: {alert['message']}")
            return False
        
        # Format message
        message = f"{alert['severity']}\n{alert['message']}"
        
        # Add action if available
        if 'action' in alert:
            message += f"\n\n💡 Action: {alert['action'].replace('_', ' ').title()}"
        
        payload = {
            'text': message,
            'blocks': [
                {
                    'type': 'header',
                    'text': {
                        'type': 'plain_text',
                        'text': '🚨 Marketing Alert'
                    }
                },
                {
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': message
                    }
                },
                {
                    'type': 'divider'
                },
                {
                    'type': 'context',
                    'elements': [
                        {
                            'type': 'mrkdwn',
                            'text': f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        
        try:
            response = requests.post(self.slack_webhook, json=payload, timeout=10)
            if response.status_code == 200:
                print("✅ Slack alert sent!")
                return True
            else:
                print(f"❌ Slack error: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Slack error: {e}")
            return False
    
    def send_email_alert(self, alert: Dict) -> bool:
        """
        Send alert via email
        
        Args:
            alert: Alert dictionary
        
        Returns:
            bool: Success/failure
        """
        if not self.email_enabled:
            return False
        
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        sender = os.getenv('ALERT_EMAIL_SENDER')
        password = os.getenv('ALERT_EMAIL_PASSWORD')
        recipient = os.getenv('ALERT_EMAIL_RECIPIENT')
        
        if not all([sender, password, recipient]):
            print("ℹ️ Email not configured")
            return False
        
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = recipient
        msg['Subject'] = f"Marketing Alert: {alert['severity']}"
        
        body = f"""
        Marketing Attribution Alert
        {'='*40}
        
        Severity: {alert['severity']}
        Message: {alert['message']}
        Action: {alert.get('action', 'Monitor')}
        Time: {datetime.now()}
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            print("✅ Email alert sent!")
            return True
        except Exception as e:
            print(f"❌ Email error: {e}")
            return False
    
    def run_alert_cycle(self) -> List[Dict]:
        """
        Run the full alert cycle
        
        Returns:
            List of alerts sent
        """
        print(f"\n🔍 Running alert cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 60)
        
        all_alerts = []
        
        # Check channel health
        health_alerts = self.check_channel_health()
        all_alerts.extend(health_alerts)
        
        # Check anomalies
        anomaly_alerts = self.check_anomalies()
        all_alerts.extend(anomaly_alerts)
        
        # Send alerts
        sent_alerts = []
        for alert in all_alerts:
            channel = alert.get('channel', 'unknown')
            
            # Check cooldown
            last_time = self.alert_cooldown.get(channel, datetime.min)
            if (datetime.now() - last_time).seconds < self.cooldown_seconds:
                print(f"⏰ Cooldown active for {channel} - skipping")
                continue
            
            # Send to Slack
            if self.slack_webhook:
                self.send_slack_alert(alert)
            
            # Send to Email
            if self.email_enabled:
                self.send_email_alert(alert)
            
            # Print to console
            print(f"📢 {alert['severity']}: {alert['message']}")
            if 'action' in alert:
                print(f"   💡 Action: {alert['action'].replace('_', ' ').title()}")
            
            # Update cooldown
            self.alert_cooldown[channel] = datetime.now()
            sent_alerts.append(alert)
        
        if not sent_alerts:
            print("✅ No alerts to send")
        else:
            print(f"📤 Sent {len(sent_alerts)} alerts")
        
        return sent_alerts

if __name__ == "__main__":
    # Test the alert system
    alerts = SmartAlerts()
    alerts.run_alert_cycle()
