# ui/tabs_resources.py
import pandas as pd, streamlit as st
import plotly.express as px

def render_tab(scenario_data):
    st.subheader("🏥 자원 분포 및 효율성 분석")
    if not scenario_data:
        st.warning("⚠️ 시나리오 데이터를 불러올 수 없습니다.")
        return

    c1, c2 = st.columns([2,1])
    with c1:
        st.markdown("**📊 병원별 자원 분포**")
        hospitals = scenario_data.get("hospitals")
        distances = scenario_data.get("distances")
        if isinstance(hospitals, pd.DataFrame) and isinstance(distances, pd.DataFrame):
            df = hospitals.copy()
            if len(distances) >= len(hospitals):
                df["거리"] = distances["distance"][:len(hospitals)]
            fig = px.scatter(df, x=("거리" if "거리" in df.columns else df.index),
                             y="병상수", color="종별코드", size="병상수", hover_data=["요양기관명"],
                             title="병원별 거리-병상수 분포",
                             labels={"거리":"거리(km)","병상수":"병상 수","종별코드":"병원등급"})
            st.plotly_chart(fig, use_container_width=True)

            tier = df.groupby("종별코드").agg({"병상수":["count","sum","mean"], "거리":"mean" if "거리" in df.columns else "size"}).round(1)
            tier.columns = ["병원수","총병상수","평균병상수","평균거리"]
            tier.index = ["상급종합병원","일반병원"]
            st.dataframe(tier, use_container_width=True)

    with c2:
        st.markdown("**📈 자원 효율성 지표**")
        amb = scenario_data.get("ambulances")
        uav = scenario_data.get("uavs")
        if isinstance(amb, pd.DataFrame):
            st.metric("총 구급차 수", len(amb))
            if "init_distance" in amb:
                st.metric("평균 출동거리", f"{amb['init_distance'].mean():.1f}km")
                st.plotly_chart(px.histogram(amb, x="init_distance", nbins=10, title="구급차 출동거리 분포"), use_container_width=True)
        if isinstance(uav, pd.DataFrame):
            st.metric("총 UAV 수", len(uav))
            if "init_distance" in uav:
                st.metric("UAV 평균 출동거리", f"{uav['init_distance'].mean():.1f}km")
