import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# Page config
st.set_page_config(
    page_title="Marketing Attribution Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Connect to database
@st.cache_resource
def get_db():
    return duckdb.connect("attribution.db")

db = get_db()

# Title
st.title("🚀 Real-Time Marketing Attribution Dashboard")
st.markdown("*Powered by Multi-Touch Attribution Models*")
st.divider()

# Sidebar filters
st.sidebar.header("🎯 Filters")
st.sidebar.markdown("---")

# Date range filter
date_range = st.sidebar.date_input(
    "Select Date Range",
    value=(datetime.now() - timedelta(days=7), datetime.now()),
    max_value=datetime.now()
)

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Attribution Models")
show_models = st.sidebar.multiselect(
    "Select models to display",
    ["First-Click", "Last-Click", "Linear", "Time-Decay", "Shapley Value"],
    default=["First-Click", "Last-Click", "Shapley Value"]
)

st.sidebar.markdown("---")
st.sidebar.subheader("📈 Channel Performance")
st.sidebar.info("""
**ROAS Legend:**
- 🟢 > 50x: Excellent
- 🟡 20-50x: Good
- 🟠 10-20x: Average
- 🔴 < 10x: Needs Review
""")

# ---- MAIN DASHBOARD ----

# Row 1: Key Metrics
col1, col2, col3, col4 = st.columns(4)

# Get metrics
metrics = db.execute("""
    SELECT 
        COUNT(DISTINCT order_id) as total_orders,
        SUM(revenue_usd) as total_revenue,
        COUNT(DISTINCT CASE WHEN publisher != 'organic' THEN order_id END) as attributed_orders,
        SUM(CASE WHEN publisher != 'organic' THEN revenue_usd ELSE 0 END) as attributed_revenue,
        COUNT(DISTINCT publisher) as active_channels
    FROM attribution_comparison
""").fetchone()

with col1:
    st.metric("💰 Total Revenue", f"${metrics[1]:,.2f}", delta=f"{metrics[0]} orders")
with col2:
    st.metric("📈 Attributed Revenue", f"${metrics[3]:,.2f}", delta=f"{metrics[2]} orders")
with col3:
    st.metric("📱 Active Channels", metrics[4], delta="Last 7 days")
with col4:
    attribution_rate = (metrics[2]/metrics[0]*100) if metrics[0] > 0 else 0
    st.metric("🎯 Attribution Rate", f"{attribution_rate:.1f}%", delta="vs organic")

st.divider()

# Row 2: Attribution Model Comparison
st.subheader("📊 Attribution Model Comparison by Channel")

# Get attribution data
attribution_data = db.execute("""
    SELECT 
        publisher,
        AVG(first_click_credit) as first_click,
        AVG(last_click_credit) as last_click,
        AVG(linear_credit) as linear,
        AVG(time_decay_credit) as time_decay,
        AVG(shapley_credit) as shapley
    FROM attribution_comparison
    WHERE publisher != 'organic'
    GROUP BY publisher
    ORDER BY shapley DESC
""").fetchdf()

if not attribution_data.empty:
    # Create comparison chart
    fig = go.Figure()
    
    # Add bars for each model
    model_colors = {
        'first_click': '#FF6B6B',
        'last_click': '#4ECDC4',
        'linear': '#45B7D1',
        'time_decay': '#96CEB4',
        'shapley': '#FFEAA7'
    }
    
    model_names = {
        'first_click': 'First-Click',
        'last_click': 'Last-Click',
        'linear': 'Linear',
        'time_decay': 'Time-Decay',
        'shapley': 'Shapley Value'
    }
    
    for model in ['first_click', 'last_click', 'linear', 'time_decay', 'shapley']:
        if model_names[model] in show_models:
            fig.add_trace(go.Bar(
                name=model_names[model],
                x=attribution_data['publisher'],
                y=attribution_data[model],
                marker_color=model_colors[model],
                text=attribution_data[model].round(2),
                textposition='auto',
            ))
    
    fig.update_layout(
        title="Average Attribution Credit per Channel",
        xaxis_title="Channel",
        yaxis_title="Average Credit ($)",
        barmode='group',
        height=500,
        legend_title="Attribution Model"
    )
    
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# Row 3: Channel Performance & ROAS
col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("📈 Channel Performance Breakdown")
    
    # Get performance metrics
    performance = db.execute("""
        WITH channel_performance AS (
            SELECT 
                publisher,
                COUNT(DISTINCT order_id) as orders,
                SUM(revenue_usd) as revenue,
                COUNT(*) as touchpoints,
                AVG(shapley_credit) as avg_value,
                SUM(shapley_credit) as total_value
            FROM attribution_comparison
            WHERE publisher != 'organic'
            GROUP BY publisher
        )
        SELECT 
            publisher,
            orders,
            revenue,
            touchpoints,
            avg_value,
            total_value,
            CASE 
                WHEN total_value > 0 THEN (revenue / total_value) 
                ELSE 0 
            END as roas
        FROM channel_performance
        ORDER BY revenue DESC
    """).fetchdf()
    
    if not performance.empty:
        # Format metrics
        performance['ROAS'] = performance['roas'].round(2)
        performance['ROAS_Color'] = performance['roas'].apply(
            lambda x: '🟢' if x > 50 else ('🟡' if x > 20 else ('🟠' if x > 10 else '🔴'))
        )
        
        st.dataframe(
            performance[['publisher', 'orders', 'revenue', 'touchpoints', 'ROAS', 'ROAS_Color']],
            column_config={
                "publisher": "Channel",
                "orders": st.column_config.NumberColumn("Orders"),
                "revenue": st.column_config.NumberColumn("Revenue", format="$%.2f"),
                "touchpoints": "Touchpoints",
                "ROAS": st.column_config.NumberColumn("ROAS", format="%.2fx"),
                "ROAS_Color": "Performance"
            },
            hide_index=True,
            use_container_width=True
        )

with col2:
    st.subheader("💡 Actionable Insights")
    
    # Get recommendations
    recommendations = db.execute("""
        SELECT 
            publisher,
            ROUND(AVG(last_click_credit), 2) as last_click,
            ROUND(AVG(shapley_credit), 2) as shapley,
            CASE 
                WHEN AVG(shapley_credit) > AVG(last_click_credit) * 1.1 
                THEN '🚀 Undervalued by Last-Click - Consider increasing budget'
                WHEN AVG(shapley_credit) < AVG(last_click_credit) * 0.9 
                THEN '⚠️ Overvalued by Last-Click - Consider reducing budget'
                ELSE '✅ Fairly valued'
            END as recommendation
        FROM attribution_comparison
        WHERE publisher != 'organic'
        GROUP BY publisher
    """).fetchdf()
    
    if not recommendations.empty:
        for _, row in recommendations.iterrows():
            with st.container():
                st.markdown(f"**{row['publisher']}**")
                st.markdown(f"* Last-Click: ${row['last_click']:.2f}")
                st.markdown(f"* Shapley: ${row['shapley']:.2f}")
                st.markdown(f"* {row['recommendation']}")
                st.markdown("---")

st.divider()

# Row 4: Time Series & Distribution
col1, col2 = st.columns(2)

with col1:
    st.subheader("📉 Attribution Trends Over Time")
    
    # Get time series data - FIXED: using calculation_timestamp instead of attribution_timestamp
    time_series = db.execute("""
        SELECT 
            DATE(calculation_timestamp) as date,
            publisher,
            SUM(shapley_credit) as attributed_value
        FROM attribution_comparison
        WHERE publisher != 'organic'
        GROUP BY date, publisher
        ORDER BY date DESC
        LIMIT 30
    """).fetchdf()
    
    if not time_series.empty:
        fig = px.line(
            time_series,
            x='date',
            y='attributed_value',
            color='publisher',
            title="Attributed Value by Channel Over Time",
            labels={'attributed_value': 'Attributed Value ($)', 'date': 'Date'}
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No time series data available yet. Run the attribution pipeline first!")

with col2:
    st.subheader("🎯 Channel Attribution Distribution")
    
    # Get distribution
    distribution = db.execute("""
        SELECT 
            publisher,
            SUM(shapley_credit) as total_value
        FROM attribution_comparison
        WHERE publisher != 'organic'
        GROUP BY publisher
    """).fetchdf()
    
    if not distribution.empty:
        fig = px.pie(
            distribution,
            values='total_value',
            names='publisher',
            title="Revenue Attribution by Channel (Shapley Value)",
            hole=0.3
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# Footer
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.caption("📊 Dashboard powered by DuckDB + Streamlit")
with col2:
    st.caption("🔍 Attribution Models: First-Click, Last-Click, Linear, Time-Decay, Shapley")
with col3:
    st.caption(f"🔄 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Auto-refresh button
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()
