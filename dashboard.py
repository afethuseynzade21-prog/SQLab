"""
SQLab — SQL Agent Monitor Dashboard
"""
import time
import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="SQL Agent Monitor", page_icon="⚡", layout="wide")

API = st.sidebar.text_input("API URL", value="http://localhost:8000/api/v1")

if st.sidebar.button("Yenilə"):
    st.cache_data.clear()
    st.rerun()

st.markdown("## ⚡ SQL Agent Monitor")
st.caption(f"Son yeniləmə: {datetime.now().strftime('%H:%M:%S')}")
st.divider()

def get(path, params=None):
    try:
        r = httpx.get(f"{API}{path}", params=params, timeout=5)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

tab1, tab2, tab3, tab4 = st.tabs(["Ümumi baxış", "Sorğular", "Qiymətləndirmə", "Təsdiq"])

with tab1:
    stats = get("/queries/stats") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cəmi sorğu", stats.get("total", 0))
    c2.metric("Uğur faizi", f"{stats.get('success_rate_pct', 0)}%")
    c3.metric("Ort. icra vaxtı", f"{stats.get('avg_execution_ms', 0)} ms")
    c4.metric("Bloklanmış", stats.get("blocked", 0))
    c5.metric("Gözləyən", stats.get("pending_approval", 0))

    st.divider()
    if stats:
        labels = ["Uğurlu", "Xətalı", "Bloklandı", "Gözləyir"]
        values = [stats.get("success", 0), stats.get("error", 0),
                  stats.get("blocked", 0), stats.get("pending_approval", 0)]
        colors = ["#3ecf8e", "#e05c5c", "#e8a020", "#4ea8de"]
        fig = go.Figure(go.Pie(
            labels=labels, values=values, hole=0.6,
            marker=dict(colors=colors),
            textfont=dict(size=12),
        ))
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          margin=dict(t=10, b=10, l=10, r=10), height=280)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    status_filter = st.selectbox("Status", ["Hamısı", "SUCCESS", "ERROR", "BLOCKED", "pending_approval"])
    
    params = {"size": 50}
    if status_filter != "Hamısı":
        params["status"] = status_filter
    
    q_list = get("/queries", params) or []
    
    if q_list:
        df = pd.DataFrame([{
            "Sual": (q.get("nl_input") or "")[:60],
            "Status": q.get("status", ""),
            "ms": q.get("execution_time_ms", ""),
            "Judge": q.get("llm_judge_score", ""),
            "Tarix": (q.get("executed_at") or "")[:16],
        } for q in q_list])
        st.dataframe(df, use_container_width=True, hide_index=True, height=400)
    else:
        st.info("Sorğu tapılmadı.")

with tab3:
    eval_list = get("/evaluations", {"size": 50}) or []
    
    if eval_list:
        scores = [e.get("llm_judge_score") for e in eval_list if e.get("llm_judge_score")]
        if scores:
            col1, col2, col3 = st.columns(3)
            col1.metric("Ortalama bal", f"{sum(scores)/len(scores):.1f}/10")
            col2.metric("Ən yüksək", max(scores))
            col3.metric("Sorğu sayı", len(scores))
            
            fig2 = go.Figure(go.Histogram(x=scores, nbinsx=10,
                marker_color="#3ecf8e"))
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="LLM hakim balı", yaxis_title="Say",
                margin=dict(t=10, b=10, l=10, r=10), height=250)
            st.plotly_chart(fig2, use_container_width=True)
        
        df_e = pd.DataFrame([{
            "Sual": (e.get("notes") or "")[:60],
            "Judge bal": e.get("llm_judge_score", ""),
            "Model": e.get("judge_model", ""),
            "Tarix": (e.get("evaluated_at") or "")[:10],
        } for e in eval_list])
        st.dataframe(df_e, use_container_width=True, hide_index=True)
    else:
        st.info("Qiymətləndirmə məlumatı tapılmadı.")

with tab4:
    if st.button("Yenilə", key="ref_appr"):
        st.rerun()
    
    pending = get("/approvals/pending") or []
    
    if not pending:
        st.success("Gözləyən sorğu yoxdur.")
    else:
        st.warning(f"{len(pending)} sorğu gözləyir.")
        for i, item in enumerate(pending):
            qid = item.get("id") or item.get("query_log_id", "")
            nl = item.get("nl_input", "")
            sql = item.get("sql_query") or item.get("generated_sql") or "SQL yoxdur"
            
            with st.expander(f"#{i+1} — {nl[:50]}"):
                st.code(sql, language="sql")
                col_a, col_r = st.columns(2)
                if col_a.button("Təsdiqlə", key=f"a_{qid}_{i}", type="primary"):
                    try:
                        r = httpx.post(f"{API}/approvals/{qid}/approve", timeout=10)
                        if r.status_code == 200:
                            st.success("Təsdiqləndi!")
                            time.sleep(1)
                            st.rerun()
                    except:
                        st.error("Xəta baş verdi.")
                if col_r.button("Rədd et", key=f"r_{qid}_{i}"):
                    try:
                        r = httpx.post(f"{API}/approvals/{qid}/reject",
                                       json={"reason": "Rədd edildi"}, timeout=10)
                        if r.status_code == 200:
                            st.warning("Rədd edildi.")
                            time.sleep(1)
                            st.rerun()
                    except:
                        st.error("Xəta baş verdi.")
