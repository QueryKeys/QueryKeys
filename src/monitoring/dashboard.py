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
    "bg":          "#060B14",
    "bg2":         "#0A1628",
    "bg3":         "#0D1B2A",
    "text":        "#E2E8F0",
    "text_dim":    "#64748B",
    "text_bright": "#F8FAFC",
    "accent":      "#3B82F6",
    "accent2":     "#8B5CF6",
    "success":     "#10B981",
    "danger":      "#F43F5E",
    "warning":     "#F59E0B",
    "border":      "#1E293B",
    "border2":     "#2D3F55",
    "card":        "#0F1E2E",
    "card2":       "#132030",
    "plot_bg":     "#0A1628",
    "plot_paper":  "#060B14",
    "plotly_tpl":  "plotly_dark",
    "label":       "🌙 לילה",
    "grad_start":  "#3B82F6",
    "grad_end":    "#8B5CF6",
}

LIGHT = {
    "bg":          "#F0F4F8",
    "bg2":         "#FFFFFF",
    "bg3":         "#E8EFF5",
    "text":        "#1A202C",
    "text_dim":    "#718096",
    "text_bright": "#000000",
    "accent":      "#2563EB",
    "accent2":     "#7C3AED",
    "success":     "#059669",
    "danger":      "#E11D48",
    "warning":     "#D97706",
    "border":      "#CBD5E1",
    "border2":     "#94A3B8",
    "card":        "#FFFFFF",
    "card2":       "#F8FAFC",
    "plot_bg":     "#FFFFFF",
    "plot_paper":  "#F0F4F8",
    "plotly_tpl":  "plotly_white",
    "label":       "☀️ יום",
    "grad_start":  "#2563EB",
    "grad_end":    "#7C3AED",
}

if "theme" not in st.session_state:
    st.session_state.theme = "dark"


def T() -> dict:
    return DARK if st.session_state.theme == "dark" else LIGHT


# ── CSS פרימיום ───────────────────────────────────────────────────────────────
def inject_css():
    c = T()
    is_dark = st.session_state.theme == "dark"
    sidebar_bg = "linear-gradient(180deg, #0A1628 0%, #060B14 100%)" if is_dark else "linear-gradient(180deg, #FFFFFF 0%, #F0F4F8 100%)"
    card_bg    = "linear-gradient(135deg, #0F1E2E 0%, #0A1628 100%)" if is_dark else "linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%)"

    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');

/* ═══ בסיס ═══ */
html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif !important;
    background-color: {c['bg']} !important;
    color: {c['text']} !important;
    direction: rtl;
}}
.main .block-container {{
    background-color: {c['bg']} !important;
    padding: 1.8rem 2.5rem !important;
    max-width: 1440px;
}}

/* ═══ סיידבר ═══ */
[data-testid="stSidebar"] {{
    background: {sidebar_bg} !important;
    border-left: 1px solid {c['border2']} !important;
    border-right: none !important;
}}
[data-testid="stSidebar"] * {{
    direction: rtl;
    color: {c['text']} !important;
}}

/* ═══ כותרות ═══ */
h1, h2, h3, h4 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.8px !important;
    color: {c['text_bright']} !important;
    border: none !important;
    margin-bottom: 0 !important;
    padding-bottom: 0 !important;
}}

/* ═══ כרטיסי מדד ═══ */
[data-testid="metric-container"] {{
    background: {card_bg} !important;
    border: 1px solid {c['border']} !important;
    border-top: 2px solid {c['accent']} !important;
    border-radius: 14px !important;
    padding: 18px 20px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.25), 0 0 0 1px {c['border']} !important;
    transition: all 0.25s ease !important;
    position: relative !important;
    overflow: hidden !important;
}}
[data-testid="metric-container"]::before {{
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, {c['grad_start']}, {c['grad_end']});
    border-radius: 14px 14px 0 0;
}}
[data-testid="metric-container"]:hover {{
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 32px rgba(59,130,246,0.2), 0 0 0 1px {c['border2']} !important;
    border-top-color: {c['accent2']} !important;
}}
[data-testid="stMetricLabel"] > div {{
    font-family: 'Inter', sans-serif !important;
    color: {c['text_dim']} !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
}}
[data-testid="stMetricValue"] > div {{
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 1.9rem !important;
    font-weight: 700 !important;
    color: {c['text_bright']} !important;
    letter-spacing: -1px !important;
    line-height: 1.1 !important;
}}
[data-testid="stMetricDelta"] svg {{ display: none !important; }}
[data-testid="stMetricDelta"] > div {{
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    margin-top: 4px !important;
}}

