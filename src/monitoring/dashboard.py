"""
Real-time Streamlit dashboard for QueryKeys Polymarket Bot.

Pages:
  1. Portfolio Overview — equity curve, P&L, drawdown, open positions
  2. Market Scanner — active markets, scores, edges
  3. Predictions — ensemble breakdown per market, model agreement
  4. Orders — live order status, fill history
  5. Risk Monitor — exposure heatmap, category breakdown, alerts
  6. Backtest Results — metrics, MC fan chart, walk-forward

Run: streamlit run src/monitoring/dashboard.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="QueryKeys — Polymarket Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def get_engine():
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/querykeys.db")
    # Use sync engine for Streamlit
    sync_url = db_url.replace("sqlite+aiosqlite:///", "sqlite:///").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    return create_engine(sync_url)


def query_df(sql: str, params: Optional[Dict] = None) -> pd.DataFrame:
    try:
        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except Exception as e:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.image("https://polymarket.com/static/favicon.ico", width=32)
        st.title("QueryKeys")
        st.markdown("**Elite Prediction Market Bot**")
        st.divider()

        mode = os.getenv("BOT_MODE", "paper")
        color = "🟢" if mode == "live" else "🟡"
        st.markdown(f"{color} Mode: **{mode.upper()}**")

        refresh = st.slider("Auto-refresh (s)", 5, 60, 10)
        st.markdown(f"Last refresh: `{datetime.now().strftime('%H:%M:%S')}`")

        page = st.radio(
            "Navigation",
            ["Portfolio", "Markets", "Predictions", "Orders", "Risk", "Backtest"],
        )
        st.divider()
        st.caption("v1.0.0 | QueryKeys")
    return page, refresh


# ---------------------------------------------------------------------------
# Portfolio page
# ---------------------------------------------------------------------------

def render_portfolio():
    st.header("Portfolio Overview")

    df = query_df("""
        SELECT * FROM portfolio_snapshots
        ORDER BY timestamp DESC LIMIT 1000
    """)

    if df.empty:
        st.info("No portfolio data yet. Start the bot to begin trading.")
        _demo_portfolio()
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    latest = df.iloc[-1]

    # KPI row
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Value", f"${latest['total_value']:,.2f}",
                  delta=f"${latest['daily_pnl']:+,.2f} today")
    with col2:
        st.metric("Cash", f"${latest['cash']:,.2f}")
    with col3:
        st.metric("Invested", f"${latest['invested']:,.2f}")
    with col4:
        st.metric("Total P&L", f"${latest['realized_pnl']:+,.2f}",
                  delta=f"${latest['unrealized_pnl']:+,.2f} unrealized")
    with col5:
        dd = latest["drawdown"] * 100
        st.metric("Drawdown", f"{dd:.2f}%",
                  delta=None,
                  delta_color="inverse")

    st.divider()

    # Equity curve
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["total_value"],
        mode="lines", name="Portfolio Value",
        line=dict(color="#00d4aa", width=2),
        fill="tozeroy", fillcolor="rgba(0,212,170,0.1)",
    ))
    fig.update_layout(
        title="Equity Curve",
        xaxis_title="Time",
        yaxis_title="Portfolio Value ($)",
        template="plotly_dark",
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)

    col_left, col_right = st.columns(2)

    # Daily P&L bars
    with col_left:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=df["timestamp"], y=df["daily_pnl"],
            marker_color=["#00d4aa" if v >= 0 else "#ff4b4b" for v in df["daily_pnl"]],
            name="Daily P&L",
        ))
        fig2.update_layout(
            title="Daily P&L", template="plotly_dark", height=280
        )
        st.plotly_chart(fig2, use_container_width=True)

    # Drawdown chart
    with col_right:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=df["timestamp"], y=-df["drawdown"] * 100,
            mode="lines", fill="tozeroy",
            line=dict(color="#ff4b4b"), fillcolor="rgba(255,75,75,0.2)",
            name="Drawdown %",
        ))
        fig3.update_layout(
            title="Drawdown", template="plotly_dark", height=280,
            yaxis_title="Drawdown (%)",
        )
        st.plotly_chart(fig3, use_container_width=True)


def _demo_portfolio():
    """Show demo chart when no data exists."""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    rets = np.random.normal(0.003, 0.02, 100)
    equity = 10000 * np.cumprod(1 + rets)
    fig = px.line(x=dates, y=equity, title="Demo Equity Curve (no live data)",
                  template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Markets page
# ---------------------------------------------------------------------------

def render_markets():
    st.header("Active Markets")

    df = query_df("""
        SELECT condition_id, question, category,
               volume_24h, liquidity, end_date, active
        FROM markets
        WHERE active = 1
        ORDER BY volume_24h DESC
        LIMIT 100
    """)

    if df.empty:
        st.info("No markets scanned yet.")
        return

    df["end_date"] = pd.to_datetime(df["end_date"])
    df["dte"] = (df["end_date"] - pd.Timestamp.now()).dt.days
    df["volume_24h"] = df["volume_24h"].apply(lambda x: f"${x:,.0f}")
    df["liquidity"] = df["liquidity"].apply(lambda x: f"${x:,.0f}")

    # Category filter
    cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
    cat_filter = st.selectbox("Filter by category", cats)
    if cat_filter != "All":
        df = df[df["category"] == cat_filter]

    st.dataframe(
        df[["question", "category", "volume_24h", "liquidity", "dte"]],
        use_container_width=True,
        height=500,
    )

    # Category breakdown pie
    cat_df = query_df("SELECT category, COUNT(*) as count FROM markets GROUP BY category")
    if not cat_df.empty:
        fig = px.pie(cat_df, names="category", values="count",
                     title="Markets by Category", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Predictions page
# ---------------------------------------------------------------------------

def render_predictions():
    st.header("Ensemble Predictions")

    df = query_df("""
        SELECT p.condition_id, p.timestamp, p.yes_probability,
               p.confidence, p.uncertainty, p.edge, p.market_price,
               m.question, m.category
        FROM predictions p
        LEFT JOIN markets m ON p.condition_id = m.condition_id
        ORDER BY p.timestamp DESC
        LIMIT 200
    """)

    if df.empty:
        st.info("No predictions yet.")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["edge_pct"] = (df["edge"] * 100).round(2)

    # Filter: show only predictions with edge
    show_edge_only = st.checkbox("Show only predictions with edge > 2%", value=True)
    if show_edge_only:
        df = df[df["edge"].abs() > 0.02]

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Avg Edge", f"{df['edge_pct'].mean():.2f}%")
    with col2:
        st.metric("Avg Confidence", f"{df['confidence'].mean():.2f}")

    # Scatter: model prob vs market price
    fig = px.scatter(
        df,
        x="market_price",
        y="yes_probability",
        color="edge_pct",
        size="confidence",
        hover_data=["question", "category", "uncertainty"],
        color_continuous_scale="RdYlGn",
        title="Model Probability vs Market Price",
        template="plotly_dark",
    )
    fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1,
                  line=dict(color="white", dash="dash"))
    st.plotly_chart(fig, use_container_width=True)

    # Table
    st.dataframe(
        df[["question", "category", "market_price", "yes_probability",
            "edge_pct", "confidence", "uncertainty"]].head(50),
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Orders page
# ---------------------------------------------------------------------------

def render_orders():
    st.header("Order Management")

    df = query_df("""
        SELECT order_id, condition_id, side, order_type,
               price, size, status, filled_size, avg_fill_price,
               created_at
        FROM orders
        ORDER BY created_at DESC LIMIT 200
    """)

    if df.empty:
        st.info("No orders placed yet.")
        return

    # Status breakdown
    status_counts = df["status"].value_counts()
    col1, col2, col3, col4 = st.columns(4)
    for col, (status, count) in zip([col1, col2, col3, col4], status_counts.items()):
        with col:
            st.metric(status.capitalize(), count)

    # Orders table
    df["fill_pct"] = (df["filled_size"] / df["size"].replace(0, 1) * 100).round(1)
    st.dataframe(
        df[["condition_id", "side", "order_type", "price", "size",
            "status", "fill_pct", "created_at"]],
        use_container_width=True,
        height=400,
    )

    # Status pie
    fig = px.pie(
        values=status_counts.values,
        names=status_counts.index,
        title="Order Status Distribution",
        template="plotly_dark",
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Risk page
# ---------------------------------------------------------------------------

def render_risk():
    st.header("Risk Monitor")

    port_df = query_df("""
        SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1
    """)

    if port_df.empty:
        st.info("No portfolio data yet.")
        return

    latest = port_df.iloc[0]
    bankroll = float(latest["total_value"])

    col1, col2, col3 = st.columns(3)
    with col1:
        exposure = float(latest["invested"]) / max(bankroll, 1)
        color = "normal" if exposure < 0.6 else "inverse"
        st.metric("Portfolio Exposure", f"{exposure:.1%}", delta_color=color)
    with col2:
        dd = float(latest["drawdown"])
        st.metric("Current Drawdown", f"{dd:.2%}",
                  delta=f"{'HALTED' if dd > 0.20 else 'OK'}",
                  delta_color="inverse" if dd > 0.10 else "normal")
    with col3:
        daily_pnl = float(latest["daily_pnl"])
        daily_pct = daily_pnl / max(bankroll, 1)
        st.metric("Daily P&L %", f"{daily_pct:.2%}", delta=f"${daily_pnl:+.2f}")

    # Exposure gauge
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=exposure * 100,
        title={"text": "Portfolio Exposure (%)"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#00d4aa"},
            "steps": [
                {"range": [0, 60], "color": "#1a1a2e"},
                {"range": [60, 80], "color": "#ffa726"},
                {"range": [80, 100], "color": "#ff4b4b"},
            ],
            "threshold": {
                "line": {"color": "white", "width": 4},
                "thickness": 0.75,
                "value": 80,
            },
        },
    ))
    fig.update_layout(template="plotly_dark", height=300)
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Backtest page
# ---------------------------------------------------------------------------

def render_backtest():
    st.header("Backtest Results")

    # Look for latest backtest results JSON
    results_path = Path("data/backtest_results.json")
    if not results_path.exists():
        st.info("No backtest results found. Run: `python scripts/run_backtest.py`")
        return

    with open(results_path) as f:
        data = json.load(f)

    m = data.get("metrics", {})
    mc = data.get("monte_carlo", {})

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Return", f"{m.get('total_return', 0):.1%}")
    with col2:
        st.metric("Sharpe Ratio", f"{m.get('sharpe_ratio', 0):.3f}")
    with col3:
        st.metric("Max Drawdown", f"{m.get('max_drawdown', 0):.1%}")
    with col4:
        st.metric("Win Rate", f"{m.get('win_rate', 0):.1%}")
    with col5:
        st.metric("Brier Score", f"{m.get('brier_score', 0):.4f}")

    st.divider()

    # Equity curve from backtest
    eq = m.get("equity_curve", [])
    if eq:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=eq, mode="lines", name="Backtest Equity",
            line=dict(color="#00d4aa", width=2),
        ))
        fig.update_layout(
            title="Backtest Equity Curve",
            template="plotly_dark", height=350,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Monte Carlo fan chart
    if mc:
        st.subheader("Monte Carlo Confidence Intervals")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Median Final Equity", f"${mc.get('equity_p50', 0):,.0f}")
        with col_b:
            st.metric("90th Pct Final Equity", f"${mc.get('equity_p90', 0):,.0f}")
        with col_c:
            st.metric("Prob. of Ruin", f"{mc.get('prob_ruin', 0):.1%}")

    st.json(data.get("config", {}))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    page, refresh = render_sidebar()

    if page == "Portfolio":
        render_portfolio()
    elif page == "Markets":
        render_markets()
    elif page == "Predictions":
        render_predictions()
    elif page == "Orders":
        render_orders()
    elif page == "Risk":
        render_risk()
    elif page == "Backtest":
        render_backtest()

    # Auto-refresh
    time.sleep(refresh)
    st.rerun()


if __name__ == "__main__":
    main()
