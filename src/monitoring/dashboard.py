"""
QueryKeys — Retro Terminal Dashboard
Phosphor-green CRT aesthetic with Dark / Light mode toggle.
Run: streamlit run src/monitoring/dashboard.py
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

HEARTBEAT_FILE = Path("data/bot_heartbeat.json")
HEARTBEAT_STALE_SECS = 30   # bot is considered dead if no update in 30s
STRATEGIES_YAML = Path("config/strategies.yaml")

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text


def rgba(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' + alpha float to 'rgba(r,g,b,alpha)' for Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

# ── page config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(
    page_title="QueryKeys // TERMINAL",
    page_icon="⌨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── theme definitions ────────────────────────────────────────────────────────
DARK = {
    "bg":           "#0a0a0a",
    "bg2":          "#0d1117",
    "text":         "#00ff41",
    "text_dim":     "#008f11",
    "text_bright":  "#ccffcc",
    "accent":       "#00ff41",
    "accent2":      "#00d4aa",
    "danger":       "#ff3333",
    "warning":      "#ffaa00",
    "border":       "#00ff41",
    "card":         "#0a1a0a",
    "plot_bg":      "#0a0a0a",
    "plot_paper":   "#0d1117",
    "plotly_tpl":   "plotly_dark",
    "glow":         "#00ff41",
    "scanline":     "rgba(0,255,65,0.03)",
    "label":        "◉ DARK MODE",
}

LIGHT = {
    "bg":           "#f0ede0",
    "bg2":          "#e4e0cc",
    "text":         "#1a4a1a",
    "text_dim":     "#4a7a4a",
    "text_bright":  "#0a200a",
    "accent":       "#1a6a1a",
    "accent2":      "#1a6644",
    "danger":       "#cc1111",
    "warning":      "#cc7700",
    "border":       "#2a7a2a",
    "card":         "#dde8cc",
    "plot_bg":      "#f0ede0",
    "plot_paper":   "#e4e0cc",
    "plotly_tpl":   "plotly_white",
    "glow":         "#2a7a2a",
    "scanline":     "rgba(0,80,0,0.04)",
    "label":        "◎ LIGHT MODE",
}

if "theme" not in st.session_state:
    st.session_state.theme = "dark"


def T() -> dict:
    return DARK if st.session_state.theme == "dark" else LIGHT


# ── CSS injection ────────────────────────────────────────────────────────────
def inject_css():
    c = T()
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=VT323:wght@400&display=swap');

/* ── global ── */
html, body, [class*="css"] {{
    font-family: 'Share Tech Mono', 'Courier New', monospace !important;
    background-color: {c['bg']} !important;
    color: {c['text']} !important;
}}

/* ── scanlines overlay ── */
.main::before {{
    content: "";
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: repeating-linear-gradient(
        0deg,
        {c['scanline']} 0px, {c['scanline']} 1px,
        transparent 1px, transparent 3px
    );
    pointer-events: none;
    z-index: 9999;
}}

/* ── vignette ── */
.main::after {{
    content: "";
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.45) 100%);
    pointer-events: none;
    z-index: 9998;
}}

/* ── main content area ── */
.main .block-container {{
    background-color: {c['bg']} !important;
    padding: 1.5rem 2rem !important;
}}

/* ── sidebar ── */
[data-testid="stSidebar"] {{
    background-color: {c['bg2']} !important;
    border-right: 1px solid {c['border']} !important;
    box-shadow: 4px 0 24px {c['glow']}22 !important;
}}
[data-testid="stSidebar"] * {{
    font-family: 'Share Tech Mono', monospace !important;
    color: {c['text']} !important;
}}

/* ── headers ── */
h1, h2, h3, h4 {{
    font-family: 'VT323', monospace !important;
    color: {c['text']} !important;
    text-shadow: 0 0 8px {c['glow']}99, 0 0 18px {c['glow']}44 !important;
    letter-spacing: 4px !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid {c['border']}55 !important;
    padding-bottom: 6px !important;
}}

/* ── metric cards ── */
[data-testid="metric-container"] {{
    background-color: {c['card']} !important;
    border: 1px solid {c['border']} !important;
    border-radius: 0 !important;
    padding: 14px !important;
    box-shadow: 0 0 12px {c['glow']}33, inset 0 0 8px {c['glow']}0d !important;
    animation: pulse-glow 4s ease-in-out infinite !important;
}}
[data-testid="stMetricLabel"] > div {{
    color: {c['text_dim']} !important;
    font-size: 0.72rem !important;
    letter-spacing: 3px !important;
    text-transform: uppercase !important;
}}
[data-testid="stMetricValue"] > div {{
    font-family: 'VT323', monospace !important;
    font-size: 2.1rem !important;
    color: {c['text_bright']} !important;
    text-shadow: 0 0 10px {c['glow']}bb !important;
}}
[data-testid="stMetricDelta"] svg {{ display: none !important; }}
[data-testid="stMetricDelta"] > div {{
    color: {c['accent2']} !important;
    font-size: 0.72rem !important;
    letter-spacing: 1px !important;
}}

/* ── buttons ── */
.stButton > button {{
    background: transparent !important;
    border: 1px solid {c['border']} !important;
    color: {c['text']} !important;
    font-family: 'Share Tech Mono', monospace !important;
    border-radius: 0 !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    box-shadow: 0 0 8px {c['glow']}44 !important;
    transition: all 0.15s !important;
}}
.stButton > button:hover {{
    background: {c['accent']}22 !important;
    box-shadow: 0 0 18px {c['glow']}99 !important;
    color: {c['text_bright']} !important;
}}

/* ── selectbox / checkbox ── */
.stSelectbox > div > div,
.stCheckbox > label {{
    background-color: {c['card']} !important;
    border: 1px solid {c['border']}88 !important;
    border-radius: 0 !important;
    color: {c['text']} !important;
}}

/* ── dataframe ── */
[data-testid="stDataFrame"] {{
    border: 1px solid {c['border']}66 !important;
    box-shadow: 0 0 12px {c['glow']}22 !important;
}}

/* ── divider ── */
hr {{
    border-color: {c['border']}55 !important;
    box-shadow: 0 0 6px {c['glow']}44 !important;
}}

/* ── info / alert ── */
.stAlert {{
    background-color: {c['card']} !important;
    border: 1px solid {c['border']}88 !important;
    border-radius: 0 !important;
}}

/* ── radio ── */
[data-testid="stRadio"] label {{
    font-family: 'Share Tech Mono', monospace !important;
}}

/* ── json ── */
.stJson {{
    background-color: {c['card']} !important;
    border: 1px solid {c['border']}44 !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.8rem !important;
}}

/* ── scrollbar ── */
::-webkit-scrollbar {{ width: 5px; }}
::-webkit-scrollbar-track {{ background: {c['bg']}; }}
::-webkit-scrollbar-thumb {{ background: {c['border']}55; }}
::-webkit-scrollbar-thumb:hover {{ background: {c['border']}; }}

/* ── blink cursor ── */
@keyframes blink {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0; }}
}}
.cursor {{
    display: inline-block;
    width: 10px; height: 1.1em;
    background: {c['text']};
    animation: blink 1.1s step-start infinite;
    vertical-align: text-bottom;
    margin-left: 3px;
}}

/* ── glow pulse on cards ── */
@keyframes pulse-glow {{
    0%, 100% {{ box-shadow: 0 0 8px {c['glow']}33, inset 0 0 6px {c['glow']}0d; }}
    50%  {{ box-shadow: 0 0 20px {c['glow']}66, inset 0 0 12px {c['glow']}1a; }}
}}
</style>
""", unsafe_allow_html=True)


