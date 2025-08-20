# ui/tabs_analysis.py
import numpy as np, pandas as pd, streamlit as st
import plotly.express as px, plotly.graph_objects as go
from parsers import load_simulation_results

def render_tab(selected_location, coord_str):
    st.subheader("📈 시뮬레이션 결과 상세 분석")
    data = load_simulation_results(coord_str)
    if not data or not data["rules"]:
        st.info("📊 분석할 시뮬레이션 결과가 없습니다.")
        return

    st.success(f"📊 {len(data['rules'])}개 규칙 분석")
    st.info(f"📅 결과 파일: {data['file_path'].split(os.sep)[-1] if 'file_path' in data else ''}")

    df = pd.DataFrame({
        "규칙": data["rules"],
        "생존율": data["survival_rates"],
        "대응시간": data["response_times"] if data["response_times"] else [0]*len(data["rules"]),
        "PDR": data["pdr_rates"] if data["pdr_rates"] else [0]*len(data["rules"]),
    })
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("🏆 최고 성과 규칙")
        best = df.iloc[df["생존율"].idxmax()]
        st.markdown(f"**{best['규칙']}**  \n생존율 **{best['생존율']:.3f}**, 대응시간 **{best['대응시간']:.1f}분**, PDR **{best['PDR']:.3f}**")

        st.subheader("📊 상위 10개 규칙")
        top10 = df.nlargest(10, "생존율")[["규칙","생존율","대응시간","PDR"]].round(3)
        st.dataframe(top10, hide_index=True, use_container_width=True)

    with c2:
        st.subheader("📈 성과 분포")
        st.plotly_chart(px.histogram(df, x="생존율", nbins=15, title="생존율 분포"), use_container_width=True)
        if df["대응시간"].sum() > 0:
            st.plotly_chart(px.scatter(df, x="대응시간", y="생존율", hover_data=["규칙"],
                                       title="생존율 vs 대응시간", color="생존율"), use_container_width=True)

    st.subheader("📋 전체 결과 요약")
    disp = df.sort_values("생존율", ascending=False).reset_index(drop=True)
    disp.insert(0, "순위", range(1, len(disp)+1))
    st.dataframe(disp.round(3), hide_index=True, use_container_width=True)

    if len(df) > 0:
        top15 = df.nlargest(15, "생존율")
        fig = go.Figure()
        fig.add_trace(go.Bar(name="생존율", x=top15["규칙"], y=top15["생존율"]))
        if top15["대응시간"].sum() > 0:
            fig.add_trace(go.Scatter(name="대응시간", x=top15["규칙"], y=top15["대응시간"], yaxis="y2", mode="lines+markers"))
        fig.update_layout(title="상위 15개 규칙 성과 비교", xaxis_tickangle=-45,
                          yaxis=dict(title="생존율"), yaxis2=dict(title="대응시간(분)", overlaying="y", side="right"))
        st.plotly_chart(fig, use_container_width=True)