/* ═══ כפתורים ═══ */
.stButton > button {{
    background: linear-gradient(135deg, {c['grad_start']}, {c['grad_end']}) !important;
    border: none !important;
    color: #ffffff !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    border-radius: 10px !important;
    padding: 0.45rem 1.2rem !important;
    letter-spacing: 0.3px !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 12px rgba(59,130,246,0.35) !important;
}}
.stButton > button:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(59,130,246,0.5) !important;
    opacity: 0.95 !important;
}}
.stButton > button:active {{
    transform: translateY(0) !important;
}}

/* ═══ סלקטבוקס ═══ */
.stSelectbox > div > div {{
    background: {c['card']} !important;
    border: 1px solid {c['border2']} !important;
    border-radius: 10px !important;
    color: {c['text']} !important;
    font-family: 'Inter', sans-serif !important;
}}

/* ═══ סליידר ═══ */
[data-testid="stSlider"] > div > div > div {{
    background: linear-gradient(90deg, {c['grad_start']}, {c['grad_end']}) !important;
}}

/* ═══ דאטה פריים ═══ */
[data-testid="stDataFrame"] {{
    border: 1px solid {c['border']} !important;
    border-radius: 12px !important;
    overflow: hidden !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15) !important;
}}

/* ═══ חוצה ═══ */
hr {{
    border: none !important;
    height: 1px !important;
    background: linear-gradient(90deg, transparent, {c['border2']}, transparent) !important;
    margin: 14px 0 !important;
}}

/* ═══ אלרט ═══ */
.stAlert {{
    background: {c['card']} !important;
    border: 1px solid {c['border']} !important;
    border-right: 3px solid {c['warning']} !important;
    border-radius: 10px !important;
    font-family: 'Inter', sans-serif !important;
}}

/* ═══ JSON ═══ */
.stJson {{
    background: {c['card']} !important;
    border: 1px solid {c['border']} !important;
    border-radius: 10px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.8rem !important;
}}

/* ═══ סקרולבר ═══ */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: {c['bg']}; }}
::-webkit-scrollbar-thumb {{ background: {c['border2']}; border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: {c['accent']}; }}

/* ═══ כרטיס סטטוס ═══ */
.status-card {{
    background: {card_bg};
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 16px 18px;
    margin: 8px 0;
    box-shadow: 0 4px 16px rgba(0,0,0,0.2);
}}

/* ═══ תגיות ═══ */
.badge-online {{
    display: inline-flex; align-items: center; gap: 5px;
    background: rgba(16,185,129,0.12); color: #10B981;
    border: 1px solid rgba(16,185,129,0.3);
    padding: 3px 12px; border-radius: 999px;
    font-size: .72rem; font-weight: 700; letter-spacing: 0.5px;
}}
.badge-online::before {{
    content: "●";
    animation: live-pulse 1.5s ease-in-out infinite;
}}
.badge-offline {{
    display: inline-flex; align-items: center; gap: 5px;
    background: rgba(244,63,94,0.12); color: #F43F5E;
    border: 1px solid rgba(244,63,94,0.3);
    padding: 3px 12px; border-radius: 999px;
    font-size: .72rem; font-weight: 700;
}}
.badge-offline::before {{ content: "○"; }}