# ── DB helpers ───────────────────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/querykeys.db")
    sync_url = (db_url
                .replace("sqlite+aiosqlite:///", "sqlite:///")
                .replace("postgresql+asyncpg://", "postgresql://"))
    return create_engine(sync_url)


def qdf(sql: str, params: Optional[Dict] = None) -> pd.DataFrame:
    try:
        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except Exception:
        return pd.DataFrame()


def bot_status() -> dict:
    """Read bot heartbeat file. Returns status dict."""
    if not HEARTBEAT_FILE.exists():
        return {"running": False, "reason": "no heartbeat file"}
    try:
        data = json.loads(HEARTBEAT_FILE.read_text())
        ts = data.get("timestamp", 0)
        age = time.time() - ts
        running = age < HEARTBEAT_STALE_SECS
        return {
            "running": running,
            "age_secs": round(age),
            "mode": data.get("mode", "unknown"),
            "uptime": data.get("uptime_secs", 0),
            "trades_today": data.get("trades_today", 0),
            "open_positions": data.get("open_positions", 0),
            "last_scan": data.get("last_scan", "—"),
            "reason": "stale" if not running else "ok",
        }
    except Exception:
        return {"running": False, "reason": "parse error"}


def strategy_enabled(name: str) -> bool:
    """Return True if the named strategy is enabled in strategies.yaml."""
    if not STRATEGIES_YAML.exists():
        return False
    text = STRATEGIES_YAML.read_text()
    # Find the block for this strategy and check its enabled flag
    pattern = rf'name:\s*["\']?{re.escape(name)}["\']?.*?enabled:\s*(true|false)'
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).lower() == "true" if m else False


