"""
Streamlit Store Intelligence Dashboard
Real-time analytics for retail CCTV monitoring.
"""
from __future__ import annotations

import os
import time
from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
REFRESH_INTERVAL = 30  # seconds

st.set_page_config(
    page_title="Store Intelligence System",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .main { background: #0f1117; }

    .metric-card {
        background: linear-gradient(135deg, #1a1f2e 0%, #252b3b 100%);
        border: 1px solid #2d3650;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin: 4px;
    }
    .metric-value {
        font-size: 2.4rem;
        font-weight: 700;
        color: #a78bfa;
        line-height: 1.2;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #94a3b8;
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .metric-delta {
        font-size: 0.8rem;
        color: #34d399;
        margin-top: 2px;
    }
    .anomaly-badge {
        background: #7f1d1d;
        color: #fca5a5;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #34d399;
        margin-right: 6px;
    }
    .header-gradient {
        background: linear-gradient(90deg, #7c3aed 0%, #a78bfa 50%, #c4b5fd 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2rem;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── API helpers ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_metrics() -> dict:
    try:
        r = httpx.get(f"{API_BASE}/metrics", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_funnel() -> dict:
    try:
        r = httpx.get(f"{API_BASE}/metrics/funnel", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_events(page: int = 1, page_size: int = 100) -> dict:
    try:
        r = httpx.get(f"{API_BASE}/events", params={"page": page, "page_size": page_size}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "events": []}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_anomalies() -> dict:
    try:
        r = httpx.get(f"{API_BASE}/anomalies", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "anomalies": []}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_occupancy() -> dict:
    try:
        r = httpx.get(f"{API_BASE}/metrics/occupancy", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "zones": []}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_heatmap() -> dict:
    try:
        r = httpx.get(f"{API_BASE}/metrics/heatmap", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "cells": []}


@st.cache_data(ttl=5)
def check_api_health() -> dict:
    try:
        r = httpx.get(f"{API_BASE}/health", timeout=5)
        return r.json()
    except Exception as e:
        return {"status": "unhealthy", "database": False}


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🛍️ **Store Intelligence**")
    st.markdown("*AI Store Intelligence System*")
    st.divider()

    health = check_api_health()
    api_status = health.get("status", "unknown")
    db_status = health.get("database", False)

    status_color = "🟢" if api_status == "healthy" else "🔴"
    st.markdown(f"{status_color} **API:** {api_status.capitalize()}")
    st.markdown(f"{'🟢' if db_status else '🔴'} **Database:** {'Connected' if db_status else 'Disconnected'}")

    st.divider()
    st.markdown("### 🎛️ Controls")

    auto_refresh = st.toggle("Auto Refresh", value=False)
    refresh_interval = st.slider("Refresh interval (s)", 10, 120, REFRESH_INTERVAL)

    if st.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if st.button("🌱 Seed Data", use_container_width=True):
        with st.spinner("Seeding..."):
            try:
                r = httpx.post(f"{API_BASE}/pipeline/seed?n_visitors=50", timeout=30)
                if r.status_code == 200:
                    st.success("✅ Data seeded!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Error: {r.text}")
            except Exception as e:
                st.error(f"Failed: {e}")

    st.divider()
    st.markdown(f"**Last updated:** {datetime.now().strftime('%H:%M:%S')}")
    st.markdown(f"**API:** `{API_BASE}`")


# ── Main Header ───────────────────────────────────────────────────────────────

st.markdown(
    "<p class='header-gradient'>🛍️ Store Intelligence Dashboard</p>",
    unsafe_allow_html=True,
)
st.markdown("Real-time retail analytics powered by YOLOv8 + ByteTrack")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Overview",
    "🔀 Funnel",
    "🗺️ Heatmap",
    "📋 Events",
    "⚠️ Anomalies",
])


# ── Tab 1: Overview ───────────────────────────────────────────────────────────
with tab1:
    metrics_data = fetch_metrics()

    if "error" in metrics_data:
        st.error(f"API Error: {metrics_data['error']}")
        st.info("💡 Make sure the API is running at `" + API_BASE + "` and the database is seeded.")
    else:
        # KPI metrics row
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "👥 Total Entries",
                f"{metrics_data.get('total_entries', 0):,}",
                help="Total customer entries today",
            )
        with col2:
            st.metric(
                "🔑 Unique Visitors",
                f"{metrics_data.get('unique_visitors', 0):,}",
                help="Deduplicated visitor count",
            )
        with col3:
            dwell = metrics_data.get("avg_dwell_seconds", 0)
            dwell_min = round(dwell / 60, 1)
            st.metric(
                "⏱️ Avg Dwell",
                f"{dwell_min} min",
                help="Average time in store",
            )
        with col4:
            conv = metrics_data.get("conversion_rate", 0)
            st.metric(
                "💰 Conversion",
                f"{conv:.1%}",
                help="Visitors who reached checkout",
            )

        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("🏃 Active Now", metrics_data.get("active_sessions", 0))
        with col6:
            st.metric("🔁 Re-entries", metrics_data.get("reentry_count", 0))
        with col7:
            st.metric("👨‍👩‍👦 Group Entries", metrics_data.get("group_entry_count", 0))
        with col8:
            anom = metrics_data.get("anomaly_count", 0)
            st.metric("⚠️ Anomalies", anom, delta=None if anom == 0 else f"{anom} active")

        st.divider()

        # Occupancy chart
        st.markdown("### 🏪 Zone Occupancy")
        occ_data = fetch_occupancy()
        if occ_data.get("zones"):
            occ_df = pd.DataFrame(occ_data["zones"])
            fig = go.Figure()
            colors = ["#7c3aed", "#a78bfa", "#c4b5fd", "#ddd6fe", "#ede9fe", "#f5f3ff"]
            for i, row in occ_df.iterrows():
                pct = row.get("utilization_pct", 0)
                color = colors[min(i, len(colors) - 1)]
                fig.add_trace(go.Bar(
                    name=row["name"],
                    x=[row["name"]],
                    y=[row["current_count"]],
                    marker_color=color,
                    text=f"{row['current_count']}/{row['capacity']} ({pct}%)",
                    textposition="outside",
                ))

            fig.update_layout(
                title="Current Zone Occupancy",
                showlegend=False,
                plot_bgcolor="#0f1117",
                paper_bgcolor="#0f1117",
                font_color="#e2e8f0",
                yaxis_title="People Count",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No occupancy data available. Try seeding the database.")


# ── Tab 2: Funnel ─────────────────────────────────────────────────────────────
with tab2:
    st.markdown("### 🔀 Visitor Journey Funnel")
    st.caption("Session-based funnel — each visitor counted once per stage")

    funnel_data = fetch_funnel()
    if "error" in funnel_data or not funnel_data.get("stages"):
        st.warning("No funnel data available. Seed the database to populate.")
    else:
        stages = funnel_data["stages"]
        df_funnel = pd.DataFrame(stages)

        # Plotly funnel chart
        fig = go.Figure(go.Funnel(
            y=df_funnel["stage"].tolist(),
            x=df_funnel["count"].tolist(),
            textinfo="value+percent initial",
            marker=dict(
                color=["#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe"],
                line=dict(width=2, color="#1e293b"),
            ),
            connector=dict(line=dict(color="#334155", width=2)),
        ))
        fig.update_layout(
            title=f"Visitor Funnel | Conversion Rate: {funnel_data.get('conversion_rate', 0):.1%}",
            plot_bgcolor="#0f1117",
            paper_bgcolor="#0f1117",
            font_color="#e2e8f0",
            height=450,
        )
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 Conversion Rate", f"{funnel_data.get('conversion_rate', 0):.1%}")
        with col2:
            st.metric("🗺️ Avg Zones / Visit", f"{funnel_data.get('avg_stages_per_visitor', 0):.1f}")


# ── Tab 3: Heatmap ────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### 🗺️ Store Zone Heatmap")
    st.caption("Visit frequency and dwell time per zone")

    heatmap_data = fetch_heatmap()
    if "error" in heatmap_data or not heatmap_data.get("cells"):
        st.warning("No heatmap data. Seed the database first.")
    else:
        cells = heatmap_data["cells"]
        df_heat = pd.DataFrame(cells)

        fig = go.Figure()

        # Store layout background
        fig.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1,
                      fillcolor="#1a1f2e", line=dict(color="#334155", width=2))

        # Add zone rectangles
        zone_bounds = {
            "ENTRY_MAIN":  (0.0, 0.8, 1.0, 1.0),
            "AISLE_A":     (0.0, 0.5, 0.5, 0.8),
            "AISLE_B":     (0.5, 0.5, 1.0, 0.8),
            "BEAUTY_BAR":  (0.2, 0.2, 0.8, 0.5),
            "CHECKOUT":    (0.0, 0.0, 1.0, 0.2),
            "EXIT_MAIN":   (0.0, 0.85, 1.0, 1.0),
        }

        for cell in cells:
            zid = cell["zone_id"]
            heat = cell["heat_value"]
            if zid in zone_bounds:
                x0, y0, x1, y1 = zone_bounds[zid]
                r = int(124 + heat * 131)
                g = int(58 + (1 - heat) * 139)
                b = int(237 - heat * 200)
                color = f"rgba({r},{g},{b},{0.3 + heat * 0.5})"
                fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                              fillcolor=color, line=dict(color="#7c3aed", width=1))
                fig.add_annotation(
                    x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                    text=f"<b>{cell['name']}</b><br>{cell['visit_count']} visits",
                    showarrow=False, font=dict(color="white", size=10),
                )

        fig.update_layout(
            title="Store Layout Heatmap — Visit Frequency",
            xaxis=dict(showticklabels=False, showgrid=False, range=[0, 1]),
            yaxis=dict(showticklabels=False, showgrid=False, range=[0, 1]),
            plot_bgcolor="#0f1117",
            paper_bgcolor="#0f1117",
            font_color="#e2e8f0",
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            df_heat[["zone_id", "name", "visit_count", "avg_dwell", "heat_value"]].rename(
                columns={
                    "zone_id": "Zone ID",
                    "name": "Zone Name",
                    "visit_count": "Visits",
                    "avg_dwell": "Avg Dwell (s)",
                    "heat_value": "Heat Score",
                }
            ),
            use_container_width=True,
        )


# ── Tab 4: Events ─────────────────────────────────────────────────────────────
with tab4:
    st.markdown("### 📋 Event Log")

    col1, col2 = st.columns(2)
    with col1:
        event_type_filter = st.selectbox(
            "Filter by type",
            ["All", "entry", "exit", "zone_enter", "zone_exit", "reentry", "group_entry", "anomaly"],
        )
    with col2:
        page_size = st.selectbox("Events per page", [25, 50, 100, 200], index=1)

    event_type = None if event_type_filter == "All" else event_type_filter
    events_data = fetch_events(page=1, page_size=page_size)

    if "error" in events_data:
        st.error(f"Error fetching events: {events_data['error']}")
    else:
        events_list = events_data.get("events", [])
        total = events_data.get("total", 0)
        st.caption(f"Showing {len(events_list)} of {total:,} total events")

        if events_list:
            df_events = pd.DataFrame(events_list)
            cols_to_show = [c for c in ["timestamp", "event_type", "track_id", "zone_id", "camera_id", "confidence"] if c in df_events.columns]
            df_display = df_events[cols_to_show].copy()
            if "confidence" in df_display.columns:
                df_display["confidence"] = df_display["confidence"].apply(lambda x: f"{x:.2f}" if x else "-")

            def color_event(val):
                colors = {
                    "entry": "color: #34d399",
                    "exit": "color: #f87171",
                    "reentry": "color: #fbbf24",
                    "group_entry": "color: #60a5fa",
                    "anomaly": "color: #f472b6",
                    "zone_enter": "color: #a78bfa",
                    "zone_exit": "color: #94a3b8",
                }
                return colors.get(val, "")

            st.dataframe(df_display, use_container_width=True, height=500)

            # Event type distribution
            type_counts = df_events["event_type"].value_counts().reset_index()
            type_counts.columns = ["event_type", "count"]
            fig = px.pie(
                type_counts,
                values="count",
                names="event_type",
                title="Event Distribution",
                color_discrete_sequence=px.colors.sequential.Purples_r,
            )
            fig.update_layout(
                plot_bgcolor="#0f1117", paper_bgcolor="#0f1117", font_color="#e2e8f0"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No events yet. Click 'Seed Data' in the sidebar.")


# ── Tab 5: Anomalies ──────────────────────────────────────────────────────────
with tab5:
    st.markdown("### ⚠️ Anomaly Detection")

    anomalies_data = fetch_anomalies()
    anomalies_list = anomalies_data.get("anomalies", [])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Anomalies", anomalies_data.get("total", 0))
    with col2:
        st.metric("Active", anomalies_data.get("active_count", 0))
    with col3:
        if anomalies_list:
            high_count = sum(1 for a in anomalies_list if a.get("severity") in ("high", "critical"))
            st.metric("High/Critical", high_count)
        else:
            st.metric("High/Critical", 0)

    if anomalies_list:
        df_anom = pd.DataFrame(anomalies_list)
        cols = [c for c in ["detected_at", "anomaly_type", "severity", "zone_id", "track_id", "description"] if c in df_anom.columns]

        severity_colors = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

        for _, row in df_anom[cols].head(20).iterrows():
            sev = row.get("severity", "medium")
            icon = severity_colors.get(sev, "⚪")
            with st.expander(f"{icon} {row.get('anomaly_type', 'Unknown')} — {row.get('zone_id', 'N/A')}"):
                st.markdown(f"**Severity:** {sev.upper()}")
                st.markdown(f"**Zone:** {row.get('zone_id', 'N/A')}")
                st.markdown(f"**Track:** {row.get('track_id', 'N/A')}")
                st.markdown(f"**Description:** {row.get('description', 'N/A')}")
                st.markdown(f"**Detected:** {row.get('detected_at', 'N/A')}")
    else:
        st.success("✅ No anomalies detected. Store operations nominal.")

    st.divider()
    st.markdown("#### Anomaly Rules")
    st.markdown("""
    | Type | Trigger | Severity |
    |------|---------|---------|
    | Overcrowding | Zone > 90% capacity for > 60s | High |
    | Loitering | Person at entry/exit > 120s | Medium |
    | Long Dwell | Person at checkout > 300s | Medium |
    | Tailgating | ≥2 persons entering within 1.5s | Low |
    | Group Entry | ≥3 persons entering within 2s | Low |
    """)


# ── Auto refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_interval)
    st.cache_data.clear()
    st.rerun()
