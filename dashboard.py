"""
SQL Agent Monitoring Dashboard — Streamlit
Real FastAPI backend-ə qoşulur, canlı məlumat göstərir.

İşə salmaq:
    streamlit run dashboard.py --server.port 8501
    # http://localhost:8501
"""

import time
import streamlit as st
import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(
    page_title="SQL Agent Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .block-container { padding-top: 1.2rem; }
  .metric-card {
    background: #111418; border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px; padding: 16px;
  }
  .stMetric { background: #111418 !important; }
  div[data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace; }
  .approval-card {
    background: #0d1117; border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px; padding: 18px; margin-bottom: 14px;
  }
</style>
""", unsafe_allow_html=True)

API_BASE = st.sidebar.text_input("API URL", value="http://localhost:8000/api/v1")
AUTO_REFRESH = st.sidebar.checkbox("Avtomatik yenilə (30s)", value=False)

if AUTO_REFRESH:
    placeholder = st.sidebar.empty()
    for remaining in range(30, 0, -1):
        placeholder.caption(f"Yenilənəcək: {remaining}s")
        time.sleep(1)
    placeholder.empty()
    st.cache_data.clear()
    st.rerun()


@st.cache_data(ttl=30)
def fetch(path: str, api_base: str, params: dict | None = None) -> dict | list | None:
    try:
        r = httpx.get(f"{api_base}{path}", params=params, timeout=5.0, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.sidebar.error(f"API xətası: {e}")
        return None


@st.cache_data(ttl=30)
def query_stats(api_base: str, session_id: str | None = None) -> dict:
    params = {"session_id": session_id} if session_id else {}
    return fetch("/queries/stats", api_base, params) or {}


@st.cache_data(ttl=30)
def recent_queries(api_base: str, size: int = 20) -> list:
    return fetch(f"/queries?size={size}", api_base) or []


@st.cache_data(ttl=30)
def security_logs(api_base: str, size: int = 20) -> list:
    return fetch(f"/security?size={size}", api_base) or []


@st.cache_data(ttl=30)
def agents(api_base: str) -> list:
    return fetch("/agents", api_base) or []


@st.cache_data(ttl=30)
def evaluations(api_base: str, size: int = 50) -> list:
    return fetch(f"/evaluations?size={size}", api_base) or []


def pending_approvals(api_base: str) -> list:
    """Gözləyən sorğuları gətirir — cache olmadan, həmişə təzə."""
    try:
        r = httpx.get(f"{api_base}/approvals/pending", timeout=5.0, follow_redirects=True)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception:
        return []


def approve_query(api_base: str, query_log_id: str) -> bool:
    try:
        r = httpx.post(
            f"{api_base}/approvals/{query_log_id}/approve",
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception:
        return False


def reject_query(api_base: str, query_log_id: str, reason: str = "İnsan tərəfindən rədd edildi") -> bool:
    try:
        r = httpx.post(
            f"{api_base}/approvals/{query_log_id}/reject",
            json={"reason": reason},
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception:
        return False


if st.sidebar.button("🔄 İndi yenilə"):
    st.cache_data.clear()
    st.rerun()

col_t, col_ts = st.columns([3, 1])
with col_t:
    st.markdown("## ⚡ SQL Agent Monitor")
with col_ts:
    st.markdown(
        f"<div style='text-align:right;color:#666;font-family:monospace;font-size:12px;padding-top:12px'>"
        f"{datetime.now().strftime('%H:%M:%S')}</div>",
        unsafe_allow_html=True,
    )

st.divider()

# Gözləyən sorğu sayını badge kimi göstər
pending = pending_approvals(API_BASE)
pending_count = len(pending)
tab_approval_label = f"✋ Təsdiq ({pending_count})" if pending_count > 0 else "✋ Təsdiq"

tab_ov, tab_q, tab_approval, tab_sec, tab_eval = st.tabs([
    "📊 Ümumi baxış", "🔍 Sorğular", tab_approval_label, "🔒 Təhlükəsizlik", "📈 Qiymətləndirmə"
])

# ════════════════════════════════════════════════════════════════
#  TAB 1: Ümumi baxış
# ════════════════════════════════════════════════════════════════
with tab_ov:
    stats = query_stats(API_BASE)

    prev_success = st.session_state.get("prev_success_rate", None)
    cur_success = stats.get("success_rate_pct")
    if cur_success is not None:
        delta_val = (
            f"{cur_success - prev_success:+.1f}% əvvəlki sessiyaya nəzərən"
            if prev_success is not None
            else None
        )
        st.session_state["prev_success_rate"] = cur_success
    else:
        delta_val = None

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Cəmi sorğu",       stats.get("total", "—"))
    k2.metric("Uğur faizi",       f"{cur_success or '—'}%", delta=delta_val)
    k3.metric("Ort. icra vaxtı",  f"{stats.get('avg_execution_ms', '—')} ms")
    k4.metric("Bloklanmış",       stats.get("blocked", "—"))
    k5.metric("Gözləyən",         pending_count, delta=f"+{pending_count}" if pending_count > 0 else None)

    st.divider()
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Agent performansı**")
        agent_list = agents(API_BASE)
        if agent_list:
            df_agents = pd.DataFrame([
                {
                    "Agent":     a.get("name", "—"),
                    "LLM":       a.get("llm_model", "—"),
                    "Framework": a.get("framework", "—"),
                    "Read-only": "✓" if a.get("read_only") else "✗",
                    "Yaradılıb": a.get("created_at", "")[:10],
                }
                for a in agent_list
            ])
            st.dataframe(df_agents, use_container_width=True, hide_index=True)
        else:
            st.info("Agent məlumatı tapılmadı.")

    with col_right:
        st.markdown("**Sorğu status paylaması**")
        if stats:
            labels = ["Uğurlu", "Xətalı", "Bloklandı", "Gözləyir"]
            values = [
                stats.get("success", 0),
                stats.get("error", 0),
                stats.get("blocked", 0),
                stats.get("pending_approval", 0),
            ]
            colors = ["#3ecf8e", "#e05c5c", "#e8a020", "#4ea8de"]
            fig = go.Figure(go.Pie(
                labels=labels, values=values,
                hole=0.6,
                marker=dict(colors=colors, line=dict(color="#0b0e12", width=2)),
                textfont=dict(family="JetBrains Mono", size=11),
            ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(font=dict(size=11)),
                margin=dict(t=10, b=10, l=10, r=10),
                height=260,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Statistika məlumatı tapılmadı.")

# ════════════════════════════════════════════════════════════════
#  TAB 2: Sorğular
# ════════════════════════════════════════════════════════════════
with tab_q:
    st.markdown("**Son sorğular**")

    status_filter = st.selectbox(
        "Status filtri",
        ["Hamısı", "success", "error", "blocked", "pending_approval"],
        label_visibility="collapsed",
    )

    q_list = recent_queries(API_BASE, size=50)
    if q_list:
        if status_filter != "Hamısı":
            q_list = [q for q in q_list if q.get("status") == status_filter]

        df_q = pd.DataFrame([
            {
                "NL sorğu":   q.get("nl_input", "")[:60],
                "Status":     q.get("status", ""),
                "Exec ms":    q.get("execution_time_ms", "—"),
                "Sətir sayı": q.get("rows_returned", "—"),
                "SQL":        (q.get("sql_query") or "")[:80],
                "Tarix":      q.get("executed_at", "")[:19],
            }
            for q in q_list
        ])

        def status_color(val: str) -> str:
            colors = {
                "success":          "background-color:#1a5c3e; color:#3ecf8e",
                "error":            "background-color:#5c1f1f; color:#e05c5c",
                "blocked":          "background-color:#7a5210; color:#e8a020",
                "pending_approval": "background-color:#1a3a55; color:#4ea8de",
            }
            return colors.get(val, "")

        st.dataframe(
            df_q.style.applymap(status_color, subset=["Status"]),
            use_container_width=True,
            hide_index=True,
            height=400,
        )
    else:
        st.info("Sorğu tapılmadı.")

# ════════════════════════════════════════════════════════════════
#  TAB 3: Human-in-the-loop Təsdiq
# ════════════════════════════════════════════════════════════════
with tab_approval:
    st.markdown("### ✋ Gözləyən sorğular")
    st.caption("Aşağıdakı sorğular icra olunmadan sizin təsdiqinizi gözləyir.")

    if st.button("🔄 Yenilə", key="refresh_approvals"):
        st.rerun()

    if not pending:
        st.success("✓ Gözləyən sorğu yoxdur.")
    else:
        st.warning(f"**{pending_count}** sorğu gözləyir.")
        st.divider()

        for i, item in enumerate(pending):
            qid = item.get("id") or item.get("query_log_id", "")
            nl  = item.get("nl_input", "—")
            sql = item.get("sql_query") or item.get("generated_sql") or "SQL mövcud deyil"
            session = item.get("session_id", "—")
            created = (item.get("created_at") or item.get("executed_at") or "")[:19]

            with st.container():
                st.markdown(f"""
<div class="approval-card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <span style="color:#4ea8de;font-family:monospace;font-size:12px">#{i+1} · Session: {session[:20]}...</span>
    <span style="color:#666;font-size:11px">{created}</span>
  </div>
  <div style="color:#e2e8f0;margin-bottom:10px"><strong>Sual:</strong> {nl}</div>
  <div style="background:#050810;border-left:3px solid #3b82f6;padding:10px;border-radius:4px;font-family:monospace;font-size:12px;color:#60a5fa;white-space:pre-wrap">{sql}</div>
</div>
""", unsafe_allow_html=True)

                col_a, col_r, col_reason = st.columns([1, 1, 3])

                with col_a:
                    if st.button("✅ Təsdiqlə", key=f"approve_{qid}_{i}", type="primary"):
                        if approve_query(API_BASE, qid):
                            st.success(f"Sorğu təsdiqləndi!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Xəta baş verdi. API işləyirmi?")

                with col_r:
                    if st.button("❌ Rədd et", key=f"reject_{qid}_{i}"):
                        reason = st.session_state.get(f"reason_{qid}", "İnsan tərəfindən rədd edildi")
                        if reject_query(API_BASE, qid, reason):
                            st.warning("Sorğu rədd edildi.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Xəta baş verdi.")

                with col_reason:
                    st.text_input(
                        "Rədd səbəbi (ixtiyari)",
                        key=f"reason_{qid}",
                        placeholder="Məsələn: Şübhəli sorğu...",
                        label_visibility="collapsed",
                    )

                st.divider()

# ════════════════════════════════════════════════════════════════
#  TAB 4: Təhlükəsizlik
# ════════════════════════════════════════════════════════════════
with tab_sec:
    col_sl, col_sr = st.columns([2, 1])

    with col_sl:
        st.markdown("**Təhlükəsizlik hadisələri**")
        min_risk = st.slider("Minimum risk balı", 0.0, 1.0, 0.0, 0.05)
        sec_list = security_logs(API_BASE, size=30)
        if sec_list:
            filtered = [s for s in sec_list if (s.get("risk_score") or 0) >= min_risk]
            df_sec = pd.DataFrame([
                {
                    "Hadisə növü": s.get("event_type", "").replace("_", " "),
                    "Risk balı":   s.get("risk_score", "—"),
                    "Hərəkət":     s.get("action_taken", "—"),
                    "Model":       s.get("detection_model", "—"),
                    "Giriş":       (s.get("input_text") or "")[:50],
                    "Vaxt":        s.get("created_at", "")[:19],
                }
                for s in filtered
            ])
            st.dataframe(df_sec, use_container_width=True, hide_index=True, height=380)
        else:
            st.info("Təhlükəsizlik hadisəsi tapılmadı.")

    with col_sr:
        st.markdown("**Hadisə növü paylaması**")
        if sec_list:
            from collections import Counter
            counts = Counter(s.get("event_type", "other") for s in sec_list)
            fig2 = px.bar(
                x=list(counts.values()),
                y=[k.replace("_", " ") for k in counts.keys()],
                orientation="h",
                color_discrete_sequence=["#e8a020"],
            )
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, color="#3d3c38"),
                yaxis=dict(color="#7a7870"),
                margin=dict(t=10, b=10, l=10, r=10),
                height=280,
                showlegend=False,
                font=dict(family="JetBrains Mono", size=11),
            )
            st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════════════════════
#  TAB 5: Qiymətləndirmə
# ════════════════════════════════════════════════════════════════
with tab_eval:
    eval_list = evaluations(API_BASE, size=50)

    e1, e2 = st.columns(2)

    with e1:
        st.markdown("**Semantic oxşarlıq paylaması**")
        if eval_list:
            sims = [e.get("semantic_similarity") for e in eval_list if e.get("semantic_similarity")]
            if sims:
                fig3 = px.histogram(
                    x=sims, nbins=20,
                    color_discrete_sequence=["#3ecf8e"],
                    labels={"x": "Semantic oxşarlıq", "y": "Sayı"},
                )
                fig3.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(color="#3d3c38"),
                    yaxis=dict(color="#3d3c38"),
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=250,
                    font=dict(family="JetBrains Mono", size=11),
                )
                st.plotly_chart(fig3, use_container_width=True)

    with e2:
        st.markdown("**LLM hakim balı paylaması**")
        if eval_list:
            judges = [e.get("llm_judge_score") for e in eval_list if e.get("llm_judge_score")]
            if judges:
                fig4 = px.histogram(
                    x=judges, nbins=20,
                    color_discrete_sequence=["#4ea8de"],
                    labels={"x": "LLM hakim balı", "y": "Sayı"},
                )
                fig4.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(color="#3d3c38"),
                    yaxis=dict(color="#3d3c38"),
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=250,
                    font=dict(family="JetBrains Mono", size=11),
                )
                st.plotly_chart(fig4, use_container_width=True)

    st.divider()
    st.markdown("**Qiymətləndirmə nəticələri**")
    if eval_list:
        df_eval = pd.DataFrame([
            {
                "Funksional": (
                    "✓" if e.get("functional_correct") else
                    ("✗" if e.get("functional_correct") is False else "—")
                ),
                "Semantic":    round(e.get("semantic_similarity") or 0, 3),
                "LLM hakim":  round(e.get("llm_judge_score") or 0, 3),
                "Hakim model": e.get("judge_model", "—"),
                "Qeyd":        (e.get("notes") or "")[:60],
                "Tarix":       e.get("evaluated_at", "")[:10],
            }
            for e in eval_list
        ])
        st.dataframe(df_eval, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("Qiymətləndirmə məlumatı tapılmadı.")

st.divider()
st.markdown(
    "<div style='text-align:center;color:#3d3c38;font-family:monospace;font-size:11px'>"
    "SQL Agent Monitor · "
    f"Son yeniləmə: {datetime.now().strftime('%H:%M:%S')}"
    "</div>",
    unsafe_allow_html=True,
)