def set_strategy_enabled(name: str, enabled: bool) -> None:
    """Toggle enabled: true/false for a named strategy in strategies.yaml."""
    if not STRATEGIES_YAML.exists():
        return
    text = STRATEGIES_YAML.read_text()
    # Replace the enabled line within the named strategy's block only
    # We do a two-pass: find the name anchor, then flip the next enabled line
    lines = text.splitlines()
    in_block = False
    result = []
    for line in lines:
        if re.search(rf'name:\s*["\']?{re.escape(name)}["\']?', line):
            in_block = True
        if in_block and re.match(r'\s+enabled:\s*(true|false)', line):
            line = re.sub(r'(enabled:\s*)(true|false)', f'\\g<1>{"true" if enabled else "false"}', line)
            in_block = False  # only flip the first occurrence
        result.append(line)
    STRATEGIES_YAML.write_text("\n".join(result))


# ── UI helpers ───────────────────────────────────────────────────────────────
def term_header(title: str, level: int = 1):
    c = T()
    tag = f"h{level}"
    prefix = "██" if level == 1 else "▶▶"
    st.markdown(
        f"<{tag} style='font-family:VT323,monospace;color:{c['text']};"
        f"text-shadow:0 0 10px {c['glow']}99;letter-spacing:4px;"
        f"border-bottom:1px solid {c['border']}55;padding-bottom:6px;'>"
        f"{prefix} {title.upper()} <span class='cursor'></span></{tag}>",
        unsafe_allow_html=True,
    )


def status_bar(pairs: list[tuple[str, str]]):
    c = T()
    cells = "  │  ".join(
        f"<span style='color:{c['text_dim']}'>{k}:</span>"
        f"<span style='color:{c['text_bright']};margin-left:4px'>{v}</span>"
        for k, v in pairs
    )
    st.markdown(
        f"<div style='font-family:Share Tech Mono,monospace;font-size:.78rem;"
        f"padding:6px 12px;background:{c['card']};border:1px solid {c['border']}44;"
        f"margin-bottom:14px;letter-spacing:1px;'>▸ {cells}</div>",
        unsafe_allow_html=True,
    )


