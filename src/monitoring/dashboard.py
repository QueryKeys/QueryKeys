"""
QueryKeys — לוח בקרה מסחרי מודרני
עיצוב כהה מודרני עם תמיכה מלאה בעברית.
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
    page_title="QueryKeys — לוח בקרה",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── ערכות צבעים ──────────────────────────────────────────────────────────────
DARK = {
    "bg":          "#0f172a",
    "bg2":         "#1e293b",
    "bg3":         "#0f172a",
    "text":        "#f1f5f9",
    "text_dim":    "#94a3b8",
    "text_bright": "#ffffff",
    "accent":      "#6366f1",
    "accent2":     "#22d3ee",
    "success":     "#22c55e",
    "danger":      "#ef4444",
    "warning":     "#f59e0b",
    "border":      "#334155",
    "card":        "#1e293b",
    "plot_bg":     "#1e293b",
    "plot_paper":  "#0f172a",
    "plotly_tpl":  "plotly_dark",
    "label":       "🌙 מצב לילה",
}

LIGHT = {
    "bg":          "#f8fafc",
    "bg2":         "#ffffff",
    "bg3":         "#f1f5f9",
    "text":        "#0f172a",
    "text_dim":    "#64748b",
    "text_bright": "#020617",
    "accent":      "#4f46e5",
    "accent2":     "#0891b2",
    "success":     "#16a34a",
    "danger":      "#dc2626",
    "warning":     "#d97706",
    "border":      "#e2e8f0",
    "card":        "#ffffff",
    "plot_bg":     "#ffffff",
    "plot_paper":  "#f8fafc",
    "plotly_tpl":  "plotly_white",
    "label":       "☀️ מצב יום",
}

if "theme" not in st.session_state:
    st.session_state.theme = "dark"


def T() -> dict:
    return DARK if st.session_state.theme == "dark" else LIGHT


# ── CSS מודרני ────────────────────────────────────────────────────────────────
def inject_css():
    c = T()
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif !important;
    background-color: {c['bg']} !important;
    color: {c['text']} !important;
    direction: rtl;
}}

.main .block-container {{
    background-color: {c['bg']} !important;
    padding: 1.5rem 2rem !important;
    max-width: 1400px;
}}

[data-testid="stSidebar"] {{
    background-color: {c['bg2']} !important;
    border-left: 1px solid {c['border']} !important;
    border-right: none !important;
}}
[data-testid="stSidebar"] * {{
    color: {c['text']} !important;
    direction: rtl;
}}

h1, h2, h3, h4 {{
    font-family: 'Inter', sans-serif !important;
    color: {c['text_bright']} !important;
    font-weight: 700 !important;
    letter-spacing: -0.5px !important;
    border-bottom: 2px solid {c['accent']} !important;
    padding-bottom: 8px !important;
    margin-bottom: 16px !important;
}}

[data-testid="metric-container"] {{
    background: {c['card']} !important;
    border: 1px solid {c['border']} !important;
    border-radius: 12px !important;
    padding: 16px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2) !important;
    transition: box-shadow 0.2s !important;
}}
[data-testid="metric-container"]:hover {{
    box-shadow: 0 4px 12px rgba(99,102,241,0.25) !important;
}}
[data-testid="stMetricLabel"] > div {{
    color: {c['text_dim']} !important;
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}}
[data-testid="stMetricValue"] > div {{
    font-size: 1.8rem !important;
    font-weight: 700 !important;
    color: {c['text_bright']} !important;
}}
[data-testid="stMetricDelta"] svg {{ display: none !important; }}
[data-testid="stMetricDelta"] > div {{
    font-size: 0.8rem !important;
    font-weight: 500 !important;
}}

.stButton > button {{
    background: {c['accent']} !important;
    border: none !important;
    color: #ffffff !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    padding: 0.4rem 1rem !important;
    transition: opacity 0.15s !important;
}}
.stButton > button:hover {{
    opacity: 0.85 !important;
}}

.stSelectbox > div > div {{
    background-color: {c['card']} !important;
    border: 1px solid {c['border']} !important;
    border-radius: 8px !important;
    color: {c['text']} !important;
}}

[data-testid="stDataFrame"] {{
    border: 1px solid {c['border']} !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}}

hr {{
    border-color: {c['border']} !important;
    margin: 12px 0 !important;
}}

.stAlert {{
    background-color: {c['card']} !important;
    border: 1px solid {c['border']} !important;
    border-radius: 8px !important;
}}

.stJson {{
    background-color: {c['card']} !important;
    border-radius: 8px !important;
    border: 1px solid {c['border']} !important;
}}

::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: {c['bg']}; }}
::-webkit-scrollbar-thumb {{ background: {c['border']}; border-radius: 3px; }}

/* כרטיס סטטוס */
.status-card {{
    background: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 14px 16px;
    margin: 6px 0;
}}

/* תג מצב */
.badge-online  {{ background: rgba(34,197,94,0.15);  color: #22c55e; border: 1px solid #22c55e44; padding: 3px 10px; border-radius: 999px; font-size: .75rem; font-weight: 600; }}
.badge-offline {{ background: rgba(239,68,68,0.15);  color: #ef4444; border: 1px solid #ef444444; padding: 3px 10px; border-radius: 999px; font-size: .75rem; font-weight: 600; }}
.badge-blitz   {{ background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid #f59e0b44; padding: 3px 10px; border-radius: 999px; font-size: .75rem; font-weight: 600; }}
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


# ── עוזרי ממשק ──────────────────────────────────────────────────────────────
def page_header(title: str, subtitle: str = ""):
    c = T()
    st.markdown(
        f"<div style='margin-bottom:20px'>"
        f"<h2 style='margin:0;font-size:1.5rem'>{title}</h2>"
        + (f"<p style='color:{c['text_dim']};margin:4px 0 0;font-size:.85rem'>{subtitle}</p>" if subtitle else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def kpi_bar(pairs: list[tuple[str, str]]):
    c = T()
    cells = "  ·  ".join(
        f"<span style='color:{c['text_dim']};font-size:.8rem'>{k}:</span> "
        f"<span style='color:{c['text_bright']};font-weight:600;font-size:.85rem'>{v}</span>"
        for k, v in pairs
    )
    st.markdown(
        f"<div style='background:{c['card']};border:1px solid {c['border']};"
        f"border-radius:8px;padding:10px 16px;margin-bottom:16px'>{cells}</div>",
        unsafe_allow_html=True,
    )


def _fig(fig: go.Figure, title: str, h: int = 350) -> go.Figure:
    c = T()
    fig.update_layout(
        title=dict(text=title, font=dict(family="Inter,sans-serif", size=14, color=c["text_dim"])),
        template=c["plotly_tpl"],
        height=h,
        paper_bgcolor=c["plot_paper"],
        plot_bgcolor=c["plot_bg"],
        font=dict(family="Inter,sans-serif", color=c["text"]),
        xaxis=dict(gridcolor=rgba(c["border"], 0.3), linecolor=rgba(c["border"], 0.5)),
        yaxis=dict(gridcolor=rgba(c["border"], 0.3), linecolor=rgba(c["border"], 0.5)),
        margin=dict(l=40, r=20, t=45, b=40),
    )
    return fig


# ── סיידבר ───────────────────────────────────────────────────────────────────
def render_sidebar():
    c = T()
    with st.sidebar:
        # לוגו + כותרת
        st.markdown(
            f"<div style='text-align:center;padding:16px 0 8px'>"
            f"<div style='font-size:1.6rem;font-weight:800;color:{c['text_bright']}'>QueryKeys</div>"
            f"<div style='font-size:.75rem;color:{c['text_dim']};margin-top:2px'>לוח בקרה מסחרי · v1.0</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # מצב תצוגה
        ca, cb = st.columns(2)
        with ca:
            if st.button("🌙 לילה", use_container_width=True):
                st.session_state.theme = "dark"; st.rerun()
        with cb:
            if st.button("☀️ יום", use_container_width=True):
                st.session_state.theme = "light"; st.rerun()

        st.divider()

        # סטטוס הבוט
        bs = bot_status()
        running = bs["running"]
        badge_cls = "badge-online" if running else "badge-offline"
        status_heb = "פעיל" if running else "לא פעיל"
        mode_map = {"paper": "נייר", "live": "חי", "backtest": "בקטסט"}
        mode_heb = mode_map.get(bs.get("mode", "paper"), bs.get("mode", "—"))
        h = int(bs.get("uptime", 0) // 3600)
        m = int((bs.get("uptime", 0) % 3600) // 60)
        st.markdown(
            f"<div class='status-card'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px'>"
            f"<span style='font-weight:600;font-size:.9rem'>🤖 סטטוס הבוט</span>"
            f"<span class='{badge_cls}'>{status_heb}</span></div>"
            f"<div style='font-size:.78rem;color:{c['text_dim']};line-height:1.9'>"
            f"<div>מצב: <strong style='color:{c['text']}'>{mode_heb}</strong></div>"
            f"<div>זמן פעילות: <strong style='color:{c['text']}'>{h:02d}:{m:02d}</strong></div>"
            f"<div>עסקאות היום: <strong style='color:{c['text']}'>{bs.get('trades_today', 0)}</strong></div>"
            f"<div>פוזיציות פתוחות: <strong style='color:{c['text']}'>{bs.get('open_positions', 0)}</strong></div>"
            f"<div style='color:{c['text_dim']};font-size:.72rem;margin-top:4px'>"
            f"עדכון: {datetime.now().strftime('%H:%M:%S')}</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        st.divider()

        # כפתור מצב בלץ
        blitz_on = strategy_enabled("high_conviction_blitz")
        blitz_label = "⚡ בלץ: פעיל" if blitz_on else "⚡ בלץ: כבוי"
        st.markdown(
            f"<div style='font-size:.78rem;font-weight:600;color:{c['text_dim']};margin-bottom:6px'>"
            f"מצב השקעה אגרסיבי</div>",
            unsafe_allow_html=True,
        )
        if st.button(blitz_label, use_container_width=True,
                     help="Kelly 75%, פוזיציה מקסימלית 25%. סיכון גבוה."):
            set_strategy_enabled("high_conviction_blitz", not blitz_on)
            st.rerun()
        risk_heb = "⚠️ סיכון קיצוני — 3 הפסדים יכולים למחוק את החשבון" if blitz_on else "✅ מצב בטוח פעיל"
        risk_color = c["danger"] if blitz_on else c["success"]
        st.markdown(
            f"<div style='font-size:.7rem;color:{risk_color};margin-top:4px'>{risk_heb}</div>",
            unsafe_allow_html=True,
        )

        st.divider()

        refresh = st.slider("רענון (שניות)", 5, 60, 10)
        st.divider()

        page = st.radio(
            "ניווט",
            ["📊 פורטפוליו", "🌐 שווקים", "🔮 תחזיות",
             "📋 הזמנות", "⚠️ סיכונים", "🔬 בקטסט"],
        )
        page = page.split(" ", 1)[1]  # strip emoji

    return page, refresh


# ── פורטפוליו ────────────────────────────────────────────────────────────────
def render_portfolio():
    page_header("📊 סקירת תיק ההשקעות", "ביצועים בזמן אמת")
    c = T()

    df = qdf("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1000")
    if df.empty:
        st.info("⚠️  אין נתוני תיק — הפעל את הבוט כדי להתחיל במסחר")
        _demo_portfolio()
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    lat = df.iloc[-1]

    kpi_bar([
        ("שווי כולל", f"${lat['total_value']:,.2f}"),
        ("רווח/הפסד יומי", f"${lat['daily_pnl']:+,.2f}"),
        ("ירידה מהשיא", f"{lat['drawdown']*100:.2f}%"),
        ("עדכון", datetime.now().strftime("%H:%M:%S")),
    ])

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("שווי כולל",       f"${lat['total_value']:,.2f}", f"${lat['daily_pnl']:+,.2f}")
    with c2: st.metric("מזומן",           f"${lat['cash']:,.2f}")
    with c3: st.metric("מושקע",           f"${lat['invested']:,.2f}")
    with c4: st.metric("רווח/הפסד כולל", f"${lat['realized_pnl']:+,.2f}", f"${lat['unrealized_pnl']:+,.2f} לא ממומש")
    with c5: st.metric("ירידה מהשיא",    f"{lat['drawdown']*100:.2f}%", delta_color="inverse")

    st.divider()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["total_value"],
        mode="lines", name="הון עצמי",
        line=dict(color=c["accent"], width=2.5),
        fill="tozeroy", fillcolor=rgba(c["accent"], 0.08),
    ))
    st.plotly_chart(_fig(fig, "עקומת ההון", 350), use_container_width=True)

    cl, cr = st.columns(2)
    with cl:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=df["timestamp"], y=df["daily_pnl"],
            marker_color=[c["success"] if v >= 0 else c["danger"] for v in df["daily_pnl"]],
            name="רווח/הפסד יומי",
        ))
        st.plotly_chart(_fig(fig2, "רווח/הפסד יומי", 280), use_container_width=True)
    with cr:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=df["timestamp"], y=-df["drawdown"] * 100,
            mode="lines", fill="tozeroy",
            line=dict(color=c["danger"], width=2), fillcolor=rgba(c["danger"], 0.12),
            name="ירידה מהשיא",
        ))
        st.plotly_chart(_fig(fig3, "ירידה מהשיא (%)", 280), use_container_width=True)


def _demo_portfolio():
    c = T()
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    equity = 10000 * np.cumprod(1 + np.random.normal(0.003, 0.02, 100))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=equity, mode="lines",
        line=dict(color=c["accent"], width=2.5),
        fill="tozeroy", fillcolor=rgba(c["accent"], 0.08),
        name="דמו",
    ))
    st.plotly_chart(_fig(fig, "עקומת הון לדוגמה (אין נתונים חיים)", 350), use_container_width=True)


# ── שווקים ───────────────────────────────────────────────────────────────────
def render_markets():
    page_header("🌐 שווקים פעילים", "שווקי Polymarket הנסרקים כעת")
    c = T()

    df = qdf("""
        SELECT condition_id, question, category, volume_24h, liquidity, end_date
        FROM markets WHERE active = 1 ORDER BY volume_24h DESC LIMIT 100
    """)
    if df.empty:
        st.info("⚠️  אין שווקים — הבוט עוד לא סרק")
        return

    df["end_date"] = pd.to_datetime(df["end_date"])
    df["ימים לסיום"] = (df["end_date"] - pd.Timestamp.now()).dt.days
    df["volume_24h"] = df["volume_24h"].apply(lambda x: f"${x:,.0f}")
    df["liquidity"]  = df["liquidity"].apply(lambda x: f"${x:,.0f}")

    cats = ["הכל"] + sorted(df["category"].dropna().unique().tolist())
    sel = st.selectbox("סנן לפי קטגוריה", cats)
    if sel != "הכל":
        df = df[df["category"] == sel]

    st.dataframe(
        df[["question", "category", "volume_24h", "liquidity", "ימים לסיום"]],
        use_container_width=True, height=420,
    )

    cat_df = qdf("SELECT category, COUNT(*) as cnt FROM markets GROUP BY category")
    if not cat_df.empty:
        fig = px.pie(
            cat_df, names="category", values="cnt",
            color_discrete_sequence=[c["accent"], c["accent2"], c["warning"], c["danger"]],
            hole=0.4,
        )
        st.plotly_chart(_fig(fig, "שווקים לפי קטגוריה", 320), use_container_width=True)


# ── תחזיות ───────────────────────────────────────────────────────────────────
def render_predictions():
    page_header("🔮 תחזיות המודל", "ניתוח הרכב המודלים")
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
        st.info("⚠️  אין תחזיות עדיין")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["יתרון (%)"]  = (df["edge"] * 100).round(2)

    if st.checkbox("סנן: יתרון > 2%", value=True):
        df = df[df["edge"].abs() > 0.02]

    col1, col2 = st.columns(2)
    with col1: st.metric("יתרון ממוצע", f"{df['יתרון (%)'].mean():.2f}%")
    with col2: st.metric("ביטחון ממוצע", f"{df['confidence'].mean():.2f}")

    fig = px.scatter(
        df, x="market_price", y="yes_probability",
        color="יתרון (%)", size="confidence",
        hover_data=["question", "category", "uncertainty"],
        color_continuous_scale=[[0, c["danger"]], [0.5, c["warning"]], [1, c["success"]]],
        labels={"market_price": "מחיר שוק", "yes_probability": "הסתברות המודל"},
    )
    fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1,
                  line=dict(color=c["text_dim"], dash="dash", width=1))
    st.plotly_chart(_fig(fig, "הסתברות מודל מול מחיר שוק", 400), use_container_width=True)
    st.dataframe(
        df[["question", "category", "market_price", "yes_probability",
            "יתרון (%)", "confidence", "uncertainty"]].head(50),
        use_container_width=True,
    )


# ── הזמנות ───────────────────────────────────────────────────────────────────
def render_orders():
    page_header("📋 ניהול הזמנות", "היסטוריית עסקאות")
    c = T()

    df = qdf("""
        SELECT order_id, condition_id, side, order_type,
               price, size, status, filled_size, avg_fill_price, created_at
        FROM orders ORDER BY created_at DESC LIMIT 200
    """)
    if df.empty:
        st.info("⚠️  אין הזמנות עדיין")
        return

    status_heb = {"filled": "בוצעה", "open": "פתוחה", "cancelled": "בוטלה", "partial": "חלקית"}
    sc = df["status"].value_counts()
    cols = st.columns(min(4, len(sc)))
    for col, (s, n) in zip(cols, sc.items()):
        with col:
            st.metric(status_heb.get(s, s), n)

    df["אחוז מילוי"] = (df["filled_size"] / df["size"].replace(0, 1) * 100).round(1)
    df["כיוון"] = df["side"].map({"YES": "✅ כן", "NO": "❌ לא"})
    st.dataframe(
        df[["condition_id", "כיוון", "order_type", "price", "size",
            "status", "אחוז מילוי", "created_at"]],
        use_container_width=True, height=380,
    )

    fig = px.pie(
        values=sc.values, names=[status_heb.get(s, s) for s in sc.index],
        color_discrete_sequence=[c["success"], c["warning"], c["danger"], c["accent2"]],
        hole=0.4,
    )
    st.plotly_chart(_fig(fig, "התפלגות סטטוס הזמנות", 300), use_container_width=True)


# ── סיכונים ──────────────────────────────────────────────────────────────────
def render_risk():
    page_header("⚠️ ניטור סיכונים", "חשיפה ומגבלות")
    c = T()

    df = qdf("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1")
    if df.empty:
        st.info("⚠️  אין נתוני תיק עדיין")
        return

    lat      = df.iloc[0]
    bankroll = float(lat["total_value"])
    exposure = float(lat["invested"]) / max(bankroll, 1)
    dd       = float(lat["drawdown"])
    daily    = float(lat["daily_pnl"]) / max(bankroll, 1)

    c1, c2, c3 = st.columns(3)
    with c1: st.metric("חשיפת תיק",       f"{exposure:.1%}", delta_color="normal" if exposure < 0.6 else "inverse")
    with c2: st.metric("ירידה נוכחית",    f"{dd:.2%}", delta="עצור" if dd > 0.20 else "תקין", delta_color="inverse" if dd > 0.10 else "normal")
    with c3: st.metric("רווח/הפסד יומי %", f"{daily:.2%}", delta=f"${float(lat['daily_pnl']):+.2f}")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=exposure * 100,
        title={"text": "חשיפת תיק (%)", "font": {"family": "Inter,sans-serif", "color": c["text"]}},
        number={"font": {"family": "Inter,sans-serif", "color": c["text_bright"]}, "suffix": "%"},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": c["text_dim"]},
            "bar":  {"color": c["accent"]},
            "bgcolor": c["card"],
            "steps": [
                {"range": [0,  60], "color": rgba(c["success"], 0.1)},
                {"range": [60, 80], "color": rgba(c["warning"], 0.2)},
                {"range": [80, 100],"color": rgba(c["danger"],  0.2)},
            ],
            "threshold": {"line": {"color": c["danger"], "width": 3}, "thickness": 0.75, "value": 80},
        },
    ))
    st.plotly_chart(_fig(fig, "מד חשיפת תיק", 320), use_container_width=True)


# ── בקטסט ────────────────────────────────────────────────────────────────────
def render_backtest():
    page_header("🔬 בדיקה היסטורית", "תוצאות Backtesting + Monte Carlo")
    c = T()

    path = Path("data/backtest_results.json")
    if not path.exists():
        st.info("⚠️  אין תוצאות — הרץ: python scripts/run_backtest.py")
        return

    data = json.loads(path.read_text())
    m    = data.get("metrics", {})
    mc   = data.get("monte_carlo", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("תשואה כוללת",  f"{m.get('total_return',0):.1%}")
    with c2: st.metric("Sharpe",        f"{m.get('sharpe_ratio',0):.3f}")
    with c3: st.metric("ירידה מקסימלית", f"{m.get('max_drawdown',0):.1%}")
    with c4: st.metric("אחוז הצלחה",   f"{m.get('win_rate',0):.1%}")
    with c5: st.metric("ציון Brier",    f"{m.get('brier_score',0):.4f}")

    st.divider()

    eq = m.get("equity_curve", [])
    if eq:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=eq, mode="lines", name="הון בקטסט",
            line=dict(color=c["accent"], width=2.5),
            fill="tozeroy", fillcolor=rgba(c["accent"], 0.08),
        ))
        st.plotly_chart(_fig(fig, "עקומת הון — בדיקה היסטורית", 350), use_container_width=True)

    if mc:
        st.subheader("📈 Monte Carlo — רווחי ביטחון")
        ca, cb, cc = st.columns(3)
        with ca: st.metric("הון חציוני (P50)",  f"${mc.get('equity_p50',0):,.0f}")
        with cb: st.metric("הון אופטימי (P90)", f"${mc.get('equity_p90',0):,.0f}")
        with cc: st.metric("הסתברות פשיטת רגל", f"{mc.get('prob_ruin',0):.1%}")

    st.subheader("⚙️ הגדרות הריצה")
    st.json(data.get("config", {}))


# ── ניתוב ראשי ───────────────────────────────────────────────────────────────
def main():
    inject_css()
    page, refresh = render_sidebar()

    routes = {
        "פורטפוליו":     render_portfolio,
        "שווקים":        render_markets,
        "תחזיות":        render_predictions,
        "הזמנות":        render_orders,
        "סיכונים":       render_risk,
        "בקטסט":         render_backtest,
    }
    routes.get(page, render_portfolio)()

    time.sleep(refresh)
    st.rerun()


if __name__ == "__main__":
    main()