/* ═══ אנימציות ═══ */
@keyframes live-pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.3; }}
}}
@keyframes gradient-shift {{
    0%   {{ background-position: 0% 50%; }}
    50%  {{ background-position: 100% 50%; }}
    100% {{ background-position: 0% 50%; }}
}}
@keyframes fade-up {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}

/* ═══ כותרת עמוד ═══ */
.page-header {{
    animation: fade-up 0.35s ease;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid {c['border']};
}}
.page-header h2 {{
    font-size: 1.6rem !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, {c['grad_start']}, {c['grad_end']});
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 4px !important;
}}
.page-header p {{
    color: {c['text_dim']};
    font-size: .85rem;
    margin: 0;
    font-family: 'Inter', sans-serif;
}}

/* ═══ KPI בר ═══ */
.kpi-bar {{
    background: {card_bg};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 12px 20px;
    margin-bottom: 20px;
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    font-family: 'JetBrains Mono', monospace;
}}
.kpi-item-label {{ color: {c['text_dim']}; font-size: .72rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.8px; }}
.kpi-item-value {{ color: {c['text_bright']}; font-size: .9rem; font-weight: 700; }}

/* ═══ לוגו סיידבר ═══ */
.sidebar-logo {{
    background: linear-gradient(135deg, {c['grad_start']}22, {c['grad_end']}22);
    border: 1px solid {c['border2']};
    border-radius: 16px;
    padding: 16px;
    text-align: center;
    margin-bottom: 8px;
}}
.sidebar-logo-title {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.4rem;
    font-weight: 800;
    background: linear-gradient(135deg, {c['grad_start']}, {c['grad_end']});
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
}}
.sidebar-logo-sub {{
    font-size: .68rem;
    color: {c['text_dim']};
    margin-top: 2px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

/* ═══ רדיו ניווט ═══ */
[data-testid="stRadio"] label {{
    font-family: 'Inter', sans-serif !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
    padding: 6px 10px !important;
    border-radius: 8px !important;
    transition: background 0.15s !important;
}}
[data-testid="stRadio"] label:hover {{
    background: {c['border']}44 !important;
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


# ── עוזרי ממשק ──────────────────────────────────────────────────────────────
def page_header(title: str, subtitle: str = ""):
    st.markdown(
        f"<div class='page-header'><h2>{title}</h2>"
        + (f"<p>{subtitle}</p>" if subtitle else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def kpi_bar(pairs: list[tuple[str, str]]):
    items = "".join(
        f"<div style='display:flex;flex-direction:column;gap:2px'>"
        f"<span class='kpi-item-label'>{k}</span>"
        f"<span class='kpi-item-value'>{v}</span></div>"
        for k, v in pairs
    )
    st.markdown(f"<div class='kpi-bar'>{items}</div>", unsafe_allow_html=True)


def _fig(fig: go.Figure, title: str, h: int = 350) -> go.Figure:
    c = T()
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(family="Space Grotesk, sans-serif", size=13, color=c["text_dim"]),
            x=0, xanchor="left", pad=dict(l=4),
        ),
        template=c["plotly_tpl"],
        height=h,
        paper_bgcolor=c["plot_paper"],
        plot_bgcolor=c["plot_bg"],
        font=dict(family="JetBrains Mono, monospace", size=11, color=c["text"]),
        xaxis=dict(
            gridcolor=rgba(c["border2"], 0.4),
            linecolor=rgba(c["border2"], 0.6),
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            gridcolor=rgba(c["border2"], 0.4),
            linecolor=rgba(c["border2"], 0.6),
            tickfont=dict(size=10),
        ),
        margin=dict(l=44, r=16, t=40, b=36),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
        ),
    )
    return fig


# ── סיידבר ───────────────────────────────────────────────────────────────────
def render_sidebar():
    c = T()
    with st.sidebar:
        # לוגו
        st.markdown(
            "<div class='sidebar-logo'>"
            "<div class='sidebar-logo-title'>⬡ QueryKeys</div>"
            "<div class='sidebar-logo-sub'>Polymarket Intelligence · v1.0</div>"
            "</div>",
            unsafe_allow_html=True,
        )

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