def _fig(fig: go.Figure, title: str, h: int = 350) -> go.Figure:
    c = T()
    fig.update_layout(
        title=dict(
            text=f"▶  {title.upper()}",
            font=dict(family="VT323,monospace", size=20, color=c["text"]),
        ),
        template=c["plotly_tpl"],
        height=h,
        paper_bgcolor=c["plot_paper"],
        plot_bgcolor=c["plot_bg"],
        font=dict(family="Share Tech Mono,monospace", color=c["text"]),
        xaxis=dict(gridcolor=rgba(c["border"], 0.1), linecolor=rgba(c["border"], 0.33)),
        yaxis=dict(gridcolor=rgba(c["border"], 0.1), linecolor=rgba(c["border"], 0.33)),
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


# ── sidebar ──────────────────────────────────────────────────────────────────
def render_sidebar():
    c = T()
    with st.sidebar:
        # ASCII logo
        st.markdown(
            f"<pre style='color:{c['text']};font-size:.65rem;line-height:1.25;"
            f"text-shadow:0 0 8px {c['glow']}88;text-align:center;margin:0 0 4px;'>"
            " ██████  ██   ██\n"
            "██    ██ ██  ██ \n"
            "██    ██ █████  \n"
            "██ ▄▄ ██ ██  ██ \n"
            " ██████  ██   ██\n"
            "    ▀▀           </pre>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='text-align:center;font-size:.68rem;letter-spacing:3px;"
            f"color:{c['text_dim']};margin-bottom:10px'>QUERYKEYS v1.0.0</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<hr style='border-color:{c['border']}44;margin:6px 0'>", unsafe_allow_html=True)

        # theme toggle
        ca, cb = st.columns(2)
        with ca:
            if st.button("◐ DARK", use_container_width=True):
                st.session_state.theme = "dark"
                st.rerun()
        with cb:
            if st.button("◑ LIGHT", use_container_width=True):
                st.session_state.theme = "light"
                st.rerun()
        st.markdown(
            f"<div style='text-align:center;font-size:.68rem;color:{c['text_dim']};"
            f"margin:4px 0 8px'>{c['label']}</div>",
            unsafe_allow_html=True,
        )

        st.markdown(f"<hr style='border-color:{c['border']}44;margin:6px 0'>", unsafe_allow_html=True)

        # bot status
        bs = bot_status()
        running = bs["running"]
        dot_col  = c["accent"] if running else c["danger"]
        dot_anim = "animation:pulse-glow 1s ease-in-out infinite;" if running else ""
        status_label = "ONLINE" if running else "OFFLINE"
        mode = bs.get("mode", os.getenv("BOT_MODE", "paper")).upper()
        st.markdown(
            f"<div style='background:{c['card']};border:1px solid {dot_col}55;"
            f"border-radius:4px;padding:8px 10px;margin:4px 0'>"
            f"<div style='font-size:.9rem;font-weight:bold;letter-spacing:2px;"
            f"color:{dot_col};text-shadow:0 0 8px {dot_col};{dot_anim}'>"
            f"● BOT: {status_label}</div>"
            f"<div style='font-size:.70rem;color:{c['text_dim']};margin-top:4px;line-height:1.7'>"
            f"MODE&nbsp;&nbsp;&nbsp;: {mode}<br>"
            f"UPTIME : {int(bs.get('uptime',0)//3600):02d}h {int((bs.get('uptime',0)%3600)//60):02d}m<br>"
            f"TRADES : {bs.get('trades_today',0)} today<br>"
            f"POS&nbsp;&nbsp;&nbsp;&nbsp;: {bs.get('open_positions',0)} open<br>"
            f"LAST&nbsp;&nbsp;&nbsp;: {str(bs.get('last_scan','—'))[:19]}"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-size:.72rem;color:{c['text_dim']};padding:2px'>"
            f"SYS_CLOCK: {datetime.now().strftime('%H:%M:%S')}</div>",
            unsafe_allow_html=True,
        )

        st.markdown(f"<hr style='border-color:{c['border']}44;margin:8px 0'>", unsafe_allow_html=True)

        # ── Blitz mode toggle ──────────────────────────────────────────
        blitz_on = strategy_enabled("high_conviction_blitz")
        blitz_col = c["danger"] if blitz_on else c["text_dim"]
        blitz_label = "⚡ BLITZ: ON" if blitz_on else "⚡ BLITZ: OFF"
        st.markdown(
            f"<div style='font-size:.72rem;letter-spacing:1px;color:{c['text_dim']};margin-bottom:3px'>"
            f"HIGH CONVICTION MODE</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            blitz_label,
            use_container_width=True,
            help="75% Kelly sizing, 25% max position. High risk/reward.",
        ):
            set_strategy_enabled("high_conviction_blitz", not blitz_on)
            st.rerun()
        risk_txt = "⚠ EXTREME RISK — account can wipe in 3 bad trades" if blitz_on else "Safe mode active"
        st.markdown(
            f"<div style='font-size:.63rem;color:{blitz_col};margin-top:2px;margin-bottom:4px'>"
            f"{risk_txt}</div>",
            unsafe_allow_html=True,
        )

        st.markdown(f"<hr style='border-color:{c['border']}44;margin:8px 0'>", unsafe_allow_html=True)
        refresh = st.slider("REFRESH (s)", 5, 60, 10)
        st.markdown(f"<hr style='border-color:{c['border']}44;margin:8px 0'>", unsafe_allow_html=True)

        page = st.radio(
            "NAV",
            ["▸ PORTFOLIO", "▸ MARKETS", "▸ PREDICTIONS",
             "▸ ORDERS", "▸ RISK", "▸ BACKTEST"],
        )
        page = page.replace("▸ ", "")

    return page, refresh


# ── portfolio ────────────────────────────────────────────────────────────────
def render_portfolio():
    term_header("Portfolio Overview")
    c = T()

    df = qdf("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1000")
    if df.empty:
        st.info("⚠  NO PORTFOLIO DATA — START THE BOT TO BEGIN TRADING")
        _demo_portfolio()
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    lat = df.iloc[-1]

    status_bar([
        ("TOTAL", f"${lat['total_value']:,.2f}"),
        ("DAILY_PNL", f"${lat['daily_pnl']:+,.2f}"),
        ("DRAWDOWN", f"{lat['drawdown']*100:.2f}%"),
        ("CLOCK", datetime.now().strftime("%H:%M:%S")),
    ])

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("TOTAL VALUE",  f"${lat['total_value']:,.2f}", f"${lat['daily_pnl']:+,.2f}")
    with c2: st.metric("CASH",         f"${lat['cash']:,.2f}")
    with c3: st.metric("INVESTED",     f"${lat['invested']:,.2f}")
    with c4: st.metric("TOTAL P&L",    f"${lat['realized_pnl']:+,.2f}", f"${lat['unrealized_pnl']:+,.2f} unrlzd")
    with c5: st.metric("DRAWDOWN",     f"{lat['drawdown']*100:.2f}%", delta_color="inverse")

    st.divider()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["total_value"],
        mode="lines", name="EQUITY",
        line=dict(color=c["accent"], width=2),
        fill="tozeroy", fillcolor=rgba(c["accent"], 0.1),
    ))
    st.plotly_chart(_fig(fig, "Equity Curve", 350), use_container_width=True)

    cl, cr = st.columns(2)
    with cl:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=df["timestamp"], y=df["daily_pnl"],
            marker_color=[c["accent"] if v >= 0 else c["danger"] for v in df["daily_pnl"]],
            name="DAILY P&L",
        ))
        st.plotly_chart(_fig(fig2, "Daily P&L", 280), use_container_width=True)
    with cr:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=df["timestamp"], y=-df["drawdown"] * 100,
            mode="lines", fill="tozeroy",
            line=dict(color=c["danger"]), fillcolor=rgba(c["danger"], 0.16),
            name="DRAWDOWN",
        ))
        st.plotly_chart(_fig(fig3, "Drawdown %", 280), use_container_width=True)


def _demo_portfolio():
    c = T()
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    equity = 10000 * np.cumprod(1 + np.random.normal(0.003, 0.02, 100))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=equity, mode="lines",
        line=dict(color=c["accent"], width=2),
        fill="tozeroy", fillcolor=rgba(c["accent"], 0.1),
        name="DEMO",
    ))
    st.plotly_chart(_fig(fig, "Demo Equity Curve (no live data)", 350), use_container_width=True)


# ── markets ──────────────────────────────────────────────────────────────────
def render_markets():
    term_header("Active Markets")
    c = T()

    df = qdf("""
        SELECT condition_id, question, category, volume_24h, liquidity, end_date
        FROM markets WHERE active = 1 ORDER BY volume_24h DESC LIMIT 100
    """)
    if df.empty:
        st.info("⚠  NO MARKETS SCANNED YET")
        return

    df["end_date"] = pd.to_datetime(df["end_date"])
    df["DTE"] = (df["end_date"] - pd.Timestamp.now()).dt.days
    df["volume_24h"] = df["volume_24h"].apply(lambda x: f"${x:,.0f}")
    df["liquidity"]  = df["liquidity"].apply(lambda x: f"${x:,.0f}")

    cats = ["ALL"] + sorted(df["category"].dropna().unique().tolist())
    sel = st.selectbox("FILTER_CATEGORY", cats)
    if sel != "ALL":
        df = df[df["category"] == sel]

    st.dataframe(
        df[["question", "category", "volume_24h", "liquidity", "DTE"]],
        use_container_width=True, height=450,
    )

    cat_df = qdf("SELECT category, COUNT(*) as cnt FROM markets GROUP BY category")
    if not cat_df.empty:
        fig = px.pie(
            cat_df, names="category", values="cnt",
            color_discrete_sequence=[c["accent"], c["accent2"], c["warning"], c["danger"]],
        )
        st.plotly_chart(_fig(fig, "Markets by Category", 320), use_container_width=True)


# ── predictions ──────────────────────────────────────────────────────────────
def render_predictions():
    term_header("Ensemble Predictions")
    c = T()

    df = qdf("""
        SELECT p.condition_id, p.timestamp, p.yes_probability,
               p.confidence, p.uncertainty, p.edge, p.market_price,
               m.question, m.category
        FROM predictions p
        LEFT JOIN markets m ON p.condition_id = m.condition_id
        ORDER BY p.timestamp DESC LIMIT 200
    """)
    if df.empty:
        st.info("⚠  NO PREDICTIONS YET")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["edge_pct"]  = (df["edge"] * 100).round(2)

    if st.checkbox("FILTER: EDGE > 2%", value=True):
        df = df[df["edge"].abs() > 0.02]

    col1, col2 = st.columns(2)
    with col1: st.metric("AVG EDGE",       f"{df['edge_pct'].mean():.2f}%")
    with col2: st.metric("AVG CONFIDENCE", f"{df['confidence'].mean():.2f}")

    fig = px.scatter(
        df, x="market_price", y="yes_probability",
        color="edge_pct", size="confidence",
        hover_data=["question", "category", "uncertainty"],
        color_continuous_scale=[[0, c["danger"]], [0.5, c["warning"]], [1, c["accent"]]],
    )
    fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1,
                  line=dict(color=c["text_dim"], dash="dash"))
    st.plotly_chart(_fig(fig, "Model Probability vs Market Price", 400), use_container_width=True)
    st.dataframe(
        df[["question", "category", "market_price", "yes_probability",
            "edge_pct", "confidence", "uncertainty"]].head(50),
        use_container_width=True,
    )


# ── orders ───────────────────────────────────────────────────────────────────
def render_orders():
    term_header("Order Management")
    c = T()

    df = qdf("""
        SELECT order_id, condition_id, side, order_type,
               price, size, status, filled_size, avg_fill_price, created_at
        FROM orders ORDER BY created_at DESC LIMIT 200
    """)
    if df.empty:
        st.info("⚠  NO ORDERS PLACED YET")
        return

    sc = df["status"].value_counts()
    cols = st.columns(min(4, len(sc)))
    for col, (s, n) in zip(cols, sc.items()):
        with col:
            st.metric(s.upper(), n)

    df["fill_pct"] = (df["filled_size"] / df["size"].replace(0, 1) * 100).round(1)
    st.dataframe(
        df[["condition_id", "side", "order_type", "price", "size",
            "status", "fill_pct", "created_at"]],
        use_container_width=True, height=400,
    )

    fig = px.pie(
        values=sc.values, names=sc.index,
        color_discrete_sequence=[c["accent"], c["warning"], c["danger"], c["accent2"]],
    )
    st.plotly_chart(_fig(fig, "Order Status Distribution", 300), use_container_width=True)


# ── risk ─────────────────────────────────────────────────────────────────────
def render_risk():
    term_header("Risk Monitor")
    c = T()

    df = qdf("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1")
    if df.empty:
        st.info("⚠  NO PORTFOLIO DATA YET")
        return

    lat      = df.iloc[0]
    bankroll = float(lat["total_value"])
    exposure = float(lat["invested"]) / max(bankroll, 1)
    dd       = float(lat["drawdown"])
    daily    = float(lat["daily_pnl"]) / max(bankroll, 1)

    c1, c2, c3 = st.columns(3)
    with c1: st.metric("PORTFOLIO EXPOSURE", f"{exposure:.1%}", delta_color="normal" if exposure < 0.6 else "inverse")
    with c2: st.metric("CURRENT DRAWDOWN",   f"{dd:.2%}", delta="HALTED" if dd > 0.20 else "OK", delta_color="inverse" if dd > 0.10 else "normal")
    with c3: st.metric("DAILY P&L %",        f"{daily:.2%}", delta=f"${float(lat['daily_pnl']):+.2f}")

    safe_bg = "#0a1a0a" if st.session_state.theme == "dark" else "#dde8cc"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=exposure * 100,
        title={"text": "PORTFOLIO EXPOSURE (%)",
               "font": {"family": "VT323,monospace", "color": c["text"]}},
        number={"font": {"family": "VT323,monospace", "color": c["text"]}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": c["text_dim"]},
            "bar":  {"color": c["accent"]},
            "bgcolor": safe_bg,
            "steps": [
                {"range": [0,  60], "color": safe_bg},
                {"range": [60, 80], "color": rgba(c["warning"], 0.27)},
                {"range": [80, 100],"color": rgba(c["danger"], 0.27)},
            ],
            "threshold": {
                "line": {"color": c["warning"], "width": 3},
                "thickness": 0.75, "value": 80,
            },
        },
    ))
    st.plotly_chart(_fig(fig, "Exposure Gauge", 320), use_container_width=True)


# ── backtest ─────────────────────────────────────────────────────────────────
def render_backtest():
    term_header("Backtest Results")
    c = T()

    path = Path("data/backtest_results.json")
    if not path.exists():
        st.info("⚠  NO BACKTEST RESULTS — RUN: python scripts/run_backtest.py")
        return

    data = json.loads(path.read_text())
    m    = data.get("metrics", {})
    mc   = data.get("monte_carlo", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("TOTAL RETURN", f"{m.get('total_return',0):.1%}")
    with c2: st.metric("SHARPE",       f"{m.get('sharpe_ratio',0):.3f}")
    with c3: st.metric("MAX DD",       f"{m.get('max_drawdown',0):.1%}")
    with c4: st.metric("WIN RATE",     f"{m.get('win_rate',0):.1%}")
    with c5: st.metric("BRIER",        f"{m.get('brier_score',0):.4f}")

    st.divider()

    eq = m.get("equity_curve", [])
    if eq:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=eq, mode="lines", name="BT_EQUITY",
            line=dict(color=c["accent"], width=2),
            fill="tozeroy", fillcolor=rgba(c["accent"], 0.1),
        ))
        st.plotly_chart(_fig(fig, "Backtest Equity Curve", 350), use_container_width=True)

    if mc:
        term_header("Monte Carlo Confidence Intervals", level=2)
        ca, cb, cc = st.columns(3)
        with ca: st.metric("MEDIAN EQUITY", f"${mc.get('equity_p50',0):,.0f}")
        with cb: st.metric("P90 EQUITY",    f"${mc.get('equity_p90',0):,.0f}")
        with cc: st.metric("PROB RUIN",     f"{mc.get('prob_ruin',0):.1%}")

    st.json(data.get("config", {}))


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    inject_css()
    page, refresh = render_sidebar()

    routes = {
        "PORTFOLIO":   render_portfolio,
        "MARKETS":     render_markets,
        "PREDICTIONS": render_predictions,
        "ORDERS":      render_orders,
        "RISK":        render_risk,
        "BACKTEST":    render_backtest,
    }
    routes.get(page, render_portfolio)()

    time.sleep(refresh)
    st.rerun()


if __name__ == "__main__":
    main()
